"""Write a file so a reader never sees a half-written result.

The decision this module encodes: a file is *replaced*, never edited in place. The new contents are
written to a freshly created sibling temp file and then moved onto the destination in a single
rename, so every reader sees either the whole previous version or the whole new one, and a write
that dies partway through leaves behind neither a truncated destination nor a stray temp file. The
recurring defect it exists to prevent is the ordinary two-line version — ``open(path, "w")`` and
then ``write`` — which publishes the file *empty* the moment it opens it and fills it afterwards: a
reader, a backup, or a restart that lands in that window finds a zero-length or half-written file,
and the previous contents are already gone.

The standard library does the hard parts and this module does not reimplement them:
:func:`os.replace` (through :meth:`pathlib.Path.replace`) owns the atomic, overwriting rename — on
Windows plain :func:`os.rename` refuses an existing destination, which is what makes ``replace`` the
only portable choice — and :func:`tempfile.mkstemp` owns creating a temp file that cannot collide
with anything, opened ``O_EXCL`` so it can never adopt a file some other writer is already using.
What is added is the policy the stdlib has none of:

* the temp file is always a *uniquely named sibling* of the destination. Sibling, because
  ``replace`` is only atomic within one filesystem and a temp directory elsewhere silently degrades
  to a copy-then-delete. Uniquely named, because a fixed ``{name}.tmp`` or ``{name}.{pid}.tmp``
  suffix — the shape most hand-rolled call sites this module replaces had settled on — collides the
  moment two writers touch the same path: the second truncates the first's temp file and the two
  payloads interleave into the destination. On Windows the same fixed name also fails outright while
  any reader still holds the previous temp file open.
* the temp file is removed on *any* failure, not only on :exc:`OSError`. Cleaning up
  ``except OSError`` alone still leaks a temp file when the payload fails to encode or the process
  takes a :exc:`KeyboardInterrupt` mid-write; cleaning up nothing at all — the other shape found in
  the wild — leaks one on every failed write, forever, under a name no later run ever looks at.
* whether a failed write raises or is swallowed is a *parameter* (``on_error``), not a decision
  baked into the helper, because both answers are correct somewhere: a cache entry or a "last
  update check" timestamp is not worth failing a run over, and a document a person just saved is.

Neither function serializes. Callers pass an already-encoded :class:`str` or :class:`bytes`, which
keeps :mod:`json`, indent conventions and trailing-newline taste out of this module entirely.

Two limits worth knowing. This buys atomic *visibility*, not durability: nothing is ``fsync``-ed, so
a power loss or kernel panic can still leave the previous contents in place — but never a mixture of
the two. And :func:`tempfile.mkstemp` creates its file mode ``0o600``, so on POSIX the replaced
destination ends up owner-only instead of inheriting the previous file's mode, owner and ACL;
re-apply those after the call when a group or another service has to read the file.

On Windows, two writers replacing the same destination at nearly the same moment can make the
platform's rename briefly report ``PermissionError`` even though each individual replace is atomic
and would succeed moments later; this is retried a few times with a short delay before it is allowed
to surface as a real failure.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

__all__ = ["atomic_write_bytes", "atomic_write_text"]

# Windows can raise PermissionError for a `replace` that loses a race with another thread's
# concurrent replace onto the same destination, even though each individual replace is atomic and
# would succeed moments later — a documented platform quirk (the `atomicwrites` package on PyPI
# carries the same retry for the same reason). POSIX rename has no such failure mode, so the loop
# below exits on the first attempt there.
_REPLACE_RETRIES = 10
_REPLACE_RETRY_DELAY_SECONDS = 0.01


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    mkdir: bool = False,
    on_error: Literal["raise", "ignore"] = "raise",
) -> bool:
    """Atomically replace ``path``'s contents with ``text``.

    Args:
        path: Destination file. Its parent directory must already exist unless ``mkdir=True``. The
            temp file is created in that same directory, which is what keeps the final rename
            atomic.
        text: The complete new contents, already serialized. Nothing is appended, no trailing
            newline is added, and nothing is merged with what the file held before.
        encoding: Codec used for ``text``. Defaults to UTF-8 rather than the platform default, so
            the same bytes land on every host.
        mkdir: When ``True``, create ``path.parent`` with ``parents=True, exist_ok=True`` before
            writing. ``False`` by default: for most callers a missing directory is a bug in the
            caller worth hearing about, not something to paper over.
        on_error: ``"raise"`` (the default) re-raises the :exc:`OSError` once the temp file has been
            removed. ``"ignore"`` swallows it and returns ``False`` instead. Nothing is logged
            either way — this module takes no logger, so a caller that chooses ``"ignore"`` decides
            for itself whether a failed write is worth a line.

    Returns:
        ``True`` when ``path`` now holds exactly ``text``. ``False`` only when ``on_error="ignore"``
        swallowed an :exc:`OSError`, in which case ``path`` is untouched: it still holds its
        previous contents, or still does not exist.

    Raises:
        OSError: When creating the directory, creating the temp file, writing it, or renaming it
            fails and ``on_error="raise"``. ``on_error="ignore"`` covers the write and the rename
            only; an :exc:`OSError` from ``mkdir=True`` or from creating the temp file — a missing
            or unwritable parent directory — is raised in both modes, because it happens before
            there is any half-finished write to hide, and returning ``False`` for it would be
            indistinguishable from a destination that simply could not be updated.
        UnicodeEncodeError: If ``text`` cannot be encoded with ``encoding``, for example a lone
            surrogate under UTF-8. Like every failure that is not an :exc:`OSError` it propagates
            even under ``on_error="ignore"``, since reporting success for content that was never
            written is the one outcome this module exists to rule out. The temp file is removed
            first either way.

    Note:
        Newline translation is disabled (``newline=""``), so ``text`` reaches disk exactly as
        written — a ``"\\n"`` stays ``"\\n"`` even on Windows. This module replaces a file; it does
        not also decide how a caller's newlines should look, and the platform's translation would
        make ``read_text()`` on the result not always equal ``text``.

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from genekit.atomic_write import atomic_write_text
        >>> with tempfile.TemporaryDirectory() as folder:
        ...     target = Path(folder) / "state" / "settings.json"
        ...     atomic_write_text(target, '{"theme": "dark"}', mkdir=True)
        ...     target.read_text(encoding="utf-8")
        True
        '{"theme": "dark"}'

        A failed write leaves the destination alone and takes the temp file with it, so the
        directory looks exactly as it did before the call:

        >>> with tempfile.TemporaryDirectory() as folder:
        ...     blocked = Path(folder) / "not-a-file"
        ...     blocked.mkdir()
        ...     atomic_write_text(blocked, "never lands", on_error="ignore")
        ...     sorted(entry.name for entry in Path(folder).iterdir())
        False
        ['not-a-file']
    """
    return _atomic_write(
        path,
        lambda handle: handle.write(text),
        mode="w",
        encoding=encoding,
        mkdir=mkdir,
        on_error=on_error,
    )


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    mkdir: bool = False,
    on_error: Literal["raise", "ignore"] = "raise",
) -> bool:
    """Atomically replace ``path``'s contents with ``data``, byte for byte.

    The guarantee, the parameters and the failure policy are :func:`atomic_write_text`'s; only the
    payload differs. There is no ``encoding`` and no newline translation here, so the exact bytes
    passed in are the bytes a reader finds — which is what makes this the right call for anything
    already encoded, compressed, signed or hashed.

    Args:
        path: Destination file, as in :func:`atomic_write_text`.
        data: The complete new contents. Any byte string is written verbatim, ``b""`` included,
            which truncates an existing file to zero length in one atomic step.
        mkdir: Create ``path.parent`` first; see :func:`atomic_write_text`.
        on_error: ``"raise"`` or ``"ignore"``; see :func:`atomic_write_text`.

    Returns:
        ``True`` when ``path`` now holds exactly ``data``. ``False`` only when
        ``on_error="ignore"`` swallowed an :exc:`OSError`, leaving ``path`` as it was.

    Raises:
        OSError: When the write or the rename fails and ``on_error="raise"``, and — in both modes —
            when creating the parent directory or the temp file fails. See
            :func:`atomic_write_text` for why that asymmetry is deliberate.
        TypeError: If ``data`` is a :class:`str` rather than :class:`bytes`; the binary handle
            refuses it. It propagates under ``on_error="ignore"`` too, because it is a caller bug
            rather than a filesystem that said no. The temp file is still removed first.

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from genekit.atomic_write import atomic_write_bytes
        >>> with tempfile.TemporaryDirectory() as folder:
        ...     target = Path(folder) / "cache.bin"
        ...     atomic_write_bytes(target, b"\\x00\\x01\\xfe\\xff")
        ...     target.read_bytes()
        True
        b'\\x00\\x01\\xfe\\xff'
    """
    return _atomic_write(
        path,
        lambda handle: handle.write(data),
        mode="wb",
        encoding=None,
        mkdir=mkdir,
        on_error=on_error,
    )


def _atomic_write(
    path: Path,
    write: Callable[[Any], None],
    *,
    mode: str,
    encoding: str | None,
    mkdir: bool,
    on_error: Literal["raise", "ignore"],
) -> bool:
    """Write via a unique sibling temp file, replace ``path``, and never leave the temp behind."""
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    # newline="" only applies to text mode; passing it in binary mode raises. Disabling translation
    # keeps the bytes that land on disk exactly the ones passed in, on every platform alike.
    newline = "" if "b" not in mode else None
    try:
        try:
            handle = os.fdopen(fd, mode, encoding=encoding, newline=newline)
        except BaseException:
            # fdopen failed before wrapping fd in a file object, so the fd is otherwise never
            # closed — a leak everywhere, and on Windows an open handle also blocks the tmp.unlink()
            # cleanup below.
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        with handle:
            write(handle)
        _replace_with_retry(tmp, path)
        return True
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        if on_error == "raise":
            raise
        return False
    except BaseException:
        # Encoding errors, a KeyboardInterrupt mid-write, a caller's serializer blowing up: none of
        # these are the filesystem saying no, so ``on_error`` has no say and they propagate. The
        # cleanup still runs, because the leaked temp file is the same leaked temp file either way.
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _replace_with_retry(tmp: Path, path: Path) -> None:
    """Replace ``path`` with ``tmp``, retrying briefly through Windows' transient denial."""
    for attempt in range(_REPLACE_RETRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt + 1 == _REPLACE_RETRIES:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_SECONDS)
