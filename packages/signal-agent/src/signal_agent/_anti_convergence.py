"""Feature 210's law: the explicit anti-convergence clause, applied.

app_spec.xml, "Hypothesis Authoring Agent", feature 210: *Agent applies an
explicit anti-convergence clause, so a tree never collapses into 400 parameter
tweaks of one indicator.*  docs/alpha-engine-prd.md §C3 is where the clause
comes from — the discovery agent's prompt adapts the paper's Listing 1
*"nearly verbatim, keeping in particular ... the explicit anti-convergence
clause.  Without it, a discovery tree collapses into 400 parameter tweaks of one
indicator."* — and docs/nullius-tech-architecture.md §14.1 says why nothing else
catches the failure::

    A bad proposal is caught by the evaluator at a cost of one trial charge.
    A converged tree is not caught by anything.  At roots, a weak model's
    failure mode is proposing the 400th variant of one indicator — every node
    scores plausibly, the budget is fully consumed, and nothing in the pipeline
    detects it.

The sentence has two halves, and this module is both of them, because either
alone is a promise rather than a property:

* **an explicit anti-convergence clause** — *explicit* is the load-bearing word.
  A clause that lives in a prompt template nobody diffs is a sentence somebody
  meant to write.  So it is a committed artifact
  (:data:`COMMITTED_ANTI_CONVERGENCE`, shipped beside this law) with its own
  compiler, and the *prompt* a campaign ships is screened against it:
  :meth:`AntiConvergenceGate.carries` and
  :meth:`~AntiConvergenceGate.require_in` answer *does this campaign's authoring
  prompt carry the clause?*, so a deployment whose prompt dropped it is refused
  by name rather than shipped with the clause silently missing.

* **so a tree never collapses into 400 parameter tweaks of one indicator** — the
  clause *applied*.  §14.1's failure mode has a precise shape: a proposal that
  differs from a node the campaign already holds **in its parameters alone**.
  Every axis this member already owns is structurally blind to it.  Feature 205
  asks whether a proposal is a conforming signal — a 400th variant is, perfectly.
  Feature 179's :class:`artifacts.CodeHashIndex` gates on *code*, and a tweaked
  lookback is different code, so it passes.  Feature 211's
  :meth:`StatedMechanism.duplicates` compares the agent's *stated claim*, and a
  weak model asked for a 400th variant states it confidently in fresh prose, so
  the claim differs too.  What is left is the axis this law owns: the proposal's
  **structure with every numeric literal erased**.

**The skeleton, and why it is the right granularity.**
:func:`proposal_skeleton` parses a source and rewrites it with
:func:`ast.unparse`, replacing every ``int``, ``float`` and ``complex`` literal
with one token, dropping docstrings, and leaving *names* alone.  Two proposals
share a skeleton exactly when they are the same expression tree over the same
identifiers with different constants — which is the definition of a parameter
tweak, and is not the definition of a structurally different hypothesis: a new
term, a different transformation, or another accessor read out of the window all
change the tree rather than its leaves.  ``bool`` is deliberately **not** erased:
``True``/``False`` select a branch rather than scale one, so flipping one is a
structural edit — the affinity trap the workspace's SQLite layer guards, guarded
here for its own reason.

**A refusal, and the three things it must not be read as.**  Refusing the 400th
tweak is not refusing *depth*: §14.1 gives depth the job of making a targeted
change to a mechanism, and a targeted change alters the tree rather than a leaf.
It is not a refusal of repeated *values*: two nodes that differ only in the
``seed`` they were run under are not this feature's concern, because the seed is
a parameter of the *contract* rather than of the mechanism, and it is an
argument the caller supplies rather than a literal the agent wrote.  And it is
not a novelty *score*: the verdict is a yes-or-no about one structure against
one campaign's history, and nothing here prices a proposal or measures how
converged a tree is — that figure is feature 215's, and it is a count of
distinct mechanism clusters rather than anything this module computes.

**Membership is per campaign.**  The comparison set is the nodes the caller
hands in, not the whole tree: PRD §9 makes the campaign the unit of search, and
two campaigns exploring one structure from different angles are two campaigns,
not one collapse.  A caller screening against an empty set therefore refuses
nothing — which is the correct answer for the first proposal of every campaign,
and the reason an empty *comparison set* is not the empty-document mistake
features 212 and 213 refuse.  This denylist is derived at run time from the
campaign's own history, so its empty case is "nothing has been proposed yet",
not "the human made no decision".

**Which polarity this gate takes.**  Like feature 213's it is a *denylist* —
``covers`` answers ``True`` when the proposal is refused — but unlike 212's and
213's, the list is not committed: :meth:`AntiConvergenceGate.covers` is the same
predicate :meth:`AntiConvergenceGate.admit` runs, answered over the same handed
comparison set, so a caller can ask *is this source a tweak of anything this
campaign holds?* without a verdict object.

**Why this is a fifth component and not a parameter of an earlier law.**  The
member's components each answer one feature's question, and the registry is
keyed by name — a fifth builder taking ``signal-agent`` would *replace* feature
205's law rather than sit beside it, the registry-replacement hazard
:data:`signal_agent.THEMES_COMPONENT_NAME` names.
``signal-agent-anti-convergence`` sorts between ``signal-agent`` and
``signal-agent-dead-territory`` in the name-sorted ``app.order``, so all five
stay contiguous in the category they belong to.

**It carries no prompt.**  The clause is read out of the committed artifact and
the campaign's prompt is handed *in*, so this component is the same stateless
law at every deployment — the shape :class:`signal_agent.SignalContract` takes
toward the contract member's ABI, and for the same reason: a component that
captured a prompt would be one whose answer about *novelty* depended on which
template happened to be loaded.

Stdlib only, and import-cheap — :mod:`ast`, :mod:`enum`, :mod:`hashlib`,
:mod:`json`, :mod:`pathlib`, :mod:`re` and the member's own modules — so the
factory's scan, which imports this package to fire its ``@register``, pays
nothing for it.
"""

