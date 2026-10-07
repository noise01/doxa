"""Public proposal contracts, including owners, rules, policy and incomplete search."""

from dataclasses import FrozenInstanceError, replace

import pytest

from endoxa.errors import InvalidArgumentError, RuleSyntaxError
from endoxa.governance import (
    Adopt,
    Assertion,
    ConsistencyResult,
    PremiseSet,
    RevisionPolicy,
    Rule,
    Target,
    Withdraw,
    check_consistency,
    check_entailment,
    check_support,
    proposal,
    propose_revision,
    target_of,
)


def claim(identifier, *, truth=True, confidence=0.5, atom="p(a)"):
    return Assertion(id=identifier, atom=atom, truth_value=truth, confidence=confidence)


def test_multiple_owners_preserve_every_id_and_withdraw_only_one():
    positive = claim("one", confidence=0.8)
    duplicate = claim("two", confidence=0.7, atom=" p( a ) ")
    negative = claim("negative", truth=False, confidence=0.2)
    state = PremiseSet(assertions=(positive, duplicate, negative))
    checked = check_consistency(state)
    assert checked.status == "UNSAT"
    assert next(item for item in checked.assumptions if item.truth_value).owner_ids == ("one", "two")
    outcome = propose_revision(state)
    assert outcome.changes == (Withdraw(target=target_of(negative)),)
    assert negative.truth_value is False
    assert outcome.final.status == "SAT"
    assert check_support(state, "p(a)").verdict == "NOT_ENTAILED"
    assert (
        check_entailment(PremiseSet(assertions=(positive, duplicate)), "fof(q, conjecture, p(a)).").verdict
        == "ENTAILED"
    )


def test_rule_withdrawal_is_not_confidence_zero_or_negation():
    rule = Rule(id="rule", formula="fof(r, axiom, ~p(a)).", confidence=0.1)
    positive = claim("rule", confidence=0.9)
    outcome = propose_revision(PremiseSet(assertions=(positive,), rules=(rule,)))
    assert outcome.changes == (Withdraw(target=Target(kind="rule", id="rule")),)
    assert rule.confidence == 0.1
    assert outcome.final.status == "SAT"


def test_support_keeps_rules_and_other_premises_in_both_query_polarities():
    rule = Rule(id="r", formula="fof(r, axiom, (q(a) => p(a))).", confidence=0.9)
    state = PremiseSet(assertions=(claim("a"), claim("b", truth=False), claim("q", atom="q(a)")), rules=(rule,))
    assert check_support(state, "p(a)").verdict == "ENTAILED"
    assert check_support(state, "p(a)", truth_value=False).verdict == "NOT_ENTAILED"
    assert check_entailment(state, "fof(q, conjecture, p(a)).").verdict == "INCONSISTENT_PREMISES"


def test_same_rank_has_no_id_or_kind_tiebreak():
    rule = Rule(id="z", formula="fof(r, axiom, ~p(a)).", confidence=0.5)
    outcome = propose_revision(PremiseSet(assertions=(claim("a"),), rules=(rule,)))
    assert outcome.decision == "deferred"
    assert outcome.reason == "same_rank_tie"
    assert outcome.changes == ()


def test_priority_precedes_confidence_and_protection_precedes_priority():
    a, b = claim("a", confidence=0.9), claim("b", truth=False, confidence=0.1)
    state = PremiseSet(assertions=(a, b))
    policy = RevisionPolicy(priorities={target_of(a): -1})
    assert propose_revision(state, policy).changes == (Withdraw(target=target_of(a)),)
    protected = RevisionPolicy(protected={target_of(a)}, priorities={target_of(a): -1})
    assert propose_revision(state, protected).changes == (Withdraw(target=target_of(b)),)


def test_confidence_one_is_not_implicitly_protected():
    a, b = claim("a", confidence=1.0), claim("b", truth=False, confidence=1.0)
    outcome = propose_revision(PremiseSet(assertions=(a, b)), RevisionPolicy(protected={target_of(a)}))
    assert outcome.changes == (Withdraw(target=target_of(b)),)


