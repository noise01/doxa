# endoxa

**Governed beliefs for agents.** An append-only ledger, SMT-checked consistency,
defeasible revision, and calibration instruments — a layer you give an agent,
not a framework you build one inside.

> **Status: pre-alpha.** The library was extracted whole from the research system
> it grew in, where it has run for months. Versions before 1.0 may move the public
> API: what is shown below is where the extraction landed, not a promise.

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
    Belief(target="human(socrates)", truth_value=True, confidence=1.0, context="user"),
    Belief(target="mortal(socrates)", truth_value=False, confidence=0.6, context="agent"),
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

Three runnable scripts go further — what happens over a run of turns, what a
conflict that cannot be settled looks like, and what the instruments report. See
[examples/](examples/).

## Entailment and independent support

```python
from endoxa.governance import Belief, check_entailment, check_belief_support
from endoxa.solver import Bool

p = Bool("p")
check_entailment([p], p).verdict  # "ENTAILED": premises retain the conclusion
beliefs = [Belief("human(socrates)", True, 0.7)]
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
truth value. An explicit `atom` allows an arbitrary `target` ID; without it,
the target retains its legacy meaning as flat ground atom text. Predicates and
constant arguments start with a lower-case letter. Nested terms and formula
beliefs are not supported. Missing or duplicate IDs
are `InvalidArgumentError`; malformed atoms are `RuleSyntaxError`. Invalid
inputs are errors, not UNKNOWN, and no belief is silently omitted.

The legacy `endoxa.governance.revision.entails` is unchanged: it excludes the
target, returns three strings, and does not check premise consistency first.
The new functions are additive, not aliases that change that behavior. They do
not revise beliefs, ground a conclusion, or change FOF role interpretation.

## Explicit identity and recorded metadata

```python
from endoxa.governance import Belief, LedgerOp, reconstruct_view

belief = Belief.from_atom(
    id="belief:17",
    atom="human( socrates )",
    truth_value=True,
    confidence=0.7,
    stance="hypothesis",
    source="tool",
)
assert belief.id == belief.target == "belief:17"
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

The original four positional `Belief` arguments remain valid. `atom`, `stance`
and `source` are keyword-only; `id` is a read-only alias of `target`. The new
factory normalizes flat ground atom whitespace but never normalizes IDs.
Explicit confidence must be finite and between 0 and 1, and truth values must
be Boolean. The legacy constructor's existing numeric behavior is unchanged.

`govern` refuses duplicate IDs, belief/rule ID collisions and multiple IDs for
one atom, in either polarity. This replaces ambiguous core attribution with an
error. Revision, link checks, supersession (`escalated`), holds and operations
use IDs for references and atoms for formulas. Low-level cores remain Exprs,
paired with an expression-to-ID map. Legacy low-level dictionaries still use
their keys as formulas; explicit dictionaries carry `atom` in each row.
Support queries allow multiple IDs for an atom and exclude every one.

`stance` is `asserted` or `hypothesis`. When absent, the old context comparison
remains the fallback. Explicit stance conflicting with a nonempty context is
refused. `source` is an optional member of `SOURCE_KINDS`; it supplies neither
stance nor confidence. Existing policy remains: confidence 1.0 protects an
assertion, while a hypothesis is still revisable at 1.0.

Record atom and stance on the initial ledger assertion, with source when known,
before appending ID-only operations. Replay refuses another atom, origin kind
or target kind for the same explicit belief ID; polarity and explicit stance
may change. An omitted field leaves recorded metadata untouched. Actor remains
the writer, not the origin or standing. Old ledgers keep their original
actor/context replay and leave new metadata as None. The strict `to_belief`
conversion requires recorded atom, stance and confidence; it never guesses
missing metadata or reconstructs a belief from a partial operation series.

`to_record` and `from_record` are plain field codecs for a host to persist and
restore. They do not provide storage, migrate a database or change retrieval
policy. Preserve ID, atom and recorded stance/source across paging. Historical
atoms may use different IDs; governance requires unique atom ownership in the
current snapshot. Comparing truth/confidence with `compare_to_state` remains
its existing contract, not a metadata-equivalence certificate.

## Strict additive FOF entry points

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
The old `parse_fof`, `Rule` constructor and `revision.entails` keep their existing
role acceptance and semantics.

## Compatibility during migration

The additive entry points do not silently redirect the old ones:

| Existing entry point | Additive entry point | Choice the consumer makes |
| --- | --- | --- |
| Positional `Belief(target, truth_value, confidence, context)` | `Belief.from_atom`, keyword-only atom/stance/source | Record separate identity and formula explicitly. |
| `Rule` constructor and `parse_fof` | `Rule.from_fof`, `parse_premise_fof`, `parse_query_fof` | Adopt closed-formula and role validation. |
| `revision.entails` | `check_entailment`, `check_belief_support` | Adopt premise consistency checking and four distinct verdicts. |
| `reconstruct_view` of old ledger entries | `BeliefState.to_belief` of fully recorded entries | Keep ordinary replay; opt into strict explicit-belief conversion separately. |

Old `entails` remains a self-excluding refutation query with a permissive fact
parser. Inconsistent remaining premises can still yield ENTAILED there. A
consumer must explicitly adopt the guarded query to change that behavior.
UNKNOWN never supplies a consistency or support certificate. Solver round and
match limits apply per check, including revision rechecks; consumers still have
to pass their budgets at every call boundary.

Compatibility paths are retained for consumers still using them. Removal needs
an inventory with no remaining old consumers, validated replacements for their
behavior and stored records, and an explicit compatibility decision. No removal
date or version is promised. The ordinary legacy ledger fold remains supported;
strict conversion is an additional opt-in operation, not a prerequisite for it.

The [consumer contract tests](tests/test_consumer_contract.py) exercise the old
constructor positions and refutation behavior, and run a minimal independent
consumer in a fresh interpreter with an import fence. They complement the
query, revision-budget and ledger tests; they do not certify a particular
consumer's database migration or an installed release.

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
