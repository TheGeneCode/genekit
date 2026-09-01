"""Mechanical guards on ``ledger/CANDIDATES.md``, the one public document made of private evidence.

The ledger is public; every repo it cites is private. Its sighting and migration notes are written
by agents mid-task *inside* those private repos — the moment a disclosure is least likely to be
noticed — so the notes are the highest-risk prose in the project.

This file enforces the mechanical half of ``CHARTER.md`` § Ledger hygiene: the prohibited categories
a regex can actually catch (verbatim code fences, screaming-snake identifiers, config and env
filenames, absolute paths, foreign URLs, secret-shaped tokens, private-codebase scale metrics) plus
the structural caps on note length. It cannot judge whether a note leaks business logic, an
infrastructure name, or an unfixed defect stated in ordinary English.

**Passing this file is not evidence that a note is clean.** It is a backstop under the judgement
call the charter actually asks for, not a substitute for it.
"""

import datetime as dt
import re
import shutil
import string
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple
from unittest import mock

import pytest
from hypothesis import given
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = Path(__file__).resolve().parents[1]

LEDGER = REPO_ROOT / "ledger" / "CANDIDATES.md"
CHARTER = REPO_ROOT / "CHARTER.md"
GITIGNORE = REPO_ROOT / ".gitignore"

# CHARTER.md § Ledger hygiene: "A sighting note is capped at 400 characters"; migration and
# `adopt-pending` notes get "three lines, 400 characters".
SIGHTING_NOTE_MAX_CHARS = 400
MIGRATION_NOTE_MAX_CHARS = 400
MIGRATION_NOTE_MAX_LINES = 3

# The documented escape hatch: exact offending substring -> the written reason it is deliberate.
#
# An entry here is a *recorded decision* that a specific string is safe in public, not a way to
# quiet the suite. Adding one means writing down why, in prose a stranger could audit. Deleting the
# offending text from the ledger is almost always the right move instead.
# `test_every_allowlist_entry_is_still_present` fails on a stale entry, so the list cannot rot into
# a blanket exemption for text nobody remembers.
_ALLOWED_EXCEPTIONS: dict[str, str] = {}

# genekit's own tracked files. These are public by construction, so naming one discloses nothing;
# they are stripped before the config-filename scan rather than allowlisted per sighting.
_ALLOWED_FILENAMES = ("pyproject.toml",)


class LogicalItem(NamedTuple):
    """One markdown list item rejoined from its wrapped source lines.

    ``text`` is the item's content with the ``- `` marker dropped and runs of whitespace collapsed
    to single spaces; ``line_count`` is how many source lines the item occupied, which is what the
    charter's "three lines" cap is stated in.
    """

    text: str
    line_count: int


# --------------------------------------------------------------------------------------------
# Parsing helpers (pure; the hypothesis properties at the bottom of this file cover them)
# --------------------------------------------------------------------------------------------


