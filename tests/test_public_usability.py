"""Public interfaces describe their behavior and expose AST classes."""

from endoxa.solver import (
    BOOL_SORT,
    Bool,
    BoundVar,
    BoundVarExpr,
    ForAll,
    Function,
    MultiPattern,
    Pattern,
    USort,
    parse_fof,
    to_tptp_expr,
)
from endoxa.solver.parsers import to_tptp_expr as parser_serializer


def test_expression_body_keeps_terms_and_formula_round_trip():
    assert to_tptp_expr is parser_serializer
    assert to_tptp_expr(Bool("ready")) == "ready"
    item = USort("item")
    x = BoundVar("X", item)
    predicate = Function("available", item, BOOL_SORT)
    formula = ForAll([x], predicate(x))
    body = to_tptp_expr(formula)
    name, role, restored = parse_fof(f"fof(sample, axiom, {body}).")
    assert (name, role) == ("sample", "axiom")
    assert to_tptp_expr(restored) == body
    assert isinstance(x, BoundVarExpr)
    assert isinstance(MultiPattern(predicate(x)), Pattern)
