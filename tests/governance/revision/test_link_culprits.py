"""Tests for acquired-link culprit search.

``find_link_culprits`` drops one acquired link at a time and asks
whether the theory turns SAT -- the link-level twin of the rule-culprit search.
Without it, every contradiction a mistaken acquired link creates is resolved by
retracting a *belief*, transcribing that mistake into the belief set.
These tests drive the real solver.
"""

from typing import Any

from endoxa.governance.revision import (
    PredicateConstraints,
    PredicateLink,
    find_link_culprits,
)
from endoxa.solver import Expr, parse_fof


def _rule(tptp: str) -> Expr:
    _name, _role, expr = parse_fof(tptp)
    return expr


def _wrong_implication() -> PredicateConstraints:
    """Build the constraints for a step that coined "every cat is a fish"."""
    return PredicateConstraints(implication_targets={"cat": {"fish"}})


def _cat_but_not_fish() -> dict[str, dict[str, Any]]:
    return {
        "cat(mike)": {"atom": "cat(mike)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
        "fish(mike)": {"atom": "fish(mike)", "stance": "asserted", "confidence": 1.0, "truth_value": False},
    }


class TestLinkIsTheCulprit:
    def test_wrong_implication_is_found(self) -> None:
        culprits = find_link_culprits(_cat_but_not_fish(), [], _wrong_implication())
        assert culprits == [PredicateLink(kind="implication", predicate="cat", target="fish")]

    def test_wrong_exclusion_is_found(self) -> None:
        beliefs = {
            "cat(mike)": {"atom": "cat(mike)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
            "pet(mike)": {"atom": "pet(mike)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
        }
        links = PredicateConstraints(exclusion_targets={"cat": {"pet"}})
        assert find_link_culprits(beliefs, [], links) == [
            PredicateLink(kind="exclusion", predicate="cat", target="pet"),
        ]

    def test_only_the_guilty_link_is_reported(self) -> None:
        # An innocent second link on the same beliefs must not be blamed.
        links = PredicateConstraints(implication_targets={"cat": {"fish"}, "sparrow": {"bird"}})
        assert find_link_culprits(_cat_but_not_fish(), [], links) == [
            PredicateLink(kind="implication", predicate="cat", target="fish"),
        ]


class TestLinkIsInnocent:
    def test_rule_driven_contradiction_blames_no_link(self) -> None:
        beliefs = {
            "bird(tweety)": {"atom": "bird(tweety)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
            "flies(tweety)": {"atom": "flies(tweety)", "stance": "asserted", "confidence": 0.9, "truth_value": False},
        }
        guilty_rule = _rule("fof(r, axiom, ![X] : (bird(X) => flies(X))).")
        links = PredicateConstraints(implication_targets={"cat": {"animal"}})
        assert find_link_culprits(beliefs, [guilty_rule], links) == []

    def test_functional_exclusion_is_not_a_candidate(self) -> None:
        # The config bootstrap stands in for a link nothing has produced yet
        # and its clashes are superseded by recency upstream, so it is
        # never offered up for retraction.
        beliefs = {
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
        links = PredicateConstraints(functional_predicates=("lives_in",))
        assert find_link_culprits(beliefs, [], links) == []

    def test_no_constraints_yields_no_candidates(self) -> None:
        assert find_link_culprits(_cat_but_not_fish(), [], None) == []
        assert find_link_culprits(_cat_but_not_fish(), [], PredicateConstraints()) == []


class TestConstraintReduction:
    def test_without_drops_only_the_named_edge(self) -> None:
        links = PredicateConstraints(
            exclusion_targets={"cat": {"dog", "fish"}},
            implication_targets={"cat": {"animal"}},
        )
        reduced = links.without(PredicateLink(kind="exclusion", predicate="cat", target="dog"))
        assert set(reduced.exclusion_targets["cat"]) == {"fish"}
        assert set(reduced.implication_targets["cat"]) == {"animal"}

    def test_acquired_links_exclude_functional_predicates(self) -> None:
        links = PredicateConstraints(
            functional_predicates=("lives_in",),
            exclusion_targets={"alive": {"dead"}},
            implication_targets={"cat": {"animal"}},
        )
        assert links.revision_candidates() == [
            PredicateLink(kind="exclusion", predicate="alive", target="dead"),
            PredicateLink(kind="implication", predicate="cat", target="animal"),
        ]
