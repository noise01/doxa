"""The current view as a derivation of the ledger.

**The current view is derived from the ledger.** Fold the operation series and
what comes out is what the agent holds -- including the beliefs it holds *without
deciding between them*.

``UNRESOLVED`` is the point of the exercise. Being unable to settle a
contradiction is a real state, and a system can speak about it by asking, but it
usually has no name in the state itself: a held tie is indistinguishable from two
ordinary beliefs that happen to conflict. Here it is a value of
:attr:`BeliefState.status`, and both sides carry it.

**Releasing a hold is derived, never asserted.** A hold is not a lock. It is the
name of "the preference cannot separate these two", so it ends when the
preference *can* -- when a later operation moves one side out of the other's
band. :attr:`BeliefState.released_by` reads back which operation did it.

**Only ``ground`` confers 1.0.** That makes a grounded answer the one operation
which always separates a band, and therefore the one that directly releases a
hold. Evidence can release a hold too, but only by actually moving a credence --
which is the difference between settling a tie and outranking it.

**On replaying the Laplace fold.** ``confirm`` and ``refute`` carry no
confidence: a booking says only which way the evidence points, and the credence
is computed wherever it was booked. To reconstruct a view that can be *checked*
against the host's own state, this module replays the same arithmetic. That
duplicates a rule the host also holds, and it is deliberate: a view that gave up
on confidence could not tell a correct derivation from one that had lost half its
evidence.

Pure: its own field schemas and metadata, with no storage or I/O.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from endoxa.errors import InvalidArgumentError
from endoxa.governance.ledger import LedgerOp, TargetKind
from endoxa.governance.metadata import Stance
from endoxa.governance.resolution import Belief

BeliefStatus = Literal["HELD", "UNRESOLVED"]

#: A belief the view holds outright.
HELD: BeliefStatus = "HELD"

#: A belief the view holds *without* being able to prefer it or its rival: the
#: first-class form of the unsettleable tie. Both sides of the tie
#: carry it, and neither is withdrawn -- holding both is the calibrated answer,
#: and picking one would be arbitrariness.
UNRESOLVED: BeliefStatus = "UNRESOLVED"

#: Mirrors :mod:`endoxa.governance.revision.preference`: a belief with no explicit confidence is
#: inviolable, revision failing safe toward not touching an unmarked belief.
_DEFAULT_CONFIDENCE = 1.0

#: Mirrors :mod:`endoxa.governance.revision.preference`'s band tolerance. The two derivations of
#: "does the preference separate these?" are kept independent on purpose -- the
#: package may not import a host's own revision code -- and a test pins them against each other,
#: so the day one is changed alone, it shows up as a failure rather than as a
#: silent divergence between what the system does and what its ledger says.
_CONFIDENCE_EPSILON = 1e-9

#: The role a conjecture is written under (``belief_context``), which the
#: revision preference reaches for first.
_HYPOTHESIS = "hypothesis"

#: Defaults for the evidence fold, mirroring ``settings.belief_evidence_*``.
DEFAULT_PRIOR_STRENGTH = 2.0
DEFAULT_CONFIDENCE_CEILING = 0.99


@dataclass(frozen=True, slots=True)
class BeliefState:
    """What the ledger says is currently the case about one target.

    Attributes:
        target: The belief's node id, or the rule's memory id.
        target_kind: Which of those it is.
        truth_value: The claim the target currently makes.
        confidence: The credence, or ``None`` when no operation ever stated one
            and none was derived (an unmarked belief; see ``_DEFAULT_CONFIDENCE``
            for how the preference reads that).
        status: ``HELD`` or ``UNRESOLVED``.
        context: Legacy actor fallback only. Explicit metadata never fills it
            from the writer. In old records this is the role the target was born under (``belief_context`` on the
            beliefs), which is what the revision preference reads to tell a
            conjecture from an assertion.
        held_with: The other side of the tie, while unresolved.
        released_by: The ``origin_event_id`` of the operation that ended the last
            hold, or ``None`` when it was never held or is held still.
        atom: Explicit recorded ground atom, or None when not recorded.
        stance: Explicit recorded standing, or None when not recorded.
        source: Explicit recorded origin kind, or None when not recorded.
        evidence_prior: The credence burned in at the first piece of evidence,
            and the for/against tally since. Kept because the fold
            is path-dependent -- the posterior cannot be recomputed from the
            confidence alone.
        evidence_for: Corroborations folded in so far.
        evidence_against: Counter-evidence folded in so far.
    """

    target: str
    target_kind: TargetKind = "atom"
    truth_value: bool = True
    confidence: float | None = None
    status: BeliefStatus = HELD
    context: str = ""
    held_with: str | None = None
    released_by: str | None = None
    evidence_prior: float | None = None
    evidence_for: int = 0
    evidence_against: int = 0
    atom: str | None = field(default=None, kw_only=True)
    stance: Stance | None = field(default=None, kw_only=True)
    source: str | None = field(default=None, kw_only=True)

    def to_belief(self) -> Belief:
        """Restore a fully recorded explicit belief, never guessing missing metadata.

        Legacy and partial views remain readable but cannot be converted by this
        strict entry point. The host may still use its own legacy adapter.
        """
        if self.target_kind != "atom" or self.atom is None or self.stance is None or self.confidence is None:
            msg = "A recorded atom, stance and confidence are required to restore a belief"
            raise InvalidArgumentError(msg)
        return Belief(
            id=self.target,
            atom=self.atom,
            truth_value=self.truth_value,
            confidence=self.confidence,
            stance=self.stance,
            source=self.source,
        )


@dataclass(frozen=True, slots=True)
class ViewEquivalence:
    """The result of checking a reconstructed view against a host's live state.

    What is wanted is zero disagreement between the view the ledger reconstructs
    and what the host actually holds. Several numbers rather than one, because
    they fail for different reasons and blurring them would
    hide the interesting one.

    ``UNRESOLVED`` has no counterpart here, and that is not an omission: **the
    belief store cannot represent a hold**. Two beliefs the preference could not
    separate sit on it as two ordinary beliefs, which is the gap the derived view
    closes. There is nothing on the other side for the ledger's status to be
    checked against, so it is pinned by a positive control rather than by this
    comparison.

    Attributes:
        compared: Targets checked on both sides.
        truth_breaks: Targets whose truth value disagrees. **This is the
            invariant**: a non-zero count means the derivation misread an
            operation.
        confidence_breaks: Targets whose credence disagrees among those whose
            evidence the ledger could fully account for.
        unattributed: Targets excluded from the credence comparison because the
            two sides' evidence tallies disagree. **Expected to be zero** once the
            write side records every credence move it makes. Two things can still
            put a target here, and they are not
            the same:

            - **A regression in the recording path.** A booking the belief store folded
              and did not record, or recorded and did not fold. Either way the
              write side and the ledger have come apart again.
            - **A restore that brought no tally back.** The ledger keeps a
              belief's whole series, so a belief that returned to the belief store
              without its counts reads as saying less than the audit log can
              account for. Paging carries the tally now, which is what
              made this column an invariant rather than a residual; what remains
              are the restores whose source has no tally to give -- an entry
              persists a proposition, not its evidence. Paging itself
              is still not a ledger operation: the fix was to
              stop the belief store forgetting, not to teach the ledger to forget.

            Note the test is a disagreement, not an inequality: the ledger
            holding *more* than the belief store lands here too, which is what makes
            the second case visible at all.

            **Which target it was is in** ``details``. The count alone cannot
            tell the two cases above apart, and a caller that reads the count
            during a run and then goes looking afterwards will not find the
            answer: the belief store is a working set, so by the time the run
            ends the target has usually paged out and lands in
            ``missing_from_state`` instead.
        missing_from_state: Targets the ledger knows that the belief store no longer
            has -- paged out to LTM or evicted. Excluded from the
            comparison rather than counted as breakage, and reported so the
            exclusion is never invisible.
        details: Human-readable lines for the disagreements, for a failing test
            or a diagnostic run to print. One line per disagreeing target,
            opening with the word for the column it was counted in --
            ``truth ``, ``unattributed `` or ``confidence `` -- so a caller can
            select the column it cares about by prefix. Each line then names the
            target and both sides' values.
    """

    compared: int = 0
    truth_breaks: int = 0
    confidence_breaks: int = 0
    unattributed: int = 0
    missing_from_state: int = 0
    details: tuple[str, ...] = field(default_factory=tuple)


def reconstruct_view(
    ops: Sequence[LedgerOp],
    *,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    ceiling: float = DEFAULT_CONFIDENCE_CEILING,
) -> dict[str, BeliefState]:
    """Fold the ledger into the current view.

    Args:
        ops: The operation series, in order.
        prior_strength: Pseudo-observations backing the evidence prior.
        ceiling: Upper bound the evidence fold may reach, strictly below 1.0.

    Returns:
        The state of every target the series mentions, keyed by target.
    """
    view: dict[str, BeliefState] = {}
    for op in ops:
        first_seen = op.target not in view
        state = view.get(op.target) or BeliefState(
            target=op.target,
            target_kind=op.target_kind,
            context=op.actor if op.atom is None and op.stance is None and op.source is None else "",
        )
        state = _metadata_state(state, op)
        view[op.target] = _apply(
            state,
            op,
            prior_strength=prior_strength,
            ceiling=ceiling,
            first_seen=first_seen,
        )
        if op.op == "hold" and op.partner is not None:
            partner = view.get(op.partner) or BeliefState(target=op.partner)
            view[op.partner] = replace(partner, status=UNRESOLVED, held_with=op.target, released_by=None)
        _release_holds(view, op)
    return view


def _metadata_state(state: BeliefState, op: LedgerOp) -> BeliefState:
    if state.atom is not None and (
        op.target_kind != state.target_kind or (op.atom is not None and op.atom != state.atom)
    ):
        msg = f"Belief ID {op.target!r} was registered with another atom or target kind"
        raise InvalidArgumentError(msg)
    if op.atom is not None and state.target_kind != "atom":
        msg = f"Belief ID {op.target!r} collides with a rule ID"
        raise InvalidArgumentError(msg)
    if state.source is not None and op.source is not None and state.source != op.source:
        msg = f"Recorded source kind changed for {op.target!r}"
        raise InvalidArgumentError(msg)
    return replace(
        state,
        atom=state.atom if op.atom is None else op.atom,
        stance=state.stance if op.stance is None else op.stance,
        source=state.source if op.source is None else op.source,
    )


def _apply(
    state: BeliefState,
    op: LedgerOp,
    *,
    prior_strength: float,
    ceiling: float,
    first_seen: bool,
) -> BeliefState:
    """Apply one operation to one target's state.

    ``first_seen`` says whether the series has mentioned this target before, which
    the evidence re-attribution below needs and the state alone cannot supply: a
    fresh :class:`BeliefState` is indistinguishable from one that has settled on
    the same values.
    """
    if op.op == "hold":
        return replace(state, status=UNRESOLVED, held_with=op.partner, released_by=None)
    if op.op in {"confirm", "refute"}:
        return _fold_evidence(state, supports=op.op == "confirm", prior_strength=prior_strength, ceiling=ceiling)
    updated = replace(
        state,
        truth_value=state.truth_value if op.truth_value is None else op.truth_value,
        confidence=state.confidence if op.confidence is None else op.confidence,
    )
    if op.op == "retract" and op.target_kind == "atom" and op.confidence is None:
        # The flip re-attributes the belief's own evidence to the claim it now
        # makes. The two conditions mirror the belief store's own: it swaps only
        # for an atom, and only when the write stated no confidence -- a writer
        # that states one is declaring a credence for the new claim, and a tally
        # kept for the old one must not overrule it. A retracted *rule* has no
        # tally at all: its retraction is the stated confidence itself.
        return _swap_evidence(updated, prior_strength=prior_strength, ceiling=ceiling)
    if _is_grounded_reversal(state, op, first_seen=first_seen):
        return _swap_evidence(updated, prior_strength=prior_strength, ceiling=ceiling)
    return updated


def _is_grounded_reversal(state: BeliefState, op: LedgerOp, *, first_seen: bool) -> bool:
    """Whether a ``ground`` also reversed a belief the belief store already held.

    An ask-user answer wins the operation whatever else the write does
    (:mod:`~endoxa.governance.derive`), which is right --
    conferring confidence 1.0 is the thing that only this operation does. But the
    write can *also* be a reversal, and then the belief store re-attributes the belief's
    evidence exactly as it does for a revision flip: its test is "the truth value
    changed and no confidence was stated", and it does not ask which operation
    the ledger will call it.

    So this restates the belief store's own test rather than keying off the operation
    name. All three conditions are the belief store's: an existing belief
    (``truth_flipped`` is only set for a node already there), a changed truth
    value, and no stated confidence.

    **While the write side is silent about any of its credence moves this cannot
    be seen**, because ``unattributed`` is then expected to be non-zero for other
    reasons and a target landing there says nothing in particular.
    """
    return (
        op.op == "ground"
        and op.target_kind == "atom"
        and op.confidence is None
        and not first_seen
        and op.truth_value is not None
        and op.truth_value != state.truth_value
    )


def _release_holds(view: dict[str, BeliefState], op: LedgerOp) -> None:
    """End any hold this operation just made settleable.

    A hold is released when the preference can separate the pair again -- when
    the two sides no longer share a band. The releasing operation is recorded so
    the release can be read back with a time and an author, without ever having
    been a first-class operation of its own.
    """
    if op.op == "hold":
        return
    state = view.get(op.target)
    if state is None or state.status != UNRESOLVED or state.held_with is None:
        return
    partner = view.get(state.held_with)
    if partner is None or _same_band(state, partner):
        return
    view[op.target] = replace(state, status=HELD, held_with=None, released_by=op.origin_event_id)
    if partner.held_with == op.target:
        view[state.held_with] = replace(partner, status=HELD, held_with=None, released_by=op.origin_event_id)


def _band_key(state: BeliefState) -> tuple[bool, float]:
    """Where the revision preference ranks this belief.

    The host's derivation of the same judgement is :mod:`endoxa.governance.revision.preference`
    ``band_key``; see ``_CONFIDENCE_EPSILON`` on why there are two.
    """
    confidence = _DEFAULT_CONFIDENCE if state.confidence is None else state.confidence
    hypothesis = state.stance == _HYPOTHESIS if state.stance is not None else state.context == _HYPOTHESIS
    return (not hypothesis, confidence)


def _same_band(left: BeliefState, right: BeliefState) -> bool:
    """Whether the preference ranks two beliefs identically."""
    left_key, right_key = _band_key(left), _band_key(right)
    return left_key[0] == right_key[0] and abs(left_key[1] - right_key[1]) <= _CONFIDENCE_EPSILON


def _posterior(*, prior: float, for_count: int, against_count: int, prior_strength: float, ceiling: float) -> float:
    """Laplace-smoothed credence from a prior mean and a for/against tally."""
    numerator = prior * prior_strength + for_count
    denominator = prior_strength + for_count + against_count
    return min(numerator / denominator, ceiling)


def _fold_evidence(
    state: BeliefState,
    *,
    supports: bool,
    prior_strength: float,
    ceiling: float,
) -> BeliefState:
    """Book one piece of evidence (mirroring ``fold_evidence``).

    An inviolable belief is left alone: it cannot become more certain, and
    running it through the update would only lower it.
    """
    confidence = _DEFAULT_CONFIDENCE if state.confidence is None else state.confidence
    if confidence >= 1.0:
        return state
    prior = state.evidence_prior if state.evidence_prior is not None else confidence
    for_count = state.evidence_for + (1 if supports else 0)
    against_count = state.evidence_against + (0 if supports else 1)
    posterior = _posterior(
        prior=prior,
        for_count=for_count,
        against_count=against_count,
        prior_strength=prior_strength,
        ceiling=ceiling,
    )
    if posterior == confidence and state.evidence_prior is not None:
        return state
    return replace(
        state,
        confidence=posterior,
        evidence_prior=prior,
        evidence_for=for_count,
        evidence_against=against_count,
    )


def _swap_evidence(state: BeliefState, *, prior_strength: float, ceiling: float) -> BeliefState:
    """Hand a flipped belief's evidence to the claim it now makes.

    The counts support *what the target currently claims*, not a fixed
    proposition, so the counter-evidence that motivated the flip reads as one
    count for the new claim and the burned-in prior becomes its complement.
    """
    confidence = _DEFAULT_CONFIDENCE if state.confidence is None else state.confidence
    if confidence >= 1.0:
        return state
    prior = state.evidence_prior if state.evidence_prior is not None else confidence
    swapped_prior = 1.0 - prior
    swapped_for = state.evidence_against + 1
    swapped_against = state.evidence_for
    return replace(
        state,
        confidence=_posterior(
            prior=swapped_prior,
            for_count=swapped_for,
            against_count=swapped_against,
            prior_strength=prior_strength,
            ceiling=ceiling,
        ),
        evidence_prior=swapped_prior,
        evidence_for=swapped_for,
        evidence_against=swapped_against,
    )


def compare_to_state(
    view: Mapping[str, BeliefState],
    beliefs: Mapping[str, Mapping[str, Any]],
) -> ViewEquivalence:
    """Check a reconstructed view against the host's live state (criterion 3).

    Args:
        view: The output of :func:`reconstruct_view`.
        beliefs: The host's belief store's atom nodes, keyed by node id, each a mapping of
            the node attributes (``truth_value``/``confidence``/``evidence_*``).

    Returns:
        The tally of agreements and disagreements. See :class:`ViewEquivalence`
        for why credence is reported apart from truth, and what is excluded.
    """
    compared = truth_breaks = confidence_breaks = 0
    unattributed = missing = 0
    details: list[str] = []
    for target, state in view.items():
        if state.target_kind != "atom":
            continue
        node = beliefs.get(target)
        if node is None:
            missing += 1
            continue
        compared += 1
        held_truth = bool(node.get("truth_value", True))
        if held_truth != state.truth_value:
            truth_breaks += 1
            details.append(f"truth {target}: ledger={state.truth_value} beliefs={held_truth}")
        held_evidence = _held_evidence(node)
        if held_evidence != (state.evidence_for, state.evidence_against):
            unattributed += 1
            details.append(
                f"unattributed {target}: ledger=({state.evidence_for},{state.evidence_against}) "
                f"beliefs=({held_evidence[0]},{held_evidence[1]})"
            )
            continue
        held_confidence = node.get("confidence")
        if not _confidence_agrees(state.confidence, held_confidence):
            confidence_breaks += 1
            details.append(f"confidence {target}: ledger={state.confidence} beliefs={held_confidence}")
    return ViewEquivalence(
        compared=compared,
        truth_breaks=truth_breaks,
        confidence_breaks=confidence_breaks,
        unattributed=unattributed,
        missing_from_state=missing,
        details=tuple(details),
    )


def _held_evidence(node: Mapping[str, Any]) -> tuple[int, int]:
    """Read the belief store's for/against tally for one node."""
    return (int(node.get("evidence_for", 0) or 0), int(node.get("evidence_against", 0) or 0))


def _confidence_agrees(ledger: float | None, beliefs: object) -> bool:
    """Whether the ledger's credence matches the belief store's, both absences included."""
    if ledger is None or beliefs is None:
        return ledger is None and beliefs is None
    if not isinstance(beliefs, (int, float)) or isinstance(beliefs, bool):
        return False
    return abs(float(beliefs) - ledger) <= _CONFIDENCE_EPSILON


__all__ = [
    "HELD",
    "UNRESOLVED",
    "BeliefState",
    "BeliefStatus",
    "ViewEquivalence",
    "compare_to_state",
    "reconstruct_view",
]
