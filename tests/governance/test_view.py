"""Tests for the view derived from the ledger.

What is under test is mostly ``UNRESOLVED``: that a hold puts *both* sides in it,
that it is released by derivation rather than by an operation of its own
, and that a grounded answer is what always releases it
-- the rule that only ``ground`` confers 1.0, stated as
behaviour instead of as a note.

The credence replay is tested for the properties it has to preserve, not for
particular decimals: an inviolable belief is untouched by evidence, and a flip
hands the tally to the claim the belief now makes. The numbers
themselves are pinned against the host's own implementation in
the ledger contract tests.
"""

import pytest

from endoxa.governance import HELD, UNRESOLVED, BeliefState, LedgerOp, compare_to_state, reconstruct_view


def _op(kind: str, target: str, **fields: object) -> LedgerOp:
    return LedgerOp(op=kind, target=target, **fields)  # type: ignore[arg-type]


def _tied_pair() -> list[LedgerOp]:
    """Two beliefs of equal standing, then the hold that says so."""
    return [
        _op("assert", "alive(felix)", truth_value=True, confidence=0.95, actor="user"),
        _op("assert", "dead(felix)", truth_value=True, confidence=0.95, actor="user"),
        _op("hold", "alive(felix)", partner="dead(felix)", origin_event_id="tie1"),
    ]


class TestHeldBeliefs:
    def test_an_assert_is_held(self):
        view = reconstruct_view([_op("assert", "mortal(socrates)", truth_value=True, confidence=0.9)])
        state = view["mortal(socrates)"]
        assert state.status == HELD
        assert state.truth_value is True
        assert state.confidence == 0.9

    def test_a_retract_leaves_the_belief_in_the_ledger_with_the_opposite_claim(self):
        # "It leaves the current view but not the ledger": the
        # target is still a row here, now claiming the other thing.
        view = reconstruct_view(
            [
                _op("assert", "flammable(bridge)", truth_value=True, confidence=0.9),
                _op("retract", "flammable(bridge)", truth_value=False),
            ],
        )
        assert view["flammable(bridge)"].truth_value is False

    def test_a_supersede_keeps_the_confidence_it_restates(self):
        view = reconstruct_view(
            [
                _op("assert", "at(bob,home)", truth_value=True, confidence=0.9),
                _op("supersede", "at(bob,home)", truth_value=False, confidence=0.9),
            ],
        )
        assert view["at(bob,home)"].truth_value is False
        assert view["at(bob,home)"].confidence == 0.9


class TestUnresolved:
    def test_a_hold_puts_both_sides_in_unresolved(self):
        view = reconstruct_view(_tied_pair())
        assert view["alive(felix)"].status == UNRESOLVED
        assert view["dead(felix)"].status == UNRESOLVED
        assert view["alive(felix)"].held_with == "dead(felix)"
        assert view["dead(felix)"].held_with == "alive(felix)"

    def test_neither_side_is_withdrawn(self):
        view = reconstruct_view(_tied_pair())
        assert view["alive(felix)"].truth_value is True
        assert view["dead(felix)"].truth_value is True

    def test_a_grounded_answer_releases_the_hold(self):
        ops = [*_tied_pair(), _op("ground", "dead(felix)", truth_value=False, confidence=1.0, origin_event_id="g1")]
        view = reconstruct_view(ops)
        assert view["dead(felix)"].status == HELD
        assert view["alive(felix)"].status == HELD

    def test_the_release_names_the_operation_that_did_it(self):
        # Releasing is a derivation, so it still has to
        # be readable back with a time and an author.
        ops = [*_tied_pair(), _op("ground", "dead(felix)", truth_value=False, confidence=1.0, origin_event_id="g1")]
        view = reconstruct_view(ops)
        assert view["dead(felix)"].released_by == "g1"
        assert view["alive(felix)"].released_by == "g1"

    def test_evidence_that_moves_a_credence_also_releases_it(self):
        ops = [*_tied_pair(), _op("refute", "dead(felix)", origin_event_id="ev1")]
        view = reconstruct_view(ops)
        assert view["dead(felix)"].confidence is not None
        assert view["dead(felix)"].confidence < 0.95
        assert view["dead(felix)"].status == HELD
        assert view["alive(felix)"].status == HELD

    def test_a_hypothesis_and_an_assertion_are_never_a_tie_to_begin_with(self):
        # The band separates them even at equal confidence,
        # so a hold over such a pair is released the moment anything touches it.
        ops = [
            _op("assert", "p(x)", truth_value=True, confidence=0.5, actor="hypothesis"),
            _op("assert", "q(x)", truth_value=True, confidence=0.5, actor="user"),
            _op("hold", "p(x)", partner="q(x)", origin_event_id="tie1"),
            _op("assert", "p(x)", truth_value=True, confidence=0.5, actor="hypothesis", origin_event_id="a1"),
        ]
        view = reconstruct_view(ops)
        assert view["p(x)"].status == HELD
        assert view["q(x)"].status == HELD


