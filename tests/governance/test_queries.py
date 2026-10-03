"""Independent support is not self-support or entailment from contradiction."""

from typing import get_type_hints

import pytest

from endoxa.errors import InvalidArgumentError, RuleSyntaxError, SortMismatchError
from endoxa.governance import Belief, EntailmentResult, check_belief_support, check_entailment
from endoxa.governance.revision import check_atom_support, parse_fact_to_expr
from endoxa.solver import (
    BOOL_SORT,
    INT_SORT,
    Bool,
    BoundVar,
    Eq,
    ForAll,
    Function,
    Int,
    MultiPattern,
    Not,
    Solver,
    USort,
    Var,
    parse_fof,
)


def _belief(target, *, truth=True):
    return Belief(truth_value=truth, confidence=0.7, id=target or "empty-atom", atom=target, stance="asserted")


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
def test_result_interpretation(premises, query, verdict):
    assert EntailmentResult(premises, query).verdict == verdict


@pytest.mark.parametrize(
    ("premises", "query"),
    [("SAT", None), ("UNSAT", "SAT"), ("UNKNOWN", "UNKNOWN"), ("bad", None), ("SAT", "bad")],
)
def test_impossible_result_states_are_refused(premises, query):
    with pytest.raises(InvalidArgumentError):
        EntailmentResult(premises, query)


def test_ordinary_entailment_keeps_the_conclusion_and_does_not_mutate():
    p = Bool("p")
    premises = [p]
    result = check_entailment(premises, p)
    assert result == EntailmentResult("SAT", "UNSAT")
    assert premises == [p]


def test_countermodel_is_distinct_from_false_premises():
    assert check_entailment([], Bool("p")) == EntailmentResult("SAT", "SAT")
    p = Bool("p")
    assert check_entailment([p, Not(p)], Bool("q")) == EntailmentResult("UNSAT", None)


@pytest.mark.parametrize("status", ["UNSAT", "UNKNOWN"])
def test_non_sat_premises_stop_without_a_query(monkeypatch, status):
    calls = []

    def check(_solver, *args: object, **kwargs: object):
        calls.append((args, kwargs))
        return status

    monkeypatch.setattr(Solver, "check", check)
    assert check_entailment([], Bool("q")) == EntailmentResult(status, None)
    assert len(calls) == 1


def test_limits_are_forwarded_and_renewed_for_both_checks(monkeypatch):
    calls = []
    statuses = iter(["SAT", "UNKNOWN"])

    def check(_solver, *args: object, **kwargs: object):
        calls.append((_solver, args, kwargs))
        return next(statuses)

    monkeypatch.setattr(Solver, "check", check)
    result = check_entailment([], Bool("q"), max_rounds=2, max_matches=3)
    assert result == EntailmentResult("SAT", "UNKNOWN")
    assert len(calls) == 2
    assert calls[0][0] is not calls[1][0]
    assert all(call[2] == {"max_rounds": 2, "max_matches": 3} for call in calls)
    assert calls[0][1] == ()
    assert len(calls[1][1]) == 1


@pytest.mark.parametrize("limits", [{"max_rounds": 1}, {"max_matches": 1}])
def test_real_quantifier_budget_cut_is_not_a_certificate(limits):
    rule = parse_fof("fof(loop, axiom, ![X]: (p(X) => p(f(X)))).")[2]
    fact = parse_fact_to_expr("p(a)")
    assert check_entailment([rule, fact], Bool("q"), **limits) == EntailmentResult("UNKNOWN", None)


def test_ground_euf_and_quantified_rule_inputs():
    p = parse_fof("fof(p, axiom, p(a)).")[2]
    q = parse_fof("fof(q, axiom, q(a)).")[2]
    rule = parse_fof("fof(r, axiom, ![X]: (p(X) => q(X))).")[2]
    assert check_entailment([p, rule], q).verdict == "ENTAILED"
    equality = parse_fof("fof(e, axiom, a = b).")[2]
    consequence = parse_fof("fof(e, conjecture, f(a) = f(b)).")[2]
    assert check_entailment([equality], consequence).verdict == "ENTAILED"


