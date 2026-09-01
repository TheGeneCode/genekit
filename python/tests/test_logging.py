"""Tests for genekit.logging."""

import builtins
import importlib.util
import logging
import re
import threading
from contextvars import copy_context
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from genekit.logging import (
    VERBOSE_DATEFMT,
    VERBOSE_FMT,
    _ScopeFilter,
    _validate_rotation,
    add_file_handler,
    add_scoped_file_handler,
    configure_logging,
    current_scope_label,
    dedicated_file_logger,
    get_logger,
    scoped_logging,
)


class _ListHandler(logging.Handler):
    """In-memory handler capturing formatted messages, so property tests skip file I/O."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_plain_console_logs_to_stderr(capsys):
    configure_logging(console="plain")
    get_logger("demo").info("hello stderr")
    captured = capsys.readouterr()
    assert "hello stderr" in captured.err
    assert captured.out == ""


def test_rich_missing_falls_back_to_plain(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("rich"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    configure_logging(console="rich")
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert type(handlers[0]) is logging.StreamHandler


def test_rich_console_uses_richhandler_when_rich_is_installed():
    """The ``else:`` branch of ``_make_console_handler`` — reachable only when rich really imports.

    ``test_rich_missing_falls_back_to_plain`` fakes the ImportError and so passes in both CI
    profiles; nothing else in this file reaches the RichHandler construction. Skipped on the
    ``bare`` matrix leg, which is the point: the two profiles cover different branches.
    """
    rich_logging = pytest.importorskip("rich.logging")
    configure_logging(console="rich")
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], rich_logging.RichHandler)


def test_rich_console_degrades_to_plain_when_rich_is_genuinely_absent():
    """The same fallback the monkeypatched test asserts, but with rich actually not installed.

    This is what the ``bare`` CI profile exercises: a real failed import at the real import site,
    rather than a faked one. Skipped on the ``rich`` leg.

    The skip guard deliberately checks ``find_spec("rich")``, not ``find_spec("rich.logging")``:
    ``find_spec`` on a dotted name imports each parent package to resolve the child, so when the
    parent is genuinely missing it raises ``ModuleNotFoundError`` instead of returning ``None`` —
    confirmed empirically (bare env): ``find_spec("rich")`` returns ``None``, but
    ``find_spec("rich.logging")`` raises. The finer-grained check would crash this test's skip
    guard on the very ``bare`` leg it exists to run on, so the coarser top-level check is correct,
    not merely a shortcut.
    """
    if importlib.util.find_spec("rich") is not None:
        pytest.skip("rich is installed; this test asserts the genuinely-absent path")
    configure_logging(console="rich")
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert type(handlers[0]) is logging.StreamHandler


def test_rich_partial_import_failure_falls_back_to_plain(monkeypatch):
    """`_make_console_handler`'s ``try`` block imports ``rich.console`` then ``rich.logging`` in
    sequence; ``test_rich_missing_falls_back_to_plain`` fakes failure on the *first* import (any
    name starting with ``"rich"``), so the ``except ImportError`` catching a failure of the
    *second* import specifically — parent package present and importable, only the ``rich.logging``
    submodule import raising — was never exercised by any existing test.

    This is also the direct, code-level answer to whether "rich present but ``rich.logging``
    import fails" is a real gap: it is not a gap in the shipped fallback behaviour (this test
    proves that path is handled correctly), only in *which test's skip guard* would have run in
    that scenario — and that guard's own correctness is covered by the note above.
    """
    pytest.importorskip("rich.console")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rich.logging" or name.startswith("rich.logging."):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    configure_logging(console="rich")
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert type(handlers[0]) is logging.StreamHandler


def test_reconfigure_is_idempotent():
    configure_logging(console="plain")
    first = len(logging.getLogger().handlers)
    configure_logging(console="plain")
    assert len(logging.getLogger().handlers) == first == 1


def test_console_none_without_file_raises():
    with pytest.raises(ValueError, match="requires log_file"):
        configure_logging(console="none")


def test_log_file_parents_created_and_verbose_format(tmp_path):
    log_file = tmp_path / "a" / "b" / "run.log"
    configure_logging(console="none", log_file=log_file)
    get_logger("demo").info("to file")
    assert log_file.exists()
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO\s+\w", _read(log_file))


def test_add_file_handler_captures_all_loggers(tmp_path):
    configure_logging(console="plain")
    log_file = tmp_path / "all.log"
    add_file_handler(log_file)
    get_logger("one").info("from one")
    get_logger("two").info("from two")
    contents = _read(log_file)
    assert "from one" in contents
    assert "from two" in contents


def test_scoped_handler_routes_only_matching_label(tmp_path):
    configure_logging(console="none", log_file=tmp_path / "root.log")
    file_a = tmp_path / "a.log"
    file_b = tmp_path / "b.log"
    add_scoped_file_handler(file_a, "a")
    add_scoped_file_handler(file_b, "b")
    logger = get_logger("demo")
    with scoped_logging("a"):
        logger.info("only-a")
    with scoped_logging("b"):
        logger.info("only-b")
    assert "only-a" in _read(file_a)
    assert "only-b" not in _read(file_a)
    assert "only-b" in _read(file_b)
    assert "only-a" not in _read(file_b)


def test_records_outside_scope_dropped(tmp_path):
    configure_logging(console="none", log_file=tmp_path / "root.log")
    scoped = tmp_path / "a.log"
    add_scoped_file_handler(scoped, "a")
    get_logger("demo").info("unscoped")
    assert scoped.exists()
    assert _read(scoped) == ""


def test_scope_carries_into_copied_context_thread(tmp_path):
    configure_logging(console="none", log_file=tmp_path / "root.log")
    scoped = tmp_path / "s.log"
    add_scoped_file_handler(scoped, "s")
    logger = get_logger("demo")

    def emit() -> None:
        logger.info("from worker thread")

    with scoped_logging("s"):
        ctx = copy_context()
    thread = threading.Thread(target=ctx.run, args=(emit,))
    thread.start()
    thread.join()
    assert "from worker thread" in _read(scoped)


def test_dedicated_logger_does_not_propagate(tmp_path, capsys):
    root_log = tmp_path / "root.log"
    configure_logging(console="plain")
    add_file_handler(root_log)
    usage_log = tmp_path / "usage.log"
    usage = dedicated_file_logger("usage", usage_log)
    usage.info("1200 characters")
    captured = capsys.readouterr()
    assert "1200 characters" in _read(usage_log)
    assert "1200 characters" not in _read(root_log)
    assert "1200 characters" not in captured.err


def test_dedicated_logger_reinit_single_handler(tmp_path):
    log_file = tmp_path / "usage.log"
    logger = dedicated_file_logger("usage", log_file)
    first = logger.handlers[0]
    dedicated_file_logger("usage", log_file)
    assert len(logger.handlers) == 1
    assert logger.handlers[0] is not first
    # FileHandler.close() drops its stream reference — the old handler is closed, not just detached.
    assert first.stream is None


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(outer=st.text(min_size=1), inner=st.text(min_size=1))
def test_scoped_label_set_reset_property(outer, inner):
    """The label is active inside the block and the prior value is restored on exit, nested too."""
    before = current_scope_label.get()
    with scoped_logging(outer):
        assert current_scope_label.get() == outer
        with scoped_logging(inner):
            assert current_scope_label.get() == inner
        assert current_scope_label.get() == outer
    assert current_scope_label.get() == before


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    events=st.lists(
        st.tuples(
            st.sampled_from(["a", "b"]),
            st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1),
        ),
        max_size=20,
    )
)
def test_scope_routing_partition_property(events):
    """Uses in-memory capturing handlers (not files) so each example avoids per-example file I/O."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handlers: dict[str, _ListHandler] = {}
    try:
        for label in ("a", "b"):
            handler = _ListHandler()
            handler.addFilter(_ScopeFilter(label))
            root.addHandler(handler)
            handlers[label] = handler
        logger = get_logger("prop")
        for label, message in events:
            with scoped_logging(label):
                logger.info(message)
        for label in ("a", "b"):
            assert handlers[label].messages == [m for lbl, m in events if lbl == label]
    finally:
        for handler in handlers.values():
            root.removeHandler(handler)


