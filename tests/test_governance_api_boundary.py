"""New public names are native types and exclude the retained historical engine."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import get_type_hints

from endoxa import governance
from endoxa.governance import (
    Assumption,
    ConsistencyResult,
    EntailmentResult,
    PremiseSet,
    check_consistency,
    check_entailment,
    results,
)


def test_result_names_repr_and_annotations_are_native_and_consistent():
    for record in (Assumption, ConsistencyResult, EntailmentResult):
        assert record.__module__ == "endoxa.governance.results"
        assert getattr(results, record.__name__) is record
        assert getattr(governance, record.__name__) is record
    checked = check_consistency(PremiseSet())
    assert type(checked) is ConsistencyResult
    assert repr(checked).startswith("ConsistencyResult(")
    assumption = Assumption(atom="p(a)", truth_value=True, owner_ids=("claim",))
    assert repr(assumption).startswith("Assumption(")
    assert get_type_hints(check_consistency)["return"] is ConsistencyResult
    assert get_type_hints(check_entailment)["return"] is EntailmentResult


def test_former_public_names_and_modules_are_absent():
    old_names = {
        "Belief",
        "BeliefAssumption",
        "BeliefConsistencyResult",
        "Constraints",
        "GovernanceOutcome",
        "ContradictionTie",
        "LedgerOp",
        "derive_ledger",
        "reconstruct_view",
        "govern",
        "check_belief_consistency",
        "check_belief_support",
    }
    assert not old_names.intersection(governance.__all__)
    assert all(not hasattr(governance, name) for name in old_names)
    for module in (
        "consistency",
        "derive",
        "knowledge",
        "ledger",
        "metadata",
        "provenance",
        "query",
        "resolution",
        "revision",
        "support",
        "view",
    ):
        assert importlib.util.find_spec(f"endoxa.governance.{module}") is None
    for module in (
        "legacy",
        "_ledger",
        "_derive",
        "_view",
        "_atoms",
        "_metadata",
        "_consistency",
        "_query",
        "_resolution",
        "_revision",
        "_support",
        "_knowledge",
        "_provenance",
    ):
        assert importlib.util.find_spec(f"endoxa.governance.{module}") is None


def test_new_consumer_runs_without_loading_historical_governance():
    source = Path(__file__).resolve().parents[1] / "src"
    script = r"""import importlib.abc
import sys
sys.path.insert(0, SOURCE)

class HistoryFence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("endoxa.governance."):
            name = fullname.split(".")[2]
            if name in {"_atoms", "legacy", "_metadata", "_consistency", "_query", "_resolution", "_revision",
                        "_derive", "_ledger", "_view", "_support", "_knowledge", "_provenance"}:
                raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, HistoryFence())
from endoxa.governance import (
    Assertion, ConsistencyResult, PremiseSet, Withdraw,
    check_consistency, check_support, propose_revision, target_of,
)
positive = Assertion(id="positive", atom="p(a)", truth_value=True, confidence=0.8)
negative = Assertion(id="negative", atom="p(a)", truth_value=False, confidence=0.2)
premises = PremiseSet(assertions=(positive, negative))
assert type(check_consistency(premises)) is ConsistencyResult
proposal = propose_revision(premises)
assert proposal.changes == (Withdraw(target=target_of(negative)),)
assert proposal.final.status == "SAT"
assert check_support(premises, "p(a)").verdict == "NOT_ENTAILED"
assert negative.truth_value is False
print("new public consumer passed")
""".replace("SOURCE", repr(str(source)))
    result = subprocess.run(  # noqa: S603 - fixed isolated contract probe
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "new public consumer passed"
