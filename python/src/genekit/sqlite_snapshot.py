"""Copy a live SQLite database and trust the copy only once the copy itself verifies.

The decision this module encodes: a backup of a live SQLite database is trusted only after the
**copy** passes ``PRAGMA integrity_check``. Checking the source before copying proves nothing about
the file that will actually be relied on — the copy can be truncated, written to the wrong place,
taken from the wrong file, or carry the source's damage verbatim — so verification always runs on
the file that was produced, and a copy that fails it is never left under a name that looks good.

Why not a file copy: in WAL mode, committed pages live in the ``-wal`` file until a checkpoint moves
them into the main database file. Copying the main file alone (``shutil.copy`` and friends) produces
a backup that opens cleanly, passes ``integrity_check``, and is silently missing every recent write.
The copy has to go through SQLite, which knows where the committed pages are.

The standard library already does the copying, and this module wraps it rather than replacing it.
SQL ``VACUUM INTO`` writes a transactionally consistent copy of the database even while a WAL writer
is active, rebuilding and compacting the file as it goes; it needs SQLite 3.27 or newer.
:meth:`sqlite3.Connection.backup` drives SQLite's online-backup API and copies pages exactly as they
are. Neither one verifies what it wrote, and both have sharp edges every hand-rolled call site has
had to rediscover. What is added is the policy around them:

* the source is opened **read-only**, through a ``mode=ro`` URI. A plain :func:`sqlite3.connect` on
  a missing path *creates* an empty database, which then verifies ``ok`` and is archived as a
  perfectly healthy backup of nothing; a read-only open refuses instead. The path is URI-encoded
  from :meth:`pathlib.Path.as_uri`, so characters such as ``#``, ``%`` and space reach SQLite intact
  rather than being read as URI syntax.
* the destination is **reserved exclusively** (``O_CREAT | O_EXCL``) before anything is copied, so
  neither method ever overwrites an existing file — ``backup()`` on its own silently would — and two
  runs racing on the same timestamped name fail loudly instead of interleaving.
* the destination path is **bound as a parameter** (``VACUUM INTO ?``), never quoted into the SQL by
  hand, so an apostrophe in a directory name is not an injection or a syntax error.
* every copy ends in **rollback-journal mode**, so it is one self-contained file. A page-exact
  backup of a WAL source keeps the WAL flag in its header, and every later open of it would grow
  ``-wal`` and ``-shm`` sidecars that a retention script or an archive step does not know to carry
  along.
* verification runs **on the copy**, and a copy that fails is removed — or, when asked, set aside as
  ``<name>.failed`` — so stamp-based retention ("keep the newest N") can never mistake it for a good
  backup.

Choosing ``method``. ``"vacuum"`` (the default) rebuilds the file and drops free pages, which gives
the smallest copy. Because it rebuilds indexes from table content, it can also *launder* index
corruption: a damaged index in the source becomes a clean one in the copy. ``"backup"`` copies pages
verbatim, so a damaged source yields a copy that fails verification — which is exactly what a
forensic or pre-migration evidence copy wants to learn. ``"backup"`` is also the only option where
the linked SQLite predates 3.27.

Limits worth knowing. Nothing is ``fsync``-ed: a snapshot proves the copy was consistent when it was
read back, not that it survived a power loss. ``integrity_check`` says nothing about foreign keys;
pass ``check_foreign_keys=True`` to also run ``PRAGMA foreign_key_check``. A zero-byte source is a
valid empty SQLite database, and its snapshot verifies. The destination is reserved as an empty
file before the copy starts, and a hard kill (power loss, ``SIGKILL``) mid-copy leaves that partial
file behind, so a retention scan should ignore zero-byte files. Compression, retention, restore and
logging are the caller's: the module takes no logger, and it raises rather than returning status
tuples.

Test seam. :func:`verified_snapshot` calls :func:`verify_sqlite` through its module-global name on
every call, and that is a supported contract: a consumer's tests may substitute
``genekit.sqlite_snapshot.verify_sqlite`` (for example with ``monkeypatch.setattr``) to force the
verification-failure path, since building a genuinely corrupt live database inside an application's
test harness is impractical. The substitute should raise :exc:`SqliteVerificationError`; the copy is
then removed or set aside exactly as for a real failure. Likewise the SQLite version is read from
:data:`sqlite3.sqlite_version_info` at call time, never cached at import.
"""

