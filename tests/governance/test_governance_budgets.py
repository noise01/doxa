"""Budget cuts stay inconclusive, including every revision re-check."""

import pytest

from endoxa.governance import Belief, Constraints, GovernanceOutcome, Rule, govern
from endoxa.governance.revision import (
    PredicateConstraints,
    check_consistency,
    entails,
    find_link_culprits,
    find_rule_culprits,
    find_supporting_rules,
    select_tie_question_target,
    select_verified_revision_target,
)
from endoxa.solver import Expr, Solver, parse_fof

LOOP = "fof(loop, axiom, ![X] : (p(X) => p(f(X))))."
IMPLICATION = "fof(impl, axiom, ![X] : (p(X) => q(X)))."
EXCLUSION = "fof(excl, axiom, ~(p(a) & q(a)))."


def test_unknown_is_not_a_consistency_certificate():
    outcome = govern([Belief("p(a)", truth_value=True, confidence=1.0)], Constraints(hard_axioms=(LOOP,)), max_rounds=2)
    assert outcome.consistent is None
    assert outcome.ops == ()
    assert outcome.hold is None
    assert outcome.undecided is False


def test_a_match_work_cut_is_inconclusive_too():
    outcome = govern(
        [Belief("p(a)", truth_value=True, confidence=1.0)], Constraints(hard_axioms=(IMPLICATION,)), max_matches=0
    )
    assert outcome.consistent is None
    assert outcome.ops == ()


def test_a_known_conflict_without_a_revision_is_distinct_from_unknown():
    outcome = govern([], Constraints(hard_axioms=("fof(no, axiom, $false).",)), max_rounds=0, max_matches=0)
    assert outcome.consistent is False
    assert outcome.undecided is True


def test_existing_outcome_construction_keeps_its_field_order():
    assert GovernanceOutcome(True, (), None, False).consistent is True  # noqa: FBT003 - positional compatibility


@pytest.mark.parametrize(("confidence", "defeasible", "checks"), [(0.6, True, 4), (1.0, False, 3)])
def test_govern_bounds_every_fact_rule_and_tie_recheck(monkeypatch, confidence, defeasible, checks):
    original = Solver.check
    budgets = []

    def bounded_check(self, *assumptions: Expr, max_rounds=None, max_matches=None):
        budgets.append((max_rounds, max_matches))
        # Keep a missing propagation from making this regression test hang.
        return original(self, *assumptions, max_rounds=2, max_matches=32)

    monkeypatch.setattr(Solver, "check", bounded_check)
    outcome = govern(
        [
            Belief("p(a)", truth_value=True, confidence=confidence),
            Belief("q(a)", truth_value=True, confidence=confidence),
        ],
        Constraints(rules=(Rule("excl", EXCLUSION, 1.0, defeasible=defeasible),)),
        max_rounds=2,
        max_matches=32,
    )
    assert outcome.consistent is False
    assert len(budgets) >= checks
    if not defeasible:
        assert outcome.hold is not None
    assert set(budgets) == {(2, 32)}


def test_low_level_queries_bound_work_and_keep_unknown():
    beliefs = {"p(a)": {"truth_value": True, "confidence": 1.0}}
    rules = [parse_fof(IMPLICATION)[2]]
    assert check_consistency(beliefs, rules, max_matches=0)[0] == "UNKNOWN"
    assert entails(beliefs, rules, "q(a)", max_matches=0) == "UNKNOWN"
    assert find_supporting_rules(beliefs, rules, rules, "q(a)", max_matches=0) == []


def test_rule_rechecks_do_not_accept_an_inconclusive_removal():
    beliefs = {"p(a)": {"truth_value": True, "confidence": 1.0}}
    loop = parse_fof(LOOP)[2]
    conflict = parse_fof("fof(no, axiom, ~p(a)).")[2]
    assert find_rule_culprits(beliefs, [loop, conflict], [conflict], max_rounds=2, max_matches=32) == []


def test_link_rechecks_do_not_accept_an_inconclusive_removal():
    beliefs = {name: {"truth_value": True, "confidence": 0.6} for name in ("p(a)", "q(a)")}
    links = PredicateConstraints(exclusion_targets={"p": ("q",)})
    assert find_link_culprits(beliefs, [parse_fof(LOOP)[2]], links, max_rounds=2, max_matches=32) == []


@pytest.mark.parametrize("selector", [select_verified_revision_target, select_tie_question_target])
def test_fact_and_tie_completions_preserve_work_limits(selector):
    beliefs = {name: {"truth_value": True, "confidence": 0.6} for name in ("p(a)", "q(a)")}
    result, core, mapping = check_consistency(beliefs, [parse_fof(EXCLUSION)[2]])
    assert result == "UNSAT"
    # After either flip the loop is relevant to the remaining p(a), or a
    # quantified implication is relevant to q(a). No completion is certified.
    rules = [parse_fof("fof(r, axiom, ![X] : (q(X) => r(X))).")[2], parse_fof(LOOP)[2]]
    assert (
        selector(
            core,
            beliefs,
            mapping,
            rules,
            max_rounds=2,
            max_matches=0,
            links=PredicateConstraints(exclusion_targets={"p": ("q",)}),
        )
        is None
    )


def test_existing_round_cap_reaches_rule_removal(monkeypatch):
    original = Solver.check
    rounds = []

    def bounded_check(self, *assumptions: Expr, max_rounds=None, max_matches=None):
        rounds.append((max_rounds, max_matches))
        return original(self, *assumptions, max_rounds=2, max_matches=32)

    monkeypatch.setattr(Solver, "check", bounded_check)
    govern(
        [Belief("p(a)", truth_value=True, confidence=0.6), Belief("q(a)", truth_value=True, confidence=0.6)],
        Constraints(rules=(Rule("excl", EXCLUSION, 1.0),)),
        max_rounds=2,
    )
    assert len(rounds) >= 4
    assert set(rounds) == {(2, None)}


def test_support_rechecks_do_not_turn_unknown_into_a_lost_support():
    beliefs = {"p(a)": {"truth_value": True, "confidence": 1.0}}
    implication = parse_fof(IMPLICATION)[2]
    loop = parse_fof(LOOP)[2]
    rules = [implication, loop]
    assert entails(beliefs, rules, "q(a)", max_rounds=2, max_matches=32) == "ENTAILED"
    assert find_supporting_rules(beliefs, rules, [implication], "q(a)", max_rounds=2, max_matches=32) == []
