# endoxa

**Governed beliefs for agents.** An append-only ledger, SMT-checked consistency,
defeasible revision, and calibration instruments — a layer you give an agent,
not a framework you build one inside.

> **Status: pre-alpha.** Versions before 1.0 may move the public API.
> Review the changelog when upgrading.

## The problem

An LLM agent will tell you Socrates is mortal, and twenty turns later that he is
immortal, and never notice. It has no place to put a claim other than its own
context, no way to check a new claim against the ones it already made, and no
record of why it believes any of them. Asking it to be consistent is asking the
thing that lost track to keep track.

endoxa is the place to put them.

## What it does

- **Checks.** Beliefs and the rules they live under go to a bundled SMT solver,
  which answers satisfiable, unsatisfiable, or *unknown* when its deliberation
  budget runs out — a real answer, not a failure.
- **Decides.** On a conflict it finds what is actually to blame and orders the
  candidates by how readily each may be given up. A rule the agent *learned* may
  be retracted; a rule it was given may not.
- **Holds.** When two beliefs are equally credible, the conflict cannot be
  settled from the inside. That is a state with a name, not a coin flip.
- **Records.** Every operation is an entry in an append-only ledger. A retracted
  belief keeps its row and stops counting, so the history of what the agent
  believed survives the change.
- **Measures.** Whether the agent's confidence matched its accuracy, over what it
  claims to know, what it claims to be able to do, and when it chooses to ask.

## Example

```python
from endoxa.governance import Belief, Constraints, Rule, govern

constraints = Constraints(
    rules=(
        Rule(
            name="mortality",
            axiom="fof(m, axiom, ![X]: (human(X) => mortal(X))).",
            confidence=0.9,
        ),
    ),
)
beliefs = [
    Belief(truth_value=True, confidence=1.0, id="human(socrates)", atom="human(socrates)", stance="asserted"),
    Belief(truth_value=False, confidence=0.6, id="mortal(socrates)", atom="mortal(socrates)", stance="asserted"),
]

outcome = govern(beliefs, constraints)

outcome.consistent  # False

# The operations to perform, in order: here, retracting the 0.6-confidence
# claim -- not the rule, and not the one the user asserted.
outcome.ops
```

`govern` decides; it does not mutate. The operations it returns are what you
append to the ledger and apply to your own store.

`outcome.consistent` is `True` for SAT, `False` for a detected conflict or
recency supersession, and `None` when the solver returns UNKNOWN. An inconclusive
check returns no operations; it is not a consistency certificate.
`outcome.undecided` instead means a conflict is known but no operation was selected.

`govern` and the revision queries accept `max_rounds` (quantifier-instantiation
rounds) and `max_matches` (candidate bindings examined across those rounds).
Each limit applies to **each solver check**, including candidate re-checks, and
is renewed for the next check. `None` leaves that dimension unbounded. These are
neither a cumulative governance budget nor a wall-clock deadline; a round limit
alone does not bound matching work inside a round.

Runnable scripts cover revision, unresolved ties, instruments, a direct ledger
and solver expressions. See [examples/](examples/).

## A ledger without events

`LedgerOp` is the core data contract. You own the sequence and its persistence;
`reconstruct_view` folds operations in their supplied order, without sorting
timestamps. Append the operations returned by `govern` to that same sequence.

```python
from endoxa.governance import LedgerOp, reconstruct_view

ledger = [
    LedgerOp(
        "assert",
        "reading:1",
        truth_value=True,
        confidence=0.7,
        atom="door_closed(room)",
        stance="hypothesis",
        source="tool",
    ),
    LedgerOp("confirm", "reading:1", actor="observer"),
]
state = reconstruct_view(ledger)["reading:1"]
assert state.to_belief().atom == "door_closed(room)"
assert state.source == "tool"
assert len(ledger) == 2
```

`derive_ledger` is an optional adapter for the existing audit-row dialect defined
in `endoxa.governance.derive`. Its input has `id`, `timestamp`, `event_type` and
`payload` fields and uses the supported event-name constants. It retains its
conversion rules and diagnostic counts. A new integration can write `LedgerOp`
directly; it does not need to reproduce that event vocabulary.

## Public expression and link interfaces

Import solver constructors and AST types from `endoxa.solver`. `BoundVar` is a
factory; `BoundVarExpr` is its AST class for annotations and `isinstance` checks.
`MultiPattern` is a factory and `Pattern` its AST class. The other public AST
types are `Expr`, `Var`, `Const`, `FuncDecl`, `App` and `Quantifier`.

```python
from endoxa.solver import BoundVar, BoundVarExpr, Function, MultiPattern, Pattern, USort, to_tptp_expr

item = USort("item")
x = BoundVar("X", item)
assert isinstance(x, BoundVarExpr)
f = Function("label", item, item)
assert isinstance(MultiPattern(f(x)), Pattern)
assert to_tptp_expr(f(x)) == "label(X)"
```

`to_tptp_expr` serializes an expression body, including terms. It does not add a
`fof(name, role, body).` wrapper or choose a FOF role. Serialization behavior is unchanged.

