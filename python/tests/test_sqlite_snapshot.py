"""Tests for genekit.sqlite_snapshot.

Boundary Matrix
===============

Dimension A — copy fidelity ([m] = parametrized over method "vacuum" and "backup")
------------------------------------------------------------------
| Cell | Case                                            | Expected                            |
|------|--------------------------------------------------|--------------------------------------|
| A1   | rollback db with rows [m]                        | returns destination; rows equal     |
| A2   | dirs named "o'brien #1 100% Zürich" [m]          | succeeds; rows equal                |
| A3   | zero-byte source [m]                             | succeeds; copy verifies             |
| A4   | hypothesis rows: None/int64/float/text/bytes     | rows equal (method sampled)         |

Dimension B — live WAL source and source safety
------------------------------------------------------------------
| Cell | Case                                                   | Expected                        |
|------|---------------------------------------------------------|----------------------------------|
| B1   | committed rows live only in -wal (autocheckpoint=0) [m] | copy contains them              |
| B2   | writer holds BEGIN IMMEDIATE + uncommitted insert [m]   | copy lacks it; call not blocked |
| B3   | thread commits 2-row txns; 5 snapshots [m]              | each verifies; counts even and  |
|      |                                                         | non-decreasing                  |
| B4   | WAL source with writer open [m]                         | copy header 01 01; dir = copy   |
| B5   | rollback source [m]                                     | source bytes and dir unchanged  |

Dimension C — refusals before the destination is reserved
------------------------------------------------------------------
| Cell | Case                                         | Expected                                  |
|------|-----------------------------------------------|--------------------------------------------|
| C1   | missing source, mkdir=True                   | FileNotFoundError; nothing created        |
| C2   | source is a directory                        | FileNotFoundError                         |
| C3   | method="copy"                                | ValueError; nothing created               |
| C4   | sqlite_version_info patched to (3, 26, 0)    | vacuum: RuntimeError naming               |
|      |                                              | method='backup', nothing created;         |
|      |                                              | backup: succeeds                          |
| C5   | stamped_snapshot with a missing source       | FileNotFoundError; out_dir not created    |

Dimension D — destination
------------------------------------------------------------------
| Cell | Case                                         | Expected                             |
|------|-----------------------------------------------|---------------------------------------|
| D1   | destination holds b"keep" / is empty [m]     | FileExistsError; content unchanged   |
| D2   | nested missing parent, mkdir=False           | FileNotFoundError; parent not made   |
| D3   | nested missing parent, mkdir=True            | parent created; snapshot written     |

Dimension E — failure paths clean up
------------------------------------------------------------------
| Cell | Case                                              | Expected                           |
|------|----------------------------------------------------|-------------------------------------|
| E1   | junk (non-SQLite) source [m]                      | sqlite3.DatabaseError; dir empty   |
| E2   | corrupt index source, backup                      | SqliteVerificationError, kept None,|
|      |                                                   | dir empty                          |
| E3   | same, keep_failed=True                            | kept == <name>.failed, exists;     |
|      |                                                   | destination absent                 |
| E4   | verify_sqlite substituted to raise (seam) [m]     | re-raised with path=destination;   |
|      |                                                   | dir empty                          |
| E5   | _copy writes file + sidecar, then KeyboardInterrupt| propagates; dir empty             |
| E6   | verify_sqlite substituted to KeyboardInterrupt    | propagates; dir empty              |

Dimension F — verify_sqlite and the error type
------------------------------------------------------------------
| Cell | Case                                            | Expected                            |
|------|--------------------------------------------------|--------------------------------------|
| F1   | dangling FK, foreign_keys OFF [m]               | default passes; opt-in raises with  |
|      |                                                 | detail "foreign_key_check..."       |
| F2   | live WAL db, writer open mid-transaction        | returns None                        |
| F3   | missing path / directory / junk file            | FileNotFoundError /                 |
|      |                                                 | SqliteVerificationError "could not" |
| F4   | any verification failure                        | RuntimeError; path, detail, kept    |

Dimension G — stamped_snapshot naming
------------------------------------------------------------------
| Cell | Case                                           | Expected                             |
|------|-------------------------------------------------|---------------------------------------|
| G1   | source app.db, aware UTC now, nested out_dir   | app-20260102T030405Z.db; dir created |
| G2   | prefix="", suffix="-rev.db"                    | 20260102T030405Z-rev.db              |
| G3   | naive now                                      | stamped as UTC wall clock            |
| G4   | now at UTC+05:30                               | converted to UTC wall clock          |
| G5   | "/" or "\\" in prefix or suffix                | ValueError; nothing created          |
| G6   | two threads, same now, same out_dir            | exactly one FileExistsError; one file|

Dimension H — stamp properties (hypothesis, years 1..9999, tz None/UTC/+05:30/-08:00)
------------------------------------------------------------------
| Cell | Case                          | Expected                                           |
|------|--------------------------------|-----------------------------------------------------|
| H1   | any instant                   | strptime(stamp, STAMP_FORMAT) == UTC, whole seconds |
| H2   | any two instants              | name order == instant order (whole seconds)        |
| H3   | any instant                   | len(name) == len(prefix) + 1 + 16 + len(suffix)    |

Dimension I — documentation
------------------------------------------------------------------
| Cell | Case                                    | Expected                       |
|------|------------------------------------------|---------------------------------|
| I1   | doctest.testmod(genekit.sqlite_snapshot) | failed == 0, attempted > 0     |

Every sqlite3 connection is closed through contextlib.closing (Windows handles block unlink and
rename; newer Pythons warn on unclosed connections, and the suite turns warnings into errors).
Writer threads open and close their own connection inside the thread.
"""

