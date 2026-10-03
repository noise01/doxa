# Examples

Five scripts, each about one thing the library does. They take no arguments and
no setup beyond an install:

```bash
python examples/01_a_contradiction_is_caught.py
```

| | |
| --- | --- |
| [`01_a_contradiction_is_caught.py`](01_a_contradiction_is_caught.py) | Two claims twenty turns apart that only conflict under a rule. What gives way, what is left alone, and why the retracted row stays in the ledger. |
| [`02_a_tie_is_not_a_coin_flip.py`](02_a_tie_is_not_a_coin_flip.py) | Two claims held exactly as firmly as each other. The inability to choose gets a name, both sides keep it, and an answer ends it with an author and a time. |
| [`03_what_the_instruments_say.py`](03_what_the_instruments_say.py) | Confidence read against outcomes, three ways that are kept apart because they fail differently. |
| [`04_direct_ledger.py`](04_direct_ledger.py) | A caller-owned operation sequence replayed without events or storage dependencies. |
| [`05_public_solver_interfaces.py`](05_public_solver_interfaces.py) | Expression bodies, public AST types and predicate-link revision candidates. |

The streams in them are scripted. Nothing here measures an agent — the examples
show what the library reports, which is not the same as showing that reporting
it helped.

Each one is run by `tests/test_examples.py`, output included: an example that
stopped working would fail the suite rather than wait for a reader to find it.