from __future__ import annotations

import ast
import enum
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from . import _themes
from .errors import AntiConvergenceClauseError, AntiConvergenceError

__all__ = [
    "ANTI_CONVERGENCE_COMPONENT_NAME",
    "ANTI_CONVERGENCE_POLICY_KIND",
    "CLAUSE_ABSENT_CODE",
    "COMMITTED_ANTI_CONVERGENCE",
    "NOT_A_PROPOSAL_CODE",
    "NOVEL_CODE",
    "PARAMETER_TWEAK_CODE",
    "AntiConvergenceClause",
    "AntiConvergenceGate",
    "AntiConvergenceReason",
    "AntiConvergenceVerdict",
    "anti_convergence_gate",
    "committed_anti_convergence",
    "compile_anti_convergence",
    "load_anti_convergence",
    "proposal_skeleton",
    "skeleton_digest",
]

#: The marker a document declares itself with — the same discipline feature
#: 212's committed legal set, feature 213's committed denylist and feature 167's
#: committed import allowlist take, so a stray JSON file carrying a ``clause``
#: key cannot be read as this configuration.
ANTI_CONVERGENCE_POLICY_KIND: Final[str] = "signal-agent-anti-convergence"

#: The committed artifact, shipped beside the law that checks it, so a checkout
#: cannot hold one without the other.
COMMITTED_ANTI_CONVERGENCE: Final[Path] = Path(__file__).with_name(
    "anti_convergence.json"
)

#: The greppable code feature 210's own refusal carries — its subject written as
#: a token, so an operator grepping a campaign log for the proposals the clause
#: caught finds them by the feature's own word.  This is the code one verdict
#: carries, not the code every refusal carries: the not-a-proposal case below
#: opens with its own, for the reason
#: :attr:`AntiConvergenceReason.NOT_A_PROPOSAL` states, and the admitted case
#: opens with :data:`NOVEL_CODE`.
PARAMETER_TWEAK_CODE: Final[str] = "parameter_tweak"

#: The token every admitted proposal's sentence carries.  Its mirror is the
#: refusal, which opens with :data:`PARAMETER_TWEAK_CODE` instead; an admission
#: is not a code an operator greps a campaign for, the same asymmetry
#: :data:`signal_agent.LEGAL_THEME_CODE` has against
#: :attr:`signal_agent.ThemeReason.LEGAL`.  ``NOVEL`` rather than ``convergent``
#: because *novelty* is the property PRD §C3 and §14.1 name — "Root generation
#: demands novelty under a negative constraint" — and the polarity should read
#: as the property the gate admits on rather than the failure it screens for.
NOVEL_CODE: Final[str] = "novel_structure"

#: The code the not-a-proposal refusal opens with — its own, not
#: :data:`PARAMETER_TWEAK_CODE`, the discipline feature 212's
#: ``NOT_A_THEME_CODE`` and feature 213's ``NOT_A_ROOT_CODE`` already follow: a
#: refusal that opened with the feature's headline while its own text says there
#: was nothing to screen would be quoting the subject rather than the verdict.
NOT_A_PROPOSAL_CODE: Final[str] = "not_a_proposal"

#: The code the prompt-side refusal opens with — *the campaign's prompt does not
#: carry the committed anti-convergence clause*.  This is what the other half of
#: feature 210 is grepped by, and it is deliberately not
#: :data:`PARAMETER_TWEAK_CODE`: one refusal is about a *proposal* and the other
#: is about a *prompt*, and a deployment fault must not read as a research
#: finding.
CLAUSE_ABSENT_CODE: Final[str] = "clause_absent"

#: The component name this law registers under — beside feature 205's
#: ``signal-agent``, feature 212's ``signal-agent-themes``, feature 213's
#: ``signal-agent-dead-territory`` and feature 211's
#: ``signal-agent-stated-mechanism``.  The registry is keyed by name and a later
#: registration of the same name *replaces* the earlier one, so the category's
#: later features each take their own seat on the member rather than overwriting
#: an earlier law.  Prefixed for that reason — an unprefixed ``signal-agent`` a
#: fifth time would replace feature 205's law — and
#: ``signal-agent-anti-convergence`` sorts between ``signal-agent`` and
#: ``signal-agent-dead-territory`` in the name-sorted ``app.order``, keeping the
#: member's five components contiguous in the category they belong to.
ANTI_CONVERGENCE_COMPONENT_NAME: Final[str] = "signal-agent-anti-convergence"

#: The shape :func:`skeleton_digest` emits — lowercase sha256 hex, anchored.
#: Read by :func:`_held_digests` to tell a digest from a source, which is the one
#: inference this module makes about its caller's data.
_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

#: How many duplicate node ids a refusal's sentence names before it summarises
#: the rest.  A bound rather than the whole list because a collapse is exactly
#: the case where the list is long — §14.1's "400 parameter tweaks" — and a
#: sentence that quoted four hundred ids would be one nobody reads.  Named as
#: data so the read side and its test share one number.
_MAX_LISTED_DUPLICATES: Final[int] = 8


