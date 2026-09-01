"""Guards on the repo's public-facing documents: link correctness and cross-document coherence.

Separate from ``test_packaging_metadata.py``, which is scoped to license wiring and attribution.
These files are what a stranger reads first, and a wrong branch in an absolute GitHub URL fails
silently at author time and 404s only when someone clicks it.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = Path(__file__).resolve().parents[1]

# Every tracked file that may carry an absolute GitHub URL or a cross-document reference.
_PUBLIC_DOCS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "CHARTER.md",
    REPO_ROOT / "CONTRIBUTING.md",
    REPO_ROOT / "SECURITY.md",
    REPO_ROOT / "ledger" / "CANDIDATES.md",
    PYTHON_ROOT / "README.md",
    PYTHON_ROOT / "CHANGELOG.md",
    PYTHON_ROOT / "pyproject.toml",
)

_WRONG_BRANCH_URL = re.compile(
    r"github\.com/TheGeneCode/genekit/(?:blob|tree|raw)/master(?![\w-])",
    re.IGNORECASE,
)


@pytest.mark.parametrize("doc", _PUBLIC_DOCS, ids=lambda p: p.name)
def test_no_absolute_url_points_at_the_nonexistent_master_branch(doc: Path) -> None:
    """The repo's default branch is ``main``; there is no ``master``.

    Absolute ``/blob/master/`` URLs render as perfectly ordinary links and fail only when a reader
    clicks one. Two such URLs were also baked into wheel METADATA via ``[project.urls]``.
    """
    text = doc.read_text(encoding="utf-8")
    match = _WRONG_BRANCH_URL.search(text)
    assert match is None, f"{doc.name} links to the nonexistent 'master' branch: {match.group(0)!r}"


def test_contributing_exists_and_is_reachable_from_the_root_readme() -> None:
    """The root README's framing note is the only path a stranger has to CONTRIBUTING.md, and
    GitHub's PR-compose sidebar only surfaces the file if it is at the repo root under that exact
    name.
    """
    contributing = REPO_ROOT / "CONTRIBUTING.md"
    assert contributing.is_file(), "CONTRIBUTING.md is missing from the repo root"
    assert contributing.read_text(encoding="utf-8").strip(), "CONTRIBUTING.md is empty"
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "CONTRIBUTING.md" in readme, "root README.md does not reference CONTRIBUTING.md"


def test_consumers_registry_still_names_every_consumer() -> None:
    """CHARTER.md requires migration notes to name every consumer in the registry. A future
    redaction pass that empties the name column would silently break that clause, so pin the
    decision made in this plan: the five names stay.
    """
    readme = (PYTHON_ROOT / "README.md").read_text(encoding="utf-8")
    registry = readme.split("## Consumers registry", 1)
    assert len(registry) == 2, "no '## Consumers registry' section in python/README.md"
    body = registry[1]
    for consumer in ("remove-the-bloat", "Plex", "TTS", "MeadowLark", "personal-agents"):
        assert consumer in body, f"consumers registry no longer names {consumer!r}"


class TestWrongBranchUrlRegex:
    """Boundary coverage for the ``_WRONG_BRANCH_URL`` regression regex itself.

    The regex is the only thing standing between a future edit and a silently-broken absolute
    URL, so it needs to survive the shapes a real typo or copy-paste could actually produce, not
    just the exact strings this plan happened to fix.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/TheGeneCode/genekit/blob/master/CHARTER.md",
            "http://github.com/TheGeneCode/genekit/blob/master/CHARTER.md",
            "https://www.github.com/TheGeneCode/genekit/tree/master/python",
            "See https://github.com/TheGeneCode/genekit/raw/master/LICENSE for details.",
            "https://GITHUB.COM/TheGeneCode/genekit/blob/master/CHARTER.md",
            "https://github.com/TheGeneCode/genekit/blob/Master/CHARTER.md",
            "https://github.com/TheGeneCode/genekit/tree/master",
            "[repo](https://github.com/TheGeneCode/genekit/tree/master)",
            "https://github.com/TheGeneCode/genekit/blob/master?plain=1",
            "https://github.com/TheGeneCode/genekit/blob/master#readme",
        ],
        ids=[
            "https-blob",
            "http-blob",
            "www-prefix",
            "raw-in-prose",
            "uppercase-host",
            "capitalized-branch",
            "bare-branch-root-no-trailing-slash",
            "bare-branch-root-in-markdown-link",
            "query-string-suffix",
            "fragment-suffix",
        ],
    )
    def test_catches_known_bad_url_shapes(self, url: str) -> None:
        assert _WRONG_BRANCH_URL.search(url) is not None, f"expected a match in {url!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "https://github.com/TheGeneCode/genekit/blob/main/CHARTER.md",
            "https://github.com/TheGeneCode/genekit/blob/master-plan/CHARTER.md",
            "https://github.com/OtherOrg/genekit/blob/master/CHARTER.md",
            "https://github.com/TheGeneCode/other-repo/blob/master/CHARTER.md",
            "Switch to the master branch before running this script.",
            # The historical-defect prose in python/CHANGELOG.md: bare `blob/master/`
            # with no `github.com/TheGeneCode/genekit/` prefix is an intentional exception.
            "the `[project.urls]` Changelog link pointed at `blob/master/python/CHANGELOG.md`",
        ],
        ids=[
            "main-branch",
            "master-prefixed-branch-name",
            "different-org",
            "different-repo",
            "unrelated-prose-mention",
            "changelog-bare-string-exception",
        ],
    )
    def test_does_not_flag_unrelated_text(self, text: str) -> None:
        assert _WRONG_BRANCH_URL.search(text) is None, f"unexpected match in {text!r}"


