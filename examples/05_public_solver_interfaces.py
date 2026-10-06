"""Construct expressions and inspect their types through the public facade."""

from endoxa.solver import (
    BoundVar,
    BoundVarExpr,
    Function,
    MultiPattern,
    Pattern,
    USort,
    to_tptp_expr,
)

item = USort("item")
x = BoundVar("X", item)
print(f"bound-variable type: {isinstance(x, BoundVarExpr)}")
f = Function("label", item, item)
print(f"pattern type: {isinstance(MultiPattern(f(x)), Pattern)}")
print(f"expression body: {to_tptp_expr(f(x))}")
