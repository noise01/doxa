"""An unsat core must name the assumptions that caused the conflict, and only those."""

from itertools import product

import pytest

from endoxa.solver import Bool, Eq, Implies, Int, Not, Solver


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
