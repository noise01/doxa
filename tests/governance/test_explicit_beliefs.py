"""Opaque IDs stay opaque from solver assumptions through replay and restore."""

import inspect
import json
from dataclasses import asdict
from typing import get_type_hints

import pytest

from endoxa.errors import InvalidArgumentError, RuleSyntaxError
from endoxa.governance import (
    Belief,
    Constraints,
    LedgerOp,
    Rule,
    SupportRef,
    check_belief_support,
    derive_ledger,
    govern,
    parse_premise_fof,
    parse_query_fof,
    reconstruct_view,
)
from endoxa.governance.revision import (
    PredicateConstraints,
    build_assumptions,
    check_consistency,
    find_link_culprits,
    find_rule_culprits,
    find_supporting_rules,
    functional_exclusion_partner,
    predicate_clauses,
    select_tie_question_target,
    select_verified_revision_target,
)
from endoxa.governance.revision.preference import is_hypothesis, revision_candidates
from endoxa.solver import parse_fof

_EXCL = "fof(excl, axiom, ![X]: ~(alive(X) & dead(X)))."


def _belief(belief_id, atom, *, truth=True, confidence=0.7, stance="asserted", source="user"):  # noqa: PLR0913 - query metadata
    return Belief(id=belief_id, atom=atom, truth_value=truth, confidence=confidence, stance=stance, source=source)


def _map(beliefs):
    return {
        belief.id: {
            "atom": belief.atom,
            "truth_value": belief.truth_value,
            "confidence": belief.confidence,
            "stance": belief.stance,
            "source": belief.source,
        }
        for belief in beliefs
    }


def _assert(belief, *, actor="writer", supports=()):
    return LedgerOp(
        op="assert",
        target=belief.id,
        atom=belief.atom,
        stance=belief.stance,
        source=belief.source,
        truth_value=belief.truth_value,
        confidence=belief.confidence,
        actor=actor,
        supported_by=supports,
    )


def test_explicit_identity_and_required_keyword_fields():
    belief = _belief("id:17", "p( a , b )")
    assert belief.id == "id:17"
    assert belief.atom == "p(a,b)"
    assert not hasattr(belief, "target")
    for name in ("id", "atom", "truth_value", "confidence", "stance", "source"):
        assert inspect.signature(Belief).parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(TypeError):
        Belief("p", True, 0.7, "user")  # noqa: FBT003 - rejection of the removed positional contract


@pytest.mark.parametrize("atom", [None, "", "p(X)", "p(f(a))", "p()", "p(a,,b)", "~p", "a=b"])
def test_factory_refuses_non_ground_or_malformed_atoms(atom):
    with pytest.raises(RuleSyntaxError):
        _belief("id", atom)


@pytest.mark.parametrize("belief_id", ["", " ", None, 1])
def test_id_is_nonempty_string(belief_id):
    with pytest.raises(InvalidArgumentError):
        _belief(belief_id, "p")


@pytest.mark.parametrize("stance", ["user", [], "", None])
def test_bad_stance_is_not_a_source_or_role(stance):
    with pytest.raises(InvalidArgumentError):
        _belief("id", "p", stance=stance)


@pytest.mark.parametrize("source", ["hypothesis", [], "", 1])
def test_bad_source_is_not_a_stance(source):
    with pytest.raises(InvalidArgumentError):
        _belief("id", "p", source=source)


def test_preference_requires_stance_without_role_inference():
    with pytest.raises(InvalidArgumentError, match="stance"):
        is_hypothesis({"belief_context": "hypothesis"})
    assert is_hypothesis({"stance": "hypothesis", "source": "user"})
    assert not is_hypothesis({"stance": "asserted", "source": "derivation"})
    assert not revision_candidates([("asserted", {"stance": "asserted", "confidence": 1.0})])
    assert revision_candidates([("guess", {"stance": "hypothesis", "confidence": 1.0})])


@pytest.mark.parametrize(
    "beliefs",
    [
        [_belief("id", "p"), _belief("id", "q")],
        [_belief("id", "p"), _belief("id", "p")],
        [_belief("one", "p(a)"), _belief("two", "p( a )", truth=False)],
    ],
)
def test_govern_refuses_duplicate_id_or_atom(beliefs):
    with pytest.raises(InvalidArgumentError):
        govern(beliefs, Constraints())


def test_rule_ids_cannot_collide_with_beliefs_or_each_other():
    rule = Rule.from_fof("fof(r, axiom, p).", confidence=0.9, defeasible=True, name="rule:id")
    with pytest.raises(InvalidArgumentError):
        govern([_belief("rule:id", "q")], Constraints(rules=(rule,)))
    with pytest.raises(InvalidArgumentError):
        govern([], Constraints(rules=(rule, rule)))


