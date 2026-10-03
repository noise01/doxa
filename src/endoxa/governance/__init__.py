"""Belief governance: the decision, the ledger, and the machinery underneath.

Hand this package beliefs and the constraints they live under, and it answers in
operations -- what to retract, what to hold, what stands. The answer is data
rather than a mutation: you append it to the ledger and apply it to your own
store.

- :mod:`~endoxa.governance.resolution` is the decision surface. Reading a ledger is
  not yet being governed; this is the part that makes a host governable.
- :mod:`~endoxa.governance.ledger` declares the seven operations as an append-only
  schema.
- :mod:`~endoxa.governance.derive` recovers the operation series from a host's
  audit log, read-only.
- :mod:`~endoxa.governance.view` folds the series back into a current view, in
  which an unsettleable conflict is a state with a name
  (:data:`~endoxa.governance.view.UNRESOLVED`) rather than a silent choice.
- :mod:`~endoxa.governance.support` reads a belief's footing off what became of the
  things supporting it: it had none, they still stand, they are all gone, or they
  are gone because the state no longer holds what they rested on. That last case
  is why "gone" and "refuted" must not share a name.
- :mod:`~endoxa.governance.revision` is the machinery every operation above is
  decided by -- the consistency check, the culprit searches, the preference
  ordering, and the detection of a conflict that cannot be settled from inside.
- :mod:`~endoxa.governance.knowledge` names where a belief sits relative to the
  knowledge boundary.
- :mod:`~endoxa.governance.provenance` fixes the names for where a belief came
  from, and separately for what brought it back into view. It decides nothing;
  which name applies is the host's to say.

The submodules are residents of this namespace rather than flattened into it.
What ``__all__`` exports is the API: the ledger schema, the derived view, and the
decision surface.
"""

from endoxa.governance.derive import LEDGER_EVENT_TYPES, DerivedLedger, derive_ledger
from endoxa.governance.formulas import parse_premise_fof, parse_query_fof
from endoxa.governance.knowledge import EpistemicStatus
from endoxa.governance.ledger import (
    EVIDENCE_REASONS,
    LEDGER_OPS,
    REASON_REASSERTION,
    REASON_REVISION_SURVIVED,
    REASON_RULE_RETRACTED,
    REASON_SUPPORT_LOST,
    EvidenceReason,
    LedgerOp,
    OpKind,
    SupportKind,
    SupportRef,
    TargetKind,
)
from endoxa.governance.metadata import Stance
from endoxa.governance.provenance import (
    PROVENANCE_KEYS,
    RETRIEVAL_KINDS,
    SOURCE_KINDS,
)
from endoxa.governance.query import (
    EntailmentResult,
    EntailmentVerdict,
    SolverStatus,
    check_belief_support,
    check_entailment,
)
from endoxa.governance.resolution import (
    GOVERNANCE_ACTOR,
    RETRACTED_RULE_CONFIDENCE,
    Belief,
    Constraints,
    ContradictionTie,
    GovernanceOutcome,
    Rule,
    govern,
)
from endoxa.governance.support import (
    ABSENT,
    ALIVE,
    DEAD,
    IN,
    INDETERMINATE,
    OUT,
    UNSUPPORTED,
    SupportState,
    SupportVerdict,
    support_verdict,
)
from endoxa.governance.view import (
    HELD,
    UNRESOLVED,
    BeliefState,
    ViewEquivalence,
    compare_to_state,
    reconstruct_view,
)

__all__ = [
    "ABSENT",
    "ALIVE",
    "DEAD",
    "EVIDENCE_REASONS",
    "GOVERNANCE_ACTOR",
    "HELD",
    "IN",
    "INDETERMINATE",
    "LEDGER_EVENT_TYPES",
    "LEDGER_OPS",
    "OUT",
    "PROVENANCE_KEYS",
    "REASON_REASSERTION",
    "REASON_REVISION_SURVIVED",
    "REASON_RULE_RETRACTED",
    "REASON_SUPPORT_LOST",
    "RETRACTED_RULE_CONFIDENCE",
    "RETRIEVAL_KINDS",
    "SOURCE_KINDS",
    "UNRESOLVED",
    "UNSUPPORTED",
    "Belief",
    "BeliefState",
    "Constraints",
    "ContradictionTie",
    "DerivedLedger",
    "EntailmentResult",
    "EntailmentVerdict",
    "EpistemicStatus",
    "EvidenceReason",
    "GovernanceOutcome",
    "LedgerOp",
    "OpKind",
    "Rule",
    "SolverStatus",
    "Stance",
    "SupportKind",
    "SupportRef",
    "SupportState",
    "SupportVerdict",
    "TargetKind",
    "ViewEquivalence",
    "check_belief_support",
    "check_entailment",
    "compare_to_state",
    "derive_ledger",
    "govern",
    "parse_premise_fof",
    "parse_query_fof",
    "reconstruct_view",
    "support_verdict",
]
