# Revision proposals

`propose_revision(premises, policy=RevisionPolicy(), *, candidate=None,
max_rounds=None, max_matches=None, max_withdrawals=1, max_checks=256)` checks
possible changes and returns a `RevisionResult`. It neither mutates the input
nor applies or saves a proposal. A SAT state without a candidate needs no repair;
an attempted SAT state with a candidate proposes `Adopt` directly.

## Candidate and withdrawal scope

A candidate is at most one new `Assertion` or `Rule`, with a new ID within its
kind. Without a candidate, the function searches for a repair. With one, it
considers adopting it while withdrawing existing targets, and ranks standalone
candidate rejection alongside those withdrawals.

`max_withdrawals` is an integer at least one, excluding Boolean values. It bounds
the number of existing targets omitted in a trial, not the number of change
records: two withdrawals plus candidate adoption produces three changes.
The default remains one. Raise the limit explicitly to consider larger sets.
Candidate rejection is always a separate singleton. Rejection plus an existing
repair is excluded, at every limit. A protected candidate cannot be rejected.

Every visited trial checks the complete remaining input, including Rules, fixed
axioms and the full functional scope. It does not restrict possible withdrawals
to owners in the initial diagnostic core. A rejected candidate reuses the original
verdict; it cannot silently certify an originally inconsistent state.

`Adopt(record)` adds the captured candidate record.
`Withdraw(target)` ends adoption of only that typed ID. It does not negate the
claim, reverse its original polarity or set Rule confidence to zero. Other owners
or remaining Rules may still entail a withdrawn claim.

## Explicit protection and set ranking

`RevisionPolicy.protected` contains typed `Target` references that cannot be
omitted. `priorities` maps typed targets to integer withdrawal priorities;
missing priorities are zero. Every referenced target must exist in the submitted
state or candidate. Rules and Assertions use the same ordering.

Larger numeric priorities are more important to retain. Rank omission sets in
two stages:

1. Count omissions at each priority layer, reading from the largest numeric
   priority down. Minimize that count vector lexicographically.
2. Only for equal count vectors, compare each layer's omitted confidences sorted
   descending, in the same layer order. Minimize these vectors lexicographically.

| Comparison | Preferred omission set |
| --- | --- |
| One priority-10 record versus two priority-0 records | The two priority-0 records: count vectors `[1, 0]` versus `[0, 2]`. |
| One record versus two, all priority 0 | The singleton, regardless of confidence: counts `[1]` versus `[2]`. |
| Two records at one layer, confidences `[0.6, 0.5]` versus `[0.9, 0.1]` | `[0.6, 0.5]`; the highest omitted confidence is smaller. No sums are compared. |
| Equal count and confidence vectors | Equal ranks; two verified SAT choices defer without an ID tie-break. |

At `max_withdrawals=1`, this keeps the lower-priority, then lower-confidence
single-target order. Confidence 1.0 alone does not protect a record. Recency,
source, novelty, FOF role and Rule origin do not infer protection or priority.

Sets are enumerated lazily in rank order, without materializing all combinations.
The frontier grows with visited sets; input sorting and constructing ranks still
depend on input size. This is a bounded search, not an unlimited repair algorithm.

## Read the result

| Field | Meaning |
| --- | --- |
| `decision` | `unchanged`, `proposed` or `deferred`. Only `proposed` carries changes. |
| `reason` | Why the state was retained, a proposal selected, or a decision deferred. |
| `binding` | Complete original inputs, policy, candidate, solver limits, withdrawal limit, total-check budget and candidate-inclusive scope. |
| `original` | The pre-candidate state checked with the retained candidate-inclusive scope. |
| `initial` | The attempted state including the candidate; shares `original` without one. |
| `fixed_base` | Optional check of fixed axioms and functional exclusions, without adoptable records. |
| `trials` | Visited `RevisionTrial` records; each `omitted` is a nonempty tuple of distinct typed targets, including a singleton. |
| `changes` | Tuple of `Adopt` and `Withdraw` records, empty for unchanged or deferred results. |
| `final` | Optional checked result for the selected state; do not assume it is present on deferral. |
| `checks_used` | Actual consistency calls charged to this proposal. |

The [candidate workflow](../examples/08_candidate_workflow.py) demonstrates adoption,
rejection, equal-rank deferral and a withdrawal combined with adoption.

## Multiple withdrawals and two different budgets

[Example 07](../examples/07_bounded_revisions.py) has two independent positive/
negative conflicts. No single withdrawal repairs both. At `max_withdrawals=2`
and `max_checks=16`, it selects two weaker records, verifies the whole final input
SAT, and uses seven checks. At `max_checks=2`, it defers without changes instead.
The original four records are unchanged in both cases.

`max_checks` is a finite integer at least two, excluding Boolean values; the default
is 256. It caps all consistency calls made by one proposal: original, attempted
when a candidate exists, fixed base when needed, and trials. Without a candidate,
original and initial share one call. Candidate rejection reuses the original
verdict without another charge. The actual count can be less than the limit.

`max_rounds` and `max_matches` are per-solver-check limits, renewed each time;
they remain nonnegative integers or `None`. The proposal-wide call count is not
a time limit and does not bound the cost of an individual solver check. Supply
per-check limits as well when needed.

A unique verified best set must be established within the configured scope.
An unexamined same-rank competitor after budget exhaustion defers even if a SAT
trial was already found. A relevant UNKNOWN at a better or equal rank also blocks
selection. Inferior ranks need not be checked after a unique best is settled.
All controls are captured in the binding.

## Reasons and limits

| Decision / reason | Interpretation |
| --- | --- |
| `unchanged` / `already_consistent` | The submitted state is SAT and there is no candidate. |
| `proposed` / `candidate_consistent` | The attempted state is SAT; adoption is proposed. |
| `unchanged` / `candidate_rejected` | Standalone rejection uniquely ranks best and retains a verified SAT original state. |
| `proposed` / `unique_verified_revision` | A unique best omission set is verified within the configured scope. |
| `deferred` / `same_rank_tie` | Two best-ranked SAT outcomes are available; no arbitrary choice is made. |
| `deferred` / `initial_unknown`, `fixed_base_unknown` or `trial_unknown` | A necessary solver verdict is inconclusive. This is not rejection or falsity. |
| `deferred` / `check_budget_exhausted` | The total consistency-call allowance ended before a result could be selected. This is separate from solver UNKNOWN. |
| `deferred` / `fixed_base_unsat` | The non-withdrawable fixed theory itself conflicts. |
| `deferred` / `no_eligible_target` | Every attempted adoptable target is protected. |
| `deferred` / `no_verified_single_revision` | No verified choice was found at the default one-withdrawal scope. |
| `deferred` / `no_verified_revision` | No verified choice was found at a larger configured scope. |

Exhausting a withdrawal scope is not a proof that repair is impossible. A unique
best result is optimal only within the chosen scope. Deferred results contain no
changes to apply, including when some trials were SAT. The caller decides whether
to obtain more information, change its policy or request different limits.

[Application, storage and migration](application-and-migration.md) · [Back to README](../README.md)