from __future__ import annotations

import contextlib
import errno
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Literal

from genekit.tz import to_tz

__all__ = [
    "STAMP_FORMAT",
    "SqliteVerificationError",
    "stamped_snapshot",
    "verified_snapshot",
    "verify_sqlite",
]

STAMP_FORMAT: Final = "%Y%m%dT%H%M%SZ"
"""``strptime`` format of the UTC stamp in :func:`stamped_snapshot` names; sorts chronologically."""

_VACUUM_INTO_MIN_SQLITE: Final = (3, 27, 0)
_SIDECAR_SUFFIXES: Final = ("-journal", "-wal", "-shm")
_FAILED_SUFFIX: Final = ".failed"


class SqliteVerificationError(RuntimeError):
    """A database file failed verification or could not be read as a database at all.

    Raised by :func:`verify_sqlite` when ``PRAGMA integrity_check`` reports anything but ``ok``,
    when the opt-in ``PRAGMA foreign_key_check`` reports a violation, or when SQLite cannot read
    the file. :func:`verified_snapshot` re-raises it against the snapshot's path, after the failed
    copy has been removed or set aside. It subclasses :exc:`RuntimeError`, so a caller that treats
    any backup failure as fatal needs no import to catch it.

    Args:
        path: The file that was checked.
        detail: What the check reported.
        kept: Where a failed snapshot was set aside, if it was.

    Attributes:
        path: The file that was checked.
        detail: What the check reported: the ``integrity_check`` rows, a ``foreign_key_check``
            violation summary, or the error SQLite raised while opening or reading the file.
        kept: Where a failed snapshot was set aside (``keep_failed=True``); ``None`` when it was
            removed or the check was not of a snapshot.

    Example:
        >>> from pathlib import Path
        >>> from genekit.sqlite_snapshot import SqliteVerificationError
        >>> error = SqliteVerificationError(Path("app.db"), "integrity_check: [('page 3',)]")
        >>> isinstance(error, RuntimeError), error.kept is None
        (True, True)
        >>> print(error)
        app.db failed verification: integrity_check: [('page 3',)]
    """

    def __init__(self, path: Path, detail: str, *, kept: Path | None = None) -> None:
        self.path = path
        self.detail = detail
        self.kept = kept
        message = f"{path} failed verification: {detail}"
        if kept is not None:
            message += f" (kept at {kept})"
        super().__init__(message)


def verify_sqlite(path: Path, *, check_foreign_keys: bool = False) -> None:
    """Check that ``path`` is a readable, structurally sound SQLite database.

    The file is opened read-only through a ``mode=ro`` URI, so a missing file is never created and
    the file is never written. The open is a normal one — not ``immutable`` — so it is safe on a
    live WAL database: it takes the usual shared locks and reads committed ``-wal`` content, rather
    than assuming nothing else is writing.

    Args:
        path: The database file to check. Must be an existing regular file.
        check_foreign_keys: Also run ``PRAGMA foreign_key_check`` and fail on any violation.
            ``False`` by default, because ``integrity_check`` does not look at foreign keys and
            many schemas declare them without ever enforcing them.

    Returns:
        ``None`` when ``PRAGMA integrity_check`` returns exactly one ``ok`` row (and, when asked,
        ``foreign_key_check`` returns none).

    Raises:
        FileNotFoundError: If ``path`` is not an existing regular file (missing, or a directory).
        SqliteVerificationError: If ``integrity_check`` reports a problem, if
            ``check_foreign_keys=True`` and a violation is found, or if SQLite cannot open or read
            the file — for example because it is not a database at all. The connection is closed
            before this propagates.

    Example:
        >>> import contextlib, sqlite3, tempfile
        >>> from pathlib import Path
        >>> from genekit.sqlite_snapshot import SqliteVerificationError, verify_sqlite
        >>> with tempfile.TemporaryDirectory() as folder:
        ...     good = Path(folder) / "good.db"
        ...     with contextlib.closing(sqlite3.connect(good)) as connection:
        ...         _ = connection.execute("CREATE TABLE notes(body TEXT)")
        ...     print(verify_sqlite(good))
        ...     junk = Path(folder) / "junk.db"
        ...     _ = junk.write_bytes(b"this is not a database " * 64)
        ...     try:
        ...         verify_sqlite(junk)
        ...     except SqliteVerificationError as exc:
        ...         print(type(exc).__name__, exc.detail.startswith("could not read"))
        None
        SqliteVerificationError True
    """
    if not path.is_file():
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(path))
    try:
        with contextlib.closing(sqlite3.connect(_readonly_uri(path), uri=True)) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
            if rows != [("ok",)]:
                raise SqliteVerificationError(path, f"integrity_check: {rows!r}")
            if check_foreign_keys:
                violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    summary = f"{len(violations)} violation(s), first {violations[0]!r}"
                    raise SqliteVerificationError(path, f"foreign_key_check: {summary}")
    except sqlite3.Error as exc:
        raise SqliteVerificationError(path, f"could not read the database: {exc}") from exc


