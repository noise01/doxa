"""Tests for the governance decision surface.

``govern`` is where an external host stops assembling the governance layer's parts and starts
being governed by it, so what is tested is that the *answers* are the operations the ledger
declares -- a retraction names what to withdraw, a hold names both sides -- and that the
preference is applied on the way there.

The wiring's agreement with production is pinned separately, against a live OS
(the equivalence tests): here the concern is the surface
itself, and these run with no beliefs, no DB and no LLM.
"""

from endoxa.governance import Belief, Constraints, Rule, govern

_EXCLUSION = "fof(excl, axiom, ![X] : ~(alive(X) & dead(X)))."
_IMPLICATION = "fof(impl, axiom, ![X] : (cat(X) => animal(X)))."


def _belief(target: str, *, truth: bool = True, confidence: float = 0.9, context: str = "user") -> Belief:
    return Belief(
        truth_value=truth,
        confidence=confidence,
        id=target,
        atom=target,
        stance=("hypothesis" if context == "hypothesis" else "asserted"),
    )


class TestConsistentBoards:
    def test_a_consistent_belief_set_yields_no_operations(self):
        outcome = govern([_belief("alive(felix)")], Constraints(hard_axioms=(_EXCLUSION,)))
        assert outcome.consistent is True
        assert outcome.ops == ()
        assert outcome.hold is None
        assert outcome.retraction is None

    def test_an_empty_belief_set_is_consistent(self):
        assert govern([], Constraints()).consistent is True


class TestRetractingABelief:
    def test_the_weaker_belief_is_the_one_withdrawn(self):
        outcome = govern(
            [_belief("alive(felix)", confidence=0.9), _belief("dead(felix)", confidence=0.6)],
            Constraints(hard_axioms=(_EXCLUSION,)),
        )
        assert outcome.consistent is False
        retraction = outcome.retraction
        assert retraction is not None
        assert retraction.op == "retract"
        assert retraction.target == "dead(felix)"
        assert retraction.target_kind == "atom"
        # The operation states the claim the belief now makes, so applying it needs no
        # second look at the beliefs.
        assert retraction.truth_value is False

    def test_the_survivors_of_the_conflict_are_confirmed(self):
        # The conflict named a set and one of them was flipped; the rest were weighed
        # against it and survived, which is evidence for them.
        outcome = govern(
            [_belief("alive(felix)", confidence=0.9), _belief("dead(felix)", confidence=0.6)],
            Constraints(hard_axioms=(_EXCLUSION,)),
        )
        confirmed = [op.target for op in outcome.ops if op.op == "confirm"]
        assert "alive(felix)" in confirmed
        assert "dead(felix)" not in confirmed

    def test_a_conjecture_is_reached_for_before_an_assertion_of_equal_confidence(self):
        outcome = govern(
            [
                _belief("alive(felix)", confidence=0.8, context="user"),
                _belief("dead(felix)", confidence=0.8, context="hypothesis"),
            ],
            Constraints(hard_axioms=(_EXCLUSION,)),
        )
        retraction = outcome.retraction
        assert retraction is not None
        assert retraction.target == "dead(felix)"


class TestRetractingARule:
    def test_a_defeasible_rule_can_be_the_culprit(self):
        outcome = govern(
            [_belief("cat(felix)", confidence=1.0), _belief("animal(felix)", truth=False, confidence=1.0)],
            Constraints(rules=(Rule(name="impl", axiom=_IMPLICATION, confidence=0.4),)),
        )
        retraction = outcome.retraction
        assert retraction is not None
        assert retraction.target == "impl"
        assert retraction.target_kind == "rule"
        # Kept, not deleted: the row stops counting so the rule can be re-learned.
        assert retraction.confidence == 0.0

    def test_a_non_defeasible_rule_is_never_a_candidate(self):
        outcome = govern(
            [_belief("cat(felix)", confidence=1.0), _belief("animal(felix)", truth=False, confidence=1.0)],
            Constraints(rules=(Rule(name="impl", axiom=_IMPLICATION, confidence=1.0, defeasible=False),)),
        )
        assert outcome.consistent is False
        assert outcome.retraction is None


class TestHolding:
    def test_two_beliefs_the_preference_cannot_separate_are_held(self):
        outcome = govern(
            [_belief("alive(felix)", confidence=0.95), _belief("dead(felix)", confidence=0.95)],
            Constraints(hard_axioms=(_EXCLUSION,)),
        )
        assert outcome.consistent is False
        assert outcome.retraction is None
        (hold,) = outcome.ops
        assert hold.op == "hold"
        assert {hold.target, hold.partner} == {"alive(felix)", "dead(felix)"}

    def test_the_hold_carries_what_an_answer_would_ground(self):
        outcome = govern(
            [_belief("alive(felix)", confidence=0.95), _belief("dead(felix)", confidence=0.95)],
            Constraints(hard_axioms=(_EXCLUSION,)),
        )
        assert outcome.hold is not None
        assert outcome.hold.affirm_true or outcome.hold.affirm_false

    def test_inviolable_beliefs_are_held_too(self):
        # 1.0 is one band among others: the preference cannot separate two
        # grounded claims either.
        outcome = govern(
            [_belief("alive(felix)", confidence=1.0), _belief("dead(felix)", confidence=1.0)],
            Constraints(hard_axioms=(_EXCLUSION,)),
        )
        assert outcome.hold is not None
        assert outcome.undecided is False


class TestSuperseding:
    def test_a_newer_functional_claim_retires_the_older_one(self):
        # A state change is not a miscalibration, so the older belief keeps its confidence
        # and the newer wins whatever they are.
        outcome = govern(
            [_belief("at(bob,home)", confidence=1.0), _belief("at(bob,office)", confidence=1.0)],
            Constraints(functional_predicates=frozenset({"at"})),
            escalated="at(bob,office)",
        )
        assert outcome.consistent is False
        superseded = outcome.retraction
        assert superseded is not None
        assert superseded.op == "supersede"
        assert superseded.target == "at(bob,home)"
        assert superseded.truth_value is False
        assert superseded.confidence == 1.0

    def test_supersession_is_not_reached_for_without_functional_predicates(self):
        outcome = govern(
            [_belief("at(bob,home)"), _belief("at(bob,office)")],
            Constraints(),
            escalated="at(bob,office)",
        )
        assert outcome.consistent is True
