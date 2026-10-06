"""Check adopted premises and propose verified changes; callers own their state."""

from endoxa.governance.checks import (
    check_consistency,
    check_entailment,
    check_support,
)
from endoxa.governance.formulas import parse_premise_fof, parse_query_fof
from endoxa.governance.premises import Assertion, PremiseSet, RevisionPolicy, Rule, Target, target_of
from endoxa.governance.proposal import (
    Adopt,
    RevisionBinding,
    RevisionDecision,
    RevisionReason,
    RevisionResult,
    RevisionTrial,
    Withdraw,
    propose_revision,
)
from endoxa.governance.results import Assumption, ConsistencyResult, EntailmentResult, EntailmentVerdict, SolverStatus

__all__ = [
    "Adopt",
    "Assertion",
    "Assumption",
    "ConsistencyResult",
    "EntailmentResult",
    "EntailmentVerdict",
    "PremiseSet",
    "RevisionBinding",
    "RevisionDecision",
    "RevisionPolicy",
    "RevisionReason",
    "RevisionResult",
    "RevisionTrial",
    "Rule",
    "SolverStatus",
    "Target",
    "Withdraw",
    "check_consistency",
    "check_entailment",
    "check_support",
    "parse_premise_fof",
    "parse_query_fof",
    "propose_revision",
    "target_of",
]