def _split_header(text: str) -> tuple[str, str]:
    """Split the ledger into ``(header, entries)`` on the first line that is exactly ``---``.

    The header holds the fenced ``markdown`` template and the write-time rule blockquote — the one
    place in the file where a code fence is legitimate. ``entries`` is everything from the first
    ``## `` heading onward, which is the region every content detector treats as prose.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "---":
            header = "\n".join(lines[:index])
            rest = lines[index + 1 :]
            for offset, candidate in enumerate(rest):
                if candidate.startswith("## "):
                    return header, "\n".join(rest[offset:])
            return header, ""
    return text, ""


def _iter_entries(entries: str) -> Iterator[tuple[str, str]]:
    """Yield ``(slug, body)`` for each ``## `` heading in the entries region.

    The slug is the first whitespace-delimited token after ``## `` — the capability name the ledger
    keys entries by. The body is every line up to the next heading, headings excluded.
    """
    slug: str | None = None
    body: list[str] = []
    for line in entries.splitlines():
        if line.startswith("## "):
            if slug is not None:
                yield slug, "\n".join(body)
            slug = line[3:].strip().split()[0] if line[3:].strip() else ""
            body = []
        elif slug is not None:
            body.append(line)
    if slug is not None:
        yield slug, "\n".join(body)


def _unwrap_list_items(block: str) -> list[LogicalItem]:
    """Rejoin each markdown list item in ``block`` with its wrapped continuation lines.

    A continuation is an indented line that does not itself begin with ``- `` after its indent —
    markdown's soft-wrap. Without this, every length cap in the charter would be measured against
    an arbitrary editor wrap point rather than against the note.
    """
    items: list[LogicalItem] = []
    texts: list[list[str]] = []
    counts: list[int] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            texts.append([stripped[2:]])
            counts.append(1)
        elif texts:
            texts[-1].append(stripped)
            counts[-1] += 1
    for parts, count in zip(texts, counts, strict=True):
        items.append(LogicalItem(re.sub(r"\s+", " ", " ".join(parts)).strip(), count))
    return items


def _field_block(body: str, field: str) -> tuple[str, str]:
    """Return ``(marker_line, nested_block)`` for the top-level ``- <field>:`` list field."""
    lines = body.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if line.startswith(f"- {field}:"):
            start = index
            break
    if start is None:
        return "", ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip() and not lines[index].startswith((" ", "\t")):
            end = index
            break
    return lines[start], "\n".join(lines[start + 1 : end])


def _sighting_items(body: str) -> list[LogicalItem]:
    """Logical items nested under ``- sightings:``.

    The marker line carries no content of its own, so only the nested items are returned.
    """
    _, nested = _field_block(body, "sightings")
    return _unwrap_list_items(nested)


def _note_items(body: str) -> list[LogicalItem]:
    """Logical items under ``- notes:``, including its ``migrate:`` / ``adopt-pending:`` sub-items.

    Unlike ``- sightings:``, the ``- notes:`` marker line carries prose itself, so it is kept and
    unwrapped alongside the sub-items nested beneath it.
    """
    marker, nested = _field_block(body, "notes")
    if not marker:
        return []
    return _unwrap_list_items("\n".join([marker, nested]) if nested else marker)


def _scrub_allowlisted(text: str) -> str:
    """Remove every recorded exception from ``text``.

    Every content detector runs on scrubbed text, so an allowlist entry suppresses exactly its own
    substring and nothing else — it cannot blind a detector to a neighbouring violation.
    """
    for offender in _ALLOWED_EXCEPTIONS:
        text = text.replace(offender, "")
    return text


# --------------------------------------------------------------------------------------------
# Detectors. Each maps to one bullet of CHARTER.md § Ledger hygiene.
# --------------------------------------------------------------------------------------------

# "Verbatim code. No snippets, no fenced blocks" — applied to the entries region only, since the
# header's single ``markdown`` template fence is excluded by _split_header.
_FENCE = re.compile(r"^\s*```", re.MULTILINE)

# "Configuration or credential names. No env-var names, no config keys" — env vars and module-level
# constants both surface as SCREAMING_SNAKE identifiers.
_SCREAMING_SNAKE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")

# "Configuration or credential names ... no config filenames".
_CONFIG_FILENAME = re.compile(
    r"(?<![\w.])"
    r"(?:\.env(?:\.[\w-]+)?|[\w-]+\.(?:env|ini|cfg|conf|toml|ya?ml|json|plist))\b",
    re.IGNORECASE,
)

# "Infrastructure identifiers ... absolute filesystem paths, machine names."
_ABSOLUTE_PATH = re.compile(
    r"(?:\b[A-Za-z]:[\\/]"
    r"|(?<![\w.])/(?:home|Users|mnt|opt|etc|var|srv|tmp|root|private|Volumes|data|usr)/"
    r"|(?<![\w`])~[\\/])"
)

# "Infrastructure identifiers. No hostnames, internal URLs, endpoints" — every URL in the ledger
# must point back at this repo, the only public thing it is allowed to link to.
_URL = re.compile(r"https?://[^\s)>\]]+")
_OWN_REPO_URL_PREFIX = "https://github.com/TheGeneCode/genekit"

# "no secret material of any kind — not redacted, not truncated".
_SECRET_SHAPED = re.compile(
    r"(?:sk-ant-[A-Za-z0-9_-]{20,}"
    r"|sk-[A-Za-z0-9]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b[A-Fa-f0-9]{32,}\b)"
)

# "Scale metrics about a private codebase. No counts of tests, lines, modules, files, importers, or
# call sites." The ledger's own bookkeeping ("3 sightings", "2 repos") is not a scale metric about
# anyone's codebase, so the keyword list is deliberately closed rather than "digit + noun".
_SCALE_METRIC = re.compile(
    r"\b\d[\d,]*[\s-]*\+?[\s-]*"
    r"(?:tests?|passed|failed|lines?|modules?|files?|importers?|call sites?|LOC)\b",
    re.IGNORECASE,
)

# "A sighting is `<repo>/<path>:<lines> — <YYYY-MM-DD> — <note>`. The coordinates always stay."
# The separators are em dashes (U+2014); line ranges may use hyphens or en dashes (U+2013).
_SIGHTING_LINE = re.compile(
    r"^(?P<loc>\S+?)(?::(?P<lines>[\d,\u2013\-]+))?"
    r"\s+\u2014\s+(?P<date>\d{4}-\d{2}-\d{2})\s+\u2014\s+(?P<note>.+)$"
)


_LEDGER_TEXT = LEDGER.read_text(encoding="utf-8")
_LEDGER_HEADER, _LEDGER_ENTRIES = _split_header(_LEDGER_TEXT)
_ENTRY_BODIES = dict(_iter_entries(_LEDGER_ENTRIES))
_SLUGS = tuple(_ENTRY_BODIES)


# --------------------------------------------------------------------------------------------
# The real ledger
# --------------------------------------------------------------------------------------------


def test_the_ledger_parses_into_entries_at_all() -> None:
    """Every other test here is vacuous if the split or the heading scan silently found nothing.

    A future reformat of the ledger that broke ``---``/``## `` structure would otherwise turn this
    whole file green by parsing zero sightings.
    """
    assert _LEDGER_HEADER.strip(), "no header region found before the first '---' line"
    assert _SLUGS, "no '## ' entries found after the first '---' line"
    assert any(_sighting_items(body) for body in _ENTRY_BODIES.values()), "no sightings parsed"


def test_entries_region_contains_no_fenced_code_block() -> None:
    """Verbatim code is the bluntest disclosure a note can make.

    The header's ``markdown`` template fence is the only legitimate fence in the file, and
    ``_split_header`` puts it out of scope — so any fence in the entries region is a pasted snippet.
    """
    match = _FENCE.search(_LEDGER_ENTRIES)
    assert match is None, (
        "a code fence appears in the ledger's entries region; notes name mechanisms, not code"
    )


@pytest.mark.parametrize("slug", _SLUGS, ids=list(_SLUGS))
def test_every_sighting_line_matches_the_canonical_shape(slug: str) -> None:
    """``<repo>/<path>:<lines> — <YYYY-MM-DD> — <note>``, with em dashes.

    The coordinates are the evidence the rule of three runs on; a sighting that does not parse
    cannot be audited, and a hyphen quietly substituted for the em dash breaks every downstream
    reader that splits on the separator.
    """
    for item in _sighting_items(_ENTRY_BODIES[slug]):
        assert _SIGHTING_LINE.match(item.text) is not None, (
            f"{slug}: sighting does not match '<repo>/<path>:<lines> \u2014 <date> \u2014 <note>' "
            f"(em dash separators): {item.text!r}"
        )


@pytest.mark.parametrize("slug", _SLUGS, ids=list(_SLUGS))
def test_every_sighting_note_is_within_the_character_cap(slug: str) -> None:
    """Past 400 characters a note has stopped describing the capability and started describing
    the app it was found in — which is the private part.
    """
    for item in _sighting_items(_ENTRY_BODIES[slug]):
        match = _SIGHTING_LINE.match(item.text)
        if match is None:
            continue  # reported by test_every_sighting_line_matches_the_canonical_shape
        note = match.group("note")
        assert len(note) <= SIGHTING_NOTE_MAX_CHARS, (
            f"{slug}: sighting note is {len(note)} chars, cap is {SIGHTING_NOTE_MAX_CHARS}: "
            f"{note[:80]!r}..."
        )


@pytest.mark.parametrize("slug", _SLUGS, ids=list(_SLUGS))
def test_every_migration_note_is_within_three_lines_and_the_cap(slug: str) -> None:
    """Migration and ``adopt-pending`` notes get three lines and 400 characters.

    Longer reasoning belongs in the consumer's own repo, where it is private and where the people
    it concerns will actually look for it.
    """
    for item in _note_items(_ENTRY_BODIES[slug]):
        if not item.text.startswith(("migrate:", "adopt-pending:")):
            continue
        assert item.line_count <= MIGRATION_NOTE_MAX_LINES, (
            f"{slug}: migration note spans {item.line_count} lines, cap is "
            f"{MIGRATION_NOTE_MAX_LINES}: {item.text[:80]!r}..."
        )
        assert len(item.text) <= MIGRATION_NOTE_MAX_CHARS, (
            f"{slug}: migration note is {len(item.text)} chars, cap is "
            f"{MIGRATION_NOTE_MAX_CHARS}: {item.text[:80]!r}..."
        )


def test_no_screaming_snake_identifier_anywhere_in_the_ledger() -> None:
    """Env-var names and config keys both read as SCREAMING_SNAKE.

    The charter's instruction is to write *an env-var override naming the config location* and
    never the name itself, so no such identifier should survive anywhere in the file.
    """
    hits = _SCREAMING_SNAKE.findall(_scrub_allowlisted(_LEDGER_TEXT))
    assert not hits, f"config/env-var-shaped identifiers in the ledger: {hits}"


def test_no_config_or_env_filename() -> None:
    """No config filenames — not redacted, not truncated, not "obviously harmless".

    genekit's own tracked files are stripped first: naming a file that is already public in this
    repo discloses nothing about a private one.
    """
    text = _scrub_allowlisted(_LEDGER_TEXT)
    for filename in _ALLOWED_FILENAMES:
        text = text.replace(filename, "")
    hits = _CONFIG_FILENAME.findall(text)
    assert not hits, f"config/env filenames in the ledger: {hits}"


def test_no_absolute_filesystem_path() -> None:
    """Absolute paths are infrastructure identifiers: they leak machine and account names.

    A sighting's repo-relative coordinates say everything the rule of three needs.
    """
    hits = _ABSOLUTE_PATH.findall(_scrub_allowlisted(_LEDGER_TEXT))
    assert not hits, f"absolute filesystem paths in the ledger: {hits}"


def test_no_url_outside_this_repo() -> None:
    """The only public thing the ledger may link to is genekit itself.

    Any other URL is a hostname or endpoint belonging to something nobody reading this can see.
    """
    for url in _URL.findall(_scrub_allowlisted(_LEDGER_TEXT)):
        assert url.startswith(_OWN_REPO_URL_PREFIX), f"ledger links outside this repo: {url!r}"


def test_no_secret_shaped_token() -> None:
    """Secret material of any kind, including a truncated or "expired" one.

    The failure message deliberately reports only the offset: echoing the token into CI logs
    would republish the thing this test exists to keep out of a public file.
    """
    match = _SECRET_SHAPED.search(_scrub_allowlisted(_LEDGER_TEXT))
    offset = match.start() if match else -1
    assert match is None, f"secret-shaped token in the ledger at character offset {offset}"


def test_no_private_codebase_scale_metric() -> None:
    """Counts of tests, lines, modules, files, importers or call sites are free intelligence
    about a codebase nobody can read.

    The ledger's own bookkeeping is not a scale metric: ``3 sightings``, ``2 repos`` and ``5 MB``
    must not trip this, and ``TestScaleMetricRegex`` pins that.
    """
    hits = _SCALE_METRIC.findall(_scrub_allowlisted(_LEDGER_TEXT))
    assert not hits, f"scale metrics about a private codebase: {hits}"


# --------------------------------------------------------------------------------------------
# The rules the ledger and charter must keep stating
# --------------------------------------------------------------------------------------------

_LEDGER_HYGIENE_HEADING = "## Ledger hygiene"

_CHARTER_REQUIRED_PHRASES = (
    "coordinates always stay",
    "Verbatim code",
    "Configuration or credential names",
    "Infrastructure identifiers",
    "Business logic",
    "Scale metrics",
    "Unfixed defects",
    "New private repo names",
    "three lines, 400",
)

_LEDGER_HEADER_REQUIRED_PHRASES = (
    "This file is public",
    "coordinates always stay",
    "400 characters",
    "../CHARTER.md#ledger-hygiene",
)


def test_charter_has_the_ledger_hygiene_section() -> None:
    """The detectors above are only meaningful while the rule they mechanize is written down.

    Pin both the heading (which the ledger's anchor link depends on) and every prohibited category,
    so a future edit cannot quietly drop a bullet and leave a test enforcing a rule nobody states.
    """
    charter = CHARTER.read_text(encoding="utf-8")
    assert _LEDGER_HYGIENE_HEADING in charter, "CHARTER.md has no '## Ledger hygiene' section"
    section = charter.split(_LEDGER_HYGIENE_HEADING, 1)[1].split("\n## ", 1)[0]
    for phrase in _CHARTER_REQUIRED_PHRASES:
        assert phrase in section, f"CHARTER.md § Ledger hygiene no longer says {phrase!r}"


def test_ledger_header_carries_the_write_time_rule() -> None:
    """The rule has to be legible at the moment of writing, not only in a charter nobody opens.

    An agent appending a sighting mid-task inside a private repo reads the top of this file and
    nothing else, so the header must restate the constraint and link to the full rule.
    """
    for phrase in _LEDGER_HEADER_REQUIRED_PHRASES:
        assert phrase in _LEDGER_HEADER, f"ledger header no longer says {phrase!r}"


def test_every_allowlist_entry_is_still_present() -> None:
    """A stale allowlist entry is a standing exemption for text nobody remembers writing.

    Vacuously true while ``_ALLOWED_EXCEPTIONS`` is empty; the point is that it stops being
    vacuous the moment someone records an exception and then prunes the line it covered.
    """
    for offender, reason in _ALLOWED_EXCEPTIONS.items():
        assert offender in _LEDGER_TEXT, (
            f"allowlisted string {offender!r} is no longer in the ledger; delete the entry "
            f"(recorded reason: {reason})"
        )


def test_allowlist_check_actually_fails_for_a_stale_entry() -> None:
    """``test_every_allowlist_entry_is_still_present`` is vacuously true while the dict is empty.

    That test has exactly one job: fail when someone allowlists a string, then deletes the ledger
    text it covered without deleting the allowlist entry. Exercise the same assertion this file's
    real test makes, against a key guaranteed absent from the ledger, to prove it is a real check
    and not a no-op that would pass on any input.
    """
    stale_key = "THIS_KEY_IS_DELIBERATELY_ABSENT_FROM_THE_LEDGER_TEXT"
    assert stale_key not in _LEDGER_TEXT, "test setup invalid: key unexpectedly present"
    with pytest.raises(AssertionError):
        assert stale_key in _LEDGER_TEXT, (
            f"allowlisted string {stale_key!r} is no longer in the ledger; delete the entry"
        )


def test_docs_untracked_check_skips_cleanly_without_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole test must skip, not fail, when ``git`` is unavailable on ``PATH``.

    A hard failure here would break the suite in a git-less sandbox for a check that has nothing
    to do with the code under test; ``pytest.skip`` is the only correct outcome.
    """
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(pytest.skip.Exception):
        test_docs_stays_untracked_and_ignored()


def test_docs_stays_untracked_and_ignored() -> None:
    """``docs/`` holds local planning notes that name private repos in prose the ledger forbids.

    Ignoring it is the only thing keeping that material out of a public repo, and a stray
    ``git add -f`` would not announce itself, so check both the rule and the actual index.
    """
    ignored = [line.strip() for line in GITIGNORE.read_text(encoding="utf-8").splitlines()]
    assert "docs/" in ignored, ".gitignore no longer ignores 'docs/'"

    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    result = subprocess.run(
        ["git", "ls-files", "docs"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"git ls-files failed: {result.stderr.strip()!r}")
    assert result.stdout.strip() == "", (
        f"docs/ is tracked despite being gitignored: {result.stdout.strip()!r}"
    )


# --------------------------------------------------------------------------------------------
# Regex self-tests. A detector nobody tests is a detector nobody can trust to stay honest.
# --------------------------------------------------------------------------------------------


class TestScreamingSnakeRegex:
    """``_SCREAMING_SNAKE`` must catch env-var and config-key shapes without eating the ledger's
    ordinary vocabulary: snake_case symbol names, versions, and file paths all appear in real
    sightings and none of them are configuration.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "ERROR_LOG_PATH",
            "AWS_SECRET_ACCESS_KEY",
            "an override named DATABASE_URL points at it",
            "LOG_LEVEL=debug",
            "APP_ENV_2 was read at import time",
        ],
        ids=[
            "error-log-path",
            "aws-secret-access-key",
            "in-prose",
            "with-assignment",
            "trailing-digits",
        ],
    )
    def test_catches_known_bad_identifiers(self, text: str) -> None:
        assert _SCREAMING_SNAKE.search(text) is not None, f"expected a match in {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "configure_logging",
            "dedicated_file_logger",
            "py-v0.2.0",
            "genekit[rich]",
            "MeadowLark/src/progress_smoothing.py",
            "yt-dlp",
            "2026-07-17",
            "pyproject.toml",
            "TTS/articleReader.py:48-70,204-210",
            "a hand-rolled `_DENVER` module constant",
            "ProgressSmoother derives speed and ETA",
        ],
        ids=[
            "snake-case-symbol",
            "snake-case-symbol-long",
            "version-tag",
            "extra-name",
            "repo-relative-path",
            "hyphenated-tool-name",
            "iso-date",
            "own-tracked-file",
            "sighting-coordinates",
            "leading-underscore-single-word",
            "camel-case-class",
        ],
    )
    def test_does_not_flag_ledger_vocabulary(self, text: str) -> None:
        assert _SCREAMING_SNAKE.search(text) is None, f"unexpected match in {text!r}"


class TestConfigFilenameRegex:
    """``_CONFIG_FILENAME`` must catch the filename shapes a note might drop in passing, while
    leaving Python module paths — which sightings are *made of* — alone.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "settings.yaml",
            ".env.local",
            "reads .env at startup",
            "config.ini",
            "app.conf",
            "credentials.json",
            "prod.yml",
            "Info.plist",
            "pipeline.cfg",
            "SETTINGS.YAML",
        ],
        ids=[
            "yaml",
            "dotenv-variant",
            "bare-dotenv-in-prose",
            "ini",
            "conf",
            "json",
            "yml",
            "plist",
            "cfg",
            "uppercase",
        ],
    )
    def test_catches_known_bad_filenames(self, text: str) -> None:
        assert _CONFIG_FILENAME.search(text) is not None, f"expected a match in {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "MeadowLark/src/progress_smoothing.py",
            "remove-the-bloat/src/remove_the_bloat/logging_setup.py",
            "personal-agents/packages/agents-core/src/agents_core/config.py",
            "py-v0.2.0",
            "genekit[rich]",
            "configure_logging",
            "yt-dlp",
            "2026-07-17",
            "3 sightings across 2 repos",
            "an env-var override naming the config location",
        ],
        ids=[
            "python-module-path",
            "python-module-path-nested",
            "config-module-is-a-path-not-a-filename",
            "version-tag",
            "extra-name",
            "snake-case-symbol",
            "hyphenated-tool-name",
            "iso-date",
            "ledger-bookkeeping",
            "charter-sanctioned-phrasing",
        ],
    )
    def test_does_not_flag_ledger_vocabulary(self, text: str) -> None:
        assert _CONFIG_FILENAME.search(text) is None, f"unexpected match in {text!r}"

    def test_own_tracked_filenames_are_stripped_rather_than_exempted_by_the_regex(self) -> None:
        """``pyproject.toml`` genuinely *is* a config filename and the regex says so.

        It is excluded by ``_ALLOWED_FILENAMES`` stripping instead, so the regex keeps catching
        ``settings.toml`` in a private repo. Pin that division of labour.
        """
        assert _CONFIG_FILENAME.search("pyproject.toml") is not None
        text = "pyproject.toml"
        for filename in _ALLOWED_FILENAMES:
            text = text.replace(filename, "")
        assert _CONFIG_FILENAME.search(text) is None