def verified_snapshot(
    source: Path,
    destination: Path,
    *,
    method: Literal["vacuum", "backup"] = "vacuum",
    check_foreign_keys: bool = False,
    keep_failed: bool = False,
    mkdir: bool = False,
) -> Path:
    """Copy the SQLite database ``source`` to ``destination`` and verify the copy.

    The copy is consistent even while another connection is writing to ``source`` in WAL mode: it
    contains every committed transaction up to the moment the copy started and nothing that was
    uncommitted. ``source`` itself is opened read-only and never modified.

    Args:
        source: The database to copy. Must be an existing regular file; it may be live, in WAL or
            rollback mode.
        destination: Where the copy is written. It must not exist — not even as an empty file —
            and is reserved exclusively before anything is copied, so this call never overwrites
            and two concurrent calls with the same destination cannot both succeed.
        method: ``"vacuum"`` (default) copies through ``VACUUM INTO``: compacted, smallest, but
            index corruption in the source can come out clean. ``"backup"`` copies pages verbatim
            through :meth:`sqlite3.Connection.backup`, so source damage shows up in verification;
            it is also the only method on SQLite older than 3.27. Either way the copy is a single
            rollback-journal file.
        check_foreign_keys: Also fail verification on any ``PRAGMA foreign_key_check`` violation.
        keep_failed: When the copy fails verification, rename it to ``<name>.failed`` instead of
            deleting it, so it can be inspected; an earlier ``.failed`` file is replaced. It never
            stays under ``destination``'s own name: if the rename is impossible the copy is
            removed and ``kept`` is ``None``.
        mkdir: When ``True``, create ``destination.parent`` with ``parents=True, exist_ok=True``
            first. ``False`` by default: a missing backup directory is usually a caller bug.

    Returns:
        ``destination``, which now holds a copy that passed :func:`verify_sqlite`.

    Raises:
        ValueError: If ``method`` is not ``"vacuum"`` or ``"backup"``.
        FileNotFoundError: If ``source`` is not an existing regular file, or if
            ``destination.parent`` does not exist and ``mkdir=False``.
        FileExistsError: If ``destination`` already exists. It is left untouched.
        RuntimeError: If ``method="vacuum"`` and the linked SQLite is older than 3.27; the message
            points at ``method='backup'``.
        sqlite3.Error: If the copy itself fails — for example because ``source`` is not a
            database. ``destination`` is removed first.
        SqliteVerificationError: If the copy fails verification. It is removed, or with
            ``keep_failed=True`` set aside and named in the exception's ``kept``; ``path`` is
            ``destination``.

        Nothing is created by any refusal raised before the destination is reserved, and anything
        else that escapes mid-copy or mid-check (a :exc:`KeyboardInterrupt`, say) propagates
        unchanged after the partial copy and any SQLite sidecar beside it are removed.

    Example:
        >>> import contextlib, sqlite3, tempfile
        >>> from pathlib import Path
        >>> from genekit.sqlite_snapshot import verified_snapshot
        >>> with tempfile.TemporaryDirectory() as folder:
        ...     source = Path(folder) / "live.db"
        ...     with contextlib.closing(sqlite3.connect(source)) as writer:
        ...         _ = writer.execute("PRAGMA journal_mode=WAL")
        ...         _ = writer.execute("CREATE TABLE notes(body TEXT)")
        ...         _ = writer.execute("INSERT INTO notes VALUES ('committed')")
        ...         writer.commit()
        ...         for method in ("vacuum", "backup"):
        ...             target = Path(folder) / f"{method}.db"
        ...             copy = verified_snapshot(source, target, method=method)
        ...             with contextlib.closing(sqlite3.connect(copy)) as reader:
        ...                 print(method, reader.execute("SELECT body FROM notes").fetchall())
        ...         try:
        ...             verified_snapshot(source, Path(folder) / "vacuum.db")
        ...         except FileExistsError:
        ...             print("refused: destination exists")
        vacuum [('committed',)]
        backup [('committed',)]
        refused: destination exists
    """
    if method not in ("vacuum", "backup"):
        raise ValueError(f"method must be 'vacuum' or 'backup', not {method!r}")
    if not source.is_file():
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(source))
    if method == "vacuum" and sqlite3.sqlite_version_info < _VACUUM_INTO_MIN_SQLITE:
        raise RuntimeError(
            f"VACUUM INTO needs SQLite 3.27+; this interpreter links {sqlite3.sqlite_version}. "
            "Pass method='backup'."
        )
    if mkdir:
        destination.parent.mkdir(parents=True, exist_ok=True)
    _reserve(destination)  # FileExistsError / FileNotFoundError propagate; nothing to clean up yet
    try:
        _copy(source, destination, method)
    except BaseException:
        _discard(destination)
        raise
    try:
        verify_sqlite(destination, check_foreign_keys=check_foreign_keys)
    except SqliteVerificationError as exc:
        if keep_failed:
            kept = _set_aside(destination)
        else:
            _discard(destination)
            kept = None
        raise SqliteVerificationError(destination, exc.detail, kept=kept) from exc
    except BaseException:
        _discard(destination)
        raise
    return destination


