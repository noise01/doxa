"""Tests for verified revision-target selection.

``select_verified_revision_target`` differs from ``select_revision_target`` by
checking that the fact it picks actually restores consistency, instead of trusting
the lowest-confidence atom in the UNSAT core. These tests drive it through the real
solver: rules are parsed with ``parse_fof`` and the core is produced by
``check_consistency`` (not hand-built), so the whiff cases exercise genuine forward
chaining and exclusion propagation.
"""

from typing import Any

from endoxa.governance.revision import (
    PredicateConstraints,
    check_consistency,
    predicate_clauses,
    select_verified_revision_target,
)
from endoxa.solver import Expr, parse_fof


def _rule(tptp: str) -> Expr:
    _name, _role, expr = parse_fof(tptp)
    return expr


def _core_for(beliefs: dict[str, dict[str, Any]], rule_exprs: list[Expr]) -> tuple[list[Expr], dict[str, str]]:
    """Run the real consistency check and return (unsat_core, expr_to_node_id)."""
    result, unsat_core, expr_to_node_id = check_consistency(beliefs, rule_exprs)
    assert result == "UNSAT", "test setup must be contradictory"
    return unsat_core, expr_to_node_id


def _core_with_links(
    beliefs: dict[str, dict[str, Any]],
    constraints: PredicateConstraints,
) -> tuple[list[Expr], dict[str, str]]:
    """Core of a contradiction the links raise, as a host produces it."""
    return _core_for(beliefs, predicate_clauses(beliefs, constraints))


