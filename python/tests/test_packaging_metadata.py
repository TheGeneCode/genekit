"""Guards on the published package metadata: license wiring, attribution, and README portability.

These assertions read the *installed* dist-info, so they only reflect ``pyproject.toml`` after a
``uv sync``. See the plan's Step 4.
"""

import re
import subprocess
import sys
import zipfile
from datetime import datetime
from importlib.metadata import distribution, metadata
from pathlib import Path
from urllib.parse import urlparse

import pytest

# tomllib landed in the stdlib in 3.11; the package floor is 3.10, so fall back to the
# tomli backport (a dev-only dependency, gated by the same version marker) below it.
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = Path(__file__).resolve().parents[1]


def _load_pyproject() -> dict:
    """Parse ``pyproject.toml`` directly, independent of any installed/synced state.

    The tests below that read ``importlib.metadata`` only reflect ``pyproject.toml`` as of the last
    ``uv sync`` — they can pass on stale metadata if the file was edited afterwards. These
    source-level checks catch config drift (typos, wrong TOML shape) before install even happens.
    """
    with (PYTHON_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def test_license_expression_is_mit() -> None:
    assert metadata("genekit")["License-Expression"] == "MIT"


def test_license_file_recorded_without_parent_traversal() -> None:
    recorded = metadata("genekit").get_all("License-File")
    assert recorded == ["LICENSE"]
    assert all(".." not in entry for entry in recorded)


def test_license_text_ships_inside_the_installed_distribution() -> None:
    files = distribution("genekit").files or []
    licenses = [f for f in files if f.name == "LICENSE"]
    assert licenses, "no LICENSE recorded in the installed distribution"
    assert any("licenses" in f.parts for f in licenses)


def test_author_is_attributed_without_an_email() -> None:
    md = metadata("genekit")
    assert md["Author"] == "TheGeneCode"
    assert md.get("Author-email") is None


def test_repository_url_is_published() -> None:
    urls = metadata("genekit").get_all("Project-URL") or []
    assert any(u.startswith("Repository,") for u in urls)


def test_root_and_python_license_files_are_identical() -> None:
    root = REPO_ROOT / "LICENSE"
    packaged = PYTHON_ROOT / "LICENSE"
    assert packaged.read_bytes() == root.read_bytes()


_RELATIVE_PARENT_LINK = re.compile(
    r"""
    \]\(\s*\.\.[/\\]      # inline markdown link:      ](../foo)   or  ](..\foo)
    | \]:\s*\.\.[/\\]     # reference-style link target: [text]: ../foo
    | href=['"]\.\.[/\\]  # raw HTML:                    href="../foo"
    """,
    re.IGNORECASE | re.VERBOSE,
)


def test_packaged_readme_has_no_relative_parent_links() -> None:
    """Broader than a literal ``](../`` substring check: also catches reference-style link
    targets (``[text]: ../foo``), raw HTML (``href="../foo"``), and Windows-style backslash
    separators (``](..\\foo)``) — none of which contain the literal ``](../`` the narrower
    substring check looks for, but all of which resolve to nothing once this file is embedded
    verbatim as wheel METADATA ``Description``.
    """
    readme = (PYTHON_ROOT / "README.md").read_text(encoding="utf-8")
    match = _RELATIVE_PARENT_LINK.search(readme)
    assert match is None, f"relative parent-path link found in README.md: {match.group(0)!r}"


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a fresh wheel with ``uv build --wheel`` and hand back its path.

    The other tests in this file read ``importlib.metadata``/``importlib.metadata.distribution``,
    which reflect the *installed* package — here that's an editable install (see
    ``genekit-0.2.0.dist-info/direct_url.json`` / the ``.pth`` shim), not a real wheel. Editable
    installs can diverge from what an actual wheel build produces, so the wheel-content tests below
    inspect the built zip directly instead of trusting installed dist-info.
    """
    out_dir = tmp_path_factory.mktemp("wheel-build")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=PYTHON_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one built wheel, got {wheels}"
    return wheels[0]


def test_wheel_zip_has_no_path_traversal_and_ships_license_under_licenses(
    built_wheel: Path,
) -> None:
    with zipfile.ZipFile(built_wheel) as zf:
        names = zf.namelist()
    # Zip-slip / path-traversal guard on the *actual build output* — the ``license-files =
    # ["../LICENSE"]`` alternative that was tried and rejected during this change would have
    # produced a namelist entry that escapes the wheel root.
    assert all(".." not in entry for entry in names)
    assert all(not entry.startswith("/") for entry in names)
    license_entries = [n for n in names if n.endswith("/LICENSE") or n == "LICENSE"]
    assert license_entries, f"no LICENSE entry in built wheel: {names}"
    assert all("licenses/" in entry for entry in license_entries)


def test_wheel_metadata_fields_match_expectations(built_wheel: Path) -> None:
    """Read METADATA out of the freshly built wheel zip directly — independent of whatever the
    ``.venv``'s editable install happens to have recorded.
    """
    with zipfile.ZipFile(built_wheel) as zf:
        metadata_name = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
        content = zf.read(metadata_name).decode("utf-8")
    lines = content.splitlines()
    assert "License-Expression: MIT" in lines
    assert "License-File: LICENSE" in lines
    assert "Author: TheGeneCode" in lines
    assert not any(line.startswith("Author-email:") for line in lines)
    assert any(line.startswith("Project-URL: Repository,") for line in lines)
    assert not any(line.startswith("Classifier: License ::") for line in lines)


def test_installed_distribution_files_is_not_none() -> None:
    """``Distribution.files`` can be ``None`` for some installers (no RECORD/SOURCES present),
    which is why other tests in this module guard with ``distribution("genekit").files or []``.
    Pin the current (non-``None``) behavior explicitly here, so a future install-layout change that
    stops populating RECORD is caught directly instead of letting those other tests degrade to a
    vacuous pass over an empty list.
    """
    files = distribution("genekit").files
    assert files is not None, "distribution('genekit').files is None; RECORD may be missing"
    assert len(files) > 0


def test_pyproject_license_is_exact_spdx_mit_string() -> None:
    project = _load_pyproject()["project"]
    # PEP 639: must be a bare SPDX expression string, not e.g. "mit", "MIT License", or a table.
    assert project["license"] == "MIT"


def test_pyproject_license_files_glob_has_no_path_traversal() -> None:
    project = _load_pyproject()["project"]
    license_files = project["license-files"]
    assert license_files == ["LICENSE"]
    assert all(".." not in entry and not entry.startswith("/") for entry in license_files)


def test_pyproject_authors_is_name_only_with_no_email_key() -> None:
    project = _load_pyproject()["project"]
    assert project["authors"] == [{"name": "TheGeneCode"}]


def test_pyproject_project_urls_are_well_formed_https_github() -> None:
    urls = _load_pyproject()["project"]["urls"]
    assert urls, "no [project.urls] table declared"
    for name, url in urls.items():
        assert url == url.strip(), f"{name} URL has leading/trailing whitespace: {url!r}"
        parsed = urlparse(url)
        assert parsed.scheme == "https", f"{name} URL is not https: {url!r}"
        assert parsed.netloc == "github.com", f"{name} URL is not on github.com: {url!r}"


def test_license_copyright_year_and_holder_are_sane() -> None:
    text = (PYTHON_ROOT / "LICENSE").read_text(encoding="utf-8")
    match = re.search(r"^Copyright \(c\) (\d{4}) (.+)$", text, re.MULTILINE)
    assert match is not None, "no 'Copyright (c) YYYY Holder' line found in LICENSE"
    year, holder = int(match.group(1)), match.group(2).strip()
    assert 2020 <= year <= datetime.now().year, f"implausible copyright year: {year}"
    assert holder == _load_pyproject()["project"]["authors"][0]["name"]


def test_changelog_unreleased_section_is_present_and_non_empty() -> None:
    changelog = (PYTHON_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## Unreleased\s*\n(.*?)(?=\n## |\Z)", changelog, re.MULTILINE | re.DOTALL)
    assert match is not None, "no '## Unreleased' section found in CHANGELOG.md"
    assert match.group(1).strip(), "'## Unreleased' section is present but empty"


def test_pyproject_requires_python_is_the_documented_floor() -> None:
    """The floor is a promise to consumers, not an implementation detail: every app that adopts
    genekit inherits it, and an overshoot silently forces those apps up an interpreter. Pinning the
    exact string here means any future widening or re-narrowing has to be a deliberate edit to a
    test that says what the floor is, rather than a quiet side effect of a dependency bump.
    """
    assert _load_pyproject()["project"]["requires-python"] == ">=3.10"


def test_dev_group_carries_a_tomli_fallback_below_the_tomllib_floor() -> None:
    """``tomllib`` only entered the stdlib in 3.11, but this very module parses TOML and the
    package floor is 3.10 — without the marker-gated ``tomli`` backport in the dev group, the whole
    file fails to import on the floor leg, silently dropping every packaging assertion on exactly
    the interpreter the floor exists to prove. Guard the fallback against being tidied away.
    """
    dev = _load_pyproject()["dependency-groups"]["dev"]
    fallbacks = [entry for entry in dev if entry.startswith("tomli")]
    assert fallbacks, f"no tomli entry in the dev dependency group: {dev}"
    markers = [entry.partition(";")[2].replace('"', "'") for entry in fallbacks]
    assert any("python_version < '3.11'" in marker for marker in markers), (
        f"tomli is present but not gated on python_version < '3.11': {fallbacks}"
    )


def test_wheel_declares_the_floor_in_its_metadata(built_wheel: Path) -> None:
    """The source TOML declaring a floor and the built artifact carrying it are two different
    claims — pip and uv read the wheel's ``Requires-Python``, not ``pyproject.toml``. Read it back
    out of a real hatchling build so a packaging-backend or config change that drops the field is
    caught here rather than by a consumer resolving genekit onto an interpreter it cannot run on.
    """
    with zipfile.ZipFile(built_wheel) as zf:
        metadata_name = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
        content = zf.read(metadata_name).decode("utf-8")
    lines = content.splitlines()
    assert "Requires-Python: >=3.10" in lines


_CI_PYTHON_VERSION_LIST = re.compile(r"python-version:\s*\[([^\]]*)\]")
_CI_PYTHON_VERSION_SCALAR = re.compile(r"""python-version:\s*["'](\d+\.\d+)["']""")
_CI_QUOTED_VERSION = re.compile(r"""["'](\d+\.\d+)["']""")


def test_ci_matrix_actually_exercises_the_declared_floor() -> None:
    """A declared floor that no CI leg runs is a claim, not a fact — the repo's own CI notes say so.
    This test is the link between the two: it reads the floor out of ``requires-python`` (rather
    than repeating the literal, so the two cannot drift) and proves the test job's matrix names it.

    It is written to fail loudly rather than emptily. A workflow reformat that broke the extraction
    would otherwise leave a green no-op — the same degradation
    ``test_installed_distribution_files_is_not_none`` guards against — so both slice boundaries and
    a plausible version count are asserted before the membership check. The slice matters too:
    the ``lint`` and ``tag-matches-version`` jobs carry their own unrelated interpreter pins, and
    searching the whole file would let those satisfy this assertion even if the matrix named
    nothing at all.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    start = re.search(r"^  test:$", workflow, re.MULTILINE)
    assert start is not None, "no '  test:' job key found in ci.yml; the slice boundary moved"
    end = re.search(r"^  tag-matches-version:$", workflow, re.MULTILINE)
    assert end is not None, "no '  tag-matches-version:' job key found in ci.yml"
    assert end.start() > start.start(), "ci.yml job order changed; the test-job slice is inverted"
    test_job = workflow[start.start() : end.start()]

    versions = set(_CI_PYTHON_VERSION_SCALAR.findall(test_job))
    for listed in _CI_PYTHON_VERSION_LIST.findall(test_job):
        versions.update(_CI_QUOTED_VERSION.findall(listed))

    assert versions, "no python-version values extracted from the test job; the regex went stale"
    assert len(versions) >= 3, (
        f"test matrix names too few interpreters to be the real one: {sorted(versions)}"
    )

    requires_python = _load_pyproject()["project"]["requires-python"]
    floor = re.fullmatch(r">=(\d+\.\d+)", requires_python)
    assert floor is not None, f"requires-python is not a bare '>=X.Y' floor: {requires_python!r}"
    assert floor.group(1) in versions, (
        f"declared floor {floor.group(1)} is not in the CI test matrix: {sorted(versions)}"
    )


def _extract_versions(text: str) -> set[str]:
    """Same extraction algorithm as ``test_ci_matrix_actually_exercises_the_declared_floor``,
    factored out so the regex trio can be exercised directly against synthetic strings.
    """
    versions = set(_CI_PYTHON_VERSION_SCALAR.findall(text))
    for listed in _CI_PYTHON_VERSION_LIST.findall(text):
        versions.update(_CI_QUOTED_VERSION.findall(listed))
    return versions


def test_ci_version_list_regex_extracts_all_quoted_entries_from_a_flow_list() -> None:
    text = '        python-version: ["3.10", "3.14"]\n'
    lists = _CI_PYTHON_VERSION_LIST.findall(text)
    assert lists == ['"3.10", "3.14"']
    assert set(_CI_QUOTED_VERSION.findall(lists[0])) == {"3.10", "3.14"}


def test_ci_version_list_regex_does_not_cross_a_closing_bracket() -> None:
    """``[^\\]]*`` must stop at the first ``]`` so a second bracketed matrix key on the same
    line (e.g. ``extras: [bare, rich]``) never bleeds into the captured version list.
    """
    text = 'python-version: ["3.10"]\nextras: [bare, rich]\n'
    assert _CI_PYTHON_VERSION_LIST.findall(text) == ['"3.10"']


def test_ci_version_scalar_regex_extracts_include_leg_pins() -> None:
    text = '          - os: windows-latest\n            python-version: "3.10"\n'
    assert _CI_PYTHON_VERSION_SCALAR.findall(text) == ["3.10"]


def test_ci_version_regexes_ignore_matrix_interpolation_syntax() -> None:
    """``python-version: ${{ matrix.python-version }}`` (the job-name and setup-uv usage in the
    real workflow) names the matrix key — it must not be mistaken for a literal version pin, or
    every job using the standard ``setup-uv`` step would falsely satisfy the assertion regardless
    of what the matrix actually declares.
    """
    text = "name: py${{ matrix.python-version }}\npython-version: ${{ matrix.python-version }}\n"
    assert _CI_PYTHON_VERSION_SCALAR.findall(text) == []
    assert _CI_PYTHON_VERSION_LIST.findall(text) == []


def test_ci_version_regexes_do_not_extract_an_unquoted_flow_list() -> None:
    """An unquoted flow-style list (``[3.10, 3.14]``) is valid YAML and a plausible future
    reformat (flagged as a risk in the implementation handoff). The current regexes are
    quoted-only and do NOT extract it — pin that gap explicitly here. This is not silently unsafe:
    ``test_ci_matrix_actually_exercises_the_declared_floor`` asserts ``versions`` is non-empty and
    has >=3 entries before checking membership, so this shape fails loudly rather than passing
    vacuously.
    """
    text = "python-version: [3.10, 3.14]\n"
    lists = _CI_PYTHON_VERSION_LIST.findall(text)
    assert lists == ["3.10, 3.14"]
    assert _CI_QUOTED_VERSION.findall(lists[0]) == []
    assert _extract_versions(text) == set()


def test_ci_matrix_slice_excludes_unrelated_jobs_pins() -> None:
    """Regression guard for the reason the real test slices the workflow to the ``test:`` job
    before searching: the ``lint`` and ``tag-matches-version`` jobs carry their own unrelated
    hardcoded ``python-version: "3.12"`` pins. Without the slice, those pins could pad the
    extracted version set and mask a test-job matrix that had genuinely dropped a version —
    a false pass. This synthetic workflow drops "3.12" from the test job's own matrix so the
    slice's effect is provable independent of the real ci.yml's current leg shape.
    """
    synthetic = (
        "  lint:\n"
        '    python-version: "3.12"\n'
        "  test:\n"
        "    strategy:\n"
        "      matrix:\n"
        '        python-version: ["3.11", "3.13"]\n'
        "  tag-matches-version:\n"
        '    python-version: "3.12"\n'
    )
    start = re.search(r"^  test:$", synthetic, re.MULTILINE)
    end = re.search(r"^  tag-matches-version:$", synthetic, re.MULTILINE)
    assert start is not None
    assert end is not None
    sliced = synthetic[start.start() : end.start()]

    assert _extract_versions(sliced) == {"3.11", "3.13"}
    assert _extract_versions(synthetic) == {"3.11", "3.12", "3.13"}
    # The unsliced extraction "finds" 3.12 only via the unrelated lint/tag-matches-version pins —
    # proof that skipping the slice would let those jobs mask a test matrix that dropped it.
    assert "3.12" not in _extract_versions(sliced)


@pytest.mark.parametrize(
    ("marker_suffix", "expected_match"),
    [
        (" python_version < '3.11'", True),
        (' python_version < "3.11"', True),
        (" python_version<'3.11'", False),
        (" python_version  <  '3.11'", False),
    ],
)
def test_tomli_marker_match_is_exact_whitespace_and_quote_sensitive(
    marker_suffix: str, expected_match: bool
) -> None:
    """Pins the actual behavior of the marker-matching logic in
    ``test_dev_group_carries_a_tomli_fallback_below_the_tomllib_floor``: it does a literal
    substring check on ``"python_version < '3.11'"`` after quote normalization, not a semantic
    marker-expression parse. A functionally equivalent marker written without the spaces around
    ``<`` (``python_version<'3.11'``) would NOT satisfy that test even though pip/uv would
    evaluate it identically. Low risk in practice — this repo's own pyproject.toml always writes
    the spaced form — but worth pinning so a future reformat of the marker doesn't produce a
    confusing failure in an unrelated-looking test.
    """
    entry = f"tomli>=2;{marker_suffix}"
    marker = entry.partition(";")[2].replace('"', "'")
    assert ("python_version < '3.11'" in marker) == expected_match
