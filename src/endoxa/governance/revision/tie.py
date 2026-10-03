"""Contradiction ties that no revision can settle, turned into a question.

The exclusion and implication tiers resolve every contradiction the solver can
decide. What they deliberately leave alone is the *tie*: two beliefs of equal
standing whose conflict has no cheaper side. The settled answer there is to hold
both rather than retract one arbitrarily -- picking a side between two equally
certain claims would be arbitrariness, not calibration.

Holding both is right; staying silent about it is not. Before this module a tie
surfaced only as a warning on the host's side: something to read afterwards
rather than something a caller could act on. This module decides when a tie is
well-formed enough to ask the user about, and what each answer would have to
ground for the answer to actually settle it.

Scope: **any pair the revision preference cannot separate** -- two beliefs
sharing a preference band (:mod:`.preference`). An earlier form of this gate had
only the 1.0 case to generalise from and was written as "both inviolable"; 1.0 is
now one band among others. What that newly admits is every *fallible*
equal-confidence pair, and where the confidence stamped on user testimony is a
constant, that means every clash between two things the user said.

Pure: stdlib and this package's own revision logic only.
"""

from dataclasses import dataclass
from typing import Any

from endoxa.governance.metadata import atom_text
from endoxa.governance.revision.engine import _fact_argument_terms, check_consistency
from endoxa.governance.revision.links import PredicateConstraints, predicate_clauses
from endoxa.governance.revision.preference import is_unsettleable_pair
from endoxa.solver import Expr

# A tie is a *pair*: exactly two held beliefs named by the conflict. Three or
# more (a functional-exclusion pile-up) cannot be settled by one
# yes/no question, and this gate is what keeps a question from being asked
# about them -- the question-side counterpart of "each contradiction is
# resolved on its own beat".
_TIE_ARITY = 2


@dataclass(frozen=True, slots=True)
class ContradictionTie:
    """A two-way contradiction the TMS cannot settle, and what an answer would ground.

    ``node_a`` is the atom the question is asked about, always in the positive
    ("is it true?"). Which of the pair that is comes from lexicographic order of
    the node ids, not from the UNSAT core order -- the core order is
    solver-dependent, and letting it choose would make the question's identity
    (and hence its de-duplication key) wobble from beat to beat.

    Attributes:
        node_a: ID of the belief asked about, in the positive. Resolve its
            atom from the input snapshot when presenting the question.
        truth_a: The truth value ``node_a`` is currently held at.
        node_b: The other atom in the conflict.
        truth_b: The truth value ``node_b`` is currently held at.
        affirm_true: Belief IDs to ground **True** on affirmation (False on denial).
        affirm_false: Belief IDs to ground **False** on affirmation (True on denial).
    """

    node_a: str
    truth_a: bool
    node_b: str
    truth_b: bool
    affirm_true: tuple[str, ...]
    affirm_false: tuple[str, ...]


def _held_conflict_beliefs(
    unsat_core: list[Expr],
    beliefs: dict[str, dict[str, Any]],
    expr_to_node_id: dict[str, str],
) -> list[tuple[str, dict[str, Any]]]:
    """Recover the held beliefs an UNSAT core names, in first-seen order.

    Mirrors the recovery loop in
    :func:`~endoxa.governance.revision.engine.select_verified_revision_target`;
    a core expression that maps to no live belief (a rule instance, a paged-out
    atom) simply contributes nothing.
    """
    found: dict[str, dict[str, Any]] = {}
    for core_expr in unsat_core:
        node_id = expr_to_node_id.get(str(core_expr))
        if node_id and node_id in beliefs:
            found.setdefault(node_id, beliefs[node_id])
    return list(found.items())


def _settlement(tie_nodes: list[tuple[str, dict[str, Any]]]) -> tuple[str, bool, str, bool]:
    """Order the pair and read off the two truth values (``node_a`` first)."""
    (node_a, data_a), (node_b, data_b) = sorted(tie_nodes, key=lambda n: n[0])
    return node_a, bool(data_a.get("truth_value", True)), node_b, bool(data_b.get("truth_value", True))


def _completion(
    cluster: dict[str, dict[str, Any]],
    pair: tuple[str, str],
    targets: tuple[bool, bool],
) -> dict[str, dict[str, Any]]:
    """Build the sub-theory as it would stand after one of the two answers."""
    node_a, node_b = pair
    a_target, b_target = targets
    return {
        **cluster,
        node_a: {**cluster[node_a], "truth_value": a_target},
        node_b: {**cluster[node_b], "truth_value": b_target},
    }