def test_support_excludes_self_but_can_find_an_independent_rule():
    target = _belief("mortal(socrates)")
    assert check_belief_support([target], [], target.id).verdict == "NOT_ENTAILED"
    rule = parse_fof("fof(m, axiom, ![X]: (human(X) => mortal(X))).")[2]
    beliefs = [target, _belief("human(socrates)")]
    assert check_belief_support(beliefs, [rule], target.id).verdict == "ENTAILED"
    assert beliefs == [target, _belief("human(socrates)")]


def test_alias_ids_and_both_polarities_cannot_supply_self_support():
    beliefs = [_belief("p(a)"), _belief("p( a )", truth=False), _belief(" p(a) ")]
    assert check_belief_support(beliefs, [], "p(a)") == EntailmentResult("SAT", "SAT")
    assert check_belief_support(beliefs, [], "p( a )", truth_value=False) == EntailmentResult("SAT", "SAT")


def test_negative_support_is_explicit_and_not_chosen_by_stored_truth():
    beliefs = [_belief("p(a)", truth=False), _belief("q(a)")]
    rule = parse_fof("fof(r, axiom, ![X]: (q(X) => ~p(X))).")[2]
    assert check_belief_support(beliefs, [rule], "p(a)", truth_value=False).verdict == "ENTAILED"
    assert check_belief_support(beliefs, [rule], "p(a)").verdict == "NOT_ENTAILED"


def test_inconsistent_remaining_premises_do_not_support_the_target():
    beliefs = [_belief("q"), _belief("p"), _belief(" p ", truth=False)]
    assert check_belief_support(beliefs, [], "q") == EntailmentResult("UNSAT", None)
    data = {belief.id: belief.to_record() for belief in beliefs}
    assert check_atom_support(data, [], "q") == EntailmentResult("UNSAT", None)


def test_atom_support_for_an_unheld_target_and_no_self_proof():
    assert check_atom_support({"id": {"atom": "p", "truth_value": True}}, [], "p").verdict == "NOT_ENTAILED"
    assert check_atom_support({}, [], "q") == EntailmentResult("SAT", "SAT")
    assert check_entailment([parse_fact_to_expr("p")], parse_fact_to_expr("p")).verdict == "ENTAILED"


@pytest.mark.parametrize(
    ("beliefs", "target", "message"),
    [([_belief("p"), _belief("p", truth=False)], "p", "Duplicate"), ([_belief("p")], "q", "not found")],
)
def test_duplicate_and_missing_ids_are_refused(beliefs, target, message):
    with pytest.raises(InvalidArgumentError, match=message):
        check_belief_support(beliefs, [], target)


@pytest.mark.parametrize("text", ["", "id-17", "bad atom", "p(X)", "p(f(a))", "p(a,,b)", "p()", "~p", "a = b"])
def test_bad_beliefs_are_never_silently_skipped(text):
    with pytest.raises(RuleSyntaxError):
        check_belief_support([_belief("p"), _belief(text)], [], "p")


@pytest.mark.parametrize("truth", [0, "true", None])
def test_non_boolean_truth_is_refused(truth):
    with pytest.raises(InvalidArgumentError):
        check_belief_support([_belief("p")], [], "p", truth_value=truth)
    with pytest.raises(InvalidArgumentError):
        check_belief_support([_belief("p", truth=truth)], [], "p")


def test_wrong_belief_type_is_refused():
    with pytest.raises(InvalidArgumentError):
        check_belief_support(["p"], [], "p")


def test_free_first_order_variables_are_refused():
    u = USort("U")
    pred = Function("p", u, BOOL_SORT)
    for term in [BoundVar("X", u), Var("X", u)]:
        with pytest.raises(InvalidArgumentError, match="Free"):
            check_entailment([], pred(term))
    # The parser's unquantified upper-case term is also a free variable.
    with pytest.raises(InvalidArgumentError, match="Free"):
        check_entailment([], parse_fof("fof(q, conjecture, p(X)).")[2])


