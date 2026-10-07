"""Set preference, scope and total-check budgets hold without arbitrary selection."""

from dataclasses import replace
from itertools import combinations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from endoxa.errors import InvalidArgumentError
from endoxa.governance import (
    Adopt,
    Assertion,
    ConsistencyResult,
    PremiseSet,
    RevisionPolicy,
    RevisionTrial,
    Rule,
    Withdraw,
    check_consistency,
    proposal,
    propose_revision,
    target_of,
)
from endoxa.governance import _revision_search as search


def claim(identifier, atom="p(a)", *, truth=True, confidence=0.5):
    return Assertion(id=identifier, atom=atom, truth_value=truth, confidence=confidence)


def withdrawn(outcome):
    return {change.target.id for change in outcome.changes if isinstance(change, Withdraw)}


def test_independent_conflicts_need_two_withdrawals_and_leave_inputs_intact():
    records = (
        claim("p-positive", confidence=0.8),
        claim("p-negative", truth=False, confidence=0.2),
        claim("q-positive", "q(a)", confidence=0.9),
        claim("q-negative", "q(a)", truth=False, confidence=0.3),
    )
    state = PremiseSet(assertions=records)
    assert propose_revision(state).reason == "no_verified_single_revision"
    result = propose_revision(state, max_withdrawals=2)
    assert result.decision == "proposed"
    assert withdrawn(result) == {"p-negative", "q-negative"}
    assert result.final.status == "SAT"
    assert result.binding.max_withdrawals == 2
    assert result.binding.max_checks == 256
    assert state.assertions == tuple(sorted(records, key=lambda record: record.id))


def test_two_lower_priority_withdrawals_preserve_one_more_important_rule():
    a, b = claim("a", truth=False, confidence=0.9), claim("b", "q(a)", truth=False, confidence=0.8)
    rule = Rule(id="r", formula="fof(r, axiom, (p(a) & q(a))).", confidence=0.1)
    state = PremiseSet(assertions=(a, b), rules=(rule,))
    policy = RevisionPolicy(priorities={target_of(rule): 10, target_of(a): -2, target_of(b): -2})
    result = propose_revision(state, policy, max_withdrawals=2)
    assert withdrawn(result) == {"a", "b"}
    assert all(target_of(rule) not in trial.omitted for trial in result.trials)
    assert result.final.status == "SAT"


def test_within_one_priority_layer_one_withdrawal_precedes_two_lower_confidences():
    state = PremiseSet(
        assertions=(claim("a", truth=False, confidence=0.1), claim("b", "q(a)", truth=False, confidence=0.2)),
        rules=(Rule(id="r", formula="fof(r, axiom, (p(a) & q(a))).", confidence=0.99),),
    )
    assert withdrawn(propose_revision(state, max_withdrawals=2)) == {"r"}


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("separate_layers", [False, True])
def test_equal_counts_compare_descending_confidences_not_their_sum(reverse, separate_layers):
    records = (
        claim("a", "p(a)", confidence=0.9),
        claim("b", "q(a)", confidence=0.1),
        claim("c", "r(a)", confidence=0.6),
        claim("d", "s(a)", confidence=0.5),
    )
    state = PremiseSet(
        assertions=tuple(reversed(records)) if reverse else records,
        hard_axioms=("fof(conflict, axiom, ~((p(a) | q(a)) & (r(a) | s(a)))).",),
    )
    policy = (
        RevisionPolicy(priorities={target_of(records[0]): 10, target_of(records[2]): 10})
        if separate_layers
        else RevisionPolicy()
    )
    assert withdrawn(propose_revision(state, policy, max_withdrawals=2)) == {"c", "d"}


def test_equal_set_ranks_defer_under_changed_ids_and_input_order():
    for identifiers in (("a", "b", "c", "d"), ("z", "x", "w", "v")):
        records = tuple(claim(identifier, f"{atom}(a)") for identifier, atom in zip(identifiers, "pqrs", strict=True))
        for ordered in (records, tuple(reversed(records))):
            state = PremiseSet(
                assertions=ordered,
                hard_axioms=("fof(conflict, axiom, ~((p(a) | q(a)) & (r(a) | s(a)))).",),
            )
            result = propose_revision(state, max_withdrawals=2)
            assert (result.decision, result.reason, result.changes) == ("deferred", "same_rank_tie", ())