# PLR0913: six arguments, four of them the conflict description the solver just
# produced -- the same shape (and the same reason) as select_verified_revision_target.
def select_tie_question_target(  # noqa: PLR0913
    unsat_core: list[Expr],
    beliefs: dict[str, dict[str, Any]],
    expr_to_node_id: dict[str, str],
    rule_exprs: list[Expr],
    *,
    max_rounds: int | None = None,
    max_matches: int | None = None,
    links: PredicateConstraints | None = None,
) -> ContradictionTie | None:
    """Decide whether a contradiction is a tie worth asking the user about.

    Called where revision gave up: every fact, link and rule candidate was
    exhausted without a target. That branch covers more than ties (a conflict
    among rule instances alone names no belief at all), so the tie test is made
    here rather than read off the absent decision.

    Three conditions, in order:

    1. The core names **exactly two** held beliefs. Zero means there
       is nobody to ask about; three or more is a pile-up that one yes/no cannot
       settle.
    2. **The preference cannot separate them**: they share a band,
       and they are not hypotheses. An unequal pair got settled by revision and
       never reaches here.
    3. **Both completions are SAT.** The affirmative answer and the negative
       answer each have to actually restore consistency. Asking a question whose
       answer leaves the contradiction standing spends the user's time and comes
       straight back on the next beat; this is the same discipline the verified
       revision target applies to a flip, moved in front of the question.

    The sub-theory both completions are checked against is built exactly as
    :func:`~endoxa.governance.revision.engine.select_verified_revision_target`
    builds it: every belief sharing an individual with a core atom, plus the core
    atoms themselves. Link clauses are re-synthesised per trial so the
    check sees the same constraints the detection did.

    Condition 3 restates, from the answer's side, what the revision selector
    already found from the flip's side: ``node_a`` flipping to SAT and the "no"
    completion being SAT are the same fact. So a pair that selector declined as
    unsettleable always passes here, and a pair where only one flip settles never
    arrives. Checking it twice is not redundancy but a wedge: if either
    side is ever changed alone, the correspondence breaks where a test can see it.

    Args:
        unsat_core: The conflicting expressions the solver returned.
        beliefs: The full belief snapshot (node ID -> data).
        expr_to_node_id: Mapping produced by ``build_assumptions``.
        rule_exprs: The active rule expressions (hard constraints for the re-check).
        max_rounds: Optional E-matching round cap; an ``"UNKNOWN"`` re-check is
            treated conservatively as not settling the tie, so no question is asked.
        max_matches: Optional candidate-binding cap per solver check, across its rounds.
            Both limits are renewed for each completion, not shared across the search.
        links: The link sources whose ground clauses constrain the re-check.

    Returns:
        The :class:`ContradictionTie` to ask about, or None when the conflict is
        not a well-formed, answerable tie.
    """
    tie_nodes = _held_conflict_beliefs(unsat_core, beliefs, expr_to_node_id)
    if len(tie_nodes) != _TIE_ARITY:
        return None
    if not is_unsettleable_pair(tie_nodes[0][1], tie_nodes[1][1]):
        return None

    node_a, truth_a, node_b, truth_b = _settlement(tie_nodes)

    # The question is always asked about node_a in the positive, so "yes" means
    # node_a is true. What that makes node_b depends only on whether the two are
    # currently held at the same truth value: if they are, the conflict is
    # between the claims themselves and one must give; if they are not, the
    # conflict is between a claim and a *denial*, and affirming one affirms the
    # other (has the four-row check).
    b_on_affirm = truth_a != truth_b

    core_terms: frozenset[str] = frozenset().union(
        *(_fact_argument_terms(atom_text(nid, data)) for nid, data in tie_nodes)
    )
    cluster: dict[str, dict[str, Any]] = {
        nid: data for nid, data in beliefs.items() if core_terms & _fact_argument_terms(atom_text(nid, data))
    }
    for nid, data in tie_nodes:
        cluster.setdefault(nid, data)

    for targets in ((True, b_on_affirm), (False, not b_on_affirm)):
        completion = _completion(cluster, (node_a, node_b), targets)
        clauses = predicate_clauses(completion, links)
        result, _, _ = check_consistency(
            completion, [*rule_exprs, *clauses], max_rounds=max_rounds, max_matches=max_matches
        )
        if result != "SAT":
            return None

    affirm_true = (node_a, node_b) if b_on_affirm else (node_a,)
    affirm_false = () if b_on_affirm else (node_b,)
    return ContradictionTie(
        node_a=node_a,
        truth_a=truth_a,
        node_b=node_b,
        truth_b=truth_b,
        affirm_true=affirm_true,
        affirm_false=affirm_false,
    )


__all__ = ["ContradictionTie", "select_tie_question_target"]
