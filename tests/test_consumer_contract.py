"""A separate minimal consumer can use the additive API and old entry points."""

import inspect
import subprocess
import sys
from pathlib import Path

from endoxa.governance import Belief
from endoxa.governance.revision import check_atom_support
from endoxa.solver import parse_fof


def test_belief_signature_has_no_inferred_identity_or_context():
    parameters = inspect.signature(Belief).parameters
    assert set(parameters) == {"id", "atom", "truth_value", "confidence", "stance", "source"}
    assert all(item.kind == item.KEYWORD_ONLY for item in parameters.values())


def test_atom_support_refuses_inconsistent_premises():

    contradiction = parse_fof("fof(c, axiom, (p & ~p)).")[2]
    assert check_atom_support({}, [contradiction], "q").verdict == "INCONSISTENT_PREMISES"


def test_minimal_consumer_uses_only_public_interfaces_in_a_fresh_process():
    # -I removes ambient path overrides. The import fence makes any accidental
    # dependency on an external consumer fail, even if installed on this host.
    source = Path(__file__).resolve().parents[1] / "src"
    script = r"""import importlib.abc
import importlib
import sys
sys.path.insert(0, SOURCE)

class PublicDependencyFence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        allowed = sys.stdlib_module_names | {"endoxa", "lark", "typing_extensions"}
        if fullname.split(".")[0] not in allowed:
            raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, PublicDependencyFence())
try:
    importlib.import_module("_unrelated_consumer")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("The import fence did not refuse an external consumer")

from endoxa.governance import (
    Belief, Constraints, LedgerOp, Rule, check_belief_support,
    govern, parse_query_fof, reconstruct_view,
)

# The consumer owns its in-memory records and applies returned ID operations.
beliefs = [
    Belief(id="claim:1", atom="human(a)", truth_value=True,
                     confidence=1.0, stance="asserted", source="user"),
    Belief(id="claim:2", atom="mortal(a)", truth_value=False,
                     confidence=0.6, stance="hypothesis"),
]
rule = Rule.from_fof("fof(r, axiom, ![X]: (human(X) => mortal(X))).",
                     name="rule:1", confidence=1.0, defeasible=False)
records = {belief.id: belief.to_record() for belief in beliefs}
restored = [Belief.from_record(record) for record in records.values()]
assert restored == beliefs
outcome = govern(restored, Constraints(rules=(rule,)), max_rounds=4, max_matches=32)
assert outcome.consistent is False
assert outcome.retraction.target == "claim:2"
assert all(op.target in records for op in outcome.ops)
births = [LedgerOp("assert", belief.id, truth_value=belief.truth_value,
                  confidence=belief.confidence, atom=belief.atom,
                  stance=belief.stance, source=belief.source) for belief in beliefs]
view = reconstruct_view([*births, *outcome.ops])
assert view["claim:2"].truth_value is True
assert view["claim:2"].to_belief().atom == "mortal(a)"
assert view["claim:2"].source is None
assert view["claim:1"].to_belief() == beliefs[0]
assert check_belief_support(restored, [parse_query_fof(
    "fof(rule, conjecture, ![X]: (human(X) => mortal(X)))."
)[2]], "claim:2", max_rounds=4, max_matches=32).verdict == "ENTAILED"
# Missing new metadata does not stop the legacy ledger's fold.
legacy = reconstruct_view([LedgerOp("assert", "p(a)", actor="hypothesis", confidence=0.7)])
assert legacy["p(a)"].context == "hypothesis"
assert legacy["p(a)"].stance is None
from endoxa.governance.revision import PredicateConstraints
from endoxa.solver import BoundVar, BoundVarExpr, MultiPattern, Pattern, USort, to_tptp_expr
x = BoundVar("X", USort("item"))
assert isinstance(x, BoundVarExpr)
assert isinstance(MultiPattern(x), Pattern)
assert to_tptp_expr(x) == "X"
assert PredicateConstraints().revision_candidates() == []
print("public consumer contract passed")
""".replace("SOURCE", repr(str(source)))
    result = subprocess.run(  # noqa: S603 - our interpreter and fixed fixture
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "public consumer contract passed"
