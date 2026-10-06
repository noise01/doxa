"""Immutable results for adopted-premise checks and revision diagnostics."""

from dataclasses import dataclass
from typing import Literal

from endoxa.errors import InvalidArgumentError
from endoxa.governance._validation import canonical_atom, validate_id

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


@dataclass(frozen=True, slots=True, kw_only=True)
class Assumption:
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


def _ordered(items: tuple[Assumption, ...]) -> tuple[Assumption, ...]:
    if not isinstance(items, (tuple, list)) or any(not isinstance(item, Assumption) for item in items):
        msg = "Expected a sequence of Assumption records"
        raise InvalidArgumentError(msg)
    if len({(item.atom, item.truth_value) for item in items}) != len(items):
        msg = "Signed assumptions must be unique"
        raise InvalidArgumentError(msg)
    return tuple(sorted(items, key=lambda item: (item.atom, item.truth_value)))


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsistencyResult:
    """A solver status, complete ownership and an assumption core.

    For UNSAT, the core together with the fixed hard axioms is inconsistent.
    A core need not be minimal or unique. An empty UNSAT core can mean the hard
    axioms conflict without beliefs. SAT and UNKNOWN have no core. The result
    covers only submitted beliefs, not retained claims the host left inactive.
    """

    status: SolverStatus
    assumptions: tuple[Assumption, ...]
    core: tuple[Assumption, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status not in {"SAT", "UNSAT", "UNKNOWN"}:
            msg = "Expected SAT, UNSAT or UNKNOWN"
            raise InvalidArgumentError(msg)
        assumptions = _ordered(self.assumptions)
        core = _ordered(self.core)
        owners = [owner for item in assumptions for owner in item.owner_ids]
        if len(set(owners)) != len(owners):
            msg = "Assertion IDs must be unique across assumptions"
            raise InvalidArgumentError(msg)
        if not set(core) <= set(assumptions) or (self.status != "UNSAT" and core):
            msg = "Core must be an assumption subset and only accompanies UNSAT"
            raise InvalidArgumentError(msg)
        object.__setattr__(self, "assumptions", assumptions)
        object.__setattr__(self, "core", core)