def test_candidate_can_be_adopted_rejected_or_tied_without_novelty_bias():
    old = claim("old", confidence=0.7)
    state = PremiseSet(assertions=(old,))
    candidate = claim("new", truth=False, confidence=0.3)
    rejected = propose_revision(state, candidate=candidate)
    assert rejected.decision == "unchanged"
    assert rejected.reason == "candidate_rejected"
    assert rejected.changes == ()
    assert rejected.original.status == rejected.final.status == "SAT"
    stronger = replace(candidate, confidence=0.9)
    accepted = propose_revision(state, candidate=stronger)
    assert accepted.changes == (Withdraw(target=target_of(old)), Adopt(record=stronger))
    assert propose_revision(state, candidate=replace(candidate, confidence=0.7)).reason == "same_rank_tie"
    neutral = claim("other", atom="q(a)")
    assert propose_revision(state, candidate=neutral).changes == (Adopt(record=neutral),)


def test_candidate_rule_and_protected_candidate():
    old = claim("a", confidence=0.9)
    candidate = Rule(id="new", formula="fof(r, axiom, ~p(a)).", confidence=0.1)
    state = PremiseSet(assertions=(old,))
    assert propose_revision(state, candidate=candidate).reason == "candidate_rejected"
    result = propose_revision(state, RevisionPolicy(protected={target_of(candidate)}), candidate=candidate)
    assert result.changes == (Withdraw(target=target_of(old)), Adopt(record=candidate))


def test_rejecting_candidate_does_not_certify_inconsistent_original():
    state = PremiseSet(assertions=(claim("a"), claim("b", truth=False)))
    candidate = claim("candidate", atom="q(a)", confidence=0.01)
    result = propose_revision(state, candidate=candidate)
    rejected_trial = next(trial for trial in result.trials if trial.omitted == (target_of(candidate),))
    assert result.original.status == rejected_trial.result.status == "UNSAT"
    assert result.reason == "same_rank_tie"


def test_fixed_conflict_and_search_exhaustion_are_distinct():
    fixed = propose_revision(PremiseSet(hard_axioms=("fof(no, axiom, $false).",)))
    assert fixed.reason == "fixed_base_unsat"
    assert fixed.fixed_base.status == "UNSAT"
    state = PremiseSet(
        assertions=(claim("a"), claim("b", truth=False), claim("c", atom="q(a)"), claim("d", truth=False, atom="q(a)"))
    )
    result = propose_revision(state)
    assert result.reason == "no_verified_single_revision"
    assert all(trial.result.status == "UNSAT" for trial in result.trials)


def test_functional_exclusion_and_explicit_recency_policy():
    old, new = (
        claim("old", atom="location(a,old)", confidence=1.0),
        claim("new", atom="location(a,new)", confidence=1.0),
    )
    state = PremiseSet(assertions=(old,), functional_predicates={"location"})
    assert propose_revision(state, candidate=new).reason == "same_rank_tie"
    policy = RevisionPolicy(priorities={target_of(old): -1})
    result = propose_revision(state, policy, candidate=new)
    assert result.changes == (Withdraw(target=target_of(old)), Adopt(record=new))
    assert result.binding.premises.functional_predicates == {"location"}
    assert old.truth_value is True
    unary = PremiseSet(assertions=(claim("a", atom="p(a)"), claim("b", atom="p(b)")), functional_predicates={"p"})
    assert check_consistency(unary).status == "SAT"


def test_real_solver_unknown_defers():
    loop = Rule(id="loop", formula="fof(loop, axiom, ![X]: (p(X) => p(f(X)))).", confidence=0.9)
    result = propose_revision(PremiseSet(assertions=(claim("a"),), rules=(loop,)), max_rounds=2)
    assert result.initial.status == "UNKNOWN"
    assert result.reason == "initial_unknown"
    assert result.changes == ()


