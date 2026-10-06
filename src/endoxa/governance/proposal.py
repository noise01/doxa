"""Snapshot-bound, verified proposals; no application, storage or credence arithmetic."""

from dataclasses import dataclass, replace
from itertools import groupby
from typing import Literal

from endoxa.errors import InvalidArgumentError
from endoxa.governance.checks import check_consistency, validate_limits
from endoxa.governance.premises import Assertion, PremiseSet, RevisionPolicy, Rule, Target, target_of
from endoxa.governance.results import ConsistencyResult

RevisionDecision = Literal["unchanged", "proposed", "deferred"]
RevisionReason = Literal[
    "already_consistent",
    "candidate_consistent",
    "candidate_rejected",
    "unique_verified_revision",
    "initial_unknown",
    "fixed_base_unsat",
    "fixed_base_unknown",
    "same_rank_tie",
    "trial_unknown",
    "no_eligible_target",
    "no_verified_single_revision",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class Adopt:
    """Add the captured candidate record to the adopted set."""

    record: Assertion | Rule

    def __post_init__(self) -> None:
        target_of(self.record)


@dataclass(frozen=True, slots=True, kw_only=True)
class Withdraw:
    """Remove only this ID from adoption, retaining its record and original polarity.

    Another owner or rule may still entail the claim. Withdrawal promises neither
    negation nor loss of entailment; rules are removed, not assigned confidence zero.
    """

    target: Target

    def __post_init__(self) -> None:
        if not isinstance(self.target, Target):
            msg = "Withdraw requires a typed target"
            raise InvalidArgumentError(msg)


@dataclass(frozen=True, slots=True, kw_only=True)
class RevisionBinding:
    """Exact immutable inputs, including all policy values and per-check limits.

    Consumers compare their current records, membership, constraints and policy,
    recheck the proposed state, then apply atomically with their own state version.
    This input binding is not a state version or a proof certificate.
    functional_scope captures the candidate-inclusive checking vocabulary,
    separately from the original adopted premises. Every check retains its
    exclusions even when an Assertion or Rule withdraws.
    """

    premises: PremiseSet
    policy: RevisionPolicy
    candidate: Assertion | Rule | None
    max_rounds: int | None
    max_matches: int | None
    functional_scope: frozenset[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class RevisionTrial:
    """Check after omitting one target from the attempted adopted set.

    Omitting the not-yet-adopted candidate means rejection. Its result is the
    original state's verdict, which can still be UNSAT or UNKNOWN.
    """

    omitted: Target
    result: ConsistencyResult


@dataclass(frozen=True, slots=True, kw_only=True)
class RevisionResult:
    """A verified change or an explicit reason to retain/defer the current state."""

    decision: RevisionDecision
    reason: RevisionReason
    binding: RevisionBinding
    original: ConsistencyResult
    initial: ConsistencyResult
    fixed_base: ConsistencyResult | None = None
    trials: tuple[RevisionTrial, ...] = ()
    changes: tuple[Adopt | Withdraw, ...] = ()
    final: ConsistencyResult | None = None


def _with_candidate(premises: PremiseSet, candidate: Assertion | Rule | None) -> PremiseSet:
    if candidate is None:
        return premises
    target_of(candidate)
    return PremiseSet(
        assertions=(*premises.assertions, candidate) if isinstance(candidate, Assertion) else premises.assertions,
        rules=(*premises.rules, candidate) if isinstance(candidate, Rule) else premises.rules,
        hard_axioms=premises.hard_axioms,
        functional_predicates=premises.functional_predicates,
        functional_scope=premises.functional_scope,
    )


def _without(premises: PremiseSet, target: Target) -> PremiseSet:
    return PremiseSet(
        assertions=tuple(record for record in premises.assertions if target_of(record) != target),
        rules=tuple(record for record in premises.rules if target_of(record) != target),
        hard_axioms=premises.hard_axioms,
        functional_predicates=premises.functional_predicates,
        functional_scope=premises.functional_scope,
    )


DEFAULT_POLICY = RevisionPolicy()


def propose_revision(
    premises: PremiseSet,
    policy: RevisionPolicy = DEFAULT_POLICY,
    *,
    candidate: Assertion | Rule | None = None,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> RevisionResult:
    """Search zero or one omission, considering candidate rejection without novelty bias.

    Every trial checks the entire attempted set, never merely the initial core.
    Protected targets are excluded. Lower priority, then lower confidence ranks
    first across both kinds; an exact same-rank tie defers. UNKNOWN in a relevant
    rank blocks choice and descent. Two SAT trials already establish nonuniqueness.
    Exhaustion means no repair in this search scope, not logical irreparability.
    Candidate rejection plus an existing withdrawal is outside the initial scope.
    Limits renew per check and do not impose an aggregate or wall-clock budget.
    Functional exclusion uses the candidate-inclusive ground scope throughout,
    including original and rejection checks; withdrawal never shrinks its clauses.
    """
    validate_limits(max_rounds, max_matches)
    if not isinstance(premises, PremiseSet) or not isinstance(policy, RevisionPolicy):
        msg = "Expected PremiseSet and RevisionPolicy"
        raise InvalidArgumentError(msg)
    attempted = _with_candidate(premises, candidate)
    records: list[Assertion | Rule] = [*attempted.assertions, *attempted.rules]
    targets = {target_of(record) for record in records}
    if not (policy.protected | set(policy.priorities)) <= targets:
        msg = "Policy references a target outside the submitted state and candidate"
        raise InvalidArgumentError(msg)
    binding = RevisionBinding(
        premises=premises,
        policy=policy,
        candidate=candidate,
        max_rounds=max_rounds,
        max_matches=max_matches,
        functional_scope=attempted.functional_scope,
    )

    def check(state: PremiseSet) -> ConsistencyResult:
        return check_consistency(state, max_rounds=max_rounds, max_matches=max_matches)

    original = check(replace(premises, functional_scope=binding.functional_scope))
    initial = original if candidate is None else check(attempted)

    def result(
        decision: RevisionDecision,
        reason: RevisionReason,
        changes: tuple[Adopt | Withdraw, ...] = (),
        final: ConsistencyResult | None = None,
    ) -> RevisionResult:
        return RevisionResult(
            decision=decision,
            reason=reason,
            binding=binding,
            original=original,
            initial=initial,
            changes=changes,
            final=final,
        )

    if initial.status == "SAT":
        if candidate is None:
            return result("unchanged", "already_consistent", final=initial)
        return result("proposed", "candidate_consistent", (Adopt(record=candidate),), initial)
    if initial.status == "UNKNOWN":
        return result("deferred", "initial_unknown")
    fixed = check(
        PremiseSet(
            hard_axioms=premises.hard_axioms,
            functional_predicates=premises.functional_predicates,
            functional_scope=binding.functional_scope,
        )
    )
    if fixed.status != "SAT":
        return RevisionResult(
            decision="deferred",
            reason="fixed_base_unsat" if fixed.status == "UNSAT" else "fixed_base_unknown",
            binding=binding,
            original=original,
            initial=initial,
            fixed_base=fixed,
        )
    return _search(binding, original, initial, fixed, attempted)


def _search(
    binding: RevisionBinding,
    original: ConsistencyResult,
    initial: ConsistencyResult,
    fixed: ConsistencyResult,
    attempted: PremiseSet,
) -> RevisionResult:
    policy, candidate = binding.policy, binding.candidate
    records: list[Assertion | Rule] = [*attempted.assertions, *attempted.rules]
    eligible = [record for record in records if target_of(record) not in policy.protected]
    trials: list[RevisionTrial] = []

    def result(
        decision: RevisionDecision,
        reason: RevisionReason,
        changes: tuple[Adopt | Withdraw, ...] = (),
        final: ConsistencyResult | None = None,
    ) -> RevisionResult:
        return RevisionResult(
            decision=decision,
            reason=reason,
            binding=binding,
            original=original,
            initial=initial,
            fixed_base=fixed,
            trials=tuple(trials),
            changes=changes,
            final=final,
        )

    if not eligible:
        return result("deferred", "no_eligible_target")

    def rank(record: Assertion | Rule) -> tuple[int, float]:
        return policy.priorities.get(target_of(record), 0), record.confidence

    # Sorting only enumerates a rank; all trials in it are compared before selection.
    for _, band in groupby(sorted(eligible, key=rank), key=rank):
        band_trials = []
        for record in band:
            target = target_of(record)
            verdict = (
                original
                if record == candidate
                else check_consistency(
                    _without(attempted, target), max_rounds=binding.max_rounds, max_matches=binding.max_matches
                )
            )
            trial = RevisionTrial(omitted=target, result=verdict)
            trials.append(trial)
            band_trials.append(trial)
        verified = [trial for trial in band_trials if trial.result.status == "SAT"]
        deferred = _rank_deferral(band_trials)
        if deferred is not None:
            return result("deferred", deferred)
        if verified:
            chosen = verified[0]
            if candidate is not None and chosen.omitted == target_of(candidate):
                return result("unchanged", "candidate_rejected", final=chosen.result)
            changes: tuple[Adopt | Withdraw, ...] = (Withdraw(target=chosen.omitted),)
            if candidate is not None:
                changes = (*changes, Adopt(record=candidate))
            return result("proposed", "unique_verified_revision", changes, chosen.result)
    return result("deferred", "no_verified_single_revision")


def _rank_deferral(trials: list[RevisionTrial]) -> RevisionReason | None:
    if sum(trial.result.status == "SAT" for trial in trials) > 1:
        return "same_rank_tie"
    if any(trial.result.status == "UNKNOWN" for trial in trials):
        return "trial_unknown"
    return None


__all__ = [
    "Adopt",
    "RevisionBinding",
    "RevisionDecision",
    "RevisionReason",
    "RevisionResult",
    "RevisionTrial",
    "Withdraw",
    "propose_revision",
]