def test_govern_retraction_survivors_and_core_reference_ids():
    beliefs = [_belief("first", "alive(a)", confidence=0.9), _belief("second", "dead(a)", confidence=0.6)]
    outcome = govern(beliefs, Constraints(hard_axioms=(_EXCL,)))
    assert outcome.retraction.target == "second"
    assert {op.target for op in outcome.ops} == {"first", "second"}
    data = _map(beliefs)
    verdict, core, mapping = check_consistency(data, [parse_fof(_EXCL)[2]])
    assert verdict == "UNSAT"
    assert {mapping[str(expr)] for expr in core} == {"first", "second"}
    assert select_verified_revision_target(core, data, mapping, [parse_fof(_EXCL)[2]])[0] == "second"


def test_govern_hold_answers_reference_ids_and_both_completions_are_checked():
    beliefs = [_belief("id:a", "alive(a)", confidence=0.9), _belief("id:b", "dead(a)", confidence=0.9)]
    outcome = govern(beliefs, Constraints(hard_axioms=(_EXCL,)))
    assert outcome.hold is not None
    assert {outcome.hold.node_a, outcome.hold.node_b} == {"id:a", "id:b"}
    assert set(outcome.hold.affirm_true + outcome.hold.affirm_false) == {"id:a", "id:b"}
    assert {outcome.ops[0].target, outcome.ops[0].partner} == {"id:a", "id:b"}


def test_cluster_uses_atom_terms_not_id_spelling():
    # A forced consequent is not a settling flip, even though IDs share no term.
    beliefs = [_belief("opaque:1", "cat(a)", confidence=1.0), _belief("opaque:2", "animal(a)", truth=False)]
    rule = Rule("r", "fof(r, axiom, ![X]: (cat(X) => animal(X))).", 1.0, defeasible=False)
    outcome = govern(beliefs, Constraints(rules=(rule,)))
    assert outcome.retraction.target == "opaque:2"
    assert outcome.retraction.truth_value is True


def test_functional_supersession_uses_escalated_id():
    beliefs = [_belief("old", "at(bob,home)", confidence=1.0), _belief("new", "at(bob,office)", confidence=1.0)]
    outcome = govern(beliefs, Constraints(functional_predicates=frozenset({"at"})), escalated="new")
    assert outcome.retraction.target == "old"
    assert outcome.retraction.op == "supersede"
    assert functional_exclusion_partner("new", _map(beliefs), {"at"})[0] == "old"
    with pytest.raises(InvalidArgumentError):
        govern(beliefs, Constraints(), escalated="at(bob,office)")


@pytest.mark.parametrize("link_kind", ["functional", "exclusion", "implication"])
def test_all_link_clause_paths_use_atoms(link_kind):
    if link_kind == "functional":
        beliefs = [_belief("one", "at(a,home)"), _belief("two", "at(a,office)")]
        links = PredicateConstraints(functional_predicates={"at"})
    else:
        beliefs = [_belief("one", "p(a)"), _belief("two", "q(a)", truth=link_kind != "implication")]
        links = PredicateConstraints(**{f"{link_kind}_targets": {"p": {"q"}}})
    data = _map(beliefs)
    clauses = predicate_clauses(data, links)
    assert clauses
    result, core, mapping = check_consistency(data, clauses)
    assert result == "UNSAT"
    assert {mapping[str(expr)] for expr in core} == {"one", "two"}
    assert select_tie_question_target(core, data, mapping, [], links=links) is not None
    if link_kind != "functional":
        assert len(find_link_culprits(data, [], links)) == 1


def test_rule_culprits_and_support_rules_work_with_ids():
    rule = parse_fof("fof(r, axiom, ![X]: (p(X) => q(X))).")[2]
    bad = _map([_belief("premise", "p(a)"), _belief("target", "q(a)", truth=False)])
    assert find_rule_culprits(bad, [rule], [rule]) == [rule]
    good = _map([_belief("premise", "p(a)"), _belief("target", "q(a)")])
    # Legacy check_atom_support/support-rule target remains formula text, never silently an ID.
    assert find_supporting_rules(good, [rule], [rule], "q(a)") == [rule]


