# Examples

Eight scripts with fixed inputs. Python 3.14+ and an endoxa 0.9.0 install are
enough; no model connection, SDK or paid API is required:

```bash
pip install endoxa==0.9.0
python examples/08_candidate_workflow.py
```

Run the files from this checkout. For library development, use
`uv sync --locked --all-extras` and `uv run python examples/08_candidate_workflow.py`.

| Script | What it demonstrates |
| --- | --- |
| [`01_a_contradiction_is_caught.py`](01_a_contradiction_is_caught.py) | A rule exposes a conflict; a verified proposal names the weaker claim to withdraw. |
| [`02_a_tie_is_not_a_coin_flip.py`](02_a_tie_is_not_a_coin_flip.py) | Equally ranked repairs defer and leave original claims unchanged. |
| [`03_what_the_instruments_say.py`](03_what_the_instruments_say.py) | Brier scores, knowledge transitions and question outcomes are measured separately. |
| [`04_check_support.py`](04_check_support.py) | Independent support from another assertion and a rule, excluding the target's own assertions. |
| [`05_public_solver_interfaces.py`](05_public_solver_interfaces.py) | Expression bodies and public AST types. |
| [`06_revision_proposals.py`](06_revision_proposals.py) | One withdrawn ID does not erase other owners or reverse its original polarity. |
| [`07_bounded_revisions.py`](07_bounded_revisions.py) | Two independent conflicts need two withdrawals; a total-check budget can defer. |
| [`08_candidate_workflow.py`](08_candidate_workflow.py) | Compatible, weaker, equal and stronger candidates receive adoption, rejection, deferral or a verified replacement proposal. |

Example 07's `max_withdrawals` and `max_checks` controls are published in 0.9.0;
they are not available in 0.8.0. Example 08 uses the same public 0.9.0 API.
Neither script applies or stores its changes. Callers own history, confidence
updates and application.

For a first complete reading, follow the [quickstart](../docs/quickstart.md).
For each smaller topic, choose the corresponding script above. The inputs are
scripted illustrations, not measurements of improved agent performance.

Every script runs under `tests/test_examples.py`, including assertions on its
reported outputs. Python snippets in the README and guides are checked too.
