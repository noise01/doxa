"""An unsat core must name the assumptions that caused the conflict, and only those."""

from itertools import product

import pytest

from endoxa.solver import Bool, Eq, Implies, Int, Not, Solver, parse_fof


def test_solver_assumptions_basic():
    """Assumption-based checking and unsat cores over propositional logic."""
    p = Bool("p")
    q = Bool("q")
    r = Bool("r")
    s = Bool("s")  # unrelated to the conflict

    solver = Solver()

    # Standing rules.
    solver.add(Implies(p, q))
    solver.add(Implies(q, r))

    # Assume p, ~r, and the unrelated s. p => q => r, so ~r contradicts, and the
    # core should name exactly the assumptions responsible: [p, ~r].
    res = solver.check(p, Not(r), s)
    assert res == "UNSAT"

    core = solver.unsat_core()
    core_strs = [str(expr) for expr in core]

    assert "p" in core_strs
    assert "(Not r)" in core_strs
    # An unrelated assumption must stay out. This is what keeps belief revision
    # from retracting a bystander.
    assert "s" not in core_strs


def test_solver_assumptions_euf():
    """The same, under the equality theory."""
    solver = Solver()

    a = Int("a")
    b = Int("b")
    c = Int("c")
    d = Int("d")  # unrelated to the conflict

    eq1 = Eq(a, b)
    eq2 = Eq(b, c)
    neq = Not(Eq(a, c))
    eq3 = Eq(c, d)

    res = solver.check(eq1, eq2, neq, eq3)
    assert res == "UNSAT"

    core = solver.unsat_core()
    core_strs = [str(expr) for expr in core]

    # The three that force the contradiction are named.
    assert str(eq1) in core_strs
    assert str(eq2) in core_strs
    assert str(neq) in core_strs
    # The unrelated equality is not.
    assert str(eq3) not in core_strs


@pytest.mark.parametrize("order", [(True, False), (False, True), (False, False, True), (True, False, True)])
def test_opposite_assumptions_keep_both_polarities(order):
    """An assumption cannot replace the opposite literal used on the trail."""
    p = Bool("core_polarity")
    assumptions = [p if positive else Not(p) for positive in order]
    solver = Solver()
    assert solver.check(*assumptions) == "UNSAT"
    core = solver.unsat_core()
    assert set(core) == {p, Not(p)}
    assert Solver().check(*core) == "UNSAT"


def test_small_assumption_cores_are_sound_with_fixed_base():
    """Check soundness, not minimum cardinality, across order and duplication."""
    p, q = Bool("core_sweep_p"), Bool("core_sweep_q")
    literals = (p, Not(p), q, Not(q))
    bases = ((), (p,), (Not(p),), (Implies(p, q),), (Implies(Not(p), q),), (p, Not(p)))
    checked = 0
    for base in bases:
        for length in range(1, 4):
            for assumptions in product(literals, repeat=length):
                solver = Solver()
                for clause in base:
                    solver.add(clause)
                verdict = solver.check(*assumptions)
                if verdict != "UNSAT":
                    assert verdict == "SAT"
                    assert not solver.unsat_core()
                    continue
                core = solver.unsat_core()
                assert set(core) <= set(assumptions)
                recheck = Solver()
                for clause in base:
                    recheck.add(clause)
                assert recheck.check(*core) == "UNSAT", (base, assumptions, core)
                checked += 1
    assert checked > 0


def test_repeated_checks_do_not_reuse_an_old_core():
    p, q = Bool("core_reuse_p"), Bool("core_reuse_q")
    solver = Solver()
    solver.add(Implies(p, q))
    for assumptions in ((Not(p), p), (p, Not(q)), (Not(p), q), (Not(p), p)):
        verdict = solver.check(*assumptions)
        core = solver.unsat_core()
        if verdict == "SAT":
            assert not core
        else:
            assert verdict == "UNSAT"
            assert set(core) <= set(assumptions)
            recheck = Solver()
            recheck.add(Implies(p, q))
            assert recheck.check(*core) == "UNSAT"


def test_base_conflict_clears_the_previous_assumption_core():
    p = Bool("core_base_update")
    solver = Solver()
    assert solver.check(Not(p), p) == "UNSAT"
    assert solver.unsat_core()
    solver.add(p)
    solver.add(Not(p))
    assert solver.check() == "UNSAT"
    assert solver.unsat_core() == []


