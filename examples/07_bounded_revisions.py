"""Two independent conflicts require two withdrawals within an explicit budget."""

from endoxa.governance import Assertion, PremiseSet, Withdraw, propose_revision

premises = PremiseSet(
    assertions=(
        Assertion(id="p-positive", atom="p(a)", truth_value=True, confidence=0.8),
        Assertion(id="p-negative", atom="p(a)", truth_value=False, confidence=0.2),
        Assertion(id="q-positive", atom="q(a)", truth_value=True, confidence=0.9),
        Assertion(id="q-negative", atom="q(a)", truth_value=False, confidence=0.3),
    )
)
print("single-withdrawal scope:", propose_revision(premises).reason)
outcome = propose_revision(premises, max_withdrawals=2, max_checks=16)
print("decision:", outcome.decision)
print("withdraw:", ", ".join(change.target.id for change in outcome.changes if isinstance(change, Withdraw)))
print("withdrawal limit:", outcome.binding.max_withdrawals)
print("checks used:", outcome.checks_used)
short = propose_revision(premises, max_withdrawals=2, max_checks=2)
print("short budget:", short.reason)
print("original records:", len(premises.assertions))
