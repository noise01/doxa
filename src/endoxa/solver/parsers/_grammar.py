"""The TPTP grammar, and everything that needs the parser library to exist.

Split from :mod:`~endoxa.solver.parsers.tptp` so that importing this package does
not build a parser. Compiling the grammar and loading the library it comes from
cost about seventy milliseconds, and they were paid at import by every caller --
including one that only reads a ledger, and one that only counts Brier scores,
neither of which parses anything.

Imported on the first parse instead, once, and held by ``sys.modules`` after
that. Nothing outside this module names the grammar library.
"""

from pathlib import Path
from typing import cast

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import LarkError

from endoxa.errors import RuleSyntaxError
from endoxa.solver.api import And, BoolVal, Eq, Exists, ForAll, Implies, Not, Or
from endoxa.solver.ast.context import global_ctx
from endoxa.solver.ast.expr import BoundVar, Expr, FuncDecl
from endoxa.solver.ast.sorts import BOOL_SORT, USort

U = USort("U")


@v_args(inline=True)
class FofTransformer(Transformer[Token, tuple[str, str, Expr]]):
    def var_expr(self, name: Token) -> BoundVar:
        return global_ctx.mk_bound_var(str(name), U)

    def var_list(self, *names: Token) -> list[BoundVar]:
        return [global_ctx.mk_bound_var(str(v_name), U) for v_name in names]

    # ``term_list: fof_term ("," fof_term)*``, and a ``fof_term`` has already
    # been transformed into an Expr by the time this runs -- these are not
    # tokens, whatever the rule they came from is spelled with.
    def term_list(self, *terms: Expr) -> tuple[Expr, ...]:
        return terms

    def const_term(self, functor: Token) -> tuple[str, tuple[Expr, ...]]:
        return (str(functor), ())

    def app_term(self, functor: Token, terms: tuple[Expr, ...]) -> tuple[str, tuple[Expr, ...]]:
        return (str(functor), tuple(terms))

    def term_expr(self, term_tuple: tuple[str, tuple[Expr, ...]]) -> Expr:
        functor, args = term_tuple
        decl = FuncDecl(functor, tuple(arg.sort for arg in args), U)
        return global_ctx.mk_app(decl, *args)

    def pred_expr(self, term_tuple: tuple[str, tuple[Expr, ...]]) -> Expr:
        functor, args = term_tuple
        decl = FuncDecl(functor, tuple(arg.sort for arg in args), BOOL_SORT)
        return global_ctx.mk_app(decl, *args)

    # The two Boolean constants. ``to_tptp_expr`` has always written them; until the
    # grammar knew them, its output for a formula containing one was text this
    # package's own parser refused.
    def true_expr(self, _token: Token) -> Expr:
        return BoolVal(val=True)

    def false_expr(self, _token: Token) -> Expr:
        return BoolVal(val=False)

    def eq_expr(self, left: Expr, right: Expr) -> Expr:
        return Eq(left, right)

    def neq_expr(self, left: Expr, right: Expr) -> Expr:
        return Not(Eq(left, right))

    def not_expr(self, expr: Expr) -> Expr:
        return Not(expr)

    def and_expr(self, left: Expr, right: Expr) -> Expr:
        return And(left, right)

    def or_expr(self, left: Expr, right: Expr) -> Expr:
        return Or(left, right)

    def implies_expr(self, left: Expr, right: Expr) -> Expr:
        return Implies(left, right)

    def forall_expr(self, vars_list: list[BoundVar], body: Expr) -> Expr:
        return ForAll(vars_list, body)

    def exists_expr(self, vars_list: list[BoundVar], body: Expr) -> Expr:
        return Exists(vars_list, body)

    def fof_annotated(self, name: Token, role: Token, formula: Expr) -> tuple[str, str, Expr]:
        return (str(name), str(role), formula)


grammar_path = Path(__file__).parent.joinpath("tptp.lark")

# Read as UTF-8 explicitly. Without it the encoding is the locale's, which on
# Windows is a legacy code page -- and this runs at import, so a grammar file
# it cannot decode is an ImportError rather than a parse failure.
parser = Lark(grammar_path.read_text(encoding="utf-8"), parser="lalr", transformer=FofTransformer())


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
    try:
        # ``Lark.parse`` is typed as returning a parse tree. This parser is built
        # with a transformer, so LALR applies it during the parse and what comes
        # back is whatever ``fof_annotated`` returned -- a fact about this parser's
        # construction that the signature cannot carry.
        return cast("tuple[str, str, Expr]", parser.parse(input_str))
    except LarkError as exc:
        # Translated at the boundary rather than allowed through. The grammar
        # library is an implementation detail everywhere else in this package, and
        # an exception type is an API: letting it out would make callers import a
        # dependency to write an ``except`` clause, and would pin a choice this
        # package reserves.
        msg = f"not a well-formed TPTP fof statement: {input_str!r}"
        raise RuleSyntaxError(msg) from exc
