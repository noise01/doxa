"""Public result records refuse misleading verdicts and invalid owner attribution."""

from dataclasses import FrozenInstanceError

import pytest

from endoxa.errors import InvalidArgumentError, RuleSyntaxError
from endoxa.governance import Assumption, ConsistencyResult, EntailmentResult, PremiseSet, Rule, check_entailment

_POSITIVE = Assumption(atom="p(a)", truth_value=True, owner_ids=("positive",))
_NEGATIVE = Assumption(atom="p(a)", truth_value=False, owner_ids=("negative",))


@pytest.mark.parametrize(
    ("premises", "query", "verdict"),
    [
        ("SAT", "UNSAT", "ENTAILED"),
        ("SAT", "SAT", "NOT_ENTAILED"),
        ("SAT", "UNKNOWN", "UNKNOWN"),
        ("UNSAT", None, "INCONSISTENT_PREMISES"),
        ("UNKNOWN", None, "UNKNOWN"),
    ],
)
def test_result_preserves_consistency_guard_and_inconclusive_checks(premises, query, verdict):
    result = EntailmentResult(premises, query)
    assert result.verdict == verdict
    assert result.premises_status == premises
    assert result.query_status == query


@pytest.mark.parametrize(
    ("premises", "query"),
    [("SAT", None), ("UNSAT", "SAT"), ("UNKNOWN", "UNSAT"), ("invalid", None), ("SAT", "invalid")],
)
def test_result_cannot_claim_a_query_ran_without_consistent_premises(premises, query):
    with pytest.raises(InvalidArgumentError):
        EntailmentResult(premises, query)


@pytest.mark.parametrize(
    ("truth", "owners"),
    [(1, ("owner",)), (True, ()), (True, "owner"), (True, ("owner", "owner")), (True, ("",))],
)
def test_assumption_requires_boolean_sign_and_distinct_explicit_owners(truth, owners):
    with pytest.raises(InvalidArgumentError):
        Assumption(atom="p(a)", truth_value=truth, owner_ids=owners)


@pytest.mark.parametrize(
    ("status", "assumptions", "core"),
    [
        ("invalid", (), ()),
        ("SAT", "not records", ()),
        ("SAT", ("not a record",), ()),
        ("SAT", (_POSITIVE, _POSITIVE), ()),
        ("SAT", (_POSITIVE, Assumption(atom="q(a)", truth_value=True, owner_ids=("positive",))), ()),
        ("UNSAT", (_POSITIVE,), (_NEGATIVE,)),
        ("SAT", (_POSITIVE,), (_POSITIVE,)),
        ("UNKNOWN", (_POSITIVE,), (_POSITIVE,)),
    ],
)
def test_consistency_result_cannot_invent_owners_or_attach_unsat_core_to_sat(status, assumptions, core):
    with pytest.raises(InvalidArgumentError):
        ConsistencyResult(status=status, assumptions=assumptions, core=core)


def test_result_copies_input_collections_and_keeps_empty_hard_axiom_core_valid():
    assumptions = [_POSITIVE, _NEGATIVE]
    result = ConsistencyResult(status="UNSAT", assumptions=assumptions, core=[])
    assumptions.clear()
    assert result.assumptions == (_NEGATIVE, _POSITIVE)
    assert result.core == ()
    with pytest.raises(FrozenInstanceError):
        result.status = "SAT"


@pytest.mark.parametrize("formula", [None, "fof(query,conjecture,p(a))."])
def test_rule_requires_a_premise_statement_instead_of_a_query(formula):
    with pytest.raises(RuleSyntaxError):
        Rule(id="rule", formula=formula, confidence=0.8)


def test_entailment_requires_a_query_statement_instead_of_a_premise():
    with pytest.raises(RuleSyntaxError):
        check_entailment(PremiseSet(), "fof(premise,axiom,p(a)).")
