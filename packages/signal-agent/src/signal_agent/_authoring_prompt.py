"""Feature 5 — build the C3 authoring prompt, as named, screenable parts.

app_spec.xml, "Hypothesis Authoring Agent": *System builds the C3 authoring
prompt with ``signal_agent._authoring_prompt.build_authoring_prompt(workspace,
history, *, clause)``.*  docs/alpha-engine-prd.md §C3 and
docs/nullius-tech-architecture.md §14.1 are what the prompt must be shaped
like, and this module is the one place that shape is assembled rather than
merely checked — the checks are features 206, 208 and 210's laws
(:mod:`signal_agent._history`, :mod:`signal_agent._guidance`,
:mod:`signal_agent._anti_convergence`), and this builder's whole job is to
hand them something they can certify.

**Three parts, named so the laws can read them.**  :func:`build_authoring_prompt`
returns an :class:`AuthoringPrompt` — an object whose three attributes are the
prompt's three named sections, exactly the shape
:meth:`~signal_agent.PromptGuidanceGate.admit` reads as "an object whose
attributes are the sections" (:mod:`signal_agent._guidance`'s widest-match
case):

* ``task`` — the signal ABI (read from feature 205's own
  :meth:`~signal_agent.SignalContract.declaration`, never restated as a second
  spelling of ``signal(ctx: MarketWindow, seed: int) -> pl.Series``), the
  node's ``theme_root`` and ``depth``, and the required answer format.  A
  mapping of facts, the same shape :meth:`~signal_agent.SignalContract.
  declaration` itself takes and for the same reason: PRD §C3 and §14.1 forbid
  injecting directional guidance into the prompt, and a mapping of facts is
  the shape that cannot accidentally become one.
* ``anti_convergence`` — the committed clause (feature 210's
  :data:`~signal_agent.COMMITTED_ANTI_CONVERGENCE`), verbatim.  Neither
  section name matches :data:`signal_agent._guidance._GUIDANCE_ROLES` and
  neither section's content declares a distillation, so
  :meth:`~signal_agent.PromptGuidanceGate.admit` admits both — and
  ``anti_convergence`` is exactly the string
  :meth:`~signal_agent.AntiConvergenceGate.require_in` screens a prompt
  for, so a caller holding this section already holds the value that gate
  accepts.
* ``history`` — every prior node of the campaign, in the store's own order,
  as the ``(PriorProposal, ScoreRecord | None)`` pairs the caller hands in.
  Carried through unmodified: no entry is dropped, no proposal text is cut,
  and no run is sampled.  ``history`` is one of :mod:`signal_agent._guidance`'s
  documented near-misses — the section this member's laws exist to
  *protect*, never to refuse — so carrying it whole is what admits the
  prompt rather than what gets it refused.

**Why the history is read in, not fetched.**  This module compiles no
store and resolves no configuration: what counts as "every prior node" is the
caller's own tree query for the round, the same stance
:mod:`signal_agent._history`'s module docstring takes for its own subject.  A
builder that queried a store itself would own a second opinion about what the
history is, and feature 206's :class:`~signal_agent.ProposalHistory` is the
law that judges whichever history a caller assembled — this module's job ends
at carrying what it was handed, whole.

**Why the agent never sees a node's null status.**  :class:`~signal_agent.
ScoreRecord` carries exactly the seven metrics ``0114`` declares plus
``fail_class`` (§6.1's *"ok | timeout | error | tripwire_fail"*) — see
:mod:`signal_agent._proposal`.  It has no field for a planted null's identity,
because the whole point of the discriminant living in the nulloracle
member's sidecar (§7.1: *"Absent.  The only way to learn a node's status is
to hold the sidecar key"*) is that nothing on the authoring path can read it.
This module never imports :mod:`nulloracle` and never names ``is_null`` —
docs/nullius-tech-architecture.md's design principle 2, restated here because
the authoring prompt is the one artifact a planted null's own author could, in
principle, read.

**Rendering is :func:`to_request`'s job, not this module's assembly.**  The
three parts are *structure* — a mapping, a string, a tuple of pairs — screened
by the two laws before anything is flattened into text.  :func:`to_request`
is the seam that turns admitted parts into the one
:class:`providers.Request` a provider call sends: one ``system`` message
carrying ``task`` and ``anti_convergence``, one ``user`` message carrying
``history``.  Splitting the two keeps the guidance and anti-convergence laws
reading the same structure a caller is about to ship, rather than a rendered
string neither law can screen honestly (:mod:`signal_agent._guidance`'s own
argument against scanning prose).

Stdlib only, plus this member's own :mod:`signal_agent._authoring` (for the
declared ABI, imported at module scope because it is a sibling submodule of
this same member) and :mod:`signal_agent._proposal` (for
:class:`~signal_agent.ScoreRecord`).  ``providers`` is a declared dependency
of this member but is reached only inside :func:`to_request`, deferred for
the same reason :func:`signal_agent._authoring.require_contract` defers
``contract``: nothing in this module is a composed ``@register`` builder, but
a module-scope import of a sibling *member* would still make this file
unimportable in an environment that has not put that member's ``src/`` on
``sys.path`` yet.

**Cost awareness (additions_spec_cost_aware_selection.xml, feature 4).**
PRD §2.3's M2 pivot found selection cost-blind: a committed pick's in-sample
IC survives but its post-cost book loses money out of sample, because
nothing told the agent that cost, not rank IC, is what it is judged on. Two
small additions carry that fact into the prompt, and neither computes a cost
of its own:

* ``task`` gains a ``cost_awareness`` key (:func:`_cost_awareness_part`) —
  the fixed statement that the node is scored and selected on the post-cost
  IR t-statistic of a dollar-neutral book, the evaluation grid's cadence
  (:func:`_cadence_statement`, derived from the grid's own dates — "weekly"
  for the archive configs), the cost model's per-rebalance cost in bps of
  traded notional, and the one line of turnover guidance feature 4 names —
  information only, judging nothing. The cadence and the per-rebalance cost
  are read, duck-typed, off an ``evaluation`` context a caller hands in
  (:func:`_field`, the same reader ``workspace`` is read through); neither
  is computed from a raw fee schedule here, because applying a fee schedule
  is :mod:`cost_model`'s own arithmetic and feature 69 forbids a second
  implementation of it. ``evaluation=None`` — what every caller that has not
  wired a context in hands in, unchanged from before this feature —
  renders both facts as the honest ``"unmeasured"``, the same word a prior
  proposal's own absent metric renders as.
* Each history block gains a ``cost figures`` line (:func:`_cost_figures`)
  naming ``ic_tstat``, ``ir_tstat``, ``turnover`` and ``cost_adjusted_ir``
  off the prior's recorded :class:`~signal_agent.ScoreRecord` explicitly,
  beside the ``score.json`` blob those same figures already sit inside —
  so the four figures a cost-aware author must weigh are not something it
  has to find by re-parsing JSON. A ``None`` score, or a ``None`` metric
  within one, renders ``"unmeasured"`` rather than ``null``.

Both additions are appended after what :func:`build_authoring_prompt` and
:func:`to_request` already rendered — every existing key, every existing
line, is unchanged in content and position.

**Book and instrument (additions_spec_research_book_v2.xml, feature 4).**
The in-sample IC→book diagnostic behind that spec found the research book
itself under-specified to the agent: a node can be scored on a plain
dollar-neutral spot book, a BTC-beta-neutral book (features 1-2 of that same
spec), or a USD-M perpetual book with funding carry (feature 3) — and
nothing told the agent which. :func:`_cost_awareness_part` gains three more
facts, read duck-typed off the same ``evaluation`` context the cadence and
per-rebalance cost already come from, so a caller wires one context and
every fact in the section follows from it:

* ``instrument`` — :data:`_INSTRUMENT_SPOT` unless ``evaluation.instrument``
  reads exactly ``"perp"``, in which case :data:`_INSTRUMENT_PERP`. Any
  other value, including an absent attribute, is the spot default: whether
  ``"perp"`` is a legal value at all is :mod:`orchestrator`'s own config
  law, not this builder's to check.
* ``book`` — :data:`_BOOK_DOLLAR_NEUTRAL` unless ``evaluation.book``'s own
  ``beta_neutral`` reads exactly ``True``, in which case
  :data:`_BOOK_BETA_NEUTRAL`. The nested read goes through :func:`_field`
  twice, once for ``book`` and once for its ``beta_neutral``, so a
  ``evaluation`` with no ``book`` at all and a ``book`` with no
  ``beta_neutral`` both fall back the same way.
* ``cost_per_unit_traded_bps`` — the fee per unit of traded notional, the
  same figure :func:`evaluator.compute_node_metrics`'s own
  ``cost_per_unit_traded`` keyword charges against Σ|Δw| (the sum of
  absolute weight changes since the prior rebalance), read the same way
  ``per_rebalance_cost_bps`` is: a number, or the honest
  :data:`_UNMEASURED` for anything else, ``None`` included.

A fifth key, ``instrument_book_guidance``, carries one fixed,
information-only line (:data:`_INSTRUMENT_BOOK_GUIDANCE`): a perp book's
persistent funding differences are part of the return, and a beta-neutral
book removes market direction, so the signal must earn from cross-sectional
differences alone. Present regardless of what ``evaluation`` carries — the
same stance :data:`_TURNOVER_GUIDANCE` takes toward actual turnover —
because the point is the general discipline, not today's config.

Appended after every key :func:`_cost_awareness_part` already rendered;
every existing key, every existing value, is unchanged.

**The theme brief (additions_spec_guided_themes.xml, feature 3).**  PRD
§9.3 v2 found the hypothesis space itself too open-ended: a prompt that named
only a theme's slug left the agent to guess a mechanism, and three
pre-registered M2 pivots failed on that set.  v2 commits a brief — mechanism,
inputs, expected sign, notes — for each of its nine guided roots
(:mod:`signal_agent._themes`'s own documents), and this feature is the one
place that brief reaches the prompt: ``task`` gains a ``theme_brief`` key
(:func:`_theme_brief_part`), the committed brief for the node's own
``theme_root``, read once through :func:`~signal_agent.committed_legal_themes`
so the brief and the shared construction rules it carries alongside can never
be two different reads of the committed artifact disagreeing with each
other. A theme root the committed document carries no brief for — a v1 slug
on a resumed campaign, or a deployment's own ``NULLIUS_LEGAL_THEMES`` slug —
renders ``theme_brief`` as ``None`` rather than a refusal: nothing here
judges whether a root is legal (that is :mod:`signal_agent._themes`'s own
law), only whether this builder has extra material to show the agent for it.
Appended after what :func:`build_authoring_prompt` already rendered, the same
way the cost-awareness addition above is: every existing key, every existing
line, unchanged in content and position.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping
from itertools import pairwise
from typing import Any, Final

from ._authoring import signal_contract
from ._proposal import ScoreRecord
from ._themes import committed_legal_themes
from .errors import SignalAgentError

__all__ = [
    "AUTHORING_PROMPT_CODE",
    "AuthoringPrompt",
    "AuthoringPromptError",
    "build_authoring_prompt",
    "to_request",
]

#: The token every refusal this module raises opens with — the greppable word
#: an operator's campaign log carries, the same discipline every refusal in
#: this member follows.
AUTHORING_PROMPT_CODE: Final[str] = "authoring_prompt"

#: The three named sections, in the order :func:`build_authoring_prompt`
#: assembles them and :class:`AuthoringPrompt` declares as ``__slots__`` — the
#: order :meth:`~signal_agent.PromptGuidanceGate.admit`'s ``_attributes_of``
#: reads them back in.  Declared once so the constructor, the repr and a test
#: asserting "these are the three parts" cannot drift apart on the list.
PROMPT_PARTS: Final[tuple[str, ...]] = ("task", "anti_convergence", "history")

#: The fields a prior proposal must carry for this module to read it — the
#: same three :class:`~signal_agent.PriorProposal` carries, named here rather
#: than checked by ``isinstance`` because the module loader imports every
#: member twice (once by file path, once as the importable member), and an
#: ``isinstance`` check against a value built from the other import would be
#: false for a value that is, in every field, the same proposal.
_PRIOR_FIELDS: Final[tuple[str, ...]] = ("node_id", "proposal", "code_hash")


class AuthoringPromptError(SignalAgentError):
    """The C3 authoring prompt could not be assembled or rendered as asked.

    Raised by :func:`build_authoring_prompt` when the workspace, the clause or
    the history handed in do not carry what the function needs to assemble
    the prompt's three named parts, and by :func:`to_request` when ``parts``
    does not carry the three sections it renders.  One class for both call
    sites, because both are the same contract seen from two moments: the
    parts could not be built, or the parts that exist could not be rendered.

    **It is deliberately not an :class:`AgentSourceError`.**  Nothing here is
    a judgement about a proposal the agent wrote — the agent has not been
    called yet, and what failed is the *caller's* wiring: a workspace missing
    a field, a clause that cannot be read as text, a history entry that is
    not a ``(PriorProposal, ScoreRecord | None)`` pair.  No re-prompt repairs
    any of that, so a campaign driver's ``except AgentSourceError:`` handler
    — which exists to re-prompt — must not catch this by accident.  The
    repair is always a fix to the call: supply the missing field, pass the
    clause's text, or correct the history entry.
    """


def _field(source: object, name: str) -> object:
    """Read one named field from a mapping key or an attribute, or ``None``.

    The duck-typed seam this whole module and :mod:`signal_agent._history`
    and :mod:`signal_agent._guidance` share: a caller hands over its own
    record type, a mapping, or a mapping-like object, and the read is by name
    rather than by class.
    """
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


# ── The workspace half: campaign_id, theme_root, depth ────────────────────────


def _validated_campaign_id(workspace: object) -> str:
    value = _field(workspace, "campaign_id")
    if not isinstance(value, str) or not value.strip():
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: the workspace's campaign_id is "
            f"{value!r} ({type(value).__name__}), not a non-empty string. "
            f"build_authoring_prompt reads campaign_id, theme_root and depth "
            f"duck-typed off the workspace handed in, and a campaign with no "
            f"id names no scope for the history the prompt is about to ship "
            f"(feature 5)."
        )
    return value


def _validated_theme_root(workspace: object) -> str:
    value = _field(workspace, "theme_root")
    if not isinstance(value, str) or not value.strip():
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: the workspace's theme_root is "
            f"{value!r} ({type(value).__name__}), not a non-empty string. "
            f"The task part names the node's theme root so the agent knows "
            f"which legal space (feature 212) it is proposing inside "
            f"(feature 5)."
        )
    return value


def _validated_depth(workspace: object) -> int:
    value = _field(workspace, "depth")
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: the workspace's depth is {value!r} "
            f"({type(value).__name__}), not a whole number. "
            f"docs/nullius-tech-architecture.md §14.1 splits the agent's "
            f"role by depth — roots at depth 0-1, the depth role at depth "
            f">= 2 — and a non-integer names no role (feature 5)."
        )
    if value < 0:
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: the workspace's depth is {value}, "
            f"which is negative. A node's depth in the discovery tree counts "
            f"up from the root and cannot be negative (feature 5)."
        )
    return value


#: The two lines the authoring format's answer must carry — the shape
#: :func:`signal_agent._authored.parse_authored` checks, restated here as the
#: instruction the agent is asked to follow rather than imported, because this
#: module's subject is the *prompt* and that module's is the *answer*; the two
#: must agree in words, not in code, since the format is a grammar a human
#: wrote once (§C3) and the checker and the asker are two different moments.
_ANSWER_FORMAT: Final[Mapping[str, str]] = {
    "code_block": (
        "Exactly one ```python fenced code block, and nothing else fenced "
        "as python. Its body is the complete signal source the sandbox "
        "will execute — the whole module, including any helper "
        "definitions the signal body needs."
    ),
    "mechanism_line": (
        "Exactly one line starting 'Mechanism:' (that exact word, a colon, "
        "then the rest of the line), stating in one sentence the economic "
        "mechanism the signal is a bet on."
    ),
}


# ── Cost awareness: feature 4 of additions_spec_cost_aware_selection.xml ────

#: The literal this module renders for a cost-awareness fact it was not
#: handed, or a prior proposal's metric a ScoreRecord carries as ``None`` —
#: one word for "not measured" wherever either appears, rather than
#: ``null`` in one place and a bare absence in another.
_UNMEASURED: Final[str] = "unmeasured"

#: The fixed statement naming what a node is scored and selected on — the
#: addition's own words (feature 4's first bullet), restated as prose an
#: agent reads rather than a flag some gate checks: the actual rule (the
#: eligible node with the highest ``ir_tstat`` is the commit) is feature 2's
#: law over ``orchestrator.closeout``, not this module's to enforce or vary.
_SELECTION_STATEMENT: Final[str] = (
    "This node is scored and selected on the post-cost IR t-statistic "
    "(ir_tstat) of a dollar-neutral book, rebalanced on the evaluation "
    "grid -- not on rank IC (ic_tstat) alone."
)

#: What ``per_rebalance_cost_bps`` means, spelled once beside the figure so
#: the number and its definition cannot separate — feature 4's own words
#: ("fees plus spread assumption, as bps of traded notional") plus the one
#: relationship it names between that figure and turnover.
_COST_BASIS_STATEMENT: Final[str] = (
    "per_rebalance_cost_bps is the cost model's fees plus its spread "
    "assumption, as bps of traded notional charged once per rebalance on "
    "the grid above; turnover multiplies this cost -- a book that turns "
    "over more often pays it more often."
)

#: Feature 4's one line of guidance, verbatim in substance: information
#: only, read by a model deciding what to try next, never checked by any
#: gate the way feature 210's clause is — the addition's own words say so
#: ("It judges nothing and is information only"), restated here as the
#: last sentence so a reader cannot mistake prose for a rule.
_TURNOVER_GUIDANCE: Final[str] = (
    "High turnover erodes the post-cost book: persistent or smoothed "
    "signals with lower turnover are preferred when their IC survives. "
    "This is information only and judges nothing."
)


#: additions_spec_research_book_v2.xml feature 4 — the two ``instrument``
#: facts, spelled once so the choice between them lives in one place beside
#: the words themselves.
_INSTRUMENT_SPOT: Final[str] = "spot"
_INSTRUMENT_PERP: Final[str] = (
    "USD-M perpetual; longs pay and shorts receive funding over the "
    "holding period"
)

#: The two ``book`` facts, the same way — "60-day" and "BTC" name feature
#: 2's own defaults (``beta_window_days=60``, ``beta_benchmark="BTCUSDT"``),
#: restated here as the fixed prose a reader sees rather than a sentence
#: this builder assembles from whichever window or benchmark a deployment
#: configured: the prompt names what the committed default book is, not a
#: second rendering of an evaluation config it does not read in full.
_BOOK_DOLLAR_NEUTRAL: Final[str] = "dollar-neutral"
_BOOK_BETA_NEUTRAL: Final[str] = (
    "dollar- and BTC-beta-neutral (legs rescaled to equal 60-day beta)"
)

#: What ``cost_per_unit_traded_bps`` means, spelled once beside the figure —
#: the same discipline :data:`_COST_BASIS_STATEMENT` follows for
#: ``per_rebalance_cost_bps`` beside it, and the same figure
#: :func:`evaluator.compute_node_metrics`'s own ``cost_per_unit_traded``
#: keyword charges, named here as the fee per unit of traded notional so the
#: agent reads the one relationship that matters: multiplied by the book's
#: own turnover, it is what the book pays.
_COST_PER_UNIT_BASIS_STATEMENT: Final[str] = (
    "cost_per_unit_traded_bps is the fee per unit of traded notional, in "
    "bps -- multiplied by Σ|Δw| (the sum of absolute weight "
    "changes since the prior rebalance) it gives the fee this node's book "
    "pays that date."
)

#: Feature 4's one information-only line about the book and instrument
#: facts above — present regardless of what a deployment configured, the
#: same stance :data:`_TURNOVER_GUIDANCE` takes toward actual turnover,
#: because the discipline it states holds whether or not this node's own
#: book is perp or beta-neutral.
_INSTRUMENT_BOOK_GUIDANCE: Final[str] = (
    "For a perp book, persistent funding differences are part of the "
    "return; for a beta-neutral book, market direction is removed -- the "
    "signal must earn from cross-sectional differences alone. This is "
    "information only and judges nothing."
)


def _instrument_statement(evaluation: object) -> str:
    """:data:`_INSTRUMENT_PERP` iff ``evaluation.instrument`` reads ``"perp"``.

    Any other value — ``"spot"`` itself, an unrecognized string, or an
    absent attribute (``None``) — answers :data:`_INSTRUMENT_SPOT`: whether
    ``"perp"`` is the only other legal value is :mod:`orchestrator`'s own
    config law (additions_spec_research_book_v2.xml feature 3), not
    something this builder checks.
    """
    return _INSTRUMENT_PERP if _field(evaluation, "instrument") == "perp" else _INSTRUMENT_SPOT


def _book_statement(evaluation: object) -> str:
    """:data:`_BOOK_BETA_NEUTRAL` iff ``evaluation.book.beta_neutral`` is ``True``.

    Read through :func:`_field` twice — once for ``evaluation``'s own
    ``book``, once for that value's ``beta_neutral`` — so an ``evaluation``
    with no ``book`` at all and a ``book`` whose ``beta_neutral`` is
    ``False`` or absent both answer the same plain-book default,
    :data:`_BOOK_DOLLAR_NEUTRAL`. The comparison is ``is True`` rather than
    truthy, the same strictness :func:`_cost_awareness_part` already applies
    to its own numeric facts, so a stray non-boolean cannot silently flip
    the rendered book.
    """
    book = _field(evaluation, "book")
    return _BOOK_BETA_NEUTRAL if _field(book, "beta_neutral") is True else _BOOK_DOLLAR_NEUTRAL


def _cadence_statement(dates: object) -> str:
    """A one-word description of the evaluation grid's spacing, or "unmeasured".

    Reads the grid's own dates (parsed as ``datetime.date``/``datetime``, or
    ISO-8601 strings) -- nothing is assumed about a deployment's rebalance
    cadence beyond what the dates themselves show. Fewer than two dates, or
    a value this function cannot parse as a date, names no spacing and
    answers the honest absence rather than a guess. A grid spaced evenly at
    7 days (the archive configs' 235 dates) answers "weekly"; one spaced
    unevenly answers "irregular" rather than silently naming the first gap
    it saw.
    """
    if not isinstance(dates, (list, tuple)) or len(dates) < 2:
        return _UNMEASURED
    parsed: list[dt.date] = []
    for value in dates:
        if isinstance(value, dt.datetime):
            parsed.append(value.date())
        elif isinstance(value, dt.date):
            parsed.append(value)
        elif isinstance(value, str):
            try:
                parsed.append(dt.date.fromisoformat(value))
            except ValueError:
                return _UNMEASURED
        else:
            return _UNMEASURED
    steps = {(later - earlier).days for earlier, later in pairwise(parsed)}
    if len(steps) != 1:
        return "irregular"
    (step,) = steps
    return {1: "daily", 7: "weekly", 30: "monthly"}.get(step, f"every {step} days")


def _cost_awareness_part(evaluation: object) -> dict[str, Any]:
    """The cost-awareness facts the two cost-aware-selection specs ask the prompt to carry.

    ``evaluation`` is duck-typed, read the same way ``workspace`` is (by
    mapping key or by attribute, through :func:`_field`): ``evaluation_dates``
    (the rebalance grid, read only to name its cadence — see
    :func:`_cadence_statement`), ``per_rebalance_cost_bps`` and
    ``cost_per_unit_traded_bps`` (the cost model's own figures),
    ``instrument`` and ``book`` (additions_spec_research_book_v2.xml feature
    4 — see :func:`_instrument_statement` and :func:`_book_statement`).
    Nothing here is computed: this function describes the shape of what it
    is handed, never applies a fee schedule or a book construction of its
    own (:mod:`cost_model` and :mod:`evaluator` own that arithmetic; feature
    69 forbids a second implementation of it).

    ``evaluation=None`` — the default, and what every caller that has not
    wired an evaluation context in hands in — answers every numeric fact as
    :data:`_UNMEASURED` and every book/instrument fact as its plain default,
    not a reason to omit the section: both specs ask for the section to
    *display*, always, so a prompt built before a deployment wires the
    context in reads the same keys a later one does, carrying the honest
    absence rather than a missing key a reader would have to guess the
    meaning of.
    """
    cadence = _cadence_statement(_field(evaluation, "evaluation_dates"))
    cost_bps = _field(evaluation, "per_rebalance_cost_bps")
    if isinstance(cost_bps, bool) or not isinstance(cost_bps, (int, float)):
        cost_bps = _UNMEASURED
    cost_per_unit_bps = _field(evaluation, "cost_per_unit_traded_bps")
    if isinstance(cost_per_unit_bps, bool) or not isinstance(cost_per_unit_bps, (int, float)):
        cost_per_unit_bps = _UNMEASURED
    return {
        "selection_statement": _SELECTION_STATEMENT,
        "cadence": cadence,
        "per_rebalance_cost_bps": cost_bps,
        "cost_basis": _COST_BASIS_STATEMENT,
        "guidance": _TURNOVER_GUIDANCE,
        "instrument": _instrument_statement(evaluation),
        "book": _book_statement(evaluation),
        "cost_per_unit_traded_bps": cost_per_unit_bps,
        "cost_per_unit_traded_basis": _COST_PER_UNIT_BASIS_STATEMENT,
        "instrument_book_guidance": _INSTRUMENT_BOOK_GUIDANCE,
    }


#: The four figures each prior proposal's history block names explicitly —
#: feature 4's own list — beside the full ``score.json`` already rendered,
#: so the figures a cost-aware author must weigh are not buried inside one
#: JSON blob it would otherwise have to re-parse.
_COST_FIGURE_NAMES: Final[tuple[str, ...]] = (
    "ic_tstat",
    "ir_tstat",
    "turnover",
    "cost_adjusted_ir",
)


def _cost_figures(score: ScoreRecord | None) -> dict[str, Any]:
    """The four named figures off ``score``, :data:`_UNMEASURED` for each absence.

    A ``None`` score (a node with no recorded pair yet) answers
    :data:`_UNMEASURED` for all four, the same way a ``None`` metric within
    a present score does — one word for "not measured", whether nothing was
    recorded or one figure among several was not.
    """
    if score is None:
        return {name: _UNMEASURED for name in _COST_FIGURE_NAMES}
    return {
        name: (value if (value := getattr(score, name, None)) is not None else _UNMEASURED)
        for name in _COST_FIGURE_NAMES
    }


# ── The theme brief: feature 3 of additions_spec_guided_themes.xml ─────────

#: The one line every rendered brief adds beside its own ``expected_sign`` —
#: PRD §9.3 v2's and docs/hypothesis-space/themes-v2.md's shared discipline
#: ("Do not flip the sign after seeing results; a flipped hypothesis is a new
#: node"), restated here next to the theme's own stated sign rather than left
#: only in the shared construction rules, so the two sentences cannot be read
#: apart: a signal that flips the stated sign is a different hypothesis, and
#: the agent's own mechanism line must say so.
_PRE_REGISTRATION_STATEMENT: Final[str] = (
    "expected_sign is pre-registered: a signal that flips it is a different "
    "hypothesis and must say so in its stated mechanism."
)


def _theme_brief_part(theme_root: str) -> dict[str, Any] | None:
    """PRD §9.3 v2's brief for the node's own theme root, or ``None``.

    Read once through :func:`~signal_agent.committed_legal_themes`: both the
    brief and the shared construction rules folded in beside it come off the
    one compiled :class:`~signal_agent.LegalThemes` this call returns, so a
    caller can never see a brief and a rules list read from two different
    moments of the committed artifact.

    ``None`` for a theme root the committed document carries no brief for —
    a v1 slug on a resumed campaign, or a deployment's own
    ``NULLIUS_LEGAL_THEMES`` slug — never a refusal: whether a root is legal
    at all is :mod:`signal_agent._themes`'s own law, not this builder's, and
    an unbriefed-but-legal root is still one a proposal may open in; it is
    only this section that has nothing extra to show the agent for it (the
    same stance :meth:`~signal_agent.LegalThemes.brief` documents for its own
    absence).
    """
    themes = committed_legal_themes()
    brief = themes.brief(theme_root)
    if brief is None:
        return None
    return {
        **brief,
        "construction_rules": list(themes.construction_rules()),
        "pre_registration": _PRE_REGISTRATION_STATEMENT,
    }


def _available_streams_statement(streams: Mapping[str, tuple[str, ...]]) -> str:
    """The plain statement ``available_streams`` earns its place in the prompt with.

    bug_spec_prompt_available_streams.xml: naming the streams a snapshot
    holds is not the same as telling the model what happens to a stream it
    does *not* list, and the live prompt must say so in words — generated
    from ``streams`` itself, never a sentence hard-coded to one snapshot's
    own cadence (the bug's own symptom: a model that reached for ``1h``
    bars and ``borrow`` data a 1d-only snapshot does not hold).  A stream
    with no recorded frequency (``trades``, ``bookfeat``, ``borrow`` are
    not frequency-partitioned) is named alone; one that is lists its
    frequencies.
    """
    parts = []
    for stream in sorted(streams):
        freqs = streams[stream]
        parts.append(f"{stream} at {', '.join(freqs)}" if freqs else stream)
    listed = "; ".join(parts) if parts else "nothing"
    return (
        f"This evaluation's sealed snapshot holds only: {listed}. Every "
        "accessor or frequency not listed here returns an empty frame for "
        "this evaluation -- build the signal from the listed streams only, "
        "and express the theme through them."
    )


def _task_part(
    workspace: object, snapshot: Any | None = None, evaluation: Any | None = None
) -> dict[str, Any]:
    """The task section: the signal ABI, the node's place, and the format.

    A mapping of facts, assembled from feature 205's own
    :meth:`~signal_agent.SignalContract.declaration` rather than a second
    spelling of the ABI — the same restraint :mod:`signal_agent._authoring`
    states for its own declaration, and for the same reason: a hard-coded
    ``signal(ctx: MarketWindow, seed: int) -> pl.Series`` here would be a
    second thing to keep in sync with the contract member's own ABI.

    ``snapshot`` is threaded straight into :meth:`~signal_agent.
    SignalContract.declaration`'s own ``snapshot`` argument
    (bug_spec_prompt_available_streams.xml): ``None`` (the default, and what
    every caller that configures no evaluation context hands in) answers a
    declaration with no ``available_streams`` key, unchanged from before
    that bug's fix.  When ``available_streams`` is present, the *contract
    section itself* also states plainly what it means — a
    ``available_streams_note`` key, generated from that same mapping by
    :func:`_available_streams_statement` and folded into the declaration
    dict returned here (never a second, sibling fact at the task level, and
    never hard-coded to one snapshot's own cadence), so the two cannot
    disagree about what the snapshot holds.

    ``evaluation`` is threaded into :func:`_cost_awareness_part`, which folds
    a ``cost_awareness`` key into the returned mapping
    (additions_spec_cost_aware_selection.xml feature 4): ``None`` (the
    default) answers it with the honest ``"unmeasured"`` for the facts it
    did not carry, same as an unconfigured ``snapshot`` leaves
    ``available_streams`` out — except the ``cost_awareness`` key itself is
    always present, because feature 4 asks for the section to display
    regardless of whether a deployment has wired an evaluation context in.

    A ``theme_brief`` key is folded in last (additions_spec_guided_themes.xml
    feature 3), built by :func:`_theme_brief_part` off this task's own
    ``theme_root`` — the committed PRD §9.3 v2 brief for that root, or
    ``None`` when the committed document carries no brief for it.
    """
    contract = signal_contract().declaration(snapshot=snapshot)
    streams = contract.get("available_streams")
    if streams is not None:
        contract["available_streams_note"] = _available_streams_statement(streams)
    task = {
        "campaign_id": _validated_campaign_id(workspace),
        "theme_root": _validated_theme_root(workspace),
        "depth": _validated_depth(workspace),
        "contract": contract,
        "answer_format": dict(_ANSWER_FORMAT),
        "cost_awareness": _cost_awareness_part(evaluation),
    }
    task["theme_brief"] = _theme_brief_part(task["theme_root"])
    return task


# ── The anti-convergence half: the committed clause, verbatim ────────────────


def _clause_text(clause: object) -> str:
    """The committed clause's text, read duck-typed, refusing a blank one.

    Three shapes are accepted, because a caller holds one of three values:
    the clause's own text (a plain ``str``), a
    :class:`~signal_agent.AntiConvergenceClause` (``clause.text()``), or the
    composed :class:`~signal_agent.AntiConvergenceGate` itself
    (``gate.text()``, which delegates to its own clause).  All three answer
    with the same string for one deployment, so reading whichever is handed
    in cannot make the shipped clause disagree with the one feature 210's
    gate screens a prompt against.
    """
    if isinstance(clause, str):
        text = clause
    else:
        reader = getattr(clause, "text", None)
        candidate = reader() if callable(reader) else None
        text = candidate if isinstance(candidate, str) else None
    if text is None:
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: clause must be the committed "
            f"anti-convergence clause's text (a string), or a value "
            f"carrying a text() method that returns one — feature 210's "
            f"AntiConvergenceClause or AntiConvergenceGate — got "
            f"{type(clause).__name__}. A prompt that cannot read the clause "
            f"cannot ship PRD §C3's explicit anti-convergence clause "
            f"verbatim (feature 5)."
        )
    if not text.strip():
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: the anti-convergence clause's text is "
            f"blank. PRD §C3's clause is the one prose this member ships "
            f"verbatim, and a blank clause would be feature 210's "
            f"clause_absent failure arriving from this builder instead of "
            f"from AntiConvergenceGate.require_in (feature 5)."
        )
    return text


# ── The history half: every prior node, whole, in order ──────────────────────


def _validated_history(
    history: object,
) -> tuple[tuple[Any, ScoreRecord | None], ...]:
    """Every ``(PriorProposal, ScoreRecord | None)`` pair, unmodified, in order.

    Nothing is summarised, sampled or truncated: every entry the caller hands
    in is kept, in the caller's own order, with its proposal text and its
    score carried exactly as given.  What is checked is only the *shape* —
    that each entry is a pair, that its first element carries a prior
    proposal's three fields, and that its second is a
    :class:`~signal_agent.ScoreRecord` or ``None`` — because a shape this
    module cannot read is a caller's wiring fault, not a judgement about
    whether the history is complete (that is feature 206's
    :class:`~signal_agent.ProposalHistory`, a separate law over the same
    values).
    """
    if isinstance(history, (str, bytes, Mapping)):
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: history must be a sequence of "
            f"(PriorProposal, ScoreRecord or None) pairs, got "
            f"{type(history).__name__}; a bare string or mapping is one "
            f"value, not a sequence of prior nodes (feature 5)."
        )
    if not isinstance(history, Iterable):
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: history must be an iterable of "
            f"(PriorProposal, ScoreRecord or None) pairs, got "
            f"{type(history).__name__} (feature 5)."
        )
    entries: list[tuple[Any, ScoreRecord | None]] = []
    for index, entry in enumerate(history):
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise AuthoringPromptError(
                f"{AUTHORING_PROMPT_CODE}: history entry {index} is "
                f"{entry!r}, not a (PriorProposal, ScoreRecord or None) "
                f"pair. Every prior node of the campaign is a proposal "
                f"beside its score, verbatim, and an entry that is not a "
                f"two-element pair names neither (feature 5)."
            )
        prior, score = entry
        if not all(hasattr(prior, name) for name in _PRIOR_FIELDS):
            raise AuthoringPromptError(
                f"{AUTHORING_PROMPT_CODE}: history entry {index}'s first "
                f"element is {prior!r}, which carries no node_id, proposal "
                f"or code_hash. Feature 206's PriorProposal is the shape "
                f"this history is read as, and a value missing any of the "
                f"three is not one (feature 5)."
            )
        if score is not None and not callable(getattr(score, "to_json", None)):
            raise AuthoringPromptError(
                f"{AUTHORING_PROMPT_CODE}: history entry {index}'s score is "
                f"{score!r} ({type(score).__name__}), neither a ScoreRecord "
                f"nor None. A node not yet scored is recorded as None, "
                f"never as a placeholder value (feature 5)."
            )
        entries.append((prior, score))
    return tuple(entries)


class AuthoringPrompt:
    """The C3 authoring prompt's three named parts — a screenable value.

    What :func:`build_authoring_prompt` returns, and what
    :meth:`~signal_agent.PromptGuidanceGate.admit` reads as "an object whose
    attributes are the sections": ``task``, ``anti_convergence`` and
    ``history``, exactly :data:`PROMPT_PARTS` and in that order.  Carried as a
    ``__slots__`` object rather than a bare mapping so a caller reads
    ``parts.history`` the way every other value this member hands out is
    read — :class:`~signal_agent.ParsedProposal`,
    :class:`~signal_agent.PriorProposal`, :class:`~signal_agent.ProposalRecord`
    — while still satisfying :mod:`signal_agent._guidance`'s widest-match
    screen, which falls back to ``vars()`` or ``__slots__`` for an object
    shape.

    **Its constructor refuses nothing.**  Every refusal belongs to
    :func:`build_authoring_prompt`, the one construction site; a value that
    exists is one that construction already validated, the discipline
    :class:`~signal_agent.PriorProposal` and
    :class:`~signal_agent.ParsedProposal` state for their own constructors.
    """

    __slots__ = PROMPT_PARTS

    def __init__(
        self,
        *,
        task: Mapping[str, Any],
        anti_convergence: str,
        history: tuple[tuple[Any, ScoreRecord | None], ...],
    ) -> None:
        self.task = task
        self.anti_convergence = anti_convergence
        self.history = history

    def __eq__(self, other: object) -> bool:
        """Equal when the three parts are equal — never by ``isinstance``.

        The loader imports every member twice, once by file path under a
        synthetic name and once as the importable member, so an
        ``isinstance`` check against this class would be false for a value
        built from the other import of the same file — the discipline
        :class:`~signal_agent.PriorProposal.__eq__` states for its own.
        """
        if not all(hasattr(other, name) for name in PROMPT_PARTS):
            return NotImplemented
        return (
            self.task == other.task
            and self.anti_convergence == other.anti_convergence
            and self.history == other.history
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"AuthoringPrompt(task_keys={sorted(self.task)!r}, "
            f"anti_convergence_chars={len(self.anti_convergence)}, "
            f"history_nodes={len(self.history)})"
        )


def build_authoring_prompt(
    workspace: object,
    history: Iterable[tuple[Any, ScoreRecord | None]],
    *,
    clause: object,
    snapshot: Any | None = None,
    evaluation: Any | None = None,
) -> AuthoringPrompt:
    """Build the C3 authoring prompt's three named parts.

    ``workspace`` is duck-typed: it reads ``campaign_id``, ``theme_root`` and
    ``depth`` off it, by mapping key or by attribute.  ``history`` is a
    sequence of ``(PriorProposal, ScoreRecord | None)`` pairs — the store's
    own order, carried whole: nothing is summarised, sampled or truncated.
    ``clause`` is the committed anti-convergence clause, as its text, or as a
    value carrying a ``text()`` method that returns it.  ``snapshot``, when
    given, is the sealed snapshot mount feature 7's composed author resolved
    from ``NULLIUS_EVALUATION_CONFIG`` (bug_spec_prompt_available_streams.xml)
    — passed straight through to :meth:`~signal_agent.SignalContract.
    declaration`, so the task's ``contract`` carries ``available_streams``
    exactly when a caller configured one.  ``evaluation``, when given, is a
    duck-typed evaluation context read for ``evaluation_dates`` and
    ``per_rebalance_cost_bps`` (additions_spec_cost_aware_selection.xml
    feature 4) — folded into the task's ``cost_awareness`` key by
    :func:`_cost_awareness_part`, which answers ``"unmeasured"`` for either
    fact ``evaluation`` does not carry (``None`` included).

    The returned :class:`AuthoringPrompt` is the value
    :meth:`~signal_agent.PromptGuidanceGate.admit` screens and
    :func:`to_request` renders into a :class:`providers.Request`; this
    function raises :class:`AuthoringPromptError` rather than build a prompt
    it cannot name the parts of, and never summarises, samples or truncates
    anything it is handed.
    """
    task = _task_part(workspace, snapshot, evaluation)
    anti_convergence = _clause_text(clause)
    entries = _validated_history(history)
    return AuthoringPrompt(
        task=task, anti_convergence=anti_convergence, history=entries
    )


# ── Rendering: parts in, one providers.Request out ────────────────────────────


def _part(parts: object, name: str) -> object:
    """Read one named part off ``parts``, in whichever shape it arrived.

    Three shapes, because a caller may hold the value at three different
    points in the pipeline: the :class:`AuthoringPrompt`
    :func:`build_authoring_prompt` returned (read by attribute); a mapping a
    caller assembled by hand; or the ``tuple[(name, content), ...]`` a
    :class:`~signal_agent.GuidanceVerdict`'s ``sections`` or ``require()``
    hands back after screening the prompt — the realistic shape a caller has
    in hand right before it renders and ships, since the documented pattern
    is to call :meth:`~signal_agent.PromptGuidanceGate.require` on the parts
    before flattening them.  Reading all three means :func:`to_request` can
    sit immediately after that call without a caller re-wrapping its answer.
    """
    if isinstance(parts, Mapping):
        return parts.get(name)
    if isinstance(parts, (tuple, list)):
        for entry in parts:
            if (
                isinstance(entry, tuple)
                and len(entry) == 2
                and entry[0] == name
            ):
                return entry[1]
        return None
    return getattr(parts, name, None)


def _render_system(task: object, anti_convergence: object) -> str:
    """The system message: the task's facts, then the clause, verbatim.

    JSON for the task — deterministic, sorted, and exactly the shape
    :meth:`~signal_agent.ScoreRecord.to_json` and every other rendered
    document in this member takes — and the clause's own text appended
    unmodified, so the rendered string carries it as an exact substring:
    that is what lets :meth:`~signal_agent.AntiConvergenceGate.require_in`
    accept this very message.
    """
    if not isinstance(anti_convergence, str):
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: the anti_convergence part is "
            f"{anti_convergence!r} ({type(anti_convergence).__name__}), not "
            f"text; the system message carries the committed clause "
            f"verbatim, and a non-string part has no verbatim text to carry "
            f"(feature 5)."
        )
    rendered_task = json.dumps(task, sort_keys=True, indent=2, default=str)
    return (
        "## Task\n"
        f"{rendered_task}\n\n"
        "## Anti-convergence clause\n"
        f"{anti_convergence}"
    )


def _render_history(history: object) -> str:
    """The user message: every prior node, in order, whole.

    One block per entry — its ``node_id``, its ``code_hash``, its complete
    ``proposal.md`` text, its ``score.json`` (or the literal ``null`` for
    a node not yet scored), and a ``cost figures`` line naming
    ``ic_tstat``, ``ir_tstat``, ``turnover`` and ``cost_adjusted_ir``
    explicitly (:func:`_cost_figures`, additions_spec_cost_aware_selection.xml
    feature 4) — and nothing else: no entry is skipped, no proposal is cut,
    and no run is sampled.  The cost figures line is appended after
    ``score.json``, never in place of it: the full recorded score still
    renders exactly as it did before feature 4. An empty history renders as
    the honest statement that there is none yet, which is the correct state
    for a campaign's first node and not a reason to refuse (feature 206's
    own stance toward an empty history, restated here for its rendering).
    """
    if not isinstance(history, Iterable) or isinstance(history, (str, bytes, Mapping)):
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: the history part is "
            f"{history!r} ({type(history).__name__}), not an iterable of "
            f"(PriorProposal, ScoreRecord or None) pairs (feature 5)."
        )
    entries = list(history)
    if not entries:
        return (
            "## History\n"
            "No prior proposals exist yet for this campaign; this is the "
            "first node."
        )
    blocks: list[str] = []
    for prior, score in entries:
        score_json = score.to_json() if score is not None else "null"
        cost_figures = json.dumps(_cost_figures(score), sort_keys=True)
        blocks.append(
            f"### node {_field(prior, 'node_id')} "
            f"(code_hash {_field(prior, 'code_hash')})\n"
            f"proposal.md:\n{_field(prior, 'proposal')}\n\n"
            f"score.json:\n{score_json}\n\n"
            f"cost figures: {cost_figures}"
        )
    return "## History\n\n" + "\n\n".join(blocks)


def to_request(
    parts: object,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> Any:
    """Render admitted prompt parts into the one :class:`providers.Request`.

    One ``system`` message carrying the ``task`` and ``anti_convergence``
    parts, one ``user`` message carrying the ``history`` part — the split
    :mod:`signal_agent._guidance` and :mod:`signal_agent._anti_convergence`
    each screen a different half of: the system message is what
    :meth:`~signal_agent.AntiConvergenceGate.require_in` accepts (the clause
    is an exact substring of it), and ``parts`` itself — read before this
    call — is what :meth:`~signal_agent.PromptGuidanceGate.admit` screens.

    ``providers`` is imported here, deferred, rather than at module scope —
    see the module docstring.
    """
    from providers import Message, Request

    task = _part(parts, "task")
    anti_convergence = _part(parts, "anti_convergence")
    history = _part(parts, "history")
    if task is None or anti_convergence is None or history is None:
        missing = [
            name
            for name, value in (
                ("task", task),
                ("anti_convergence", anti_convergence),
                ("history", history),
            )
            if value is None
        ]
        raise AuthoringPromptError(
            f"{AUTHORING_PROMPT_CODE}: parts carries no {', '.join(missing)}; "
            f"to_request renders the task and anti_convergence parts into "
            f"one system message and the history part into one user "
            f"message, and a part that is absent has nothing to render "
            f"(feature 5)."
        )
    return Request(
        messages=(
            Message(role="system", content=_render_system(task, anti_convergence)),
            Message(role="user", content=_render_history(history)),
        ),
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
