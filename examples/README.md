# Examples

Six scripts, each about one thing the library does. They take no arguments and
no setup beyond an install:

```bash
python examples/06_revision_proposals.py
```

| | |
| --- | --- |
| [`01_a_contradiction_is_caught.py`](01_a_contradiction_is_caught.py) | A rule exposes a conflict; a verified proposal names the weaker claim to withdraw. |
| [`02_a_tie_is_not_a_coin_flip.py`](02_a_tie_is_not_a_coin_flip.py) | Equally ranked repairs defer and leave original claims unchanged. |
| [`03_what_the_instruments_say.py`](03_what_the_instruments_say.py) | Confidence read against outcomes, three ways kept apart because they fail differently. |
| [`04_check_support.py`](04_check_support.py) | Independent support from another assertion and a rule, excluding the target's own assertion. |
| [`05_public_solver_interfaces.py`](05_public_solver_interfaces.py) | Expression bodies and public AST types. |
| [`06_revision_proposals.py`](06_revision_proposals.py) | One withdrawn ID does not erase other owners or reverse its original polarity. |

Examples 01, 02, 04 and 06 use the unreleased public premise API. Example 05
uses the public solver constructors. Callers own history, confidence updates
and application.

The streams in them are scripted. Nothing here measures an agent — the examples
show what the library reports, which is not the same as showing that reporting
it helped.

Each one is run by `tests/test_examples.py`, output included: an example that
stopped working would fail the suite rather than wait for a reader to find it.