from __future__ import annotations

import contextlib
import doctest
import sqlite3
import tempfile
import threading
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import genekit.sqlite_snapshot as sqlite_snapshot
from genekit.sqlite_snapshot import (
    STAMP_FORMAT,
    SqliteVerificationError,
    _stamped_name,
    stamped_snapshot,
    verified_snapshot,
    verify_sqlite,
)

Method = Literal["vacuum", "backup"]
METHODS: tuple[Method, ...] = ("vacuum", "backup")
MOMENT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
ROLLBACK_HEADER = b"\x01\x01"
WAL_HEADER = b"\x02\x02"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(path: Path, rows: Sequence[object], *, wal: bool = False) -> None:
    """Create ``t(id INTEGER PRIMARY KEY, v)`` (``v`` untyped) holding ``rows``, then close."""
    with contextlib.closing(sqlite3.connect(path)) as connection:
        if wal:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v)")
        connection.executemany("INSERT INTO t(v) VALUES (?)", [(row,) for row in rows])
        connection.commit()


def _rows(path: Path) -> list[object]:
    """Values of ``t.v`` in insertion order, read through a read-only open."""
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as connection:
        return [row[0] for row in connection.execute("SELECT v FROM t ORDER BY id")]


def _header_journal_bytes(path: Path) -> bytes:
    """File-format read/write version bytes: 01 01 = rollback journal, 02 02 = WAL."""
    return path.read_bytes()[18:20]


