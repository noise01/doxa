# endoxa

**Consistency checks, verified revision proposals, and independent measurements.**
Callers own adopted membership, confidence updates, history, storage, and application.

> **Status: pre-alpha.** Version 0.9.0 adds bounded multiple withdrawals and a
> finite proposal-wide check budget, and changes revision trial and binding types.
> This minor release includes breaking changes. Read the
> [migration guide](docs/application-and-migration.md#upgrading-to-090) and
> [changelog](CHANGELOG.md#090) before upgrading.

## Start here

Python 3.14 or newer:

```bash
pip install endoxa==0.9.0
```

The core requires no model SDK or paid API. Its dependency is the TPTP grammar
parser; trace and graph coverage packages are optional extras.

| Guide | What to read it for |
| --- | --- |
| [Quickstart](docs/quickstart.md) | Install, check a snapshot, and read candidate adoption, rejection and deferral. |
| [Public API and checks](docs/api.md) | Input and result fields, formula syntax, support and functional scope. |
| [Revision proposals](docs/revision.md) | Protection, set ranking, multiple withdrawals, check budgets and uncertainty. |
| [Application, storage and migration](docs/application-and-migration.md) | Validate a binding, recheck, apply atomically, and upgrade old callers. |
| [Runnable examples](examples/README.md) | Eight scripts with fixed inputs and checked outputs. |

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

Import premise records, check functions and proposal types from `endoxa.governance`.
`Assertion` describes one signed ground atom; `Rule` describes an adopted closed
FOF premise. `PremiseSet` holds the complete snapshot and fixed constraints.

- `check_consistency` reports `SAT`, `UNSAT` or `UNKNOWN` with signed ownership and
  an assumption core. The core is diagnostic, not a withdrawal plan.
- `check_entailment` checks consistency before asking whether a closed FOF
  conjecture follows. Inconsistent premises are reported separately.
- `check_support` excludes every Assertion of the queried atom in both polarities,
  then asks whether the remaining input entails the claim independently.

These checks cover Boolean formulas and uninterpreted first-order logic with
equality, without arithmetic reasoning. Quantified solving is incomplete.
`UNKNOWN` is inconclusive; invalid inputs raise an `EndoxaError` instead.
See [input types and check results](docs/api.md).

## Revision proposals

`propose_revision(premises, policy=RevisionPolicy(), candidate=None,
max_withdrawals=1, max_checks=256)` returns data. A candidate is at most one new
Assertion or Rule. `Adopt` adds its captured record; `Withdraw` ends one typed
ID's adoption without negating its claim. Exact equal ranks defer.

Set `max_withdrawals` explicitly above one to consider larger existing-target sets.
`max_checks` caps consistency calls across the whole proposal; exhaustion defers
without changes, even when a SAT trial has been found but selection is incomplete.
Per-check `max_rounds` and `max_matches` are separate solver controls.
Protection and withdrawal priorities are explicit; confidence is never aggregated.
See [ranking, candidate constraints and budgets](docs/revision.md).

## Applying safely

Only `decision="proposed"` carries changes to apply. Before applying or restoring
one, the caller compares the complete current inputs, policy and limits with its
`binding`, retains `binding.functional_scope`, validates all changes, and rechecks
the complete proposed state for `SAT`. It must check its store version and apply
all changes atomically. A binding or saved SAT result is neither a store version
nor a certificate for the current state.

endoxa implements no persistence codec, store update or transaction. See
[application and storage responsibilities](docs/application-and-migration.md).

## Other public interfaces

`endoxa.solver` provides expression constructors and solver types.
`endoxa.instruments.calibration` measures Brier scores, knowledge transitions,
ask outcomes and windows; `endoxa.instruments.coverage` measures rule connectivity.
Callers supply predictions, outcomes and active inputs. Instruments neither update
confidence nor control adoption. See the
[measurement example](examples/03_what_the_instruments_say.py).

Ledger schemas, historical replay and state comparison belong to callers.
The former `governance.legacy` and Belief-based entry points are removed without
compatibility aliases. Historical `retract` polarity reversal is not `Withdraw`.
See [migration and limits](docs/application-and-migration.md#upgrading-from-070-or-earlier).

## Development

Install with `uv sync --locked --all-extras`.
Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`,
`uv run lint-imports`, and `uv run pytest`.
Optional extras: `trace` for trace records and `coverage` for graph measurements.

Licensed under Apache-2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