def test_split_on_heading_only_ever_returns_two_parts_even_when_duplicated() -> None:
    """The registry test's ``split(heading, 1)`` has ``maxsplit=1``, so it can never produce a
    length-3 result no matter how many times the heading recurs in the document — the
    ``len(registry) == 2`` assertion guards the heading's *presence*, not its uniqueness. Pin that
    semantics so a future refactor to a maxsplit-less ``split(heading)`` doesn't silently change
    what ``len == 2`` means, and so a second, later ``## Consumers registry`` heading elsewhere in
    the file (e.g. in a changelog entry describing this very test) can't cause a false failure.
    """
    heading = "## Consumers registry"
    text = f"# doc\n\n{heading}\n\nfirst body\n\n{heading}\n\nsecond body naming MeadowLark"
    parts = text.split(heading, 1)
    assert len(parts) == 2
    assert "second body naming MeadowLark" in parts[1]


def test_split_on_heading_returns_one_part_when_heading_absent() -> None:
    """The other half of the boundary: no heading at all collapses to a single-element list, which
    is what makes ``len(registry) == 2`` a meaningful presence check rather than a tautology.
    """
    text = "# doc\n\nno registry section here"
    parts = text.split("## Consumers registry", 1)
    assert len(parts) == 1


def test_contributing_relative_links_are_not_subject_to_the_absolute_link_rule() -> None:
    """``test_packaged_readme_has_no_relative_parent_links`` (test_packaging_metadata.py) enforces
    absolute links only on ``python/README.md``, because that file is embedded verbatim as wheel
    METADATA. CONTRIBUTING.md is read on GitHub directly and deliberately uses same-directory
    relative links (``CHARTER.md``, ``ledger/CANDIDATES.md``) instead. Pin both facts: the links
    are relative (not accidentally rewritten to absolute GitHub URLs), and CONTRIBUTING.md is not
    among the paths the packaged-README test reads, so the two rules can never collide.
    """
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "(CHARTER.md)" in contributing
    assert "(ledger/CANDIDATES.md)" in contributing
    assert "github.com" not in contributing.lower()

    packaging_metadata_test = (
        PYTHON_ROOT / "tests" / "test_packaging_metadata.py"
    ).read_text(encoding="utf-8")
    assert "CONTRIBUTING" not in packaging_metadata_test
