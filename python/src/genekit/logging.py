"""Opinionated logging setup: console + file handlers, context-scoped file routing.

The decision this module encodes: console records go to **stderr** (so machine-readable output on
stdout stays clean and pipeable), file records get a verbose, greppable format, and concurrent units
of work can each own a log file without contaminating one another.

`rich` is optional. Install the ``genekit[rich]`` extra for the rich console; without it,
``console="rich"`` degrades silently to ``console="plain"``.
"""

import contextvars
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

VERBOSE_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
"""Verbose, greppable format used by every file handler in this module."""

VERBOSE_DATEFMT = "%Y-%m-%d %H:%M:%S"
"""Sortable timestamp format paired with :data:`VERBOSE_FMT`."""

_CONSOLE_DATEFMT = "%H:%M:%S"
_RICH_FMT = "%(message)s"
_RICH_DATEFMT = "[%X]"

ConsoleMode = Literal["rich", "plain", "none"]

current_scope_label: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "genekit_scope_label", default=None
)
"""Label of the scope whose work the current context is doing, or ``None`` outside any scope.

Set by :func:`scoped_logging`. Because it is a :class:`~contextvars.ContextVar`, the label is
carried into workers started from a captured ``contextvars.copy_context()``, so records emitted deep
inside a nested thread still know which scope they belong to.
"""


def _validate_rotation(rotate_bytes: int, backup_count: int) -> None:
    """Reject rotation arguments that are negative or that quietly disable rotation.

    Rotation is either fully on or fully off: it is on only when **both** ``rotate_bytes`` and
    ``backup_count`` are positive. A positive ``backup_count`` with ``rotate_bytes == 0`` never
    rolls over, and a positive ``rotate_bytes`` with ``backup_count == 0`` cannot bound the file
    either — the stdlib :class:`~logging.handlers.RotatingFileHandler` reopens the same path in
    append mode on rollover, so the file grows without limit. Both mismatches promise bounded logs
    the config cannot deliver, so — like ``console="none"`` without a ``log_file`` — the silent
    no-op is surfaced as an error instead. To bound a log file, keep at least one backup.

    Args:
        rotate_bytes: Rollover threshold in bytes. 0 means "never rotate". Must be >= 0.
        backup_count: Number of rotated backups to keep. Must be >= 0, and positive if and only if
            ``rotate_bytes`` is positive.

    Returns:
        None.

    Raises:
        ValueError: If ``rotate_bytes`` or ``backup_count`` is negative, or if exactly one of them
            is positive (rotation half-configured).

    Example:
        >>> from genekit.logging import _validate_rotation
        >>> _validate_rotation(5_000_000, 3)
    """
    if rotate_bytes < 0:
        raise ValueError(f"rotate_bytes must be >= 0, got {rotate_bytes!r}")
    if backup_count < 0:
        raise ValueError(f"backup_count must be >= 0, got {backup_count!r}")
    if backup_count > 0 and rotate_bytes == 0:
        raise ValueError(
            "backup_count > 0 requires rotate_bytes > 0 — with rotate_bytes=0 the file never "
            "rotates and no backups are ever kept"
        )
    if rotate_bytes > 0 and backup_count == 0:
        raise ValueError(
            "rotate_bytes > 0 requires backup_count > 0 — with backup_count=0 the stdlib handler "
            "reopens the file in append mode on rollover and never bounds its size"
        )


def _make_file_handler(
    path: Path,
    level: str,
    *,
    fmt: str = VERBOSE_FMT,
    datefmt: str = VERBOSE_DATEFMT,
    rotate_bytes: int = 0,
    backup_count: int = 0,
) -> logging.Handler:
    """Build a UTF-8 file handler with a verbose, greppable (non-rich) formatter.

    A positive ``rotate_bytes`` yields a size-rotating handler; otherwise a plain file handler that
    grows without bound. Rotation arguments are validated here, so every caller — present and
    future — is protected from a half-configured rotation regardless of its own checks.
    """
    _validate_rotation(rotate_bytes, backup_count)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler: logging.Handler
    if rotate_bytes > 0:
        handler = RotatingFileHandler(
            path, maxBytes=rotate_bytes, backupCount=backup_count, encoding="utf-8"
        )
    else:
        handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(level.upper())
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    return handler


