"""Deductive belief verification: the pure ``check_atom_support`` refutation query.

``verify_belief`` grounds a belief by asking whether it is entailed by the
current beliefs under the active rules. These pure tests exercise that query at
the domain seam: entailment via a rule, a counter-model, a face-value belief
excluded from its own proof, and the inconclusive verdicts (budget
cut / unparseable target).
"""

from endoxa.governance.revision import check_atom_support, find_supporting_rules
from endoxa.solver import parse_fof

# human(X) => mortal(X): the canonical entailment rule.
_MORTAL_RULE = parse_fof("fof(rule_mortal, axiom, ![X] : (human(X) => mortal(X))).")[2]
# A non-terminating matching loop, to force an inconclusive (budget-cut) verdict.
_LOOP_RULE = parse_fof("fof(loop, axiom, ![X] : (p(X) => p(f(X)))).")[2]


def _belief(truth: bool = True) -> dict[str, object]:  # noqa: FBT001, FBT002
    return {"truth_value": truth, "confidence": 1.0, "stance": "asserted"}


def test_entailed_through_rule() -> None:
    """A target the rule derives from a present fact is ENTAILED."""
    beliefs = {"human(socrates)": {"atom": "human(socrates)", **_belief()}}
    assert check_atom_support(beliefs, [_MORTAL_RULE], "mortal(socrates)").verdict == "ENTAILED"


def test_not_entailed_without_premise() -> None:
    """A target the rule cannot reach from the beliefs is NOT_ENTAILED."""
    # human(socrates) does not make plato mortal.
    beliefs = {"human(socrates)": {"atom": "human(socrates)", **_belief()}}
    assert check_atom_support(beliefs, [_MORTAL_RULE], "mortal(plato)").verdict == "NOT_ENTAILED"


def test_face_value_belief_is_not_self_entailing() -> None:
    """A belief present only at face value is NOT its own proof.

    The target atom is excluded from the assumptions, so a belief that merely
    sits on the host's belief store -- with no rule or other belief deriving it -- is
    NOT_ENTAILED. This is the correction that lets cautious verification
     actually refute an unsupported precondition instead of trusting
    it because it happens to be present.
    """
    beliefs = {"mortal(socrates)": {"atom": "mortal(socrates)", **_belief()}}
    assert check_atom_support(beliefs, [], "mortal(socrates)").verdict == "NOT_ENTAILED"


def test_present_belief_still_entailed_when_derivable() -> None:
    """A present belief that OTHER beliefs + a rule derive is still ENTAILED.

    Excluding the target's own presence does not hide a genuine derivation:
    human(socrates) + the mortal rule entail mortal(socrates) even though it is
    also asserted at face value.
    """
    beliefs = {
        "human(socrates)": {"atom": "human(socrates)", **_belief()},
        "mortal(socrates)": {"atom": "mortal(socrates)", **_belief()},
    }
    assert check_atom_support(beliefs, [_MORTAL_RULE], "mortal(socrates)").verdict == "ENTAILED"


def test_empty_beliefs_not_entailed() -> None:
    """With nothing asserted and no reaching rule, a target is NOT_ENTAILED."""
    assert check_atom_support({}, [_MORTAL_RULE], "mortal(socrates)").verdict == "NOT_ENTAILED"


def test_budget_cut_is_unknown() -> None:
    """A query that cannot converge within the deliberation budget is UNKNOWN."""
    beliefs = {"p(a)": {"atom": "p(a)", **_belief()}}
    # The loop rule keeps instantiating p(f(a)), p(f(f(a))), ...; the unrelated
    # target q(a) never resolves, so a finite budget cuts to UNKNOWN.
    assert check_atom_support(beliefs, [_LOOP_RULE], "q(a)", max_rounds=3).verdict == "UNKNOWN"


# A second, independent route to mortal(X): every philosopher is mortal too.
_PHILOSOPHER_RULE = parse_fof("fof(rule_phil, axiom, ![X] : (philosopher(X) => mortal(X))).")[2]


def test_supporting_rules_names_the_necessary_rule() -> None:
    """The rule the derivation cannot do without is returned."""
    beliefs = {"human(socrates)": {"atom": "human(socrates)", **_belief()}}
    supports = find_supporting_rules(beliefs, [_MORTAL_RULE], [_MORTAL_RULE], "mortal(socrates)")
    assert supports == [_MORTAL_RULE]


def test_supporting_rules_empty_when_an_alternative_route_exists() -> None:
    """Two independent derivations mean no single rule is a support.

    Dropping either rule still leaves the target entailed, so losing one of them
    is not the loss of the belief's footing -- and recording an edge would make a
    later retraction fabricate counter-evidence.
    """
    beliefs = {
        "human(socrates)": {"atom": "human(socrates)", **_belief()},
        "philosopher(socrates)": {"atom": "philosopher(socrates)", **_belief()},
    }
    rules = [_MORTAL_RULE, _PHILOSOPHER_RULE]
    assert find_supporting_rules(beliefs, rules, rules, "mortal(socrates)") == []


def test_supporting_rules_ignores_rules_outside_the_defeasible_set() -> None:
    """A base axiom is never recorded: an edge to it could never fire."""
    beliefs = {"human(socrates)": {"atom": "human(socrates)", **_belief()}}
    assert find_supporting_rules(beliefs, [_MORTAL_RULE], [], "mortal(socrates)") == []


def test_supporting_rules_empty_for_an_underivable_target() -> None:
    """Nothing supports a target that was not entailed to begin with."""
    beliefs = {"human(socrates)": {"atom": "human(socrates)", **_belief()}}
    assert find_supporting_rules(beliefs, [_MORTAL_RULE], [_MORTAL_RULE], "mortal(plato)") == []


def test_supporting_rules_records_nothing_for_an_inconclusive_verdict() -> None:
    """A budget-cut verdict yields no support edges.

    UNKNOWN means the question was never answered; recording an edge on it would
    let the deliberation budget decide which beliefs stay revisable later.
    """
    beliefs = {"p(a)": {"atom": "p(a)", **_belief()}}
    assert find_supporting_rules(beliefs, [_LOOP_RULE], [_LOOP_RULE], "q(a)", max_rounds=3) == []
