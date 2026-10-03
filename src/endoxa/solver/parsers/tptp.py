"""Reading TPTP in, and writing it back out.

Writing an expression out is a walk over this package's own AST and needs
nothing else. Reading one in needs a grammar and the library that compiles it,
which live in :mod:`~endoxa.solver.parsers._grammar` and are loaded on the first
parse rather than at import -- see that module for why.
"""

from endoxa.solver.ast.expr import App, BoundVar, Const, Expr, Quantifier, Var

_BINARY_ARITY = 2


def parse_fof(input_str: str) -> tuple[str, str, Expr]:
    """Parse one TPTP ``fof`` annotated formula into ``(name, role, formula)``.

    Args:
        input_str: A complete ``fof(name, role, formula).`` statement, terminating
            period included.

    Returns:
        The formula's name and role as written, and the parsed expression.

    Raises:
        RuleSyntaxError: If the text is not a well-formed ``fof`` statement. The
            grammar library's own diagnosis, which carries the line and column, is
            chained as ``__cause__``.
    """
    # Imported here, not above: this is where a parser first becomes necessary,
    # and everything that never parses is spared building one.
    from endoxa.solver.parsers._grammar import parse_fof as _parse  # noqa: PLC0415

    return _parse(input_str)


def to_tptp_expr(expr: Expr) -> str:
    """Serialize an expression body, without a named FOF statement wrapper.

    Accepts terms as well as Boolean formulas; no FOF role is selected.
    """
    if isinstance(expr, Const):
        if isinstance(expr.value, bool):
            return "$true" if expr.value else "$false"
        return str(expr.value)

    if isinstance(expr, (Var, BoundVar)):
        return expr.name

    if isinstance(expr, App):
        return _app_to_tptp(expr)

    if isinstance(expr, Quantifier):
        quant = "!" if expr.is_forall else "?"
        vars_str = ", ".join(v.name for v in expr.bound_vars)
        return f"({quant} [{vars_str}] : {to_tptp_expr(expr.body)})"

    return str(expr)


def _app_to_tptp(expr: App) -> str:
    name = expr.decl.name
    if name == "And":
        return "(" + " & ".join(to_tptp_expr(arg) for arg in expr.args) + ")"
    if name == "Or" and len(expr.args) == _BINARY_ARITY:
        lhs = expr.args[0]
        rhs = expr.args[1]
        if isinstance(lhs, App) and lhs.decl.name == "Not":
            return f"({to_tptp_expr(lhs.args[0])} => {to_tptp_expr(rhs)})"
        return f"({to_tptp_expr(lhs)} | {to_tptp_expr(rhs)})"
    if name == "Or":
        return "(" + " | ".join(to_tptp_expr(arg) for arg in expr.args) + ")"
    if name == "Not":
        return f"~{to_tptp_expr(expr.args[0])}"
    # No branch for "Implies". :func:`~endoxa.solver.Implies` builds
    # ``Or(Not(p), q)`` and no declaration of that name is ever created, so such a
    # branch could only fire on a caller's own predicate called ``Implies`` --
    # where writing it out as an arrow would be wrong.
    if name == "Eq":
        return f"({to_tptp_expr(expr.args[0])} = {to_tptp_expr(expr.args[1])})"

    if not expr.args:
        return name
    args_str = ", ".join(to_tptp_expr(arg) for arg in expr.args)
    return f"{name}({args_str})"