def _make_console_handler(console: Literal["rich", "plain"]) -> logging.Handler:
    """Build the stderr console handler, falling back to plain when rich is unavailable."""
    if console == "rich":
        try:
            from rich.console import Console
            from rich.logging import RichHandler
        except ImportError:
            pass
        else:
            handler: logging.Handler = RichHandler(
                rich_tracebacks=True, show_path=False, console=Console(stderr=True, emoji=False)
            )
            handler.setFormatter(logging.Formatter(_RICH_FMT, datefmt=_RICH_DATEFMT))
            return handler
    plain = logging.StreamHandler(sys.stderr)
    plain.setFormatter(logging.Formatter(VERBOSE_FMT, datefmt=_CONSOLE_DATEFMT))
    return plain


def configure_logging(
    level: str = "INFO",
    *,
    log_file: Path | None = None,
    console: ConsoleMode = "rich",
    rotate_bytes: int = 0,
    backup_count: int = 0,
) -> None:
    """Configure root logging. Idempotent across calls — later calls replace earlier handlers.

    Console records always go to stderr, leaving stdout free for machine-readable output. When
    ``log_file`` is given, a verbose file handler is attached alongside the console so a run can be
    troubleshot after the fact. A long-lived process (a daemon) can cap that file's growth by
    passing ``rotate_bytes`` **and** ``backup_count`` together; the default leaves the file
    unbounded, matching prior behaviour. Rotation is single-process only — do not point two
    processes at the same rotating ``log_file``, as their rollover renames can race (on Windows the
    loser raises ``PermissionError``).

    Args:
        level: Root log level name, case-insensitive (e.g. ``"INFO"``, ``"debug"``).
        log_file: Optional path for a verbose log file. Parent directories are created.
        console: ``"rich"`` for a rich-formatted console (requires the ``genekit[rich]`` extra;
            silently degrades to ``"plain"`` when rich is not installed), ``"plain"`` for a stdlib
            stderr handler with :data:`VERBOSE_FMT`, or ``"none"`` for no console output.
        rotate_bytes: If > 0, the log file rolls over once it reaches this many bytes (a
            :class:`~logging.handlers.RotatingFileHandler`); ``0`` (the default) uses a plain,
            unbounded file handler. Requires ``log_file`` and a positive ``backup_count``.
        backup_count: Number of rotated backups to keep. Must be > 0 to enable rotation and ``0``
            (the default) when ``rotate_bytes`` is 0; a bounded log always keeps at least one
            backup.

    Returns:
        None.

    Raises:
        ValueError: If ``console`` is not one of ``"rich"``, ``"plain"``, ``"none"``; if
            ``console="none"`` is combined with ``log_file=None`` (that configuration has zero
            handlers and would silently discard every record); if ``rotate_bytes`` or
            ``backup_count`` is negative, or exactly one of them is positive (rotation
            half-configured); or if ``rotate_bytes`` > 0 without a ``log_file`` to rotate.

    Example:
        >>> from genekit.logging import configure_logging, get_logger
        >>> configure_logging("DEBUG", console="plain")
        >>> get_logger("demo").info("ready")
    """
    if console not in ("rich", "plain", "none"):
        raise ValueError(f"console must be 'rich', 'plain' or 'none', got {console!r}")
    if console == "none" and log_file is None:
        raise ValueError("console='none' requires log_file — that config would drop every record")
    _validate_rotation(rotate_bytes, backup_count)
    if rotate_bytes > 0 and log_file is None:
        raise ValueError("rotate_bytes > 0 requires log_file — there is no file to rotate")

    handlers: list[logging.Handler] = []
    if console != "none":
        handlers.append(_make_console_handler(console))
    if log_file is not None:
        handlers.append(
            _make_file_handler(
                log_file, level, rotate_bytes=rotate_bytes, backup_count=backup_count
            )
        )
    logging.basicConfig(level=level.upper(), handlers=handlers, force=True)


def add_file_handler(
    path: Path, level: str = "INFO", *, rotate_bytes: int = 0, backup_count: int = 0
) -> logging.Handler:
    """Attach an unfiltered file handler to the root logger and return it.

    Every record reaching the root logger lands in this file. Correct when one unit of work runs at
    a time; for concurrent units each wanting their own file, use :func:`add_scoped_file_handler`,
    which admits only the matching scope's records.

    Args:
        path: Log file path. Parent directories are created.
        level: Handler level name, case-insensitive.
        rotate_bytes: If > 0, the file rolls over at this many bytes
            (:class:`~logging.handlers.RotatingFileHandler`); ``0`` (default) is an unbounded plain
            file handler.
        backup_count: Rotated backups to keep when ``rotate_bytes`` > 0. Must be > 0 to enable
            rotation (a bounded log keeps at least one backup).

    Returns:
        The attached handler, so callers can ``removeHandler``/``close`` it later.

    Raises:
        ValueError: If ``rotate_bytes`` or ``backup_count`` is negative, or exactly one of them is
            positive (rotation half-configured).

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from genekit.logging import add_file_handler, configure_logging, get_logger
        >>> configure_logging(console="plain")
        >>> handler = add_file_handler(Path(tempfile.mkdtemp()) / "run.log")
        >>> get_logger("demo").info("captured to console and file")
    """
    handler = _make_file_handler(
        path, level, rotate_bytes=rotate_bytes, backup_count=backup_count
    )
    logging.getLogger().addHandler(handler)
    return handler


