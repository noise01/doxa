"""The governance ledger's operation schema.

A boundary that does not exist as a structure cannot be exported, so this module
declares the governance layer as an **append-only ledger of operations**. It is a
naming exercise rather than a new design: every operation below already happens
in any system that revises beliefs, and :mod:`~endoxa.governance.derive` recovers
the series from what a host already records.

The seven operations. ``confirm`` and ``refute`` are deliberately *not* folded
into a single "record evidence" operation with a polarity argument, so that a
reader never has to recover the polarity from an argument:

``assert``
    A belief is claimed. Birth confidence is decided by the source.
``retract``
    Revision withdrew it (it was chosen as the culprit). It leaves the current
    view but **not the ledger**; counter-evidence is booked against it.
``supersede``
    The world moved on (recency supersession). The old value was true
    when written -- this is a state change, not a miscalibration.
``confirm`` / ``refute``
    Evidence for / against is booked. Confidence moves; nothing is
    withdrawn.
``hold``
    The tie no revision preference can separate. **Both sides stay in
    the view**; this is the first-class form of ``UNRESOLVED``.
``ground``
    An answer from outside landed. The only operation that confers confidence
    1.0, and therefore the only one that directly releases a ``hold``.

**Append-only applies to the schema itself.** A later increment must be able to
fill in what it needs by *adding* operations and columns, never by changing the
meaning of an existing one. The reserved columns below are that promise made
concrete: named now, left empty on purpose.

Two things have since tested the promise, and they came out differently. A
reserved column was filled -- and the seat had been declared ``tuple[str, ...]``
when what belonged in it was a set of *typed* endpoints, so reserving a seat and
reserving its dimensions turn out to be different acts. Separately, a column was
added that nobody had reserved at all, and it cost nothing, which is the point:
the promise is about adding rather than about a fixed list of seats.

Pure: its own field schemas and metadata, with no storage or I/O.
"""

from dataclasses import dataclass, field
from typing import Literal

from endoxa.errors import InvalidArgumentError
from endoxa.governance.metadata import Stance, canonical_atom, validate_id, validate_source, validate_stance

#: The seven ledger operations. The tuple fixes a stable reading order for
#: reports; membership tests should use it rather than re-listing the names.
LEDGER_OPS: tuple[str, ...] = (
    "assert",
    "retract",
    "supersede",
    "confirm",
    "refute",
    "hold",
    "ground",
)

OpKind = Literal["assert", "retract", "supersede", "confirm", "refute", "hold", "ground"]

#: What a ledger operation is about. ``atom`` is a belief, including a
#: forward-derived consequent that carries a support record; ``rule`` is a learned
#: axiom. Both are in the ledger's primary scope. ``link`` is reserved and never
#: emitted here: a host that keeps its own record of fallible links between
#: predicates owns that ledger, and the two are deliberately not merged.
TargetKind = Literal["atom", "rule", "link"]

#: Why a ``confirm``/``refute`` was booked. The tuple
#: fixes a stable reading order for reports, as ``LEDGER_OPS`` does; membership
#: tests should use it rather than re-listing the names.
#:
#: **These names live here rather than with whoever writes them.** The event names
#: in :mod:`~endoxa.governance.derive` are duplicated and pinned by a host-side test,
#: because this package may not import a host's event definitions -- that
#: duplication is forced. A reason runs the other way: the ledger is what the word
#: is for, and a host may import this package freely. So extend the set at its
#: source rather than copying the strings into the writers.

#: A belief's footing went away and the loss was booked against it.
REASON_SUPPORT_LOST = "support_lost"
#: A write restated a belief already held, corroborating it instead of
#: overwriting it.
REASON_REASSERTION = "reassertion"
#: The belief was suspected in a contradiction and revision kept it.
REASON_REVISION_SURVIVED = "revision_survived"
#: A rule the belief was recorded as resting on was softly retracted.
REASON_RULE_RETRACTED = "rule_retracted"

EVIDENCE_REASONS: tuple[str, ...] = (
    REASON_SUPPORT_LOST,
    REASON_REASSERTION,
    REASON_REVISION_SURVIVED,
    REASON_RULE_RETRACTED,
)

EvidenceReason = Literal["support_lost", "reassertion", "revision_survived", "rule_retracted"]

#: What the far end of a support is: ``derivation`` names an atom's node id,
#: ``rule`` a learned axiom's memory id. Held as a string rather than imported
#: from the host, and pinned against the host's own constants by the same
#: host-side test that pins the event names.
SupportKind = Literal["derivation", "rule"]


@dataclass(frozen=True, slots=True)
class SupportRef:
    """One thing a belief rode on, as the ledger carries it.

    **Why this is not a bare string.** Both endpoints are strings -- a node id and
    a memory id -- so a flat tuple of them would make every reader guess which one
    it was holding, and look up ``ax_1`` as though it were an atom. The rule
    everywhere else here is that an endpoint's kind is carried rather than
    inferred, just as a reader never has to recover a polarity from an argument.
    It would be strange for this to be the one place the kind is dropped.

    Attributes:
        kind: Which sort of thing ``ref`` names.
        ref: The atom's node id, or the rule's memory id.
    """

    kind: SupportKind
    ref: str


