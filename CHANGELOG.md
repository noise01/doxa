# Changelog

Versions follow [semantic versioning](https://semver.org). Before 1.0.0 a release
may move the public API: what it looks like now is where the extraction landed,
not a promise.

## [Unreleased]

### Fixed

- `govern` no longer reports an UNKNOWN solver verdict as consistent.
  `GovernanceOutcome.consistent` is now `bool | None`: existing SAT/conflict and
  supersession results keep their Boolean values; UNKNOWN returns `None` with no
  operations. `undecided` retains its separate meaning of a known conflict with
  no selected operation. Callers that treated every falsey value as a confirmed
  conflict must distinguish `None` explicitly. Field order is unchanged.
- Governance and revision queries propagate both `max_rounds` and `max_matches`
  through candidate, rule, link, support and tie-completion re-checks. Existing
  positional inputs remain valid and the new caps are keyword-only. Limits apply
  per solver check, not cumulatively to the search or as a wall-clock guarantee;
  either omitted limit remains unbounded. An UNKNOWN fact trial cannot select a
  revision through the link-clash progress fallback.
- TPTP output preserves every operand of n-ary `And` and `Or`, including
  flattened nested connectives. Binary spelling, including implication arrows,
  and the existing zero/one-operand normalization are unchanged.

### Added

- Check legacy constructor positions and refutation behavior, plus the public
  governance API from a minimal independent consumer in an isolated process.
  Document the explicit choices when adopting the additive entry points and
  the conditions for future compatibility cleanup, without a removal deadline.

- Add explicit Belief atom/stance/source fields, a separate-ID `from_atom`
  factory, ID alias and plain field record codecs. Governance and revision
  resolve formulas from atoms and return IDs through operations, cores and
  holds. Governance rejects duplicate IDs, duplicate atom ownership and
  belief/rule ID collisions; support excludes all aliases of its target.
- Ledger operations and reconstructed states retain optional explicit
  atom/stance/source. Replay refuses an ID's changing atom or origin kind,
  while explicit stance updates can move a preference band. Actor stays the
  writer. Legacy replay and missing metadata remain distinct; strict restore
  refuses to guess a belief from unrecorded fields.
- Add `parse_premise_fof`, `parse_query_fof` and `Rule.from_fof` for strict
  single closed Boolean FOF statements. Names and source text are preserved;
  premise/query roles are checked without assigning priority or provenance.
  Legacy constructors, FOF parser and entailment query remain compatible.

- Add `check_entailment`, `check_belief_support` and `EntailmentResult` to
  `endoxa.governance`. Both queries require SAT premises before testing the
  conclusion and distinguish inconsistent premises from UNKNOWN. Ordinary
  entailment retains the conclusion in its premises; support excludes all
  beliefs with the same ground atom in either polarity. Invalid inputs are
  rejected explicitly. The existing `revision.entails` behavior is unchanged.

- **`compare_to_state` names the target it counted as `unattributed`.** The
  column had a count and no line: a target whose evidence tally disagreed was
  counted and named nowhere, while `truth` and `confidence` each wrote a line
  naming the target and both sides. A caller reading the count *during* a run
  could not go on to ask which belief it was, and it could not ask afterwards
  either — the belief store a caller compares against is a working set, so by
  the end of a run the target has usually paged out and is counted in
  `missing_from_state` instead. The count was a lower bound on a question
  nobody could then answer.

  The line joins the other two in `details`, in the same shape, opening with the
  name of the column it was counted in — `unattributed <target>:
  ledger=(for,against) beliefs=(for,against)` — so a caller selects a column by
  prefix. Nothing else moved: the counts, the exclusions and the early exit past
  the credence test are unchanged, and a target whose tally agrees still writes
  no line.

  `compare_to_state` also gets its first tests in this repository. It had none;
  what exercised it lived in a consumer this package cannot see.

- **`governance.provenance` is back, exported, and tested — the names only.**
  0.2.0 removed it under a rule worth keeping: exported by nothing, imported by
  nothing, tested by nothing, 118 lines on no execution path. Two of those three
  were true from in here and false outside. The consumer these names were written
  for is a private host this package cannot see, so "imported by nothing" meant
  "by nothing visible" — thirteen call sites, as it turns out — and the unit
  tests existed the whole time, over there, where they could not count. The half
  that was true without qualification is that `__all__` never exported it, and a
  name outside the API is a name nobody here has a reason to keep. So the return
  comes with the two things the deletion rule actually reads: `SOURCE_KINDS`,
  `RETRIEVAL_KINDS` and `PROVENANCE_KEYS` are exported from `endoxa.governance`,
  and `tests/governance/test_provenance.py` holds them.

  What did **not** come back is the mapping from a host's write roles onto these
  names. It read words like `conjecture` and `observation` that belong to one
  host's schema, and a package that cannot see its consumers has no business
  holding a vocabulary belonging to one of them. The module's own line already
  said as much — fixing the names is its whole job, and deciding which one
  applies is the host's. The split is that sentence applied to the module
  itself, and a test asserts the module stayed data, so putting the mapping back
  would be a decision rather than a drift.

- **A "What this is not" section in the README.** Five things this is not: a
  reasoner, a knowledge base, a general-purpose SMT solver, a new idea, or
  measured against the alternative. The last is the point of the section — there
  is no benchmark here and no claim that an agent using this is better at
  anything than one that is not, and saying so plainly is more use to a reader
  than saying nothing. The other four answer the questions a reader arrives with,
  in the place they arrive.
- **The boundary rules now read the documents as well as the source.** Every rule
  in `tests/test_package_boundary.py` was written against `.py` files and swept
  `src/` and `tests/`, which left every markdown file in the project outside all
  of them — including the README, the most-read file here and the one where a
  name from the private repository would do the most damage. Nothing was wrong in
  the 25 documents when they were brought in; the point is that nothing could
  have said so, and all five checks would have stayed green. The sweep globs
  rather than lists, so a new documentation directory cannot escape it quietly.
  This log is exempt from the rules about pointers, and only those: an entry
  about a change that forbade a form has to be able to show the form, and a
  release note sends nobody after a document. A test asserts that the exemption
  is still load-bearing, so it goes when the reason for it goes.

## [0.4.0]

Three deferred items, each of which found something once it was looked at
properly. The theme is the same in all three: a number nobody measured, a claim
nobody checked, a rule nobody could see through.

### Changed

- **Importing this package no longer builds a parser.** Compiling the TPTP
  grammar and loading the library that compiles it cost about seventy
  milliseconds, and every caller paid them at import — including one that only
  reads a ledger, and one that only counts Brier scores, neither of which parses
  anything. The grammar moved to `solver.parsers._grammar`, loaded on the first
  parse and held from then on.

  | import | before | after |
  | --- | ---: | ---: |
  | `endoxa.solver` | 101 ms | 33 ms |
  | `endoxa.governance` | 111 ms | 48 ms |
  | `endoxa.instruments.calibration` | 121 ms | 56 ms |

  A first parse costs 67 ms once; every parse after it is unchanged. Nothing in
  the public API moved — `parse_fof` and `to_tptp` are still
  `endoxa.solver`'s. What did move is the module-level `parser` object inside
  `solver.parsers.tptp`, which was never exported and which that package's own
  docstring tells callers not to reach for.

- **A test holds it there.** One top-level `from lark import ...` put back
  anywhere undoes the whole thing, silently, with every other test still
  passing. Each check runs in a fresh interpreter and asserts the library is
  absent from `sys.modules`, with a control asserting it is present after a
  parse — otherwise the check proves nothing.

- **Coverage is measured in CI, with a floor.** Branch coverage, 86.6–87.4%
  across runs, held at 85 as a ratchet — a drop worth noticing becomes something
  someone decided rather than something that happened. The floor sits below the
  low end rather than below the mean, because part of the suite is a random sweep
  and the number moves; a floor set at the figure a run reports fails on an
  unlucky one. Branch rather than line: a line that ran is not a line whose
  alternatives ran, and the difference here is two points.

  Measuring it found something the aggregate had been hiding. With the grammar
  moved out, what remained of `solver.parsers.tptp` — the write-out half, all of
  it public — measured **16%**: `to_tptp` is exported from `endoxa.solver` and no
  test had ever called it. Writing those tests found two more things:

  - **`to_tptp` could produce text `parse_fof` refuses.** It writes `$true` and
    `$false` for the Boolean constants, and the grammar knew neither word. The
    two are exported side by side; they agree now, and a round-trip test over
    sixteen formulas says so.
  - **A branch in the writer that could only ever be wrong.** It special-cased a
    declaration named `Implies`, but `Implies` builds `Or(Not(p), q)` and no
    declaration of that name is ever created — so the branch could only fire on a
    caller's own predicate called `Implies`, and would have written it out as a
    connective. Removed, with a test pinning that such a predicate stays one.

- **The Z3 differential covers equality now, not only propositions.** The README
  said the solver's correctness is "asserted differentially against Z3". The
  harness's own docstring was precise — "deliberately restricted to
  quantifier-free propositional logic" — but the summary a reader sees was not,
  and the congruence closure underneath, which is most of what makes this an SMT
  solver rather than a SAT solver, was outside it.

  Added a second fragment: constants and uninterpreted functions over one
  uninterpreted sort, compared with `=`. Chosen on the same principle as the
  first — both solvers are complete on it, so a disagreement is a bug rather than
  one of them giving up first. `theories/euf.py` goes from 90% to **98%**.

  The generator needed a shove to be worth anything. Random equalities are
  satisfiable 295 times in 300, so a batch of them exercises the easy half of the
  solver and calls it coverage; it now mixes in shapes that need congruence and
  transitivity, and a test asserts the batch stays between 20% and 80%
  unsatisfiable rather than merely containing one of each.

  **Quantifiers stay outside, and the README now says so.** Instantiation here is
  anytime and answers `UNKNOWN` when its budget runs out — a correct answer, and
  not one a verdict comparison can score.

- **The former package name was still in the differential harness.** Ten
  occurrences, in identifiers: `render_doxa`, `_doxa_verdict`,
  `test_doxa_solver_agrees_with_z3`. A check had reported the tree clean, because
  it looked for the name with a word boundary on each side — and an underscore is
  a word character, so `doxa` matches none of those. Renamed, and the
  boundary test now looks for it with a rule that can see an identifier, with a
  control demonstrating what the obvious rule misses.

## [0.3.0]

A caller who wants to handle a bad rule string can now name what gets raised.
Before this the answer was `lark.exceptions.UnexpectedToken`.

### Added

- Add explicit Belief atom/stance/source fields, a separate-ID `from_atom`
  factory, ID alias and plain field record codecs. Governance and revision
  resolve formulas from atoms and return IDs through operations, cores and
  holds. Governance rejects duplicate IDs, duplicate atom ownership and
  belief/rule ID collisions; support excludes all aliases of its target.
- Ledger operations and reconstructed states retain optional explicit
  atom/stance/source. Replay refuses an ID's changing atom or origin kind,
  while explicit stance updates can move a preference band. Actor stays the
  writer. Legacy replay and missing metadata remain distinct; strict restore
  refuses to guess a belief from unrecorded fields.
- Add `parse_premise_fof`, `parse_query_fof` and `Rule.from_fof` for strict
  single closed Boolean FOF statements. Names and source text are preserved;
  premise/query roles are checked without assigning priority or provenance.
  Legacy constructors, FOF parser and entailment query remain compatible.

- **`endoxa.errors`.** Every error this package raises on its own behalf derives
  from `EndoxaError`, and each also derives from the built-in a caller would
  reach for without knowing about the module — `RuleSyntaxError` is a
  `ValueError`, `SortMismatchError` is a `TypeError`. Catching either works;
  `EndoxaError` additionally tells you whose failure it was. `InternalError` is
  kept separate from the rest on purpose: the others say a caller asked for
  something that cannot be given, that one says the package reached a state it
  does not believe is reachable.
- **A test that reads every `raise` in the source** and fails on one outside the
  hierarchy, plus one asserting that `lark` is imported in exactly one module. A
  rule nothing checks holds until the next person who has not read it.

### Fixed

- **The grammar library reached through the public API.** `parse_fof` let its
  parser's exceptions out, and `govern` parses the rules it is handed, so
  handling a typo in an axiom meant importing `lark` to name the type — a
  dependency this package documents as an internal detail, in an exception type,
  which is API. Translated at the boundary now, with the parser's own diagnosis
  (line and column) chained as `__cause__` for anyone who wants it.
- **The TPTP grammar file was read at the locale's encoding.** No `encoding=`, so
  on Windows that is a legacy code page — and the read happens at import, so a
  file it could not decode would be an `ImportError` rather than a parse failure.

### Changed

- **CI runs on Windows and macOS as well as Linux.** The package is developed on
  Windows and was tested only on Linux, which is the wrong way round.
- **A job installs the oldest version each direct dependency allows** and runs
  the suite against it. `lark>=1.3.1` had never meant that 1.3.1 works, only that
  someone typed it. It does; now something says so.
- **Actions are pinned to commits**, with Dependabot to move them. The publish
  step is the one that matters: it holds the token that can upload to the index.
- Three raise sites that were `ValueError` are now `SolverStateError`, which is a
  `RuntimeError` — asking a solver for a model it has not computed is a state
  error rather than a bad argument. Anything catching `ValueError` there needs
  `EndoxaError` or `RuntimeError` instead.
- **The DAG contract covers top-level modules, not only packages.** `errors.py`
  is a module, and the completeness check would have let it out of the layer
  rules without saying anything.

## [0.2.1]

`py.typed` shipped in 0.1.1 and said the annotations in here are usable. For 26
of the 63 exported callables they were not, and had never been.

- **Annotations on the public API could not be read back.** Reading a signature
  -- ``typing.get_type_hints``, ``inspect.signature``, a docs generator, a
  runtime validator -- raised ``NameError`` for the whole solver construction
  API (``And``, ``Or``, ``Not``, ``ForAll``, ``Exists`` and the rest), five
  functions in ``governance``, every windowed calibration function, and both
  coverage entry points. The cause is a linter rule doing its job: an import used
  only in annotations gets moved into ``if TYPE_CHECKING`` to save import time,
  and under PEP 649 the name is then looked up, at the moment something reads the
  annotation, in a namespace that does not have it. Nothing failed at import.
  Nothing failed in a test. An annotation nobody reads cannot be caught by
  running the code, which is the whole reason it survived two releases.

  Fixed by importing those names at runtime, in the twenty-four modules that had
  moved them. ``TC001``/``TC002``/``TC003`` are switched off with the reason
  written next to them, or they would put every one of them back.
- **A test now holds the promise.** It walks every package under ``endoxa`` that
  declares ``__all__`` -- read off the source tree, not from a list that would
  need keeping in step -- and calls ``get_type_hints`` on everything exported.
  With a positive control that plants the exact shape and shows it caught.
- **``build_predicate_graph`` returns a ``PredicateGraph``.** ``nx.Graph`` is
  generic to a type checker and a plain class at runtime, so the ``nx.Graph[str]``
  that 0.2.0 introduced raised as soon as anything read the annotation. The alias
  is subscripted where it is checked and bare where it is evaluated.

## [0.2.0]

Two modules that could not be reached are gone, and a type checker now runs in
CI. The checker was the interesting half: it found a loop that could not
terminate and a comparison that could never be false, neither of which any test
was ever going to reach.

### Removed

- **`governance.provenance`** and **`solver.parsers.dimacs`**. Neither was
  exported, neither was imported anywhere in the package, and neither had a test
  — 118 lines that ran on no path. `dimacs` was also the only function here that
  read a file, in a package whose security policy names untrusted input reaching
  a parser as one of its two problem shapes; a parser nothing calls is a surface
  with no purpose. The suite passes unchanged without them, which is the whole
  argument for the removal.

### Fixed

- **A congruence merge with no terms named was a non-terminating loop.** An edge
  in the equality graph carries the two terms whose equality it rests on, and the
  explanation walk reads them back. The edge type allowed them to be absent, and
  the walk defended itself with a guard that skipped such an edge *without
  advancing to the next one*. Nothing ever built such an edge, so nothing ever
  hung; the guard was reachable only in a state no caller could produce. It is
  refused at the write now, the type no longer admits it, and the guard is gone.
- **A quantifier was rebuilt on every substitution, including the ones that
  changed nothing.** The walk decided whether to rebuild by comparing a freshly
  built *list* of patterns against the stored *tuple* of them. A list is never
  equal to a tuple however their contents match, so the test was true on every
  pass. Hash-consing returned the identical object either way, which is why this
  was invisible to every test and why the test added for it asserts that the
  rebuild does not happen rather than what came back.
- **A SAT preprocessing check could never fire.** `[[]] in clauses` asked whether
  a list-of-lists was an element of a list of clauses. The `[] in clauses` beside
  it is the one that means UNSAT.
- **Three type suppressions suppressed nothing.** Two in `governance.derive` were
  malformed — trailing prose after the error code makes the comment invalid, and
  a checker reads it as a syntax error rather than as an instruction. A third
  named a checker that is not among this project's dependencies. All three are
  replaced by the narrowing they were standing in for.
- **The TPTP transformer's annotations described the wrong things.** `term_list`
  and `app_term` were typed as receiving tokens; by the time they run, the
  grammar has already transformed their children into expressions.

### Changed

- **`mypy --strict` runs in CI**, over `src/endoxa`. Strict is what turns
  `warn_unused_ignores` on, which is the setting that would have caught the
  suppressions above the day they were written. The tests are deliberately out of
  scope: they carry untyped fixtures, private access and planted violations on
  purpose.
- **`ForAll` and `Exists` take a `Sequence[Expr]`** rather than a `list[Expr]`.
  They only iterate it. A `list` parameter is invariant, so a caller holding a
  `list` of a subclass could not pass it.
- **`SATSolver` and `SMTEngine` take a `Callbacks`** — `dict[str, Callable]`,
  named in `solver.sat.types` alongside the rest of the search vocabulary —
  rather than a bare `dict`. `Trail` takes an `AssignHook` with the signature it
  actually calls.
- **`mk_bound_var` returns a `BoundVar`**, not the `Expr` the shared hash-cons
  cache is typed to return.
- **`FuncDecl` is imported from `solver.ast.expr`**, where it is defined, rather
  than from `solver.ast.context`, which only imports it. Unchanged for anyone
  importing it from `endoxa.solver`, which is where the README says to.

## [0.1.1]

The extraction took the host's names out and did not always repair the sentences
around them. This release is that repair, and a set of checks so the next removal
cannot pass unnoticed.

- **Prose the redaction broke.** A tie that "surfaced only as a warning log in a
  warning log". A parenthetical emptied of its contents, leaving ``(..)``. A
  clause ending "extended to revision selection by", with nothing after the "by".
  Lines holding nothing but a full stop, where a citation used to end the
  sentence. And a singular noun replaced by the plural "beliefs" in nineteen
  places, so the docstrings read "the beliefs's own test" and "what the beliefs
  does". Repaired throughout.
- **References a reader could not follow.** Cross-references into modules that
  exist only in the host (``.propagation.propagate``,
  ``.memory._build_exclusion_links``, ``EventStore.get_by_types``); an ``:attr:``
  still pointing at ``BeliefState.state`` after that field was renamed to
  ``status``; section marks with no document named ("§2.10"); a decision record
  cited without its number ("Three RFCs settled on holding both"); and
  ``docs/backlog.md``, which is not in this repository. Each replaced by what it
  was trying to say, or removed.
- **"production" meant the host.** Nine places used the word for the system this
  was extracted from. An outside reader takes it for "production environment",
  which is a different claim entirely.
- **Checks for all of the above, each with a positive control.** The vocabulary
  rules already here ask whether a forbidden word survived the move; these ask
  the harder question they cannot -- whether *removing* one left a readable
  sentence. Added: the four scar shapes above, cross-references that resolve to
  nothing in this package, ADR/RFC named without a number, private document
  names, and the dotted form of a host module path (``modules.reasoning``), which
  the existing rule missed because it was written for slashes.
- **``py.typed``.** The ``Typing :: Typed`` classifier was a claim PEP 561 did
  not back: with no marker file, a downstream type checker ignores every
  annotation in here. Added, shipped in both the wheel and the sdist, and pinned
  by a test that reads the classifier and fails if the marker is missing.
- **The top-level ``__init__`` no longer promises a facade.** It described itself
  as "the facade [the exports] will land in". None is coming, and that is the
  decision rather than an unfinished one: import from the layer you mean, because
  the layer a name belongs to is the most useful thing its address can tell you.

## [0.1.0]

No API change. What moved is the evidence for it: of the two thin places 0.0.1
named in its own entry, one is now covered directly and the other turned out not
to be a gap in this package at all.

- **A policy on issues, and a place for security reports.** The tracker is open
  and read, and no response time is offered — an open tracker with nothing
  written next to it implies a maintenance commitment this cannot keep.
  Vulnerabilities go to a private advisory rather than a public issue, and
  `SECURITY.md` names the two shapes a problem here would take: rule text is
  untrusted input reaching a parser, and a consistent belief set is not a true
  one.
- **`examples/`.** Three scripts: a contradiction that only exists under a rule
  and what gives way when it surfaces; a conflict between two equally credible
  claims, which gets a name and an end with an author rather than a coin flip;
  and what the three instruments report about an agent's confidence. Each is run
  by the test suite with the numbers its prose points at asserted, because an
  example nobody executes is a promise nobody keeps.
- **Corrected what 0.0.1 said about `governance.support`.** The note claimed the
  module records a belief's footing and that nothing had exercised it. Neither
  half was right. It records nothing: it folds *resolved* support states into a
  verdict, because deciding whether an antecedent is still alive means reading a
  host's state and this package does not know what that state is. And it has had
  a direct test since the port, including the distinction the fold exists for —
  that `out` and `indeterminate` must not collapse, or a paged-out antecedent
  becomes counter-evidence against everything that once rested on it. What is
  true, and what the note should have said, is about traffic rather than
  coverage: see the amended 0.0.1 entry below.
- **The calibration accumulators are tested directly.** They were reachable only
  through the windowed recomputation that folds them, which cannot construct an
  accumulator that has seen nothing and cannot state any of their contracts on
  its own terms. Added: each type asserted directly, the empty states (no
  observations is not a score of zero), the two ask-policy rates that differ
  only in their denominator, the transitions that count as neither direction,
  and the property that folding one observation at a time agrees with computing
  over the whole stream at once. The export list of
  `endoxa.instruments.calibration` is checked against the package both ways.

## [0.0.1]

First release.

The package was lifted whole out of the research system it grew in, where it has
run for months. That is the reason it arrives with a solver, a ledger, revision
and instruments already fitted to each other, and also the reason the version is
0.0.1: it has been used by exactly one host, and an API that only ever answered
to one caller has not been tested as an API.

What is in it:

- `syntax` — the shape of an atom: predicate, arity, arguments.
- `solver` — a bundled SMT engine over uninterpreted functions and equality, with
  a deliberation budget that returns *unknown* rather than running forever. Its
  answers are asserted differentially against Z3 in dev-only tests.
- `governance` — the append-only ledger and the view folded from it, defeasible
  revision (what to blame, what may be given up, and when a conflict is genuinely
  unsettleable), and where a belief came from.
- `trace` — the ordered series of an agent's propositions. Optional; needs
  `endoxa[trace]`.
- `instruments` — calibration over knowledge, competence and the choice to ask,
  and how densely rules connect predicates. Optional for the latter, which needs
  `endoxa[coverage]`.

Known gaps, stated because the tests do not state them: the calibration
accumulators are covered indirectly at best, having been verified through the
host's own suite rather than their own, and the support fold has coverage but no
traffic — its host calls it on every pass, yet across that host's whole archive
no belief has ever been observed losing its footing, so the branch the fold
exists to get right has never once been taken outside a test.

*(Amended after release: the original wording said this module "records" a
belief's footing and "was never exercised". It records nothing, and it is
tested. The gap is the one stated above. See the 0.1.0 entry.)*

[0.4.0]: https://github.com/noise01/endoxa/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/noise01/endoxa/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/noise01/endoxa/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/noise01/endoxa/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/noise01/endoxa/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/noise01/endoxa/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/noise01/endoxa/releases/tag/v0.0.1
