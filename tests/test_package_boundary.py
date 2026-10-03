"""Checks on what this package is allowed to say, contain, and forget to declare.

Rules that were held by hand while the code was being brought over, and are held
by CI from here on. A rule nothing checks is a rule that lasts until the next
person who has not read it.

Two shapes of rule live here. The first asks whether a forbidden word survived
the move. The second asks a harder question the first cannot: whether the *edit
that removed one* left a readable sentence behind. Deleting a name and not
repairing the grammar around it passes every vocabulary check ever written, and
leaves prose like "the tie surfaced only as a warning log in a warning log" for a
stranger to read. Those leftovers have shapes -- an empty parenthetical, a line
holding nothing but a full stop, a plural handed a singular's possessive -- and
:data:`SCARS` is the list of the ones actually found in this package.

Each check is paired with a positive control that plants a violation and shows the
detector firing. A check that cannot fail is not a check, and these look for the
*absence* of things, which is exactly the shape that passes by accident.
"""

import ast
import io
import re
import tokenize
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Project identity is not part of this package's standalone interface.
#: Shared ordinary research vocabulary is allowed.
FORBIDDEN_WORDS = {"doppelganger": "another project's name"}

#: References to unavailable modules, as paths or dotted names.
HOST_PATH = re.compile(
    r"\b(?:domains|modules|runtime|faculties|interface|evals|policies|environments)(?:/|\.(?=[a-z_]))",
)

#: Citations of decision records that live in a private repository. Both the numbered
#: form and the bare one: "Three RFCs settled on holding both" sends a reader after
#: documents that are not only unopenable but unnamed.
CITATION = re.compile(r"\b(?:ADR|RFC)s?\b")

#: Documents that exist only in the repository this was extracted from.
PRIVATE_DOC = re.compile(r"\bbacklog\.md\b|\bdocs/")

#: The name this package was published under for one release, before the index
#: refused it. Deliberately **not** written with ``\b``: an underscore is a word
#: character, so ``\bdoxa\b`` matches neither ``render_doxa`` nor ``_doxa_verdict``
#: -- which is how ten of them sat in the differential harness through a check that
#: reported the tree clean. A rename hides in identifiers, which is exactly where a
#: word-boundary rule cannot look.
FORMER_NAME = re.compile(r"(?<![a-z])doxa(?![a-z])")

#: What a redaction leaves behind when the name goes and the sentence does not get
#: rewritten. Each of these was found in this package, not imagined for the test.
SCARS = {
    "an empty parenthetical -- whatever was inside it was deleted": re.compile(r"(?<=\s)\(\s*\.{0,2}\s*\)"),
    "a line holding nothing but a full stop": re.compile(r"^\s*\.\s*$"),
    "a section mark with no document to look it up in": re.compile(r"§"),
    "a plural handed a singular's possessive": re.compile(r"\b\w+s's\b"),
}

#: Words that genuinely end in ``s`` while being singular, so ``'s`` is correct English
#: on them -- including the name the test fixtures are built around. Without this the
#: possessive rule fires on ``the class's`` and becomes a rule people delete rather
#: than obey.
SINGULARS_ENDING_IN_S = frozenset(
    {"access", "basis", "class", "harness", "process", "socrates", "status", "success", "witness"},
)

CJK = re.compile(r"[　-ヿ一-鿿]")

#: Sphinx cross-reference roles, whose target has to name something this package
#: actually defines. An unresolvable one is a pointer into the host, or a rename that
#: only got applied on one side.
ROLE = re.compile(r":(?:func|mod|class|meth|data|attr|obj|exc):`~?([^`]+)`")

#: Inline code spans, replaced before the scar patterns run: ``p()`` is a call with no
#: arguments, not a parenthetical someone emptied.
CODE_SPAN = re.compile(r"``[^`]*``")

type Corpus = list[tuple[str, str]]


