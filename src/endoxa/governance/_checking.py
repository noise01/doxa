"""Shared expression checking without adoption or historical policy."""

from collections.abc import Sequence

from endoxa.governance.formulas import _validate_formula
from endoxa.governance.results import EntailmentResult
from endoxa.solver import Expr, Not, Solver


def check_entailment(
    premises: Sequence[Expr],
    conclusion: Expr,
    *,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> EntailmentResult:
    """Check ordinary entailment after certifying the premises as SAT.

    The conclusion is not removed from premises. UNSAT or UNKNOWN premises
    stop the query, so inconsistency cannot be reported as independent support.
    Both limits are renewed for each of the two solver checks, not cumulative.

    Inputs must be Boolean formulas in propositional logic or uninterpreted
    first-order logic with equality. Bool symbols are propositional constants;
    first-order variables must be bound by quantifiers over uninterpreted sorts.
    Quantified solving is incomplete and may return UNKNOWN. Arithmetic and
    integer-sorted terms are not supported, nor are bare patterns or free
    first-order variables. Invalid formulas raise an EndoxaError, not UNKNOWN.
    """
    for formula in (*premises, conclusion):
        _validate_formula(formula)
    solver = Solver()
    for formula in premises:
        solver.add(formula)
    status = solver.check(max_rounds=max_rounds, max_matches=max_matches)
    if status != "SAT":
        return EntailmentResult(status, None)
    # A fresh check avoids carrying a previous query's assumptions or state.
    query = Solver()
    for formula in premises:
        query.add(formula)
    query_status = query.check(Not(conclusion), max_rounds=max_rounds, max_matches=max_matches)
    return EntailmentResult(status, query_status)