class TestWhiffAvoidance:
    """A consequent re-derived by an asserted antecedent must not be chosen."""

    def test_skips_re_derived_consequent_under_exclusion(self) -> None:
        # a(c) forces p(c); p(c) and q(c) are mutually exclusive. p(c) is the
        # lowest-confidence atom, but flipping it whiffs (a(c) re-derives it), so
        # the resolvable q(c) must be chosen instead.
        rules = [
            _rule("fof(r, axiom, ![X] : (a(X) => p(X)))."),
            _rule("fof(excl, axiom, ![X] : ~(p(X) & q(X)))."),
        ]
        beliefs = {
            "a(c)": {"atom": "a(c)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
            "p(c)": {"atom": "p(c)", "stance": "hypothesis", "confidence": 0.5, "truth_value": True},
            "q(c)": {"atom": "q(c)", "stance": "asserted", "confidence": 0.9, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        target = select_verified_revision_target(core, beliefs, mapping, rules)
        assert target is not None
        assert target[0] == "q(c)"

    def test_skips_re_derived_consequent_under_negation(self) -> None:
        # a(c) forces b(c); ~b(c) is asserted low-confidence. Flipping b(c) whiffs;
        # the asserted ~b(c) (as b(c) with truth_value False) is the real fix.
        rules = [_rule("fof(r, axiom, ![X] : (a(X) => b(X))).")]
        beliefs = {
            "a(c)": {"atom": "a(c)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
            "b(c)": {"atom": "b(c)", "stance": "asserted", "confidence": 0.9, "truth_value": False},
        }
        core, mapping = _core_for(beliefs, rules)
        target = select_verified_revision_target(core, beliefs, mapping, rules)
        assert target is not None
        # b(c)=False is the only revisable atom; flipping it to True agrees with the
        # rule's derivation, restoring SAT.
        assert target[0] == "b(c)"


class TestIndependentContradictions:
    """The theory decomposes per constant: resolve one conflict, leave the rest."""

    def test_resolves_the_conflicting_constant_not_a_bystander(self) -> None:
        # Two independent contradictions: c (p&q) and d (p&q). The core names one of
        # them; the returned target must belong to that conflict, and flipping it
        # need not restore *global* SAT (d's clash remains for a later beat).
        rules = [_rule("fof(excl, axiom, ![X] : ~(p(X) & q(X))).")]
        beliefs = {
            "p(c)": {"atom": "p(c)", "stance": "asserted", "confidence": 0.9, "truth_value": True},
            "q(c)": {"atom": "q(c)", "stance": "hypothesis", "confidence": 0.4, "truth_value": True},
            "p(d)": {"atom": "p(d)", "stance": "asserted", "confidence": 0.9, "truth_value": True},
            "q(d)": {"atom": "q(d)", "stance": "hypothesis", "confidence": 0.4, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        target = select_verified_revision_target(core, beliefs, mapping, rules)
        assert target is not None
        node_id, _data = target
        # The whole set stays UNSAT after any single flip, yet a per-constant fix
        # exists: it must be one of the atoms in the core's own conflict.
        core_ids = {mapping[str(e)] for e in core if str(e) in mapping}
        assert node_id in core_ids
        # It must be the flip that resolves that constant's clash (lower-confidence
        # hypothesis q over observation p).
        assert node_id.startswith("q(")


class TestBackwardCompatibility:
    """On a simple, directly-resolvable conflict the verified pick matches policy."""

    def test_lowest_confidence_fallible_wins_direct_clash(self) -> None:
        rules = [_rule("fof(excl, axiom, ![X] : ~(human(X) & robot(X))).")]
        beliefs = {
            "human(x)": {"atom": "human(x)", "stance": "asserted", "confidence": 0.95, "truth_value": True},
            "robot(x)": {"atom": "robot(x)", "stance": "asserted", "confidence": 0.9, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        target = select_verified_revision_target(core, beliefs, mapping, rules)
        assert target is not None
        assert target[0] == "robot(x)"

    def test_hypothesis_preferred_among_verified(self) -> None:
        # Both flips resolve the clash; the hypothesis is peeled first even though
        # its confidence is higher than the observation's.
        rules = [_rule("fof(excl, axiom, ![X] : ~(p(X) & q(X))).")]
        beliefs = {
            "p(x)": {"atom": "p(x)", "stance": "hypothesis", "confidence": 0.6, "truth_value": True},
            "q(x)": {"atom": "q(x)", "stance": "asserted", "confidence": 0.5, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        target = select_verified_revision_target(core, beliefs, mapping, rules)
        assert target is not None
        assert target[0] == "p(x)"


class TestEqualConfidenceTie:
    """When the preference ranks two settling candidates alike, nothing is picked.

    An earlier selector returned the first candidate whose flip restored
    consistency. Since ``sorted`` is stable, equal-confidence candidates kept the
    order the UNSAT core arrived in -- so which belief got retracted was decided by
    the solver. These tests fix the replacement rule: the band is judged as a whole.
    """

    def test_two_settling_candidates_at_the_same_confidence_yield_no_target(self) -> None:
        rules = [_rule("fof(excl, axiom, ![X] : ~(alive(X) & dead(X))).")]
        beliefs = {
            "alive(felix)": {"atom": "alive(felix)", "stance": "asserted", "confidence": 0.95, "truth_value": True},
            "dead(felix)": {"atom": "dead(felix)", "stance": "asserted", "confidence": 0.95, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        assert select_verified_revision_target(core, beliefs, mapping, rules) is None

    def test_single_settling_candidate_in_the_band_still_wins(self) -> None:
        """Equal standing is not enough -- the beliefs can separate what the preference cannot.

        ``q(c)`` is re-derived by the asserted ``a(c)``, so flipping it whiffs
         and only ``p(c)`` settles the clash. The rule is "two settling
        candidates", not "two candidates".
        """
        rules = [
            _rule("fof(excl, axiom, ![X] : ~(p(X) & q(X)))."),
            _rule("fof(derive, axiom, ![X] : (a(X) => q(X)))."),
        ]
        beliefs = {
            "a(c)": {"atom": "a(c)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
            "p(c)": {"atom": "p(c)", "stance": "asserted", "confidence": 0.5, "truth_value": True},
            "q(c)": {"atom": "q(c)", "stance": "asserted", "confidence": 0.5, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        target = select_verified_revision_target(core, beliefs, mapping, rules)
        assert target is not None
        assert target[0] == "p(c)"

    def test_next_band_is_reached_when_the_first_settles_nothing(self) -> None:
        """A whiffed low-confidence band yields to a higher-confidence fix, as before.

        Bands here are pure confidence (all three beliefs are assertions), so this
        pins the traversal itself rather than the hypothesis axis.
        """
        rules = [
            _rule("fof(d, axiom, ![X] : (a(X) => p(X)))."),
            _rule("fof(e, axiom, ![X] : ~(p(X) & q(X)))."),
        ]
        beliefs = {
            "a(c)": {"atom": "a(c)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
            "p(c)": {"atom": "p(c)", "stance": "asserted", "confidence": 0.4, "truth_value": True},
            "q(c)": {"atom": "q(c)", "stance": "asserted", "confidence": 0.9, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        target = select_verified_revision_target(core, beliefs, mapping, rules)
        assert target is not None
        assert target[0] == "q(c)"

    def test_hypothesis_and_assertion_at_equal_confidence_are_different_bands(self) -> None:
        """Equal confidence is not equal standing: being a guess is itself a reason to go first."""
        rules = [_rule("fof(excl, axiom, ![X] : ~(p(X) & q(X))).")]
        beliefs = {
            "p(x)": {"atom": "p(x)", "stance": "hypothesis", "confidence": 0.5, "truth_value": True},
            "q(x)": {"atom": "q(x)", "stance": "asserted", "confidence": 0.5, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        target = select_verified_revision_target(core, beliefs, mapping, rules)
        assert target is not None
        assert target[0] == "p(x)"

    def test_core_order_does_not_change_the_verdict(self) -> None:
        """The whole point: the solver's core order must not decide anything."""
        rules = [_rule("fof(excl, axiom, ![X] : ~(p(X) & q(X))).")]
        beliefs = {
            "p(x)": {"atom": "p(x)", "stance": "asserted", "confidence": 0.5, "truth_value": True},
            "q(x)": {"atom": "q(x)", "stance": "asserted", "confidence": 0.9, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        forward = select_verified_revision_target(core, beliefs, mapping, rules)
        reverse = select_verified_revision_target(list(reversed(core)), beliefs, mapping, rules)
        assert forward is not None
        assert reverse is not None
        assert forward[0] == reverse[0] == "p(x)"


class TestHypothesisIsReadFromBeliefContext:
    """The hypothesis preference reads the key the host's belief store actually writes.

    ``add_atom`` takes a ``role`` argument and stores it under ``belief_context``;
    ``BeliefNode`` has no ``role`` field. Reading ``role`` therefore never matched
    a real belief, which left the policy of retracting a conjecture before an
    assertion inert.
    """

    def test_belief_context_hypothesis_outranks_a_lower_confidence_assertion(self) -> None:
        rules = [_rule("fof(excl, axiom, ![X] : ~(p(X) & q(X))).")]
        beliefs = {
            "p(x)": {"atom": "p(x)", "stance": "hypothesis", "confidence": 0.9, "truth_value": True},
            "q(x)": {"atom": "q(x)", "stance": "asserted", "confidence": 0.3, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        target = select_verified_revision_target(core, beliefs, mapping, rules)
        assert target is not None
        assert target[0] == "p(x)"

    def test_legacy_role_key_is_not_treated_as_a_hypothesis(self) -> None:
        """A belief dict still keyed on ``role`` gets no preference -- the follow-through gate.

        This is the detector for a missed rename: anything that hand-builds belief
        dicts (a test, an eval host) has to use ``belief_context``, and if it does
        not, its "hypothesis" is simply an ordinary belief. Here that means the
        lower-confidence atom wins on confidence alone.
        """
        rules = [_rule("fof(excl, axiom, ![X] : ~(p(X) & q(X))).")]
        beliefs = {
            "p(x)": {
                "atom": "p(x)",
                "stance": "asserted",
                "role": "hypothesis",
                "confidence": 0.9,
                "truth_value": True,
            },
            "q(x)": {"atom": "q(x)", "stance": "asserted", "role": "user", "confidence": 0.3, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        target = select_verified_revision_target(core, beliefs, mapping, rules)
        assert target is not None
        assert target[0] == "q(x)"


class TestLinkDerivedClauses:
    """The re-check sees the link constraints too."""

    def test_rejects_a_flip_that_only_moves_the_clash(self) -> None:
        # cat -> animal (implication link) and animal excludes mineral. The beliefs
        # violates the implication: cat(x) is held, animal(x) is denied. Flipping
        # animal(x) to true satisfies the implication but makes it clash with the
        # pinned mineral(x) -- the beat would whiff. Only a re-check that re-
        # synthesizes the clauses from the *flipped* beliefs can see that.
        constraints = PredicateConstraints(
            exclusion_targets={"animal": {"mineral"}},
            implication_targets={"cat": {"animal"}},
        )
        beliefs = {
            "cat(x)": {"atom": "cat(x)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
            "animal(x)": {"atom": "animal(x)", "stance": "asserted", "confidence": 0.9, "truth_value": False},
            "mineral(x)": {"atom": "mineral(x)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
        }
        core, mapping = _core_with_links(beliefs, constraints)

        # Without the link clauses the flip looks like a fix.
        assert select_verified_revision_target(core, beliefs, mapping, [])[0] == "animal(x)"

        # With them, no fact flip resolves, so the fact path declines (the rule path
        # or a later beat handles it) instead of whiffing.
        assert select_verified_revision_target(core, beliefs, mapping, [], links=constraints) is None

    def test_pileup_falls_back_to_a_flip_that_makes_progress(self) -> None:
        # Three residences under a single-valued predicate: three pairwise clashes,
        # and no single flip reaches SAT. Requiring full satisfiability would abandon
        # the fact path; the progress criterion keeps one retraction per beat
        # and picks the lowest-confidence atom.
        constraints = PredicateConstraints(functional_predicates=("lives_in",))
        beliefs = {
            "lives_in(alice, tokyo)": {
                "atom": "lives_in(alice, tokyo)",
                "stance": "asserted",
                "confidence": 0.9,
                "truth_value": True,
            },
            "lives_in(alice, osaka)": {
                "atom": "lives_in(alice, osaka)",
                "stance": "asserted",
                "confidence": 0.5,
                "truth_value": True,
            },
            "lives_in(alice, kyoto)": {
                "atom": "lives_in(alice, kyoto)",
                "stance": "asserted",
                "confidence": 0.8,
                "truth_value": True,
            },
        }
        core, mapping = _core_with_links(beliefs, constraints)
        target = select_verified_revision_target(core, beliefs, mapping, [], links=constraints)
        assert target is not None
        assert target[0] == "lives_in(alice, osaka)"

        # The pile-up shrank (3 clashes -> 1), so the following beat resolves it.
        remaining = {**beliefs, target[0]: {**target[1], "truth_value": False}}
        assert len(predicate_clauses(remaining, constraints)) == 1

    def test_inviolable_link_clash_returns_none(self) -> None:
        # Two pinned user residences: the progress fallback does not make an
        # inviolable belief revisable, it only relaxes what counts as verified.
        constraints = PredicateConstraints(functional_predicates=("lives_in",))
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
                "confidence": 1.0,
                "truth_value": True,
            },
        }
        core, mapping = _core_with_links(beliefs, constraints)
        assert select_verified_revision_target(core, beliefs, mapping, [], links=constraints) is None

    def test_empty_constraints_match_the_previous_behavior(self) -> None:
        rules = [_rule("fof(excl, axiom, ![X] : ~(human(X) & robot(X))).")]
        beliefs = {
            "human(x)": {"atom": "human(x)", "stance": "asserted", "confidence": 0.95, "truth_value": True},
            "robot(x)": {"atom": "robot(x)", "stance": "asserted", "confidence": 0.9, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        without = select_verified_revision_target(core, beliefs, mapping, rules)
        with_empty = select_verified_revision_target(core, beliefs, mapping, rules, links=PredicateConstraints())
        assert without == with_empty
        assert with_empty is not None
        assert with_empty[0] == "robot(x)"


class TestNoResolvableFact:
    """When no single fact flip resolves the clash, return None (rule may still fix)."""

    def test_inviolable_clash_returns_none(self) -> None:
        # Two pinned user facts under an exclusion: neither is revisable.
        rules = [_rule("fof(excl, axiom, ![X] : ~(p(X) & q(X))).")]
        beliefs = {
            "p(c)": {"atom": "p(c)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
            "q(c)": {"atom": "q(c)", "stance": "asserted", "confidence": 1.0, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, rules)
        assert select_verified_revision_target(core, beliefs, mapping, rules) is None
