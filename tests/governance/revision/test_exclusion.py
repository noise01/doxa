"""Tests for predicate-link constraint synthesis.

``functional_exclusion_clauses`` turns a single-valued predicate holding two
different final-argument values into an SMT ground clause so the consistency
check goes UNSAT; ``inter_predicate_exclusion_clauses`` does the same for an
excluded predicate pair on one argument tuple; ``implication_clauses``
for an antecedent held true with its consequent held false.
``functional_exclusion_partner`` finds the older belief the recency-supersession
rule retracts. ``backward_implication_clauses`` (/) is the one
derivation-side synthesizer: it walks the implication links backwards from a
verification target so an acquired consequence is provable, not just detectable.
The clause tests drive the real solver (``check_consistency`` / ``check_atom_support``) so a
synthesized clause's UNSAT is genuine, not asserted.
"""

from typing import Any

from endoxa.governance.revision import (
    PredicateConstraints,
    backward_implication_clauses,
    check_atom_support,
    check_consistency,
    functional_exclusion_clauses,
    functional_exclusion_partner,
    implication_clauses,
    inter_predicate_exclusion_clauses,
    predicate_clauses,
)

_FUNCTIONAL = ("lives_in", "works_at")


def _true(node_id: str) -> tuple[str, dict[str, Any]]:
    return node_id, {"atom": node_id, "stance": "asserted", "confidence": 1.0, "truth_value": True}


def _false(node_id: str) -> tuple[str, dict[str, Any]]:
    return node_id, {"atom": node_id, "stance": "asserted", "confidence": 1.0, "truth_value": False}


class TestFunctionalExclusionClauses:
    """Clause synthesis over a belief snapshot."""

    def test_conflicting_pair_is_unsat(self) -> None:
        # Two residences for one person under a single-valued predicate: the
        # synthesized clause must make the belief set UNSAT even though both atoms
        # are inviolable user beliefs (no axiom network involved).
        beliefs = dict([_true("lives_in(alice, tokyo)"), _true("lives_in(alice, osaka)")])
        clauses = functional_exclusion_clauses(beliefs, _FUNCTIONAL)
        assert len(clauses) == 1
        result, _core, _map = check_consistency(beliefs, clauses)
        assert result == "UNSAT"

    def test_empty_config_yields_no_clauses(self) -> None:
        # The production default (no functional predicates) must leave the check
        # byte-for-byte unchanged: no clauses, so the same pair is SAT.
        beliefs = dict([_true("lives_in(alice, tokyo)"), _true("lives_in(alice, osaka)")])
        assert functional_exclusion_clauses(beliefs, ()) == []
        result, _core, _map = check_consistency(beliefs, [])
        assert result == "SAT"

    def test_same_value_is_not_a_conflict(self) -> None:
        beliefs = dict([_true("lives_in(alice, tokyo)"), _true("lives_in(bob, tokyo)")])
        assert functional_exclusion_clauses(beliefs, _FUNCTIONAL) == []

    def test_non_functional_predicate_ignored(self) -> None:
        # knows/2 is not declared single-valued: two values are fine.
        beliefs = dict([_true("knows(alice, tokyo)"), _true("knows(alice, osaka)")])
        assert functional_exclusion_clauses(beliefs, _FUNCTIONAL) == []

    def test_false_atoms_do_not_participate(self) -> None:
        # Exclusion is stated over the atom *holding*; a retracted value is inert.
        beliefs = dict([_true("lives_in(alice, tokyo)")])
        beliefs["lives_in(alice, osaka)"] = {
            "atom": "lives_in(alice, osaka)",
            "stance": "asserted",
            "confidence": 1.0,
            "truth_value": False,
        }
        assert functional_exclusion_clauses(beliefs, _FUNCTIONAL) == []

    def test_three_values_yield_pairwise_clauses(self) -> None:
        beliefs = dict(
            [
                _true("lives_in(alice, tokyo)"),
                _true("lives_in(alice, osaka)"),
                _true("lives_in(alice, kyoto)"),
            ],
        )
        # 3 distinct values -> C(3,2) = 3 pairwise exclusion clauses.
        assert len(functional_exclusion_clauses(beliefs, _FUNCTIONAL)) == 3

    def test_distinct_subjects_are_independent(self) -> None:
        # alice's clash is real; bob's single residence adds nothing.
        beliefs = dict(
            [
                _true("lives_in(alice, tokyo)"),
                _true("lives_in(alice, osaka)"),
                _true("lives_in(bob, kyoto)"),
            ],
        )
        assert len(functional_exclusion_clauses(beliefs, _FUNCTIONAL)) == 1


