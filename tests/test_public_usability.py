"""Public interfaces describe their behavior and expose AST classes."""

from endoxa import solver
from endoxa.governance import Belief, revision
from endoxa.governance.revision import PredicateConstraints, PredicateLink
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


def test_candidates_keep_order_duplicates_and_exclusions():
    links = PredicateConstraints(
        functional_predicates=("location",),
        exclusion_targets={"z": ("a", "a")},
        implication_targets={"b": ("c",)},
    )
    assert links.revision_candidates() == [
        PredicateLink("exclusion", "z", "a"),
        PredicateLink("exclusion", "z", "a"),
        PredicateLink("implication", "b", "c"),
    ]


def test_obsolete_exports_are_absent():

    assert not hasattr(solver, "to_tptp")
    assert not hasattr(revision, "entails")
    assert not hasattr(PredicateConstraints, "acquired_links")
    assert not hasattr(Belief, "from_atom")