def test_duplicate_owners_must_both_withdraw_when_opposite_owner_is_protected():
    records = (claim("one"), claim("two"), claim("negative", truth=False))
    state = PremiseSet(assertions=records)
    policy = RevisionPolicy(protected={target_of(records[2])})
    assert propose_revision(state, policy).reason == "no_verified_single_revision"
    result = propose_revision(state, policy, max_withdrawals=2)
    assert withdrawn(result) == {"one", "two"}
    assert len(result.trials[-1].omitted) == 2


def test_three_withdrawals_preserve_a_protected_opposite_owner():
    owners = tuple(claim(str(index)) for index in range(3))
    opposite = claim("opposite", truth=False)
    state = PremiseSet(assertions=(*owners, opposite))
    policy = RevisionPolicy(protected={target_of(opposite)})
    assert propose_revision(state, policy, max_withdrawals=2).reason == "no_verified_revision"
    result = propose_revision(state, policy, max_withdrawals=3, max_checks=9)
    assert withdrawn(result) == {record.id for record in owners}
    assert result.checks_used == 9
    assert len(result.trials) == 7
    assert result.final.status == "SAT"


def test_functional_scope_survives_two_withdrawals_and_rule_rederivation():
    old = claim("old", "location(a,old)", confidence=0.9)
    new = claim("new", "location(a,new)", confidence=0.1)
    rule = Rule(id="derive", formula="fof(r, axiom, location(a,new)).", confidence=0.2)
    state = PremiseSet(assertions=(old, new), rules=(rule,), functional_predicates={"location"})
    policy = RevisionPolicy(protected={target_of(old)})
    assert propose_revision(state, policy).reason == "no_verified_single_revision"
    result = propose_revision(state, policy, max_withdrawals=2)
    assert withdrawn(result) == {"new", "derive"}
    assert result.binding.functional_scope == state.functional_scope
    assert check_consistency(replace(state, assertions=(old,), rules=())).status == "SAT"


def test_protected_conflict_is_not_repaired_by_removing_unrelated_targets():
    positive, negative = claim("yes"), claim("no", truth=False)
    policy = RevisionPolicy(protected={target_of(positive), target_of(negative)})
    state = PremiseSet(assertions=(positive, negative, claim("other", "q(a)")))
    result = propose_revision(state, policy, max_withdrawals=2)
    assert (result.decision, result.reason) == ("deferred", "no_verified_revision")
    assert result.trials[0].omitted == (target_of(next(a for a in state.assertions if a.id == "other")),)


def test_protected_candidate_can_adopt_with_two_existing_withdrawals():
    state = PremiseSet(assertions=(claim("a", truth=False), claim("b", "q(a)", truth=False)))
    candidate = Rule(id="candidate", formula="fof(r, axiom, (p(a) & q(a))).", confidence=0.9)
    result = propose_revision(
        state, RevisionPolicy(protected={target_of(candidate)}), candidate=candidate, max_withdrawals=2
    )
    assert withdrawn(result) == {"a", "b"}
    assert result.changes[-1] == Adopt(record=candidate)
    assert result.original.status == result.final.status == "SAT"
    assert result.initial.status == "UNSAT"


def test_candidate_rejection_never_combines_with_existing_repair():
    state = PremiseSet(assertions=(claim("yes"), claim("no", truth=False)), hard_axioms=("fof(noq, axiom, ~q(a)).",))
    candidate = claim("candidate", "q(a)")
    result = propose_revision(state, candidate=candidate, max_withdrawals=2)
    assert result.reason == "no_verified_revision"
    assert not result.changes
    assert any(trial.omitted == (target_of(candidate),) for trial in result.trials)
    assert all(target_of(candidate) not in trial.omitted or len(trial.omitted) == 1 for trial in result.trials)


def test_initial_checks_and_cached_candidate_rejection_are_counted_exactly(monkeypatch):
    actual = proposal.check_consistency
    calls = []

    def check(state, **limits: int | None):
        calls.append((state, limits))
        return actual(state, **limits)

    monkeypatch.setattr(proposal, "check_consistency", check)
    old = claim("old", confidence=0.8)
    state = PremiseSet(assertions=(old,))
    assert propose_revision(state, max_checks=2).checks_used == len(calls) == 1
    calls.clear()
    neutral = claim("neutral", "q(a)")
    assert propose_revision(state, candidate=neutral, max_checks=2).checks_used == len(calls) == 2
    assert calls[0][0].assertions == state.assertions
    assert len(calls[1][0].assertions) == 2
    calls.clear()
    candidate = claim("candidate", truth=False, confidence=0.1)
    short = propose_revision(state, candidate=candidate, max_checks=2)
    assert short.reason == "check_budget_exhausted"
    assert short.checks_used == len(calls) == 2
    assert short.original.status == "SAT"
    assert short.initial.status == "UNSAT"
    assert short.fixed_base is None
    calls.clear()
    result = propose_revision(state, candidate=candidate, max_checks=3)
    assert result.reason == "candidate_rejected"
    assert result.checks_used == len(calls) == 3
    assert result.trials[0].result is result.original
    assert all(limits == {"max_rounds": None, "max_matches": None} for _, limits in calls)


