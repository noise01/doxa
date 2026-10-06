"""Read-only checks over a complete adopted premise snapshot."""

from itertools import combinations

from endoxa.errors import InvalidArgumentError
from endoxa.governance._checking import check_entailment as check_expressions
from endoxa.governance._validation import canonical_atom
from endoxa.governance.formulas import parse_premise_fof, parse_query_fof
from endoxa.governance.premises import PremiseSet
from endoxa.governance.results import Assumption, ConsistencyResult, EntailmentResult
from endoxa.solver import BOOL_SORT, Expr, FuncDecl, Not, Or, Solver, USort, global_ctx
from endoxa.syntax.atoms import parse_atom

FUNCTIONAL_MIN_ARITY = 2


def _atom_expression(text: str) -> Expr:
    """Translate the validated ground-atom syntax used by Assertion and scope."""
    text = canonical_atom(text)
    atom = parse_atom(text)
    sort = USort("U")
    arguments = tuple(global_ctx.mk_app(FuncDecl(argument, (), sort)) for argument in atom.args) if atom else ()
    predicate = FuncDecl(atom.predicate if atom else text, tuple(sort for _ in arguments), BOOL_SORT)
    return global_ctx.mk_app(predicate, *arguments)


def validate_limits(max_rounds: int | None, max_matches: int | None) -> None:
    """Reject invalid budgets before any check, including early return paths."""
    for name, value in (("max_rounds", max_rounds), ("max_matches", max_matches)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            msg = f"{name} must be a nonnegative integer or None"
            raise InvalidArgumentError(msg)


def theory(premises: PremiseSet) -> list[Expr]:
    """Build rules and fixed theory, preserving functional exclusion in support queries."""
    if not isinstance(premises, PremiseSet):
        msg = "Expected a PremiseSet"
        raise InvalidArgumentError(msg)
    expressions = [parse_premise_fof(rule.formula)[2] for rule in premises.rules]
    expressions.extend(parse_premise_fof(text)[2] for text in premises.hard_axioms)
    atoms = sorted(premises.functional_scope)
    for left_text, right_text in combinations(atoms, 2):
        left, right = parse_atom(left_text), parse_atom(right_text)
        if (
            left is not None
            and right is not None
            and left.predicate in premises.functional_predicates
            and left.predicate == right.predicate
            and len(left.args) >= FUNCTIONAL_MIN_ARITY
            and len(left.args) == len(right.args)
            and left.args[:-1] == right.args[:-1]
            and left.args[-1] != right.args[-1]
        ):
            expressions.append(Or(Not(_atom_expression(left_text)), Not(_atom_expression(right_text))))
    return expressions


def signed_assertions(premises: PremiseSet, *, exclude_atom: str | None = None) -> list[Expr]:
    """Return all submitted assertion formulas without inferring their membership."""
    result = []
    for assertion in premises.assertions:
        if assertion.atom == exclude_atom:
            continue
        atom = _atom_expression(assertion.atom)
        result.append(atom if assertion.truth_value else Not(atom))
    return result


def check_consistency(
    premises: PremiseSet, *, max_rounds: int | None = None, max_matches: int | None = None
) -> ConsistencyResult:
    """Check signed ownership; a core is neither all conflicts nor a withdrawal plan."""
    validate_limits(max_rounds, max_matches)
    expressions = theory(premises)
    groups: dict[tuple[str, bool], list[str]] = {}
    for assertion in premises.assertions:
        groups.setdefault((assertion.atom, assertion.truth_value), []).append(assertion.id)
    assumptions = tuple(
        Assumption(atom=atom, truth_value=truth, owner_ids=tuple(ids)) for (atom, truth), ids in sorted(groups.items())
    )
    owners = {}
    for assumption in assumptions:
        atom = _atom_expression(assumption.atom)
        owners[atom if assumption.truth_value else Not(atom)] = assumption
    solver = Solver()
    for expr in expressions:
        solver.add(expr)
    status = solver.check(*owners, max_rounds=max_rounds, max_matches=max_matches)
    core = tuple(owners[expr] for expr in solver.unsat_core()) if status == "UNSAT" else ()
    return ConsistencyResult(status=status, assumptions=assumptions, core=core)


def check_entailment(
    premises: PremiseSet,
    conclusion: str,
    *,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> EntailmentResult:
    """Check a closed FOF conjecture after certifying the complete premises SAT."""
    validate_limits(max_rounds, max_matches)
    query = parse_query_fof(conclusion)[2]
    return check_expressions(
        [*theory(premises), *signed_assertions(premises)], query, max_rounds=max_rounds, max_matches=max_matches
    )


def check_support(
    premises: PremiseSet,
    atom: str,
    *,
    truth_value: bool = True,
    max_rounds: int | None = None,
    max_matches: int | None = None,
) -> EntailmentResult:
    """Exclude every owner of the atom in both polarities, retaining all other theory."""
    validate_limits(max_rounds, max_matches)
    if not isinstance(truth_value, bool):
        msg = "Support truth_value must be a bool"
        raise InvalidArgumentError(msg)
    atom = canonical_atom(atom)
    target = _atom_expression(atom)
    return check_expressions(
        [*theory(premises), *signed_assertions(premises, exclude_atom=atom)],
        target if truth_value else Not(target),
        max_rounds=max_rounds,
        max_matches=max_matches,
    )


__all__ = ["check_consistency", "check_entailment", "check_support"]