def _real_files() -> Corpus:
    """Every source file except this one, as ``(name, text)``."""
    paths = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tests").rglob("*.py"))
    return [
        (path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in paths
        if path.name != Path(__file__).name
    ]


#: Directories holding something other than this repository's own writing --
#: installed packages, build output, tool caches. Without this the sweep below
#: reads every markdown file every dependency ever shipped and fails on someone
#: else's prose.
NOT_OURS = frozenset(
    {".git", ".venv", "venv", "dist", "build", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache"},
)

#: The one document exempt from the pointer rules. A log of a change that forbade
#: a form has to be able to show the form: the entry for 0.1.1 quotes "§2.10" and
#: "Three RFCs settled on holding both" because those are the strings the rule was
#: built to catch, and the entry for 0.2.1 quotes the identifiers a word-boundary
#: pattern could not see. Mention is not use, and nobody reading release notes is
#: being sent after a document. The vocabulary rules still apply to it -- no
#: version of this project has release notes that need the host's name.
POINTER_EXEMPT = "CHANGELOG.md"

#: A fenced block is code, and the typographic rules are about prose. Blanked
#: rather than dropped so a reported line number is the line in the file.
FENCED = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)

#: Markdown's inline code, which the source rules meet as double backticks.
MD_CODE_SPAN = re.compile(r"`[^`]*`")


def _markdown_files(*, changelog: bool = True) -> Corpus:
    """Every markdown document this repository publishes, as ``(name, text)``.

    Swept rather than listed: a listed set is one a new documentation directory
    escapes silently, which is the failure this whole function exists to undo.
    ``_real_files`` collects ``.py`` only, so until this was written every
    markdown file in the project sat outside every rule in this module --
    including ``README.md``, the most-read file here and the one where a host
    name would do the most damage. Nothing was wrong in them when they were
    brought in. The point is that nothing could have said so.
    """
    paths = sorted(
        path
        for path in ROOT.rglob("*.md")
        if not NOT_OURS & set(path.relative_to(ROOT).parts) and (changelog or path.name != POINTER_EXEMPT)
    )
    return [(path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8")) for path in paths]


def _word_offences(corpus: Corpus) -> list[str]:
    return [
        f"{name}: {word!r} -- {why}"
        for name, text in corpus
        for word, why in FORBIDDEN_WORDS.items()
        if re.search(rf"\b{word}\b", text.lower())
    ]


def _line_offences(corpus: Corpus, pattern: re.Pattern[str]) -> list[str]:
    return [
        f"{name}:{number}"
        for name, text in corpus
        for number, line in enumerate(text.splitlines(), 1)
        if pattern.search(line)
    ]


def _prose(source: str) -> list[tuple[int, str]]:
    """Return a file's comments and docstrings as ``(line, text)``.

    String literals that are not docstrings are excluded on purpose: test data is
    allowed to contain anything, including the non-ASCII terms whose handling is
    the point of some of the tests.
    """
    found = [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                found.append((getattr(node, "lineno", 1), doc))
    return found


def _cjk_offences(corpus: Corpus) -> list[str]:
    return [f"{name}:{line}" for name, text in corpus for line, prose in _prose(text) if CJK.search(prose)]


def _prose_lines(corpus: Corpus) -> list[tuple[str, int, str]]:
    """Every individual line of prose, as ``(file, line-of-the-block, text)``.

    The line number is where the comment or docstring starts rather than where the
    offending line sits inside it -- enough to find, and it keeps this independent
    of how a docstring is indented.
    """
    return [
        (name, line, text) for name, source in corpus for line, prose in _prose(source) for text in prose.splitlines()
    ]


def _markdown_prose_lines(corpus: Corpus) -> list[tuple[str, int, str]]:
    """Every line of a markdown document, with its code blanked out.

    The counterpart of :func:`_prose_lines`, which reaches prose by tokenising
    Python. A markdown file is prose all the way down apart from its code, so the
    work here is the reverse: take the whole file and take the code out of it.
    """
    lines: list[tuple[str, int, str]] = []
    for name, text in corpus:
        blanked = FENCED.sub(lambda block: "\n" * block.group().count("\n"), text)
        lines.extend((name, number, line) for number, line in enumerate(blanked.splitlines(), 1))
    return lines


def _scar_offences(corpus: Corpus) -> list[str]:
    return _scars_in(_prose_lines(corpus))


def _markdown_scar_offences(corpus: Corpus) -> list[str]:
    return _scars_in(
        [(name, line, MD_CODE_SPAN.sub("CODE", text)) for name, line, text in _markdown_prose_lines(corpus)]
    )


def _scars_in(lines: list[tuple[str, int, str]]) -> list[str]:
    offences = []
    for name, line, text in lines:
        stripped = CODE_SPAN.sub("CODE", text)
        for why, pattern in SCARS.items():
            found = pattern.search(stripped)
            if not found:
                continue
            if pattern is SCARS["a plural handed a singular's possessive"]:
                word = found.group().removesuffix("'s")
                if word.lower() in SINGULARS_ENDING_IN_S:
                    continue
            offences.append(f"{name}:{line}: {why} -- {text.strip()[:70]!r}")
    return offences


def _prose_offences(corpus: Corpus, pattern: re.Pattern[str]) -> list[str]:
    return [
        f"{name}:{line}: {text.strip()[:70]!r}" for name, line, text in _prose_lines(corpus) if pattern.search(text)
    ]


def _class_members(node: ast.ClassDef) -> set[str]:
    """Collect a class's own name and its members, under both bare and dotted forms.

    Attributes a method assigns to ``self`` count: a class that sets its state in
    ``__init__`` declares none of them at class level, and a reference to one is
    no less resolvable for that.
    """
    names = {node.name}
    for child in node.body:
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            names |= {child.name, f"{node.name}.{child.name}"}
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            names |= {child.target.id, f"{node.name}.{child.target.id}"}
    for inner in ast.walk(node):
        assigned_on_self = (
            isinstance(inner, ast.Attribute)
            and isinstance(inner.ctx, ast.Store)
            and isinstance(inner.value, ast.Name)
            and inner.value.id == "self"
        )
        if assigned_on_self:
            names |= {inner.attr, f"{node.name}.{inner.attr}"}
    return names


def _top_level_names(node: ast.stmt) -> set[str]:
    """Return the names one top-level statement makes available under its module."""
    if isinstance(node, ast.ClassDef):
        return _class_members(node)
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {target.id for target in node.targets if isinstance(target, ast.Name)}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    if isinstance(node, ast.ImportFrom):
        return {alias.asname or alias.name for alias in node.names}
    return set()


def _module_symbols() -> dict[str, set[str]]:
    """Map each module's dotted name to the top-level names it defines or re-exports."""
    symbols: dict[str, set[str]] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        dotted = path.relative_to(ROOT / "src").with_suffix("").as_posix().replace("/", ".")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        symbols[dotted.removesuffix(".__init__")] = set().union(*(_top_level_names(node) for node in tree.body), set())
    return symbols


def _resolves(target: str, *, package: str, symbols: dict[str, set[str]]) -> bool:
    """Whether a cross-reference target names something in this package.

    ``package`` is what a leading dot means in the file the reference was written
    in: for ``__init__.py`` that is the package itself, for any other module it is
    the package the module sits in.
    """
    target = target.removeprefix("~").strip()
    if target.startswith("."):
        target = package + target
    if target in symbols:
        return True
    head, _, tail = target.rpartition(".")
    if head in symbols and tail in symbols[head]:
        return True
    return any(target in names for names in symbols.values())


def _dangling_references() -> list[str]:
    symbols = _module_symbols()
    dangling: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        dotted = path.relative_to(ROOT / "src").with_suffix("").as_posix().replace("/", ".")
        module = dotted.removesuffix(".__init__")
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        name = path.relative_to(ROOT).as_posix()
        dangling.extend(
            f"{name}:{line}: {target}"
            for line, prose in _prose(path.read_text(encoding="utf-8"))
            for target in ROLE.findall(prose)
            if not _resolves(target, package=package, symbols=symbols)
        )
    return dangling


def _contract_layers() -> set[str]:
    contracts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    layers = next(
        contract["layers"]
        for contract in contracts["tool"]["importlinter"]["contracts"]
        if contract["type"] == "layers"
    )
    return {layer.removeprefix("endoxa.") for layer in layers}


class TestVocabulary:
    """The package does not name structures that only exist somewhere else."""

    def test_no_forbidden_word_appears(self):
        offences = _word_offences(_real_files())
        assert not offences, "host vocabulary reached the package:\n" + "\n".join(offences)

    def test_a_planted_word_is_caught(self):
        assert _word_offences([("planted.py", "# doppelganger holds it")])
        assert not _word_offences([("planted.py", "# the belief set holds it")])

    def test_a_word_inside_a_longer_one_is_not_caught(self):
        """An identifier containing the project name is not a prose reference."""
        assert not _word_offences([("planted.py", "# doppelgangers are fictional")])

    def test_shared_research_vocabulary_is_allowed(self):
        assert not _word_offences([("planted.py", "# acquisition, salience and kernel methods")])

    def test_no_host_path_is_referenced(self):
        offences = _line_offences(_real_files(), HOST_PATH)
        assert not offences, "a path into the host this came from:\n" + "\n".join(offences)

    def test_a_planted_host_path_is_caught(self):
        assert _line_offences([("planted.py", "# see domains/memory.py")], HOST_PATH)
        assert not _line_offences([("planted.py", "# see endoxa/governance.py")], HOST_PATH)

    def test_no_decision_record_is_cited(self):
        offences = _line_offences(_real_files(), CITATION)
        assert not offences, "a citation of a record this package's readers cannot open:\n" + "\n".join(offences)

    def test_a_planted_citation_is_caught(self):
        assert _line_offences([("planted.py", "# see ADR-0123 for why")], CITATION)
        assert _line_offences([("planted.py", "# see RFC-0091 for why")], CITATION)
        assert not _line_offences([("planted.py", "# see the docstring for why")], CITATION)

    def test_an_unnumbered_record_is_caught_too(self):
        """Dropping the number does not make the reference followable, only vaguer."""
        assert _line_offences([("planted.py", "# Three RFCs settled on holding both")], CITATION)

    def test_the_former_name_is_gone(self):
        offences = _line_offences(_real_files(), FORMER_NAME)
        assert not offences, "the name this was published under before:\n" + "\n".join(offences)

    def test_a_planted_former_name_is_caught(self):
        """Including the two shapes a word-boundary rule cannot see."""
        assert _line_offences([("planted.py", "def render_doxa(node):")], FORMER_NAME)
        assert _line_offences([("planted.py", "x = _doxa_verdict(node)")], FORMER_NAME)
        assert _line_offences([("planted.py", "# see doxa for why")], FORMER_NAME)

    def test_a_word_boundary_rule_would_have_missed_them(self):
        """Why this pattern is written the way it is, rather than the obvious way."""
        obvious = re.compile(r"\bdoxa\b")
        assert not obvious.search("def render_doxa(node):")
        assert not obvious.search("x = _doxa_verdict(node)")

    def test_the_current_name_is_not_caught(self):
        """``endoxa`` ends in the old name and must not trip the rule."""
        assert not _line_offences([("planted.py", "import endoxa.governance")], FORMER_NAME)
        assert not _line_offences([("planted.py", "x = render_endoxa(node)")], FORMER_NAME)

    def test_no_private_document_is_named(self):
        offences = _prose_offences(_real_files(), PRIVATE_DOC)
        assert not offences, "a document only the host repository holds:\n" + "\n".join(offences)

    def test_a_planted_private_document_is_caught(self):
        assert _prose_offences([("planted.py", "# out of scope; see docs/backlog.md")], PRIVATE_DOC)
        assert _prose_offences([("planted.py", '"""The remaining work (``backlog.md`` §6)."""')], PRIVATE_DOC)
        assert not _prose_offences([("planted.py", "# out of scope; see the CHANGELOG")], PRIVATE_DOC)


class TestRedactionScars:
    """Removing a name is half the edit. These are the shapes of the other half undone."""

    def test_no_scar_survives(self):
        offences = _scar_offences(_real_files())
        assert not offences, "the redaction left the sentence broken:\n" + "\n".join(offences)

    def test_each_planted_scar_is_caught(self):
        assert _scar_offences([("planted.py", "# the solver can decide (..). What it leaves")])
        assert _scar_offences([("planted.py", '"""What the belief rested on\n\n    .\n    """')])
        assert _scar_offences([("planted.py", "# the revision target (§2.10) is picked")])
        assert _scar_offences([("planted.py", "# mirroring the beliefs's own reader")])

    def test_a_call_with_no_arguments_is_not_a_scar(self):
        """``p()`` and ``match()`` are code, and the parentheses are meant to be empty."""
        assert not _scar_offences([("planted.py", "# arity-0 atoms (``p()``) yield an empty tuple")])
        assert not _scar_offences([("planted.py", "# tested between ``match()`` calls")])

    def test_a_singular_ending_in_s_keeps_its_possessive(self):
        """``the class's`` is correct English; a rule that forbids it gets deleted."""
        assert not _scar_offences([("planted.py", "# the class's own reader")])
        assert not _scar_offences([("planted.py", "# the process's exit code")])


class TestCrossReferences:
    """Every ``:func:``/``:mod:`` target names something a reader of this package can find."""

    def test_no_reference_dangles(self):
        dangling = _dangling_references()
        assert not dangling, "a cross-reference naming nothing in this package:\n" + "\n".join(dangling)

    def test_a_planted_dangling_reference_is_caught(self):
        """Both real ones the extraction left behind: a host class, and a host module."""
        symbols = _module_symbols()
        package = "endoxa.governance.revision"
        assert not _resolves("EventStore.get_by_types", package=package, symbols=symbols)
        assert not _resolves(".memory._build_exclusion_links", package=package, symbols=symbols)

    def test_a_relative_reference_resolves_against_its_own_package(self):
        symbols = _module_symbols()
        package = "endoxa.governance.revision"
        assert _resolves(".preference", package=package, symbols=symbols)
        assert _resolves(".engine.select_verified_revision_target", package=package, symbols=symbols)
        assert not _resolves(".propagation.propagate", package=package, symbols=symbols)


class TestLanguage:
    """Comments and docstrings are English; test data may be anything."""

    def test_no_cjk_in_prose(self):
        offences = _cjk_offences(_real_files())
        assert not offences, "non-English prose:\n" + "\n".join(offences)

    def test_planted_cjk_prose_is_caught(self):
        assert _cjk_offences([("planted.py", '"""説明。"""\n')])
        assert _cjk_offences([("planted.py", "x = 1  # 説明\n")])

    def test_cjk_test_data_is_left_alone(self):
        """A string that is not a docstring is data, and data may be in any script."""
        assert not _cjk_offences([("planted.py", 'name = "エロウェン"\n')])


class TestTypingPromise:
    """The ``Typing :: Typed`` classifier is a claim, and PEP 561 is how it is kept."""

    def test_the_marker_is_present(self):
        """Without ``py.typed`` a type checker ignores every annotation in here.

        The classifier would then be advertising something no downstream project
        can actually use -- annotations written, declared, and unreadable.
        """
        classifiers = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["classifiers"]
        if "Typing :: Typed" not in classifiers:
            return
        marker = ROOT / "src" / "endoxa" / "py.typed"
        assert marker.is_file(), "the classifier claims a typing the marker does not grant"


def _units_under_the_package() -> set[str]:
    """Everything directly under ``endoxa``: subpackages, and modules beside them.

    Both, because the layers contract constrains whatever it lists and leaves
    everything else unconstrained. A rule that only counted packages would let a
    new top-level *module* out of the DAG without anything saying so -- which is
    what ``errors`` would have done.
    """
    root = ROOT / "src" / "endoxa"
    packages = {path.parent.name for path in root.glob("*/__init__.py")}
    modules = {path.stem for path in root.glob("*.py") if path.name != "__init__.py"}
    return packages | modules


class TestContractCompleteness:
    """Everything under ``endoxa`` is named by the layers contract, or it escapes it."""

    def test_the_contract_and_the_source_agree(self):
        declared, actual = _contract_layers(), _units_under_the_package()
        assert actual - declared == set(), f"outside the DAG contract: {sorted(actual - declared)}"
        assert declared - actual == set(), f"the contract names something gone: {sorted(declared - actual)}"

    def test_a_top_level_module_counts_too(self):
        """``errors.py`` is a module, not a package, and is still inside the DAG."""
        assert "errors" in _units_under_the_package()
        assert "errors" in _contract_layers()

    def test_the_comparison_is_two_way(self):
        """A new package and a deleted one are different failures, and both must show."""
        declared, actual = {"solver", "syntax"}, {"solver", "syntax", "sneaky"}
        assert actual - declared == {"sneaky"}
        assert {"solver", "syntax", "gone"} - actual == {"gone"}


class TestPublishedDocuments:
    """The rules above, applied to the markdown a reader actually arrives at.

    Every one of them was written against source and pointed only at source,
    which left the front page of the project as the one file no rule could see.
    A host name in ``README.md`` would have shipped to the index with all five
    checks green.
    """

    def test_the_sweep_reaches_the_front_page(self):
        """A glob matching nothing would pass every other test in this class."""
        names = {name for name, _ in _markdown_files()}
        assert "README.md" in names
        assert "examples/README.md" in names
        assert POINTER_EXEMPT in names
        assert not [name for name in names if NOT_OURS & set(Path(name).parts)]

    def test_no_forbidden_word_appears(self):
        offences = _word_offences(_markdown_files())
        assert not offences, "host vocabulary reached the documents:\n" + "\n".join(offences)

    def test_no_document_is_written_in_another_language(self):
        offences = _line_offences(_markdown_files(), CJK)
        assert not offences, "a document a reader of this package cannot read:\n" + "\n".join(offences)

    def test_no_host_path_is_referenced(self):
        offences = _line_offences(_markdown_files(changelog=False), HOST_PATH)
        assert not offences, "a path into the host this came from:\n" + "\n".join(offences)

    def test_no_decision_record_is_cited(self):
        offences = _line_offences(_markdown_files(changelog=False), CITATION)
        assert not offences, "a citation of a record this package's readers cannot open:\n" + "\n".join(offences)

    def test_no_private_document_is_named(self):
        offences = _line_offences(_markdown_files(changelog=False), PRIVATE_DOC)
        assert not offences, "a document only the host repository holds:\n" + "\n".join(offences)

    def test_the_former_name_is_gone(self):
        offences = _line_offences(_markdown_files(changelog=False), FORMER_NAME)
        assert not offences, "the name this was published under before:\n" + "\n".join(offences)

    def test_no_scar_survives(self):
        offences = _markdown_scar_offences(_markdown_files(changelog=False))
        assert not offences, "the redaction left the sentence broken:\n" + "\n".join(offences)

    def test_each_planted_document_is_caught(self):
        """The same controls as above, written the way a document writes them."""
        assert _word_offences([("planted.md", "The doppelganger holds it.")])
        assert _line_offences([("planted.md", "See domains/memory.py.")], HOST_PATH)
        assert _line_offences([("planted.md", "Settled in ADR-0123.")], CITATION)
        assert _line_offences([("planted.md", "Listed in docs/backlog.md.")], PRIVATE_DOC)
        assert _line_offences([("planted.md", "`render_doxa` is gone.")], FORMER_NAME)
        assert _markdown_scar_offences([("planted.md", "The revision target (§2.10) is picked.")])

    def test_a_fenced_block_is_not_prose(self):
        """An example calling ``p()`` is code, and its parentheses are meant to be empty."""
        fenced = "Before.\n\n```python\nassert p() == ()\n```\n\nAfter."
        assert not _markdown_scar_offences([("planted.md", fenced)])

    def test_a_fenced_block_does_not_shift_the_line_numbers(self):
        """Blanked rather than dropped, so a failure is reported where it sits."""
        text = "Alpha.\n\n```python\nx = 1\ny = 2\n```\n\nthe beliefs's own reader"
        (offence,) = _markdown_scar_offences([("planted.md", text)])
        assert offence.startswith("planted.md:8:"), offence

    def test_the_changelog_is_the_only_exemption(self):
        swept = {name for name, _ in _markdown_files()}
        pointed = {name for name, _ in _markdown_files(changelog=False)}
        assert swept - pointed == {POINTER_EXEMPT}

    def test_the_exemption_is_load_bearing(self):
        """If the log stops needing it, the carve-out should go rather than sit."""
        changelog = [(POINTER_EXEMPT, (ROOT / POINTER_EXEMPT).read_text(encoding="utf-8"))]
        assert _line_offences(changelog, CITATION), "the log no longer quotes what the rule forbids"
        assert not _word_offences(changelog), "the exemption does not reach host vocabulary"