def test_functional_withdrawal_cannot_hide_a_rule_derived_value():
    old = claim("old", atom="location(a,old)", confidence=0.8)
    new = claim("new", atom="location(a,new)", confidence=0.2)
    rule = Rule(id="r", formula="fof(r, axiom, location(a,new)).", confidence=0.9)
    state = PremiseSet(assertions=(old, new), rules=(rule,), functional_predicates={"location"})
    result = propose_revision(state)
    assert result.initial.status == "UNSAT"
    assert result.trials[0].omitted == (target_of(new),)
    assert result.trials[0].result.status == "UNSAT"
    assert result.changes == (Withdraw(target=target_of(old)),)
    assert result.final.status == "SAT"
    remaining = replace(state, assertions=(old,))
    assert check_consistency(remaining).status == "UNSAT"
    assert check_support(remaining, new.atom).verdict == "INCONSISTENT_PREMISES"
    assert check_entailment(remaining, "fof(q, conjecture, location(a,new)).").verdict == "INCONSISTENT_PREMISES"
    assert result.binding.functional_scope == state.functional_scope


def test_functional_rule_withdrawal_really_restores_consistency():
    old = claim("old", atom="location(a,old)", confidence=0.8)
    candidate = claim("candidate", atom="location(a,new)", truth=False, confidence=0.7)
    rule = Rule(id="r", formula="fof(r, axiom, location(a,new)).", confidence=0.1)
    state = PremiseSet(assertions=(old,), rules=(rule,), functional_predicates={"location"})
    result = propose_revision(state, candidate=candidate)
    assert result.changes == (Withdraw(target=target_of(rule)), Adopt(record=candidate))
    assert result.final.status == "SAT"
    assert result.binding.functional_scope == {old.atom, candidate.atom}


def test_functional_candidate_rejection_uses_candidate_inclusive_scope():
    old = claim("old", atom="location(a,old)", confidence=0.8)
    candidate = claim("candidate", atom="location(a,new)", confidence=0.1)
    rule = Rule(id="r", formula="fof(r, axiom, location(a,new)).", confidence=0.9)
    state = PremiseSet(assertions=(old,), rules=(rule,), functional_predicates={"location"})
    result = propose_revision(state, candidate=candidate)
    assert result.original.status == "UNSAT"
    assert result.trials[0].omitted == (target_of(candidate),)
    assert result.trials[0].result.status == "UNSAT"
    assert result.changes == (Withdraw(target=target_of(old)), Adopt(record=candidate))
    assert result.final.status == "SAT"
    without_rule = replace(state, rules=())
    rejected = propose_revision(without_rule, candidate=candidate)
    assert rejected.reason == "candidate_rejected"
    assert rejected.final.status == "SAT"


def test_functional_duplicate_owners_and_unconfigured_predicates():
    old = claim("old", atom="location(a,old)", confidence=0.8)
    new = claim("new", atom="location(a,new)", confidence=0.1)
    alias = replace(new, id="alias", confidence=0.2)
    state = PremiseSet(assertions=(old, new, alias), functional_predicates={"location"})
    result = propose_revision(state)
    assert [trial.result.status for trial in result.trials] == ["UNSAT", "UNSAT", "SAT"]
    assert result.changes == (Withdraw(target=target_of(old)),)
    assert propose_revision(replace(state, functional_predicates=())).reason == "already_consistent"


def test_functional_scope_is_canonical_immutable_and_cannot_omit_active_atoms():
    scope = ["location( a, new )"]
    old = claim("old", atom="location(a,old)")
    state = PremiseSet(assertions=(old,), functional_scope=scope, functional_predicates={"location"})
    scope.clear()
    assert state.functional_scope == {old.atom, "location(a,new)"}
    assert check_consistency(state).status == "SAT"
    with pytest.raises(InvalidArgumentError):
        PremiseSet(functional_scope="location(a,new)")
    with pytest.raises(RuleSyntaxError):
        PremiseSet(functional_scope={"location(X,new)"})


def test_candidate_rejection_retains_unknown_original_verdict():
    loop = Rule(id="loop", formula="fof(loop, axiom, ![X]: (p(X) => p(f(X)))).", confidence=0.9)
    old = claim("old", confidence=0.8)
    state = PremiseSet(assertions=(old,), rules=(loop,))
    candidate = claim("new", truth=False, confidence=0.1)
    result = propose_revision(state, candidate=candidate, max_rounds=2)
    assert result.original.status == "UNKNOWN"
    assert result.initial.status == "UNSAT"
    assert result.trials[0].omitted == (target_of(candidate),)
    assert result.trials[0].result.status == "UNKNOWN"
    assert result.reason == "trial_unknown"
    assert result.changes == ()