def test_integer_terms_and_non_boolean_formulas_are_refused():
    for formula in [Int("x"), Eq(Int("x"), Int("y"))]:
        with pytest.raises(SortMismatchError):
            check_entailment([], formula)
        with pytest.raises(SortMismatchError):
            check_entailment([formula], Bool("p"))
    with pytest.raises(InvalidArgumentError):
        check_entailment([], "p")


def test_patterns_are_only_valid_inside_quantifiers_and_cannot_hide_free_variables():
    u = USort("U")
    x, y = BoundVar("X", u), BoundVar("Y", u)
    pred = Function("p", u, BOOL_SORT)
    with pytest.raises(InvalidArgumentError, match="Unsupported"):
        check_entailment([], MultiPattern(pred(x)))
    with pytest.raises(InvalidArgumentError, match="Free"):
        check_entailment([], ForAll([x], pred(x), patterns=[MultiPattern(pred(y))]))
    with pytest.raises(InvalidArgumentError, match="patterns"):
        check_entailment([], ForAll([x], pred(x), patterns=[Bool("trigger")]))
    formula = ForAll([x], pred(x), patterns=[MultiPattern(pred(x))])
    assert check_entailment([], formula, max_rounds=1).verdict in {"NOT_ENTAILED", "UNKNOWN"}


def test_bad_quantifier_binders_and_bodies_are_refused():
    with pytest.raises(InvalidArgumentError):
        check_entailment([], ForAll([Bool("x")], Bool("p")))
    with pytest.raises(InvalidArgumentError):
        check_entailment([], ForAll([BoundVar("X", INT_SORT)], Bool("p")))
    with pytest.raises(SortMismatchError):
        check_entailment([], ForAll([BoundVar("X", USort("U"))], Int("x")))


def test_public_annotations_are_resolvable():
    assert get_type_hints(check_belief_support)["return"] is EntailmentResult
    assert get_type_hints(check_entailment)["return"] is EntailmentResult


def test_support_forwards_both_limits(monkeypatch):
    calls = []

    def check(_solver, *_args: object, **kwargs: object):
        calls.append(kwargs)
        return "UNKNOWN"

    monkeypatch.setattr(Solver, "check", check)
    assert check_belief_support([_belief("p")], [], "p", max_rounds=2, max_matches=3).verdict == "UNKNOWN"
    assert calls == [{"max_rounds": 2, "max_matches": 3}]


def test_non_string_target_id_is_refused():
    with pytest.raises(InvalidArgumentError, match="target_id"):
        check_belief_support([_belief("p")], [], [])


def test_atom_query_can_name_an_unheld_atom_and_excludes_all_polarities():
    data = {
        "observation:1": {"atom": "p( a )", "truth_value": True},
        "observation:2": {"atom": " p(a) ", "truth_value": False},
        "observation:3": {"atom": "q(a)", "truth_value": True},
    }
    assert check_atom_support(data, [], "p(a)").verdict == "NOT_ENTAILED"
    rule = parse_fof("fof(r, axiom, ![X]: (q(X) => p(X))).")[2]
    assert check_atom_support(data, [rule], "p(a)").verdict == "ENTAILED"
    # The query accepts atom text rather than resolving a held target ID.
    assert check_atom_support({}, [], "unheld(a)").verdict == "NOT_ENTAILED"
    with pytest.raises(InvalidArgumentError, match="not found"):
        check_belief_support([], [], "unheld:id")


@pytest.mark.parametrize("status", ["UNSAT", "UNKNOWN"])
def test_atom_query_stops_at_non_sat_premises_and_forwards_both_limits(monkeypatch, status):
    calls = []

    def check(_solver, *assumptions: object, **limits: object):
        calls.append((assumptions, limits))
        return status

    monkeypatch.setattr(Solver, "check", check)
    result = check_atom_support({}, [], "unheld", max_rounds=3, max_matches=5)
    assert result == EntailmentResult(status, None)
    assert calls == [((), {"max_rounds": 3, "max_matches": 5})]


@pytest.mark.parametrize("truth", [None, 1, "false"])
def test_atom_query_refuses_non_boolean_observations(truth):
    with pytest.raises(InvalidArgumentError):
        check_atom_support({"observation": {"atom": "p", "truth_value": truth}}, [], "q")
