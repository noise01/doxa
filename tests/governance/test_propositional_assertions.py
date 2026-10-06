"""Bare ground propositions use the same signed checks as predicate atoms."""

from endoxa.governance import Assertion, PremiseSet, check_consistency, check_entailment, check_support


def test_bare_proposition_is_checked_and_can_support_another_proposition():
    premises = PremiseSet(
        assertions=(Assertion(id="observed", atom=" ready ", truth_value=True, confidence=1.0),),
        hard_axioms=("fof(link,axiom,ready => available).",),
    )
    assert check_consistency(premises).status == "SAT"
    assert check_entailment(premises, "fof(query,conjecture,available).").query_status == "UNSAT"
    assert check_support(premises, "available").verdict == "ENTAILED"
    assert check_support(premises, "ready").verdict == "NOT_ENTAILED"


def test_opposite_bare_propositions_preserve_both_owners_and_block_explosion():
    premises = PremiseSet(
        assertions=(
            Assertion(id="yes", atom="ready", truth_value=True, confidence=1.0),
            Assertion(id="no", atom=" ready ", truth_value=False, confidence=1.0),
        )
    )
    result = check_consistency(premises)
    assert result.status == "UNSAT"
    assert {owner for assumption in result.core for owner in assumption.owner_ids} == {"yes", "no"}
    assert check_support(premises, "unrelated").verdict == "INCONSISTENT_PREMISES"
