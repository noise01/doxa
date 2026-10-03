"""Strict additive FOF entry points and the supported query fragment."""

from endoxa.errors import InvalidArgumentError, RuleSyntaxError, SortMismatchError
from endoxa.solver import BOOL_SORT, App, Const, Expr, Quantifier, USort, Var, parse_fof
from endoxa.solver.ast.expr import BoundVar, Pattern


def parse_premise_fof(text: str) -> tuple[str, str, Expr]:
    """Parse one closed Boolean FOF premise, retaining its name and role.

    Accepts axiom, hypothesis and assumption. Role is neither source nor stance
    and does not determine whether a Rule is defeasible. The syntax and theory
    fragment are the same as check_entailment; this is not a full TPTP reader.
    """
    return _parse_role(text, frozenset({"axiom", "hypothesis", "assumption"}))


def parse_query_fof(text: str) -> tuple[str, str, Expr]:
    """Parse one closed Boolean FOF conjecture, retaining its name and role."""
    return _parse_role(text, frozenset({"conjecture"}))


def _parse_role(text: str, roles: frozenset[str]) -> tuple[str, str, Expr]:
    if not isinstance(text, str):
        msg = "Expected one FOF statement as a string"
        raise RuleSyntaxError(msg)
    name, role, formula = parse_fof(text)
    if role not in roles:
        msg = f"FOF role {role!r} is not accepted here; expected {sorted(roles)}"
        raise RuleSyntaxError(msg)
    _validate_formula(formula)
    return name, role, formula


def _validate_formula(formula: Expr) -> None:
    if not isinstance(formula, Expr):
        msg = "Expected a solver Expr"
        raise InvalidArgumentError(msg)
    if formula.sort != BOOL_SORT:
        msg = "Premises and conclusion must be Boolean formulas"
        raise SortMismatchError(msg)
    _validate_node(formula, frozenset())


def _validate_node(node: Expr, bound: frozenset[BoundVar]) -> None:
    if node.sort != BOOL_SORT and not isinstance(node.sort, USort):
        msg = f"Unsupported sort for entailment: {node.sort}"
        raise SortMismatchError(msg)
    if isinstance(node, BoundVar):
        if node not in bound:
            msg = f"Free first-order variable: {node.name}"
            raise InvalidArgumentError(msg)
    elif isinstance(node, Var):
        if node.sort != BOOL_SORT:
            msg = f"Free first-order variable: {node.name}"
            raise InvalidArgumentError(msg)
    elif isinstance(node, Quantifier):
        _validate_quantifier(node, bound)
    elif isinstance(node, App):
        for child in node.args:
            _validate_node(child, bound)
    elif not isinstance(node, Const):
        msg = f"Unsupported expression node: {type(node).__name__}"
        raise InvalidArgumentError(msg)


def _validate_quantifier(node: Quantifier, bound: frozenset[BoundVar]) -> None:
    if node.body.sort != BOOL_SORT:
        msg = "Quantifier body must be Boolean"
        raise SortMismatchError(msg)
    if any(not isinstance(var, BoundVar) or not isinstance(var.sort, USort) for var in node.bound_vars):
        msg = "Quantifiers require bound variables over uninterpreted sorts"
        raise InvalidArgumentError(msg)
    scope = bound | frozenset(node.bound_vars)
    _validate_node(node.body, scope)
    for pattern in node.patterns:
        if not isinstance(pattern, Pattern):
            msg = "Quantifier triggers must be patterns"
            raise InvalidArgumentError(msg)
        for expr in pattern.exprs:
            _validate_node(expr, scope)


__all__ = ["parse_premise_fof", "parse_query_fof"]
