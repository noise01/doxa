from typing import Any

from endoxa.governance.revision import (
    RevisionDecision,
    choose_revision_candidate,
    parse_fact_to_expr,
    select_revision_target,
)


class TestChooseRevisionCandidate:
    def test_no_targets_returns_none(self) -> None:
        assert choose_revision_candidate(None, []) is None

    def test_only_fact_target(self) -> None:
        assert choose_revision_candidate(0.4, []) == RevisionDecision(kind="fact")

    def test_only_rule_targets_picks_lowest_confidence(self) -> None:
        # index 1 has the lowest confidence.
        assert choose_revision_candidate(None, [0.8, 0.3, 0.5]) == RevisionDecision(kind="rule", rule_index=1)

    def test_lower_confidence_rule_beats_fact(self) -> None:
        assert choose_revision_candidate(0.9, [0.2]) == RevisionDecision(kind="rule", rule_index=0)

    def test_lower_confidence_fact_beats_rule(self) -> None:
        assert choose_revision_candidate(0.2, [0.9]) == RevisionDecision(kind="fact")

    def test_tie_prefers_fact_over_rule(self) -> None:
        # Equal confidence: the more local fact revision wins the tie.
        assert choose_revision_candidate(0.5, [0.5]) == RevisionDecision(kind="fact")


class TestLinkCandidates:
    """Acquired links join the comparison, ranked between facts and rules."""

    def test_only_link_targets_picks_lowest_confidence(self) -> None:
        decision = choose_revision_candidate(None, [], [0.8, 0.3])
        assert decision == RevisionDecision(kind="link", link_index=1)

    def test_lower_confidence_link_beats_fact_and_rule(self) -> None:
        assert choose_revision_candidate(0.9, [0.8], [0.2]) == RevisionDecision(kind="link", link_index=0)

    def test_tie_prefers_fact_over_link(self) -> None:
        # A belief binds one individual; a link binds two predicates over all of
        # them, so the fact is the more local revision.
        assert choose_revision_candidate(0.5, [], [0.5]) == RevisionDecision(kind="fact")

    def test_tie_prefers_link_over_rule(self) -> None:
        # A link is bounded to one argument tuple's two predicates; a learned rule
        # can state any formula, so the link is the more local revision.
        assert choose_revision_candidate(None, [0.5], [0.5]) == RevisionDecision(kind="link", link_index=0)

    def test_full_tie_prefers_fact(self) -> None:
        assert choose_revision_candidate(0.5, [0.5], [0.5]) == RevisionDecision(kind="fact")

    def test_omitting_links_preserves_the_prior_behavior(self) -> None:
        # The default empty sequence keeps every existing call site identical.
        assert choose_revision_candidate(0.5, [0.4]) == RevisionDecision(kind="rule", rule_index=0)


def _core(*node_ids: str) -> tuple[list[Any], dict[str, str]]:
    """Build a (unsat_core, expr_to_node_id) pair for the given belief node ids.

    Mirrors build_assumptions: each node id is parsed to an Expr and its string
    form keys back to the node id, which is how select_revision_target resolves a
    core expression to the belief it must revise.
    """
    core: list[Any] = []
    expr_to_node_id: dict[str, str] = {}
    for nid in node_ids:
        expr = parse_fact_to_expr(nid)
        core.append(expr)
        expr_to_node_id[str(expr)] = nid
    return core, expr_to_node_id


class TestSelectRevisionTarget:
    """Fallibility is expressed by confidence < 1.0, not by role.

    User testimony carrying interlocutor confidence (0.95) is now revisable; only a
    confidence of 1.0 (ask-user grounding) or an unmarked belief stays
    inviolable.
    """

    def test_user_testimony_below_one_is_revisable(self) -> None:
        core, mapping = _core("mortal(socrates)")
        beliefs = {
            "mortal(socrates)": {
                "atom": "mortal(socrates)",
                "stance": "asserted",
                "confidence": 0.95,
                "truth_value": False,
            }
        }
        target = select_revision_target(core, beliefs, mapping)
        assert target is not None
        assert target[0] == "mortal(socrates)"

    def test_inviolable_user_belief_is_not_revisable(self) -> None:
        core, mapping = _core("mortal(socrates)")
        beliefs = {
            "mortal(socrates)": {
                "atom": "mortal(socrates)",
                "stance": "asserted",
                "confidence": 1.0,
                "truth_value": False,
            }
        }
        assert select_revision_target(core, beliefs, mapping) is None

    def test_unmarked_belief_defaults_to_inviolable(self) -> None:
        # No confidence key: fails safe toward 1.0, so nothing is revised.
        core, mapping = _core("mortal(socrates)")
        beliefs = {"mortal(socrates)": {"atom": "mortal(socrates)", "stance": "asserted", "truth_value": False}}
        assert select_revision_target(core, beliefs, mapping) is None

    def test_lowest_confidence_fallible_belief_wins(self) -> None:
        # A grounded observation (0.9) is peeled before user testimony (0.95).
        core, mapping = _core("human(socrates)", "mortal(socrates)")
        beliefs = {
            "human(socrates)": {
                "atom": "human(socrates)",
                "stance": "asserted",
                "confidence": 0.95,
                "truth_value": True,
            },
            "mortal(socrates)": {
                "atom": "mortal(socrates)",
                "stance": "asserted",
                "confidence": 0.9,
                "truth_value": False,
            },
        }
        target = select_revision_target(core, beliefs, mapping)
        assert target is not None
        assert target[0] == "mortal(socrates)"

    def test_hypothesis_is_preferred_over_lower_but_non_hypothesis(self) -> None:
        # The hypothesis branch fires first even against a lower-confidence belief.
        core, mapping = _core("human(socrates)", "mortal(socrates)")
        beliefs = {
            "human(socrates)": {
                "atom": "human(socrates)",
                "stance": "hypothesis",
                "confidence": 0.5,
                "truth_value": True,
            },
            "mortal(socrates)": {
                "atom": "mortal(socrates)",
                "stance": "asserted",
                "confidence": 0.95,
                "truth_value": False,
            },
        }
        target = select_revision_target(core, beliefs, mapping)
        assert target is not None
        assert target[0] == "human(socrates)"
