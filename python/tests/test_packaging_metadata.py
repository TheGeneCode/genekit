"""Guards on the published package metadata: license wiring, attribution, and README portability.

These assertions read the *installed* dist-info, so they only reflect ``pyproject.toml`` after a
``uv sync``. See the plan's Step 4.
"""

import re
import subprocess
import tomllib
import zipfile
from datetime import datetime
from importlib.metadata import distribution, metadata
from pathlib import Path
from urllib.parse import urlparse

import pytest

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
