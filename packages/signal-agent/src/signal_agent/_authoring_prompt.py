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
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Final

from ._authoring import signal_contract
from ._proposal import ScoreRecord
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


def _task_part(workspace: object, snapshot: Any | None = None) -> dict[str, Any]:
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
    """
    contract = signal_contract().declaration(snapshot=snapshot)
    streams = contract.get("available_streams")
    if streams is not None:
        contract["available_streams_note"] = _available_streams_statement(streams)
    return {
        "campaign_id": _validated_campaign_id(workspace),
        "theme_root": _validated_theme_root(workspace),
        "depth": _validated_depth(workspace),
        "contract": contract,
        "answer_format": dict(_ANSWER_FORMAT),
    }


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
    exactly when a caller configured one.

    The returned :class:`AuthoringPrompt` is the value
    :meth:`~signal_agent.PromptGuidanceGate.admit` screens and
    :func:`to_request` renders into a :class:`providers.Request`; this
    function raises :class:`AuthoringPromptError` rather than build a prompt
    it cannot name the parts of, and never summarises, samples or truncates
    anything it is handed.
    """
    task = _task_part(workspace, snapshot)
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
    ``proposal.md`` text, and its ``score.json`` (or the literal ``null`` for
    a node not yet scored) — and nothing else: no entry is skipped, no
    proposal is cut, and no run is sampled.  An empty history renders as the
    honest statement that there is none yet, which is the correct state for
    a campaign's first node and not a reason to refuse (feature 206's own
    stance toward an empty history, restated here for its rendering).
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
        blocks.append(
            f"### node {_field(prior, 'node_id')} "
            f"(code_hash {_field(prior, 'code_hash')})\n"
            f"proposal.md:\n{_field(prior, 'proposal')}\n\n"
            f"score.json:\n{score_json}"
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
