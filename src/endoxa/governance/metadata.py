"""Explicit atom identity and belief metadata; no host role mappings."""

import math
import re
from collections.abc import Mapping
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
    """Explicit atom when recorded; otherwise the legacy identity-as-expression."""
    atom = data.get("atom")
    return node_id if atom is None else canonical_atom(atom)


def validate_atom_ids(beliefs: Mapping[str, Mapping[str, Any]]) -> None:
    """Refuse ambiguous explicit-atom maps; leave legacy low-level queries alone."""
    if not any(data.get("atom") is not None for data in beliefs.values()):
        return
    owners: dict[str, str] = {}
    for node_id, data in beliefs.items():
        validate_id(node_id)
        atom = canonical_atom(atom_text(node_id, data))
        if atom in owners:
            msg = f"Atom {atom!r} has multiple belief IDs: {owners[atom]!r}, {node_id!r}"
            raise InvalidArgumentError(msg)
        owners[atom] = node_id
