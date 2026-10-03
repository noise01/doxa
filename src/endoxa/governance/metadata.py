"""Explicit atom identity and belief metadata; no host role mappings."""

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal

from endoxa.errors import InvalidArgumentError, RuleSyntaxError
from endoxa.governance.provenance import SOURCE_KINDS

Stance = Literal["asserted", "hypothesis"]
_NAME = r"[a-z][a-zA-Z0-9_]*"
_FACT = re.compile(rf"\s*{_NAME}(?:\(\s*{_NAME}(?:\s*,\s*{_NAME})*\s*\))?\s*")


def validate_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        msg = "An ID must be a nonempty string"
        raise InvalidArgumentError(msg)


def canonical_atom(text: str) -> str:
    """Validate a flat ground atom and normalize whitespace, never an ID."""
    if not isinstance(text, str) or _FACT.fullmatch(text) is None:
        msg = f"Expected a flat ground atom, got {text!r}"
        raise RuleSyntaxError(msg)
    return re.sub(r"\s+", "", text)


def validate_stance(value: Stance | None) -> None:
    if value is not None and (not isinstance(value, str) or value not in {"asserted", "hypothesis"}):
        msg = f"Invalid belief stance: {value!r}"
        raise InvalidArgumentError(msg)


def validate_source(value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or value not in SOURCE_KINDS):
        msg = f"Invalid source kind: {value!r}"
        raise InvalidArgumentError(msg)


def validate_confidence(value: float) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        msg = "Explicit confidence must be a finite number between 0 and 1"
        raise InvalidArgumentError(msg)


def atom_text(node_id: str, data: Mapping[str, Any]) -> str:
    """Read a required explicit atom; an ID is never a formula fallback."""
    if "atom" not in data:
        msg = f"Belief {node_id!r} requires an explicit atom"
        raise InvalidArgumentError(msg)
    return canonical_atom(data["atom"])


def validate_atom_ids(beliefs: Mapping[str, Mapping[str, Any]]) -> None:
    """Refuse missing atoms and ambiguous atom ownership in revision maps."""
    owners: dict[str, str] = {}
    for node_id, data in beliefs.items():
        validate_id(node_id)
        atom = canonical_atom(atom_text(node_id, data))
        if atom in owners:
            msg = f"Atom {atom!r} has multiple belief IDs: {owners[atom]!r}, {node_id!r}"
            raise InvalidArgumentError(msg)
        owners[atom] = node_id


@dataclass(frozen=True, slots=True, kw_only=True)
class Belief:
    """An explicitly identified flat ground belief supplied to governance.

    The caller supplies stance independently of source and confidence. IDs are
    opaque; atom whitespace is normalized without changing identity.
    """

    id: str
    atom: str
    truth_value: bool
    confidence: float
    stance: Stance
    source: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_confidence(self.confidence)
        validate_stance(self.stance)
        if self.stance is None:
            msg = "Belief requires an explicit stance"
            raise InvalidArgumentError(msg)
        validate_source(self.source)
        if not isinstance(self.truth_value, bool):
            msg = "Belief truth_value must be a bool"
            raise InvalidArgumentError(msg)
        object.__setattr__(self, "atom", canonical_atom(self.atom))

    def to_record(self) -> dict[str, Any]:
        """Encode the explicit fields as a plain record, including missing source."""
        return asdict(self)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Belief:
        """Restore an explicit field record without guessing absent metadata."""
        try:
            return cls(**dict(record))
        except TypeError as error:
            msg = "Invalid belief field record"
            raise InvalidArgumentError(msg) from error
