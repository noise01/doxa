"""Read-only multiple ownership, sound attribution, and explicit uncertainty."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from itertools import permutations
from typing import get_type_hints

import pytest

from endoxa.errors import InvalidArgumentError, RuleSyntaxError
from endoxa.governance import (
    Belief,
    BeliefAssumption,
    BeliefConsistencyResult,
    Constraints,
    check_belief_consistency,
    govern,
    parse_premise_fof,
)
from endoxa.governance.revision import check_consistency
from endoxa.solver import BOOL_SORT, BoolVal, Eq, Not, Solver


def belief(identifier, atom="p(a)", *, truth=True, **metadata: object):
    return Belief(
        id=identifier,
        atom=atom,
        truth_value=truth,
        confidence=metadata.get("confidence", 0.7),
        stance=metadata.get("stance", "asserted"),
        source=metadata.get("source"),
    )


def assert_sound(result, axioms=()):
    assert set(result.core) <= set(result.assumptions)
    solver = Solver()
    for axiom in axioms:
        solver.add(parse_premise_fof(axiom)[2])
    expressions = []
    for item in result.core:
        atom = parse_premise_fof(f"fof(c,axiom,{item.atom}).")[2]
        expressions.append(atom if item.truth_value else Not(atom))
    assert solver.check(*expressions) == "UNSAT"


def test_polarities_and_every_owner_are_preserved_for_all_input_orders():
    beliefs = [belief("z", "p( a )"), belief("a", truth=True), belief("n", truth=False)]
    original = deepcopy(beliefs)
    expected = (
        BeliefAssumption(atom="p(a)", truth_value=False, owner_ids=("n",)),
        BeliefAssumption(atom="p(a)", truth_value=True, owner_ids=("a", "z")),
    )
    for ordered in permutations(beliefs):
        result = check_belief_consistency(ordered)
        assert result.status == "UNSAT"
        assert result.assumptions == result.core == expected
        assert_sound(result)
    assert beliefs == original
    assert check_belief_consistency(beliefs[1:]).status == "UNSAT"
    assert check_belief_consistency([beliefs[2]]).status == "SAT"


def test_same_polarity_and_metadata_do_not_select_or_rank_an_owner():
    result = check_belief_consistency(
        [
            belief("tool", source="tool", confidence=0.1, stance="hypothesis"),
            belief("person", source="user", confidence=1.0),
        ]
    )
    assert result.status == "SAT"
    assert result.core == ()
    assert result.assumptions == (BeliefAssumption(atom="p(a)", truth_value=True, owner_ids=("person", "tool")),)
    assert check_belief_consistency([]) == BeliefConsistencyResult(status="SAT", assumptions=(), core=())


@pytest.mark.parametrize(
    ("axioms", "beliefs"),
    [
        (["fof(r,axiom,![X]:(p(X)=>q(X)))."], [belief("p"), belief("q", "q(a)", truth=False)]),
        (["fof(e,axiom,a=b)."], [belief("p"), belief("q", "p(b)", truth=False)]),
        (["fof(p,axiom,p(a))."], [belief("n", truth=False)]),
        (["fof(p,axiom,p(a)).", "fof(n,axiom,~p(a))."], []),
    ],
)
def test_core_is_sound_with_fixed_axioms(axioms, beliefs):
    result = check_belief_consistency(beliefs, axioms)
    assert result.status == "UNSAT"
    assert_sound(result, axioms)
    if not beliefs:
        assert result.core == ()


@pytest.mark.parametrize("limits", [{"max_rounds": 0}, {"max_rounds": 1}, {"max_matches": 0}, {"max_matches": 1}])
def test_real_budget_cut_is_unknown_and_keeps_ownership(limits):
    result = check_belief_consistency([belief("seed")], ["fof(loop,axiom,![X]:(p(X)=>p(f(X))))."], **limits)
    assert result.status == "UNKNOWN"
    assert result.core == ()
    assert result.assumptions[0].owner_ids == ("seed",)


def test_zero_budgets_do_not_hide_a_ground_conflict():
    result = check_belief_consistency([belief("yes"), belief("no", truth=False)], max_rounds=0, max_matches=0)
    assert result.status == "UNSAT"
    assert_sound(result)


@pytest.mark.parametrize("name", ["max_rounds", "max_matches"])
@pytest.mark.parametrize("value", [-1, True, False, 1.5, "1"])
def test_invalid_limits_are_errors(name, value):
    with pytest.raises(InvalidArgumentError):
        check_belief_consistency([], **{name: value})


@pytest.mark.parametrize(
    ("beliefs", "axioms", "error"),
    [
        ([belief("same"), belief("same")], [], InvalidArgumentError),
        ([belief("same"), belief("same", truth=False)], [], InvalidArgumentError),
        ([{}], [], InvalidArgumentError),
        ("p(a)", [], InvalidArgumentError),
        ([], "fof(p,axiom,p).", InvalidArgumentError),
        ([], ["fof(p,conjecture,p)."], RuleSyntaxError),
        ([], ["not fof"], RuleSyntaxError),
        ([], ["fof(p,axiom,p). fof(q,axiom,q)."], RuleSyntaxError),
    ],
)
def test_invalid_inputs_do_not_become_unknown(beliefs, axioms, error):
    with pytest.raises(error):
        check_belief_consistency(beliefs, axioms)


def test_all_axioms_are_validated_even_after_a_base_contradiction():
    with pytest.raises(RuleSyntaxError):
        check_belief_consistency([], ["fof(p,axiom,p).", "fof(n,axiom,~p).", "bad"])


def test_strict_governance_and_revision_still_refuse_multiple_owners():
    beliefs = [belief("first"), belief("second", truth=False)]
    with pytest.raises(InvalidArgumentError):
        govern(beliefs, Constraints())
    with pytest.raises(InvalidArgumentError):
        check_consistency({item.id: item.to_record() for item in beliefs}, [])


def test_frozen_records_copy_lists_and_validate_result_states():
    owners = ["z", "a"]
    item = BeliefAssumption(atom="p( a )", truth_value=True, owner_ids=owners)
    assumptions = [item]
    result = BeliefConsistencyResult(status="SAT", assumptions=assumptions, core=[])
    owners.clear()
    assumptions.clear()
    assert result.assumptions[0].owner_ids == ("a", "z")
    with pytest.raises(FrozenInstanceError):
        result.status = "UNSAT"
    with pytest.raises(FrozenInstanceError):
        item.truth_value = False
    for status in ("SAT", "UNKNOWN"):
        with pytest.raises(InvalidArgumentError):
            BeliefConsistencyResult(status=status, assumptions=(item,), core=(item,))
    with pytest.raises(InvalidArgumentError):
        BeliefConsistencyResult(status="UNSAT", assumptions=(), core=(item,))
    with pytest.raises(InvalidArgumentError):
        BeliefConsistencyResult(status="invalid", assumptions=(), core=())
    assert get_type_hints(check_belief_consistency)["return"] is BeliefConsistencyResult
    assert get_type_hints(BeliefAssumption)["owner_ids"] == tuple[str, ...]


@pytest.mark.parametrize(
    "fields",
    [
        {"atom": "p(a)", "truth_value": 1, "owner_ids": ("a",)},
        {"atom": "bad(", "truth_value": True, "owner_ids": ("a",)},
        {"atom": "p(a)", "truth_value": True, "owner_ids": ()},
        {"atom": "p(a)", "truth_value": True, "owner_ids": "a"},
        {"atom": "p(a)", "truth_value": True, "owner_ids": ("",)},
        {"atom": "p(a)", "truth_value": True, "owner_ids": ("a", "a")},
    ],
)
def test_invalid_public_assumption_records_are_refused(fields):
    with pytest.raises((InvalidArgumentError, RuleSyntaxError)):
        BeliefAssumption(**fields)


def test_results_refuse_ambiguous_or_partial_owner_attribution():
    positive = BeliefAssumption(atom="p(a)", truth_value=True, owner_ids=("a", "b"))
    partial = BeliefAssumption(atom="p(a)", truth_value=True, owner_ids=("a",))
    negative_same_id = BeliefAssumption(atom="p(a)", truth_value=False, owner_ids=("a",))
    for assumptions, core in (
        ((positive,), (partial,)),
        ((positive, partial), ()),
        ((positive, negative_same_id), ()),
        ((positive,), (positive, positive)),
        (("not a record",), ()),
    ):
        with pytest.raises(InvalidArgumentError):
            BeliefConsistencyResult(status="UNSAT", assumptions=assumptions, core=core)


def test_a_different_atom_is_not_an_equality_alias():
    beliefs = [belief("left", "p(a)"), belief("right", "p(b)", truth=False)]
    assert check_belief_consistency(beliefs).status == "SAT"
    result = check_belief_consistency(beliefs, ["fof(e,axiom,a=b)."])
    assert result.status == "UNSAT"
    # Ownership follows the original signed premise, not an EUF-renamed atom.
    assert {item.atom for item in result.core} == {"p(a)", "p(b)"}
    assert_sound(result, ["fof(e,axiom,a=b)."])


@pytest.mark.parametrize("body", ["$true=$false", "(p(a))=(p(b))", "p($false)", "(p|q)=(p&q)"])
def test_boolean_term_syntax_is_refused_before_solving(monkeypatch, body):
    def unexpected_solver():
        pytest.fail("Unsupported input reached the solver")

    monkeypatch.setattr("endoxa.governance.consistency.Solver", unexpected_solver)
    with pytest.raises(RuleSyntaxError):
        check_belief_consistency([], [f"fof(e,axiom,{body})."])


def test_arbitrary_solver_ast_is_not_a_hard_axiom():
    with pytest.raises(RuleSyntaxError):
        check_belief_consistency([], [Eq(BoolVal(val=True), BoolVal(val=False))])


@pytest.mark.parametrize(("body", "status"), [("$true", "SAT"), ("$false", "UNSAT"), ("$true & ~$false", "SAT")])
def test_boolean_constants_are_valid_formulas(body, status):
    axioms = [f"fof(c,axiom,{body})."]
    result = check_belief_consistency([], axioms)
    assert result.status == status
    assert result.assumptions == result.core == ()
    if status == "UNSAT":
        assert_sound(result, axioms)


def test_individual_function_equality_is_not_predicate_truth_equality():
    axiom = "fof(e,axiom,p(a)!=p(b))."
    expression = parse_premise_fof(axiom)[2]
    equality = expression.args[0]
    assert all(term.sort != BOOL_SORT for term in equality.args)
    # Both predicates can be false while their individual-valued function terms
    # differ. The same spelling does not make their sorts interchangeable.
    result = check_belief_consistency([belief("a", truth=False), belief("b", "p(b)", truth=False)], [axiom])
    assert result.status == "SAT"
    assert result.core == ()


def test_base_contradiction_has_empty_core_even_with_submitted_beliefs():
    axioms = ["fof(no,axiom,$false)."]
    result = check_belief_consistency([belief("unrelated")], axioms)
    assert result.status == "UNSAT"
    assert result.assumptions[0].owner_ids == ("unrelated",)
    assert result.core == ()
    assert_sound(result, axioms)


def test_negative_group_retains_every_owner_and_leaves_input_unchanged():
    beliefs = [belief("z", truth=False), belief("a", truth=False), belief("yes")]
    original = deepcopy(beliefs)
    result = check_belief_consistency(beliefs)
    assert result.status == "UNSAT"
    assert next(item for item in result.core if not item.truth_value).owner_ids == ("a", "z")
    assert beliefs == original
    assert_sound(result)
