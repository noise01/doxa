"""Tests for defeasible-rule culprit search.

``find_rule_culprits`` drops one defeasible rule at a time and asks whether the
theory turns SAT. Before the link-derived ground clauses were part of that
theory, a contradiction raised purely by the links looked
resolvable by dropping *any* rule -- every defeasible rule was reported as a
culprit and ``choose_revision_candidate`` could retract an innocent one. These
tests drive the real solver.
"""

from typing import Any

from endoxa.governance.revision import (
    PredicateConstraints,
    find_rule_culprits,
)
from endoxa.solver import Expr, parse_fof

_FUNCTIONAL = PredicateConstraints(functional_predicates=("lives_in",))


def _rule(tptp: str) -> Expr:
    _name, _role, expr = parse_fof(tptp)
    return expr


def _clashing_residences() -> dict[str, dict[str, Any]]:
    """Build a contradiction no rule participates in: two residences for one person."""
    return {
        "lives_in(alice, tokyo)": {
            "atom": "lives_in(alice, tokyo)",
            "stance": "asserted",
            "confidence": 1.0,
            "truth_value": True,
        },
        "lives_in(alice, osaka)": {
            "atom": "lives_in(alice, osaka)",
            "stance": "asserted",
            "confidence": 0.9,
            "truth_value": True,
        },
    }


class TestLinkOnlyContradiction:
    """A clash the rules have nothing to do with must not blame a rule."""

    def test_innocent_rule_is_not_a_culprit(self) -> None:
        beliefs = _clashing_residences()
        unrelated = _rule("fof(r, axiom, ![X] : (bird(X) => flies(X))).")
        assert find_rule_culprits(beliefs, [unrelated], [unrelated], _FUNCTIONAL) == []

    def test_without_constraints_the_innocent_rule_looks_guilty(self) -> None:
        # The behaviour without them, kept as the regression's other half: with the
        # clause absent the theory is SAT to begin with, so dropping any rule
        # "restores" consistency.
        beliefs = _clashing_residences()
        unrelated = _rule("fof(r, axiom, ![X] : (bird(X) => flies(X))).")
        assert find_rule_culprits(beliefs, [unrelated], [unrelated]) == [unrelated]


class TestGenuineRuleCulprit:
    """A rule that really forces the contradiction is still found."""

    def test_rule_forcing_a_denied_consequent_is_a_culprit(self) -> None:
        beliefs = {
            "bird(tweety)": {"atom": "bird(tweety)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
            "flies(tweety)": {"atom": "flies(tweety)", "stance": "asserted", "confidence": 0.9, "truth_value": False},
        }
        guilty = _rule("fof(r, axiom, ![X] : (bird(X) => flies(X))).")
        assert find_rule_culprits(beliefs, [guilty], [guilty], _FUNCTIONAL) == [guilty]

    def test_rule_culprit_alongside_an_unrelated_link_clash(self) -> None:
        # Both a rule-forced contradiction (tweety) and a link clash (alice)
        # are on the beliefs. Dropping the rule leaves alice's clash, so no rule is a
        # culprit -- alice's contradiction is resolved on its own beat by the fact
        # path, and the rule stays until its own conflict is the one
        # being examined.
        beliefs = {
            **_clashing_residences(),
            "bird(tweety)": {"atom": "bird(tweety)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
            "flies(tweety)": {"atom": "flies(tweety)", "stance": "asserted", "confidence": 0.9, "truth_value": False},
        }
        guilty = _rule("fof(r, axiom, ![X] : (bird(X) => flies(X))).")
        assert find_rule_culprits(beliefs, [guilty], [guilty], _FUNCTIONAL) == []