class TestEvidenceReplay:
    def test_corroboration_raises_and_counter_evidence_lowers(self):
        base = [_op("assert", "p(x)", truth_value=True, confidence=0.5)]
        up = reconstruct_view([*base, _op("confirm", "p(x)")])["p(x)"]
        down = reconstruct_view([*base, _op("refute", "p(x)")])["p(x)"]
        assert up.confidence > 0.5
        assert down.confidence < 0.5
        assert (up.evidence_for, up.evidence_against) == (1, 0)
        assert (down.evidence_for, down.evidence_against) == (0, 1)

    def test_an_inviolable_belief_is_untouched_by_evidence(self):
        # Only ask-user grounding confers 1.0, and evidence must not erode it
        #: corroboration cannot raise it and the fold would only
        # lower it.
        view = reconstruct_view(
            [_op("assert", "p(x)", truth_value=True, confidence=1.0), _op("refute", "p(x)")],
        )
        assert view["p(x)"].confidence == 1.0

    def test_corroboration_never_promotes_a_fallible_belief_to_inviolable(self):
        ops = [_op("assert", "p(x)", truth_value=True, confidence=0.95), *[_op("confirm", "p(x)") for _ in range(50)]]
        assert reconstruct_view(ops)["p(x)"].confidence < 1.0

    def test_a_retract_hands_the_tally_to_the_new_claim(self):
        # The counts support what the belief currently claims, so the
        # counter-evidence that motivated the flip reads as one count *for* the
        # opposite claim.
        view = reconstruct_view(
            [
                _op("assert", "p(x)", truth_value=True, confidence=0.9),
                _op("retract", "p(x)", truth_value=False),
            ],
        )
        state = view["p(x)"]
        assert state.truth_value is False
        assert (state.evidence_for, state.evidence_against) == (1, 0)
        assert state.evidence_prior == pytest.approx(0.1)  # the complement of the old claim's prior
        assert state.confidence < 0.5

    def test_an_unmarked_belief_keeps_no_credence_of_its_own(self):
        view = reconstruct_view([_op("assert", "p(x)", truth_value=True)])
        assert view["p(x)"].confidence is None


class TestRules:
    def test_a_retracted_rule_stays_in_the_view_with_its_lowered_confidence(self):
        view = reconstruct_view(
            [
                _op("assert", "mem_2", target_kind="rule", truth_value=True, confidence=0.7),
                _op("retract", "mem_2", target_kind="rule", truth_value=True, confidence=0.0),
            ],
        )
        assert view["mem_2"].target_kind == "rule"
        assert view["mem_2"].confidence == 0.0


def _confirmed_once() -> dict[str, BeliefState]:
    """Build a belief the ledger has booked one corroboration for."""
    return reconstruct_view(
        [
            _op("assert", "mortal(socrates)", truth_value=True, confidence=0.9, actor="user"),
            _op("confirm", "mortal(socrates)", reason="corroboration", origin_event_id="e1"),
        ],
    )


def _node(state: BeliefState, *, evidence_for: int, evidence_against: int) -> dict[str, object]:
    """Build a host node agreeing with ``state`` on truth and credence, and only on those."""
    return {
        "truth_value": state.truth_value,
        "confidence": state.confidence,
        "evidence_for": evidence_for,
        "evidence_against": evidence_against,
    }


class TestComparingToTheHostsState:
    """What ``unattributed`` says beyond how many.

    The count was the whole output until the line below existed: a target whose
    evidence tally disagreed was counted and named nowhere. A consumer reading
    the number *during* a run could not then ask which belief it was, and it
    could not ask afterwards either -- the belief store is a working set, so by
    the end of a run the target has usually paged out and is counted in
    ``missing_from_state`` instead. The count is a lower bound on a question
    nobody could go on to answer.
    """

    def test_a_target_whose_tally_disagrees_is_named_with_both_sides(self):
        view = _confirmed_once()
        state = view["mortal(socrates)"]
        result = compare_to_state(view, {"mortal(socrates)": _node(state, evidence_for=0, evidence_against=0)})
        assert result.unattributed == 1
        assert result.details == ("unattributed mortal(socrates): ledger=(1,0) beliefs=(0,0)",)

    def test_the_ledger_holding_less_is_named_too(self):
        # The test is a disagreement, not an inequality: a host node holding
        # more than the ledger can account for is the case the column exists for.
        view = _confirmed_once()
        state = view["mortal(socrates)"]
        result = compare_to_state(view, {"mortal(socrates)": _node(state, evidence_for=1, evidence_against=3)})
        assert result.details == ("unattributed mortal(socrates): ledger=(1,0) beliefs=(1,3)",)

    def test_the_line_opens_with_the_column_it_was_counted_in(self):
        # A consumer selects the column it cares about by prefix, so the word
        # has to be the column's own and has to come first.
        view = _confirmed_once()
        state = view["mortal(socrates)"]
        result = compare_to_state(view, {"mortal(socrates)": _node(state, evidence_for=0, evidence_against=0)})
        assert [line for line in result.details if line.startswith("unattributed ")] == list(result.details)
        assert not [line for line in result.details if line.startswith("confidence ")]

    def test_an_agreeing_tally_writes_no_line(self):
        # Without this the test above passes on an instrument that names every
        # target it compares, which is not the same instrument.
        view = _confirmed_once()
        state = view["mortal(socrates)"]
        result = compare_to_state(view, {"mortal(socrates)": _node(state, evidence_for=1, evidence_against=0)})
        assert result.unattributed == 0
        assert result.details == ()

    def test_an_unattributed_target_is_not_also_compared_on_credence(self):
        # The tally disagreeing means the credence cannot be read as agreeing or
        # not, so the target leaves before the credence test and carries exactly
        # one line rather than two.
        view = _confirmed_once()
        state = view["mortal(socrates)"]
        node = _node(state, evidence_for=0, evidence_against=0) | {"confidence": 0.1}
        result = compare_to_state(view, {"mortal(socrates)": node})
        assert result.confidence_breaks == 0
        assert len(result.details) == 1
