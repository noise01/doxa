"""Shared validation of explicit ground inputs, without historical records."""

import math
import re

from endoxa.errors import InvalidArgumentError, RuleSyntaxError

_NAME = r"[a-z][a-zA-Z0-9_]*"
_FACT = re.compile(rf"\s*{_NAME}(?:\(\s*{_NAME}(?:\s*,\s*{_NAME})*\s*\))?\s*")


def canonical_atom(text: str) -> str:
    """Validate a flat ground atom and normalize whitespace, never an ID."""
    if not isinstance(text, str) or _FACT.fullmatch(text) is None:
        msg = f"Expected a flat ground atom, got {text!r}"
        raise RuleSyntaxError(msg)
    return re.sub(r"\s+", "", text)


def validate_confidence(value: float) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        msg = "Explicit confidence must be a finite number between 0 and 1"
        raise InvalidArgumentError(msg)


def validate_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        msg = "An ID must be a nonempty string"
        raise InvalidArgumentError(msg)
