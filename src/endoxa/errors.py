"""What this package raises, and one name that catches all of it.

A caller who wants to handle a bad rule string has to be able to name the thing
that gets raised. Before this module the answer was ``lark.exceptions.UnexpectedToken``:
the grammar library reached through :func:`~endoxa.solver.parse_fof` and out of
:func:`~endoxa.governance.check_consistency`, so handling a typo in an axiom meant importing
a dependency this package documents as an internal detail, and pinning a
behaviour it reserves the right to change.

Everything raised on this package's own behalf now derives from
:class:`EndoxaError`. That is a rule with a test behind it rather than a
convention: ``tests/test_error_surface.py`` reads every ``raise`` in the source
and fails on one that does not.

Each class also derives from the built-in exception a caller would reach for
without knowing about this module -- ``TypeError`` for a sort mismatch,
``ValueError`` for an argument out of range. Catching either the built-in or
:class:`EndoxaError` works; the second tells you *whose* failure it was.
"""


class EndoxaError(Exception):
    """Base for every error this package raises on its own behalf.

    Deliberately not raised directly. It exists to be caught: ``except
    EndoxaError`` is the one clause that separates "this library refused" from a
    ``TypeError`` that came from somewhere else in the same block.
    """


class RuleSyntaxError(EndoxaError, ValueError):
    """A rule, axiom or formula string that could not be parsed.

    Carries the offending text, and chains the underlying parser error as its
    cause: ``raise ... from`` keeps the grammar's own diagnosis reachable through
    ``__cause__`` for anyone who wants the column number, without making the
    parser part of this package's public surface.
    """


class SortMismatchError(EndoxaError, TypeError):
    """A term used where a term of another sort was required.

    Raised while an expression is being built rather than when it is solved: an
    ill-sorted formula has no meaning to check, so it is refused at construction.
    """


class ArityMismatchError(EndoxaError, ValueError):
    """A function or predicate applied to the wrong number of arguments."""


class InvalidArgumentError(EndoxaError, ValueError):
    """An argument outside the range the function is defined for."""


class SolverStateError(EndoxaError, RuntimeError):
    """The engine was asked for something its current state cannot give.

    Popping a scope that was never pushed, or reading a model from a search that
    has not run or that came back UNSAT. The call is not wrong in itself, only
    wrong now.
    """


class InternalError(EndoxaError, RuntimeError):
    """An invariant inside this package did not hold.

    Distinct from the rest on purpose: the others say a caller asked for
    something that cannot be given, and this one says the package reached a state
    it does not believe is reachable. Seeing one is grounds for a bug report
    rather than for handling it.
    """


__all__ = [
    "ArityMismatchError",
    "EndoxaError",
    "InternalError",
    "InvalidArgumentError",
    "RuleSyntaxError",
    "SolverStateError",
    "SortMismatchError",
]