def test_assertion_and_rule_with_identical_ids_are_distinct_withdrawal_targets():
    retained = claim("retained", confidence=0.9)
    negative = claim("shared", truth=False, confidence=0.1)
    rule = Rule(id="shared", formula="fof(r, axiom, ~p(a)).", confidence=0.2)
    result = propose_revision(
        PremiseSet(assertions=(retained, negative), rules=(rule,)),
        RevisionPolicy(protected={target_of(retained)}),
        max_withdrawals=2,
    )
    assert {change.target for change in result.changes} == {target_of(negative), target_of(rule)}
    assert result.final.status == "SAT"


@pytest.mark.parametrize(
    ("budget", "reason"), [(2, "check_budget_exhausted"), (3, "check_budget_exhausted"), (4, "same_rank_tie")]
)
def test_budget_must_cover_same_rank_competitors_even_after_a_sat_trial(budget, reason):
    state = PremiseSet(assertions=(claim("yes"), claim("no", truth=False)))
    result = propose_revision(state, max_checks=budget)
    assert result.reason == reason
    assert not result.changes
    assert result.checks_used == budget
    if budget == 3:
        assert len(result.trials) == 1
        assert result.trials[0].result.status == "SAT"


def test_budget_need_not_cover_inferior_candidates_after_unique_best_is_verified():
    state = PremiseSet(assertions=(claim("yes", confidence=0.1), claim("no", truth=False, confidence=0.9)))
    result = propose_revision(state, max_checks=3, max_withdrawals=2)
    assert withdrawn(result) == {"yes"}
    assert result.checks_used == 3
    assert len(result.trials) == 1


def test_same_rank_unknown_blocks_a_verified_sat_trial(monkeypatch):
    a, b = claim("a"), claim("b", truth=False)
    actual = proposal.check_consistency

    def check(state, **limits: int | None):
        if state.assertions == (a,):
            return ConsistencyResult(status="UNKNOWN", assumptions=(), core=())
        return actual(state, **limits)

    monkeypatch.setattr(proposal, "check_consistency", check)
    result = propose_revision(PremiseSet(assertions=(a, b)), max_withdrawals=2)
    assert result.reason == "trial_unknown"
    assert not result.changes
    assert [trial.result.status for trial in result.trials] == ["SAT", "UNKNOWN"]


def test_huge_search_space_is_visited_only_as_far_as_the_check_budget(monkeypatch):
    calls = []

    def check(state, **_limits: int | None):
        calls.append(state)
        return ConsistencyResult(status="UNSAT" if state.assertions else "SAT", assumptions=(), core=())

    monkeypatch.setattr(proposal, "check_consistency", check)
    records = tuple(claim(str(index), f"p(c{index})", confidence=index / 100) for index in range(60))
    result = propose_revision(PremiseSet(assertions=records), max_withdrawals=60, max_checks=4)
    assert result.reason == "check_budget_exhausted"
    assert result.checks_used == len(calls) == 4
    assert len(result.trials) == 2


@pytest.mark.parametrize("budget", [2, 4, 16])
def test_check_budget_also_bounds_subset_expansion(monkeypatch, budget):
    expansions = []
    actual = search._successors

    def successors(indices, size, limit):
        result = actual(indices, size, limit)
        expansions.append(result)
        return result

    def check(state, **_limits: int | None):
        return ConsistencyResult(status="UNSAT" if state.assertions else "SAT", assumptions=(), core=())

    monkeypatch.setattr(search, "_successors", successors)
    monkeypatch.setattr(proposal, "check_consistency", check)
    records = tuple(claim(str(index), f"p(c{index})") for index in range(60))
    result = propose_revision(PremiseSet(assertions=records), max_withdrawals=60, max_checks=budget)
    assert result.reason == "check_budget_exhausted"
    assert result.checks_used == budget
    assert len(expansions) == len(result.trials) == budget - 2
    assert sum(len(successors) for successors in expansions) <= 2 * (budget - 2)