class _ScopeFilter(logging.Filter):
    """Admit a record only while :data:`current_scope_label` equals this handler's ``label``.

    With concurrent scopes each attaching their own root-logger handler, an unfiltered handler would
    receive *every* scope's records (the root logger fans every record out to all handlers). This
    filter partitions records by the context that emitted them; a record with no active label
    (``None``) belongs to no scope and is dropped from scoped files.
    """

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def filter(self, record: logging.LogRecord) -> bool:
        return current_scope_label.get() == self.label


def add_scoped_file_handler(path: Path, label: str, level: str = "INFO") -> logging.Handler:
    """Attach a context-routed file handler to the root logger and return it.

    Identical to :func:`add_file_handler` but filtered so the handler only records lines emitted
    while the active :data:`current_scope_label` is ``label`` — the contamination-free building
    block for concurrent work that each wants its own log file.

    Args:
        path: Log file path. Parent directories are created.
        label: Scope label this handler accepts, as passed to :func:`scoped_logging`.
        level: Handler level name, case-insensitive.

    Returns:
        The attached handler, so callers can ``removeHandler``/``close`` it later.

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from genekit.logging import add_scoped_file_handler, configure_logging, scoped_logging
        >>> from genekit.logging import get_logger
        >>> configure_logging(console="plain")
        >>> handler = add_scoped_file_handler(Path(tempfile.mkdtemp()) / "job-a.log", "job-a")
        >>> with scoped_logging("job-a"):
        ...     get_logger("demo").info("goes to job-a.log")
    """
    handler = _make_file_handler(path, level)
    handler.addFilter(_ScopeFilter(label))
    logging.getLogger().addHandler(handler)
    return handler


@contextmanager
def scoped_logging(label: str) -> Iterator[None]:
    """Set :data:`current_scope_label` to ``label`` for the duration of the block.

    The previous label is restored on exit (via a contextvar token), so nesting works. Wrap a unit
    of work in this so every record it — and any worker running a ``copy_context()`` captured
    inside it — emits is routed to the matching :func:`add_scoped_file_handler` file.

    Args:
        label: The scope label to make active inside the block.

    Yields:
        None.

    Example:
        >>> from genekit.logging import current_scope_label, scoped_logging
        >>> with scoped_logging("job-a"):
        ...     current_scope_label.get()
        'job-a'
    """
    token = current_scope_label.set(label)
    try:
        yield
    finally:
        current_scope_label.reset(token)


def dedicated_file_logger(
    name: str, path: Path, *, level: str = "INFO", fmt: str = VERBOSE_FMT
) -> logging.Logger:
    """Return a named logger that writes only to ``path`` and never propagates to the root.

    For side-channel logs — usage/audit trails — that must stay out of the console and out of the
    root log file. Re-calling with the same ``name`` replaces (and closes) the previous handler
    rather than duplicating it, so re-initialization is safe.

    Args:
        name: Logger name, e.g. ``"usage"``. Reusing a name re-initializes that logger.
        path: Log file path. Parent directories are created.
        level: Level name applied to both the logger and its handler, case-insensitive.
        fmt: Formatter string for the file. Defaults to :data:`VERBOSE_FMT`; a usage trail often
            wants something terser such as ``"%(asctime)s | %(message)s"``.

    Returns:
        The configured logger, with exactly one file handler and ``propagate`` disabled.

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from genekit.logging import dedicated_file_logger
        >>> usage = dedicated_file_logger(
        ...     "usage", Path(tempfile.mkdtemp()) / "usage.log", fmt="%(asctime)s | %(message)s"
        ... )
        >>> usage.info("1200 characters synthesized")
    """
    logger = logging.getLogger(name)
    logger.setLevel(level.upper())
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    logger.addHandler(_make_file_handler(path, level, fmt=fmt))
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a module logger by name.

    Args:
        name: Logger name, conventionally the caller's ``__name__``.

    Returns:
        The logger registered under ``name``.

    Example:
        >>> from genekit.logging import get_logger
        >>> get_logger("demo").name
        'demo'
    """
    return logging.getLogger(name)