def stamped_snapshot(
    source: Path,
    out_dir: Path,
    *,
    prefix: str | None = None,
    suffix: str | None = None,
    now: datetime | None = None,
    method: Literal["vacuum", "backup"] = "vacuum",
    check_foreign_keys: bool = False,
    keep_failed: bool = False,
) -> Path:
    """Write a verified snapshot of ``source`` into ``out_dir`` under a UTC timestamped name.

    The file is ``out_dir / "<prefix>-<stamp><suffix>"``, or ``"<stamp><suffix>"`` when ``prefix``
    is ``""``. The stamp is :data:`STAMP_FORMAT` in UTC (``20260102T030405Z``), always 16
    characters, so names with the same prefix and suffix sort in chronological order and parse back
    with :meth:`datetime.datetime.strptime`. Copying and verification are
    :func:`verified_snapshot`'s, with ``mkdir=True``.

    Args:
        source: The database to copy; see :func:`verified_snapshot`.
        out_dir: Directory the snapshot goes in. Created, with parents, once the arguments have
            passed validation; a refused call does not create it.
        prefix: Name before the stamp. Defaults to ``source.stem``; ``""`` drops it and its
            hyphen. Must not contain a path separator.
        suffix: Name after the stamp, extension included. Defaults to ``source.suffix``. Must not
            contain a path separator.
        now: The instant to stamp. Defaults to the current time. A naive value is taken to be UTC
            (the :func:`genekit.tz.to_tz` policy); an aware one is converted to UTC. The stamp has
            one-second resolution, so two snapshots of the same names in the same second collide
            and the second raises :exc:`FileExistsError` — by design, rather than overwriting.
        method: ``"vacuum"`` or ``"backup"``; see :func:`verified_snapshot`.
        check_foreign_keys: See :func:`verified_snapshot`.
        keep_failed: See :func:`verified_snapshot`.

    Returns:
        The path of the snapshot, which passed :func:`verify_sqlite`.

    Raises:
        ValueError: If ``prefix`` or ``suffix`` contains a forward slash, a backslash, or the
            platform's path separator. Nothing is created.
        OverflowError: If ``now`` is an aware value within a UTC offset of the ends of
            :class:`~datetime.datetime`'s range, so it has no UTC equivalent.
        FileExistsError: If a snapshot with the same name already exists, as above.
        Everything :func:`verified_snapshot` raises, under the same cleanup guarantees.

    Example:
        >>> import contextlib, sqlite3, tempfile
        >>> from datetime import datetime, timezone
        >>> from pathlib import Path
        >>> from genekit.sqlite_snapshot import STAMP_FORMAT, stamped_snapshot
        >>> moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        >>> with tempfile.TemporaryDirectory() as folder:
        ...     source = Path(folder) / "state.sqlite"
        ...     with contextlib.closing(sqlite3.connect(source)) as connection:
        ...         _ = connection.execute("CREATE TABLE notes(body TEXT)")
        ...     backups = Path(folder) / "backups"
        ...     named = stamped_snapshot(source, backups, prefix="app", suffix=".db", now=moment)
        ...     print(named.name)
        ...     default = stamped_snapshot(source, backups, now=moment)
        ...     print(default.name)
        ...     print(datetime.strptime(named.stem.split("-")[1], STAMP_FORMAT))
        app-20260102T030405Z.db
        state-20260102T030405Z.sqlite
        2026-01-02 03:04:05
    """
    resolved_prefix = source.stem if prefix is None else prefix
    resolved_suffix = source.suffix if suffix is None else suffix
    moment = datetime.now(timezone.utc) if now is None else now
    name = _stamped_name(resolved_prefix, resolved_suffix, moment)
    # mkdir=True rather than creating out_dir here, so a call verified_snapshot refuses up front
    # (missing source, unknown method, old SQLite) leaves no empty directory behind.
    return verified_snapshot(
        source,
        out_dir / name,
        method=method,
        check_foreign_keys=check_foreign_keys,
        keep_failed=keep_failed,
        mkdir=True,
    )


