"""Check support independently of a claim's own assertion."""

from endoxa.governance import Assertion, PremiseSet, Rule, check_support

premises = PremiseSet(
    assertions=(
        Assertion(id="observation", atom="closed(door)", truth_value=True, confidence=0.7, source="tool"),
        Assertion(id="claim", atom="safe(room)", truth_value=True, confidence=0.8),
    ),
    rules=(Rule(id="safety", formula="fof(s, axiom, (closed(door) => safe(room))).", confidence=0.9),),
)
print("independent support:", check_support(premises, "safe(room)").verdict)
print("source:", next(record.source for record in premises.assertions if record.id == "observation"))