# --- Boundary matrix additions ---------------------------------------------------------------


def test_verbose_fmt_and_datefmt_constants_pinned():
    """Byte-compatibility contract with the pre-promotion implementation — must not drift."""
    assert VERBOSE_FMT == "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    assert VERBOSE_DATEFMT == "%Y-%m-%d %H:%M:%S"


def test_current_scope_label_default_is_none():
    assert current_scope_label.get() is None


@pytest.mark.parametrize("bad_console", ["Rich", "PLAIN", "loud", ""])
def test_configure_logging_invalid_console_raises(bad_console):
    with pytest.raises(ValueError, match="console must be"):
        configure_logging(console=bad_console)


def test_configure_logging_invalid_level_raises():
    with pytest.raises(ValueError):
        configure_logging(level="not-a-level", console="plain")


def test_configure_logging_lowercase_level_accepted():
    configure_logging(level="debug", console="plain")
    assert logging.getLogger().level == logging.DEBUG


def test_add_file_handler_invalid_level_raises(tmp_path):
    with pytest.raises(ValueError):
        add_file_handler(tmp_path / "x.log", level="not-a-level")


def test_reconfigure_closes_old_file_handler(tmp_path):
    """basicConfig(force=True) must close the old handler, or Windows keeps the file locked."""
    log_file = tmp_path / "run.log"
    configure_logging(console="plain", log_file=log_file)
    first_file_handlers = [
        h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)
    ]
    assert len(first_file_handlers) == 1
    old_handler = first_file_handlers[0]
    configure_logging(console="plain", log_file=log_file)
    assert old_handler.stream is None


