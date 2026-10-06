"""Equally ranked repairs defer without choosing an arbitrary ID."""

from endoxa.governance import Assertion, PremiseSet, propose_revision

pair = PremiseSet(
    assertions=(
        Assertion(id="indoors", atom="indoors(cat)", truth_value=True, confidence=0.6),
        Assertion(id="outdoors", atom="outdoors(cat)", truth_value=True, confidence=0.6),
    ),
    hard_axioms=("fof(x, axiom, ~(indoors(cat) & outdoors(cat))).",),
)
proposal = propose_revision(pair)
print("decision:", proposal.decision)
print("reason:", proposal.reason)
print("changes:", len(proposal.changes))
print("original claims:", len(pair.assertions))
