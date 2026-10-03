"""Tests for tie detection on unsettleable contradictions.

``select_tie_question_target`` runs where revision gave up. It has to say "yes,
this is a two-way tie between two inviolable beliefs, and here is what each
answer would ground" -- or say nothing, because every other shape of dead-end
(a pile-up, a conflict among rules, a belief that lost for some other reason)
must keep falling through to the existing warning log.

Like ``test_verified_revision.py`` these drive the real solver: rules come from
``parse_fof`` and cores from ``check_consistency``, so the SAT checks on the two
completions exercise genuine forward chaining rather than a hand-built core.
"""

from typing import Any

from endoxa.governance.revision import (
    PredicateConstraints,
    check_consistency,
    predicate_clauses,
    select_tie_question_target,
)
from endoxa.solver import Expr, parse_fof


def _rule(tptp: str) -> Expr:
    _name, _role, expr = parse_fof(tptp)
    return expr


def _core_for(beliefs: dict[str, dict[str, Any]], rule_exprs: list[Expr]) -> tuple[list[Expr], dict[str, str]]:
    """Run the real consistency check and return (unsat_core, expr_to_node_id)."""
    result, unsat_core, expr_to_node_id = check_consistency(beliefs, rule_exprs)
    assert result == "UNSAT", "test setup must be contradictory"
    return unsat_core, expr_to_node_id


def _user(*, truth_value: bool = True, confidence: float = 1.0) -> dict[str, Any]:
    return {"stance": "asserted", "confidence": confidence, "truth_value": truth_value}


# Two inviolable beliefs that cannot both hold: the canonical tie.
_EXCLUSION_RULE = _rule("fof(excl, axiom, ![X] : ~(alive(X) & dead(X))).")


def _exclusion_tie() -> dict[str, dict[str, Any]]:
    return {"alive(felix)": {"atom": "alive(felix)", **_user()}, "dead(felix)": {"atom": "dead(felix)", **_user()}}


class TestPairGate:
    """Only a conflict naming exactly two held beliefs is a question-worthy tie."""

    def test_two_inviolable_beliefs_are_a_tie(self) -> None:
        beliefs = _exclusion_tie()
        core, mapping = _core_for(beliefs, [_EXCLUSION_RULE])
        tie = select_tie_question_target(core, beliefs, mapping, [_EXCLUSION_RULE])
        assert tie is not None
        assert (tie.node_a, tie.node_b) == ("alive(felix)", "dead(felix)")
        assert tie.truth_a is True
        assert tie.truth_b is True

    def test_pile_up_of_three_is_not_asked_about(self) -> None:
        # Three co-held beliefs that are jointly, but not pairwise, impossible:
        # one yes/no cannot settle it, so the tie gate must decline.
        rules = [_rule("fof(triple, axiom, ![X] : ~(alive(X) & dead(X) & buried(X))).")]
        beliefs = {
            "alive(felix)": {"atom": "alive(felix)", **_user()},
            "dead(felix)": {"atom": "dead(felix)", **_user()},
            "buried(felix)": {"atom": "buried(felix)", **_user()},
        }
        core, mapping = _core_for(beliefs, rules)
        assert select_tie_question_target(core, beliefs, mapping, rules) is None

    def test_conflict_naming_one_belief_is_not_a_tie(self) -> None:
        # A rule that outright forbids the only asserted atom: nobody to weigh it
        # against, so there is no two-way question to ask.
        rules = [_rule("fof(no_ghosts, axiom, ~ghost(felix)).")]
        beliefs = {"ghost(felix)": {"atom": "ghost(felix)", **_user()}}
        core, mapping = _core_for(beliefs, rules)
        assert select_tie_question_target(core, beliefs, mapping, rules) is None