def _listing(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


def _corrupt_index(path: Path) -> None:
    """Build a rollback-mode db whose index ``t_x`` is damaged but whose table is intact.

    The index root page is an interior b-tree page; with ~2000 short rows it holds only a few
    cells, packed at the end of the page, so bytes in the middle are free space and overwriting
    them changes nothing ``integrity_check`` looks at. Everything after the 12-byte interior
    page header (the cell pointer array and the cells) is overwritten with 0xFF instead, which
    points every cell out of range.
    """
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE t(x TEXT)")
        connection.execute("CREATE INDEX t_x ON t(x)")
        connection.executemany("INSERT INTO t VALUES (?)", [(f"row-{n:06d}",) for n in range(2000)])
        connection.commit()
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        root = connection.execute(
            "SELECT rootpage FROM sqlite_master WHERE type = 'index' AND name = 't_x'"
        ).fetchone()[0]
    data = bytearray(path.read_bytes())
    start = (root - 1) * page_size
    assert data[start] == 0x02, "index root page is not an interior index b-tree page"
    header = 12
    data[start + header : start + page_size] = b"\xff" * (page_size - header)
    path.write_bytes(bytes(data))
    assert _header_journal_bytes(path) == ROLLBACK_HEADER
    with pytest.raises(SqliteVerificationError):
        verify_sqlite(path)


# ---------------------------------------------------------------------------
# Dimension A — copy fidelity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS)
def test_verified_snapshot_copies_rows(tmp_path: Path, method: Method) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["one", 2, 3.5, b"\x00four", None])
    destination = tmp_path / "copy.db"
    result = verified_snapshot(source, destination, method=method)
    assert result == destination
    assert _rows(destination) == _rows(source)


@pytest.mark.parametrize("method", METHODS)
def test_unusual_path_characters(tmp_path: Path, method: Method) -> None:
    odd = "o'brien #1 100% Zürich"
    source_dir = tmp_path / "src" / odd
    source_dir.mkdir(parents=True)
    source = source_dir / f"{odd}.db"
    _make_db(source, ["a", "b"])
    destination = tmp_path / "dst" / odd / f"{odd}.db"
    verified_snapshot(source, destination, method=method, mkdir=True)
    assert _rows(destination) == ["a", "b"]


@pytest.mark.parametrize("method", METHODS)
def test_zero_byte_source_snapshots_as_empty_db(tmp_path: Path, method: Method) -> None:
    source = tmp_path / "empty.db"
    source.touch()
    destination = tmp_path / "copy.db"
    verified_snapshot(source, destination, method=method)
    assert verify_sqlite(destination) is None


_cell_values = st.one_of(
    st.none(),
    st.integers(min_value=-(2**63), max_value=2**63 - 1),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(),
    st.binary(),
)


@given(rows=st.lists(_cell_values, max_size=20), method=st.sampled_from(METHODS))
@settings(max_examples=25, deadline=None)
def test_hypothesis_rows_round_trip(rows: list[object], method: Method) -> None:
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "src.db"
        _make_db(source, rows)
        copy = verified_snapshot(source, Path(folder) / "copy.db", method=method)
        assert _rows(copy) == _rows(source)


