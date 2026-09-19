"""Tests for genekit.atomic_write.

Boundary Matrix
===============

Dimension A — happy path
------------------------------------------------------------------
| Cell | Case                               | Expected                     |
|------|-------------------------------------|-------------------------------|
| A1   | atomic_write_text to a fresh path  | file exists, content exact   |
| A2   | atomic_write_bytes to a fresh path | file exists, content exact   |
| A3   | write over an existing file        | old content fully replaced   |

Dimension B — mkdir
------------------------------------------------------------------
| Cell | Case                                  | Expected                       |
|------|----------------------------------------|---------------------------------|
| B1   | mkdir=False, missing parent dir       | raises OSError                 |
| B2   | mkdir=True, missing nested parent dir | parent created, write succeeds |

Dimension C — on_error
------------------------------------------------------------------
| Cell | Case                                    | Expected                            |
|------|------------------------------------------|--------------------------------------|
| C1   | on_error="raise", forced OSError mid-write | raises OSError, no *.tmp left    |
| C2   | on_error="ignore", same forced failure    | False, no *.tmp left, dest untouched |

Dimension D — non-OSError exception mid-write
------------------------------------------------------------------
| Cell | Case                              | Expected                             |
|------|-------------------------------------|---------------------------------------|
| D1   | encode failure, on_error="raise"  | propagates, no *.tmp left            |
| D2   | encode failure, on_error="ignore" | still propagates, no *.tmp left      |

Dimension E — concurrency
------------------------------------------------------------------
| Cell | Case                                          | Expected                          |
|------|-------------------------------------------------|------------------------------------|
| E1   | N threads, same path, distinct full payloads    | final content is one full payload |

Dimension F — temp uniqueness
------------------------------------------------------------------
| Cell | Case                                | Expected                              |
|------|---------------------------------------|----------------------------------------|
| F1   | concurrent writers on the same path  | no collision; mkstemp names distinct  |

Dimension G — unicode/empty (text)
------------------------------------------------------------------
| Cell | Case                            | Expected                        |
|------|------------------------------------|------------------------------------|
| G1   | empty string                      | round-trips exactly               |
| G2   | unicode ("Zürich/Ünïcode")        | round-trips exactly               |
| G3   | very long string                  | round-trips exactly               |
| G4   | embedded \\n / \\r\\n / \\r       | round-trips, no newline translation |

Dimension H — bytes edge cases
------------------------------------------------------------------
| Cell | Case                           | Expected            |
|------|----------------------------------|----------------------|
| H1   | empty bytes                     | round-trips exactly |
| H2   | arbitrary binary incl. b"\\x00" | round-trips exactly |

Dimension I — _replace_with_retry (isolated from thread timing)
------------------------------------------------------------------
| Cell | Case                                            | Expected                        |
|------|---------------------------------------------------|------------------------------------|
| I1   | PermissionError twice, then success               | succeeds, replace called 3x      |
| I2   | PermissionError every attempt                      | raises after _REPLACE_RETRIES     |
| I3   | non-PermissionError OSError                        | raises immediately, no sleep      |

Dimension D also covers, for atomic_write_bytes specifically, that a non-OSError (TypeError from
a str payload) propagates regardless of on_error, and that os.fdopen raising a non-OSError
(unknown codec) closes the raw fd and leaves no temp file behind.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from genekit.atomic_write import (
    _REPLACE_RETRIES,
    _replace_with_retry,
    atomic_write_bytes,
    atomic_write_text,
)

# ---------------------------------------------------------------------------
# Dimension A — happy path
# ---------------------------------------------------------------------------


def test_atomic_write_text_happy_path(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    result = atomic_write_text(target, "hello world")
    assert result is True
    assert target.read_text(encoding="utf-8") == "hello world"


def test_atomic_write_bytes_happy_path(tmp_path: Path) -> None:
    target = tmp_path / "f.bin"
    result = atomic_write_bytes(target, b"hello world")
    assert result is True
    assert target.read_bytes() == b"hello world"


def test_write_over_existing_file_fully_replaces_content(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("old content that is much longer than the new one", encoding="utf-8")
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


# ---------------------------------------------------------------------------
# Dimension B — mkdir
# ---------------------------------------------------------------------------


def test_mkdir_false_missing_parent_raises(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "f.txt"
    with pytest.raises(OSError):
        atomic_write_text(target, "content", mkdir=False)


def test_mkdir_true_creates_nested_parent(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "f.txt"
    result = atomic_write_text(target, "content", mkdir=True)
    assert result is True
    assert target.read_text(encoding="utf-8") == "content"


def test_mkdir_false_missing_parent_raises_even_with_on_error_ignore(tmp_path: Path) -> None:
    # mkstemp/mkdir sit outside the try/cleanup block, so on_error="ignore" must not swallow
    # this OSError the way it swallows a failed write or replace.
    target = tmp_path / "missing" / "f.txt"
    with pytest.raises(OSError):
        atomic_write_text(target, "content", mkdir=False, on_error="ignore")


# ---------------------------------------------------------------------------
# Dimension C — on_error
# ---------------------------------------------------------------------------


def _no_tmp_files_left(directory: Path) -> bool:
    return not list(directory.glob("*.tmp"))


def test_on_error_raise_forced_failure_raises_and_leaves_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.txt"

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("forced failure")

    monkeypatch.setattr("os.fdopen", _boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "content", on_error="raise")
    assert _no_tmp_files_left(tmp_path)
    assert not target.exists()


def test_on_error_ignore_returns_false_no_temp_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.txt"
    target.write_text("original", encoding="utf-8")

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("forced failure")

    monkeypatch.setattr("os.fdopen", _boom)
    result = atomic_write_text(target, "replacement", on_error="ignore")
    assert result is False
    assert _no_tmp_files_left(tmp_path)
    assert target.read_text(encoding="utf-8") == "original"


# ---------------------------------------------------------------------------
# Dimension D — non-OSError exception mid-write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("on_error", ["raise", "ignore"])
def test_non_oserror_always_propagates(tmp_path: Path, on_error: str) -> None:
    target = tmp_path / "f.txt"

    # atomic_write_text/bytes fix their own write callback, so the only caller-triggerable
    # non-OSError is an encoding failure — a lone surrogate cannot be encoded as UTF-8.
    with pytest.raises(UnicodeEncodeError):
        atomic_write_text(
            target,
            "\udc80",
            encoding="utf-8",
            on_error=on_error,  # lone surrogate
        )
    assert _no_tmp_files_left(tmp_path)


def test_fdopen_non_oserror_failure_closes_fd_and_leaves_no_temp(tmp_path: Path) -> None:
    # An unknown codec name makes os.fdopen itself raise LookupError (not OSError), before the
    # fd is ever wrapped in a file object. This exercises the fd-leak fix's `except BaseException`
    # branch specifically: if the raw fd were left open, the tmp.unlink() cleanup below would be
    # blocked on Windows and a *.tmp file would survive.
    target = tmp_path / "f.txt"
    with pytest.raises(LookupError):
        atomic_write_text(target, "content", encoding="not-a-real-codec")
    assert _no_tmp_files_left(tmp_path)
    assert not target.exists()


@pytest.mark.parametrize("on_error", ["raise", "ignore"])
def test_atomic_write_bytes_type_error_propagates_regardless_of_on_error(
    tmp_path: Path, on_error: str
) -> None:
    # atomic_write_bytes shares _atomic_write's exception routing with atomic_write_text, but
    # dimension D above only ever exercises that routing through the text entry point. A str
    # payload makes the binary handle's write() raise TypeError, which must propagate through
    # both on_error modes exactly like the text-side UnicodeEncodeError does.
    target = tmp_path / "f.bin"
    with pytest.raises(TypeError):
        atomic_write_bytes(target, "not bytes", on_error=on_error)  # type: ignore[arg-type]
    assert _no_tmp_files_left(tmp_path)


# ---------------------------------------------------------------------------
# Dimension E — concurrency
# ---------------------------------------------------------------------------


def test_concurrent_writers_no_torn_read(tmp_path: Path) -> None:
    target = tmp_path / "shared.txt"
    payloads = [str(n) * 5000 for n in range(8)]
    errors: list[BaseException] = []

    def _write(payload: str) -> None:
        try:
            atomic_write_text(target, payload)
        except BaseException as exc:  # noqa: BLE001 - collected for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_write, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    final = target.read_text(encoding="utf-8")
    assert final in payloads
    assert _no_tmp_files_left(tmp_path)


# ---------------------------------------------------------------------------
# Dimension F — temp uniqueness
# ---------------------------------------------------------------------------


def test_temp_names_are_unique_across_concurrent_writers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile as tempfile_module

    seen_names: list[str] = []
    real_mkstemp = tempfile_module.mkstemp

    def _tracking_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        fd, name = real_mkstemp(*args, **kwargs)
        seen_names.append(name)
        return fd, name

    monkeypatch.setattr(tempfile_module, "mkstemp", _tracking_mkstemp)
    target = tmp_path / "shared.txt"
    threads = [
        threading.Thread(target=atomic_write_text, args=(target, str(n) * 100)) for n in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(seen_names) == 6
    assert len(set(seen_names)) == 6


# ---------------------------------------------------------------------------
# Dimension I — _replace_with_retry (deterministic, isolated from thread timing)
# ---------------------------------------------------------------------------


def test_replace_with_retry_succeeds_after_transient_permission_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.txt"
    target.write_text("old", encoding="utf-8")
    tmp = tmp_path / "f.txt.tmp"
    tmp.write_text("new", encoding="utf-8")

    real_replace = Path.replace
    calls = {"n": 0}

    def _flaky_replace(self: Path, dest: Path) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("transient")
        real_replace(self, dest)

    monkeypatch.setattr(Path, "replace", _flaky_replace)
    monkeypatch.setattr("time.sleep", lambda *_args: None)

    _replace_with_retry(tmp, target)

    assert calls["n"] == 3
    assert target.read_text(encoding="utf-8") == "new"


def test_replace_with_retry_exhausts_retries_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.txt"
    tmp = tmp_path / "f.txt.tmp"
    tmp.write_text("new", encoding="utf-8")
    calls = {"n": 0}

    def _always_denied(self: Path, dest: Path) -> None:
        calls["n"] += 1
        raise PermissionError("stuck")

    monkeypatch.setattr(Path, "replace", _always_denied)
    monkeypatch.setattr("time.sleep", lambda *_args: None)

    with pytest.raises(PermissionError):
        _replace_with_retry(tmp, target)
    assert calls["n"] == _REPLACE_RETRIES


def test_replace_with_retry_does_not_retry_non_permission_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.txt"
    tmp = tmp_path / "f.txt.tmp"
    tmp.write_text("new", encoding="utf-8")
    calls = {"n": 0}
    slept = {"called": False}

    def _not_found(self: Path, dest: Path) -> None:
        calls["n"] += 1
        raise FileNotFoundError("gone")

    monkeypatch.setattr(Path, "replace", _not_found)
    monkeypatch.setattr("time.sleep", lambda *_args: slept.__setitem__("called", True))

    with pytest.raises(FileNotFoundError):
        _replace_with_retry(tmp, target)
    assert calls["n"] == 1
    assert slept["called"] is False


# ---------------------------------------------------------------------------
# Dimension G — unicode/empty (text)
# ---------------------------------------------------------------------------


def _read_text_exact(path: Path) -> str:
    """Read back without newline translation, matching what atomic_write_text wrote."""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Zürich/Ünïcode",
        "x" * 100_000,
        "line one\nline two\r\nline three\rline four",
    ],
    ids=["empty", "unicode", "very-long", "mixed-newlines"],
)
def test_text_round_trips_exactly(tmp_path: Path, text: str) -> None:
    target = tmp_path / "f.txt"
    atomic_write_text(target, text)
    assert _read_text_exact(target) == text


# ---------------------------------------------------------------------------
# Dimension H — bytes edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [b"", b"\x00\x00\x00", bytes(range(256)), b"\xff" * 10_000],
    ids=["empty", "nul-bytes", "all-byte-values", "large-binary"],
)
def test_bytes_round_trip_exactly(tmp_path: Path, data: bytes) -> None:
    target = tmp_path / "f.bin"
    atomic_write_bytes(target, data)
    assert target.read_bytes() == data


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


@given(text=st.text())
@settings(max_examples=200)
def test_hypothesis_text_round_trip(tmp_path_factory: pytest.TempPathFactory, text: str) -> None:
    target = tmp_path_factory.mktemp("atomic-write") / "f.txt"
    atomic_write_text(target, text)
    assert _read_text_exact(target) == text


@given(data=st.binary())
@settings(max_examples=200)
def test_hypothesis_bytes_round_trip(tmp_path_factory: pytest.TempPathFactory, data: bytes) -> None:
    target = tmp_path_factory.mktemp("atomic-write") / "f.bin"
    atomic_write_bytes(target, data)
    assert target.read_bytes() == data