class TestPreferenceGate:
    """A tie is where the *preference* runs out, not where confidence hits 1.0.

    The gate asks whether the two beliefs share a preference band. Confidence 1.0
    is one band among others, so the case the older gate generalised from falls out
    rather than being its own rule -- and every fallible equal-confidence pair now
    comes in with it.
    """

    def test_unequal_confidence_pair_is_not_a_tie(self) -> None:
        # The preference separates these, so revision settles it and the conflict
        # never reaches the question path.
        beliefs = {
            "alive(felix)": {"atom": "alive(felix)", **_user()},
            "dead(felix)": {"atom": "dead(felix)", **_user(confidence=0.5)},
        }
        core, mapping = _core_for(beliefs, [_EXCLUSION_RULE])
        assert select_tie_question_target(core, beliefs, mapping, [_EXCLUSION_RULE]) is None

    def test_equal_confidence_fallible_pair_is_a_tie(self) -> None:
        # Two user assertions carry the same interlocutor
        # confidence, so nothing in the preference tells them apart.
        beliefs = {
            "alive(felix)": {"atom": "alive(felix)", **_user(confidence=0.95)},
            "dead(felix)": {"atom": "dead(felix)", **_user(confidence=0.95)},
        }
        core, mapping = _core_for(beliefs, [_EXCLUSION_RULE])
        tie = select_tie_question_target(core, beliefs, mapping, [_EXCLUSION_RULE])
        assert tie is not None
        assert (tie.node_a, tie.node_b) == ("alive(felix)", "dead(felix)")

    def test_hypothesis_pair_is_not_a_tie(self) -> None:
        # Intuition writes every conjecture at one constant confidence, so admitting
        # hypotheses would turn each clash between two of the system's own guesses
        # into a question. A conflict between conjectures wants evidence, not the
        # user's attention.
        beliefs = {
            "alive(felix)": {"atom": "alive(felix)", "stance": "hypothesis", "confidence": 0.5, "truth_value": True},
            "dead(felix)": {"atom": "dead(felix)", "stance": "hypothesis", "confidence": 0.5, "truth_value": True},
        }
        core, mapping = _core_for(beliefs, [_EXCLUSION_RULE])
        assert select_tie_question_target(core, beliefs, mapping, [_EXCLUSION_RULE]) is None

    def test_inviolable_hypothesis_is_not_a_tie(self) -> None:
        # This stops arriving here once the hypothesis branch reads the right key:
        # a hypothesis sits in its own band, so revision settles the pair rather
        # than declining it.
        beliefs = _exclusion_tie()
        beliefs["dead(felix)"] = {"atom": "dead(felix)", "stance": "hypothesis", "confidence": 1.0, "truth_value": True}
        core, mapping = _core_for(beliefs, [_EXCLUSION_RULE])
        assert select_tie_question_target(core, beliefs, mapping, [_EXCLUSION_RULE]) is None


class TestDeterminism:
    """The question's identity must not ride on solver-dependent core order."""

    def test_core_order_does_not_change_which_atom_is_asked_about(self) -> None:
        beliefs = _exclusion_tie()
        core, mapping = _core_for(beliefs, [_EXCLUSION_RULE])
        forward = select_tie_question_target(core, beliefs, mapping, [_EXCLUSION_RULE])
        reversed_ = select_tie_question_target(list(reversed(core)), beliefs, mapping, [_EXCLUSION_RULE])
        assert forward is not None
        assert reversed_ is not None
        assert forward == reversed_