@dataclass(frozen=True, slots=True)
class LedgerOp:
    """One entry in the append-only governance ledger.

    Frozen because the ledger is append-only in the strong sense: an entry is
    never edited after the fact, and a correction is a *later* entry. The view
    is derived from the series (:mod:`~endoxa.governance.view`),
    never by rewriting it.

    Attributes:
        op: Which of the seven operations this is.
        target: What it is about -- a belief ID for atom, a rule ID for rule.
            Legacy atom IDs are expression strings; explicit IDs stay opaque.
        target_kind: Which kind of thing ``target`` names.
        actor: The role that performed the write, verbatim from the host
            (``user``/``agent``/``observation``/``hypothesis``/``axiom`` ...).
            Carried rather than interpreted: whether a retraction came from the
            TMS or from a user's own correction is a distinction the ledger
            should let a reader draw, not one it should erase.
        truth_value: The claim's truth value after the operation, when the
            operation states one. ``None`` means "this operation does not move
            it" (evidence bookings and holds).
        confidence: The confidence the operation itself writes, when it writes
            one explicitly. ``None`` means the value is derived rather than
            stated -- e.g. ``confirm``/``refute``, whose effect on confidence is
            the Laplace fold the view replays.
        partner: The other side of a ``hold``. A tie is a *pair*, so a hold names
            both members; ``None`` for every other operation.
        origin_event_id: The host event this operation was derived from, or
            ``None`` when the operation could not be attributed to one (see
            :mod:`~endoxa.governance.derive`).
        at: Wall-clock time of the originating event (epoch seconds), or
            ``None`` when unknown. Ordering is the position in the series, not
            this field.
        reason: Why this evidence was booked, one of :data:`EVIDENCE_REASONS`.
            ``None`` for every operation that is not a ``confirm``/``refute``, and
            for an entry derived from a row whose reason was absent or outside the
            set -- an unrecognised word is dropped rather than guessed, for the
            same reason :class:`SupportRef` carries its ``kind`` instead of
            inferring it.

            **Not a new operation.** ``confirm`` and ``refute`` were deliberately
            not folded into one operation with a polarity argument, so that a
            reader never has to recover the polarity from an argument; adding the
            reason as an *attribute* runs the same way, taking material away from
            the reader's guesswork rather than adding to it. The seven operations
            are unchanged.

            **Not a reserved seat either.** ``supported_by`` was named in advance
            and sat in later; this column was added the moment it was written,
            which is the other half of the same promise -- adding a column is
            allowed, repurposing one is not.
        session_id: **Reserved** -- the provenance seat. Left ``None`` when a
            host's persisted rows carry no session id, since nothing truthful can
            be put here until the write side supplies one.
        supported_by: What the target rested on **at the time of this operation**.
            That is the whole value of the column: "this ``refute`` arrived after
            everything holding the belief up was gone" becomes readable from the
            series alone, without consulting the host's state. Empty for a belief
            no derivation put there -- the large majority of them -- and for every
            operation about a rule.

            This seat was reserved in advance, and the reservation held in the
            sense that mattered: no existing column changed meaning, no reader
            broke, nothing was rewritten. **Its declared type did not hold.** The
            seat was ``tuple[str, ...]`` and what has to sit in it is a set of
            *typed* endpoints (see :class:`SupportRef`), so reserving a seat and
            reserving its dimensions turned out to be different acts.
        atom: Optional explicit ground atom. Record on the initial assertion
            with stance, before appending ID-only governance operations. It is
            stable for that ID; another formula requires another ID.
        stance: Optional explicit standing, independent of actor and source.
            A later explicit write may change it. Omission leaves it untouched.
        source: Optional recorded origin kind, independent of the actor. Once
            recorded, replay refuses a different kind for the same ID. This is
            not a source-ID vocabulary or a storage policy implementation.
        valid_at: **Reserved** -- the temporality seat. A later form may carry
            time as syntax; until then a ledger entry knows when it was *written*
            (``at``), not when its claim holds.
    """

    op: OpKind
    target: str
    target_kind: TargetKind = "atom"
    actor: str = ""
    truth_value: bool | None = None
    confidence: float | None = None
    partner: str | None = None
    origin_event_id: str | None = None
    at: float | None = None
    reason: EvidenceReason | None = None
    # Reserved seats -- see the class docstring. Adding a column is allowed;
    # repurposing one is not. ``supported_by`` is no longer reserved: it has been
    # sat in.
    session_id: str | None = None
    supported_by: tuple[SupportRef, ...] = ()
    valid_at: float | None = None
    atom: str | None = field(default=None, kw_only=True)
    stance: Stance | None = field(default=None, kw_only=True)
    source: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        validate_stance(self.stance)
        validate_source(self.source)
        explicit = self.atom is not None or self.stance is not None or self.source is not None
        if explicit:
            validate_id(self.target)
            if self.target_kind != "atom":
                msg = "Belief metadata is only valid for atom operations"
                raise InvalidArgumentError(msg)
        if self.atom is not None:
            object.__setattr__(self, "atom", canonical_atom(self.atom))
            if self.stance is None:
                msg = "An explicit ledger atom requires an explicit stance"
                raise InvalidArgumentError(msg)


__all__ = [
    "EVIDENCE_REASONS",
    "LEDGER_OPS",
    "REASON_REASSERTION",
    "REASON_REVISION_SURVIVED",
    "REASON_RULE_RETRACTED",
    "REASON_SUPPORT_LOST",
    "EvidenceReason",
    "LedgerOp",
    "OpKind",
    "SupportKind",
    "SupportRef",
    "TargetKind",
]
