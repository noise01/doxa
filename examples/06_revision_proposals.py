"""Withdraw one owner while retaining another owner's positive claim."""

from endoxa.governance import Assertion, PremiseSet, check_entailment, propose_revision

premises = PremiseSet(
    assertions=(
        Assertion(id="first", atom="p(a)", truth_value=True, confidence=0.8),
        Assertion(id="second", atom="p(a)", truth_value=True, confidence=0.7),
        Assertion(id="negative", atom="p(a)", truth_value=False, confidence=0.2),
    ),
)
outcome = propose_revision(premises)
print(f"decision: {outcome.decision}")
print(f"withdraw: {outcome.changes[0].target.id}")
print(f"original negative polarity: {premises.assertions[1].truth_value}")
remaining = PremiseSet(assertions=tuple(record for record in premises.assertions if record.id != "negative"))
print(f"positive still entailed: {check_entailment(remaining, 'fof(q, conjecture, p(a)).').verdict}")
