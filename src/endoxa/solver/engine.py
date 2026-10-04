from collections.abc import Mapping
from typing import Literal, cast

from endoxa.errors import SolverStateError
from endoxa.solver.ast.context import NOT_DECL, OR_DECL, global_ctx
from endoxa.solver.ast.expr import App, Expr, Quantifier, Var
from endoxa.solver.ast.sorts import BOOL_SORT, BoolSort
from endoxa.solver.quantifiers import EMatcher
from endoxa.solver.sat.solver import SATSolver
from endoxa.solver.sat.types import Callbacks, Lit
from endoxa.solver.tactic import Preprocessor, Skolemizer, TseitinEncoder
from endoxa.solver.theories import EUFSolver


class SMTEngine:
    def __init__(self, callbacks: Callbacks | None = None) -> None:
        self.encoder: TseitinEncoder = TseitinEncoder()
        self.euf: EUFSolver = EUFSolver()
        self.ematcher: EMatcher = EMatcher(self.euf)
        self.sat: SATSolver = SATSolver(theory=self.euf, callbacks=callbacks)

        self.assertions: list[Expr] = []
        self.scopes: list[Expr] = []
        self.curr_scope: Expr | None = None
        self.scope_counter: int = 0

        self.is_unsat = False
        self.unsat_core_exprs: list[Expr] | None = None

        # Merged from the encoder, preprocessor, SAT solver and EUF theory, each
        # of which keeps its own TypedDict. Flattening them loses the per-source
        # key names, so the merged view is as narrow as it can honestly be.
        self.stats: dict[str, int] = {}

    def _absorb(self, counters: object) -> None:
        """Fold one component's counter block into the merged view.

        Each component keeps its counters in a ``TypedDict`` of its own. A
        ``TypedDict`` is not a ``Mapping[str, int]`` to a type checker even when
        every key it declares holds an int, so the cast states that once here
        rather than at each of the four sources.
        """
        self.stats.update(cast("Mapping[str, int]", counters))

    def _encode_and_simplify(self, expr: Expr, *, is_assumption: bool = False) -> tuple[list[list[Lit]], int, int, Lit]:
        old_var_count = self.encoder.next_var
        new_var_count, new_clauses, root_lit = self.encoder.run_incremental(expr, is_assumption=is_assumption)
        self._absorb(self.encoder.stats)

        protected_vars = set(range(old_var_count))
        for var_id in range(old_var_count, new_var_count):
            e = self.encoder.var_to_expr[var_id]
            if (
                isinstance(e, (Var, Quantifier))
                or (isinstance(e, App) and e.decl.name == "Eq")
                or not isinstance(e.sort, BoolSort)
                or (isinstance(e, App) and e.decl.name not in ("And", "Or", "Not", "Eq", "Implies"))
            ):
                protected_vars.add(var_id)

        preprocessor = Preprocessor(new_clauses, protected_vars=protected_vars)
        simplified_clauses = preprocessor.run()
        self._absorb(preprocessor.stats)

        return simplified_clauses, old_var_count, new_var_count, root_lit

    def _assert_to_sat(self, clauses: list[list[Lit]], new_var_count: int) -> bool:
        current_sat_vars = len(self.sat.trail.assignment)
        for _ in range(new_var_count - current_sat_vars):
            self.sat.add_variable()

        # An empty clause anywhere in the set is UNSAT outright. (A second test
        # for ``[[]]`` stood here, asking whether a list-of-lists was an element
        # of a list of clauses -- a shape that cannot occur, so it never fired.)
        if [] in clauses:
            if not self.sat.add_clause([]):
                return False
        else:
            for clause in clauses:
                if not self.sat.add_clause(clause):
                    return False
        return True

    def _register_to_theories(
        self,
        start_var: int,
        end_var: int,
        depth: int,
        *,
        add_matching_rule: bool = False,
    ) -> None:
        for var_id in range(start_var, end_var):
            expr = self.encoder.var_to_expr[var_id]
            if isinstance(expr, App) and expr.decl.name == "Eq":
                self.euf.register_equality(var_id, expr.args[0], expr.args[1])
                self.ematcher.set_term_depth(expr.args[0], depth)
                self.ematcher.set_term_depth(expr.args[1], depth)
            elif not isinstance(expr.sort, BoolSort) or (
                isinstance(expr, App) and expr.decl.name not in ("And", "Or", "Not", "Eq", "Implies")
            ):
                if isinstance(expr.sort, BoolSort):
                    # A predicate's SAT assignment is its equality to true.
                    # Register that link so congruent predicate applications
                    # cannot receive opposite Boolean assignments.
                    self.euf.register_equality(var_id, expr, global_ctx.mk_true())
                else:
                    self.euf.register_term(expr)
                self.ematcher.set_term_depth(expr, depth)

            if add_matching_rule and isinstance(expr, Quantifier) and expr.is_forall:
                self.ematcher.add_rule(expr)

    def add_formula(self, formula: Expr) -> None:
        if self.curr_scope is not None:
            formula = global_ctx.mk_app(OR_DECL, global_ctx.mk_app(NOT_DECL, self.curr_scope), formula)

        self.assertions.append(formula)

        if self.sat.trail.get_decision_level() > 0:
            self.sat.backtrack(0)

        skolemizer = Skolemizer()
        sk_formula = skolemizer.run(formula)

        simplified_clauses, old_var_count, new_var_count, _ = self._encode_and_simplify(sk_formula)
        self._register_to_theories(old_var_count, new_var_count, depth=0, add_matching_rule=True)

        if not self._assert_to_sat(simplified_clauses, new_var_count):
            self.is_unsat = True

    def check(  # noqa: C901, PLR0912
        self,
        assumptions: list[Expr] | None = None,
        *,
        max_rounds: int | None = None,
        max_matches: int | None = None,
    ) -> Literal["SAT", "UNSAT", "UNKNOWN"]:
        """Check satisfiability, optionally bounding the E-matching work.

        ``max_rounds`` caps how many quantifier-instantiation rounds the loop may
        perform. When the cap is reached while E-matching still yields new
        instances, the check returns ``"UNKNOWN"`` instead of looping further:
        the verdict is undetermined because instantiation had not converged. This
        makes deliberation *anytime* -- a potentially non-terminating matching
        loop is cut at the budget rather than running unbounded. ``None`` (the
        default) leaves the loop unbounded, preserving the original behaviour.

        ``max_matches`` bounds the work *inside* a round: the total candidate
        bindings E-matching may examine across the whole check. The round cap
        alone does not bound a check, because it is only tested once ``match()``
        has returned -- a single round over a large E-graph can run arbitrarily
        long. A check whose matching was truncated cannot claim
        ``"SAT"``: no model was found, but instantiation never finished, so the
        verdict is downgraded to ``"UNKNOWN"``. ``"UNSAT"`` is unaffected --
        a contradiction derived from the ground clauses stays sound however
        the search was cut short.
        """
        self.unsat_core_exprs = []
        if self.is_unsat:
            return "UNSAT"

        # Decisions belong to one check's assumptions, not to the next call.
        # Keep base propagation and learned clauses, but discard old decisions
        # before encoding or selecting the new assumptions.
        self.sat.backtrack(0)
        if assumptions is None:
            assumptions = []

        assumptions_lits: list[Lit] = []
        for scope_var in self.scopes:
            if scope_var in self.encoder.expr_to_var:
                var_id = self.encoder.expr_to_var[scope_var]
                assumptions_lits.append((var_id << 1) | 0)

        lit_to_expr: dict[Lit, Expr] = {}
        for expr in assumptions:
            skolemizer = Skolemizer()
            sk_formula = skolemizer.run(expr)

            simplified_clauses, old_var_count, new_var_count, root_lit = self._encode_and_simplify(
                sk_formula,
                is_assumption=True,
            )
            self._register_to_theories(old_var_count, new_var_count, depth=0, add_matching_rule=True)

            self._assert_to_sat(simplified_clauses, new_var_count)

            assumptions_lits.append(root_lit)
            lit_to_expr[root_lit] = expr

        rounds = 0
        # The match budget is spent across the whole check, not refilled per
        # round: the guarantee wanted here is on the check as a unit.
        matches_left = max_matches
        matches_used = 0
        ematch_truncated = False
        while True:
            result = self.sat.check(assumptions=assumptions_lits)

            if result == "UNSAT":
                self.unsat_core_exprs = []
                for lit in getattr(self.sat, "unsat_core", []):
                    if lit in lit_to_expr:
                        self.unsat_core_exprs.append(lit_to_expr[lit])
                self.unsat_core_exprs = list(set(self.unsat_core_exprs))
                return "UNSAT"

            if result == "SAT":
                has_new_instances = False

                if self.ematcher is not None and self.euf is not None:
                    new_instances = self.ematcher.match(max_matches=matches_left)
                    if matches_left is not None:
                        matches_used += self.ematcher.matches_used
                        matches_left = max(0, matches_left - self.ematcher.matches_used)
                        ematch_truncated = ematch_truncated or self.ematcher.truncated
                        self.stats["ematch_matches"] = matches_used
                        self.stats["ematch_truncated"] = ematch_truncated

                    if new_instances:
                        # Deliberation budget: another instantiation round is
                        # needed but the cap is spent, so the verdict stays
                        # undetermined. Cut the loop.
                        if max_rounds is not None and rounds >= max_rounds:
                            return "UNKNOWN"

                        self.sat.backtrack(0)

                        for expr_inst, new_depth in new_instances:
                            simplified_clauses, old_var_count, new_var_count, _ = self._encode_and_simplify(expr_inst)
                            self._register_to_theories(
                                old_var_count,
                                new_var_count,
                                depth=new_depth,
                                add_matching_rule=False,
                            )

                            if not self._assert_to_sat(simplified_clauses, new_var_count):
                                return "UNSAT"

                        has_new_instances = True
                        rounds += 1

                if has_new_instances:
                    continue

                # Matching was cut short, so "no instance left to add" does not
                # mean the search converged -- the verdict is undetermined.
                if ematch_truncated:
                    return "UNKNOWN"

                return "SAT"

    def push(self) -> None:
        scope_var = global_ctx.mk_var(f"@scope_{self.scope_counter}", BOOL_SORT)
        self.scope_counter += 1

        self.scopes.append(scope_var)
        self.curr_scope = scope_var

    def pop(self, num_levels: int = 1) -> None:
        if num_levels > len(self.scopes):
            msg = "Cannot pop beyond level 0"
            raise SolverStateError(msg)

        for _ in range(num_levels):
            self.scopes.pop()

        self.curr_scope = self.scopes[-1] if self.scopes else None

        if self.sat.trail.get_decision_level() > 0:
            self.sat.backtrack(0)

    def get_model(self) -> dict[Expr, int]:
        if not self.sat or not self.encoder:
            msg = "Engine must be run before requesting a model."
            raise SolverStateError(msg)
        sat_model = self.sat.model
        if not sat_model:
            msg = "Model is not available (UNSAT)."
            raise SolverStateError(msg)

        return {expr: sat_model[var] for var, expr in enumerate(self.encoder.var_to_expr) if var in sat_model}

    def get_unsat_core(self) -> list[Expr]:
        return self.unsat_core_exprs or []

    def get_stats(self) -> dict[str, int]:
        if self.sat:
            self._absorb(self.sat.stats)
        if self.euf:
            self._absorb(self.euf.stats)
        return self.stats