`PredicateConstraints.revision_candidates()` enumerates exclusion and implication
links in deterministic order for possible retraction. Single-valued predicates are excluded from that list
and continue to participate in recency supersession.

## Entailment and independent support

```python
from endoxa.governance import Belief, check_entailment, check_belief_support
from endoxa.solver import Bool

p = Bool("p")
check_entailment([p], p).verdict  # "ENTAILED": premises retain the conclusion
beliefs = [Belief(truth_value=True, confidence=0.7, id="human(socrates)", atom="human(socrates)", stance="asserted")]
check_belief_support(beliefs, [], "human(socrates)").verdict  # "NOT_ENTAILED"
```

Both functions return an `EntailmentResult` with `premises_status` and
`query_status`. Premises must first be SAT. UNSAT premises produce
`INCONSISTENT_PREMISES`; UNKNOWN premises produce `UNKNOWN`. Neither proceeds
to the query, so `query_status` is `None`. Otherwise, the query checks premises
with the negated conclusion: UNSAT means `ENTAILED`, SAT means `NOT_ENTAILED`,
and UNKNOWN means `UNKNOWN`. Both budgets apply separately to each check.

`check_entailment` accepts Boolean `Expr` formulas in propositional logic or
uninterpreted first-order logic with equality. Bool symbols are propositional
constants; first-order variables must be quantified over uninterpreted sorts.
Quantified solving is incomplete. Integer terms, arithmetic, free first-order
variables and bare patterns are refused.

`check_belief_support` accepts a sequence of `Belief`, rule expressions and a
target ID. It removes all beliefs with the same atom in either polarity,
including whitespace variants with different IDs. `truth_value=False` queries
the negated atom; the default queries its positive form regardless of its stored
truth value. An explicit atom has an independent ID;
belief atoms are explicit flat ground atom text. Predicates and
constant arguments start with a lower-case letter. Nested terms and formula
beliefs are not supported. Missing or duplicate IDs
are `InvalidArgumentError`; malformed atoms are `RuleSyntaxError`. Invalid
inputs are errors, not UNKNOWN, and no belief is silently omitted.

`endoxa.governance.revision.check_atom_support` checks the positive atom's
independent support from explicit revision maps, including when it is not held.
It returns the same four-verdict `EntailmentResult`; inconsistent premises do not
support a conclusion. This query accepts atom text directly, so the atom need
not already be held. It always queries the positive form and excludes every
observation of that atom in either polarity. In contrast, `check_belief_support`
resolves a held ID and accepts an explicit query polarity. Each map entry needs
a nonempty string ID and a separate `atom` field; supplied `truth_value` must be
Boolean and omission means true. Both queries stop after UNSAT or UNKNOWN
premises, without querying a conclusion.

## Explicit identity and recorded metadata

```python
from endoxa.governance import Belief, LedgerOp, reconstruct_view

belief = Belief(
    id="belief:17", atom="human( socrates )", truth_value=True, confidence=0.7, stance="hypothesis", source="tool"
)
assert belief.id == "belief:17"
assert belief.atom == "human(socrates)"
assert Belief.from_record(belief.to_record()) == belief

birth = LedgerOp(
    op="assert",
    target=belief.id,
    truth_value=belief.truth_value,
    confidence=belief.confidence,
    actor="observer",
    atom=belief.atom,
    stance=belief.stance,
    source=belief.source,
)
restored = reconstruct_view([birth])[belief.id].to_belief()
assert restored == belief
```

`Belief` requires keyword-only `id`, `atom`, `truth_value`, `confidence` and
`stance`. `source` is optional. Atom whitespace is normalized; IDs stay opaque.
Confidence must be finite and between 0 and 1, and truth values must be Boolean.
Record codecs require these explicit fields and do not infer missing metadata.

`govern` refuses duplicate IDs, belief/rule ID collisions and multiple IDs for
one atom, in either polarity. This replaces ambiguous core attribution with an
error. Revision, link checks, supersession (`escalated`), holds and operations
use IDs for references and atoms for formulas. Low-level cores remain Exprs,
paired with an expression-to-ID map. Low-level revision dictionaries require
`atom` in each row and explicit `stance` where revision preference is used.
Support queries allow multiple IDs for an atom and exclude every one.

`stance` is `asserted` or `hypothesis`, chosen by the caller independently of
writer attribution and source. Source kinds are `user`, `tool`, `corpus` and
`derivation`; omission means unknown, not an inferred origin. Ledger replay keeps
old records readable with missing metadata. `BeliefState.to_belief()` requires
recorded atom, stance and confidence before producing a governable belief.

## Strict FOF entry points

```python
from endoxa.governance import Rule, parse_premise_fof, parse_query_fof

text = "fof(mortality, hypothesis, ![X]: (human(X) => mortal(X)))."
name, role, expression = parse_premise_fof(text)
assert (name, role) == ("mortality", "hypothesis")
rule = Rule.from_fof(text, name="rule:17", confidence=0.9, defeasible=False)
assert rule.name == "rule:17" and rule.axiom == text
assert parse_query_fof("fof(question, conjecture, mortal(socrates)).")[:2] == (
    "question",
    "conjecture",
)
```

