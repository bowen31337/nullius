"""Feature 208's law: the prompt carries no summarized directional guidance.

app_spec.xml, "Hypothesis Authoring Agent", feature 208: *System rejects
injecting summarized directional guidance into the prompt, because prose
priors over-constrain the search space.*  docs/alpha-engine-prd.md §C3 states
the requirement as a rule about what the prompt may carry, and states it in
the imperative::

    Do not inject high-level directional guidance from history into the
    prompt. The paper's Figure 5 found this consistently *underperformed* the
    unguided version across both paradigms, because strong semantic priors
    about future search directions over-constrain the space and impede diverse
    exploration. Keep history as an interactive replay object, not as prose
    advice. This is counterintuitive and most implementations get it
    backwards.

docs/nullius-tech-architecture.md §14.1:773 states the same rule as the
answer to the context-window problem the read-everything requirement creates::

    Do not solve this by summarizing history into guidance. The paper's
    Figure 5 found that actively hurt. Truncating complete proposals is a
    different operation from compressing them into prose, and is probably
    safer — but it is an untested assumption and should be measured before it
    is relied on.

Two claims are bundled in the feature's sentence and this law is both of them,
because either alone is a preference rather than a refusal:

* **rejects injecting summarized directional guidance into the prompt** — the
  *injection* is the subject, and an injection is an act an assembler
  performs on the prompt it is building.  So the law sits at the assembly
  seam: the caller hands it the prompt's **parts** — the named sections the
  flattener is about to render — and :meth:`PromptGuidanceGate.admit` refuses
  any part that *declares itself* guidance, by its role name or by its
  declared provenance.  The verdict is a value; ``require`` on it is the one
  place :class:`~signal_agent.InjectedGuidanceError` exists.

* **because prose priors over-constrain the search space** — the *because* is
  not decoration, and it is what the refusal's sentence carries: the paper's
  Figure 5 finding, quoted from PRD §C3, so a caller reading the refusal
  learns the reason the section it was proud of is not in the prompt.  PRD
  §C3's last line — *"This is counterintuitive and most implementations get
  it backwards"* — is the whole reason the refusal exists as a law rather
  than as a convention in a template: the implementation that gets it
  backwards believes the guidance section is an improvement.

**What the law reads, and why it refuses what it cannot.**  Three shapes of
prompt parts are recognised, widest first, because an assembler has whatever
its own driver produced: a mapping of section name to content, an object
whose attributes are the sections, and a sequence of entries that each name
themselves.  A flat prompt string is **refused** as
:data:`NOT_PROMPT_PARTS_CODE` rather than scanned, and the refusal is the
honest one: this member's discipline about prose scanning is stated at
:mod:`signal_agent._history`, which declines to pattern-scan proposal text
for truncation markers because a marker is a convention rather than an
encoding — and the same reasoning here is stronger, not weaker.  A scan of
prompt prose for guidance words would refuse the very content §C3 and §14.1
*require* — every prior ``proposal.md`` in full, feature 206's whole subject —
the first time a proposal carries a "Summary" heading of its own, and would
admit the guidance that never used the word.  A law that cannot see the
declared structure certifies nothing, which is the same fail-closed stance
:meth:`signal_agent.AntiConvergenceGate.carries` takes toward a prompt when
its own clause is unreadable: the alternative is a silent green tick on a
prompt nobody checked.

**Why the declared role is the load-bearing check, when feature 206 needed a
recomputed one.**  :mod:`signal_agent._history` refuses truncated histories
through *recomputed identity* because its failure mode is a loader that
truncates *without saying so* — a law that only read declarations would be
satisfied by silence.  This feature's failure mode is the opposite of silent:
§C3's *"most implementations get it backwards"* names an implementation that
adds the guidance section *believing it helps*, under a name that says what
it is — "summary", "lessons", "insights", "directions" — because from that
implementation's chair the section is the feature.  The injection arrives
declared, so the declaration is what the law reads.  An operator who wanted
guidance past this gate would have to lie about the section's name, and a
liar defeats every screen short of a model's judgement — a member that
pretended otherwise by scanning prose would produce the false refusals and
false admissions described above while looking like rigour.

**The vocabulary, and its deliberate near-misses.**  :data:`_GUIDANCE_ROLES`
is a *denylist* of declared roles, the §C3 sibling of feature 213's §9.4
denylist, and for the same reason an allowlist would be wrong here: PRD §9
makes the campaign the unit of search and a deployment may add sections the
member never imagined ("budget", "universe", "rotation") without asking this
law's permission — the law refuses the one thing §C3 forbids rather than
everything §C3 does not name.  Names are normalised before matching (case,
spacing and punctuation), because a role is a word rather than a spelling;
matching is exact after that, never a substring.  Three near-misses are
deliberately **not** in the set, and each is load-bearing:

* ``themes`` — the legal theme set is a §9.3 fact the prompt legitimately
  carries (``legal_roots``, feature 218's own vocabulary), and a section
  named for it is configuration rather than direction;
* ``scores`` / ``records`` — §14.1's prompt carries each proposal's
  ``score.json`` beside it, and a score record is a *fact per node*, not
  prose about where to look: the record is the replay object's content, and
  refusing it would refuse §C3's "interactive replay object" for being one;
* ``history`` / ``proposals`` — the sections this law exists to *protect*,
  whose wholeness is feature 206's judgment and never this one's.

A role refuses only when its content is truthy: ``summary: ""`` injects
nothing, and refusing on the field name alone would refuse a template's
empty placeholder slot — the same reading
:func:`signal_agent._history._declared_loss` takes of a ``dropped: []``.

**Declared provenance, the second half of the declaration.**  A part whose
name is innocent may still *say where it came from*, and where it came from
is the history: :data:`_DISTILLING_KEYS` are the keys that declare a
distillation (``derived_from``, ``distilled_from``, ``summarized_from``,
...) and :data:`_HISTORY_TOKENS` the words a provenance value may name
(history, priors, proposals, the tree, the campaign, its scores) for the
declaration to be this feature's subject.  A part declaring
``derived_from: "contract"`` is admitted — feature 205's declaration is
facts, and prose derived from facts is not a prior about *where to look* —
while ``derived_from: "prior proposals"`` is refused whatever the part is
called, because §14.1's sentence names the operation exactly: *compressing
[complete proposals] into prose*.

**The boundary with feature 206.**  §14.1:773 draws it: *truncating* a
proposal is a different operation from *compressing* it into prose.  Feature
206 judges the **history handed to the assembler** — every prior proposal,
whole, by recomputed identity; this law judges the **prompt shipped to the
agent** — no part of it declared as distilled guidance.  The two compose into
§C3's one sentence, *"Keep history as an interactive replay object, not as
prose advice"*: 206 is the replay half (the history arrives whole) and 208 is
the not-prose half (nothing about it is re-told as advice).  Neither law
reads the other's subject: this law does not look inside a ``history``
section's entries — a ``summary_of`` declaration on an entry there is
feature 206's :data:`~signal_agent.SAMPLED_HISTORY_CODE` refusal, not this
law's — and 206 never refuses a summary for being *guidance*, only for being
a sample.  A prompt needs both gates to be §C3-shaped: whole history in,
no prose about it.

**The boundary with feature 210.**  The committed anti-convergence clause is
the one prose this member compiles, and
:mod:`signal_agent._anti_convergence` documents why it stays on the right
side of §C3: it is a *negative constraint* — it names no direction to search
in and carries nothing distilled from campaign history.  This law's
denylist agrees by construction: the clause travels under whatever section
name the campaign gives it, none of :data:`_GUIDANCE_ROLES` matches that
name, and the clause's text declares no provenance.  A prompt carrying the
committed clause, the contract declaration and the whole history is admitted
here and *required* by feature 210's :meth:`~signal_agent.AntiConvergenceGate.
require_in` — the two prompt-side laws pull in opposite directions on
purpose, because §C3 demands exactly one thing the prompt must carry and one
class of thing it must not.

**Why the refusal is a returned value and not an exception.**  What a run
does about an injected-guidance finding is not this law's decision — the
section is deleted by the run's own assembler, and a caller that wanted to
*measure* how often its assemblies carried guidance (the §14.1:773 instinct
— measure the assumption before relying on it — applied to the *other* side
of the truncation trade) cannot do that through a raise.  So ``admit`` never
raises, :meth:`GuidanceVerdict.require` is the one place the exception
exists, for a caller whose last line before shipping the prompt wants it,
and :meth:`PromptGuidanceGate.unguided` is the boolean read for the caller
that only wanted the question answered.

**The asymmetry at the error.**
:class:`~signal_agent.InjectedGuidanceError` is a *sibling* of
:class:`~signal_agent.AgentSourceError`, of
:class:`~signal_agent.TruncatedHistoryError` and of
:class:`~signal_agent.AntiConvergenceClauseError`, not a subclass of any of
them — the discipline :class:`~signal_agent.TruncatedHistoryError` states:
a caller's pre-existing ``except AgentSourceError:`` handler repairs by
re-prompting the agent, and re-prompting does nothing about a prompt that
will be re-assembled the same way; the repair is to delete the section and
re-ship, which is the assembler's job, not the agent's.  It is a sibling of
the clause error rather than folded into it because the two prompt-side
refusals are opposites a caller must tell apart — 210's says the prompt is
*missing* what §C3 requires, this one says it *carries* what §C3 forbids —
and an operator grepping a campaign log for one must not find the other.

Stdlib only, and import-cheap — :mod:`enum` and :mod:`re` — so the factory's
scan, which imports this package to fire its ``@register``, pays nothing for
it, and the law compiles no artifact, reads no environment and resolves no
member: presence in the composed application cannot depend on scan order.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Iterable, Mapping
from typing import Any, Final

from .errors import InjectedGuidanceError

__all__ = [
    "GUIDANCE_COMPONENT_NAME",
    "INJECTED_GUIDANCE_CODE",
    "MAX_LISTED_INJECTIONS",
    "NOT_PROMPT_PARTS_CODE",
    "UNGUIDED_CODE",
    "GuidanceReason",
    "GuidanceVerdict",
    "PromptGuidanceGate",
    "prompt_guidance_gate",
]

#: The component name the plugin registers this law's component under.
#: Hyphenated like its siblings so the member's components stay contiguous
#: in the loader's name-sorted ``app.order``, and prefixed rather than bare so
#: a later registration cannot replace the plugin's own ``signal-agent``
#: component by colliding with it — the registry-replacement hazard
#: :data:`signal_agent.THEMES_COMPONENT_NAME` names.  ``signal-agent-guidance``
#: sorts between ``signal-agent-diagnosis`` and ``signal-agent-history``, so
#: the member's eight components stay contiguous in the category they belong
#: to.
GUIDANCE_COMPONENT_NAME: Final[str] = "signal-agent-guidance"

#: The token every admitted prompt's sentence carries — the feature's own
#: subject written as a word, so an operator grepping a campaign log for the
#: rounds that shipped a clean prompt finds them by it.  ``unguided`` rather
#: than ``clean`` or ``legal`` because *unguided* is the paper's own word for
#: the version that won — PRD §C3: *"consistently underperformed the
#: **unguided** version"* — so the admission reads as the property that made
#: the difference rather than as an absence.  Its mirror is the refusal,
#: which opens with :data:`INJECTED_GUIDANCE_CODE` instead; an admission is
#: not a code an operator greps a campaign for, the same asymmetry
#: :data:`signal_agent.LEGAL_THEME_CODE` and
#: :data:`signal_agent.COMPLETE_HISTORY_CODE` have against their reasons.
UNGUIDED_CODE: Final[str] = "unguided_prompt"

#: Refused: a part of the prompt declares itself summarized directional
#: guidance — by its role name or by its declared provenance.  The feature's
#: own subject: *System rejects injecting summarized directional guidance into
#: the prompt*.
INJECTED_GUIDANCE_CODE: Final[str] = "injected_guidance"

#: Refused: what was handed over carries no parts this law can screen — a
#: flat prompt string, a bare ``None``, a number.  The caller's wiring is
#: wrong, not the prompt's contents: the law reads the *declared structure*
#: of the prompt and a value with none is not screenable, which is a fact
#: about the call rather than a finding about a section — the same split
#: :data:`signal_agent.NOT_A_HISTORY_CODE` draws for a value that was never a
#: history.
NOT_PROMPT_PARTS_CODE: Final[str] = "not_prompt_parts"

#: How many offending sections a refusal's sentence names before it stops and
#: counts the rest.  Bounded for the same reason
#: :data:`signal_agent.MAX_LISTED_OFFENDERS` is: the sentence is read by a
#: human fixing an assembler, and an unbounded list is a message nobody reads.
MAX_LISTED_INJECTIONS: Final[int] = 8

#: The fields a sequence entry may name itself by, in the order they are
#: read.  A part of a prompt is screenable when it *declares* what it is, and
#: a sequence entry declares that with one of these — the duck-typed seam
#: feature 184's question and feature 190's adapter both use, read here at
#: the one place a section's identity lives.
_NAME_FIELDS: Final[tuple[str, ...]] = ("name", "role", "section", "title")

#: The declared roles this law refuses — a denylist, the §C3 sibling of
#: feature 213's §9.4 denylist, drawn from the words the documents themselves
#: use for the forbidden thing: PRD §C3's *"high-level directional guidance"*
#: and *"prose advice"*, §14.1:773's *"summarizing history into guidance"*.
#: Names are normalised before matching (see :func:`_normalised`), so the set
#: holds the normal forms.  Refused regardless of the section's content when
#: that content is truthy; the near-misses deliberately absent — ``themes``,
#: ``scores``, ``history`` — are documented at :func:`_guidance_role`.
_GUIDANCE_ROLES: Final[frozenset[str]] = frozenset(
    {
        "advice",
        "digest",
        "direction",
        "directional",
        "directional_guidance",
        "directions",
        "guidance",
        "guidance_summary",
        "hints",
        "history_digest",
        "history_summary",
        "insights",
        "lessons",
        "lessons_learned",
        "recommendations",
        "summary",
        "summary_of_history",
        "synthesis",
        "takeaways",
        "tips",
        "trends",
        "what_failed",
        "what_worked",
    }
)

#: The keys a part's content may declare its own provenance with — the
#: distillation verbs.  Read only on content that is itself a mapping or an
#: object with the named attribute, because provenance is a field a record
#: carries, not a property of prose; and refused only when the value names
#: the history (see :data:`_HISTORY_TOKENS`), because §C3 forbids guidance
#: *from history*, not derivation as such.  Both ``-zed`` and ``-sed``
#: spellings, because the repository's own documents use the American
#: (§14.1 *"summarizing"*) while a caller's records may use either.
_DISTILLING_KEYS: Final[frozenset[str]] = frozenset(
    {
        "derived_from",
        "distilled_from",
        "generated_from",
        "summarised_from",
        "summarized_from",
        "synthesised_from",
        "synthesized_from",
    }
)

#: The words a provenance value may name for the declared source to be *the
#: history* — the subject §C3's rule is about.  Matched as whole tokens over
#: the normalised value, never as substrings, so a provenance of
#: ``"history_of_mathematics"`` is read as the tokens ``history`` (a match —
#: and honestly so: a section distilled from *any* history is prose about a
#: past) while ``"contract"`` and ``"manifest"`` are not.  ``score``/
#: ``scores``/``scoring`` are members because §14.1's prompt carries
#: ``score.json`` per node as *records*; prose *derived from* them is exactly
#: the Figure 5 finding re-stated, which is the thing that underperformed.
_HISTORY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "campaign",
        "campaigns",
        "history",
        "node",
        "nodes",
        "prior",
        "priors",
        "proposal",
        "proposals",
        "score",
        "scores",
        "scoring",
        "tree",
        "trees",
    }
)

#: The splitter for provenance values and section names: anything that is not
#: a lowercase letter or digit is a separator.  One regex, stated once, so the
#: normal form the vocabulary is written in and the normal form the caller's
#: names are read in cannot drift apart.
_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"[^0-9a-z]+")


def _normalised(name: object) -> str:
    """The normal form of a section name or provenance value.

    Lowercased, with every run of non-alphanumerics collapsed to one
    underscore and the edges trimmed, so ``"Prior Insights"``,
    ``"PRIOR-INSIGHTS"`` and ``"prior_insights"`` are one role — a role is a
    word, not a spelling, and refusing only the underscored form would be a
    law about typography rather than about guidance.  Not a substring
    operation: the normal form is *matched against* the vocabulary, so
    ``"historical_context"`` (normal form ``historical_context``) is not the
    role ``history_summary`` and is not refused for containing ``history``.
    """
    return _SEPARATORS.sub("_", str(name).strip().lower()).strip("_")


def _field(value: object, name: str) -> object:
    """Read one field from a mapping key or an attribute, or ``None``.

    The duck-typed seam :func:`signal_agent._history._field` states for its
    own entries, restated here because its subject is private to that module:
    a caller hands over its own record type, a mapping, or a mapping-like
    object, and the law reads fields by name without demanding a class.
    """
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _declared_name(entry: object) -> str | None:
    """The name a sequence entry declares itself with, or ``None``.

    The first of :data:`_NAME_FIELDS` present as a non-empty string wins, in
    the tuple's order, so two fields naming one entry cannot produce two
    verdicts.  ``None`` — not a positional placeholder — because a sequence
    entry that names itself nothing is a part with no declaration, and the
    law's honest answer to that is :data:`NOT_PROMPT_PARTS_CODE` rather than
    a silently screened ``section-3``: a part that cannot be named cannot
    declare a role, and reading it anyway would be the vacuous green this
    member refuses everywhere.
    """
    for field in _NAME_FIELDS:
        name = _field(entry, field)
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _attributes_of(prompt: object) -> dict[str, Any] | None:
    """The instance attributes of an object-shaped prompt, or ``None``.

    ``vars()`` for the ordinary case — a dataclass instance, a plain object,
    a ``SimpleNamespace`` — and the class's ``__slots__`` for the case
    ``vars()`` cannot reach: a slots instance has no ``__dict__``, and a
    member of a workspace that hand-writes ``__slots__`` on its own values
    (feature 223's prefix view is the named precedent) would be unscreenable
    by a law that only knew ``vars()``.  ``None`` when neither reading
    yields anything — an ``object()`` with no state names no parts, and the
    caller is told to hand parts rather than handed a vacuous admission:
    an empty *mapping* is a template's deliberately-empty prompt, an
    attribute-less *object* is a stray value, and only the first of those
    is a prompt this law can certify.
    """
    try:
        fields = dict(vars(prompt))  # type: ignore[arg-type]
    except TypeError:
        slots = getattr(type(prompt), "__slots__", ())
        if isinstance(slots, str) or not isinstance(slots, Iterable):
            return None
        fields = {
            name: getattr(prompt, name)
            for name in slots
            if isinstance(name, str) and hasattr(prompt, name)
        }
    return fields or None


def _sections_of(prompt: object) -> list[tuple[str, object]] | None:
    """Every named part of the handed-over prompt, or ``None`` if unrecognised.

    The shapes, widest first, because a caller assembling a prompt has
    whatever its own driver produced:

    * a **mapping** of section name to content — the canonical shape, the
      one a template engine or a JSON prompt document produces, read in the
      mapping's own order so the admitted parts come back in the order the
      flattener would render them;
    * an **object whose attributes are the sections** — a dataclass or a
      namespace, the shape a typed driver builds;
    * a **sequence of entries that each name themselves** — lists of
      section records, each carrying one of :data:`_NAME_FIELDS`.

    A bare ``str``/``bytes`` is not any of these: it is the *rendered*
    prompt, and the law refuses it as :data:`NOT_PROMPT_PARTS_CODE` for the
    reasons the module docstring gives — a flat text cannot be screened
    honestly, and certifying it would be the silent green tick.  ``None`` and
    every other non-shape are refused the same way, the caller's wiring
    rather than the prompt's contents.  An *empty* mapping or sequence is
    admitted: a prompt with no parts injects nothing, exactly as an empty
    history is a whole history (feature 206), and refusing it would block
    the empty-prompt case the way refusing an empty history would block a
    campaign's first round.
    """
    if isinstance(prompt, (str, bytes)):
        return None
    if isinstance(prompt, Mapping):
        return [(str(name), content) for name, content in prompt.items()]
    if isinstance(prompt, Iterable):
        sections: list[tuple[str, object]] = []
        for entry in prompt:
            if isinstance(entry, (str, bytes)):
                return None
            name = _declared_name(entry)
            if name is None:
                return None
            sections.append((name, entry))
        return sections
    attributes = _attributes_of(prompt)
    if attributes is None:
        return None
    return [(str(name), content) for name, content in attributes.items()]


def _guidance_role(name: object) -> str | None:
    """The guidance role a section name declares, or ``None``.

    A *whole-name* match over the normal form, never a substring, so the
    near-misses stay near-misses: ``themes`` (the §9.3 legal set is a fact
    the prompt may carry), ``scores`` (§14.1's per-node ``score.json``
    records *are* the replay object's content), ``history`` and
    ``proposals`` (the sections this law exists to protect, whose wholeness
    is feature 206's judgment) are all admitted by this function, and a
    section called ``historical_context`` is too — ``context`` is not a
    guidance word and ``history`` inside a longer name is a substring this
    function deliberately does not match.
    """
    normal = _normalised(name)
    if normal in _GUIDANCE_ROLES:
        return normal
    return None


def _names_history(value: object) -> bool:
    """Whether a provenance value names the history, as whole tokens.

    ``str()`` first, so a structured value (a list of source names, a
    record's ``__str__``) is read for its words rather than refused for its
    type — a caller's provenance field is its own vocabulary and the words
    are what the declaration means.  Tokenised by the same
    :data:`_SEPARATORS` the roles use, so the two normal forms cannot drift.
    """
    tokens = _SEPARATORS.split(str(value).lower())
    return any(token in _HISTORY_TOKENS for token in tokens)


def _distilled_from_history(content: object) -> str | None:
    """The provenance declaration that makes ``content`` distilled history.

    Read only on content that is a mapping or carries the named attribute,
    because a provenance is a field a record declares, not a property of
    prose.  Returns the declaring key and its value as one sentence-able
    phrase (``derived_from: 'prior proposals'``) for the refusal to quote,
    or ``None``.  A declaration whose value names nothing in
    :data:`_HISTORY_TOKENS` — ``derived_from: "contract"``` — is *not* this
    feature's subject and is not refused: PRD §C3 forbids guidance *from
    history*, and prose derived from the declared ABI is not a prior about
    where to search.

    Sorted key order, so a record carrying two declarations is refused the
    same way twice — the reason :func:`signal_agent._history._declared_loss`
    iterates sorted, restated for this law's own vocabulary.
    """
    if isinstance(content, (str, bytes)):
        return None
    for key in sorted(_DISTILLING_KEYS):
        value = _field(content, key)
        if value is not None and str(value).strip() and _names_history(value):
            return f"{key}: {value!r}"
    return None


def _listed(offenders: list[str]) -> tuple[str, ...]:
    """The distinct offending sections, sorted, for the verdict to carry.

    Sorted and de-duplicated — the same section found by both checks, or
    named twice by a sequence of entries, is one deletion — because the
    count an operator reads is the count of things to remove, and an
    inflated number is a misleading one.  The sentence's own bounded
    listing is built from the per-section notes in the caller's order
    instead, so a reader of the refusal hits the declarations in the order
    the prompt carries them.
    """
    return tuple(sorted(dict.fromkeys(offenders)))


class GuidanceReason(enum.StrEnum):
    """Why a prompt was admitted or refused — the audit vocabulary.

    A :class:`enum.StrEnum` whose *value* is the token its own
    :attr:`GuidanceVerdict.detail` opens with, so the reason is greppable in
    a campaign log without a lookup table and a refusal never opens with
    another reason's headline — the discipline
    :class:`signal_agent.HistoryReason` states for its own.  The two
    refusals are split by *repair*, not by which check found the section: a
    declared injection is deleted by the assembler, and a value with no
    screenable structure is re-handed by the caller — one fixes the prompt,
    the other fixes the call.
    """

    #: Admitted: no part of the prompt declares itself summarized
    #: directional guidance, by role or by provenance.  Its detail opens
    #: with :data:`UNGUIDED_CODE` rather than with this value, the one place
    #: this enum and its codes differ — the same asymmetry
    #: :attr:`signal_agent.HistoryReason.COMPLETE` has against
    #: :data:`signal_agent.COMPLETE_HISTORY_CODE`.  "unguided" is the reason
    #: a caller branches on; "unguided_prompt" is the word a log line opens
    #: with, and an admission is not a code an operator greps a campaign for.
    UNGUIDED = "unguided"

    #: Refused: a part of the prompt declares itself summarized directional
    #: guidance — its role name is in the vocabulary, or its content
    #: declares a distillation whose source is the history.  One reason for
    #: both declarations because the repair is one action: delete the
    #: section; the sentence names each part and *which* declaration matched,
    #: so the distinction an operator needs is in the detail rather than in
    #: a second reason to branch on.  Spelled as the code itself, so
    #: branching on the value and grepping for it are the same string.
    INJECTED_GUIDANCE = INJECTED_GUIDANCE_CODE

    #: Refused: the value handed over carries no parts this law can screen.
    #: Its own reason rather than a spelling of the injection case because
    #: the repair is different in kind: there is no section to delete — the
    #: caller must hand the prompt's named parts, and an operator looking
    #: for an injected section would be looking in the wrong place.  Spelled
    #: as the code itself, for the same reason :attr:`INJECTED_GUIDANCE` is.
    NOT_PROMPT_PARTS = NOT_PROMPT_PARTS_CODE


class GuidanceVerdict:
    """What the law decided about one prompt, plus the parts it admitted.

    Read-only in the sense that matters: every field is set once, in
    :func:`_verdict`, from the *reason* and the sections that produced it —
    :attr:`admitted` is never a constant a caller could set, and a verdict
    cannot disagree with its own reason.  The same shape
    :class:`signal_agent.HistoryVerdict`,
    :class:`signal_agent.DeadTerritoryVerdict` and
    :class:`signal_agent.AntiConvergenceVerdict` use.

    :attr:`sections` is empty on **every** refusal, including
    :attr:`GuidanceReason.NOT_PROMPT_PARTS` — there is nothing to flatten
    and nothing to hand an agent, and returning the screenable prefix of a
    prompt this law just refused would let a caller ship exactly the prompt
    this feature exists to stop.  The offending sections are carried
    separately, in :attr:`offenders`, for the message and for a log — named,
    never quoted, because the prose of an injected section is the thing to
    delete, not the thing to re-print in a log line where a reader might
    mistake it for content the system endorses.

    **Its constructor refuses nothing.**  A caller holding a refusal is the
    caller that most needs one, and it cannot be told about an object it was
    never allowed to build — the discipline
    :class:`signal_agent.SourceAdoption` and
    :class:`signal_agent.HistoryVerdict` state for their own constructors.
    """

    __slots__ = ("admitted", "detail", "offenders", "reason", "sections")

    def __init__(
        self,
        reason: GuidanceReason,
        detail: str,
        *,
        sections: Iterable[tuple[str, object]] = (),
        offenders: Iterable[str] = (),
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.offenders = tuple(offenders)
        #: Computed from the reason, never passed in: a verdict whose
        #: ``admitted`` flag disagreed with its reason would be a value a
        #: caller could branch on twice and get two answers.
        self.admitted = reason is GuidanceReason.UNGUIDED
        self.sections = tuple(sections) if self.admitted else ()

    def require(self) -> tuple[tuple[str, object], ...]:
        """Return the admitted parts, or raise :class:`InjectedGuidanceError`.

        The only place this law raises.  A caller whose next line is the
        flatten-and-ship wants the raise; a caller measuring its assemblies
        branches on :attr:`admitted` instead and never constructs the
        exception — which is why the verdict exists at all.  The parts come
        back in the caller's own order, contents untouched, so the prompt
        that ships is the prompt that was screened and not a re-ordered or
        re-written one.
        """
        if not self.admitted:
            raise InjectedGuidanceError(self.detail)
        return self.sections

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"GuidanceVerdict({self.reason.value!r}, "
            f"sections={len(self.sections)}, offenders={len(self.offenders)})"
        )


def _verdict(
    reason: GuidanceReason,
    detail: str,
    *,
    sections: Iterable[tuple[str, object]] = (),
    offenders: Iterable[str] = (),
) -> GuidanceVerdict:
    """Build a verdict.  The one construction site, so no verdict is hand-made."""
    return GuidanceVerdict(reason, detail, sections=sections, offenders=offenders)


class PromptGuidanceGate:
    """Feature 208's law, as the value a composed application carries.

    A facade with nothing behind it but this module — the same shape
    :class:`signal_agent.ProposalHistory` gives feature 206 and
    :class:`signal_agent.MechanismDiagnosis` gives feature 209 — so a caller
    holding the composed component can ask feature 208's question, *does this
    campaign's authoring prompt carry injected summarized guidance?*, without
    importing this submodule by name.

    **It carries nothing.**  No prompt, no campaign, no history, no store:
    the prompt is handed *in* on every call, because a component shared
    across a campaign that carried one would let two rounds' verdicts be
    read through each other — the property
    :class:`signal_agent.AntiConvergenceGate` states for its own subject,
    and for the same reason: the campaign is the unit of search and the
    prompt changes every round.

    Two methods, split by what the caller wants back.  :meth:`unguided` is
    the query a monitoring caller asks — *was this round's prompt clean?* —
    and answers with a bool, because a dashboard has no use for a sentence.
    :meth:`admit` is the same judgment carrying the parts and the refusal's
    reason, for a caller whose next line ships the prompt.  They cannot
    disagree: :meth:`unguided` is defined in terms of :meth:`admit`, and the
    second observation of the same prompt costs one pass over the parts.

    :meth:`admit` never raises.  :meth:`require` on the returned verdict is
    the one place :class:`~signal_agent.InjectedGuidanceError` exists.
    """

    __slots__ = ()

    def unguided(self, prompt: object) -> bool:
        """Whether the handed prompt carries no injected guidance.

        A thin read of :meth:`admit`, so the boolean a deployment's CI check
        branches on and the verdict a driver acts on cannot drift apart.
        """
        return self.admit(prompt).admitted

    def admit(self, prompt: object) -> GuidanceVerdict:
        """Judge one authoring prompt against §C3's no-guidance rule.

        Two checks, in this order, each with its own reason, because a
        caller reading the refusal is fixing one thing and the first
        declaration is the one its reader hit:

        1. **Is it screenable at all?**  A flat string, a bare ``None``, a
           number, a sequence entry that names itself nothing —
           :data:`NOT_PROMPT_PARTS_CODE`.  The caller's wiring is wrong and
           its call is what needs changing; an empty mapping or sequence
           passes, because a prompt with no parts injects nothing.
        2. **Does any part declare itself guidance?**  A part whose
           normalised name is one of :data:`_GUIDANCE_ROLES` (with truthy
           content), or whose content declares one of
           :data:`_DISTILLING_KEYS` naming the history, refuses as
           :data:`INJECTED_GUIDANCE_CODE`, naming every offending part and
           the declaration that matched.  Both declarations are one reason
           because the repair is one action: delete the part.

        The admitted parts are returned **unmodified**, in the caller's own
        order — the law judges a prompt and never authors one, and a gate
        that deleted a guidance section "for" the caller would be writing
        the campaign's prompt, which is the deployment's own decision to
        make and review.  The refusal tells the caller what to delete; it
        does not delete it.
        """
        sections = _sections_of(prompt)
        if sections is None:
            described = (
                "a flat prompt text (str)"
                if isinstance(prompt, str)
                else (
                    "bytes"
                    if isinstance(prompt, bytes)
                    else f"{type(prompt).__name__}"
                )
            )
            return _verdict(
                GuidanceReason.NOT_PROMPT_PARTS,
                f"{NOT_PROMPT_PARTS_CODE}: the authoring prompt was handed "
                f"over as {described}, which names no parts this law can "
                f"screen. Feature 208 refuses an *injection* — a part of the "
                f"prompt whose declared role or declared provenance is "
                f"summarized directional guidance — and a declaration is "
                f"something the prompt's structure carries: a mapping of "
                f"section name to content, an object whose attributes are "
                f"the sections, or a sequence of entries that each name "
                f"themselves. A flat prompt text cannot be screened "
                f"honestly: scanning prose for guidance words would refuse "
                f"the very content PRD §C3 and §14.1 require — every prior "
                f"proposal.md in full, feature 206's whole subject — the "
                f"first time a proposal carries a 'Summary' heading of its "
                f"own, and would admit the guidance that never used the "
                f"word. Hand the parts; a law that cannot read the "
                f"structure certifies nothing (feature 208).",
            )

        offenders: list[str] = []
        notes: list[str] = []
        admitted: list[tuple[str, object]] = []

        for name, content in sections:
            role = _guidance_role(name) if content else None
            provenance = _distilled_from_history(content) if content else None
            if role is not None or provenance is not None:
                offenders.append(name)
                declared = (
                    f"declares the guidance role {role!r}"
                    if role is not None
                    else f"declares itself distilled from the history ({provenance})"
                )
                notes.append(f"{name} {declared}")
            else:
                admitted.append((name, content))

        if offenders:
            listed = "; ".join(notes[:MAX_LISTED_INJECTIONS])
            if len(notes) > MAX_LISTED_INJECTIONS:
                listed = f"{listed}; and {len(notes) - MAX_LISTED_INJECTIONS} more"
            return _verdict(
                GuidanceReason.INJECTED_GUIDANCE,
                f"{INJECTED_GUIDANCE_CODE}: the authoring prompt carries "
                f"part(s) declared as summarized directional guidance — "
                f"{listed}. PRD §C3: 'Do not inject high-level directional "
                f"guidance from history into the prompt. The paper's Figure "
                f"5 found this consistently underperformed the unguided "
                f"version across both paradigms, because strong semantic "
                f"priors about future search directions over-constrain the "
                f"space and impede diverse exploration.' Keep history as an "
                f"interactive replay object, not as prose advice: every "
                f"prior proposal in full is feature 206's half of that "
                f"sentence, and deleting the distilled part is this "
                f"feature's — the agent reads the history, it is not told "
                f"what the history means (features 208, 206; PRD §C3, "
                f"§14.1:773).",
                offenders=_listed(offenders),
            )

        return _verdict(
            GuidanceReason.UNGUIDED,
            f"{UNGUIDED_CODE}: the authoring prompt's {len(admitted)} named "
            f"part(s) carry no summarized directional guidance — none "
            f"declares a guidance role and none declares itself distilled "
            f"from the history — so the history reaches the agent as the "
            f"interactive replay object PRD §C3 asks for rather than as "
            f"prose advice, and the search space is left as wide as the "
            f"campaign admitted it (features 208, 206; PRD §C3).",
            sections=admitted,
        )

    def require(self, prompt: object) -> tuple[tuple[str, object], ...]:
        """Refuse a prompt that carries injected guidance, else return its parts.

        The caller's verb: raises
        :class:`~signal_agent.errors.InjectedGuidanceError` — carrying the
        gate's own ``injected_guidance`` sentence — when the prompt carries a
        declared guidance part (or was not screenable as parts at all), and
        returns the admitted parts unchanged when it does not, so a caller
        can put it on the last line before it flattens and ships and have
        feature 208 enforced there rather than remembered.
        """
        return self.admit(prompt).require()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "PromptGuidanceGate()"


def prompt_guidance_gate() -> PromptGuidanceGate:
    """The law, for a caller that wants it directly.

    Not a component — the ``@register`` builder in this member's ``__init__``
    is, and this is the same call minus the composition.  The member's own
    tests and any operator script reach here.  A function rather than a
    module-level instance so an importer never shares state with another
    importer of the same file under the loader's second name — the
    discipline every other law function in this member follows.  The object
    is stateless, so the cost of a fresh one is a ``__slots__`` allocation
    and the benefit is that no caller can be surprised by another's.
    """
    return PromptGuidanceGate()
