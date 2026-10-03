"""Anytime deliberation budget: bound the E-matching loop in rounds and in work.

The meta-control arbiter caps how many E-matching rounds a slow S2 consistency
check may spend. These pure tests exercise the
engine/domain seam: a non-terminating matching loop is cut and reported as
``"UNKNOWN"``, while well-behaved checks converge unaffected.

``max_rounds`` alone does not bound a check, because the cap is only tested once
``match()`` has returned. A soak run stalled for 64 minutes inside a *single*
round, so ``max_matches`` bounds the candidate bindings the
search may examine. Its tests assert on the engine's own counters rather than on
wall-clock time, so they stay deterministic and need no ``benchmark`` marker.
"""

from endoxa.governance.revision import check_consistency
from endoxa.solver import Bool, Implies, Not, Solver, parse_fof

# A classic matching loop: p(X) => p(f(X)) with the seed p(a) instantiates
# p(f(a)), p(f(f(a))), ... without end. Unbounded, check() would not terminate.
_LOOP_RULE = parse_fof("fof(loop, axiom, ![X] : (p(X) => p(f(X)))).")[2]
_SEED_FACT = parse_fof("fof(seed, axiom, p(a)).")[2]


def test_matching_loop_is_cut_to_unknown() -> None:
    """A non-terminating matching loop returns UNKNOWN under a finite budget."""
    solver = Solver()
    solver.add(_LOOP_RULE)
    solver.add(_SEED_FACT)
    assert solver.check(max_rounds=3) == "UNKNOWN"


def test_zero_budget_forbids_any_instantiation() -> None:
    """max_rounds=0 cuts before the first E-matching round on the loop."""
    solver = Solver()
    solver.add(_LOOP_RULE)
    solver.add(_SEED_FACT)
    assert solver.check(max_rounds=0) == "UNKNOWN"


def test_budget_does_not_bite_converging_check() -> None:
    """A quantified check that converges returns its real verdict within budget."""
    rule = parse_fof("fof(r, axiom, ![X] : (p(X) => q(X))).")[2]
    fact = parse_fof("fof(fa, axiom, p(a)).")[2]
    not_q = parse_fof("fof(nq, axiom, ~q(a)).")[2]

    solver = Solver()
    solver.add(rule)
    # p(a) with the rule forces q(a); ~q(a) makes it UNSAT after one round.
    assert solver.check(fact, not_q, max_rounds=10) == "UNSAT"


def test_propositional_check_ignores_budget() -> None:
    """Propositional checks need no E-matching, so even a zero budget decides them."""
    p = Bool("p")
    q = Bool("q")
    solver = Solver()
    solver.add(Implies(p, q))
    assert solver.check(p, Not(q), max_rounds=0) == "UNSAT"


def test_check_consistency_cuts_matching_loop() -> None:
    """The tms.check_consistency wrapper reports UNKNOWN when the budget is spent."""
    beliefs = {"p(a)": {"atom": "p(a)", "truth_value": True, "confidence": 1.0, "stance": "asserted"}}
    result, unsat_core, _map = check_consistency(beliefs, [_LOOP_RULE], max_rounds=3)
    assert result == "UNKNOWN"
    assert unsat_core == []


def test_check_consistency_unbounded_by_default() -> None:
    """Without a budget, a well-behaved check keeps its original SAT/UNSAT result."""
    beliefs = {
        "animal(kitty)": {"atom": "animal(kitty)", "truth_value": False, "confidence": 1.0, "stance": "asserted"},
        "cat(kitty)": {"atom": "cat(kitty)", "truth_value": True, "confidence": 0.8, "stance": "asserted"},
    }
    rule = parse_fof("fof(rule_animal, axiom, ![X] : (cat(X) => animal(X))).")[2]
    result, _core, _map = check_consistency(beliefs, [rule])
    assert result == "UNSAT"


def _wide_solver(constants: int) -> Solver:
    """Build a solver whose matching cost is quadratic in the term count.

    The stalled soak run was inside ``_match_arg``'s ``App`` branch, which scans
    the whole term table for every candidate binding -- reached when a pattern
    argument is itself a term (``p(f(X))``) rather than a bare variable. Flat
    unary rules do *not* show this: their cost is linear, so they would test the
    budget without reproducing what it exists for.

    Measured work for this shape (unbounded, one check): 1.8k candidates at
    ``constants=10``, 6.4k at 20, 24k at 40, 93k at 80 -- roughly 4x per
    doubling. The stalled run had ~8,500 terms.
    """
    solver = Solver()
    solver.add(parse_fof("fof(r1, axiom, ![X] : (p(f(X)) => q(X))).")[2])
    solver.add(parse_fof("fof(r2, axiom, ![X] : (q(X) => p(f(X)))).")[2])
    for i in range(constants):
        solver.add(parse_fof(f"fof(a{i}, axiom, p(f(c{i}))).")[2])
    return solver


def test_match_budget_truncates_within_a_round() -> None:
    """A spent match budget stops the search and is reported on the engine stats."""
    solver = _wide_solver(constants=60)
    assert solver.check(max_matches=200) == "UNKNOWN"
    assert solver.engine.stats["ematch_truncated"] is True
    assert solver.engine.stats["ematch_matches"] <= 200


def test_match_budget_does_not_bite_a_small_check() -> None:
    """A generous budget leaves the real verdict (and the untruncated flag) intact."""
    solver = _wide_solver(constants=2)
    assert solver.check(max_matches=1_000_000) == "SAT"
    assert solver.engine.stats["ematch_truncated"] is False


def test_match_budget_absent_by_default() -> None:
    """Without max_matches the search is unbounded and keeps no counters."""
    solver = _wide_solver(constants=2)
    assert solver.check() == "SAT"
    assert "ematch_truncated" not in solver.engine.stats


def test_truncation_does_not_downgrade_unsat() -> None:
    """UNSAT survives truncation: a contradiction derived before the cut stays sound.

    Rules are matched in the order they were added, so putting the contradictory
    rule first makes this deterministic: its (cheap) instantiation lands, then
    the quadratic rules spend what is left of the budget and trip the cut. The
    contradiction is already on the clause set, and a cut search cannot unmake it.
    """
    solver = Solver()
    solver.add(parse_fof("fof(rbad, axiom, ![X] : (p(f(X)) => bad)).")[2])
    solver.add(parse_fof("fof(nbad, axiom, ~bad).")[2])
    solver.add(parse_fof("fof(r1, axiom, ![X] : (p(f(X)) => q(X))).")[2])
    solver.add(parse_fof("fof(r2, axiom, ![X] : (q(X) => p(f(X)))).")[2])
    for i in range(60):
        solver.add(parse_fof(f"fof(a{i}, axiom, p(f(c{i}))).")[2])

    assert solver.check(max_matches=400) == "UNSAT"
    # Not vacuous: the budget really was spent, and the verdict survived it.
    assert solver.engine.stats["ematch_truncated"] is True