# ---------------------------------------------------------------------------
# Dimension B — live WAL source and source safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS)
def test_snapshot_includes_committed_wal_only_rows(tmp_path: Path, method: Method) -> None:
    source = tmp_path / "live.db"
    _make_db(source, ["base"], wal=True)
    with contextlib.closing(sqlite3.connect(source)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.executemany("INSERT INTO t(v) VALUES (?)", [("wal-only",)] * 3)
        writer.commit()
        wal = source.with_name(source.name + "-wal")
        assert wal.stat().st_size > 0, "precondition: the new rows live in -wal"
        copy = verified_snapshot(source, tmp_path / "out" / "copy.db", method=method, mkdir=True)
        assert _rows(copy) == ["base", "wal-only", "wal-only", "wal-only"]


@pytest.mark.parametrize("method", METHODS)
def test_snapshot_excludes_uncommitted_transaction(tmp_path: Path, method: Method) -> None:
    source = tmp_path / "live.db"
    _make_db(source, ["committed"], wal=True)
    with contextlib.closing(sqlite3.connect(source, isolation_level=None)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO t(v) VALUES ('uncommitted')")
        # The writer never releases its lock while the snapshot runs, so a snapshot that
        # blocked on it would end in "database is locked", not return.
        copy = verified_snapshot(source, tmp_path / "out" / "copy.db", method=method, mkdir=True)
        writer.execute("ROLLBACK")
    assert _rows(copy) == ["committed"]


@pytest.mark.parametrize("method", METHODS)
def test_snapshot_beside_busy_writer_is_consistent(tmp_path: Path, method: Method) -> None:
    source = tmp_path / "live.db"
    _make_db(source, [], wal=True)
    stop = threading.Event()
    first_commit = threading.Event()
    errors: list[BaseException] = []

    def _write() -> None:
        try:
            with contextlib.closing(sqlite3.connect(source, timeout=10)) as writer:
                while not stop.is_set():
                    with writer:  # one transaction per pair; commits on exit
                        writer.execute("INSERT INTO t(v) VALUES ('a')")
                        writer.execute("INSERT INTO t(v) VALUES ('b')")
                    first_commit.set()
        except BaseException as exc:  # noqa: BLE001 - collected for the assertion below
            errors.append(exc)
            first_commit.set()

    thread = threading.Thread(target=_write)
    thread.start()
    counts: list[int] = []
    try:
        assert first_commit.wait(timeout=10)
        for n in range(5):
            copy = verified_snapshot(
                source, tmp_path / "snaps" / f"{n}.db", method=method, mkdir=True
            )
            verify_sqlite(copy)
            counts.append(len(_rows(copy)))
    finally:
        stop.set()
        thread.join(timeout=30)
    assert not thread.is_alive()
    assert not errors
    assert all(count % 2 == 0 for count in counts), counts
    assert counts == sorted(counts)
    assert counts[0] > 0


@pytest.mark.parametrize("method", METHODS)
def test_copy_is_single_rollback_file(tmp_path: Path, method: Method) -> None:
    source = tmp_path / "live.db"
    _make_db(source, ["x"], wal=True)
    out = tmp_path / "out"
    with contextlib.closing(sqlite3.connect(source)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO t(v) VALUES ('y')")
        writer.commit()
        assert _header_journal_bytes(source) == WAL_HEADER
        copy = verified_snapshot(source, out / "copy.db", method=method, mkdir=True)
    assert _header_journal_bytes(copy) == ROLLBACK_HEADER
    assert _listing(out) == ["copy.db"]
    assert _rows(copy) == ["x", "y"]
    assert _listing(out) == ["copy.db"], "reading the copy grew sidecar files"


@pytest.mark.parametrize("method", METHODS)
def test_source_is_never_modified(tmp_path: Path, method: Method) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    source = source_dir / "app.db"
    _make_db(source, ["a", "b", "c"])
    before_bytes = source.read_bytes()
    before_listing = _listing(source_dir)
    verified_snapshot(source, tmp_path / "copy.db", method=method)
    assert source.read_bytes() == before_bytes
    assert _listing(source_dir) == before_listing


# ---------------------------------------------------------------------------
# Dimension C — refusals before the destination is reserved
# ---------------------------------------------------------------------------


def test_missing_source_raises_and_creates_nothing(tmp_path: Path) -> None:
    source = tmp_path / "missing.db"
    destination = tmp_path / "out" / "copy.db"
    with pytest.raises(FileNotFoundError):
        verified_snapshot(source, destination, mkdir=True)
    assert not source.exists()
    assert not destination.parent.exists()


def test_directory_source_raises(tmp_path: Path) -> None:
    source = tmp_path / "a-directory.db"
    source.mkdir()
    with pytest.raises(FileNotFoundError):
        verified_snapshot(source, tmp_path / "copy.db")
    assert _listing(tmp_path) == ["a-directory.db"]


def test_unknown_method_raises_value_error(tmp_path: Path) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    destination = tmp_path / "out" / "copy.db"
    with pytest.raises(ValueError, match="'copy'"):
        verified_snapshot(
            source,
            destination,
            method="copy",  # pyright: ignore[reportArgumentType]
            mkdir=True,
        )
    assert not destination.parent.exists()


def test_vacuum_on_old_sqlite_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 26, 0))
    vacuum_target = tmp_path / "vacuum" / "copy.db"
    with pytest.raises(RuntimeError, match="method='backup'") as excinfo:
        verified_snapshot(source, vacuum_target, method="vacuum", mkdir=True)
    assert type(excinfo.value) is RuntimeError
    assert not vacuum_target.parent.exists()
    backup_target = verified_snapshot(source, tmp_path / "backup.db", method="backup")
    assert _rows(backup_target) == ["a"]


def test_stamped_refusal_creates_no_out_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "backups"
    with pytest.raises(FileNotFoundError):
        stamped_snapshot(tmp_path / "missing.db", out_dir, now=MOMENT)
    assert not out_dir.exists()


# ---------------------------------------------------------------------------
# Dimension D — destination
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("existing", [b"keep", b""], ids=["non-empty", "empty"])
@pytest.mark.parametrize("method", METHODS)
def test_existing_destination_untouched(tmp_path: Path, method: Method, existing: bytes) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    destination = tmp_path / "copy.db"
    destination.write_bytes(existing)
    with pytest.raises(FileExistsError):
        verified_snapshot(source, destination, method=method)
    assert destination.read_bytes() == existing
    assert _listing(tmp_path) == ["app.db", "copy.db"]


def test_missing_parent_mkdir_false_raises(tmp_path: Path) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    destination = tmp_path / "a" / "b" / "copy.db"
    with pytest.raises(FileNotFoundError):
        verified_snapshot(source, destination)
    assert not (tmp_path / "a").exists()


def test_mkdir_true_creates_parent(tmp_path: Path) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    destination = tmp_path / "a" / "b" / "copy.db"
    assert verified_snapshot(source, destination, mkdir=True) == destination
    assert _rows(destination) == ["a"]


# ---------------------------------------------------------------------------
# Dimension E — failure paths clean up
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS)
def test_junk_source_raises_and_cleans_up(tmp_path: Path, method: Method) -> None:
    source = tmp_path / "junk.db"
    source.write_bytes(b"this is not a database " * 64)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(sqlite3.DatabaseError):
        verified_snapshot(source, out / "copy.db", method=method)
    assert _listing(out) == []


