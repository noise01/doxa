# endoxa

**Consistency checks, verified revision proposals, and independent measurements.**
Callers own adopted membership, confidence updates, history, storage, and application.

> **Status: pre-alpha.** Version 0.9.0 adds bounded multiple withdrawals and
> a finite proposal-wide check budget, and changes revision trial and binding types.
> This minor release includes breaking changes. Review the
> [0.9.0 migration notes](https://github.com/noise01/endoxa/blob/v0.9.0/CHANGELOG.md#090) before upgrading.
>
> Callers upgrading from 0.7.0 or earlier also need the
> [0.8.0 migration notes](https://github.com/noise01/endoxa/blob/v0.8.0/CHANGELOG.md#080).

## Import boundaries

Use `endoxa.governance` for Assertion-based inputs, result types, checks, and
revision proposals. `Assumption` and `ConsistencyResult` are the actual result
type names; they are not aliases of the former Belief-based records. Their
definitions live in `endoxa.governance.results`, with one recommended import
surface in `endoxa.governance`. `Rule` here always means an adopted FOF premise
record with `id`, `formula`, and `confidence`.

Solver constructors remain in `endoxa.solver`; independent measurements remain
in `endoxa.instruments`. Ledger schemas, event conversion, historical replay and
state comparison belong to callers; the former `governance.legacy` path is removed.
Former modules such as `governance.revision`, `resolution`, `metadata`, `query`,
and `consistency` are removed, without compatibility aliases. Their obsolete
internal truth-flip and rule/link arbitration implementations are also removed.

## Example

```python
from endoxa.governance import Assertion, PremiseSet, propose_revision

premises = PremiseSet(
    assertions=(
        Assertion(id="observation-1", atom="open(door)", truth_value=True, confidence=0.8),
        Assertion(id="observation-2", atom="open(door)", truth_value=False, confidence=0.3),
    )
)
outcome = propose_revision(premises)
assert outcome.decision == "proposed"
assert outcome.changes[0].target.id == "observation-2"
assert outcome.final.status == "SAT"
# Withdraw removes this ID from adoption. Its original negative claim stays negative.
# Nothing has been applied or saved.
```

## Inputs and checking

`Assertion` requires keyword fields `id`, `atom`, `truth_value`, `confidence`,
and optional `source`. Atoms are flat ground predicates; whitespace is normalized.
IDs identify individual records. Multiple IDs may supply the same signed atom;
duplicate IDs within a kind are errors. Changing content or polarity requires a
new ID. A confidence update is a new input snapshot supplied by the caller.
Confidence must be finite in [0, 1], excluding Boolean values. Source is an optional
nonempty string and does not select a policy.

`Rule(id, formula, confidence)` has keyword fields and a closed FOF premise string.
Its ID is independent of an Assertion ID. `PremiseSet` contains `assertions`,
`rules`, `hard_axioms`, `functional_predicates`, and `functional_scope`.

- `check_consistency(premises)` returns `status`, signed `assumptions` with
  `owner_ids`, and an assumption `core`. A core is sound with the fixed theory,
  but need not be minimal, unique, or cover every conflict.
  It is not a removal plan.
  Rules constrain the check; they are not owners in this diagnostic core.
- `check_entailment(premises, conclusion)` accepts a closed FOF conjecture string.
  It first checks premise consistency. Its result distinguishes `ENTAILED`,
  `NOT_ENTAILED`, `INCONSISTENT_PREMISES`, and `UNKNOWN`.
- `check_support(premises, atom, truth_value=True)` removes all assertions of that
  canonical atom in both polarities, retaining rules and other premises. The atom
  need not already be adopted. It uses the same consistency guard.

Functional predicates exclude positive facts with equal leading arguments and
different final values, at arity two or greater, over ground atoms in
`functional_scope`. The scope defaults to the submitted Assertion atoms and can
include explicit additional ground atoms. It supplies exclusions, not assertions.
Preserve it when changing adoption within the same checking scope, for example
with `dataclasses.replace`: a withdrawn value may still be derived by a Rule.
Proposals expand this scope with a candidate Assertion's atom and keep it fixed
for every check, including the original state and candidate rejection. The binding
captures the original input separately from this candidate-inclusive scope.
Consumers must validate and retain `binding.functional_scope` when rechecking and
applying the result. Rule-only values outside this explicit ground scope do not
automatically extend it.
Unary predicates do not imply that different subjects exclude one another.
This is ground exclusion, not a complete quantified functionality axiom or equality
reasoner. For a newer value superseding an older one, give the old target
an explicit lower withdrawal priority; novelty itself never wins.

All checks accept `max_rounds` and `max_matches`. Limits are nonnegative integers
or `None`; they renew per solver check, not per proposal or wall-clock interval.
Quantified E-matching is incomplete and can return `UNKNOWN`. Invalid inputs raise
an `EndoxaError`; they are not solver uncertainty. The supported fragment is
Boolean formulas and uninterpreted first-order logic with equality, not arithmetic.

## Revision proposals

`propose_revision(premises, policy=RevisionPolicy(), candidate=None,
max_withdrawals=1, max_checks=256)` accepts at
most one new Assertion or Rule. Without a candidate it searches for a repair;
with one it checks adoption and considers rejection alongside existing targets.
Candidate IDs must be new within their kind.

`RevisionPolicy(protected, priorities)` uses `Target(kind="assertion"|"rule", id=...)`.
Protected targets cannot be omitted, including a protected submitted candidate.
Lower integer priority withdraws first; an omitted priority is zero. Rank sets
by their withdrawal-count vector, reading priority layers from the largest
numeric priority down. Minimize that vector lexicographically before comparing
confidence: withdrawing two less important records can beat withdrawing one
more important record. Within one priority layer, fewer withdrawals come first.
Only equal count vectors compare confidence, layer by layer in that same order,
with each layer's omitted confidences sorted descending. Smaller vectors win;
for example `[0.6, 0.5]` beats `[0.9, 0.1]`, despite its larger sum. Confidence
is never added or aggregated. Exact equal ranks defer without an ID tie-break
or source policy. With `max_withdrawals=1`, this retains the single-target order.
Confidence 1.0 is not implicitly protected. Policy targets must exist in the
submitted state or candidate.

The result includes `decision` (`unchanged`, `proposed`, `deferred`), `reason`,
`binding`, `original`, `initial`, optional `fixed_base`, `trials`, `changes`,
optional `final`, and `checks_used`. Each trial's `omitted` is a nonempty tuple
of typed targets, including single-target trials. `original` always reports the
state before the candidate;
`initial` reports the attempted state including it. Rejecting a candidate does not
silently certify an inconsistent original state. A verified rejection that keeps
an already consistent state returns `unchanged` with `candidate_rejected`.

`Adopt(record)` adds the captured record.
`Withdraw(target)` only excludes that ID
from adoption. It never creates a negative claim or sets rule confidence to zero.
Other owners or remaining rules may still entail the withdrawn claim.

`max_withdrawals` is an integer at least one, defaulting to one. Set it explicitly
to two or more to consider larger existing-target sets. Candidate rejection is
still a standalone omission, ranked alongside existing withdrawals; rejection
plus existing repair is excluded at every limit. Protected candidates cannot
be rejected. No zero-cost rejection or novelty preference is inferred.

Every trial checks the complete remaining input, not only core owners, retaining
the full functional scope. Sets are enumerated lazily in rank order; the search
does not build all combinations first. Each visited set creates at most two
successors, so the frontier grows with visited trials rather than the size of
the full search space. Sorting input records and constructing each rank still
depend on input size. A proposal requires a unique verified best
set within this bounded scope. Two SAT sets at the best rank establish a tie.
A relevant UNKNOWN or an unexamined same-rank competitor after budget exhaustion
defers even if a SAT trial was found. Inferior sets need not be checked after a
unique best rank is settled. This is optimality within the configured scope, not
a guarantee of the best repair with an unlimited number of withdrawals.

`max_checks` is a finite integer at least two, defaulting to 256. It caps all
`check_consistency` calls made by one proposal: original state, attempted state
when a candidate exists, fixed base when needed, and revision trials. Without a
candidate, original and initial share one check; candidate rejection reuses the
original verdict without charging another. The minimum of two preserves both
original and attempted diagnostics for candidate requests. `checks_used` reports
the actual count, which can be smaller than the cap. The default accommodates a
complete one-or-two withdrawal search over 22 existing records: 253 sets plus
the original and fixed-base checks, before any early stopping.

Budget exhaustion returns `deferred` with `check_budget_exhausted`; it is separate
from solver UNKNOWN. `max_rounds` and `max_matches` still renew per individual
check. The total-check cap is not a time limit and does not bound the cost of a
single check. Supply per-check limits when needed. Search exhaustion is
`no_verified_single_revision` at the default scope and `no_verified_revision`
for larger scopes, never a claim that no repair exists. All scope and budget
settings are captured in the binding.

## Applying safely

`propose_revision` returns data; producing or saving a proposal does not change
adopted membership. Only `decision="proposed"` carries changes to apply. A ledger
is optional, and confidence calculation remains the caller's responsibility.

The immutable `binding` captures `premises`, `policy`, `candidate`, `max_rounds`,
`max_matches`, `max_withdrawals`, `max_checks`, and the candidate-inclusive
`functional_scope`. Before applying a proposal, including one restored from
storage, compare the current adopted records
and membership with `binding.premises`: IDs, atoms or rule formulas, polarity,
confidence, source, hard axioms, functional predicates, and retained ground scope.
Compare the policy's protected targets and priorities, the complete candidate,
and the intended search scope and both types of check limits too. Validate the
changes against these inputs and recheck the complete proposed state with
`check_consistency`; require SAT.

Preserve and validate `binding.functional_scope` in that state and later checks.
Do not weaken it or regenerate it from only the remaining Assertions. If restored
information is missing, input has changed, or the saved proposal uses an older API
contract, reconstruct complete current inputs and recheck or call
`propose_revision` again. A restored `final.status="SAT"` is not a certificate
for the current state.

The consumer must compare its store's state version and apply all changes in the
same atomic transaction or equivalent conditional update. The binding is neither
a proof certificate nor a store version; comparing it alone cannot prevent a
concurrent update between checking and application. endoxa implements no such
transaction.

## Storage boundary

Public records are an in-memory Python API, not a durable storage schema.
Field access and `dataclasses.replace` are available. Currently,
`dataclasses.asdict` works for `Assertion`, `Rule`, and `PremiseSet`; those records
can also be pickled. These conveniences are not a general codec: `RevisionPolicy`
contains a read-only mapping for `priorities`, so `asdict` and pickle raise
`TypeError` for it and for a proposal containing it. No long-term storage
compatibility is promised for dataclass output, pickle, type names, or module paths.

Callers own conversion to and from their chosen storage format, schema versions
and migrations, adoption state, and history. They must retain the inputs and scope
needed for the application checks above and validate recovered inputs through the
public constructors. endoxa supplies no general persistence codec for the new API;
historical formats and their migrations are also caller-owned.

## Measurements and historical data

`endoxa.instruments.calibration` retains independent Brier, knowledge-transition,
ask-outcome and windowed measurements. `endoxa.instruments.coverage` retains static
rule connectivity measurements. Callers provide observations and active inputs;
measurements do not update confidence or control adoption.

Historical atom `retract` recorded a polarity reversal. It must not be converted
blindly to `Withdraw`, which only ends adoption of an ID. Consumers preserve old
history through their own schemas, replay and confidence accounting.
The package contains no historical adjudication or replay engine. Callers needing
historical comparisons retain their own explicit reference implementation.
See [examples](examples/README.md).

## Development

Python 3.14+; install with `uv sync --locked --all-extras`.
Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`,
`uv run lint-imports`, and `uv run pytest`.
Optional extras: `trace` for trace records and `coverage` for graph measurements.

Licensed under Apache-2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
