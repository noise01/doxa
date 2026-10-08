# Public API and checks

Use `endoxa.governance` for the premise API described here. It exports the types
below together with `check_consistency`, `check_entailment`, `check_support` and
`propose_revision`. Definitions and annotations are part of the in-memory Python
API, not a durable storage schema.

## Input records

All constructors in this table use keyword fields. Records are immutable.

| Type | Fields and meaning |
| --- | --- |
| `Assertion` | Required `id`, `atom`, `truth_value`, `confidence`; optional `source=None`. One individually adoptable signed ground atom. |
| `Rule` | Required `id`, `formula`, `confidence`. One individually adoptable closed FOF premise. |
| `PremiseSet` | `assertions=()`, `rules=()`, `hard_axioms=()`, `functional_predicates=frozenset()`, `functional_scope=frozenset()`. The complete adopted input plus fixed constraints. |
| `Target` | Required `kind="assertion"` or `"rule"`, and `id`. `target_of(record)` builds the typed reference. |
| `RevisionPolicy` | `protected=frozenset()` and `priorities={}`. Typed targets explicitly control withdrawal eligibility and order. |

IDs are nonempty strings identifying individual records. Multiple IDs can supply
the same signed atom. Duplicate IDs within one kind are rejected; an Assertion
and a Rule may share an ID because targets include the kind. A candidate's ID must
be new within its kind. Use a new ID when changing a claim's content or polarity.
A confidence update is a new input snapshot supplied by the caller.

Confidence is a finite number in [0, 1]; Boolean values are rejected. Confidence
is used by revision ranking, not aggregated into logical truth. `source` is an
optional nonempty string; it does not infer a policy. `PremiseSet` normalizes
collections to immutable values and sorts records by ID.

An Assertion atom is a flat ground predicate such as `ready`, `open(door)` or
`location(parcel,office)`. Names start with a lowercase letter and contain letters,
digits or underscores. Whitespace is normalized. Variables, nested terms,
negation and numeric arguments are not Assertion atom syntax: put the sign in
`truth_value` and formulas in Rules or hard axioms.

## Formula syntax

Rules and hard axioms accept one closed FOF statement per string, for example
`fof(m, axiom, ![X]: (human(X) => mortal(X))).` Include the terminating period.
Accepted premise roles are `axiom`, `hypothesis` and `assumption`; query strings
use `conjecture`. The FOF name and role do not protect an adopted Rule. Use
`RevisionPolicy` for protection, or `hard_axioms` for non-withdrawable constraints.

`parse_premise_fof(text)` and `parse_query_fof(text)` return the FOF name, role
and public solver expression. They validate a closed Boolean formula in the
supported fragment: Boolean connectives and uninterpreted first-order logic
with equality. First-order variables must be bound by quantifiers over
uninterpreted sorts. Arithmetic, integer-sorted terms and free first-order
variables are unsupported. This is not a general TPTP reader.

For expression constructors and AST types, import from `endoxa.solver`; see
[example 05](../examples/05_public_solver_interfaces.py). Measurement inputs
belong to `endoxa.instruments`, independently of these checks.

## Checks and results

All three check functions accept keyword `max_rounds=None` and `max_matches=None`.
Each is a nonnegative integer or `None`, excluding Boolean values. Limits renew
for each solver check, including the two checks used for guarded entailment.
They do not cap a whole proposal or its elapsed time.

| Call | Result and interpretation |
| --- | --- |
| `check_consistency(premises)` | `ConsistencyResult(status, assumptions, core)`: `SAT`, `UNSAT` or `UNKNOWN`. |
| `check_entailment(premises, conclusion)` | `EntailmentResult(premises_status, query_status)`, where the conclusion is a closed FOF conjecture. |
| `check_support(premises, atom, truth_value=True)` | The same `EntailmentResult`, after excluding every Assertion of the canonical atom in both polarities. The atom need not already be adopted. `truth_value` is keyword-only. |

Consistency assumptions group records by canonical atom and polarity.
Each `Assumption(atom, truth_value, owner_ids)` contains every submitted ID
supplying that signed atom, with unique sorted owners. Ownership is attribution,
not a verdict that every owner should withdraw. A consistency core is sound
with the full fixed theory, including Rules and functional exclusions. It need
not be minimal, unique, or cover every conflict. Rules constrain the check but
are not owner IDs in this diagnostic core. An empty UNSAT core can mean the
fixed theory itself conflicts. SAT and UNKNOWN results have no core.

Entailment first checks the complete query premises. Only when they are SAT
does it check those premises together with the negated conclusion:

| `premises_status` | `query_status` | `.verdict` |
| --- | --- | --- |
| `SAT` | `UNSAT` | `ENTAILED` |
| `SAT` | `SAT` | `NOT_ENTAILED` |
| `UNSAT` | `None` | `INCONSISTENT_PREMISES` |
| `UNKNOWN` | `None` | `UNKNOWN` |
| `SAT` | `UNKNOWN` | `UNKNOWN` |

`NOT_ENTAILED` does not mean the conclusion is false. `UNKNOWN` does not justify
adoption, rejection or negation. Quantified E-matching is incomplete and can
remain inconclusive. Invalid inputs raise errors instead: catch
`endoxa.errors.EndoxaError` for the package's error family, or the specific
`RuleSyntaxError`, `InvalidArgumentError` or `SortMismatchError` when appropriate.

Support retains all Rules, hard axioms, other atoms and functional scope.
It excludes the target's own assertions even when they would conflict with
each other. Ordinary entailment retains them. See the executable comparison
in the [quickstart](quickstart.md#check-what-is-supplied).

## Functional predicates and retained scope

For a predicate of arity at least two, functional exclusion prevents simultaneous
positive ground facts with the same leading arguments and different final values.
For example, `location(parcel,office)` and `location(parcel,depot)` conflict when
`location` is declared functional and both atoms are in `functional_scope`.
Unary predicates do not exclude different subjects.

`functional_scope` defaults to the submitted Assertion atoms and unions in any
explicit additional ground atoms. These atoms provide exclusion vocabulary,
not additional asserted facts. Rule-only values do not automatically extend it.
This is ground exclusion, not complete quantified functionality or a general
equality reasoner for value names.

```python
from dataclasses import replace
from endoxa.governance import Assertion, PremiseSet

premises = PremiseSet(
    assertions=(
        Assertion(id="old", atom="location(parcel,office)", truth_value=True, confidence=0.4),
        Assertion(id="new", atom="location(parcel,depot)", truth_value=True, confidence=0.8),
    ),
    functional_predicates={"location"},
)
remaining = replace(premises, assertions=tuple(record for record in premises.assertions if record.id != "old"))
assert remaining.functional_scope == premises.functional_scope
assert "location(parcel,office)" in remaining.functional_scope
```

Rebuilding a snapshot from only remaining records could lose the old value's
exclusion even though a Rule can still derive it. Preserve scope across withdrawal
and later checks. Proposals add a candidate Assertion's atom to the checking scope
and keep that scope fixed even for the original-state and rejection checks.
`binding.premises` retains the original input separately;
`binding.functional_scope` records the candidate-inclusive scope. Validate and
retain the latter for [application](application-and-migration.md#before-applying-a-proposal).

[Revision proposals](revision.md) · [Back to README](../README.md)
