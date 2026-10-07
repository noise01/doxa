"""endoxa -- checked premises, revision proposals, and independent measurements.

Submit explicit premises for consistency, entailment, independent support, or a
verified revision proposal. Callers own adopted membership, confidence updates,
history, storage, and application; this package writes no ledger.

The five packages are a DAG, listed here bottom-up:

- ``endoxa.syntax`` -- the shape of an atom: predicate, arity, arguments.
- ``endoxa.solver`` -- a self-contained SMT engine deciding satisfiability.
- ``endoxa.governance`` -- premise checks and verified revision proposals.
- ``endoxa.trace`` -- the ordered series of an agent's conscious propositions.
- ``endoxa.instruments`` -- calibration and coverage measures, imported by nothing
  else, because a measure its subject can reach is a measure its subject can
  move.

Nothing is re-exported here, and that is the decision rather than an unfinished
one: import from the package you mean. A top-level facade would give every name a
second address; the package owning a name states its responsibility.
"""

__all__: list[str] = []
