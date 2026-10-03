"""What the revision preference says about a belief, derived in one place.

Two selectors read the same preference: :mod:`~endoxa.governance.revision.engine`
picks which belief to retract, and :mod:`~endoxa.governance.revision.tie` decides
when no belief can be picked and the user has to be asked instead. They are two
faces of one judgement -- "does the preference separate these beliefs?" -- and
writing the derivation twice would let one of them be fixed alone.

The unit of that judgement is the **band**: beliefs the preference ranks
identically. Being unsettleable is not the solver failing to decide, it is the
*preference* failing to decide -- so it is a property of a band, not of a
confidence value. Confidence 1.0 is then just one band among others, which is
why band equality can replace the older "both inviolable" tie gate, which had
only the 1.0 case to generalise from.

Pure and basis-independent (governance tier): stdlib only.
"""

from collections.abc import Iterator
from typing import Any

from endoxa.errors import InvalidArgumentError
from endoxa.governance.metadata import validate_stance

# Confidence is a float that evidence folding moves by Laplace smoothing, so
# exact equality would let a 1e-16 difference slip a genuine tie through and back
# into arbitrary settlement. The tolerance is far below the 0.01-order spacing of
# real values, so it never merges bands that are meant to be distinct.
#
# Known limitation: banding compares each candidate against its band's
# first member, so equality is not strictly transitive. Values spaced under the
# tolerance apart do not occur at the resolution confidence is actually written at.
_CONFIDENCE_EPSILON = 1e-9

# A belief with no explicit confidence is inviolable: revision fails safe toward
# not touching an unmarked belief.
_DEFAULT_CONFIDENCE = 1.0


def is_hypothesis(data: dict[str, Any]) -> bool:
    """Read explicit stance without interpreting writer roles or source kinds."""
    stance = data.get("stance")
    validate_stance(stance)
    if stance is None:
        msg = "Revision preference requires an explicit stance"
        raise InvalidArgumentError(msg)
    return bool(stance == "hypothesis")


def confidence_of(data: dict[str, Any]) -> float:
    """Read the belief's confidence, defaulting to inviolable when unmarked."""
    return float(data.get("confidence", _DEFAULT_CONFIDENCE))


def band_key(data: dict[str, Any]) -> tuple[bool, float]:
    """Where the revision preference ranks this belief.

    Ordered as the TMS policy reads: hypotheses first (``False`` sorts before
    ``True``), then by confidence ascending. Two beliefs with the same key are
    ones the preference has nothing left to say about.
    """
    return (not is_hypothesis(data), confidence_of(data))


def same_band(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Whether the preference ranks two beliefs identically."""
    left_key, right_key = band_key(left), band_key(right)
    return left_key[0] == right_key[0] and abs(left_key[1] - right_key[1]) <= _CONFIDENCE_EPSILON


def revision_candidates(
    conflict_nodes: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """Return the beliefs in a conflict that may be retracted, in preference order.

    A hypothesis is always a candidate; an asserted belief only below confidence
    1.0, the standing that ask-user grounding confers.

    The order is ``(band, node_id)``. The **node id is what makes the enumeration
    deterministic**: before it, equal-confidence candidates kept the
    order the UNSAT core happened to arrive in, and since Python's sort is stable
    that solver-dependent order decided which belief got retracted. Lexicographic
    order is arbitrary but fixed -- the same discipline, for the same reason, that
    applies to picking which atom a tie question is asked about.
    """
    candidates = [
        (node_id, data)
        for node_id, data in conflict_nodes
        if is_hypothesis(data) or confidence_of(data) < _DEFAULT_CONFIDENCE
    ]
    return sorted(candidates, key=lambda n: (band_key(n[1]), n[0]))


def preference_bands(
    candidates: list[tuple[str, dict[str, Any]]],
) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    """Group candidates ordered by :func:`revision_candidates` into bands.

    Each yielded band is a maximal run the preference ranks identically. Not
    ``itertools.groupby``: band membership is decided against the band's first
    member with a tolerance (see ``_CONFIDENCE_EPSILON``), not by key equality.
    """
    band: list[tuple[str, dict[str, Any]]] = []
    for node_id, data in candidates:
        if band and not same_band(band[0][1], data):
            yield band
            band = []
        band.append((node_id, data))
    if band:
        yield band


def is_unsettleable_pair(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Whether the preference cannot separate two conflicting beliefs.

    This is the tie gate. It subsumes the "both inviolable" test it replaced:
    two beliefs at confidence 1.0 share the band ``(True, 1.0)``, so that case
    falls out as one band among others rather than as its own rule. What it newly
    admits is every *fallible* equal-confidence pair -- and where a source's
    confidence is a constant, that includes every clash between two things the
    same source said.

    Hypotheses are excluded. Checking ``left`` alone is enough: a shared band
    already implies the two agree on being hypotheses. The exclusion is
    deliberate rather than inherited -- A host that writes every conjecture at one
    constant confidence, so admitting them would turn every clash between two of
    the system's own guesses into a question for the user. A conflict between
    conjectures asks for more evidence, not for someone else's attention.
    """
    return same_band(left, right) and not is_hypothesis(left)


__all__ = [
    "band_key",
    "confidence_of",
    "is_hypothesis",
    "is_unsettleable_pair",
    "preference_bands",
    "revision_candidates",
    "same_band",
]
