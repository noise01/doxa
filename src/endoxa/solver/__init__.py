"""A self-contained SMT engine, and the public facade for it.

Satisfiability modulo theories with assumption-based solving and unsat cores, an
equality (EUF) theory, quantifier instantiation by E-matching under explicit
budgets, and a TPTP front end. It depends on nothing else in endoxa.

A check answers three ways -- ``"SAT"``, ``"UNSAT"``, or ``"UNKNOWN"`` when a
budget ran out. The third is a real answer rather than a failure: deliberation is
*anytime*, so a matching loop that could run unbounded is cut and reported as
undetermined instead of hanging. ``"UNSAT"`` stays sound however the search was
cut short, because a contradiction derived from the ground clauses does not
depend on instantiation having finished.

Correctness is asserted differentially against Z3 rather than by this package's
own tests alone; those tests are dev-only and are not shipped.

External callers should import from ``endoxa.solver`` directly rather than reaching
into submodules. Modules *inside* this package keep their deep imports to avoid
import cycles (``parsers.tptp`` depends on ``api``).
"""

from endoxa.solver.api import (
    And,
    Bool,
    BoolVal,
    BoundVar,
    Eq,
    Exists,
    ForAll,
    Function,
    Implies,
    Int,
    MultiPattern,
    Not,
    Or,
    Solver,
)
from endoxa.solver.ast.context import global_ctx
from endoxa.solver.ast.expr import App, Const, Expr, FuncDecl, Pattern, Quantifier, Var
from endoxa.solver.ast.expr import BoundVar as BoundVarExpr
from endoxa.solver.ast.sorts import BOOL_SORT, INT_SORT, Sort, USort
from endoxa.solver.parsers import parse_fof, to_tptp_expr

__all__ = [
    "BOOL_SORT",
    "INT_SORT",
    "And",
    "App",
    "Bool",
    "BoolVal",
    "BoundVar",
    "BoundVarExpr",
    "Const",
    "Eq",
    "Exists",
    "Expr",
    "ForAll",
    "FuncDecl",
    "Function",
    "Implies",
    "Int",
    "MultiPattern",
    "Not",
    "Or",
    "Pattern",
    "Quantifier",
    "Solver",
    "Sort",
    "USort",
    "Var",
    "global_ctx",
    "parse_fof",
    "to_tptp_expr",
]
