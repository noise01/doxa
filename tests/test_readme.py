"""The example in the README runs, and does what the README says it does.

The README is the project page on the index as well as the front of the
repository, so a snippet that no longer matches the API is the first thing a new
reader meets. Nothing was checking it, and it had drifted twice over: the rule
took a confidence the example never passed, and the formula was missing the stop
that ends a TPTP sentence. Both would have gone out with the first release.
"""

import re
from pathlib import Path

import pytest

from endoxa.errors import RuleSyntaxError

README = Path(__file__).resolve().parents[1] / "README.md"
DOCUMENTS = (README, *sorted((README.parent / "docs").glob("*.md")))

BLOCK = re.compile(r"^```python\n(.*?)^```", re.DOTALL | re.MULTILINE)


def _blocks(markdown: str) -> list[str]:
    return BLOCK.findall(markdown)


def _run(source: str) -> dict[str, object]:
    namespace: dict[str, object] = {}
    exec(source, namespace)  # noqa: S102 -- running the documentation is the point of the check
    return namespace


class TestTheExampleRuns:
    @pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
    def test_every_python_block_executes(self, path: Path):
        blocks = _blocks(path.read_text(encoding="utf-8"))
        if path == README:
            assert blocks, "no python block in the README: the check would pass by finding nothing"
        for source in blocks:
            _run(source)

    def test_the_outcome_is_the_one_the_readme_claims(self):
        """The comments assert values, and a comment is not checked by executing it."""
        namespace = _run(_blocks(README.read_text(encoding="utf-8"))[0])
        outcome = namespace["outcome"]
        assert outcome.decision == "proposed"
        assert outcome.final.status == "SAT"
        assert outcome.changes[0].target.id == "observation-2"

    def test_a_broken_block_is_caught(self):
        """Both ways the real example was broken, so the detector is known to fire."""
        with pytest.raises(TypeError):
            _run("from endoxa.governance import Rule\nRule(id='r', formula='fof(a, axiom, p(x)).')")
        # Named rather than matched on the wording: a parse failure is this
        # package's own error now, so the control can say which one instead of
        # grepping a dependency's message for "unexpected".
        with pytest.raises(RuleSyntaxError):
            _run("from endoxa.solver.parsers.tptp import parse_fof\nparse_fof('fof(a, axiom, p(x))')")