class TestAbsolutePathRegex:
    """``_ABSOLUTE_PATH`` must catch Windows drives, POSIX system roots and ``~`` expansions
    without touching the repo-relative coordinates every sighting is built from.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "C:\\Users\\etreq\\dev\\app",
            "/home/gene/app",
            "D:/work/repo",
            "~/projects/thing",
            "~\\projects\\thing",
            "/Users/gene/dev/thing",
            "/etc/hosts",
            "/var/log/app.log",
            "/opt/tooling/bin",
            "it writes to C:/temp/output",
            "/tmp/scratch.log",
            "/root/.ssh/config",
            "/private/etc/hosts",
            "/Volumes/backup/app",
            "/data/app.db",
            "/usr/local/bin/app",
        ],
        ids=[
            "windows-backslash",
            "posix-home",
            "windows-forward-slash",
            "tilde-posix",
            "tilde-windows",
            "posix-users",
            "posix-etc",
            "posix-var",
            "posix-opt",
            "in-prose",
            "posix-tmp",
            "posix-root",
            "macos-private",
            "macos-volumes",
            "posix-data",
            "posix-usr",
        ],
    )
    def test_catches_known_bad_paths(self, text: str) -> None:
        assert _ABSOLUTE_PATH.search(text) is not None, f"expected a match in {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "remove-the-bloat/src/remove_the_bloat/logging_setup.py",
            "MeadowLark/src/progress_smoothing.py",
            "personal-agents/packages/agents-core/src/agents_core/tz.py",
            "TTS/articleReader.py:48-70,204-210",
            "pyproject.toml",
            "py-v0.2.0",
            "genekit[rich]",
            "yt-dlp",
            "2026-07-17",
            "5 MB",
            "src/url_utils.py",
            "see [../CHARTER.md](../CHARTER.md) for the rule",
        ],
        ids=[
            "repo-relative-path",
            "repo-relative-path-short",
            "repo-relative-path-deep",
            "sighting-coordinates",
            "own-tracked-file",
            "version-tag",
            "extra-name",
            "hyphenated-tool-name",
            "iso-date",
            "size-figure",
            "relative-module-path",
            "relative-markdown-link",
        ],
    )
    def test_does_not_flag_ledger_vocabulary(self, text: str) -> None:
        assert _ABSOLUTE_PATH.search(text) is None, f"unexpected match in {text!r}"


class TestSecretShapedRegex:
    """``_SECRET_SHAPED`` covers the token prefixes and the long-hex shape a pasted credential or
    digest takes. Short hex-looking words in ordinary prose must survive.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "ghp_" + "a" * 32,
            "sk-" + "B" * 24,
            "gho_" + "z" * 24,
            "AKIAIOSFODNN7EXAMPLE",
            "-----BEGIN RSA PRIVATE KEY-----",
            "-----BEGIN PRIVATE KEY-----",
            "d41d8cd98f00b204e9800998ecf8427e",
            "token ghs_" + "9" * 30 + " was rotated",
            "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 2 + "-AbCdEfGh",
        ],
        ids=[
            "github-personal-token",
            "sk-style-key",
            "github-oauth-token",
            "aws-access-key-id",
            "pem-rsa-header",
            "pem-generic-header",
            "md5-length-hex",
            "in-prose",
            "anthropic-style-key-with-hyphens",
        ],
    )
    def test_catches_known_bad_tokens(self, text: str) -> None:
        assert _SECRET_SHAPED.search(text) is not None, f"expected a match in {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "2026-07-17",
            "py-v0.2.0",
            "genekit[rich]",
            "configure_logging",
            "yt-dlp",
            "5 MB",
            "deadbeef",
            "MeadowLark/src/progress_smoothing.py",
            "3 sightings across 2 repos",
            "pyproject.toml",
        ],
        ids=[
            "iso-date",
            "version-tag",
            "extra-name",
            "snake-case-symbol",
            "hyphenated-tool-name",
            "size-figure",
            "short-hex-word",
            "repo-relative-path",
            "ledger-bookkeeping",
            "own-tracked-file",
        ],
    )
    def test_does_not_flag_ledger_vocabulary(self, text: str) -> None:
        assert _SECRET_SHAPED.search(text) is None, f"unexpected match in {text!r}"


