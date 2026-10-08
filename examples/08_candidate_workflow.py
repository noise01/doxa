"""Read candidate outcomes against one fixed snapshot, without applying changes."""

from endoxa.governance import (
    Adopt,
    Assertion,
    PremiseSet,
    RevisionResult,
    Withdraw,
    propose_revision,
)


def report(label: str, outcome: RevisionResult) -> None:
    """Show the decision and typed changes without updating the input."""
    print(f"{label}: {outcome.decision} / {outcome.reason}")
    for change in outcome.changes:
        if isinstance(change, Adopt):
            print("  adopt:", change.record.id)
        elif isinstance(change, Withdraw):
            print("  withdraw:", change.target.id)
    if outcome.final is not None:
        print("  verified final:", outcome.final.status)


premises = PremiseSet(
    assertions=(Assertion(id="current-reading", atom="open(door)", truth_value=True, confidence=0.8),)
)
compatible = Assertion(id="temperature", atom="warm(room)", truth_value=True, confidence=0.6)
weaker = Assertion(id="weaker-reading", atom="open(door)", truth_value=False, confidence=0.3)
equal = Assertion(id="equal-reading", atom="open(door)", truth_value=False, confidence=0.8)
stronger = Assertion(id="stronger-reading", atom="open(door)", truth_value=False, confidence=0.9)

# These are independent requests; a returned Adopt has not changed premises.
report("compatible", propose_revision(premises, candidate=compatible))
report("weaker conflict", propose_revision(premises, candidate=weaker))
report("equal conflict", propose_revision(premises, candidate=equal))
report("stronger conflict", propose_revision(premises, candidate=stronger))
short = propose_revision(premises, candidate=stronger, max_checks=2)
report("short budget", short)
print("short budget changes:", len(short.changes))
print("original adopted IDs:", ", ".join(record.id for record in premises.assertions))
