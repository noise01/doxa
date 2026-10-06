"""A rule exposes a contradiction and a verified proposal names one withdrawal."""

from endoxa.governance import Assertion, PremiseSet, Rule, check_consistency, propose_revision

premises = PremiseSet(
    assertions=(
        Assertion(id="human", atom="human(socrates)", truth_value=True, confidence=1.0),
        Assertion(id="mortal", atom="mortal(socrates)", truth_value=False, confidence=0.6),
    ),
    rules=(Rule(id="mortality", formula="fof(m, axiom, ![X]: (human(X) => mortal(X))).", confidence=0.9),),
)
proposal = propose_revision(premises)
print("consistency:", check_consistency(premises).status)
print("decision:", proposal.decision)
for change in proposal.changes:
    print("withdraw:", change.target.id)
print("original polarity:", next(record.truth_value for record in premises.assertions if record.id == "mortal"))
print("verified final:", proposal.final.status)
