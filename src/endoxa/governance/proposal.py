"""Snapshot-bound, verified proposals; no application, storage or credence arithmetic."""

from dataclasses import dataclass, replace
from typing import Literal

from endoxa.errors import InvalidArgumentError
from endoxa.governance._revision_search import ordered_omissions
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
    "no_verified_revision",
    "check_budget_exhausted",
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
    """Exact immutable inputs, including policy, withdrawal scope and both budgets.

    Consumers compare their current records, membership, constraints and policy,
    recheck the proposed state, then apply atomically with their own state version.
    This input binding is not a state version or a proof certificate.
    functional_scope captures the candidate-inclusive checking vocabulary,
    separately from the original adopted premises. Every check retains its
    exclusions even when an Assertion or Rule withdraws.
    max_withdrawals bounds existing-target sets; max_checks caps all consistency
    calls for this proposal. Neither bound certifies unlimited search optimality.
    """

    premises: PremiseSet
    policy: RevisionPolicy
    candidate: Assertion | Rule | None
    max_rounds: int | None
    max_matches: int | None
    functional_scope: frozenset[str]
    max_withdrawals: int = 1
    max_checks: int = 256


@dataclass(frozen=True, slots=True, kw_only=True)
class RevisionTrial:
    """Check after omitting a nonempty set of targets from the attempted set.

    Omitting the not-yet-adopted candidate means rejection. Its result is the
    original state's verdict, which can still be UNSAT or UNKNOWN.
    Candidate rejection never shares a trial with existing-target withdrawals.
    """

    omitted: tuple[Target, ...]
    result: ConsistencyResult

    def __post_init__(self) -> None:
        if (
            not isinstance(self.omitted, (tuple, list))
            or not self.omitted
            or any(not isinstance(target, Target) for target in self.omitted)
            or len(set(self.omitted)) != len(self.omitted)
        ):
            msg = "RevisionTrial omitted requires nonempty distinct typed targets"
            raise InvalidArgumentError(msg)
        object.__setattr__(self, "omitted", tuple(sorted(self.omitted, key=lambda target: (target.kind, target.id))))


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
    checks_used: int = 0


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


def _without(premises: PremiseSet, targets: tuple[Target, ...]) -> PremiseSet:
    omitted = frozenset(targets)
    return PremiseSet(
        assertions=tuple(record for record in premises.assertions if target_of(record) not in omitted),
        rules=tuple(record for record in premises.rules if target_of(record) not in omitted),
        hard_axioms=premises.hard_axioms,
        functional_predicates=premises.functional_predicates,
        functional_scope=premises.functional_scope,
    )


DEFAULT_POLICY = RevisionPolicy()


@dataclass(slots=True)
class _Checks:
    binding: RevisionBinding
    used: int = 0

    def check(self, premises: PremiseSet) -> ConsistencyResult | None:
        if self.used >= self.binding.max_checks:
            return None
        self.used += 1
        return check_consistency(premises, max_rounds=self.binding.max_rounds, max_matches=self.binding.max_matches)


def _validate_search_limits(max_withdrawals: int, max_checks: int) -> None:
    for name, value, minimum in (("max_withdrawals", max_withdrawals, 1), ("max_checks", max_checks, 2)):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            msg = f"{name} must be an integer at least {minimum}"
            raise InvalidArgumentError(msg)


