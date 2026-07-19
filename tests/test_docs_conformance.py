"""The docs must not claim things the code doesn't do.

The nightly dogfood routine clean-room installs the published package and **follows the docs
verbatim**, so it is a doc-conformance tester by construction: every divergence between what the
docs promise and what the code does is a guaranteed find, and each one costs a full
fix -> PR -> release cycle for something an assertion catches in milliseconds. Historically that
class is #1 (text `--layout` dropped `unsupported`), #2 (stale CHANGELOG header), #4 (`--help`
claimed "require this bearer token" while it was a no-op) and #64 (docs promised the exception on
"every read surface"; bare `inspect --json` dropped it).

The specific trap these tests close: the supported-widget list is restated as prose in **two**
places on top of the code constant, so promoting a widget means editing three sources by hand.
0.7.0 promoted three widgets at once. Miss one edit and the docs claim a widget is undrivable
while the tool drives it — precisely the inconsistency the routine reports the next morning.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from streamlit_mcp.elements import UNSUPPORTED_ELEMENTS
from streamlit_mcp.runtime import SUPPORTED_KINDS

ROOT = Path(__file__).parent.parent
README = ROOT / "README.md"
USAGE = ROOT / "docs" / "usage.md"


def _listed_after(path: Path, marker: str, stop: str = "—.") -> set[str]:
    """The widget names a doc lists right after ``marker``, up to the first terminator.

    Deliberately dumb: it reads the prose a human reads, rather than anything generated, so the
    test fails when the human-facing sentence drifts from the code — which is the whole point.
    """
    text = path.read_text(encoding="utf-8")
    assert marker in text, f"{path.name} no longer contains {marker!r} — update this test"
    rest = text.split(marker, 1)[1]
    ends = [i for i in (rest.find(c) for c in stop) if i != -1]
    span = rest[: min(ends)] if ends else rest
    return set(re.findall(r"[a-z_]{4,}", span))


@pytest.mark.parametrize("path", [README, USAGE], ids=["README", "docs/usage.md"])
def test_docs_list_exactly_the_supported_widget_kinds(path):
    """Promote or drop a widget and this fails until the prose is updated to match."""
    assert _listed_after(path, "Supported widgets:") == set(SUPPORTED_KINDS)


def test_docs_never_call_a_supported_widget_undrivable():
    """The drift direction that actually misleads: a widget we drive still listed as one we can't.
    `pills` sat in this sentence while being drivable until 0.7.0."""
    named = _listed_after(USAGE, "can't drive", stop=")")
    assert named, "the 'can't drive' example list vanished — update this test"
    assert not (named & set(SUPPORTED_KINDS)), (
        f"docs/usage.md calls {sorted(named & set(SUPPORTED_KINDS))} undrivable, but they are in "
        f"SUPPORTED_KINDS"
    )
    assert named <= set(UNSUPPORTED_ELEMENTS), (
        f"docs/usage.md names {sorted(named - set(UNSUPPORTED_ELEMENTS))} as undrivable, but they "
        f"are not in UNSUPPORTED_ELEMENTS either — the list is stale"
    )


def test_changelog_documents_the_current_version():
    """#2 was a stale CHANGELOG header. The released version must have an entry, so a version bump
    can't ship without one."""
    from streamlit_mcp import __version__
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {__version__}" in changelog, (
        f"CHANGELOG.md has no '## {__version__}' section for the current version"
    )