class TestInterPredicateExclusionClauses:
    """Inter-predicate (pairwise antonym / exclusion class) clause synthesis."""

    def test_conflicting_pair_is_unsat(self) -> None:
        # alive/dead on the same subject under a declared exclusion: the synthesized
        # clause must make the belief set UNSAT with no axiom network involved.
        beliefs = dict([_true("alive(socrates)"), _true("dead(socrates)")])
        clauses = inter_predicate_exclusion_clauses(beliefs, {"dead": {"alive"}})
        assert len(clauses) == 1
        result, _core, _map = check_consistency(beliefs, clauses)
        assert result == "UNSAT"

    def test_empty_relation_yields_no_clauses(self) -> None:
        # The production default (no populated inter-predicate links) must leave the
        # check byte-for-byte unchanged: no clauses, so the same pair is SAT.
        beliefs = dict([_true("alive(socrates)"), _true("dead(socrates)")])
        assert inter_predicate_exclusion_clauses(beliefs, {}) == []
        result, _core, _map = check_consistency(beliefs, [])
        assert result == "SAT"

    def test_relation_is_undirected(self) -> None:
        # Only ``dead -> alive`` is recorded (the acquired links the proposing symbol
        # only), yet a clash asserted in either order must be caught: the relation is
        # treated undirected so the assertion-order blind spot is closed.
        beliefs = dict([_true("alive(socrates)"), _true("dead(socrates)")])
        assert len(inter_predicate_exclusion_clauses(beliefs, {"dead": {"alive"}})) == 1
        assert len(inter_predicate_exclusion_clauses(beliefs, {"alive": {"dead"}})) == 1

    def test_different_argument_tuples_do_not_clash(self) -> None:
        # Exclusion is stated over the identical argument tuple: alive(socrates) and
        # dead(plato) are about different subjects and never conflict.
        beliefs = dict([_true("alive(socrates)"), _true("dead(plato)")])
        assert inter_predicate_exclusion_clauses(beliefs, {"dead": {"alive"}}) == []

    def test_unrelated_predicate_ignored(self) -> None:
        # mortal is not an exclusion target of alive: co-presence is fine.
        beliefs = dict([_true("alive(socrates)"), _true("mortal(socrates)")])
        assert inter_predicate_exclusion_clauses(beliefs, {"alive": {"dead"}}) == []

    def test_false_atoms_do_not_participate(self) -> None:
        # Exclusion is stated over the atom *holding*; a retracted value is inert.
        beliefs = dict([_true("alive(socrates)")])
        beliefs["dead(socrates)"] = {
            "atom": "dead(socrates)",
            "stance": "asserted",
            "confidence": 1.0,
            "truth_value": False,
        }
        assert inter_predicate_exclusion_clauses(beliefs, {"dead": {"alive"}}) == []

    def test_exclusion_class_yields_pairwise_clauses(self) -> None:
        # A 3-member mutually exclusive class on one subject -> C(3,2) = 3 clauses.
        beliefs = dict([_true("cat(x)"), _true("dog(x)"), _true("bird(x)")])
        relation = {"cat": {"dog", "bird"}, "dog": {"cat", "bird"}, "bird": {"cat", "dog"}}
        assert len(inter_predicate_exclusion_clauses(beliefs, relation)) == 3

    def test_distinct_subjects_are_independent(self) -> None:
        # socrates's clash is real; plato's single predicate adds nothing.
        beliefs = dict([_true("alive(socrates)"), _true("dead(socrates)"), _true("alive(plato)")])
        assert len(inter_predicate_exclusion_clauses(beliefs, {"dead": {"alive"}})) == 1