def _stamped_name(prefix: str, suffix: str, moment: datetime) -> str:
    """``<prefix>-<stamp><suffix>``; fixed-width stamp, parseable with :data:`STAMP_FORMAT`."""
    for part in (prefix, suffix):
        if any(sep and sep in part for sep in ("/", "\\", os.sep, os.altsep)):
            raise ValueError(f"name parts must not contain a path separator: {part!r}")
    utc = to_tz(moment, timezone.utc)
    # Built by hand, not strftime: %Y is not zero-padded below year 1000 on every platform, and a
    # fixed width is what makes names sort chronologically. strptime(STAMP_FORMAT) still parses it.
    stamp = (
        f"{utc.year:04d}{utc.month:02d}{utc.day:02d}"
        f"T{utc.hour:02d}{utc.minute:02d}{utc.second:02d}Z"
    )
    return f"{prefix}-{stamp}{suffix}" if prefix else f"{stamp}{suffix}"


def _readonly_uri(path: Path) -> str:
    """Read-only SQLite URI; ``as_uri`` percent-encodes ``#``, ``%``, spaces and non-ASCII."""
    return f"{path.resolve().as_uri()}?mode=ro"


def _reserve(destination: Path) -> None:
    """Create ``destination`` empty with O_EXCL. VACUUM INTO accepts an empty target; backup too."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    os.close(os.open(destination, flags, 0o666))


def _copy(source: Path, destination: Path, method: Literal["vacuum", "backup"]) -> None:
    """Copy ``source`` into the reserved, empty ``destination``; every connection closed on exit."""
    with contextlib.closing(sqlite3.connect(_readonly_uri(source), uri=True)) as src:
        if method == "vacuum":
            src.execute("VACUUM INTO ?", (str(destination.resolve()),))
            return
        with contextlib.closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
            # A backup of a WAL source keeps the WAL header; any later open would then grow
            # -wal/-shm sidecars beside the copy. Rollback mode keeps the snapshot one file.
            dst.execute("PRAGMA journal_mode=DELETE")


def _discard(destination: Path) -> None:
    """Best-effort removal of ``destination`` and any sidecar SQLite left beside it."""
    sidecars = (destination.with_name(destination.name + s) for s in _SIDECAR_SUFFIXES)
    for path in (destination, *sidecars):
        with contextlib.suppress(OSError):
            path.unlink()


def _set_aside(destination: Path) -> Path | None:
    """Rename a failed copy to ``<name>.failed`` (replacing an earlier one); ``None`` if it cannot.

    A copy that cannot be renamed is removed instead: it must never stay under its good name.
    """
    failed = destination.with_name(destination.name + _FAILED_SUFFIX)
    try:
        destination.replace(failed)
    except OSError:
        _discard(destination)
        return None
    return failed