class TestScaleMetricRegex:
    """``_SCALE_METRIC`` is the detector most at risk of false positives: the ledger counts things
    constantly. Its keyword list is closed on purpose, and these cases are the reason.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "3127 passed",
            "~30 importers",
            "1,204 lines",
            "12 modules",
            "8 files",
            "40 call sites",
            "2 tests",
            "5 failed",
            "3,000 LOC",
            "roughly 60+ call sites remain",
            "900 Lines of duplicated setup",
            "a 40-line function",
            "a 900-line module",
            "12-file diff",
            "3-module refactor",
        ],
        ids=[
            "test-run-summary",
            "importer-count",
            "line-count-with-comma",
            "module-count",
            "file-count",
            "call-site-count",
            "test-count",
            "failure-count",
            "loc-count",
            "plus-suffix",
            "case-insensitive",
            "hyphenated-line-count",
            "hyphenated-line-count-large",
            "hyphenated-file-count",
            "hyphenated-module-count",
        ],
    )
    def test_catches_known_bad_metrics(self, text: str) -> None:
        assert _SCALE_METRIC.search(text) is not None, f"expected a match in {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "3 sightings across 2 repos",
            "5 MB",
            "py-v0.2.0",
            "2026-07-17",
            "1 of 3 sightings",
            "2 sightings across 2 repos \u2014 1 more needed",
            "0 repos short of the 2-repo requirement",
            "three lines, 400 characters",
            "yt-dlp",
            "a window of clamp(elapsed * 0.25, 3s, 30s)",
            "TTS/articleReader.py:48-70,204-210",
            "spans file boundaries so the rate survives the stream switch",
        ],
        ids=[
            "rule-of-three-bookkeeping",
            "size-figure",
            "version-tag",
            "iso-date",
            "progress-count",
            "sightings-and-repos",
            "repo-shortfall",
            "charter-cap-phrasing",
            "hyphenated-tool-name",
            "numeric-window-bounds",
            "sighting-coordinates",
            "file-noun-without-a-count",
        ],
    )
    def test_does_not_flag_ledger_vocabulary(self, text: str) -> None:
        assert _SCALE_METRIC.search(text) is None, f"unexpected match in {text!r}"


class TestSightingLineRegex:
    """``_SIGHTING_LINE`` is a shape validator, so its polarity is inverted: a match is the good
    outcome. What it must reject is a sighting whose coordinates or date have decayed.
    """

    @pytest.mark.parametrize(
        ("text", "expected_loc", "expected_lines", "expected_date"),
        [
            (
                "remove-the-bloat/src/remove_the_bloat/logging_setup.py \u2014 2026-07-16 \u2014 "
                "rich console handler plus scoped file routing.",
                "remove-the-bloat/src/remove_the_bloat/logging_setup.py",
                None,
                "2026-07-16",
            ),
            (
                "Plex/randomNextEpisode.py:15 \u2014 2026-07-16 \u2014 a one-liner.",
                "Plex/randomNextEpisode.py",
                "15",
                "2026-07-16",
            ),
            (
                "TTS/articleReader.py:48-70,204-210 \u2014 2026-07-16 \u2014 a dedicated logger.",
                "TTS/articleReader.py",
                "48-70,204-210",
                "2026-07-16",
            ),
            (
                "remove-the-bloat \u2014 2026-07-16 \u2014 a file plus an env-var override.",
                "remove-the-bloat",
                None,
                "2026-07-16",
            ),
            (
                "MeadowLark/src/progress_smoothing.py \u2014 2026-08-26 \u2014 a deque of samples.",
                "MeadowLark/src/progress_smoothing.py",
                None,
                "2026-08-26",
            ),
            (
                "app/mod.py:31\u201345 \u2014 2026-07-17 \u2014 an en-dashed line range.",
                "app/mod.py",
                "31\u201345",
                "2026-07-17",
            ),
        ],
        ids=[
            "path-without-line-range",
            "single-line-number",
            "multi-range-with-comma",
            "repo-only-coordinates",
            "recent-sighting",
            "en-dashed-range",
        ],
    )
    def test_matches_canonical_sighting_lines(
        self, text: str, expected_loc: str, expected_lines: str | None, expected_date: str
    ) -> None:
        match = _SIGHTING_LINE.match(text)
        assert match is not None, f"expected a match in {text!r}"
        assert match.group("loc") == expected_loc
        assert match.group("lines") == expected_lines
        assert match.group("date") == expected_date
        assert match.group("note")

    @pytest.mark.parametrize(
        "text",
        [
            "remove-the-bloat/src/mod.py - 2026-07-16 - hyphens instead of em dashes.",
            "remove-the-bloat/src/mod.py \u2013 2026-07-16 \u2013 en dashes instead of em dashes.",
            "remove-the-bloat/src/mod.py \u2014 16-07-2026 \u2014 a day-first date.",
            "remove-the-bloat/src/mod.py \u2014 2026-07-16",
            "remove-the-bloat/src/mod.py \u2014 2026-07-16 \u2014 ",
            "\u2014 2026-07-16 \u2014 no coordinates at all.",
            "remove-the-bloat/src/mod.py \u2014 2026-7-16 \u2014 an unpadded month.",
            "a note with no coordinates, date, or separators",
        ],
        ids=[
            "hyphen-separators",
            "en-dash-separators",
            "day-first-date",
            "missing-note",
            "empty-note",
            "missing-coordinates",
            "unpadded-date",
            "prose-only",
        ],
    )
    def test_rejects_malformed_sighting_lines(self, text: str) -> None:
        assert _SIGHTING_LINE.match(text) is None, f"unexpected match in {text!r}"


# --------------------------------------------------------------------------------------------
# Properties of the parsing helpers
# --------------------------------------------------------------------------------------------

_LOC_ALPHABET = string.ascii_letters + string.digits + "-_./"
_KEY_ALPHABET = string.ascii_uppercase + "_"
_PROSE_ALPHABET = string.ascii_lowercase + " "
_BLOCK_ALPHABET = string.ascii_letters + string.digits


@given(
    loc=st.text(alphabet=_LOC_ALPHABET, min_size=1, max_size=40),
    date=st.dates(),
    note=st.text(min_size=1, max_size=120).filter(
        lambda s: s.strip() == s
        and s != ""
        and "\n" not in s
        and "\r" not in s
        and "\u2014" not in s
    ),
)
def test_canonical_sighting_line_always_parses(loc: str, date: dt.date, note: str) -> None:
    """Any line assembled to the canonical shape parses and round-trips its three fields.

    The hand-written cases above prove the regex accepts the sightings that exist today; this
    proves it accepts the ones that do not exist yet, whatever unicode a future note contains.
    """
    iso = date.isoformat()
    line = f"{loc} \u2014 {iso} \u2014 {note}"
    match = _SIGHTING_LINE.match(line)
    assert match is not None, f"canonical line failed to parse: {line!r}"
    assert match.group("loc") == loc
    assert match.group("date") == iso
    assert match.group("note") == note


@given(
    items=st.lists(
        st.tuples(
            st.text(alphabet=_BLOCK_ALPHABET, min_size=1, max_size=12),
            st.lists(st.text(alphabet=_BLOCK_ALPHABET, min_size=1, max_size=12), max_size=3),
        ),
        min_size=1,
        max_size=5,
    ),
    indent=st.integers(min_value=0, max_value=4),
)
def test_unwrap_is_idempotent_and_preserves_item_count(
    items: list[tuple[str, list[str]]], indent: int
) -> None:
    """One logical item per ``- `` line, however the source happened to wrap.

    Idempotence matters because every length cap is measured on unwrapped text: if unwrapping an
    already-unwrapped item changed it, the caps would depend on the editor's wrap column.
    """
    pad = " " * indent
    lines: list[str] = []
    for head, continuations in items:
        lines.append(f"{pad}- {head}")
        lines.extend(f"{pad}  {continuation}" for continuation in continuations)

    unwrapped = _unwrap_list_items("\n".join(lines))
    assert len(unwrapped) == len(items)
    for item, (head, continuations) in zip(unwrapped, items, strict=True):
        assert item.text == " ".join([head, *continuations])
        assert item.line_count == 1 + len(continuations)

    again = _unwrap_list_items("\n".join(f"- {item.text}" for item in unwrapped))
    assert [item.text for item in again] == [item.text for item in unwrapped]


def test_unwrap_handles_the_real_ledgers_two_space_nested_indent() -> None:
    """A hand-written regression pinning the exact indent shape ``ledger/CANDIDATES.md`` uses.

    The hypothesis property above draws continuations from a hyphen-free alphabet, so it cannot
    catch a continuation line that happens to start with ``- `` (which the parser would treat as a
    new item, not a wrapped line) or a deeper 4-space nested indent under a 2-space list. Both
    shapes appear in the real file's ``notes`` block, so pin them explicitly.
    """
    block = (
        "  - notes: Promoted 2026-07-16 as `genekit.logging`. The originating app's domain\n"
        "    vocabulary was stripped for the library API; rich sits behind the\n"
        "    `genekit[rich]` extra.\n"
        "    - migrate: remove-the-bloat done 2026-07-16 — consumed through a re-export\n"
        "      shim keeping the app's original names, so no call site changed.\n"
        "    - migrate: Plex done 2026-07-16 — no shim, required raising the app's\n"
        "      requires-python floor.\n"
    )
    items = _unwrap_list_items(block)
    assert len(items) == 3
    assert items[0].text.startswith("notes: Promoted 2026-07-16")
    assert "rich sits behind" in items[0].text
    assert items[0].line_count == 3
    assert items[1].text.startswith("migrate: remove-the-bloat")
    assert "shim keeping the app's original names" in items[1].text
    assert items[1].line_count == 2
    assert items[2].text.startswith("migrate: Plex")
    assert items[2].line_count == 2


@given(
    key=st.text(alphabet=_KEY_ALPHABET, min_size=1, max_size=20),
    prefix=st.text(alphabet=_PROSE_ALPHABET, max_size=40),
    suffix=st.text(alphabet=_PROSE_ALPHABET, max_size=40),
)
def test_scrub_removes_exactly_the_allowlisted_substrings(
    key: str, prefix: str, suffix: str
) -> None:
    """Scrubbing removes the allowlisted substring and nothing else.

    The key and the surrounding prose are drawn from disjoint alphabets, so "nothing else" is
    checkable: whatever survives must be exactly the text that was never allowlisted.
    """
    exceptions = {key: "deliberate: exercised by this property test only"}
    with mock.patch.dict(_ALLOWED_EXCEPTIONS, exceptions, clear=True):
        scrubbed = _scrub_allowlisted(prefix + key + suffix)
    assert key not in scrubbed
    assert scrubbed == prefix + suffix
