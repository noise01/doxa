# Application, storage and migration

Checks and proposals describe supplied inputs. The caller owns adopted membership,
confidence calculation and updates, history, storage formats and application.
endoxa supplies no store, general persistence codec or transaction. A ledger is
optional. Instruments accept observations independently and do not decide adoption
or update confidence.

## Before applying a proposal

Only `decision="proposed"` carries changes. A caller applying one, including a
proposal restored from storage, must:

1. Compare complete current records and membership with `binding.premises`:
   typed IDs, atoms or Rule formulas, polarity, confidence, source, hard axioms,
   functional predicates and the retained original scope.
2. Compare `binding.policy`, the complete candidate, `max_rounds`, `max_matches`,
   `max_withdrawals` and `max_checks` with the inputs and controls it intends to use.
   Validate and retain the separately captured candidate-inclusive
   `binding.functional_scope`.
3. Validate all change records against those inputs, construct the complete
   proposed state and recheck it with `check_consistency`, using the retained scope
   and intended solver limits. Require `SAT`; UNKNOWN is insufficient.
4. Check the caller's store version and apply all changes atomically in the same
   transaction or equivalent conditional update. If state changed, reconstruct
   complete current inputs and request a new proposal.

The binding is neither a proof certificate nor a store version. Comparing it
alone cannot prevent a concurrent update between checking and application.
A saved `final.status="SAT"` does not certify the current state. Apply multiple
withdrawals together with any candidate adoption; do not apply one change at a
time from a verified set.

The following is only an in-memory reconstruction and recheck of a known proposal.
It performs no storage update, serialization, concurrency control or transaction:

```python
from dataclasses import replace
from endoxa.governance import Assertion, PremiseSet, Withdraw, check_consistency, propose_revision, target_of

premises = PremiseSet(
    assertions=(
        Assertion(id="positive", atom="open(door)", truth_value=True, confidence=0.8),
        Assertion(id="negative", atom="open(door)", truth_value=False, confidence=0.3),
    )
)
outcome = propose_revision(premises)
assert outcome.decision == "proposed"
assert outcome.binding.premises == premises
withdrawn = {change.target for change in outcome.changes if isinstance(change, Withdraw)}
proposed_state = replace(
    premises,
    assertions=tuple(record for record in premises.assertions if target_of(record) not in withdrawn),
    functional_scope=outcome.binding.functional_scope,
)
assert (
    check_consistency(
        proposed_state,
        max_rounds=outcome.binding.max_rounds,
        max_matches=outcome.binding.max_matches,
    ).status
    == "SAT"
)
assert len(premises.assertions) == 2  # The original input is still unchanged.
```

This example has no candidate or adopted Rules and its state is held locally.
It is not a general change applicator. A real caller also handles typed Rule
withdrawals and `Adopt` records, validates the full binding, and protects its
current state from concurrent changes.

## Storage boundary

Public records are an in-memory Python API. `dataclasses.replace` is available.
Currently `dataclasses.asdict` and pickle work for `Assertion`, `Rule` and
`PremiseSet`, but this is not a general codec: `RevisionPolicy.priorities` is a
read-only mapping, so `asdict` and pickle raise `TypeError` for it and for proposals
containing it. There is no long-term storage compatibility promise for dataclass
output, pickle, type names or module paths.

Callers choose their own formats, schema versions and migrations. Keep the inputs
and controls needed for validation, and validate recovered records through the
public constructors. If information is missing or the saved API contract is old,
reconstruct complete current inputs and recheck or request a fresh proposal.
Do not invent omitted controls and treat an old SAT result as current approval.

## Upgrading to 0.9.0

See the [0.9.0 changelog](../CHANGELOG.md#090) for the release record.

- `RevisionTrial.omitted` is now a nonempty tuple of distinct typed targets,
  including for single-target trials. Iterate over it rather than reading `.id`
  or `.kind` directly on the field.
- Retain and validate `RevisionBinding.max_withdrawals` and `max_checks` alongside
  the existing inputs, scope and per-check solver limits. Regenerate saved
  proposals missing these controls from complete current inputs before application.
- Handle finite `max_checks=256` even with default `max_withdrawals=1`.
  `check_budget_exhausted` is a deferred decision with no changes, separate from
  solver UNKNOWN. Choose a larger finite allowance explicitly when appropriate;
  never apply an incomplete search.
- Multiple existing withdrawals require `max_withdrawals` above one. Rejection
  plus existing repair remains excluded. Validate and recheck the entire proposed
  state before atomically applying the full change set.

No new durable storage schema or automatic application is introduced in 0.9.0.

## Upgrading from 0.7.0 or earlier

The [0.8.0 changelog](../CHANGELOG.md#080) records the earlier breaking boundary change.

| Former interface | Current responsibility or interface |
| --- | --- |
| `Belief` and stance-based state | Keyword-only `Assertion(id, atom, truth_value, confidence, source=None)` with independent IDs. |
| `Rule(name, axiom, confidence)` | Keyword-only `Rule(id, formula, confidence)`. |
| `Constraints` | `PremiseSet`, retaining hard axioms, functional predicates and scope. |
| `govern`, `.consistent` and `.ops` | Explicit checks and `propose_revision`; handle `.status`, `.decision`, `.reason` and typed changes. |
| Implicit protection or source-based preference | Explicit typed targets in `RevisionPolicy`; confidence 1.0 does not protect by itself. |
| Old ledger exports, event conversion, evidence reasons, replay and comparison | Caller-owned accounting and historical-format handling. |

Use `endoxa.governance` as the recommended entry. `Assumption` and
`ConsistencyResult` are native result types, not aliases of old Belief records.
The former `governance.legacy`, `revision`, `resolution`, `metadata`, `query` and
`consistency` module paths and obsolete internal truth-flip and rule/link
adjudication are removed without compatibility aliases.

Historical atom `retract` recorded polarity reversal; it must not be translated
blindly into `Withdraw`, which only ends one ID's adoption. Preserve historical
polarity, evidence and provenance meanings in the caller's own schema, replay
and confidence accounting. endoxa supplies no historical replay engine, reference
comparison implementation, database migration or durable record codec.

## Limits of the claim

The library checks the formal input supplied to it. It does not establish what
happened in the world or ensure that natural language was translated correctly.
Quantified solving is incomplete; UNKNOWN is an inconclusive result. Revision
optimality is bounded by configured withdrawal scope and check limits.

The scripted examples and restricted-fragment solver comparisons demonstrate
these contracts. They do not show that an entire agent is more accurate or better
calibrated. The package remains pre-alpha; pre-1.0 minor versions can change the
public API.

[Quickstart](quickstart.md) · [Back to README](../README.md)
