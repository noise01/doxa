"""An agent contradicts itself twenty turns apart, and the ledger notices.

The claims do not conflict on their face: one is about Socrates being human, the
other about Socrates not being mortal. What makes them a contradiction is a rule
the agent was given, and finding that out is a question about a set rather than
about either claim -- which is why noticing it is not something the thing that
lost track can be asked to do.

Run: python examples/01_a_contradiction_is_caught.py
"""

from endoxa.governance import Belief, Constraints, LedgerOp, Rule, govern, reconstruct_view

MORTALITY = "fof(m, axiom, ![X]: (human(X) => mortal(X)))."

# What the agent was told to hold, and how firmly it may be given up. A rule the
# agent learned is defeasible; one it was handed would not be.
constraints = Constraints(
    rules=(Rule(name="mortality", axiom=MORTALITY, confidence=0.9),),
)

# Turn 3: the user says it. Turn 24: the agent says the opposite of what follows,
# and says it less firmly, which is the whole of what the preference needs.
beliefs = [
    Belief(truth_value=True, confidence=1.0, id="human(socrates)", atom="human(socrates)", stance="asserted"),
    Belief(truth_value=False, confidence=0.6, id="mortal(socrates)", atom="mortal(socrates)", stance="asserted"),
]

outcome = govern(beliefs, constraints)

print("consistent:", outcome.consistent)
print()
print("What to do about it, in order:")
for op in outcome.ops:
    print(f"  {op.op:<8} {op.target:<18} truth={op.truth_value}")
print()
print("Note what did not happen: the rule was not blamed, and the claim the user")
print("made was not touched. What gave way is the least defensible thing in the")
print("set -- and `govern` decided that without changing anything.")
print()

# The operations are data. A host appends them to its ledger and applies them to
# its own store; nothing above mutated anything.
ledger = [
    LedgerOp(
        op="assert",
        target=b.id,
        actor="example",
        atom=b.atom,
        stance=b.stance,
        source=b.source,
        truth_value=b.truth_value,
        confidence=b.confidence,
    )
    for b in beliefs
]
ledger += list(outcome.ops)

print("The view, folded back out of the ledger:")
for target, state in sorted(reconstruct_view(ledger).items()):
    print(f"  {target:<18} truth={state.truth_value!s:<5} confidence={state.confidence} status={state.status}")
print()
print("The retracted row is still in the ledger. What the agent believed at turn")
print("24 survives the fact that it no longer believes it -- the view is derived,")
print("so history does not have to be overwritten to change the answer.")