@given(
    st.lists(st.tuples(st.integers(-2, 2), st.sampled_from([0.1, 0.5, 0.9]), st.booleans()), max_size=6),
    st.integers(1, 6),
    st.integers(-2, 2),
    st.booleans(),
)
@settings(max_examples=80, deadline=None)
def test_lazy_order_matches_all_bounded_sets_and_standalone_rejection(
    data, limit, candidate_priority, protected_candidate
):
    records = tuple(
        Rule(id=str(index), formula=f"fof(r, axiom, p(c{index})).", confidence=confidence)
        if index % 2
        else claim(str(index), f"p(c{index})", confidence=confidence)
        for index, (_, confidence, _) in enumerate(data)
    )
    candidate = claim("candidate", confidence=0.5)
    protected = {target_of(record) for record, entry in zip(records, data, strict=True) if entry[2]}
    if protected_candidate:
        protected.add(target_of(candidate))
    policy = RevisionPolicy(
        protected=protected,
        priorities={
            **{target_of(record): entry[0] for record, entry in zip(records, data, strict=True)},
            target_of(candidate): candidate_priority,
        },
    )
    eligible = tuple(record for record in records if target_of(record) not in protected)
    sets = [omitted for size in range(1, min(limit, len(eligible)) + 1) for omitted in combinations(eligible, size)]
    if not protected_candidate:
        sets.append((candidate,))
    layers = sorted(set(policy.priorities.values()), reverse=True)
    expected = {}
    for omitted in sets:
        counts = tuple(sum(policy.priorities[target_of(record)] == layer for record in omitted) for layer in layers)
        confidence = tuple(
            tuple(
                sorted(
                    (record.confidence for record in omitted if policy.priorities[target_of(record)] == layer),
                    reverse=True,
                )
            )
            for layer in layers
        )
        expected[frozenset(target_of(record) for record in omitted)] = (counts, confidence)
    actual = tuple(search.ordered_omissions(records, policy, candidate, limit))
    assert len(actual) == len(expected)
    assert {frozenset(omitted): rank for rank, omitted in actual} == expected
    assert [rank for rank, _ in actual] == sorted(expected.values())


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_withdrawals", v) for v in (0, -1, True, None, 1.5)]
    + [("max_checks", v) for v in (0, 1, -1, True, None, 1.5)],
)
def test_search_limit_validation_precedes_even_consistent_return(field, value):
    with pytest.raises(InvalidArgumentError, match=field):
        propose_revision(PremiseSet(), **{field: value})


@pytest.mark.parametrize("targets", [(), ("a",), (target_of(claim("a")),) * 2])
def test_trial_omissions_require_distinct_typed_targets(targets):
    with pytest.raises(InvalidArgumentError):
        RevisionTrial(omitted=targets, result=ConsistencyResult(status="SAT", assumptions=(), core=()))


@given(
    st.lists(
        st.tuples(st.integers(0, 1), st.booleans(), st.sampled_from([0.1, 0.5, 0.9]), st.integers(-1, 1)), max_size=6
    )
)
@settings(max_examples=60, deadline=None)
def test_bounded_proposals_match_an_exhaustive_small_state_oracle(data):
    records = tuple(
        claim(str(index), f"p(c{atom})", truth=truth, confidence=confidence)
        for index, (atom, truth, confidence, _) in enumerate(data)
    )
    state = PremiseSet(assertions=records)
    policy = RevisionPolicy(
        priorities={target_of(record): entry[3] for record, entry in zip(records, data, strict=True)}
    )
    result = propose_revision(state, policy, max_withdrawals=2)
    if check_consistency(state).status == "SAT":
        assert result.decision == "unchanged"
        return
    priorities = sorted(set(policy.priorities.values()), reverse=True)
    repairs = []
    for size in (1, 2):
        for omitted in combinations(records, size):
            remaining = replace(state, assertions=tuple(record for record in records if record not in omitted))
            if check_consistency(remaining).status == "SAT":
                counts = tuple(
                    sum(policy.priorities[target_of(record)] == priority for record in omitted)
                    for priority in priorities
                )
                confidences = tuple(
                    tuple(
                        sorted(
                            (
                                record.confidence
                                for record in omitted
                                if policy.priorities[target_of(record)] == priority
                            ),
                            reverse=True,
                        )
                    )
                    for priority in priorities
                )
                repairs.append(((counts, confidences), {record.id for record in omitted}))
    if not repairs:
        assert result.reason == "no_verified_revision"
    else:
        best_rank = min(rank for rank, _ in repairs)
        best = [targets for rank, targets in repairs if rank == best_rank]
        if len(best) > 1:
            assert result.reason == "same_rank_tie"
            assert not result.changes
        else:
            assert result.decision == "proposed"
            assert withdrawn(result) == best[0]
