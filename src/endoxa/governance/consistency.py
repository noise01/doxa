"""Read-only consistency and signed assumption ownership for explicit beliefs."""

from collections.abc import Sequence
from dataclasses import dataclass

from endoxa.errors import InvalidArgumentError
from endoxa.governance.formulas import parse_premise_fof
from endoxa.governance.metadata import Belief, canonical_atom, validate_id
from endoxa.governance.query import SolverStatus
from endoxa.governance.revision.facts import parse_fact_to_expr
from endoxa.solver import Not, Solver


@dataclass(frozen=True, slots=True, kw_only=True)
class BeliefAssumption:
    """A signed canonical atom and all submitted IDs supplying that premise.

    Ownership is attribution, not an individual culpability or withdrawal verdict.
    Owner IDs are nonempty, unique and sorted; confidence is never aggregated.
    """

    atom: str
    truth_value: bool
    owner_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "atom", canonical_atom(self.atom))
        if not isinstance(self.truth_value, bool):
            msg = "Assumption truth_value must be a bool"
            raise InvalidArgumentError(msg)
        if not isinstance(self.owner_ids, (tuple, list)) or not self.owner_ids:
            msg = "Assumption owner_ids must be a nonempty sequence"
            raise InvalidArgumentError(msg)
        for owner in self.owner_ids:
            validate_id(owner)
        if len(set(self.owner_ids)) != len(self.owner_ids):
            msg = "Assumption owner IDs must be unique"
            raise InvalidArgumentError(msg)
        object.__setattr__(self, "owner_ids", tuple(sorted(self.owner_ids)))


def _ordered(items: tuple[BeliefAssumption, ...]) -> tuple[BeliefAssumption, ...]:
    if not isinstance(items, (tuple, list)) or any(not isinstance(item, BeliefAssumption) for item in items):
        msg = "Expected a sequence of BeliefAssumption records"
        raise InvalidArgumentError(msg)
    if len({(item.atom, item.truth_value) for item in items}) != len(items):
        msg = "Signed assumptions must be unique"
        raise InvalidArgumentError(msg)
    return tuple(sorted(items, key=lambda item: (item.atom, item.truth_value)))


@dataclass(frozen=True, slots=True, kw_only=True)
class BeliefConsistencyResult:
    """A solver status, complete ownership and an assumption core.

    For UNSAT, the core together with the fixed hard axioms is inconsistent.
    A core need not be minimal or unique. An empty UNSAT core can mean the hard
    axioms conflict without beliefs. SAT and UNKNOWN have no core. The result
    covers only submitted beliefs, not retained claims the host left inactive.
    """

    status: SolverStatus
    assumptions: tuple[BeliefAssumption, ...]
    core: tuple[BeliefAssumption, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status not in {"SAT", "UNSAT", "UNKNOWN"}:
            msg = "Expected SAT, UNSAT or UNKNOWN"
            raise InvalidArgumentError(msg)
        assumptions = _ordered(self.assumptions)
        core = _ordered(self.core)
        owners = [owner for item in assumptions for owner in item.owner_ids]
        if len(set(owners)) != len(owners):
            msg = "Belief IDs must be unique across assumptions"
            raise InvalidArgumentError(msg)
        if not set(core) <= set(assumptions) or (self.status != "UNSAT" and core):
            msg = "Core must be an assumption subset and only accompanies UNSAT"
            raise InvalidArgumentError(msg)
        object.__setattr__(self, "assumptions", assumptions)
        object.__setattr__(self, "core", core)


def check_belief_consistency(
    beliefs: Sequence[Belief],
    hard_axioms: Sequence[str] = (),
    *,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> BeliefConsistencyResult:
    """Check submitted beliefs without selecting owners or applying operations.

    Distinct IDs may supply the same atom in either polarity. Duplicate IDs
    remain errors, even for identical records. Hard axioms are closed premise
    FOF accepted by parse_premise_fof and remain fixed throughout the check.
    They are strings, not arbitrary solver expressions. FOF equality compares
    individual terms; Boolean-valued term equality and Boolean arguments are
    outside this parser's grammar. Boolean constants remain valid formulas.
    Stance, confidence and source are not preferences in this read-only check.
    The host owns active membership, provenance, storage and later decisions.

    Limits are nonnegative integers or None, excluding bool. They bound each
    check's quantifier instantiation, not total wall-clock time. Invalid inputs
    raise errors rather than UNKNOWN. Output order is normalized; the solver's
    choice of a sound core is not promised to be unique.
    Verdicts inherit the solver's E-matching limitations, not a completeness
    guarantee for quantified first-order logic.
    """
    for name, limit in (("max_rounds", max_rounds), ("max_matches", max_matches)):
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 0):
            msg = f"{name} must be a nonnegative integer or None"
            raise InvalidArgumentError(msg)
    for name, values in (("beliefs", beliefs), ("hard_axioms", hard_axioms)):
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            msg = f"{name} must be a sequence"
            raise InvalidArgumentError(msg)
    groups: dict[tuple[str, bool], list[str]] = {}
    ids: set[str] = set()
    for belief in beliefs:
        if not isinstance(belief, Belief):
            msg = "beliefs must contain Belief records"
            raise InvalidArgumentError(msg)
        if belief.id in ids:
            msg = f"Duplicate belief ID: {belief.id!r}"
            raise InvalidArgumentError(msg)
        ids.add(belief.id)
        groups.setdefault((belief.atom, belief.truth_value), []).append(belief.id)
    # Parse every axiom before solving, including when another axiom is UNSAT.
    axioms = [parse_premise_fof(text)[2] for text in hard_axioms]
    assumptions = tuple(
        BeliefAssumption(atom=atom, truth_value=truth, owner_ids=tuple(owners))
        for (atom, truth), owners in sorted(groups.items())
    )
    expressions = {}
    for assumption in assumptions:
        atom = parse_fact_to_expr(assumption.atom)
        expressions[atom if assumption.truth_value else Not(atom)] = assumption
    solver = Solver()
    for axiom in sorted(axioms, key=str):
        solver.add(axiom)
    status = solver.check(*expressions, max_rounds=max_rounds, max_matches=max_matches)
    core = tuple(expressions[expr] for expr in solver.unsat_core()) if status == "UNSAT" else ()
    return BeliefConsistencyResult(status=status, assumptions=assumptions, core=core)


__all__ = ["BeliefAssumption", "BeliefConsistencyResult", "check_belief_consistency"]
