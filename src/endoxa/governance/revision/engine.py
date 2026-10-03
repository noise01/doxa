"""Revision queries with optional per-check E-matching limits.

Round and candidate-binding limits are renewed for each solver check, including
candidate re-checks. They are not a cumulative search budget or a wall-clock limit.
``None`` leaves the corresponding dimension unbounded. Inconclusive checks never
certify a candidate as restoring consistency.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from endoxa.errors import InvalidArgumentError
from endoxa.governance.metadata import atom_text, canonical_atom, validate_atom_ids, validate_id
from endoxa.governance.query import EntailmentResult, check_entailment
from endoxa.governance.revision.facts import parse_fact_to_expr
from endoxa.governance.revision.links import PredicateConstraints, PredicateLink, predicate_clauses
from endoxa.governance.revision.preference import is_hypothesis, preference_bands, revision_candidates
from endoxa.solver import Expr, Not, Solver

# Argument terms of a ground fact string, e.g. "r(a, b)" -> ("a", "b"). A
# propositional atom (no parentheses) yields no terms.
_FACT_ARGS_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*\((.*)\)$")

# Tie-break ranks for equal-confidence revision candidates, ordered by how much
# they generalize: a fact (rank 0, implicit) binds one individual, an acquired
# link binds two predicates over all individuals, a learned rule can state any
# formula. The most local revision wins a tie.
_LINK_TIE_RANK = 1
_RULE_TIE_RANK = 2

# Two candidates of equal standing both settling the conflict is where the
# preference runs out. One is a decision; two is a tie.
_UNSETTLEABLE_ARITY = 2


def build_assumptions(beliefs: dict[str, dict[str, Any]]) -> tuple[list[Expr], dict[str, str]]:
    """Build the solver assumption list and a stringified-expression -> node-id mapping.

    Every row requires an explicit flat ground atom. Malformed atoms, missing
    atoms and duplicate ownership are refused rather than skipped. The mapping
    translates an UNSAT core back to IDs without interpreting IDs as formulas.

    Args:
        beliefs: Mapping of belief node ID to its data (``truth_value``, ``role``, ``confidence``).

    Returns:
        A tuple of (assumption expressions, expression-string -> node-id mapping).
    """
    validate_atom_ids(beliefs)
    assumptions: list[Expr] = []
    expr_to_node_id: dict[str, str] = {}

    for node_id, data in beliefs.items():
        expr = parse_fact_to_expr(atom_text(node_id, data))

        truth_val = data.get("truth_value", True)
        ass_expr = expr if truth_val else Not(expr)

        assumptions.append(ass_expr)
        expr_to_node_id[str(ass_expr)] = node_id

    return assumptions, expr_to_node_id


def check_consistency(
    beliefs: dict[str, dict[str, Any]],
    rule_exprs: list[Expr],
    *,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> tuple[Literal["SAT", "UNSAT", "UNKNOWN"], list[Expr], dict[str, str]]:
    """Run an SMT consistency check of the belief atoms under the given rules.

    Pure (no events, no mutation): builds a fresh solver from ``rule_exprs`` as
    hard constraints plus the belief atoms as assumptions, so callers can probe
    different rule subsets (e.g. for rule-culprit search) over the same beliefs.

    Args:
        beliefs: Mapping of belief node ID to its data.
        rule_exprs: The rule expressions to assert as hard constraints.
        max_rounds: Optional cap on E-matching rounds. When exceeded the result
            is ``"UNKNOWN"`` (deliberation cut before converging). ``None`` leaves
            the check unbounded.
        max_matches: Optional candidate-binding cap per solver check, across its rounds.

    Returns:
        A tuple of (result, unsat_core, expr_to_node_id). The unsat_core is
        empty unless the result is ``"UNSAT"``.
    """
    solver = Solver()
    for expr in rule_exprs:
        solver.add(expr)
    assumptions, expr_to_node_id = build_assumptions(beliefs)
    result = solver.check(*assumptions, max_rounds=max_rounds, max_matches=max_matches)
    unsat_core = solver.unsat_core() if result == "UNSAT" else []
    return result, unsat_core, expr_to_node_id


def check_atom_support(
    beliefs: dict[str, dict[str, Any]],
    rule_exprs: list[Expr],
    atom: str,
    *,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> EntailmentResult:
    """Check independent support for an atom that need not already be held.

    Exclude the atom in both polarities, certify remaining premises as SAT,
    then query its positive form. Inconsistent or inconclusive premises are
    never evidence. Invalid inputs raise errors rather than returning UNKNOWN.
    """
    target = parse_fact_to_expr(canonical_atom(atom))
    # A support query has no core-to-ID attribution: multiple observations of
    # one atom are valid, and all polarities of the queried atom are excluded.
    assumptions = []
    for node_id, data in beliefs.items():
        validate_id(node_id)
        truth_value = data.get("truth_value", True)
        if not isinstance(truth_value, bool):
            msg = f"Belief truth_value must be a bool: {node_id!r}"
            raise InvalidArgumentError(msg)
        expr = parse_fact_to_expr(atom_text(node_id, data))
        assumptions.append(expr if truth_value else Not(expr))
    excluded = {str(target), str(Not(target))}
    remaining = [expr for expr in assumptions if str(expr) not in excluded]
    return check_entailment([*rule_exprs, *remaining], target, max_rounds=max_rounds, max_matches=max_matches)


def find_rule_culprits(  # noqa: PLR0913 - preserve existing inputs plus the two solver caps
    beliefs: dict[str, dict[str, Any]],
    active_rule_exprs: list[Expr],
    defeasible_rule_exprs: list[Expr],
    links: PredicateConstraints | None = None,
    *,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> list[Expr]:
    """Find defeasible rules whose removal alone restores consistency.

    For each defeasible (learned) rule, re-checks consistency with just that
    rule dropped from the active set. A rule whose removal flips UNSAT to SAT is
    a culprit (single-fault assumption). This sidesteps the SMT engine's
    inability to surface quantified rules in the unsat core, since E-matched
    ground instances are asserted as hard clauses.

    The link-derived ground clauses stay asserted throughout.
    Without them a purely link-derived contradiction -- an exclusion or
    implication clash no rule participates in -- leaves the reduced theory SAT for
    *every* defeasible rule, so all of them are reported as culprits and
    :func:`choose_revision_candidate` may retract an innocent low-confidence rule
    instead of revising the belief actually in conflict. With the clauses asserted,
    such a contradiction yields no culprit and the revision falls to the fact path.

    Args:
        beliefs: Mapping of belief node ID to its data.
        active_rule_exprs: All currently active rule expressions (base + learned).
        defeasible_rule_exprs: The subset of active rules eligible for retraction.
        links: The link sources whose ground clauses constrain the
            re-check. ``None`` (the default) re-checks without them.
        max_rounds: Optional E-matching round cap per solver check.
        max_matches: Optional candidate-binding cap per solver check, across its rounds.

    Returns:
        The defeasible rule expressions whose removal restores SAT.
    """
    link_exprs = predicate_clauses(beliefs, links)
    culprits: list[Expr] = []
    for rule in defeasible_rule_exprs:
        reduced = [r for r in active_rule_exprs if r is not rule]
        result, _, _ = check_consistency(
            beliefs, [*reduced, *link_exprs], max_rounds=max_rounds, max_matches=max_matches
        )
        if result == "SAT":
            culprits.append(rule)
    return culprits


def find_supporting_rules(  # noqa: PLR0913 - preserve existing inputs plus the two solver caps
    beliefs: dict[str, dict[str, Any]],
    active_rule_exprs: list[Expr],
    defeasible_rule_exprs: list[Expr],
    target: str,
    *,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> list[Expr]:
    """Find defeasible rules ``target`` cannot be derived without.

    The mirror image of :func:`find_rule_culprits`, written the same way and for
    the same reason: the SMT engine cannot surface quantified rules in an unsat
    core (E-matched instances are asserted as hard clauses), so which
    rules a derivation used has to be recovered by leave-one-out. There, dropping
    a rule that flips UNSAT to SAT identifies a culprit; here, dropping a rule
    that flips ENTAILED to NOT_ENTAILED identifies a support.

    A rule is recorded only when it is *individually necessary*. If the target
    survives the loss of every single rule --- because two rules derive it
    independently --- the list comes back empty, and no later retraction will
    count as counter-evidence against the belief. That is the intended reading:
    losing one of two sufficient supports is not the loss of the belief's
    footing: the line is drawn at support *disappearing* rather than weakening.
    The bias is toward recording nothing.

    ``UNKNOWN`` (the deliberation budget ran out) never yields an edge either,
    whether it is the standing verdict or a re-check: a question that was not
    answered must not decide which beliefs stay revisable later. Verification
    itself takes the same conservative reading.

    Pure (no events, no mutation), like every function in this module.

    Args:
        beliefs: Mapping of belief node ID to its data.
        active_rule_exprs: All currently active rule expressions (base + learned).
        defeasible_rule_exprs: The subset eligible to be recorded as supports ---
            non-defeasible base axioms are excluded because an edge to a rule
            that can never be retracted could never fire.
        target: The entailed atom whose supports are sought, as a fact string.
        max_rounds: Optional E-matching round cap per solver check.
        max_matches: Optional candidate-binding cap per solver check, across its rounds.

    Returns:
        The defeasible rule expressions whose removal costs the entailment.
    """
    # Leave-one-out only means anything against a standing entailment: without
    # this guard an underivable target would report every rule as a support,
    # since dropping any of them leaves it just as underivable. An inconclusive
    # verdict stops here too, for the reason above.
    if (
        check_atom_support(beliefs, active_rule_exprs, target, max_rounds=max_rounds, max_matches=max_matches).verdict
        != "ENTAILED"
    ):
        return []
    supports: list[Expr] = []
    for rule in defeasible_rule_exprs:
        reduced = [r for r in active_rule_exprs if r is not rule]
        if (
            check_atom_support(beliefs, reduced, target, max_rounds=max_rounds, max_matches=max_matches).verdict
            == "NOT_ENTAILED"
        ):
            supports.append(rule)
    return supports


def find_link_culprits(
    beliefs: dict[str, dict[str, Any]],
    active_rule_exprs: list[Expr],
    links: PredicateConstraints | None = None,
    *,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> list[PredicateLink]:
    """Find acquired links whose retraction alone restores consistency.

    The link-level twin of :func:`find_rule_culprits`. For each link in the
    constraint set, the clauses are **re-synthesised** with just that link dropped
    -- the clause set is always derived from the constraints, never carried around
    -- and consistency is re-checked. A link whose removal flips UNSAT to SAT is a
    culprit under the same single-fault assumption the rule search uses.

    This is what lets a wrong link die. Without it, every contradiction a mistaken
    acquired link creates is resolved by retracting a *belief*: whatever proposed
    the link is never blamed, and its error is transcribed into the belief set
    instead.

    ``functional_predicates`` is not a candidate: it is a declared bootstrap rather
    than acquired data, and its clashes are resolved by recency supersession before
    this point. A contradiction no link participates in yields no culprit, so the
    revision falls through to the fact/rule paths unchanged.

    Args:
        beliefs: Mapping of belief node ID to its data.
        active_rule_exprs: All currently active rule expressions (base + learned),
            asserted throughout so a rule-driven contradiction is not blamed on a link.
        links: The link sources. ``None`` (the default) yields no candidates,
            which is the baseline before any link is populated.
        max_rounds: Optional E-matching round cap per solver check.
        max_matches: Optional candidate-binding cap per solver check, across its rounds.

    Returns:
        The links whose removal restores SAT, in the deterministic order of
        :meth:`PredicateConstraints.revision_candidates`.
    """
    if links is None or links.is_empty():
        return []
    culprits: list[PredicateLink] = []
    for link in links.revision_candidates():
        reduced_clauses = predicate_clauses(beliefs, links.without(link))
        result, _, _ = check_consistency(
            beliefs, [*active_rule_exprs, *reduced_clauses], max_rounds=max_rounds, max_matches=max_matches
        )
        if result == "SAT":
            culprits.append(link)
    return culprits


def select_revision_target(
    unsat_core: list[Expr],
    beliefs: dict[str, dict[str, Any]],
    expr_to_node_id: dict[str, str],
) -> tuple[str, dict[str, Any]] | None:
    """Select which conflicting belief to revise, following Truth Maintenance System policy.

    Prefers the lowest-confidence hypothesis in the UNSAT core; otherwise falls back to the
    lowest-confidence *fallible* belief -- one whose confidence is below 1.0. A confidence of
    1.0 marks an inviolable belief -- in practice only an answer the user was asked
    for directly is written at 1.0; everything else, including user testimony
    stamped with the confidence a host gives its interlocutor, is revisable. A
    belief carrying no explicit confidence defaults to 1.0 and so stays
    inviolable -- revision fails safe toward not touching an unmarked belief. Returns None when
    nothing may be revised.

    Args:
        unsat_core: The conflicting expressions returned by the solver.
        beliefs: Mapping of belief node ID to its data.
        expr_to_node_id: Mapping produced by :func:`build_assumptions`.

    Returns:
        The (node_id, data) of the belief to revise, or None if no fallible belief exists.
    """
    conflict_nodes: list[tuple[str, dict[str, Any]]] = []
    for core_expr in unsat_core:
        node_id = expr_to_node_id.get(str(core_expr))
        if node_id and node_id in beliefs:
            conflict_nodes.append((node_id, beliefs[node_id]))

    hypotheses = [(nid, data) for nid, data in conflict_nodes if is_hypothesis(data)]
    if hypotheses:
        return min(hypotheses, key=lambda x: x[1].get("confidence", 1.0))

    fallible_nodes = [(nid, data) for nid, data in conflict_nodes if data.get("confidence", 1.0) < 1.0]
    if fallible_nodes:
        return min(fallible_nodes, key=lambda x: x[1].get("confidence", 1.0))

    return None


def _fact_argument_terms(fact_str: str) -> frozenset[str]:
    """Return the argument terms of a ground fact string.

    ``r(a, b)`` -> ``{"a", "b"}``; a propositional atom with no arguments yields
    the empty set. Used to cluster the beliefs that share an individual with a
    conflict, so a revision can be verified against just that conflict's
    sub-theory (see :func:`select_verified_revision_target`).
    """
    match = _FACT_ARGS_RE.match(fact_str.strip())
    if not match:
        return frozenset()
    return frozenset(arg.strip() for arg in match.group(1).split(",") if arg.strip())


# PLR0913: six arguments, four of them the conflict description the solver just
# produced (core, beliefs, mapping, rules). Bundling them into a context object would
# only move the same fields behind a name that has no other use.
def select_verified_revision_target(  # noqa: PLR0913
    unsat_core: list[Expr],
    beliefs: dict[str, dict[str, Any]],
    expr_to_node_id: dict[str, str],
    rule_exprs: list[Expr],
    *,
    max_rounds: int | None = None,
    max_matches: int | None = None,
    links: PredicateConstraints | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Select a conflicting belief whose truth-flip actually restores consistency.

    :func:`select_revision_target` picks the lowest-confidence fallible atom in the
    UNSAT core by TMS policy but never checks that flipping it resolves the clash.
    When a rule immediately re-derives that atom -- a consequent still forced by an
    asserted antecedent -- the flip is a no-op and the contradiction persists. Call
    that a *whiff*: the selector swings at the conflict and the conflict is still
    there. Whiffs become common as soon as exclusion links make independent
    contradictions common. This selector verifies each candidate, in the same
    preference order (hypotheses first, then lowest confidence), and returns the
    first whose flip genuinely restores satisfiability.

    The re-check is scoped to the conflict's *own* sub-theory: the beliefs that share
    an individual with a core atom (its argument terms), plus the core atoms
    themselves. A propositional theory decomposes by constant, so several
    independent contradictions can co-exist with no single global flip restoring full
    satisfiability; verifying against the whole belief set would then reject every
    per-constant fix. Scoping to the shared-individual cluster keeps the rule
    antecedents that could re-derive a flipped atom (so real whiffs are still caught)
    while excluding unrelated conflicts on other individuals (resolved on later
    beats). Equality-coupled individuals (EUF) pull each other into the
    cluster through the equality atoms the solver placed in the core.

    The re-check also asserts the link-derived ground clauses, *re-synthesized
    from each trial belief set* rather than reused from the detection pass:
    a flip can satisfy the clause that fired while creating a new clash, and only
    re-synthesis sees that. Because every synthesized clause is one the belief set
    currently violates, their count measures how much clash remains, which gives the
    fallback below its progress criterion.

    The search runs **band by band**. A band is a run of candidates the
    preference ranks identically, and every member of a band is checked before the
    band is judged -- no early return. One candidate settling the conflict wins
    outright, exactly as before. *Two or more* settling it means the preference has
    nothing left to say about which should go, and the function returns None rather
    than take whichever the UNSAT core happened to name first. Being unsettleable is
    a failure of the preference, not of the solver, so the tie question path
    (:mod:`endoxa.governance.revision.tie`) picks it up from there. A band where
    nothing settles falls through to the next one, so a whiffed low-confidence band
    still yields to a higher-confidence fix.

    When no band settles anything -- a functional-exclusion pile-up of three or more
    values leaves a clash behind whichever single atom is flipped -- the first
    candidate (in the same preference order) that *strictly reduces* the link
    clash count is taken instead. Tie detection is deliberately **not** applied to
    this fallback: returning None here would not raise a question either (a pile-up
    fails the tie path's pair gate) and would only cost the "each contradiction is
    resolved on its own beat" progress. The choice is still deterministic,
    because the candidate order is. A no-op flip never qualifies, so
    genuine whiffs are still rejected.

    Args:
        unsat_core: The conflicting expressions returned by the solver.
        beliefs: The full belief snapshot (node ID -> data), used to reconstruct the
            conflict's sub-theory.
        expr_to_node_id: Mapping produced by :func:`build_assumptions`.
        rule_exprs: The active rule expressions (hard constraints for the re-check).
        max_rounds: Optional E-matching round cap; an ``"UNKNOWN"`` re-check is
            treated conservatively as not resolving the conflict.
        max_matches: Optional candidate-binding cap per solver check, across its rounds.
        links: The link sources whose ground clauses constrain the
            re-check. ``None`` (the default) re-checks without them.

    Returns:
        The (node_id, data) of a fact whose flip restores consistency of its
        sub-theory (or, failing that, strictly reduces the link clash), chosen
        by TMS preference, or None when no single fact flip does, or when several
        equally-preferred ones do and the preference cannot choose between them.
    """
    conflict_nodes: list[tuple[str, dict[str, Any]]] = []
    for core_expr in unsat_core:
        node_id = expr_to_node_id.get(str(core_expr))
        if node_id and node_id in beliefs:
            conflict_nodes.append((node_id, beliefs[node_id]))

    candidates = revision_candidates(conflict_nodes)

    # Sub-theory to re-check against: every belief sharing an individual with a core
    # atom (this keeps re-derivers), plus the core atoms themselves (which covers a
    # propositional conflict, whose atoms share no term).
    core_terms: frozenset[str] = frozenset().union(
        *(_fact_argument_terms(atom_text(nid, data)) for nid, data in conflict_nodes)
    )
    cluster: dict[str, dict[str, Any]] = {
        nid: data for nid, data in beliefs.items() if core_terms & _fact_argument_terms(atom_text(nid, data))
    }
    for nid, data in conflict_nodes:
        cluster.setdefault(nid, data)

    # Clash count of the unflipped cluster: the fallback below requires a candidate to
    # strictly beat it.
    baseline_clashes = len(predicate_clauses(cluster, links))
    progress_target: tuple[str, dict[str, Any]] | None = None

    for band in preference_bands(candidates):
        settling: list[tuple[str, dict[str, Any]]] = []
        for node_id, data in band:
            flipped = {**data, "truth_value": not data.get("truth_value", True)}
            trial = {**cluster, node_id: flipped}
            trial_clauses = predicate_clauses(trial, links)
            result, _, _ = check_consistency(
                trial, [*rule_exprs, *trial_clauses], max_rounds=max_rounds, max_matches=max_matches
            )
            if result == "SAT":
                settling.append((node_id, data))
            elif result == "UNSAT" and progress_target is None and len(trial_clauses) < baseline_clashes:
                progress_target = (node_id, data)
        if len(settling) == 1:
            return settling[0]
        if len(settling) >= _UNSETTLEABLE_ARITY:
            return None
    return progress_target