def test_support_removes_all_id_aliases_and_both_polarities():
    beliefs = [_belief("one", "p(a)"), _belief("two", "p( a )", truth=False)]
    assert check_belief_support(beliefs, [], "one").verdict == "NOT_ENTAILED"
    assert check_belief_support(beliefs, [], "two", truth_value=False).verdict == "NOT_ENTAILED"
    with pytest.raises(InvalidArgumentError):
        check_belief_support(beliefs, [], "p(a)")
    with pytest.raises(InvalidArgumentError):
        build_assumptions(_map(beliefs))


def test_records_restore_explicit_metadata_and_refuse_incomplete_fields():
    belief = _belief("id", "p(a)", stance="hypothesis", source="tool")
    assert Belief.from_record(belief.to_record()) == belief
    assert Belief.from_record(asdict(belief)) == belief
    with pytest.raises(InvalidArgumentError):
        Belief.from_record({"target": "p(a)", "truth_value": True, "confidence": 0.7, "context": "user"})


def test_ledger_roundtrip_preserves_identity_stance_source_and_support_ids():
    belief = _belief("opaque", "p(a)", stance="hypothesis", source="tool")
    op = _assert(belief, actor="user", supports=(SupportRef("derivation", "antecedent:id"),))
    # actor=user must not turn a hypothesis into an assertion or change its source.
    record = json.loads(json.dumps(asdict(op)))
    record["supported_by"] = tuple(SupportRef(**item) for item in record["supported_by"])
    replayed = LedgerOp(**record)
    assert replayed == op
    state = reconstruct_view([replayed, LedgerOp("confirm", "opaque", actor="governance")])["opaque"]
    assert state.context == ""
    assert (state.atom, state.stance, state.source) == ("p(a)", "hypothesis", "tool")
    restored = Belief.from_record(state.to_belief().to_record())
    assert restored.id == "opaque"
    assert restored.stance == "hypothesis"
    assert restored.source == "tool"
    assert replayed.supported_by[0].ref == "antecedent:id"
    assert govern([restored], Constraints()).consistent is True


def test_legacy_and_partial_ledger_do_not_invent_new_metadata():
    old = reconstruct_view([LedgerOp("assert", "p(a)", actor="hypothesis", confidence=0.7)])["p(a)"]
    assert old.context == "hypothesis"
    assert old.atom is old.stance is old.source is None
    with pytest.raises(InvalidArgumentError):
        old.to_belief()
    partial = reconstruct_view([LedgerOp("retract", "opaque", actor="governance")])["opaque"]
    with pytest.raises(InvalidArgumentError):
        partial.to_belief()


def test_repeated_id_cannot_change_atom_source_or_kind():
    first = _assert(_belief("id", "p"))
    for second in [
        _assert(_belief("id", "q")),
        _assert(_belief("id", "p", source="tool")),
        LedgerOp("retract", "id", target_kind="rule"),
    ]:
        with pytest.raises(InvalidArgumentError):
            reconstruct_view([first, second])
    with pytest.raises(InvalidArgumentError):
        reconstruct_view([LedgerOp("assert", "id", target_kind="rule"), first])
    with pytest.raises(InvalidArgumentError):
        LedgerOp("assert", "id", atom="p")


def test_explicit_stance_update_releases_a_hold_without_actor_inference():
    one, two = _belief("one", "alive(a)", confidence=0.9), _belief("two", "dead(a)", confidence=0.9)
    ops = [_assert(one), _assert(two), *govern([one, two], Constraints(hard_axioms=(_EXCL,))).ops]
    view = reconstruct_view(ops)
    assert view["one"].status == view["two"].status == "UNRESOLVED"
    # Source and actor alone do not move the preference band.
    view = reconstruct_view([*ops, LedgerOp("assert", "one", actor="hypothesis")])
    assert view["one"].status == "UNRESOLVED"
    view = reconstruct_view([*ops, LedgerOp("assert", "one", stance="hypothesis", actor="user")])
    assert view["one"].status == view["two"].status == "HELD"


def test_event_adapter_preserves_explicit_metadata_but_does_not_reinterpret_old_source():
    def row(properties):
        return {
            "id": "event",
            "timestamp": 0.0,
            "event_type": "AtomAddedEvent",
            "payload": {"node_id": "opaque", "role": "hypothesis", "properties": properties},
        }

    ops = derive_ledger([row({"atom": "p(a)", "stance": "asserted", "source": "tool", "confidence": 0.7})]).ops
    state = reconstruct_view(ops)["opaque"]
    assert state.stance == "asserted"
    assert state.context == ""
    assert state.source == "tool"
    old = reconstruct_view(derive_ledger([row({"source": "user", "confidence": 0.7})]).ops)["opaque"]
    assert old.context == "hypothesis"
    assert old.source is None
    assert old.stance is None


