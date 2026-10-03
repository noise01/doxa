"""An optional read-only adapter for a legacy audit-row dialect.

This is not a general event bus or a requirement for ledger use. New callers can
construct :class:`~endoxa.governance.ledger.LedgerOp` directly and fold their own
ordered operation sequence with :func:`~endoxa.governance.view.reconstruct_view`.

``derive_ledger`` accepts mappings with ``id``, ``timestamp``, ``event_type`` and
``payload`` (a mapping or JSON text). The constants below identify the supported
event names; handlers define their payload shapes. Other event types are ignored.
Rows are ordered by timestamp and event ID, preserving the adapter's existing
conversion behavior. No event classes or storage dependencies are imported.

:class:`DerivedLedger` reports rows read, unreadable rows and a horizon: the
earliest row seen, not a guarantee that a retained log contains the entire
history. Callers remain responsible for retention and for validating their row
dialect against this adapter before relying on its output.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from endoxa.governance.ledger import EVIDENCE_REASONS, EvidenceReason, LedgerOp, OpKind, SupportRef

#: Supported event names in the legacy audit-row dialect.
ATOM_ADDED = "AtomAddedEvent"
BELIEF_EVIDENCE_BOOKED = "BeliefEvidenceBookedEvent"
BELIEF_EVIDENCE_RECORDED = "BeliefEvidenceRecordedEvent"
BELIEF_SUPPORT_RECORDED = "BeliefSupportRecordedEvent"
CONTRADICTION_TIE_DETECTED = "ContradictionTieDetectedEvent"
MEMORY_BATCH_GET_RESPONSE = "MemoryBatchGetResponseEvent"
MEMORY_BATCH_UPDATE_REQUEST = "MemoryBatchUpdateRequestEvent"

#: The event types a ledger derivation reads. Handed to the store's type-filtered
#: read so a diagnostic run does not drag the whole audit log into memory.
#:
#: ``BeliefSupportRecordedEvent`` is the odd one: it yields **no operation at
#: all**. A derivation reaching a belief already in the belief store changes
#: no claim and no credence, so it is read for the support state it
#: carries and for nothing else -- the first row type here that is state without
#: being an operation.
#:
#: ``BeliefEvidenceBookedEvent`` is the write side breaking its own silence. It
#: maps onto exactly the same operations as ``BeliefEvidenceRecordedEvent``; the
#: two are separate classes only because the belief store subscribes to the
#: latter, so re-using it would fold the evidence a second time. The distinction
#: is a host wiring detail, and the derivation is deliberately blind to it.
LEDGER_EVENT_TYPES: frozenset[str] = frozenset(
    {
        ATOM_ADDED,
        BELIEF_EVIDENCE_BOOKED,
        BELIEF_EVIDENCE_RECORDED,
        BELIEF_SUPPORT_RECORDED,
        CONTRADICTION_TIE_DETECTED,
        MEMORY_BATCH_GET_RESPONSE,
        MEMORY_BATCH_UPDATE_REQUEST,
    },
)

#: Property name the belief store writes its support record under, and the keys of one
#: record (a host's own support record). String constants for the
#: same reason the event names are: this package cannot import a host.
SUPPORTED_BY_KEY = "supported_by"
_SUPPORT_KIND_KEY = "kind"
_SUPPORT_REF_KEY = "ref"

#: Correlation id a host stamps on its axiom batch-get, pinned by the same
#: host-side test as the event names. The response to *this* request is the moment
#: a rule store's content enters the ledger as beliefs: the file or table is host
#: initialisation data, and its content becomes governance.
AXIOM_LOAD_CORRELATION_ID = "reasoning_axiom_load"

#: Memory type of a learned or base rule row.
_AXIOM_MEMORY_TYPE = "axiom"

#: Default for the confidence below which a defeasible rule stops constraining.
#: A host that sets its own passes it in rather than this importing it, so the
#: package carries no configuration dependency.
DEFAULT_RULE_ACTIVE_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class DerivedLedger:
    """The operation series recovered from a run's audit log, and what it cost.

    Attributes:
        ops: The operations in the order they happened.
        horizon: Epoch seconds of the earliest row read, or ``None`` when no row
            carried a readable timestamp. Operations before it are unrecoverable
            (see the module docstring on retention).
        rows_read: How many rows the derivation was handed.
        rows_unreadable: Rows whose payload could not be parsed as an object.
            Counted rather than dropped silently: a reader that quietly skipped
            them would be reporting a series it cannot vouch for.
    """

    ops: tuple[LedgerOp, ...]
    horizon: float | None
    rows_read: int
    rows_unreadable: int


def derive_ledger(
    rows: Sequence[Mapping[str, Any]],
    *,
    rule_active_threshold: float = DEFAULT_RULE_ACTIVE_THRESHOLD,
) -> DerivedLedger:
    """Derive the ledger's operation series from persisted event rows.

    Args:
        rows: Raw ``event_store`` rows (``id``/``timestamp``/``event_type``/
            ``payload``) in any order; they are sorted here.
        rule_active_threshold: Confidence at or above which a defeasible rule
            still constrains. An axiom update below it is a ``retract``.

    Returns:
        The derived series together with what it could and could not see.
    """
    parsed = [record for record in (_parse(row) for row in rows) if record is not None]
    unreadable = len(rows) - len(parsed)
    parsed.sort(key=lambda record: (record.at if record.at is not None else 0.0, record.event_id))

    ops: list[LedgerOp] = []
    state = _FoldState()
    for record in parsed:
        ops.extend(_operations(record, state, rule_active_threshold=rule_active_threshold))

    stamps = [record.at for record in parsed if record.at is not None]
    return DerivedLedger(
        ops=tuple(ops),
        horizon=min(stamps) if stamps else None,
        rows_read=len(rows),
        rows_unreadable=unreadable,
    )


@dataclass(frozen=True, slots=True)
class _Record:
    """One audit-log row normalized into what the derivation reads."""

    event_id: str
    event_type: str
    at: float | None
    payload: dict[str, Any]


def _parse(row: Mapping[str, Any]) -> _Record | None:
    """Normalize a raw store row, or return ``None`` when its payload is unreadable.

    Two row shapes are accepted, because a store may hand back either: a JSON
    string payload with a ``datetime`` timestamp, or a plain dict payload with an
    epoch float.
    """
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except TypeError, ValueError:
            return None
    if not isinstance(payload, dict):
        return None
    return _Record(
        event_id=str(row.get("id") or payload.get("event_id") or ""),
        event_type=str(row.get("event_type", "")),
        at=_as_epoch(row.get("timestamp", payload.get("timestamp"))),
        payload=payload,
    )


def _as_epoch(value: object) -> float | None:
    """Coerce a row timestamp to epoch seconds, or ``None`` when unreadable."""
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


@dataclass(slots=True)
class _FoldState:
    """What the fold has to remember between rows.

    ``truth`` is the running truth value per belief: the host's ``AtomAddedEvent``
    carries the properties that were *written*, not the resulting node, so whether
    a write flipped a belief is only visible against what the series says it held
    (a host's own atom writer).

    ``supports`` is the same idea for the support seat: a belief's
    footing accumulates across rows (a materialisation writes one, a later
    derivation reaching the same belief adds another), and each operation is
    stamped with the set as it stood *at that moment*. Mutable and threaded rather
    than recomputed, because the series is the only thing that has the order.
    """

    truth: dict[str, bool] = field(default_factory=dict)
    supports: dict[str, tuple[SupportRef, ...]] = field(default_factory=dict)


def _operations(
    record: _Record,
    state: _FoldState,
    *,
    rule_active_threshold: float,
) -> list[LedgerOp]:
    """Map one event row onto the ledger operations it stands for.

    A row may legitimately stand for none: ``BeliefSupportRecordedEvent`` updates
    the running support state and returns nothing, because gaining a second
    footing is not a governance operation on the belief: neither the claim nor the
    credence is touched.
    """
    if record.event_type == ATOM_ADDED:
        return _atom_operations(record, state)
    if record.event_type == BELIEF_SUPPORT_RECORDED:
        _absorb_support(record, state)
        return []
    if record.event_type in (BELIEF_EVIDENCE_RECORDED, BELIEF_EVIDENCE_BOOKED):
        return _evidence_operations(record, state)
    if record.event_type == CONTRADICTION_TIE_DETECTED:
        return _hold_operations(record)
    if record.event_type == MEMORY_BATCH_GET_RESPONSE:
        return _rule_load_operations(record)
    if record.event_type == MEMORY_BATCH_UPDATE_REQUEST:
        return _rule_update_operations(record, rule_active_threshold=rule_active_threshold)
    return []


def _support_refs(records: object) -> tuple[SupportRef, ...]:
    """Read a beliefs support record into typed references, skipping malformed entries.

    Tolerant in the same measure as the belief store's own reader
    (a host's own support record): support is read on paths that also run for
    beliefs that never had any, and an audit log is not a place where raising is
    useful. An unknown ``kind`` is dropped rather than guessed -- the whole point
    of carrying the kind is that it is not inferred.
    """
    if not isinstance(records, list):
        return ()
    refs: list[SupportRef] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        kind = record.get(_SUPPORT_KIND_KEY)
        ref = record.get(_SUPPORT_REF_KEY)
        if kind in ("derivation", "rule") and ref:
            refs.append(SupportRef(kind=kind, ref=str(ref)))
    return tuple(refs)


def _absorb_support(record: _Record, state: _FoldState) -> None:
    """Fold a ``BeliefSupportRecordedEvent`` into the running support state.

    Appended, not replaced, and never duplicated -- mirroring what the belief
    store does when it records a support: a derivation that runs again over the
    same pair is the same footing, not a second one.
    """
    node_id = str(record.payload.get("node_id", ""))
    added = _support_refs([record.payload.get("support")])
    if not node_id or not added:
        return
    current = state.supports.get(node_id, ())
    state.supports[node_id] = current + tuple(ref for ref in added if ref not in current)


def _atom_operations(record: _Record, state: _FoldState) -> list[LedgerOp]:
    """Map an ``AtomAddedEvent`` onto ``assert`` / ``retract`` / ``supersede`` / ``ground``.

    Four cases, in the order they are tested:

    - ``ask_grounding`` -> ``ground``. The ask-user closed loop is the only writer
      of confidence 1.0, so it is its own operation whatever else the
      write does.
    - an unseen belief -> ``assert``. Birth defaults to true, matching what a
      write to the belief store does.
    - a flip -> ``retract`` or ``supersede``. **The discriminator is the one the
      host's own belief store uses**: it re-attributes the belief's evidence to
      the claim the belief now makes exactly when the write carries no explicit
      ``confidence``. A revision flip writes the truth value alone; recency
      supersession restates the confidence to say "the world moved, the belief was
      not miscalibrated". So the presence of that key is not a guessed proxy for
      the distinction -- it *is* the host's own test for it.
    - anything else -> ``assert``, a restatement (the host publishes nothing at
      all for an idempotent re-assertion, so a row here always changed something).

    A written support record **replaces** what the belief is known to rest on,
    because that is what the belief store does: the write overwrites the property,
    so a re-derivation names the antecedent it actually rode on this time.
    Accumulation is the other writer's job (``_absorb_support``).
    """
    payload = record.payload
    node_id = str(payload.get("node_id", ""))
    if not node_id:
        return []
    properties = payload.get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    role = str(payload.get("role", ""))
    stated_truth = properties.get("truth_value")
    stated_truth = None if stated_truth is None else bool(stated_truth)
    confidence = _as_confidence(properties.get("confidence"))
    metadata = (
        {key: properties.get(key) for key in ("atom", "stance", "source")}
        if properties.get("atom") is not None or properties.get("stance") is not None
        else {}
    )
    known = state.truth.get(node_id)
    if SUPPORTED_BY_KEY in properties:
        state.supports[node_id] = _support_refs(properties.get(SUPPORTED_BY_KEY))

    op: OpKind
    if payload.get("ask_grounding"):
        op = "ground"
    elif known is None:
        op = "assert"
        stated_truth = True if stated_truth is None else stated_truth
    elif stated_truth is not None and stated_truth != known:
        op = "supersede" if "confidence" in properties else "retract"
    else:
        op = "assert"

    if stated_truth is not None:
        state.truth[node_id] = stated_truth
    return [
        LedgerOp(
            op=op,
            target=node_id,
            actor=role,
            truth_value=stated_truth,
            confidence=confidence,
            origin_event_id=record.event_id,
            at=record.at,
            supported_by=state.supports.get(node_id, ()),
            atom=metadata.get("atom"),
            stance=metadata.get("stance"),
            source=metadata.get("source"),
        ),
    ]


def _evidence_operations(record: _Record, state: _FoldState) -> list[LedgerOp]:
    """Map an evidence row onto ``confirm`` or ``refute``.

    Both evidence event types land here (see :data:`LEDGER_EVENT_TYPES`): which
    class the host used says only whether the belief store had already folded the
    evidence before publishing, which is not a governance distinction.

    No confidence is carried: the event says only which way the evidence points,
    and the resulting credence is the Laplace fold the view replays.

    This is the operation the support seat was worth filling for. Counter-evidence
    is booked against a derived belief exactly when its footing goes,
    and stamping the entry with what it was resting on at that moment is what lets
    a reader tell "refuted while still supported" from "refuted because the
    support died" -- from the series alone, with no beliefs in hand. The reason
     says the same thing from the other side: the support set is
    the *state* the booking found, the reason is the *event* that caused it, and
    a reader who has to infer one from the other is guessing again.
    """
    node_id = str(record.payload.get("node_id", ""))
    if not node_id:
        return []
    supports = bool(record.payload.get("supports", True))
    return [
        LedgerOp(
            op="confirm" if supports else "refute",
            target=node_id,
            origin_event_id=record.event_id,
            at=record.at,
            supported_by=state.supports.get(node_id, ()),
            reason=_reason(record.payload.get("reason")),
        ),
    ]


def _reason(value: object) -> EvidenceReason | None:
    """Read a booking's reason, or ``None`` when it is absent or unrecognised.

    Dropped rather than guessed, exactly as :func:`_support_refs` drops an
    unknown support ``kind``: the whole value of carrying the word is that it was
    not inferred, so an audit log written by an older host (or by a writer this
    set of names has not caught up with) reads as "no reason stated" instead of as
    a reason invented here.
    """
    if isinstance(value, str) and value in EVIDENCE_REASONS:
        # The membership test *is* the narrowing; a checker cannot see that a
        # frozenset of the Literal's own members proves the Literal.
        return cast("EvidenceReason", value)
    return None


def _hold_operations(record: _Record) -> list[LedgerOp]:
    """Map a ``ContradictionTieDetectedEvent`` onto one ``hold`` over the pair.

    One operation, not two: a tie *is* a pair, and counting it twice would make
    the ledger's own statistics say the system held twice as often as it did. The
    view marks both members from ``partner``.

    What the ledger records is the *detection*, not the host's decision to raise a
    question about it. Being unable to settle is the governance layer's judgement;
    deciding to ask is the host's dialogue policy. The two are kept apart
    deliberately: a ledger should not require its host to have someone to talk to.
    """
    node_a = str(record.payload.get("node_a", ""))
    node_b = str(record.payload.get("node_b", ""))
    if not node_a or not node_b:
        return []
    return [
        LedgerOp(
            op="hold",
            target=node_a,
            partner=node_b,
            origin_event_id=record.event_id,
            at=record.at,
        ),
    ]


def _rule_load_operations(record: _Record) -> list[LedgerOp]:
    """Map the axiom batch-get response onto one ``assert`` per rule.

    A rule store is host initialisation data, and the moment its content is loaded
    is the moment it enters the ledger as beliefs: learned rules are in the
    ledger's primary scope. A base, non-defeasible axiom is asserted and never
    retracted; only a defeasible rule has a retraction path.

    Only the response to Reasoning's own axiom load is read: other batch-gets
    (memory recall, paging) return the same row shape but are not the rule set
    being taken into the ledger.
    """
    if record.payload.get("correlation_id") != AXIOM_LOAD_CORRELATION_ID:
        return []
    results = record.payload.get("results")
    if not isinstance(results, list):
        return []
    ops: list[LedgerOp] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        memory_id = str(result.get("id", ""))
        if not memory_id:
            continue
        ops.append(
            LedgerOp(
                op="assert",
                target=memory_id,
                target_kind="rule",
                actor=str(result.get("source_kind") or _AXIOM_MEMORY_TYPE),
                truth_value=True,
                confidence=_as_confidence(result.get("confidence")),
                origin_event_id=record.event_id,
                at=record.at,
            ),
        )
    return ops


def _rule_update_operations(record: _Record, *, rule_active_threshold: float) -> list[LedgerOp]:
    """Map an axiom confidence update onto ``retract`` (or a restating ``assert``).

    Soft retraction of a learned rule is a confidence driven below the active
    threshold: the row is kept so the rule can be re-learned, which is precisely
    the ledger's own stance -- the entry does not disappear, it stops counting. An
    update that leaves the rule active is a restatement, not a withdrawal.
    """
    if record.payload.get("memory_type") != _AXIOM_MEMORY_TYPE:
        return []
    updates = record.payload.get("updates")
    if not isinstance(updates, list):
        return []
    ops: list[LedgerOp] = []
    for update in updates:
        if not isinstance(update, dict):
            continue
        memory_id = str(update.get("id", ""))
        confidence = _as_confidence(update.get("confidence"))
        if not memory_id or confidence is None:
            continue
        ops.append(
            LedgerOp(
                op="retract" if confidence < rule_active_threshold else "assert",
                target=memory_id,
                target_kind="rule",
                actor=_AXIOM_MEMORY_TYPE,
                truth_value=True,
                confidence=confidence,
                origin_event_id=record.event_id,
                at=record.at,
            ),
        )
    return ops


def _as_confidence(value: object) -> float | None:
    """Read a confidence field, or ``None`` when it is absent or not a number."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


__all__ = [
    "AXIOM_LOAD_CORRELATION_ID",
    "DEFAULT_RULE_ACTIVE_THRESHOLD",
    "LEDGER_EVENT_TYPES",
    "SUPPORTED_BY_KEY",
    "DerivedLedger",
    "derive_ledger",
]
