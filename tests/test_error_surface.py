"""Everything this package raises on its own behalf is an ``EndoxaError``.

Stated as a rule in ``endoxa/errors.py``, and a rule nothing checks holds until
the next person who has not read it. This reads every ``raise`` in the source and
every escape route out of the package, rather than trusting the convention.

The rule earns its keep at one place in particular. A grammar library sits under
the TPTP front end, and before this its exceptions came out of ``govern`` --
so handling a typo in a rule meant importing ``lark`` to name the type, and
pinning a dependency this package documents as an internal detail.
"""

import ast
import inspect
from pathlib import Path

import pytest

import endoxa.errors
from endoxa.errors import EndoxaError, RuleSyntaxError
from endoxa.governance import Belief, Constraints, Rule, govern
from endoxa.solver import parse_fof

ROOT = Path(__file__).resolve().parents[1]

#: Raised by the interpreter rather than by this package, so they are not the
#: package's to classify. ``NotImplementedError`` on an abstract method is the
#: language's own way of saying "subclass responsibility".
NOT_OURS = frozenset({"NotImplementedError", "StopIteration", "StopAsyncIteration"})


def _raised_names() -> list[tuple[str, int, str]]:
    """Every ``raise SomeError(...)`` in the shipped source, as ``(file, line, name)``."""
    found = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            call = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = call.id if isinstance(call, ast.Name) else ast.unparse(call)
            found.append((path.relative_to(ROOT).as_posix(), node.lineno, name))
    return found


def _endoxa_error_names() -> set[str]:
    return {name for name, obj in vars(endoxa.errors).items() if inspect.isclass(obj) and issubclass(obj, EndoxaError)}


class TestEveryRaiseIsOurs:
    def test_no_raise_escapes_the_hierarchy(self):
        ours = _endoxa_error_names()
        offences = [
            f"{file}:{line}: raises {name}, which is not an EndoxaError"
            for file, line, name in _raised_names()
            if name not in ours and name not in NOT_OURS
        ]
        assert not offences, "\n".join(offences)

    def test_the_walk_found_the_raises(self):
        """The control: an empty walk passes the test above for free."""
        raised = _raised_names()
        assert len(raised) >= 8, raised

    def test_a_planted_bare_raise_is_caught(self):
        ours = _endoxa_error_names()
        assert "ValueError" not in ours
        assert "EndoxaError" in ours


class TestTheParserDoesNotReachThrough:
    """A bad rule is this package's error to report, not its dependency's."""

    def test_a_malformed_axiom_raises_ours(self):
        with pytest.raises(RuleSyntaxError) as caught:
            parse_fof("fof(r, axiom, ![X] : human(X)")  # no terminating period
        assert "fof" in str(caught.value)

    def test_it_arrives_through_the_governance_entry_point_too(self):
        """``govern`` parses the rules it is handed, so the boundary has to hold there."""
        with pytest.raises(EndoxaError):
            govern(
                beliefs=[
                    Belief(
                        truth_value=True,
                        confidence=1.0,
                        id="human(socrates)",
                        atom="human(socrates)",
                        stance="asserted",
                    )
                ],
                constraints=Constraints(rules=(Rule(name="r", axiom="not a formula", confidence=0.9),)),
            )

    def test_the_parser_diagnosis_is_kept_as_the_cause(self):
        """Wrapped, not swallowed: the line and column are still reachable."""
        with pytest.raises(RuleSyntaxError) as caught:
            parse_fof("fof(r, axiom, ![X] : human(X)")
        assert caught.value.__cause__ is not None
        assert "lark" in type(caught.value.__cause__).__module__

    def test_it_is_still_catchable_as_a_builtin(self):
        """A caller who never reads ``endoxa.errors`` keeps working."""
        with pytest.raises(ValueError, match="TPTP"):
            parse_fof("fof(r, axiom, ![X] : human(X)")

    def test_nothing_outside_the_parser_imports_the_grammar_library(self):
        """One boundary to hold, so it is worth knowing there is only one.

        Read off the imports rather than the text: ``errors.py`` names ``lark`` in
        its docstring, saying what used to come out of here, and a substring
        search cannot tell that from a dependency.
        """
        importers = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                imported = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                if any(name.split(".")[0] == "lark" for name in imported):
                    importers.append(path.relative_to(ROOT).as_posix())
        assert sorted(set(importers)) == ["src/endoxa/solver/parsers/_grammar.py"], importers