class TestLinkImplicationClauses:
    """Defeasible-implication clause synthesis."""

    def test_true_antecedent_with_false_consequent_is_unsat(self) -> None:
        # cat(x) asserted while animal(x) is held false: the synthesized implication
        # must make the belief set UNSAT with no axiom network involved.
        beliefs = dict([_true("cat(felix)"), _false("animal(felix)")])
        clauses = implication_clauses(beliefs, {"cat": {"animal"}})
        assert len(clauses) == 1
        result, _core, _map = check_consistency(beliefs, clauses)
        assert result == "UNSAT"

    def test_empty_relation_yields_no_clauses(self) -> None:
        # The production default (no populated implication links) must leave the
        # check byte-for-byte unchanged: no clauses, so the same pair is SAT.
        beliefs = dict([_true("cat(felix)"), _false("animal(felix)")])
        assert implication_clauses(beliefs, {}) == []
        result, _core, _map = check_consistency(beliefs, [])
        assert result == "SAT"

    def test_relation_is_directed(self) -> None:
        # ``cat -> animal`` fires; the converse must NOT be synthesized from it --
        # symmetrizing would inject "every animal is a cat".
        beliefs = dict([_true("cat(felix)"), _false("animal(felix)")])
        assert len(implication_clauses(beliefs, {"cat": {"animal"}})) == 1
        assert implication_clauses(beliefs, {"animal": {"cat"}}) == []

    def test_true_consequent_is_no_clash(self) -> None:
        # Co-present and both true: the role was exercised, nothing to resolve.
        beliefs = dict([_true("cat(felix)"), _true("animal(felix)")])
        assert implication_clauses(beliefs, {"cat": {"animal"}}) == []

    def test_absent_consequent_yields_no_clause(self) -> None:
        # No forward materialization: with animal(felix) off the beliefs the clause set
        # stays empty, matching unit propagation's escalation condition.
        beliefs = dict([_true("cat(felix)")])
        assert implication_clauses(beliefs, {"cat": {"animal"}}) == []

    def test_false_antecedent_yields_no_clause(self) -> None:
        # Implication is stated over the antecedent *holding*; a retracted one is inert.
        beliefs = dict([_false("cat(felix)"), _false("animal(felix)")])
        assert implication_clauses(beliefs, {"cat": {"animal"}}) == []

    def test_different_argument_tuples_do_not_clash(self) -> None:
        beliefs = dict([_true("cat(felix)"), _false("animal(rex)")])
        assert implication_clauses(beliefs, {"cat": {"animal"}}) == []

    def test_reverse_assertion_order_is_caught(self) -> None:
        # In-beat propagation reads only the newly asserted atom's links, so a
        # consequent asserted false *after* its antecedent is missed there. Scanning
        # beliefs pairs closes that blind spot at this deeper tier: the
        # clause set does not depend on which atom arrived last.
        beliefs = dict([_false("animal(felix)"), _true("cat(felix)")])
        assert len(implication_clauses(beliefs, {"cat": {"animal"}})) == 1

    def test_chain_yields_one_clause_per_broken_link(self) -> None:
        # cat -> mammal -> animal with both consequents held false: each broken link
        # is its own ground clause (resolved one per beat).
        beliefs = dict([_true("cat(felix)"), _false("mammal(felix)"), _false("animal(felix)")])
        relation = {"cat": {"mammal"}, "mammal": {"animal"}}
        # mammal(felix) is false, so it is not a true antecedent: only cat -> mammal fires.
        assert len(implication_clauses(beliefs, relation)) == 1

    def test_multiple_targets_each_yield_a_clause(self) -> None:
        beliefs = dict([_true("cat(felix)"), _false("animal(felix)"), _false("pet(felix)")])
        assert len(implication_clauses(beliefs, {"cat": {"animal", "pet"}})) == 2

    def test_distinct_subjects_are_independent(self) -> None:
        beliefs = dict([_true("cat(felix)"), _false("animal(felix)"), _true("cat(tom)")])
        assert len(implication_clauses(beliefs, {"cat": {"animal"}})) == 1


