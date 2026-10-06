"""The grammar of a ground atom.

A predicate's identity is ``predicate`` + ``arity``, and reading that identity
out of an expression string like ``mortal(socrates)`` is something several parts
of the library need to do identically. This module is its single home, so two
callers can never disagree about what an atom is.

Pure and dependency-free -- stdlib only, importing nothing else in endoxa -- so it
sits below everything.

**Two narrower parsers remain elsewhere, deliberately.**
:mod:`endoxa.governance.checks`
each read atoms with a stricter pattern: theirs tolerates no whitespace around
the parenthesis and drops empty terms, so ``p (a)`` and ``p(a,,b)`` mean
something to them that they do not mean here. Folding those in would *widen* the
grammar the revision path accepts, which is a change of behaviour rather than a
tidy-up.
"""

import re
from dataclasses import dataclass

#: A ground ``name(args)`` atom. Terms are not parsed further: beliefs are ground
#: atoms and their terms are compared as strings.
_PREDICATE_PATTERN = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\((.*)\)\s*$")


@dataclass(frozen=True, slots=True)
class ParsedAtom:
    """A ground atom split into predicate and argument terms."""

    predicate: str
    args: tuple[str, ...]

    @property
    def arity(self) -> int:
        """Number of argument terms."""
        return len(self.args)

    def key(self) -> str:
        """Return the ``predicate/arity`` natural key."""
        return f"{self.predicate}/{self.arity}"


def parse_atom(expr: str) -> ParsedAtom | None:
    """Parse ``"name(a, b)"`` into a :class:`ParsedAtom`, or ``None`` if malformed.

    Arity-0 atoms (``"p()"``) yield an empty argument tuple. Argument terms are
    whitespace-trimmed; nested structure is not parsed, since terms are compared
    as strings.
    """
    match = _PREDICATE_PATTERN.match(expr)
    if match is None:
        return None
    args_str = match.group(2).strip()
    args = tuple(part.strip() for part in args_str.split(",")) if args_str else ()
    return ParsedAtom(predicate=match.group(1), args=args)


#: The lowest arity at which a functional-exclusion link can mean anything: a
#: predicate whose last argument is a value needs at least one argument before it.
#: One constant, because a rule about what a link *means* cannot hold on one path
#: and not another.
FUNCTIONAL_MIN_ARITY = 2