def test_corrupt_copy_removed_by_default(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.db"
    _corrupt_index(source)
    out = tmp_path / "out"
    out.mkdir()
    destination = out / "copy.db"
    with pytest.raises(SqliteVerificationError) as excinfo:
        verified_snapshot(source, destination, method="backup")
    assert excinfo.value.kept is None
    assert excinfo.value.path == destination
    assert _listing(out) == []


def test_corrupt_copy_kept_when_asked(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.db"
    _corrupt_index(source)
    out = tmp_path / "out"
    out.mkdir()
    destination = out / "copy.db"
    with pytest.raises(SqliteVerificationError) as excinfo:
        verified_snapshot(source, destination, method="backup", keep_failed=True)
    failed = destination.with_name(destination.name + ".failed")
    assert excinfo.value.kept == failed
    assert failed.is_file()
    assert not destination.exists()
    assert _listing(out) == ["copy.db.failed"]
    assert "kept at" in str(excinfo.value)


def test_unrenameable_failed_copy_is_removed_not_left_under_good_name(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.db"
    _corrupt_index(source)
    out = tmp_path / "out"
    out.mkdir()
    destination = out / "copy.db"
    (out / "copy.db.failed").mkdir()  # a directory in the way makes the set-aside rename fail
    with pytest.raises(SqliteVerificationError) as excinfo:
        verified_snapshot(source, destination, method="backup", keep_failed=True)
    assert excinfo.value.kept is None
    assert not destination.exists()
    assert _listing(out) == ["copy.db.failed"]


@pytest.mark.parametrize("method", METHODS)
def test_verification_failure_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: Method
) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    out = tmp_path / "out"
    out.mkdir()
    destination = out / "copy.db"

    def _always_fails(path: Path, *, check_foreign_keys: bool = False) -> None:
        raise SqliteVerificationError(path, "forced by the test seam")

    monkeypatch.setattr(sqlite_snapshot, "verify_sqlite", _always_fails)
    with pytest.raises(SqliteVerificationError) as excinfo:
        verified_snapshot(source, destination, method=method)
    assert excinfo.value.path == destination
    assert excinfo.value.detail == "forced by the test seam"
    assert excinfo.value.kept is None
    assert _listing(out) == []


def test_interrupt_mid_copy_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    out = tmp_path / "out"
    out.mkdir()

    def _write_then_interrupt(source: Path, destination: Path, method: Method) -> None:
        destination.write_bytes(b"partial copy")
        destination.with_name(destination.name + "-journal").write_bytes(b"sidecar")
        raise KeyboardInterrupt

    monkeypatch.setattr(sqlite_snapshot, "_copy", _write_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        verified_snapshot(source, out / "copy.db")
    assert _listing(out) == []


def test_interrupt_mid_verify_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    out = tmp_path / "out"
    out.mkdir()

    def _interrupt(path: Path, *, check_foreign_keys: bool = False) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(sqlite_snapshot, "verify_sqlite", _interrupt)
    with pytest.raises(KeyboardInterrupt):
        verified_snapshot(source, out / "copy.db", keep_failed=True)
    assert _listing(out) == []


# ---------------------------------------------------------------------------
# Dimension F — verify_sqlite and the error type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS)
def test_foreign_key_check_opt_in(tmp_path: Path, method: Method) -> None:
    source = tmp_path / "fk.db"
    with contextlib.closing(sqlite3.connect(source)) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE child(pid INTEGER REFERENCES parent(id))")
        connection.execute("INSERT INTO child VALUES (42)")
        connection.commit()
    default = verified_snapshot(source, tmp_path / "default.db", method=method)
    assert default.is_file()
    strict = tmp_path / "strict.db"
    with pytest.raises(SqliteVerificationError) as excinfo:
        verified_snapshot(source, strict, method=method, check_foreign_keys=True)
    assert excinfo.value.detail.startswith("foreign_key_check")
    assert not strict.exists()


def test_verify_sqlite_ok_on_live_wal_db(tmp_path: Path) -> None:
    source = tmp_path / "live.db"
    _make_db(source, ["a"], wal=True)
    with contextlib.closing(sqlite3.connect(source, isolation_level=None)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO t(v) VALUES ('committed')")
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO t(v) VALUES ('pending')")
        assert verify_sqlite(source) is None
        writer.execute("ROLLBACK")


def test_verify_sqlite_missing_and_junk(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify_sqlite(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()
    with pytest.raises(FileNotFoundError):
        verify_sqlite(tmp_path)
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a database " * 64)
    with pytest.raises(SqliteVerificationError) as excinfo:
        verify_sqlite(junk)
    assert excinfo.value.detail.startswith("could not read")


def test_error_is_runtime_error_with_attributes(tmp_path: Path) -> None:
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"\x00" * 100 + b"not sqlite" * 100)
    with pytest.raises(SqliteVerificationError) as excinfo:
        verify_sqlite(junk)
    error = excinfo.value
    assert isinstance(error, RuntimeError)
    assert error.path == junk
    assert error.detail
    assert error.kept is None
    assert str(junk) in str(error)
    assert error.detail in str(error)


# ---------------------------------------------------------------------------
# Dimension G — stamped_snapshot naming
# ---------------------------------------------------------------------------


def test_stamped_default_name(tmp_path: Path) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    out_dir = tmp_path / "backups" / "nested"
    result = stamped_snapshot(source, out_dir, now=MOMENT)
    assert result == out_dir / "app-20260102T030405Z.db"
    assert _listing(out_dir) == ["app-20260102T030405Z.db"]
    assert _rows(result) == ["a"]


def test_stamped_empty_prefix_and_explicit_suffix(tmp_path: Path) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    result = stamped_snapshot(source, tmp_path / "out", prefix="", suffix="-rev.db", now=MOMENT)
    assert result.name == "20260102T030405Z-rev.db"


def test_stamped_naive_now_is_utc(tmp_path: Path) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    result = stamped_snapshot(source, tmp_path / "out", now=datetime(2026, 1, 2, 3, 4, 5))
    assert result.name == "app-20260102T030405Z.db"


def test_stamped_aware_now_converted(tmp_path: Path) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    india = timezone(timedelta(hours=5, minutes=30))
    result = stamped_snapshot(
        source, tmp_path / "out", now=datetime(2026, 1, 2, 8, 34, 5, tzinfo=india)
    )
    assert result.name == "app-20260102T030405Z.db"


@pytest.mark.parametrize(
    ("prefix", "suffix"),
    [("a/b", None), ("a\\b", None), (None, "\\x"), (None, "/x.db")],
    ids=["slash-prefix", "backslash-prefix", "backslash-suffix", "slash-suffix"],
)
def test_stamped_rejects_separator_in_parts(
    tmp_path: Path, prefix: str | None, suffix: str | None
) -> None:
    source = tmp_path / "app.db"
    _make_db(source, ["a"])
    out_dir = tmp_path / "out"
    with pytest.raises(ValueError, match="path separator"):
        stamped_snapshot(source, out_dir, prefix=prefix, suffix=suffix, now=MOMENT)
    assert not out_dir.exists()
    assert _listing(tmp_path) == ["app.db"]


def test_same_second_collision_raises(tmp_path: Path) -> None:
    source = tmp_path / "app.db"
    _make_db(source, list(range(500)))
    out_dir = tmp_path / "out"
    barrier = threading.Barrier(2)
    results: list[Path] = []
    errors: list[BaseException] = []

    def _snapshot() -> None:
        try:
            barrier.wait(timeout=10)
            results.append(stamped_snapshot(source, out_dir, now=MOMENT))
        except BaseException as exc:  # noqa: BLE001 - collected for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_snapshot) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert len(results) == 1, errors
    assert len(errors) == 1
    assert isinstance(errors[0], FileExistsError)
    assert _listing(out_dir) == [results[0].name]
    assert _rows(results[0]) == list(range(500))


# ---------------------------------------------------------------------------
# Dimension H — stamp properties
# ---------------------------------------------------------------------------

_naive_datetimes = st.datetimes(min_value=datetime(1, 1, 2), max_value=datetime(9999, 12, 30))
_zones = st.sampled_from(
    [
        None,
        timezone.utc,
        timezone(timedelta(hours=5, minutes=30)),
        timezone(timedelta(hours=-8)),
    ]
)


@st.composite
def _instants(draw: st.DrawFn) -> datetime:
    return draw(_naive_datetimes).replace(tzinfo=draw(_zones))


def _utc_wall_clock(moment: datetime) -> datetime:
    """Naive UTC wall clock of ``moment`` (naive means UTC), truncated to whole seconds."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.replace(microsecond=0)


@given(moment=_instants())
@settings(max_examples=200)
def test_hypothesis_stamp_parses_back(moment: datetime) -> None:
    name = _stamped_name("p", ".db", moment)
    stamp = name[len("p-") : -len(".db")]
    assert datetime.strptime(stamp, STAMP_FORMAT) == _utc_wall_clock(moment)


@given(first=_instants(), second=_instants())
@settings(max_examples=200)
def test_hypothesis_stamp_orders_like_instants(first: datetime, second: datetime) -> None:
    first_name = _stamped_name("app", ".db", first)
    second_name = _stamped_name("app", ".db", second)
    first_utc, second_utc = _utc_wall_clock(first), _utc_wall_clock(second)
    assert (first_name < second_name) == (first_utc < second_utc)
    assert (first_name == second_name) == (first_utc == second_utc)


@given(moment=_instants())
@settings(max_examples=200)
def test_hypothesis_stamp_fixed_width(moment: datetime) -> None:
    prefix, suffix = "snapshot", ".sqlite"
    name = _stamped_name(prefix, suffix, moment)
    assert len(name) == len(prefix) + 1 + 16 + len(suffix)


# ---------------------------------------------------------------------------
# Dimension I — documentation
# ---------------------------------------------------------------------------


def test_docstring_examples_run() -> None:
    results = doctest.testmod(sqlite_snapshot)
    assert results.failed == 0
    assert results.attempted > 0