class TestPolarity:
    """The four rows of the tie table, through the real solver."""

    def test_same_truth_value_splits_the_pair(self) -> None:
        # alive=T, dead=T -> "yes" keeps alive and denies dead.
        beliefs = _exclusion_tie()
        core, mapping = _core_for(beliefs, [_EXCLUSION_RULE])
        tie = select_tie_question_target(core, beliefs, mapping, [_EXCLUSION_RULE])
        assert tie is not None
        assert tie.affirm_true == ("alive(felix)",)
        assert tie.affirm_false == ("dead(felix)",)

    def test_same_truth_value_when_both_are_denied(self) -> None:
        # Both held false under a rule demanding one of them: still a split.
        rules = [_rule("fof(one_of, axiom, ![X] : (alive(X) | dead(X))).")]
        beliefs = {
            "alive(felix)": {"atom": "alive(felix)", **_user(truth_value=False)},
            "dead(felix)": {"atom": "dead(felix)", **_user(truth_value=False)},
        }
        core, mapping = _core_for(beliefs, rules)
        tie = select_tie_question_target(core, beliefs, mapping, rules)
        assert tie is not None
        assert tie.truth_a is False
        assert tie.affirm_true == ("alive(felix)",)
        assert tie.affirm_false == ("dead(felix)",)

    def test_opposite_truth_values_move_together(self) -> None:
        # animal(felix)=F, cat(felix)=T under cat => animal: the conflict is
        # between a claim and a denial, so affirming one affirms the other.
        rules = [_rule("fof(impl, axiom, ![X] : (cat(X) => animal(X))).")]
        beliefs = {
            "animal(felix)": {"atom": "animal(felix)", **_user(truth_value=False)},
            "cat(felix)": {"atom": "cat(felix)", **_user()},
        }
        core, mapping = _core_for(beliefs, rules)
        tie = select_tie_question_target(core, beliefs, mapping, rules)
        assert tie is not None
        assert (tie.node_a, tie.node_b) == ("animal(felix)", "cat(felix)")
        assert tie.affirm_true == ("animal(felix)", "cat(felix)")
        assert tie.affirm_false == ()


class TestBothCompletionsMustSettle:
    """A question is only worth asking if either answer restores consistency."""

    def test_declines_when_the_negative_answer_leaves_a_contradiction(self) -> None:
        # alive/dead exclude each other *and* a third rule forces alive(felix).
        # "yes" (alive) settles; "no" (dead) still clashes with the forcing rule,
        # so the question would half-whiff and must not be asked.
        rules = [
            _EXCLUSION_RULE,
            _rule("fof(forced, axiom, alive(felix))."),
        ]
        beliefs = _exclusion_tie()
        core, mapping = _core_for(beliefs, rules)
        assert select_tie_question_target(core, beliefs, mapping, rules) is None

    def test_declines_when_the_affirmative_answer_leaves_a_contradiction(self) -> None:
        rules = [
            _EXCLUSION_RULE,
            _rule("fof(forced, axiom, dead(felix))."),
        ]
        beliefs = _exclusion_tie()
        core, mapping = _core_for(beliefs, rules)
        assert select_tie_question_target(core, beliefs, mapping, rules) is None


class TestLinkDerivedTies:
    """A tie raised by acquired links, as a host produces it."""

    def test_inter_predicate_exclusion_tie(self) -> None:
        constraints = PredicateConstraints(exclusion_targets={"alive": ("dead",)})
        beliefs = _exclusion_tie()
        clauses = predicate_clauses(beliefs, constraints)
        core, mapping = _core_for(beliefs, clauses)
        tie = select_tie_question_target(core, beliefs, mapping, [], links=constraints)
        assert tie is not None
        assert tie.affirm_true == ("alive(felix)",)
        assert tie.affirm_false == ("dead(felix)",)

    def test_implication_tie(self) -> None:
        constraints = PredicateConstraints(implication_targets={"cat": ("animal",)})
        beliefs = {
            "animal(felix)": {"atom": "animal(felix)", **_user(truth_value=False)},
            "cat(felix)": {"atom": "cat(felix)", **_user()},
        }
        clauses = predicate_clauses(beliefs, constraints)
        core, mapping = _core_for(beliefs, clauses)
        tie = select_tie_question_target(core, beliefs, mapping, [], links=constraints)
        assert tie is not None
        assert tie.affirm_true == ("animal(felix)", "cat(felix)")
        assert tie.affirm_false == ()
