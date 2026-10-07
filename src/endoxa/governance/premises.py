"""Immutable checking inputs; membership and confidence updates belong to callers."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from endoxa.errors import InvalidArgumentError
from endoxa.governance._validation import canonical_atom, validate_confidence, validate_id
from endoxa.governance.formulas import parse_premise_fof


@dataclass(frozen=True, slots=True, kw_only=True)
class Assertion:
    """One individually adoptable signed atom; a different claim needs another ID."""

    id: str
    atom: str
    truth_value: bool
    confidence: float
    source: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_confidence(self.confidence)
        if not isinstance(self.truth_value, bool):
            msg = "Assertion truth_value must be a bool"
            raise InvalidArgumentError(msg)
        if self.source is not None:
            validate_id(self.source)
        object.__setattr__(self, "atom", canonical_atom(self.atom))


@dataclass(frozen=True, slots=True, kw_only=True)
class Rule:
    """One individually adoptable closed FOF rule, without an intrinsic priority."""

    id: str
    formula: str
    confidence: float

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_confidence(self.confidence)
        parse_premise_fof(self.formula)


@dataclass(frozen=True, slots=True, kw_only=True)
class Target:
    """An ID qualified by record kind; identical IDs across kinds stay distinct."""

    kind: Literal["assertion", "rule"]
    id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in {"assertion", "rule"}:
            msg = "Target kind must be assertion or rule"
            raise InvalidArgumentError(msg)
        validate_id(self.id)


def target_of(record: Assertion | Rule) -> Target:
    """Refer to one typed input record."""
    if not isinstance(record, (Assertion, Rule)):
        msg = "Expected an Assertion or Rule"
        raise InvalidArgumentError(msg)
    return Target(kind="assertion" if isinstance(record, Assertion) else "rule", id=record.id)


@dataclass(frozen=True, slots=True, kw_only=True)
class PremiseSet:
    """The complete adopted input, including fixed axioms and functional exclusion.

    Functional predicates exclude simultaneous positive ground values with the
    same leading arguments and different final arguments (arity at least two).
    Recency is not inferred; callers express any supersession preference in policy.
    functional_scope retains ground atoms used to generate those exclusions even
    after an owner withdraws. It contains the submitted assertion atoms by default;
    callers must preserve it when changing adoption within the same checking scope.
    Scope atoms are vocabulary, not additional assertions or quantified functionality.
    """

    assertions: tuple[Assertion, ...] = ()
    rules: tuple[Rule, ...] = ()
    hard_axioms: tuple[str, ...] = ()
    functional_predicates: frozenset[str] = frozenset()
    functional_scope: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for name, values, kind in (("assertions", self.assertions, Assertion), ("rules", self.rules, Rule)):
            if not isinstance(values, (tuple, list)) or any(not isinstance(value, kind) for value in values):
                msg = f"{name} requires typed records"
                raise InvalidArgumentError(msg)
            if len({value.id for value in values}) != len(values):
                msg = f"Duplicate IDs in {name}"
                raise InvalidArgumentError(msg)
            object.__setattr__(self, name, tuple(sorted(values, key=lambda value: value.id)))
        if not isinstance(self.hard_axioms, (tuple, list)):
            msg = "hard_axioms requires a sequence of FOF strings"
            raise InvalidArgumentError(msg)
        for text in self.hard_axioms:
            parse_premise_fof(text)
        object.__setattr__(self, "hard_axioms", tuple(sorted(self.hard_axioms)))
        if not isinstance(self.functional_predicates, (set, frozenset, tuple, list)):
            msg = "functional_predicates requires a collection of predicate names"
            raise InvalidArgumentError(msg)
        for predicate in self.functional_predicates:
            if canonical_atom(predicate) != predicate or "(" in predicate:
                msg = "Expected a canonical predicate name"
                raise InvalidArgumentError(msg)
        object.__setattr__(self, "functional_predicates", frozenset(self.functional_predicates))
        if not isinstance(self.functional_scope, (set, frozenset, tuple, list)):
            msg = "functional_scope requires a collection of ground atoms"
            raise InvalidArgumentError(msg)
        scope = frozenset(canonical_atom(atom) for atom in self.functional_scope)
        scope |= frozenset(assertion.atom for assertion in self.assertions)
        object.__setattr__(self, "functional_scope", scope)


@dataclass(frozen=True, slots=True, kw_only=True)
class RevisionPolicy:
    """Protected targets cannot withdraw; lower integer priority withdraws first.

    Missing priorities are zero. For sets, minimize withdrawal counts from the
    largest priority down before comparing descending confidence vectors within
    those same layers. Smaller vectors win, equally for assertions and rules.
    Equal ranks defer; IDs never break ties. Confidence 1.0 is eligible unless
    explicitly protected.
    """

    protected: frozenset[Target] = frozenset()
    priorities: Mapping[Target, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.protected, (set, frozenset, tuple, list)) or any(
            not isinstance(target, Target) for target in self.protected
        ):
            msg = "protected requires typed targets"
            raise InvalidArgumentError(msg)
        if not isinstance(self.priorities, Mapping) or any(
            not isinstance(target, Target) or not isinstance(rank, int) or isinstance(rank, bool)
            for target, rank in self.priorities.items()
        ):
            msg = "priorities requires typed targets and integer ranks"
            raise InvalidArgumentError(msg)
        object.__setattr__(self, "protected", frozenset(self.protected))
        object.__setattr__(self, "priorities", MappingProxyType(dict(self.priorities)))


__all__ = ["Assertion", "PremiseSet", "RevisionPolicy", "Rule", "Target", "target_of"]