class TestLinkClauses:
    """The aggregate synthesizer the detection and revision paths share."""

    def test_aggregates_all_three_forms(self) -> None:
        beliefs = dict(
            [
                _true("lives_in(alice, tokyo)"),
                _true("lives_in(alice, osaka)"),
                _true("alive(felix)"),
                _true("dead(felix)"),
                _true("cat(tom)"),
                _false("animal(tom)"),
            ],
        )
        constraints = PredicateConstraints(
            functional_predicates=_FUNCTIONAL,
            exclusion_targets={"alive": {"dead"}},
            implication_targets={"cat": {"animal"}},
        )
        assert len(predicate_clauses(beliefs, constraints)) == 3
        result, _core, _map = check_consistency(beliefs, predicate_clauses(beliefs, constraints))
        assert result == "UNSAT"

    def test_clause_count_is_the_clash_count(self) -> None:
        # Every synthesized clause is one the belief set currently violates, which is
        # what lets the revision path use the count as a progress measure.
        # Three residences clash pairwise: three clauses.
        beliefs = dict(
            [
                _true("lives_in(alice, tokyo)"),
                _true("lives_in(alice, osaka)"),
                _true("lives_in(alice, kyoto)"),
            ],
        )
        constraints = PredicateConstraints(functional_predicates=_FUNCTIONAL)
        assert len(predicate_clauses(beliefs, constraints)) == 3

        # Retracting one leaves a single clash between the remaining two.
        beliefs["lives_in(alice, kyoto)"] = {
            "atom": "lives_in(alice, kyoto)",
            "stance": "asserted",
            "confidence": 1.0,
            "truth_value": False,
        }
        assert len(predicate_clauses(beliefs, constraints)) == 1

    def test_empty_constraints_are_a_no_op(self) -> None:
        beliefs = dict([_true("lives_in(alice, tokyo)"), _true("lives_in(alice, osaka)")])
        assert predicate_clauses(beliefs, PredicateConstraints()) == []
        assert predicate_clauses(beliefs, None) == []


class TestFunctionalExclusionPartner:
    """Finding the older belief a newer assertion supersedes."""

    def test_finds_true_conflicting_partner(self) -> None:
        beliefs = dict([_true("lives_in(alice, tokyo)"), _true("lives_in(alice, osaka)")])
        partner = functional_exclusion_partner("lives_in(alice, osaka)", beliefs, _FUNCTIONAL)
        assert partner is not None
        assert partner[0] == "lives_in(alice, tokyo)"

    def test_no_partner_when_predicate_not_functional(self) -> None:
        beliefs = dict([_true("knows(alice, tokyo)"), _true("knows(alice, osaka)")])
        assert functional_exclusion_partner("knows(alice, osaka)", beliefs, _FUNCTIONAL) is None

    def test_no_partner_when_value_matches(self) -> None:
        beliefs = dict([_true("lives_in(alice, tokyo)"), _true("lives_in(bob, tokyo)")])
        assert functional_exclusion_partner("lives_in(alice, tokyo)", beliefs, _FUNCTIONAL) is None

    def test_ignores_retracted_partner(self) -> None:
        beliefs = dict([_true("lives_in(alice, osaka)")])
        beliefs["lives_in(alice, tokyo)"] = {
            "atom": "lives_in(alice, tokyo)",
            "stance": "asserted",
            "confidence": 1.0,
            "truth_value": False,
        }
        assert functional_exclusion_partner("lives_in(alice, osaka)", beliefs, _FUNCTIONAL) is None

    def test_empty_config_yields_no_partner(self) -> None:
        beliefs = dict([_true("lives_in(alice, tokyo)"), _true("lives_in(alice, osaka)")])
        assert functional_exclusion_partner("lives_in(alice, osaka)", beliefs, ()) is None