def _require_mapping(value: Any, what: str) -> Mapping:
    """Return ``value`` as a mapping, refusing anything else.

    A compiler that guessed at the meaning of a stray list or string would be
    writing policy rather than reading it — the stance
    :func:`signal_agent.compile_legal_themes` and
    :func:`signal_agent.compile_dead_territory` state for their own documents.
    """
    if not isinstance(value, Mapping):
        raise AntiConvergenceClauseError(
            f"{what} must be a mapping, got {type(value).__name__}: "
            f"{value!r}. An anti-convergence clause is a structured document, "
            f"and a compiler that guessed at the meaning of a stray list or "
            f"string would be writing the clause rather than reading it — "
            f"refused, fail closed (feature 210)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value.strip():
        raise AntiConvergenceClauseError(
            f"{what} must be a non-empty string, got {value!r} "
            f"({type(value).__name__}). A field that does not say what it is "
            f"cannot be trusted to say what the agent must not propose, and a "
            f"clause compiled from a blank one is a clause with a hole in it "
            f"(feature 210, refused fail closed)."
        )
    return value


class AntiConvergenceClause:
    """A compiled anti-convergence clause: the text an authoring prompt must carry.

    What :func:`compile_anti_convergence` returns is not the document — it is
    the document plus the guarantee that the clause is named, titled and
    non-empty.  Holders (the gate, an operator script, a CI check that
    recompiles the committed artifact) cite that guarantee rather than re-derive
    it — the same division feature 212's
    :class:`signal_agent.LegalThemes` and feature 213's
    :class:`signal_agent.DeadTerritory` draw for their own documents.

    **One clause, not a list.**  Features 212 and 213 compile *sets* — a legal
    space and a denylist — and their entries are interchangeable.  This document
    holds exactly one clause, because PRD §C3 names exactly one ("the explicit
    anti-convergence clause"), and a document that could hold two would make
    "does the prompt carry the clause?" a question about which one.  A
    deployment that wants a stricter clause edits this one, in review; it does
    not add a second.

    **It is prose, and the only prose this member compiles.**  Every other law
    here refuses prose as a leakage channel: feature 211's *stated mechanism* is
    the agent's rationale and is never a scored input, and feature 205's
    :meth:`SignalContract.declaration` is a mapping of facts because PRD §C3 and
    §14.1 forbid guidance in the prompt.  This clause is the exception that
    proves that rule — it is a *negative constraint*, it names no direction to
    search in, and it carries nothing distilled from campaign history.  What it
    must never grow into is a summary of what has been tried; that is feature
    208's refusal, and the read side here is the clause verbatim rather than a
    digest of it.
    """

    __slots__ = ("_text", "_title", "kind", "slug")

    def __init__(self, *, kind: str, slug: str, title: str, text: str) -> None:
        self.kind = kind
        self.slug = slug
        self._title = title
        self._text = text

    def title(self) -> str:
        """The clause's human title — the document's own name for it.

        The read side a log line and a dashboard both want: ``anti-convergence``
        is legible to the pipeline, and the title is the committed document's
        own wording rather than a second description someone wrote here.
        """
        return self._title

    def text(self) -> str:
        """The clause verbatim — the text a prompt must carry.

        Verbatim, and deliberately not a summary: the screen that follows is a
        *substring* test against exactly this text, so a read side that
        paraphrased would be one that screened prompts against a sentence the
        campaign could never have carried.  The clause is also the one thing
        here a human reviews, and a reviewer reading a paraphrase is reviewing
        the paraphrase.
        """
        return self._text

    def __len__(self) -> int:
        # The clause's length in characters.  One clause, so this is its length
        # rather than a count of entries — the one place this read differs from
        # features 212's and 213's sets, and it does so because the document
        # does.  A caller logging what it carried gets a number it can compare.
        return len(self._text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"AntiConvergenceClause(slug={self.slug!r}, chars={len(self)})"


def compile_anti_convergence(document: Any) -> AntiConvergenceClause:
    """Compile an anti-convergence clause, refusing one that cannot be read.

    The seam the configuration turns on.  The document is read whole — marker,
    then one clause — and the clause is held to the grammar before an
    :class:`AntiConvergenceClause` is handed out, so no caller ever screens a
    prompt against a clause with nothing in it.  A refusal propagates as an
    exception: a drifted artifact is never applied, because a prompt screened
    against a clause that cannot be read is a prompt screened against nothing.

    A document whose clause text is blank is **refused**, and that is the
    opposite reading from an empty *campaign* at run time — which refuses
    nothing, because a campaign with no proposals yet has nothing to have
    converged on.  The difference is *which document is empty*: a committed
    clause that says nothing is the absence of PRD §C3's decision, and a
    deployment that shipped one would be authoring with the clause missing while
    believing it had it.
    """
    doc = _require_mapping(document, "an anti-convergence clause document")

    marker = doc.get("policy")
    if not isinstance(marker, str) or not marker.strip():
        raise AntiConvergenceClauseError(
            f"an anti-convergence clause's 'policy' must be a non-empty string, "
            f"got {marker!r} ({type(marker).__name__}). A document that does "
            f"not say what it is cannot be trusted to say what the agent must "
            f"not propose (feature 210, refused fail closed)."
        )
    if marker != ANTI_CONVERGENCE_POLICY_KIND:
        raise AntiConvergenceClauseError(
            f"an anti-convergence clause must declare itself "
            f"{ANTI_CONVERGENCE_POLICY_KIND!r}, got {marker!r}. A stray JSON "
            f"file carrying a 'clause' key is not this configuration — refused, "
            f"fail closed (feature 210)."
        )

    entry = _require_mapping(doc.get("clause"), "an anti-convergence 'clause'")
    slug = _require_str(entry.get("slug"), "an anti-convergence 'slug'")
    title = _require_str(entry.get("title"), "an anti-convergence 'title'")
    text = _require_str(entry.get("text"), "an anti-convergence 'text'")

    if not _themes._SLUG_RE.match(slug):
        raise AntiConvergenceClauseError(
            f"an anti-convergence clause's slug must be a lowercase hyphenated "
            f"slug, got {slug!r}. The slug is how an operator and a campaign "
            f"log name the clause they are grepping for, so a spelling no "
            f"reader could reconstruct names nothing — and the grammar is "
            f"feature 212's, shared rather than respelled, so the member's "
            f"three committed artifacts cannot drift apart on what a slug is "
            f"(feature 210, refused fail closed)."
        )

    return AntiConvergenceClause(
        kind=ANTI_CONVERGENCE_POLICY_KIND, slug=slug, title=title, text=text
    )


def load_anti_convergence(
    path: Path = COMMITTED_ANTI_CONVERGENCE,
) -> AntiConvergenceClause:
    """Read and compile an anti-convergence clause, refusing an unreadable file.

    Reads through the same law as any change to it would be: the committed
    artifact is not privileged, so a drift written to disk is refused exactly as
    a drift compiled in memory (feature 210).
    """
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise AntiConvergenceClauseError(
            f"could not read the anti-convergence clause at {path}: {exc}. PRD "
            f"§C3 makes this clause part of the defining prompt of the system "
            f"— 'without it, a discovery tree collapses into 400 parameter "
            f"tweaks of one indicator' — and a clause that cannot be read is "
            f"not one that screens everything gracefully: it is a deployment "
            f"whose prompt was never checked, and a caller that carried on "
            f"would be authoring with the clause missing while believing it was "
            f"carrying §C3's (feature 210)."
        ) from exc
    except ValueError as exc:
        raise AntiConvergenceClauseError(
            f"the anti-convergence clause at {path} is not valid JSON: {exc}. "
            f"Refused rather than read partially: a clause compiled from a "
            f"partially-parsed document is one whose file and whose gate "
            f"disagree (feature 210)."
        ) from exc
    return compile_anti_convergence(document)


def committed_anti_convergence() -> AntiConvergenceClause:
    """The committed artifact, compiled through the same law as any change.

    The posture an operator gets without writing a stanza — and the document
    feature 210's own tests hold to PRD §C3's one clause, so "the prompt must
    carry this text" is a checked fact about a file in the repository rather
    than a claim in a runbook.
    """
    return load_anti_convergence(COMMITTED_ANTI_CONVERGENCE)


class _ParameterEraser(ast.NodeTransformer):
    """Erase every numeric literal in a parsed source, and nothing else.

    The whole of :func:`proposal_skeleton`.  Three edits, each deliberate:

    * **numeric literals** — ``int``, ``float`` and ``complex`` become the
      literal ``0``.  This is the erasure the feature is about:
      ``ctx.close.rolling_mean(20)`` and ``ctx.close.rolling_mean(60)`` are one
      hypothesis with two parameters, and §14.1's "400 parameter tweaks of one
      indicator" is four hundred of the first.
    * **``bool`` is left alone**, and that is not an oversight.  ``True`` and
      ``False`` are ``int`` subclasses in Python, so a naive walk would erase
      them too — and a flag that selects a *branch* is not a parameter that
      scales one.  Erasing it would make ``x if flag else y`` and ``y if flag
      else x`` one structure, which is the false merge this gate exists to avoid
      on the other side.  The affinity trap the workspace's SQLite layer guards
      is the same trap, guarded here for its own reason.
    * **docstrings are dropped.**  A docstring is prose *about* a proposal, and
      two agents describing one mechanism in different words must not be two
      structures.  This rewrite is the only place the law reads anything other
      than the tree, and it removes rather than inspects.
    * **named keyword arguments are sorted by name.**  :func:`ast.unparse`
      renders a call's keywords in the order the source wrote them, so
      ``rolling_mean(20, min_periods=1)`` and ``rolling_mean(20,
      min_periods=1)`` written in the other keyword order would parse to two
      different skeletons — a spelling difference with no bearing on the
      mechanism, and one a model re-proposing the same idea would produce by
      accident.  Sorting the *named* keywords closes it.  A call that also
      unpacks ``**`` is left in source order: the unpacking's position relative
      to the named keywords is a fact about which of them may be overridden,
      so reordering there would be editing the proposal rather than normalising
      its spelling.
    """

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        # ``bool`` first: Python's ``bool`` is an ``int`` subclass, so the order
        # of these two branches is the whole of the deliberate asymmetry above.
        if isinstance(node.value, bool):
            return node
        if isinstance(node.value, (int, float, complex)):
            return ast.copy_location(ast.Constant(value=0, kind=None), node)
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        visited = super().generic_visit(node)
        assert isinstance(visited, ast.Call)
        if visited.keywords and all(kw.arg is not None for kw in visited.keywords):
            visited.keywords = sorted(visited.keywords, key=lambda kw: kw.arg or "")
        return visited

    def visit_Module(self, node: ast.Module) -> ast.AST:
        return self._without_docstring(super().generic_visit(node))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._without_docstring(super().generic_visit(node))

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> ast.AST:
        return self._without_docstring(super().generic_visit(node))

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        return self._without_docstring(super().generic_visit(node))

    @staticmethod
    def _without_docstring(visited: ast.AST) -> ast.AST:
        """Drop a leading string-expression statement from a body, if present."""
        body = getattr(visited, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            visited.body = body[1:]
        return visited


def proposal_skeleton(source: object) -> str:
    """The structure of a proposed signal, with every numeric literal erased.

    The unit of comparison :class:`AntiConvergenceGate` decides on, and the
    feature's own answer to *what is a parameter tweak?*  Two sources share a
    skeleton exactly when they parse to the same expression tree over the same
    identifiers with different constants — which is §14.1's failure mode stated
    as a computable property, and is deliberately **not** satisfied by two
    proposals that genuinely differ: a new term, a different transformation, an
    operator applied where none was, or another accessor read out of the window
    all change the tree rather than its leaves.

    The answer is normalised through :func:`ast.unparse`, so formatting,
    comments, line breaks, quote style and the order of keyword arguments do not
    make two spellings of one structure look like two.  That normalisation is
    also why the comparison is a *string* rather than an ``ast.AST``: an AST
    defines no structural equality, so two independently parsed identical
    sources would compare unequal, and a gate comparing trees by identity would
    admit every proposal — the vacuous green no gate in this member may allow.

    **A source that cannot be parsed raises.**  This function is not the
    conformance check — feature 205's :meth:`SignalContract.adopt` is, and it
    runs first — so a syntax error here is a caller that skipped that check
    rather than a proposal to judge.  The refusal names the parse failure,
    because the alternative (returning a sentinel skeleton) would make every
    unparseable proposal compare equal to every other one and to itself, which
    is the collapse this gate exists to detect arriving as its own answer.
    """
    if not isinstance(source, str) or not source.strip():
        raise AntiConvergenceError(
            f"a proposal's structure can only be read from non-empty source "
            f"text, got {type(source).__name__}. docs/nullius-tech-"
            f"architecture.md §14.1 states the failure this screens for — 'the "
            f"400th variant of one indicator' — and a value that is not source "
            f"has no indicator to be a variant of (feature 210)."
        )
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise AntiConvergenceError(
            f"the proposal does not parse, so its structure cannot be read: "
            f"{exc}. The conformance screen (feature 205's adopt) runs before "
            f"this one, so a source that cannot be parsed here is a caller that "
            f"skipped it rather than a proposal to judge — and answering with a "
            f"placeholder structure would make every unparseable proposal "
            f"compare equal to every other one (feature 210)."
        ) from exc
    return ast.unparse(_ParameterEraser().visit(tree))


def skeleton_digest(source: object) -> str:
    """The sha256 hexdigest of a proposal's skeleton — the collapse's key.

    The value :class:`AntiConvergenceGate` compares on, computed over
    :func:`proposal_skeleton`'s output rather than over the raw source, so two
    sources that differ only in their constants share a key.  Spelled
    ``hashlib.sha256(...).hexdigest()`` in lowercase — the same three lines
    :func:`signal_agent.source_code_hash`, :func:`signal_agent.mechanism_digest`
    and :func:`artifacts.source_code_hash` each state — because a digest that
    disagreed with its neighbours on case would make one value look like two,
    which is precisely the failure this key exists to prevent.

    **It is a key, never a magnitude.**  The type is ``str`` and not an integer,
    on the grounds :func:`signal_agent.mechanism_digest` sets out: a numeric
    digest is *orderable*, and an orderable derived value is the first step
    toward a scored one.  Nothing here prices a proposal; it answers whether the
    campaign already holds this structure.
    """
    return hashlib.sha256(proposal_skeleton(source).encode("utf-8")).hexdigest()


class AntiConvergenceReason(enum.StrEnum):
    """Why a proposal was admitted or refused — the audit vocabulary.

    A :class:`enum.StrEnum` whose *value* is the token its own
    :attr:`AntiConvergenceVerdict.detail` opens with — so the reason is
    greppable in a campaign log without a lookup table, and a refusal never
    opens with another reason's headline.  The three are split by *repair*, not
    by which check happened to fail, the discipline
    :class:`signal_agent.AdoptionReason` states for its own: a caller handed a
    value that was never source has a wiring bug, a caller handed a tweak has a
    proposal to refuse, and a caller handed a novel structure may open the node.
    """

    #: Admitted: no node in the handed comparison set has this structure.  Its
    #: detail opens with :data:`NOVEL_CODE` rather than with this value, the one
    #: place this enum and its codes differ — the same asymmetry
    #: :attr:`signal_agent.ThemeReason.LEGAL` has against
    #: :data:`signal_agent.LEGAL_THEME_CODE`.  "novel" is the reason a caller
    #: branches on; "novel_structure" is the word a log line opens with, and an
    #: admission is not a code an operator greps a campaign for.
    NOVEL = "novel"

    #: Refused: the proposal's structure — every numeric literal erased — is one
    #: the campaign already holds.  Feature 210's headline, and the reason the
    #: digest and the node ids are carried: the retrying agent needs to see
    #: *which* of its own nodes it is duplicating and *how many times*, because
    #: "not novel" is not a repair and "you have proposed this structure nine
    #: times" is.  Spelled as the code itself, so branching on the value and
    #: grepping for it are the same string.
    PARAMETER_TWEAK = PARAMETER_TWEAK_CODE

    #: Refused: the value is not a proposal at all — not a string, a string with
    #: nothing in it, or text that does not parse.  Its own reason rather than a
    #: spelling of the tweak case because the repair is different in kind: an
    #: empty or unparseable submission is a bug at the *call site* (or a caller
    #: that skipped feature 205's adopt), and an operator looking for a
    #: converged tree would be looking in the wrong place.  Spelled as the code
    #: itself, for the same reason :attr:`PARAMETER_TWEAK` is.
    NOT_A_PROPOSAL = NOT_A_PROPOSAL_CODE


class AntiConvergenceVerdict:
    """One proposal's verdict: novel or a tweak, why, and in what words.

    ``admitted`` is the one field a caller must check, and it is *computed* from
    the reason rather than set by a constant — the same "computed, never
    assumed" stance :class:`signal_agent.SourceAdoption`,
    :class:`signal_agent.ThemeAdmission` and
    :class:`signal_agent.DeadTerritoryVerdict` take for their own answers.  The
    object carries everything the callers downstream need and nothing else:

    * :attr:`digest` — the proposal's skeleton digest, the key the comparison
      ran on, ``None`` for a refusal that never reached a parse.  Carried rather
      than left to the caller because the retry prompt and the campaign log both
      want to name the structure, and a caller that recomputed it later is
      exactly the pair that can drift;
    * :attr:`duplicates` — every node in the handed comparison set holding that
      structure, as ``(node_id, digest)`` pairs in the order the caller supplied
      them.  Empty for an admission and for a refusal that never parsed;
    * :attr:`detail` — one operator-facing paragraph, the sentence a campaign
      log records.

    **Its constructor refuses nothing.**  A caller holding a refusal is the
    caller that most needs one, and it cannot be told about an object it was
    never allowed to build — the discipline
    :class:`signal_agent.SourceAdoption` states for its own constructor.  The
    refusals live at :meth:`require`.
    """

    __slots__ = ("admitted", "detail", "digest", "duplicates", "reason")

    def __init__(
        self,
        *,
        reason: AntiConvergenceReason,
        detail: str,
        digest: str | None = None,
        duplicates: Iterable[tuple[str, str]] = (),
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.admitted = reason is AntiConvergenceReason.NOVEL
        self.digest = digest
        self.duplicates = tuple(duplicates)

    def require(self) -> str:
        """Return the admitted structure digest, or raise the feature's error.

        The bridge between the law's returned answer and the exception a caller
        wants on its last line before it opens a node: an admitted proposal
        returns its skeleton digest, so a caller can write
        ``gate.admit(source, held).require()`` and have feature 210 enforced
        there rather than remembered.  A refusal raises with this verdict's own
        sentence, so the retry prompt and the log line say the same thing.
        """
        if not self.admitted:
            raise AntiConvergenceError(self.detail)
        assert self.digest is not None  # admitted implies a digest, by construction
        return self.digest

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"AntiConvergenceVerdict(reason={self.reason.value!r}, "
            f"duplicates={len(self.duplicates)})"
        )


def _held_digests(held: Iterable[Any]) -> tuple[tuple[str, str], ...]:
    """Normalise a comparison set into ``(node_id, skeleton digest)`` pairs.

    The comparison set arrives in one of three shapes, and all three are
    legitimate for a caller that already holds part of the answer:

    * ``(node_id, source)`` pairs — the campaign's tree as the caller has it;
    * ``(node_id, digest)`` pairs — what a previous
      :class:`AntiConvergenceVerdict` carried, so a caller screening several
      proposals in one pass does not re-parse its whole history per proposal;
    * a bare ``str`` — source text with no node id yet, for the caller screening
      a batch before any of it is persisted.  The id is synthesised from the
      entry's position so the pair shape is uniform downstream, and it is
      spelled ``held-<n>`` rather than a UUID because it is *not* a node id and
      must not be mistaken for one in a log line.

    A digest is told from a source by its shape — a 64-character lowercase hex
    string is a digest, which is the shape :func:`skeleton_digest` emits.  That
    inference is the one this module makes about its caller's data, and it is
    spelled out here rather than hidden: a caller passing a *source* that is
    exactly 64 hex characters would have it read as a digest, so a caller with
    such a proposal should pass it as a ``(node_id, source)`` pair — the
    ambiguity is unresolvable in general, and the documented answer is the
    explicit shape.

    An entry whose digest cannot be derived is **skipped** rather than raising:
    the comparison set is the caller's own history, and a node the caller cannot
    parse is one this law has no opinion about.  Refusing the *new* proposal
    because an *old* one was unparseable would be this gate reporting a defect
    in the tree as a property of the submission.
    """
    pairs: list[tuple[str, str]] = []
    for index, entry in enumerate(held):
        if isinstance(entry, str):
            node_id, payload = f"held-{index}", entry
        elif isinstance(entry, tuple) and len(entry) == 2:
            node_id, payload = str(entry[0]), entry[1]
        else:
            continue
        if not isinstance(payload, str):
            continue
        if _DIGEST_RE.match(payload):
            pairs.append((node_id, payload))
            continue
        try:
            pairs.append((node_id, skeleton_digest(payload)))
        except AntiConvergenceError:
            continue
    return tuple(pairs)


class AntiConvergenceGate:
    """Feature 210's law, as the value a composed application carries.

    A facade over this module and the committed clause it compiled — the same
    shape :class:`signal_agent.SignalThemeGate` gives feature 212 and
    :class:`signal_agent.DeadTerritoryGate` gives feature 213 — so a caller
    holding the composed component can ask both halves of feature 210's question
    without importing this submodule by name or re-reading the artifact:

    * *does this campaign's prompt carry the clause?* — :meth:`carries` and
      :meth:`require_in`, screened against the committed text;
    * *is this proposal a parameter tweak of something this campaign already
      holds?* — :meth:`admit`, :meth:`covers` and :meth:`require`.

    **It carries the compiled clause and nothing else.**  No proposal, no
    campaign, no tree, no store: the comparison set is handed *in* on every
    call, because a component shared across a campaign that held one would let
    two campaigns' verdicts be read through each other, and — load-bearing —
    because per-campaign membership is the feature's semantics rather than an
    implementation detail (PRD §9 makes the campaign the unit of search).

    **The two halves fail in opposite directions, deliberately.**  The applied
    half — :meth:`admit` — refuses *nothing* when the comparison set is empty,
    because a campaign with no proposals yet has nowhere to have converged to.
    The clause half — :meth:`carries` — refuses *everything* when the clause
    itself is unreadable, because an empty clause is a substring of every string
    and the naive test would certify a prompt nobody checked.  The two are not
    in tension: the first is about a campaign that has done nothing, the second
    about a deployment that cannot say what it is screening for.  Confusing them
    is the empty-document mistake features 212 and 213 refuse, restated.

    **The delegation is deliberately thin** — each verb is one call into the law
    above it — because a second implementation of the comparison rule or the
    refusal wording here would be a second thing to keep in sync with the law,
    which is the drift the member's one-provenance rule exists to prevent.  What
    the class adds is discoverability (the factory's scan composes it), a single
    duck-checkable seam for the category's remaining features, and the read side
    — the clause a prompt must carry, which is the half a deployment's CI check
    asks for.
    """

    __slots__ = ("_clause",)

    def __init__(self, clause: AntiConvergenceClause) -> None:
        self._clause = clause

    @property
    def clause(self) -> AntiConvergenceClause:
        """The compiled clause this gate carries.

        Exposed so a caller — a CI check recompiling the committed artifact, an
        operator asking what the agent was asked to write under — reads the
        clause rather than re-deriving it.  Reading it refuses nothing: the
        clause holds no capability, which is the point of the component being a
        facade rather than an execution path.
        """
        return self._clause

    def text(self) -> str:
        """The clause verbatim — the text a campaign's prompt must carry.

        The read side an agent's prompt builder and a CI check both need.
        Deliberately the clause's own text rather than a summary of it: the
        screen below is a substring test against exactly this, and a prompt
        builder handed a paraphrase would ship a prompt that does not carry the
        committed clause.
        """
        return self._clause.text()

    # -- The clause half: the prompt must carry it ---------------------------

    def carries(self, prompt: object) -> bool:
        """Whether an authoring prompt carries the committed clause.

        The read side of the prompt screen: *did this campaign ship the clause?*
        is a question a deployment should be able to answer without a verdict,
        and answering it from the compiled artifact is what makes the clause a
        fact about the configuration rather than a line somebody meant to put in
        a template.

        **A substring test, on the clause verbatim.**  Not a similarity score,
        not a keyword list, not a model's judgement — the clause is committed,
        the prompt is text, and "carries it" means the text is *in* it.  A
        deployment that rewords the clause has a different clause and should
        commit that one; a deployment that paraphrases has a prompt that does
        not carry the clause it claims to.

        **A gate whose own clause is unreadable certifies nothing**, and this is
        the branch that says so.  The composed builder hands out a gate whose
        clause was built by construction after a drifted artifact rather than
        through the compiler (see :func:`signal_agent.build_anti_convergence`),
        and that clause's text is empty — so the naive
        ``self._clause.text() in prompt`` would answer ``True`` for *every*
        prompt, since the empty string is a substring of every string.  That is
        a silent certification of a prompt nobody checked, and it is precisely
        the failure docs/nullius-tech-architecture.md §14.1 describes: a
        converged tree "is not caught by anything".  A gate that cannot read its
        own clause therefore refuses to certify any prompt — fail closed —
        rather than certifying them all.  The cost is a deployment that cannot
        author until its artifact is fixed, refused loudly and by name; the
        alternative's cost is every campaign authoring blind.
        """
        text = self._clause.text()
        return isinstance(prompt, str) and bool(text) and text in prompt

    def require_in(self, prompt: object) -> str:
        """Refuse an authoring prompt that does not carry the clause.

        Raises :class:`~signal_agent.errors.AntiConvergenceClauseError` —
        carrying this gate's own ``clause_absent`` sentence — when the prompt
        does not carry the committed clause, and returns the prompt unchanged
        when it does, so a caller can put it on the last line before it ships a
        prompt to the agent and have PRD §C3 enforced there rather than
        remembered.

        The prompt is returned **unmodified**.  This law checks the prompt; it
        does not author it — a gate that inserted the clause into a campaign's
        prompt would be writing that campaign's prompt, and the deployment would
        have no way to review what its agent was actually told.
        """
        if not self.carries(prompt):
            described = (
                "which is not text at all"
                if not isinstance(prompt, str)
                else (
                    f"a prompt of {len(prompt)} character(s) not carrying it"
                    if prompt.strip()
                    else "an empty prompt"
                )
            )
            raise AntiConvergenceClauseError(
                f"{CLAUSE_ABSENT_CODE}: the campaign's authoring prompt was "
                f"screened against the committed anti-convergence clause "
                f"({self._clause.kind}, {self._clause.slug!r}) and does not "
                f"carry it — {described}. PRD §C3 keeps the explicit "
                f"anti-convergence clause in the discovery agent's prompt "
                f"'nearly verbatim', and docs/nullius-tech-architecture.md "
                f"§14.1 says why nothing downstream substitutes for it: 'A bad "
                f"proposal is caught by the evaluator at a cost of one trial "
                f"charge. A converged tree is not caught by anything.' A prompt "
                f"that dropped the clause is a campaign that will spend its "
                f"whole budget on variants of one indicator and be told by "
                f"every score that it went well. Commit the clause into the "
                f"prompt, or commit a different clause into "
                f"{COMMITTED_ANTI_CONVERGENCE.name} (feature 210)."
            )
        # ``carries`` answered True, which it can only do for a string; the
        # assertion is what lets the return type be ``str`` without a cast.
        assert isinstance(prompt, str)
        return prompt

    # -- The applied half: the proposal must not be a tweak -------------------

    def covers(self, source: object, held: Iterable[Any]) -> bool:
        """Whether ``source`` is a parameter tweak of anything in ``held``.

        The read side of the applied law, and the same predicate
        :meth:`admit` runs, so a deployment or a dashboard can ask *is this
        proposal one the campaign already holds in different parameters?*
        without a verdict object and without the two answers drifting apart.

        ``True`` when the proposal is refused — the polarity feature 213's
        ``covers`` takes for its denylist, and the inverse of feature 212's for
        its allowlist: the same word, opposite verdict.

        A ``source`` that cannot be parsed is ``False`` rather than an
        exception, deliberately, because this is the *asking* verb: a caller
        branching on the answer gets a boolean, and the caller that wants the
        parse failure named calls :meth:`admit` or :func:`proposal_skeleton`.
        """
        try:
            digest = skeleton_digest(source)
        except AntiConvergenceError:
            return False
        return any(digest == existing for _, existing in _held_digests(held))

    def admit(
        self, source: object, held: Iterable[Any] = ()
    ) -> AntiConvergenceVerdict:
        """Judge one proposal: admit it only if the campaign holds no such structure.

        The feature's verb.  In order, and each step's own reason:

        1. **it is a proposal** — a non-string, a blank string, or text that
           does not parse is refused with
           :attr:`AntiConvergenceReason.NOT_A_PROPOSAL`.  Its own reason because
           the repair is the caller's: an unparseable submission is a caller
           that skipped feature 205's ``adopt``, or an agent that returned no
           code;
        2. **the campaign does not hold its structure** — :func:`skeleton_digest`
           runs and the handed comparison set is searched, and a match is refused
           with :attr:`AntiConvergenceReason.PARAMETER_TWEAK`, carrying the
           structure's digest and every node the campaign already holds at it, so
           the retrying agent can see which of its own proposals it is
           duplicating.

        **The comparison set is handed in, and it is per campaign.**  ``held``
        is an iterable of proposals the caller already holds — source text, or
        ``(node_id, source)`` pairs, or the ``(node_id, digest)`` pairs a
        previous verdict carried; see :func:`_held_digests` for the three
        shapes.  What is compared is each entry's *skeleton*, never its text.
        PRD §9 makes the campaign the unit of search, so the caller judging node
        400 passes node 400's campaign and not the whole tree.

        An empty comparison set refuses nothing, which is the correct answer for
        the first proposal of every campaign and is why this law's empty case is
        not the empty-document mistake features 212 and 213 refuse: nothing has
        been proposed yet is not the same as nobody made the decision.

        The admitted proposal is returned **unmodified** — this law judges a
        structure and never edits a source, and a gate that rewrote a proposal
        "into novelty" would be authoring it.
        """
        held_pairs = _held_digests(held)

        if not isinstance(source, str) or not source.strip():
            described = (
                type(source).__name__
                if not isinstance(source, str)
                else f"a string of {len(source)} character(s) containing no source"
            )
            return AntiConvergenceVerdict(
                reason=AntiConvergenceReason.NOT_A_PROPOSAL,
                detail=(
                    f"{NOT_A_PROPOSAL_CODE}: a proposal's structure can only be "
                    f"read from non-empty source text, got {described}. The "
                    f"anti-convergence clause screens a proposal's *structure* "
                    f"against the structures the campaign already holds, so a "
                    f"submission that is not source has nothing to screen — this "
                    f"is a bug in the call that built the proposal (or a caller "
                    f"that skipped feature 205's conformance check) rather than "
                    f"a converged tree, and no comparison set could have matched "
                    f"it (feature 210)."
                ),
            )

        try:
            digest = skeleton_digest(source)
        except AntiConvergenceError as refusal:
            return AntiConvergenceVerdict(
                reason=AntiConvergenceReason.NOT_A_PROPOSAL,
                detail=(
                    f"{NOT_A_PROPOSAL_CODE}: the proposal's structure cannot be "
                    f"read — {refusal} Feature 205's conformance screen admits "
                    f"only source the sandbox can invoke, so a submission that "
                    f"does not parse is one that never reached that screen; "
                    f"feature 210 refuses it here rather than admitting it as "
                    f"novel, because a structure nobody can read is a structure "
                    f"nobody compared (feature 210)."
                ),
            )

        duplicates = tuple(pair for pair in held_pairs if pair[1] == digest)
        if duplicates:
            count = len(duplicates)
            listed = ", ".join(node for node, _ in duplicates[:_MAX_LISTED_DUPLICATES])
            if count > _MAX_LISTED_DUPLICATES:
                listed = (
                    f"{listed}, ... ({count - _MAX_LISTED_DUPLICATES} more)"
                )
            return AntiConvergenceVerdict(
                reason=AntiConvergenceReason.PARAMETER_TWEAK,
                digest=digest,
                duplicates=duplicates,
                detail=(
                    f"{PARAMETER_TWEAK_CODE}: the proposal's structure — every "
                    f"numeric literal erased — is one this campaign already "
                    f"holds {count} time(s) (skeleton {digest}, nodes: {listed}). "
                    f"docs/nullius-tech-architecture.md §14.1 names this as the "
                    f"failure nothing downstream catches: 'A bad proposal is "
                    f"caught by the evaluator at a cost of one trial charge. A "
                    f"converged tree is not caught by anything. At roots, a weak "
                    f"model's failure mode is proposing the 400th variant of one "
                    f"indicator — every node scores plausibly, the budget is "
                    f"fully consumed, and nothing in the pipeline detects it.' "
                    f"PRD §C3's clause forbids exactly this: a proposal that "
                    f"differs from an existing node only in its parameters is "
                    f"the same hypothesis re-submitted. Open a mechanism this "
                    f"campaign does not hold, or make a structural change to one "
                    f"it does — a new term, another accessor, a different "
                    f"transformation — and state which. Refused before the node "
                    f"is opened (features 210, 205; §14.1, PRD §C3)."
                ),
            )

        return AntiConvergenceVerdict(
            reason=AntiConvergenceReason.NOVEL,
            digest=digest,
            detail=(
                f"{NOVEL_CODE}: no node in the comparison set this campaign "
                f"handed in has the proposal's structure (skeleton {digest}), so "
                f"the branch opens a mechanism the tree does not already contain "
                f"and the node may be opened. docs/nullius-tech-architecture.md "
                f"§14.1: 'Root generation demands novelty under a negative "
                f"constraint' — this is that constraint applied against the "
                f"campaign's own history (feature 210)."
            ),
        )

    def require(self, source: object, held: Iterable[Any] = ()) -> str:
        """Refuse unless the proposal opens a structure the campaign lacks.

        The caller's verb: raises
        :class:`~signal_agent.errors.AntiConvergenceError` — carrying the gate's
        own ``parameter_tweak`` sentence — when the proposal is a tweak, and
        returns its skeleton digest when it is novel, so a caller can put it on
        the last line before it opens a node and have feature 210 enforced there
        rather than remembered.
        """
        return self.admit(source, held).require()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"AntiConvergenceGate(clause={self._clause.slug!r})"


def anti_convergence_gate() -> AntiConvergenceGate:
    """The law, for a caller that wants it directly.

    Not a component — the ``@register`` builder in this member's ``__init__``
    is, and this is the same call minus the composition.  The member's own tests
    and any operator script reach here.  Like features 212's and 213's
    conveniences it reads the committed artifact beside it, which means a
    drifted file raises a named refusal here rather than silently handing back a
    gate that screens nothing.
    """
    return AntiConvergenceGate(committed_anti_convergence())
