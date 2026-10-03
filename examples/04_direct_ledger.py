"""Record and replay observations without an event schema or storage framework."""

from endoxa.governance import LedgerOp, reconstruct_view

ledger = [
    LedgerOp(
        "assert",
        "reading:1",
        truth_value=True,
        confidence=0.7,
        atom="door_closed(room)",
        stance="hypothesis",
        source="tool",
    ),
    LedgerOp("confirm", "reading:1", actor="observer"),
]
state = reconstruct_view(ledger)["reading:1"]
print(f"operations: {len(ledger)}; atom: {state.to_belief().atom}; source: {state.source}")
