# Quickstart

This guide describes the public endoxa 0.9.0 API. It takes a snapshot of adopted
claims and rules, checks it, and returns a proposal. The inputs below are scripted
illustrations, not measurements of an agent or observations about a real door.

## Install and run

Use Python 3.14 or newer:

```bash
pip install endoxa==0.9.0
```

The core uses a TPTP grammar parser and makes no model calls. `endoxa[trace]`
and `endoxa[coverage]` add optional trace and graph measurement dependencies.
No model SDK or paid service is needed for these examples.

From this checkout, run:

```bash
python examples/08_candidate_workflow.py
```

The [examples guide](../examples/README.md) also lists the seven smaller scripts.
For library development, use `uv sync --locked --all-extras` and `uv run python`
instead of relying on a separately installed release.

## Check what is supplied

```python
from endoxa.governance import (
    Assertion,
    PremiseSet,
    Rule,
    check_consistency,
    check_entailment,
    check_support,
)

premises = PremiseSet(
    assertions=(
        Assertion(id="sensor", atom="closed(door)", truth_value=True, confidence=0.7),
        Assertion(id="claim", atom="safe(room)", truth_value=True, confidence=0.8),
    ),
    rules=(Rule(id="safety", formula="fof(s, axiom, (closed(door) => safe(room))).", confidence=0.9),),
)
assert check_consistency(premises).status == "SAT"
assert check_entailment(premises, "fof(q, conjecture, safe(room)).").verdict == "ENTAILED"
assert check_support(premises, "safe(room)").verdict == "ENTAILED"
```

Ordinary entailment retains the submitted `safe(room)` claim. Support excludes
all of that atom's own Assertions, including negative ones, and uses the remaining
sensor claim and rule. Confidence does not make a submitted premise partly active:
every supplied Assertion and Rule participates in the logical check.

`SAT` means the supplied premises can hold together, not that the door is actually
closed. Read [check results and supported syntax](api.md#checks-and-results) before
interpreting `UNSAT`, `NOT_ENTAILED`, `INCONSISTENT_PREMISES` or `UNKNOWN`.

## Submit a candidate and read the decision

The [candidate workflow](../examples/08_candidate_workflow.py) submits separate
new records against one fixed snapshot: `open(door)` at confidence 0.8. It reports:

```text
compatible: proposed / candidate_consistent
weaker conflict: unchanged / candidate_rejected
equal conflict: deferred / same_rank_tie
stronger conflict: proposed / unique_verified_revision
short budget: deferred / check_budget_exhausted
```

| Attempt | Meaning |
| --- | --- |
| A compatible `warm(room)` claim | `Adopt` proposes adding its captured record. |
| A conflicting `open(door)` negative claim at 0.3 | Candidate rejection is preferred; the original consistent state is retained without changes. |
| The same conflict at 0.8 | Equal-ranked viable outcomes defer; no ID chooses the winner. |
| The same conflict at 0.9 | The proposal withdraws the old ID and adopts the new record, with the full final input verified SAT. |
| That last request with `max_checks=2` | Original and attempted diagnostics consume the budget; revision selection is deferred without changes. |

These outcomes use the default policy. Explicit protection and priorities can
change them. Source, recency and the origin of a rule do not automatically select
a policy. Candidate rejection is ranked alongside withdrawals; it is not a free
fallback when checking or comparison is inconclusive.

The script never changes the original snapshot or saves a proposal. Each attempt
is independent; a returned `Adopt` has not automatically become input to the next
request. The caller decides whether to proceed using the
[application requirements](application-and-migration.md#before-applying-a-proposal).

## Choose the next guide

- [Public API and checks](api.md) explains records, ownership, syntax and functional exclusions.
- [Revision proposals](revision.md) explains ranking sets, multiple withdrawals and uncertainty.
- [Application, storage and migration](application-and-migration.md) explains safe use and version changes.

[Back to README](../README.md)
