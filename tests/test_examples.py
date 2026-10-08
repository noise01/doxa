"""The examples run, and still say what their prose says they say.

An example is a promise made in public, and the README already demonstrated how
quietly one rots: its snippet had been broken twice over and nothing noticed
until someone tried to install the package. So these are executed here as a
reader would execute them -- as scripts, from the repository root -- and the
numbers their prose points at are asserted, not just their exit codes.

The enumeration checks itself. An example added without a row below would
otherwise be the one nobody runs.
"""

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

#: Each example, with the lines its own prose commits it to. Substrings rather
#: than whole output: what is pinned is the claim, not the layout.
CLAIMS: dict[str, tuple[str, ...]] = {
    "08_candidate_workflow.py": (
        "compatible: proposed / candidate_consistent",
        "adopt: temperature",
        "weaker conflict: unchanged / candidate_rejected",
        "equal conflict: deferred / same_rank_tie",
        "stronger conflict: proposed / unique_verified_revision",
        "withdraw: current-reading",
        "adopt: stronger-reading",
        "verified final: SAT",
        "short budget: deferred / check_budget_exhausted",
        "short budget changes: 0",
        "original adopted IDs: current-reading",
    ),
    "07_bounded_revisions.py": (
        "single-withdrawal scope: no_verified_single_revision",
        "decision: proposed",
        "withdraw: p-negative, q-negative",
        "withdrawal limit: 2",
        "checks used: 7",
        "short budget: check_budget_exhausted",
        "original records: 4",
    ),
    "06_revision_proposals.py": (
        "decision: proposed",
        "withdraw: negative",
        "original negative polarity: False",
        "positive still entailed: ENTAILED",
    ),
    "04_check_support.py": ("independent support: ENTAILED", "source: tool"),
    "05_public_solver_interfaces.py": (
        "expression body: label(X)",
        "bound-variable type: True",
        "pattern type: True",
    ),
    "01_a_contradiction_is_caught.py": (
        "consistency: UNSAT",
        "decision: proposed",
        "withdraw: mortal",
        "original polarity: False",
        "verified final: SAT",
    ),
    "02_a_tie_is_not_a_coin_flip.py": (
        "decision: deferred",
        "changes: 0",
        "original claims: 2",
    ),
    "03_what_the_instruments_say.py": (
        # The prose says a single score cannot tell "is" from "was"; these are
        # the numbers that make the point, so they are the ones that must hold.
        "Brier 0.332",
        "0.631",
        "1/3",
        "resolution rate: 0.75",
        "affirm rate:     0.67",
    ),
}


def test_the_enumeration_covers_every_example() -> None:
    on_disk = {path.name for path in EXAMPLES.glob("*.py")}
    assert on_disk == set(CLAIMS), f"examples and claims disagree: {on_disk ^ set(CLAIMS)}"


@pytest.mark.parametrize(("name", "claims"), CLAIMS.items())
def test_the_example_runs_and_says_what_it_claims(name: str, claims: tuple[str, ...]) -> None:
    result = subprocess.run(  # noqa: S603 -- a fixed path run by this interpreter, which is the point
        [sys.executable, str(EXAMPLES / name)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{name} exited {result.returncode}:\n{result.stderr}"
    missing = [claim for claim in claims if claim not in result.stdout]
    assert not missing, f"{name} no longer says {missing}:\n{result.stdout}"