@pytest.mark.parametrize("role", ["axiom", "hypothesis", "assumption"])
def test_strict_premise_roles_and_rule_factory_preserve_names(role):
    text = f"fof(original, {role}, ![X]: (p(X) => q(X)))."
    name, parsed_role, _expr = parse_premise_fof(text)
    assert (name, parsed_role) == ("original", role)
    rule = Rule.from_fof(text, name="rule:opaque", confidence=0.8, defeasible=True)
    assert rule.name == "rule:opaque"
    assert rule.axiom == text
    assert rule.defeasible is True
    assert Rule.from_fof(text, confidence=0.8, defeasible=False).name == "original"


@pytest.mark.parametrize("role", ["conjecture", "negated_conjecture", "definition", "lemma", "unknown"])
def test_strict_premise_rejects_other_roles_without_changing_legacy(role):
    text = f"fof(original, {role}, p(a))."
    assert parse_fof(text)[1] == role
    with pytest.raises(RuleSyntaxError):
        Rule("id", text, 0.8)
    with pytest.raises(RuleSyntaxError):
        parse_premise_fof(text)
    with pytest.raises(RuleSyntaxError):
        Rule.from_fof(text, confidence=0.8, defeasible=True)


def test_strict_query_preserves_name_and_requires_conjecture():
    assert parse_query_fof("fof(question, conjecture, p(a)).")[:2] == ("question", "conjecture")
    for role in ["axiom", "hypothesis", "assumption", "negated_conjecture"]:
        with pytest.raises(RuleSyntaxError):
            parse_query_fof(f"fof(q, {role}, p(a)).")


@pytest.mark.parametrize("formula", ["p(X)", "p(a)). fof(q, axiom, q(a)", "p(a)"])
def test_strict_fof_requires_closed_formula_and_one_complete_statement(formula):
    text = f"fof(q, conjecture, {formula})." if formula != "p(a)" else "fof(q, conjecture, p(a))"
    with pytest.raises((InvalidArgumentError, RuleSyntaxError)):
        parse_query_fof(text)


def test_public_factory_annotations_are_resolvable():
    for method in [Belief, Belief.from_record, Rule.from_fof, parse_premise_fof, parse_query_fof]:
        assert get_type_hints(method)


def test_cluster_keeps_a_non_core_rederiver_and_refuses_a_whiff():
    data = _map(
        [
            _belief("opaque:1", "alive(a)", confidence=1.0),
            _belief("opaque:2", "dead(a)", confidence=0.7),
            _belief("opaque:3", "cat(a)", confidence=1.0),
        ]
    )
    assumptions, mapping = build_assumptions(data)
    core = assumptions[:2]
    rules = [parse_fof(_EXCL)[2], parse_fof("fof(r, axiom, ![X]: (cat(X) => dead(X))).")[2]]
    assert select_verified_revision_target(core, data, mapping, rules) is None
    data["opaque:1"]["confidence"] = 0.7
    assert select_tie_question_target(core, data, mapping, rules) is None


@pytest.mark.parametrize("source", ["user", "tool", "corpus", "derivation"])
def test_source_does_not_choose_revision_or_protection(source):
    beliefs = [
        _belief("assertion", "alive(a)", confidence=1.0, source=source),
        _belief("guess", "dead(a)", confidence=1.0, stance="hypothesis", source=source),
    ]
    outcome = govern(beliefs, Constraints(hard_axioms=(_EXCL,)))
    assert outcome.retraction.target == "guess"


@pytest.mark.parametrize("confidence", [None, True, "0.7", float("nan"), float("inf"), -0.1, 1.1])
def test_explicit_confidence_is_a_probability(confidence):
    with pytest.raises(InvalidArgumentError):
        _belief("id", "p", confidence=confidence)


def test_explicit_record_has_boolean_claim_and_rejects_unknown_fields():
    with pytest.raises(InvalidArgumentError):
        Belief.from_record({"target": "id", "atom": "p", "truth_value": "false", "confidence": 0.7})
    with pytest.raises(InvalidArgumentError):
        Belief.from_record({"target": "p", "truth_value": True, "confidence": 0.7, "actor": "user"})


def test_strict_fof_refuses_non_string_and_keeps_exists_and_equality():
    for parser in (parse_premise_fof, parse_query_fof):
        with pytest.raises(RuleSyntaxError):
            parser(None)
    assert parse_premise_fof("fof(r, axiom, ?[X]: (p(X) & X = a)).")[:2] == ("r", "axiom")