@pytest.mark.parametrize("priority", [True, 1.5, "first", None])
def test_invalid_priority_is_an_input_error(priority):
    with pytest.raises(InvalidArgumentError):
        RevisionPolicy(priorities={target_of(claim("a")): priority})


@pytest.mark.parametrize("protected", [{"a"}, "a", [None]])
def test_invalid_protection_is_an_input_error(protected):
    with pytest.raises(InvalidArgumentError):
        RevisionPolicy(protected=protected)


def test_same_id_across_kinds_has_distinct_policy_references():
    assertion = claim("shared", confidence=0.5)
    rule = Rule(id="shared", formula="fof(r, axiom, ~p(a)).", confidence=0.5)
    policy = RevisionPolicy(protected={target_of(assertion)})
    result = propose_revision(PremiseSet(assertions=(assertion,), rules=(rule,)), policy)
    assert result.changes == (Withdraw(target=target_of(rule)),)
    assert target_of(rule) != target_of(assertion)


def test_unknown_in_later_rank_does_not_change_an_earlier_verified_choice(monkeypatch):
    old = claim("old", confidence=0.1)
    other = claim("other", truth=False, confidence=0.8)
    actual = proposal.check_consistency
    calls = []

    def check(premises, **limits: int | None):
        calls.append(premises)
        if premises.assertions == (old,):
            return ConsistencyResult(status="UNKNOWN", assumptions=(), core=())
        return actual(premises, **limits)

    monkeypatch.setattr(proposal, "check_consistency", check)
    result = propose_revision(PremiseSet(assertions=(old, other)))
    assert result.changes == (Withdraw(target=target_of(old)),)
    assert all(state.assertions != (old,) for state in calls)


def test_unknown_trial_blocks_selection_and_descent(monkeypatch):

    a, b = claim("a"), claim("b", truth=False)
    state = PremiseSet(assertions=(a, b))
    actual = proposal.check_consistency

    def check(premises, **limits: int | None):
        if len(premises.assertions) == 1 and premises.assertions[0].id == "b":
            return ConsistencyResult(status="UNKNOWN", assumptions=(), core=())
        return actual(premises, **limits)

    monkeypatch.setattr(proposal, "check_consistency", check)
    result = proposal.propose_revision(state)
    assert result.reason == "trial_unknown"
    assert result.changes == ()


def test_binding_is_immutable_and_captures_policy_confidence_and_source():
    a, b = claim("a"), claim("b", truth=False, confidence=0.2)
    priorities = {target_of(b): -1}
    policy = RevisionPolicy(priorities=priorities)
    result = propose_revision(PremiseSet(assertions=(a, b)), policy)
    priorities[target_of(b)] = 20
    assert result.binding.policy.priorities[target_of(b)] == -1
    assert result.binding.premises != PremiseSet(assertions=(a, replace(b, confidence=0.1)))
    assert result.binding.premises != PremiseSet(assertions=(a, replace(b, source="observation")))
    with pytest.raises(FrozenInstanceError):
        b.truth_value = True
    with pytest.raises(TypeError):
        policy.priorities[target_of(b)] = 3


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_invalid_confidence_is_not_unknown(confidence):
    with pytest.raises(InvalidArgumentError):
        claim("bad", confidence=confidence)


def test_invalid_ids_policy_and_limits_raise_before_search():
    a = claim("a")
    with pytest.raises(InvalidArgumentError):
        PremiseSet(assertions=(a, a))
    with pytest.raises(InvalidArgumentError):
        propose_revision(PremiseSet(assertions=(a,)), candidate=a)
    with pytest.raises(InvalidArgumentError):
        propose_revision(PremiseSet(), RevisionPolicy(protected={target_of(a)}))
    with pytest.raises(InvalidArgumentError):
        propose_revision(PremiseSet(), max_matches=True)