def test_log_file_parent_is_file_raises(tmp_path):
    """Parent-as-file is an environment error and must surface, not be silently swallowed."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    bad_log = blocker / "run.log"
    with pytest.raises((FileExistsError, NotADirectoryError)):
        add_file_handler(bad_log)


def test_unicode_log_file_path(tmp_path):
    log_file = tmp_path / "日本語" / "ログ.log"
    configure_logging(console="none", log_file=log_file)
    get_logger("demo").info("unicode message: café")
    assert log_file.exists()
    assert "unicode message" in _read(log_file)


def test_empty_string_label_is_distinct_scope(tmp_path):
    """label='' is falsy but must be treated as a real, distinct scope, not 'no active label'."""
    configure_logging(console="none", log_file=tmp_path / "root.log")
    empty_log = tmp_path / "empty.log"
    add_scoped_file_handler(empty_log, "")
    logger = get_logger("demo")
    logger.info("unscoped-dropped")
    with scoped_logging(""):
        logger.info("empty-label-admitted")
    contents = _read(empty_log)
    assert "empty-label-admitted" in contents
    assert "unscoped-dropped" not in contents


def test_nested_scoped_logging_routes_to_innermost_label(tmp_path):
    configure_logging(console="none", log_file=tmp_path / "root.log")
    file_a = tmp_path / "a.log"
    file_b = tmp_path / "b.log"
    add_scoped_file_handler(file_a, "a")
    add_scoped_file_handler(file_b, "b")
    logger = get_logger("demo")
    with scoped_logging("a"):
        logger.info("outer-a")
        with scoped_logging("b"):
            logger.info("inner-b")
        logger.info("outer-a-again")
    contents_a = _read(file_a)
    contents_b = _read(file_b)
    assert "outer-a" in contents_a
    assert "outer-a-again" in contents_a
    assert "inner-b" not in contents_a
    assert "inner-b" in contents_b


def test_add_scoped_file_handler_level_filters_below_threshold(tmp_path):
    configure_logging(console="none", log_file=tmp_path / "root.log")
    log_file = tmp_path / "warn.log"
    add_scoped_file_handler(log_file, "a", level="WARNING")
    logger = get_logger("demo")
    with scoped_logging("a"):
        logger.info("info-should-be-filtered")
        logger.warning("warn-should-pass")
    contents = _read(log_file)
    assert "warn-should-pass" in contents
    assert "info-should-be-filtered" not in contents


def test_concurrent_threads_different_scopes_no_cross_contamination(tmp_path):
    configure_logging(console="none", log_file=tmp_path / "root.log")
    file_a = tmp_path / "a.log"
    file_b = tmp_path / "b.log"
    add_scoped_file_handler(file_a, "a")
    add_scoped_file_handler(file_b, "b")
    logger = get_logger("concurrent-demo")
    barrier = threading.Barrier(2)

    def worker(label: str) -> None:
        barrier.wait()
        with scoped_logging(label):
            for i in range(50):
                logger.info(f"{label}-{i}")

    threads = [threading.Thread(target=worker, args=(lbl,)) for lbl in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    contents_a = _read(file_a)
    contents_b = _read(file_b)
    assert all(f"a-{i}" in contents_a for i in range(50))
    assert all(f"b-{i}" in contents_b for i in range(50))
    assert "b-0" not in contents_a
    assert "a-0" not in contents_b


def test_dedicated_logger_custom_fmt_applied(tmp_path):
    log_file = tmp_path / "usage.log"
    usage = dedicated_file_logger("usage-fmt", log_file, fmt="%(message)s | terse")
    usage.info("hello")
    assert _read(log_file).strip() == "hello | terse"


def test_two_dedicated_loggers_same_path_write_independently(tmp_path):
    log_file = tmp_path / "shared.log"
    logger_x = dedicated_file_logger("logger-x", log_file)
    logger_y = dedicated_file_logger("logger-y", log_file)
    logger_x.info("from-x")
    logger_y.info("from-y")
    contents = _read(log_file)
    assert "from-x" in contents
    assert "from-y" in contents


# --- Rotation --------------------------------------------------------------------------------


def _root_file_handler() -> logging.Handler:
    file_handlers = [
        h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)
    ]
    assert len(file_handlers) == 1
    return file_handlers[0]


def test_configure_logging_default_is_plain_file_not_rotating(tmp_path):
    """Default rotate_bytes=0 keeps the pre-existing plain FileHandler — no behaviour change."""
    configure_logging(console="none", log_file=tmp_path / "run.log")
    handler = _root_file_handler()
    assert type(handler) is logging.FileHandler
    assert not isinstance(handler, RotatingFileHandler)


def test_configure_logging_rotating_handler_wired(tmp_path):
    configure_logging(
        console="none", log_file=tmp_path / "run.log", rotate_bytes=1024, backup_count=3
    )
    handler = _root_file_handler()
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == 1024
    assert handler.backupCount == 3


def test_configure_logging_rotation_actually_rolls_over(tmp_path):
    log_file = tmp_path / "run.log"
    configure_logging(console="none", log_file=log_file, rotate_bytes=512, backup_count=2)
    logger = get_logger("rot-demo")
    for i in range(200):
        logger.info(f"line {i} padded to force the file past the 512-byte rollover threshold")
    assert log_file.exists()
    assert (tmp_path / "run.log.1").exists()  # at least one backup produced
    backups = list(tmp_path.glob("run.log.*"))
    assert len(backups) <= 2  # backup_count caps retained backups


def test_configure_logging_negative_rotate_bytes_raises(tmp_path):
    with pytest.raises(ValueError, match="rotate_bytes must be >= 0"):
        configure_logging(console="none", log_file=tmp_path / "run.log", rotate_bytes=-1)


def test_configure_logging_negative_backup_count_raises(tmp_path):
    with pytest.raises(ValueError, match="backup_count must be >= 0"):
        configure_logging(
            console="none", log_file=tmp_path / "run.log", rotate_bytes=1024, backup_count=-1
        )


def test_configure_logging_backup_count_without_rotate_bytes_raises(tmp_path):
    with pytest.raises(ValueError, match="backup_count > 0 requires rotate_bytes"):
        configure_logging(console="none", log_file=tmp_path / "run.log", backup_count=3)


def test_configure_logging_rotate_bytes_without_log_file_raises():
    with pytest.raises(ValueError, match="rotate_bytes > 0 requires log_file"):
        configure_logging(console="plain", rotate_bytes=1024, backup_count=3)


def test_configure_logging_rotate_bytes_positive_backup_zero_raises(tmp_path):
    """rotate_bytes>0 with backup_count=0 cannot bound the file (stdlib reopens in append mode),
    so it is rejected rather than silently growing unbounded."""
    with pytest.raises(ValueError, match="rotate_bytes > 0 requires backup_count"):
        configure_logging(
            console="none", log_file=tmp_path / "run.log", rotate_bytes=256, backup_count=0
        )


def test_add_file_handler_rotating(tmp_path):
    configure_logging(console="plain")
    log_file = tmp_path / "extra.log"
    handler = add_file_handler(log_file, rotate_bytes=2048, backup_count=1)
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == 2048
    assert handler.backupCount == 1


def test_add_file_handler_backup_count_without_rotate_bytes_raises(tmp_path):
    with pytest.raises(ValueError, match="backup_count > 0 requires rotate_bytes"):
        add_file_handler(tmp_path / "x.log", backup_count=2)


def test_add_file_handler_negative_rotate_bytes_raises(tmp_path):
    """Matrix cell distinct from configure_logging's own negative-value tests: add_file_handler
    has its own call site into _validate_rotation and needs its own coverage."""
    with pytest.raises(ValueError, match="rotate_bytes must be >= 0"):
        add_file_handler(tmp_path / "x.log", rotate_bytes=-1)


def test_add_file_handler_negative_backup_count_raises(tmp_path):
    with pytest.raises(ValueError, match="backup_count must be >= 0"):
        add_file_handler(tmp_path / "x.log", rotate_bytes=10, backup_count=-1)


def test_rotate_bytes_smaller_than_single_message_still_written(tmp_path):
    """rotate_bytes smaller than one message's rendered size must still land the message, not
    drop or corrupt it -- shouldRollover fires against an empty file before the first write
    completes."""
    log_file = tmp_path / "run.log"
    configure_logging(console="none", log_file=log_file, rotate_bytes=1, backup_count=1)
    get_logger("tiny-threshold-demo").info("this single message exceeds the 1-byte threshold")
    assert "this single message exceeds the 1-byte threshold" in _read(log_file)


def test_add_file_handler_rotate_bytes_positive_backup_zero_raises(tmp_path):
    """The reject-half-configured-rotation rule holds through add_file_handler's own call site."""
    with pytest.raises(ValueError, match="rotate_bytes > 0 requires backup_count"):
        add_file_handler(tmp_path / "x.log", rotate_bytes=256, backup_count=0)