Premises and `Rule.from_fof` accept only axiom, hypothesis and assumption;
queries accept only conjecture. Other roles, multiple statements, open formulas
and unsupported syntax are refused. Both parsers retain name, role and Expr,
with the same Boolean/uninterpreted fragment as `check_entailment`. The rule's
operation ID defaults to the FOF name; an override leaves the original
annotated text intact. Roles never supply source, stance or defeasibility.
The `Rule` constructor and governance's hard axioms use the same strict premise
validation. `Rule.from_fof` additionally reads a default ID from the FOF name.
The general `parse_fof` parser can read other roles; it does not designate a
formula as a valid governance premise.

## Upgrading from 0.5.0

Version 0.6.0 uses explicit belief fields and revision-map atoms. Migrate
callers before using it: `target` and `context`, `Belief.from_atom`, `entails`,
`acquired_links` and `to_tptp` are removed. Use `Belief`, consistency-guarded
support queries, `revision_candidates` and `to_tptp_expr` respectively.

Historic ledger rows still replay without inventing atom, stance or source.
This data-reading contract is separate from constructing new API records.

## Install

**Requires Python 3.14 or newer.** That floor is real rather than cautious: the
package is written in 3.14 syntax and will not parse on an older interpreter. If
`pip` declines to install this, that is why.

```bash
pip install endoxa
```

The core takes one dependency. Two packages need more and are opt-in:

```bash
pip install "endoxa[trace]"     # the ordered series of an agent's propositions
pip install "endoxa[coverage]"  # how densely rules connect predicates
```

## What this is not

- **Not a reasoner.** endoxa does not decide whether a claim is true. You hand it
  beliefs and the rules they live under, and it answers whether they can hold
  together and what to give up when they cannot. Where the beliefs came from is
  your side of the line — it makes no model calls and reads no context.
- **Not a knowledge base.** The ledger is the record of one agent's beliefs over
  a run: small enough to fold in memory, ordered because the order is what makes
  it a history. There is no query language and no index, and where storage
  appears at all it is a Protocol for you to implement — no backend ships here.
  To ask what the world contains, this is the wrong shape; to ask what this agent
  committed to and when it stopped, it is the right one.
- **Not a general-purpose SMT solver.** The bundled one answers a single question
  on the fragment that question needs. Z3 is faster, more complete, and decides
  theories this has never heard of — arithmetic, arrays, bitvectors — and if
  solving is the job you have, that is the tool for it. This one is here because
  it arrives with `pip`, and because its verdicts land in the same ledger as
  everything else.
- **Not a new idea.** Truth maintenance is Doyle, 1979; the assumption-based
  version is de Kleer, 1986; defeasible reasoning has decades behind it, and the
  hard questions were asked long before this was written. What is here is that
  machinery given a ledger, calibration instruments, and a surface an agent loop
  can call. If you know TMS, you already know the middle of this.
- **Not measured against the alternative.** There is no benchmark here, and no
  claim that an agent using this is more consistent, better calibrated, or more
  anything than one that is not. That would take an experiment, and there is not
  one to point at. What *is* checked is narrower and duller: that the solver
  agrees with Z3 where both are complete, that the ledger folds to the view it
  reports, that the examples do what they say. Those live in the test suite, and
  they are the claims this makes.

## Design notes

- **The solver is bundled and frozen.** endoxa answers about consistency without
  reaching for an external prover. Its verdicts are checked against Z3's over
  generated formulas in two fragments — propositional, and equality with
  uninterpreted functions — chosen because both solvers are *complete* on them, so
  a disagreement is a bug rather than an artefact of one giving up first.
  Quantifier instantiation sits outside that on purpose: it is anytime, and
  answers `UNKNOWN` when its budget runs out, which is a correct answer and not
  one a verdict comparison can score. That part has ordinary tests instead. The
  differential needs Z3, which is a dev dependency and is not shipped.
- **The ledger is the record, not a cache.** Operations are appended; the current
  view is folded from them. An unsettleable conflict appears in that view as
  `UNRESOLVED` rather than as a silent choice.
- **Instruments are imported by nothing else.** A measure its subject can reach
  is a measure its subject can move, so the dependency is forbidden by contract
  and checked in CI.
- **One name catches everything this raises.** `endoxa.errors.EndoxaError` is the
  base of every error the library raises on its own behalf, and no dependency's
  exceptions reach past the boundary — a malformed rule is a `RuleSyntaxError`,
  not the grammar library's business. Each class is also the built-in you would
  have reached for anyway, so `except ValueError` keeps working.
- **Requires Python 3.14+.**

## Issues

Issues are open and they are read. What is not offered is a response time: this
is one person's pre-alpha library, so a report may sit for a while and a pull
request may sit longer. Filing one is still the best way to move something up
the list — what is reported is what gets looked at first.

Security reports go through [private advisories](https://github.com/noise01/endoxa/security/advisories/new)
rather than public issues. See [SECURITY.md](SECURITY.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