def propose_revision(  # noqa: PLR0913 - independent solver, scope and total-check limits are public controls
    premises: PremiseSet,
    policy: RevisionPolicy = DEFAULT_POLICY,
    *,
    candidate: Assertion | Rule | None = None,
    max_rounds: int | None = None,
    max_matches: int | None = None,
    max_withdrawals: int = 1,
    max_checks: int = 256,
) -> RevisionResult:
    """Verify a unique best revision within the configured withdrawal scope.

    Every trial checks the entire attempted set, never merely the initial core.
    Protected targets are excluded. Minimize withdrawal counts from the highest
    numeric priority layer down; only equal count vectors compare descending
    confidences within those layers. An exact same-rank tie defers. A relevant
    UNKNOWN or exhausted check budget blocks selection and descent.
    Exhaustion means no repair in this search scope, not logical irreparability.
    Candidate rejection is a separate single omission and never combines with
    existing withdrawals. max_checks counts all consistency calls, including
    original, attempted and fixed-base checks. Reused verdicts cost no new check.
    max_withdrawals must be at least one and max_checks at least two, reserving
    the original and attempted diagnostics without inventing unchecked verdicts.
    It is not a wall-clock bound; max_rounds/max_matches still renew per check.
    Functional exclusion uses the candidate-inclusive ground scope throughout,
    including original and rejection checks; withdrawal never shrinks its clauses.
    """
    validate_limits(max_rounds, max_matches)
    _validate_search_limits(max_withdrawals, max_checks)
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
        max_withdrawals=max_withdrawals,
        max_checks=max_checks,
    )
    # The minimum total budget reserves both mandatory initial diagnostics.
    original = check_consistency(
        replace(premises, functional_scope=binding.functional_scope), max_rounds=max_rounds, max_matches=max_matches
    )
    initial = (
        original if candidate is None else check_consistency(attempted, max_rounds=max_rounds, max_matches=max_matches)
    )
    checks = _Checks(binding, used=1 if candidate is None else 2)

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
            checks_used=checks.used,
        )

    if initial.status == "SAT":
        if candidate is None:
            return result("unchanged", "already_consistent", final=initial)
        return result("proposed", "candidate_consistent", (Adopt(record=candidate),), initial)
    if initial.status == "UNKNOWN":
        return result("deferred", "initial_unknown")
    fixed = checks.check(
        PremiseSet(
            hard_axioms=premises.hard_axioms,
            functional_predicates=premises.functional_predicates,
            functional_scope=binding.functional_scope,
        )
    )
    if fixed is None:
        return result("deferred", "check_budget_exhausted")
    if fixed.status != "SAT":
        return RevisionResult(
            decision="deferred",
            reason="fixed_base_unsat" if fixed.status == "UNSAT" else "fixed_base_unknown",
            binding=binding,
            original=original,
            initial=initial,
            fixed_base=fixed,
            checks_used=checks.used,
        )
    return _search(checks, original, initial, fixed, attempted)


def _search(
    checks: _Checks,
    original: ConsistencyResult,
    initial: ConsistencyResult,
    fixed: ConsistencyResult,
    attempted: PremiseSet,
) -> RevisionResult:
    binding = checks.binding
    policy, candidate = binding.policy, binding.candidate
    records: tuple[Assertion | Rule, ...] = (*binding.premises.assertions, *binding.premises.rules)
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
            checks_used=checks.used,
        )

    attempted_records: tuple[Assertion | Rule, ...] = (*attempted.assertions, *attempted.rules)
    if all(target_of(record) in policy.protected for record in attempted_records):
        return result("deferred", "no_eligible_target")

    chosen: RevisionTrial | None = None
    chosen_rank = None
    for rank, omitted in ordered_omissions(records, policy, candidate, binding.max_withdrawals):
        if chosen is not None and rank != chosen_rank:
            break
        verdict = (
            original
            if candidate is not None and omitted == (target_of(candidate),)
            else checks.check(_without(attempted, omitted))
        )
        if verdict is None:
            return result("deferred", "check_budget_exhausted")
        trial = RevisionTrial(omitted=omitted, result=verdict)
        trials.append(trial)
        if verdict.status == "UNKNOWN":
            return result("deferred", "trial_unknown")
        if verdict.status == "SAT":
            if chosen is not None:
                return result("deferred", "same_rank_tie")
            chosen, chosen_rank = trial, rank
    if chosen is None:
        reason: RevisionReason = (
            "no_verified_single_revision" if binding.max_withdrawals == 1 else "no_verified_revision"
        )
        return result("deferred", reason)
    decision, reason, changes = _selected_changes(chosen, candidate)
    return result(decision, reason, changes, chosen.result)


def _selected_changes(
    chosen: RevisionTrial, candidate: Assertion | Rule | None
) -> tuple[RevisionDecision, RevisionReason, tuple[Adopt | Withdraw, ...]]:
    if candidate is not None and chosen.omitted == (target_of(candidate),):
        return "unchanged", "candidate_rejected", ()
    changes: tuple[Adopt | Withdraw, ...] = tuple(Withdraw(target=target) for target in chosen.omitted)
    if candidate is not None:
        changes = (*changes, Adopt(record=candidate))
    return "proposed", "unique_verified_revision", changes


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