def test_concurrent_writes_trigger_rotation_no_message_loss(tmp_path):
    """Race-condition matrix cell for the rotation path specifically (existing concurrency tests
    only cover scope routing, not rollover). stdlib Handler.emit is guarded by a lock shared
    across shouldRollover/doRollover/emit, so concurrent same-process writers should neither lose
    nor corrupt messages across a rollover boundary.

    backup_count is sized generously above what 400 short messages need (~23KB of text against
    ~43KB of retained capacity) so every message should still be retained somewhere across the
    base file + backups; this isolates "did locking lose/corrupt a message" from "did retention
    legitimately evict it", which a smaller backup_count would conflate.
    """
    log_file = tmp_path / "run.log"
    configure_logging(console="none", log_file=log_file, rotate_bytes=2048, backup_count=20)
    logger = get_logger("concurrent-rot-demo")
    n_threads = 4
    n_msgs = 100
    barrier = threading.Barrier(n_threads)

    def worker(tid: int) -> None:
        barrier.wait()
        for i in range(n_msgs):
            logger.info(f"t{tid}-m{i}")

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    all_text = log_file.read_text(encoding="utf-8")
    for path in tmp_path.glob("run.log.*"):
        all_text += path.read_text(encoding="utf-8")
    for tid in range(n_threads):
        for i in range(n_msgs):
            assert f"t{tid}-m{i}" in all_text