class TestBackwardImplicationClauses:
    """Derivation-side synthesis for the belief-verification query.

    Every case runs the real ``check_atom_support`` so the verdict is the solver's, not the
    clause list's shape. The baseline each one contrasts against is the verdict
    without the clauses -- the state before this increment.
    """

    def test_link_makes_the_consequence_entailed(self) -> None:
        # The beliefs holds the antecedent; the acquired link q => p is what carries
        # the target. Without the clauses the query cannot see the link at all.
        beliefs = dict([_true("cat(felix)")])
        targets = {"cat": {"animal"}}
        assert check_atom_support(beliefs, [], "animal(felix)").verdict == "NOT_ENTAILED"

        clauses = backward_implication_clauses("animal(felix)", targets)
        assert check_atom_support(beliefs, clauses, "animal(felix)").verdict == "ENTAILED"

    def test_no_links_is_a_no_op(self) -> None:
        assert backward_implication_clauses("animal(felix)", {}) == []

    def test_unrelated_links_do_not_entail(self) -> None:
        # A link set that never reaches the target's predicate leaves the verdict
        # exactly where it was.
        beliefs = dict([_true("rose(r1)")])
        clauses = backward_implication_clauses("animal(r1)", {"rose": {"flower"}})
        assert clauses == []
        assert check_atom_support(beliefs, clauses, "animal(r1)").verdict == "NOT_ENTAILED"

    def test_multi_hop_chain_is_entailed(self) -> None:
        # r => q => p: the closure must carry the target, or "can the system verify
        # what it owns" would depend on the link graph's shape.
        beliefs = dict([_true("sparrow(s1)")])
        targets = {"sparrow": {"bird"}, "bird": {"animal"}}
        clauses = backward_implication_clauses("animal(s1)", targets)
        assert check_atom_support(beliefs, clauses, "animal(s1)").verdict == "ENTAILED"

    def test_cyclic_links_terminate(self) -> None:
        # p => q => p. Expanding each predicate once bounds the walk; the target
        # is still entailed from the antecedent actually on the beliefs.
        beliefs = dict([_true("q(x1)")])
        targets = {"p": {"q"}, "q": {"p"}}
        clauses = backward_implication_clauses("p(x1)", targets)
        assert check_atom_support(beliefs, clauses, "p(x1)").verdict == "ENTAILED"

    def test_antecedent_held_false_does_not_entail(self) -> None:
        beliefs = dict([_false("cat(felix)")])
        clauses = backward_implication_clauses("animal(felix)", {"cat": {"animal"}})
        assert check_atom_support(beliefs, clauses, "animal(felix)").verdict == "NOT_ENTAILED"

    def test_absent_antecedent_does_not_entail(self) -> None:
        # The link is present but nothing on the beliefs discharges it.
        clauses = backward_implication_clauses("animal(felix)", {"cat": {"animal"}})
        assert check_atom_support({}, clauses, "animal(felix)").verdict == "NOT_ENTAILED"

    def test_direction_is_not_symmetrized(self) -> None:
        # cat(x) -> animal(x) must not license animal(x) -> cat(x).
        beliefs = dict([_true("animal(felix)")])
        clauses = backward_implication_clauses("cat(felix)", {"cat": {"animal"}})
        assert check_atom_support(beliefs, clauses, "cat(felix)").verdict == "NOT_ENTAILED"

    def test_target_does_not_prove_itself(self) -> None:
        # The target sits in the belief set at face value, which is exactly the
        # probe environment's setup. Only OTHER beliefs may entail it, and here the
        # antecedent is missing, so the answer must stay NOT_ENTAILED.
        beliefs = dict([_true("animal(felix)")])
        clauses = backward_implication_clauses("animal(felix)", {"cat": {"animal"}})
        assert check_atom_support(beliefs, clauses, "animal(felix)").verdict == "NOT_ENTAILED"

    def test_other_arguments_are_untouched(self) -> None:
        # Implication is stated over the identical argument tuple.
        beliefs = dict([_true("cat(felix)")])
        clauses = backward_implication_clauses("animal(rex)", {"cat": {"animal"}})
        assert check_atom_support(beliefs, clauses, "animal(rex)").verdict == "NOT_ENTAILED"

    def test_multi_argument_target(self) -> None:
        beliefs = dict([_true("parent_of(alice, bob)")])
        clauses = backward_implication_clauses("ancestor_of(alice, bob)", {"parent_of": {"ancestor_of"}})
        assert check_atom_support(beliefs, clauses, "ancestor_of(alice, bob)").verdict == "ENTAILED"

    def test_malformed_target_yields_no_clauses(self) -> None:
        assert backward_implication_clauses("not an atom", {"cat": {"animal"}}) == []

    def test_output_is_deterministic(self) -> None:
        targets = {"cat": {"animal"}, "dog": {"animal"}, "mammal": {"animal"}}
        first = backward_implication_clauses("animal(x1)", targets)
        second = backward_implication_clauses("animal(x1)", targets)
        assert [str(expr) for expr in first] == [str(expr) for expr in second]
        assert len(first) == 3