def test_reused_solver_matches_fresh_checks_with_base_implication():
    p, q = Bool("core_sequence_p"), Bool("core_sequence_q")
    base = Implies(p, q)
    reused = Solver()
    reused.add(base)
    literals = (p, Not(p), q, Not(q))
    for assumptions in product(literals, repeat=3):
        fresh = Solver()
        fresh.add(base)
        verdict = reused.check(*assumptions)
        assert verdict == fresh.check(*assumptions)
        core = reused.unsat_core()
        assert set(core) <= set(assumptions)
        if verdict == "UNSAT":
            recheck = Solver()
            recheck.add(base)
            assert recheck.check(*core) == "UNSAT"
        else:
            assert core == []


@pytest.mark.parametrize("reverse", [False, True])
def test_congruent_predicates_cannot_have_opposite_truth_assignments(reverse):
    equality = parse_fof("fof(e,axiom,core_a=core_b).")[2]
    positive = parse_fof("fof(p,axiom,core_pred(core_a)).")[2]
    negative = parse_fof("fof(n,axiom,~core_pred(core_b)).")[2]
    assumptions = [positive, negative]
    if reverse:
        assumptions.reverse()
    solver = Solver()
    solver.add(equality)
    assert solver.check(*assumptions) == "UNSAT"
    core = solver.unsat_core()
    assert set(core) <= set(assumptions)
    recheck = Solver()
    recheck.add(equality)
    assert recheck.check(*core) == "UNSAT"
    assert solver.check(positive) == "SAT"
    assert solver.check(negative) == "SAT"
    assert solver.unsat_core() == []


@pytest.mark.parametrize(
    ("equality", "left", "right"),
    [
        ("core_b=core_a", "core_pred(f(core_a))", "core_pred(f(core_b))"),
        ("core_a=core_b", "core_pred(core_a,core_c)", "core_pred(core_b,core_c)"),
    ],
)
def test_predicate_function_congruence_with_assumed_equality(equality, left, right):
    assumptions = [
        parse_fof(f"fof(e,axiom,{equality}).")[2],
        parse_fof(f"fof(p,axiom,{left}).")[2],
        parse_fof(f"fof(n,axiom,~{right}).")[2],
    ]
    solver = Solver()
    assert solver.check(*assumptions) == "UNSAT"
    core = solver.unsat_core()
    assert set(core) <= set(assumptions)
    assert Solver().check(*core) == "UNSAT"


@pytest.mark.parametrize(
    ("base", "left", "right"),
    [
        ("core_a=core_b", "core_pred(core_a)", "core_pred(core_b)"),
        ("core_a=core_b", "~core_pred(core_a)", "~core_pred(core_b)"),
        ("core_a=core_b", "core_pred(core_a)", "~other_pred(core_b)"),
        ("core_a!=core_b", "core_pred(core_a)", "~core_pred(core_b)"),
        ("core_a=core_b", "core_pred(core_a,core_c)", "~core_pred(core_b,core_d)"),
    ],
)
def test_predicate_congruence_preserves_satisfiable_controls(base, left, right):
    solver = Solver()
    solver.add(parse_fof(f"fof(e,axiom,{base}).")[2])
    assumptions = [parse_fof(f"fof(p,axiom,{left}).")[2], parse_fof(f"fof(q,axiom,{right}).")[2]]
    assert solver.check(*assumptions) == "SAT"
    assert solver.unsat_core() == []


def test_predicate_congruence_does_not_survive_popped_equality():
    equality = parse_fof("fof(e,axiom,scope_a=scope_b).")[2]
    assumptions = [
        parse_fof("fof(p,axiom,scope_pred(scope_a)).")[2],
        parse_fof("fof(n,axiom,~scope_pred(scope_b)).")[2],
    ]
    solver = Solver()
    assert solver.check(*assumptions) == "SAT"
    solver.push()
    solver.add(equality)
    assert solver.check(*assumptions) == "UNSAT"
    core = solver.unsat_core()
    assert set(core) <= set(assumptions)
    recheck = Solver()
    recheck.add(equality)
    assert recheck.check(*core) == "UNSAT"
    solver.pop()
    assert solver.check(*assumptions) == "SAT"
    assert solver.unsat_core() == []