@pytest.mark.parametrize(
    ("rotate_bytes", "backup_count"),
    [(0, 0), (1, 1), (1024, 5), (999_999_999, 100)],
)
def test_validate_rotation_accepts_valid_combos(rotate_bytes, backup_count):
    assert _validate_rotation(rotate_bytes, backup_count) is None


def _rotation_is_valid(rotate_bytes: int, backup_count: int) -> bool:
    """Independent spec oracle: rotation is coherent iff both bounds are non-negative and the two
    knobs agree on whether rotation is on (both positive) or off (both zero). Deliberately phrased
    as one boolean expression, not as a copy of the implementation's sequential branches, so a
    shared conceptual slip in the rule cannot pass through both."""
    both_nonnegative = rotate_bytes >= 0 and backup_count >= 0
    rotation_agrees = (rotate_bytes > 0) == (backup_count > 0)
    return both_nonnegative and rotation_agrees


@given(
    rotate_bytes=st.integers(min_value=-(10**9), max_value=10**9),
    backup_count=st.integers(min_value=-(10**9), max_value=10**9),
)
def test_validate_rotation_property(rotate_bytes, backup_count):
    """_validate_rotation raises iff the combo is invalid; otherwise returns None."""
    expected_valid = _rotation_is_valid(rotate_bytes, backup_count)
    if expected_valid:
        assert _validate_rotation(rotate_bytes, backup_count) is None
    else:
        with pytest.raises(ValueError):
            _validate_rotation(rotate_bytes, backup_count)
