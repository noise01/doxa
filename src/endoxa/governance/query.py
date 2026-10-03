"""Consistency-guarded entailment and independent belief support.

These queries do not revise beliefs or apply ledger operations. Unlike the
legacy revision ``entails`` query, they first require consistent premises.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from endoxa.errors import InvalidArgumentError
from endoxa.governance.formulas import _validate_formula
from endoxa.governance.metadata import canonical_atom
from endoxa.governance.resolution import Belief
from endoxa.governance.revision.facts import parse_fact_to_expr
from endoxa.solver import Expr, Not, Solver

SolverStatus = Literal["SAT", "UNSAT", "UNKNOWN"]
EntailmentVerdict = Literal["ENTAILED", "NOT_ENTAILED", "INCONSISTENT_PREMISES", "UNKNOWN"]

_STATUSES = frozenset({"SAT", "UNSAT", "UNKNOWN"})


@dataclass(frozen=True, slots=True)
class EntailmentResult:
    """Two solver verdicts, with a consistency-guarded interpretation.

    ``query_status`` checks premises together with the negated conclusion. It
    is absent exactly when the premise check did not return SAT. Invalid state
    combinations are refused rather than producing misleading conclusions.
    """

    premises_status: SolverStatus
    query_status: SolverStatus | None

    def __post_init__(self) -> None:
        if self.premises_status not in _STATUSES or (
            self.query_status is not None and self.query_status not in _STATUSES
        ):
            msg = "EntailmentResult requires SAT, UNSAT or UNKNOWN solver statuses"
            raise InvalidArgumentError(msg)
        if (self.premises_status == "SAT") != (self.query_status is not None):
            msg = "A query status is required exactly when premises are SAT"
            raise InvalidArgumentError(msg)

    @property
    def verdict(self) -> EntailmentVerdict:
        """Distinguish entailment, a countermodel, inconsistent premises and UNKNOWN."""
        if self.premises_status == "UNSAT":
            return "INCONSISTENT_PREMISES"
        if self.premises_status == "UNKNOWN" or self.query_status == "UNKNOWN":
            return "UNKNOWN"
        return "ENTAILED" if self.query_status == "UNSAT" else "NOT_ENTAILED"


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


def check_belief_support(  # noqa: PLR0913 - keep the query polarity and both per-check limits explicit
    beliefs: Sequence[Belief],
    rule_exprs: Sequence[Expr],
    target_id: str,
    *,
    truth_value: bool = True,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> EntailmentResult:
    """Check support after excluding all beliefs with the target's atom.

    Belief.atom is used when explicit; otherwise the legacy target is the atom
    text. Flat ground atoms use lower-case predicates and constant arguments.
    Arbitrary IDs require an explicit atom; nested terms and general formula
    beliefs are not accepted. Whitespace variants denote the same atom, even with different
    IDs or truth values. All such beliefs are excluded, in either polarity.

    The named target must exist. Its stored truth value does not choose the
    query: truth_value=True checks the positive atom, False its negation.
    Duplicate IDs or missing targets raise InvalidArgumentError; malformed
    atoms raise RuleSyntaxError. Nothing is silently skipped. Remaining beliefs
    and all supplied rules go through check_entailment's consistency guard.
    """
    if not isinstance(target_id, str):
        msg = "target_id must be a string"
        raise InvalidArgumentError(msg)
    if not isinstance(truth_value, bool):
        msg = "truth_value must be a bool"
        raise InvalidArgumentError(msg)
    atoms: dict[str, Expr] = {}
    for belief in beliefs:
        if not isinstance(belief, Belief) or not isinstance(belief.target, str):
            msg = "beliefs must contain Belief objects with string targets"
            raise InvalidArgumentError(msg)
        if belief.target in atoms:
            msg = f"Duplicate belief ID: {belief.target!r}"
            raise InvalidArgumentError(msg)
        if not isinstance(belief.truth_value, bool):
            msg = f"Belief truth_value must be a bool: {belief.target!r}"
            raise InvalidArgumentError(msg)
        atom = canonical_atom(belief.target if belief.atom is None else belief.atom)
        atoms[belief.target] = parse_fact_to_expr(atom)
    if target_id not in atoms:
        msg = f"Target belief ID not found: {target_id!r}"
        raise InvalidArgumentError(msg)
    target = atoms[target_id]
    remaining = [
        atoms[belief.target] if belief.truth_value else Not(atoms[belief.target])
        for belief in beliefs
        if str(atoms[belief.target]) != str(target)
    ]
    conclusion = target if truth_value else Not(target)
    return check_entailment([*rule_exprs, *remaining], conclusion, max_rounds=max_rounds, max_matches=max_matches)


__all__ = ["EntailmentResult", "EntailmentVerdict", "SolverStatus", "check_belief_support", "check_entailment"]