@dataclass(frozen=True, slots=True)
class RevisionDecision:
    """Which target a contradiction should be resolved against.

    ``rule_index`` indexes into the ``rule_confidences`` sequence passed to
    :func:`choose_revision_candidate` (and thus the caller's parallel list of
    rule culprits); ``link_index`` does the same for ``link_confidences``. Each
    is ``None`` unless it is the chosen kind.
    """

    kind: Literal["fact", "rule", "link"]
    rule_index: int | None = None
    link_index: int | None = None


def choose_revision_candidate(
    fact_confidence: float | None,
    rule_confidences: Sequence[float],
    link_confidences: Sequence[float] = (),
) -> RevisionDecision | None:
    """Pick the lowest-confidence contradiction-revision target.

    Considers a fact-level target (a revisable belief atom), link-level targets
    (acquired links whose retraction restores consistency) and rule-level targets
    (defeasible learned rules). The lowest-confidence candidate wins.

    Ties break by **generality**, most local first: fact, then link, then rule. A
    link binds two predicates over every individual, so it is more general than a
    single belief; a learned rule can state an arbitrary formula, so it is more
    general than a link. The ordering is about blast radius, not about trust --
    where a link came from (a single upstream judgement) is if anything weaker
    than a rule whose confidence grew through use.

    Args:
        fact_confidence: Confidence of the fact revision target, or ``None`` when
            no revisable belief atom was found.
        rule_confidences: Confidences of the rule culprits, in caller order.
        link_confidences: Confidences of the link culprits, in caller order.

    Returns:
        The chosen :class:`RevisionDecision`, or ``None`` when nothing is
        available to revise.
    """
    # (confidence, tie_rank, index): lower confidence wins; on a tie the lower
    # tie_rank -- the more local revision -- is taken.
    candidates: list[tuple[float, int, int | None]] = []
    if fact_confidence is not None:
        candidates.append((fact_confidence, 0, None))
    candidates.extend((conf, _LINK_TIE_RANK, index) for index, conf in enumerate(link_confidences))
    candidates.extend((conf, _RULE_TIE_RANK, index) for index, conf in enumerate(rule_confidences))

    if not candidates:
        return None

    _conf, tie_rank, index = min(candidates, key=lambda c: (c[0], c[1]))
    if tie_rank == _RULE_TIE_RANK:
        return RevisionDecision(kind="rule", rule_index=index)
    if tie_rank == _LINK_TIE_RANK:
        return RevisionDecision(kind="link", link_index=index)
    return RevisionDecision(kind="fact")
