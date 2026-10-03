"""What the governance layer decides to do next.

:mod:`~endoxa.governance.ledger` says what happened and
:mod:`~endoxa.governance.view` says what is currently the case. This
module is the third face: **given a set of beliefs and the constraints they live
under, which ledger operations does governance perform?**

Without it the contract is only half a contract. An external host can read a
ledger, but reading is not being governed -- to be governed it has to be able to
hand its beliefs over and get back "retract this one", "supersede that one",
"these two cannot be separated, hold both". Those answers are exactly the seven
operations, so the decision surface returns :class:`~endoxa.governance.ledger.LedgerOp`
rather than a bespoke verdict type.

**This is wiring, not new judgement.** Every decision below is made by the same
pure functions a host would otherwise have to call itself, in the same order and
under the same conditions. What changes is *where the order lives*: written out by
hand in each caller, it is a wiring that gets fixed once and stays broken
everywhere else.

**Scope: the belief tier.** Beliefs, learned rules and the ties between them --
the ledger's primary object. A host may additionally arbitrate *acquired links*
(:func:`~endoxa.governance.revision.find_link_culprits`), which the ledger
deliberately keeps separate. So this surface does not reduce a host's whole
arbitration to a single call, and it is not meant to: whether the two ledgers are
ever shown as one view is a later judgement.

**Input is text.** Rules and hard constraints arrive as TPTP axiom strings and
are parsed here. A host that had to build ``Expr`` objects would need the solver
library to speak to governance at all; taking text keeps the contract something a
foreign host can satisfy with a string.

Depends only on the bundled solver (:mod:`endoxa.solver`) and on this package's own
revision logic (:mod:`endoxa.governance.revision`).
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from endoxa.errors import InvalidArgumentError
from endoxa.governance.formulas import parse_premise_fof
from endoxa.governance.ledger import LedgerOp
from endoxa.governance.metadata import (
    Belief,
    validate_confidence,
    validate_id,
)
from endoxa.governance.revision import (
    ContradictionTie,
    check_consistency,
    choose_revision_candidate,
    find_rule_culprits,
    functional_exclusion_partner,
    select_tie_question_target,
    select_verified_revision_target,
)
from endoxa.governance.revision.facts import parse_fact_to_expr
from endoxa.solver import Expr

#: ``actor`` stamped on the operations governance itself decides. A host that
#: applies one writes it under whatever role its own beliefs use; what the ledger
#: records here is that the decision came from the governance layer rather than
#: from a speaker.
GOVERNANCE_ACTOR = "governance"

#: Confidence a soft retraction drives a rule to. The row is kept so the rule can
#: be re-learned -- which is the ledger's own stance: the entry does not
#: disappear, it stops counting.
RETRACTED_RULE_CONFIDENCE = 0.0


@dataclass(frozen=True, slots=True)
class Rule:
    """One rule constraining the beliefs, as a TPTP axiom.

    Attributes:
        name: How the rule is named in an operation that retracts it.
        axiom: The rule as a TPTP ``fof`` string.
        confidence: Its credence, weighed against a belief's when governance picks
            what to give up.
        defeasible: Whether it may be retracted at all. A base axiom is not a
            revision candidate; only a learned rule is.
    """

    name: str
    axiom: str
    confidence: float
    defeasible: bool = True

    def __post_init__(self) -> None:
        validate_id(self.name)
        validate_confidence(self.confidence)
        if not isinstance(self.defeasible, bool):
            msg = "defeasible must be a bool"
            raise InvalidArgumentError(msg)
        parse_premise_fof(self.axiom)

    @classmethod
    def from_fof(cls, text: str, *, confidence: float, defeasible: bool, name: str | None = None) -> Rule:
        """Build a rule through the strict premise entry point.

        Name defaults to the FOF name; an override is the operation's rule ID.
        The annotated source remains in axiom, retaining the original FOF name
        and role. Neither role nor name chooses defeasibility.
        """
        validate_confidence(confidence)
        if not isinstance(defeasible, bool):
            msg = "defeasible must be a bool"
            raise InvalidArgumentError(msg)
        fof_name, _role, _formula = parse_premise_fof(text)
        target = fof_name if name is None else name
        validate_id(target)
        return cls(target, text, confidence, defeasible)


@dataclass(frozen=True, slots=True)
class Constraints:
    """What the beliefs must be consistent with.

    Attributes:
        rules: Implication-style rules. All of them constrain; the defeasible ones
            are additionally revision candidates.
        hard_axioms: Inviolable TPTP axioms -- exclusion links, EUF assignment
            rules, sentinel disequalities, equality links.
            They join the consistency check and are never revision candidates.
        functional_predicates: Predicates whose final argument is a *value*, so a
            newer claim supersedes the older one it excludes rather than
            contradicting it (recency supersession). Only consulted for
            ``escalated``.
    """

    rules: tuple[Rule, ...] = ()
    hard_axioms: tuple[str, ...] = ()
    functional_predicates: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class GovernanceOutcome:
    """What governance decided, as ledger operations.

    Attributes:
        consistent: Whether the beliefs are consistent under the constraints.
            ``True`` is a SAT certificate; ``False`` denotes a known conflict
            or recency supersession. ``None`` means the solver was inconclusive,
            so no consistency certificate or operation is available.
        ops: The operations governance performs, in the order it performs them.
            Empty when consistent or inconclusive, and also when a conflict is real but nothing is
            revisable -- the correct detect-but-hold-silently outcome.
        hold: The pair a ``hold`` names, carrying what an answer would ground.
            ``None`` unless the operations contain a ``hold``.
        undecided: A conflict was found and no operation was decided at all --
            neither a retraction nor a hold. Distinct from a hold: this is the
            pile-up that no single question can settle (arity gate), and
            a host that reports "asked" for it would be lying about its own state.
    """

    consistent: bool | None
    ops: tuple[LedgerOp, ...] = ()
    hold: ContradictionTie | None = None
    undecided: bool = False

    @property
    def retraction(self) -> LedgerOp | None:
        """The operation that withdrew something, or ``None`` if nothing was withdrawn."""
        return next((op for op in self.ops if op.op in {"retract", "supersede"}), None)


@dataclass(frozen=True, slots=True)
class _Theory:
    """The parsed constraint set, and the rule objects aligned with their exprs."""

    active: list[Expr]
    defeasible: list[tuple[Rule, Expr]] = field(default_factory=list)


def govern(
    beliefs: Sequence[Belief],
    constraints: Constraints,
    *,
    escalated: str | None = None,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> GovernanceOutcome:
    """Decide what the governance layer does with these beliefs.

    Args:
        beliefs: The belief set to govern.
        constraints: The rules and inviolable axioms they live under.
        escalated: The belief ID whose assertion raised the conflict, when the host
            knows it. Only used for recency supersession: a newer functional claim
            supersedes the older one it excludes, whatever their confidences, because
            a state change is not a miscalibration.
        max_rounds: E-matching round cap per solver check, including all candidate
            re-checks. ``None`` leaves rounds unbounded.
        max_matches: Candidate-binding cap across the rounds of each solver check.
            ``None`` leaves matching work unbounded. Both caps are renewed per
            check, not cumulative across governance, and are not wall-clock limits.

    Returns:
        The operations to perform, naming belief and rule IDs. A consistent
        belief set yields none. UNKNOWN yields none and sets ``consistent=None``.
        ``undecided`` is reserved for known conflicts without a selected operation.
        Duplicate IDs, belief/rule ID collisions and
        multiple IDs for one atom are refused rather than losing a core mapping.
    """
    held = _belief_map(beliefs)
    rule_ids = [rule.name for rule in constraints.rules]
    for rule_id in rule_ids:
        validate_id(rule_id)
    if len(set(rule_ids)) != len(rule_ids) or set(rule_ids) & held.keys():
        msg = "Rule IDs must be unique and distinct from belief IDs"
        raise InvalidArgumentError(msg)
    if escalated is not None and escalated not in held:
        msg = f"Escalated belief ID not found: {escalated!r}"
        raise InvalidArgumentError(msg)
    theory = _theory(constraints)

    superseded = _supersede(held, escalated, constraints.functional_predicates)
    if superseded is not None:
        return GovernanceOutcome(consistent=False, ops=(superseded,))

    verdict, unsat_core, expr_to_node_id = check_consistency(
        held, theory.active, max_rounds=max_rounds, max_matches=max_matches
    )
    if verdict == "UNKNOWN":
        return GovernanceOutcome(consistent=None)
    if verdict == "SAT":
        return GovernanceOutcome(consistent=True)

    return _resolve(held, theory, unsat_core, expr_to_node_id, max_rounds=max_rounds, max_matches=max_matches)


def _resolve(  # noqa: PLR0913 - conflict description plus the two solver caps
    beliefs: dict[str, dict[str, Any]],
    theory: _Theory,
    unsat_core: list[Expr],
    expr_to_node_id: dict[str, str],
    *,
    max_rounds: int | None,
    max_matches: int | None,
) -> GovernanceOutcome:
    """Pick what to give up.

    The order is the load-bearing part: the verified fact target first, then the
    defeasible rules that could be the culprit instead, then one choice between
    them by confidence with the tie broken toward the more local fact revision.
    Only when that choice cannot be made is the pair tested for being a *tie* --
    an independent judgement rather than something read off the absent decision,
    because revision also gives up in cases that are not ties at all (a conflict
    among rule instances names no belief to ask about).
    """
    fact_target = select_verified_revision_target(
        unsat_core,
        beliefs,
        expr_to_node_id,
        theory.active,
        max_rounds=max_rounds,
        max_matches=max_matches,
    )
    rule_culprits = _rule_culprits(beliefs, theory, max_rounds=max_rounds, max_matches=max_matches)

    fact_confidence = fact_target[1].get("confidence", 1.0) if fact_target is not None else None
    decision = choose_revision_candidate(fact_confidence, [rule.confidence for rule in rule_culprits])

    if decision is None:
        tie = select_tie_question_target(
            unsat_core,
            beliefs,
            expr_to_node_id,
            theory.active,
            max_rounds=max_rounds,
            max_matches=max_matches,
        )
        if tie is None:
            # Real conflict, nothing revisable and no answerable pair: governance
            # holds its peace rather than inventing an operation.
            return GovernanceOutcome(consistent=False, undecided=True)
        return GovernanceOutcome(
            consistent=False,
            ops=(LedgerOp(op="hold", target=tie.node_a, partner=tie.node_b, actor=GOVERNANCE_ACTOR),),
            hold=tie,
        )

    if decision.kind == "rule" and decision.rule_index is not None:
        rule = rule_culprits[decision.rule_index]
        return GovernanceOutcome(
            consistent=False,
            ops=(
                LedgerOp(
                    op="retract",
                    target=rule.name,
                    target_kind="rule",
                    actor=GOVERNANCE_ACTOR,
                    truth_value=True,
                    confidence=RETRACTED_RULE_CONFIDENCE,
                ),
            ),
        )

    if fact_target is None:
        return GovernanceOutcome(consistent=False, undecided=True)

    node_id, data = fact_target
    flipped = not data.get("truth_value", True)
    ops = [
        LedgerOp(op="retract", target=node_id, actor=GOVERNANCE_ACTOR, truth_value=flipped),
        # The conflict named a set of beliefs and one of them was flipped; the rest
        # were weighed against it and survived, which is evidence for them and costs
        # nothing since the core is already in hand.
        *_corroborate_survivors(unsat_core, expr_to_node_id, revised=node_id),
    ]
    return GovernanceOutcome(consistent=False, ops=tuple(ops))


def _rule_culprits(
    beliefs: dict[str, dict[str, Any]],
    theory: _Theory,
    *,
    max_rounds: int | None,
    max_matches: int | None,
) -> list[Rule]:
    """Find the defeasible rules whose removal alone would restore consistency.

    ``find_rule_culprits`` answers in exprs, so the rules are recovered by object
    identity -- two rules can render to equal exprs and only identity keeps the
    confidence and the name attached to the right one.
    """
    if not theory.defeasible:
        return []
    culprit_ids = {
        id(expr)
        for expr in find_rule_culprits(
            beliefs,
            theory.active,
            [expr for _rule, expr in theory.defeasible],
            max_rounds=max_rounds,
            max_matches=max_matches,
        )
    }
    return [rule for rule, expr in theory.defeasible if id(expr) in culprit_ids]


def _corroborate_survivors(
    unsat_core: list[Expr],
    expr_to_node_id: dict[str, str],
    *,
    revised: str,
) -> list[LedgerOp]:
    """Book a ``confirm`` for every belief the conflict suspected and kept."""
    survivors = []
    for core_expr in unsat_core:
        node_id = expr_to_node_id.get(str(core_expr))
        if node_id is not None and node_id != revised:
            survivors.append(LedgerOp(op="confirm", target=node_id, actor=GOVERNANCE_ACTOR))
    return survivors


def _supersede(
    beliefs: dict[str, dict[str, Any]],
    escalated: str | None,
    functional_predicates: Collection[str],
) -> LedgerOp | None:
    """Retire the older claim a newer functional one displaces.

    Checked before consistency: functional exclusion says the world moved, so the
    older belief was right when it was written and keeps its confidence. That is
    what makes supersession the one path able to resolve two inviolable beliefs --
    the confidence policy never applies.
    """
    if escalated is None or not functional_predicates:
        return None
    partner = functional_exclusion_partner(escalated, beliefs, functional_predicates)
    if partner is None:
        return None
    node_id, data = partner
    return LedgerOp(
        op="supersede",
        target=node_id,
        actor=GOVERNANCE_ACTOR,
        truth_value=not data.get("truth_value", True),
        confidence=data.get("confidence", 1.0),
    )


def _belief_map(beliefs: Sequence[Belief]) -> dict[str, dict[str, Any]]:
    """Build the node-id -> data mapping the governance logic reads.

    Atom and stance are explicit fields; writer roles are not interpreted.
    """
    held: dict[str, dict[str, Any]] = {}
    owners: dict[str, str] = {}
    for belief in beliefs:
        validate_id(belief.id)
        if belief.id in held:
            msg = f"Duplicate belief ID: {belief.id!r}"
            raise InvalidArgumentError(msg)
        expression = belief.atom
        key = str(parse_fact_to_expr(expression))
        if key in owners:
            msg = f"Atom {expression!r} has multiple belief IDs"
            raise InvalidArgumentError(msg)
        owners[key] = belief.id
        data: dict[str, Any] = {
            "truth_value": belief.truth_value,
            "confidence": belief.confidence,
            "stance": belief.stance,
            "source": belief.source,
            "node_type": "atom",
        }
        data["atom"] = belief.atom
        held[belief.id] = data
    return held


def _theory(constraints: Constraints) -> _Theory:
    """Parse the constraint set, keeping each defeasible rule beside its expr.

    Rules first, then the hard axioms: the same order the callers assembled by
    hand, kept because the solver's UNSAT core is a set of these exprs and the
    order it reports them in is what the downstream selectors iterate.
    """
    rule_exprs = [(rule, parse_premise_fof(rule.axiom)[2]) for rule in constraints.rules]
    hard_exprs = [parse_premise_fof(axiom)[2] for axiom in constraints.hard_axioms]
    return _Theory(
        active=[expr for _rule, expr in rule_exprs] + hard_exprs,
        defeasible=[(rule, expr) for rule, expr in rule_exprs if rule.defeasible],
    )


__all__ = [
    "GOVERNANCE_ACTOR",
    "RETRACTED_RULE_CONFIDENCE",
    "Belief",
    "Constraints",
    "ContradictionTie",
    "GovernanceOutcome",
    "Rule",
    "govern",
]
