"""Feature 213's law: a proposal's theme root must not open in dead territory.

app_spec.xml, "Hypothesis Authoring Agent", feature 213: *System rejects any
root opening in structurally dead territory such as sub-30-minute
liquidity-taking strategies.*  docs/alpha-engine-prd.md §9.4 is where the list
comes from and why it is *configured* rather than derived —

    Triangular arbitrage, cross-exchange latency arbitrage, anything with a
    holding period under ~30 minutes taking liquidity.  Do not let the agent
    open roots there.

— and it is the *neighbouring refusal* feature 212's law is deliberately not:
§9.4 is a finding about a root that is *already inside* the legal set, and a
document that folded the two together would make the second unfixable without
widening the first.  This module is that second refusal, and it depends on
:mod:`signal_agent._themes` for nothing — the two laws are independent
questions and a dependency would have made feature 213's verdict read through
feature 212's set.

The sentence decomposes into four claims, and each of them is a seam here
rather than a comment:

* **any root opening** — the subject is the *root* of a proposal's branch, the
  same territory feature 212 judges and feature 205's node table carries in
  its own column (``theme_root TEXT NOT NULL``).  What is judged is the
  territory the text is *about*, not the text the agent wrote; a conforming
  signal in a dead theme is a proposal this system does not want, and a member
  that folded the dead-territory check into adoption would have made one verb
  answer a question whose repair differs from feature 205's.

* **in structurally dead territory** — the finding is *viability*, not
  membership.  Feature 212's law is an *allowlist*: a root is admitted iff the
  human-admitted §9.3 set names it.  This law is a *denylist*: a root is
  refused iff the configured §9.4 list names it.  The two questions are
  genuinely different and the polarity is the whole feature — a root can be
  *legal* (the human admitted the space) and yet *dead* (the mechanism cannot
  pay for itself at retail scale however well the signal works), and a root
  that is legal-and-dead must read as a viability finding, never as "the human
  never admitted this space".  That is why this member carries two gates: the
  pipeline runs feature 212 (is the space admitted?) and then feature 213 (is
  the mechanism live?), and a proposal that fails either is refused, with the
  refusal that names the failure that actually happened.

* **such as sub-30-minute liquidity-taking strategies** — the list is the
  committed artifact (:data:`COMMITTED_DEAD_TERRITORY`) that ships beside this
  law, and :func:`compile_dead_territory` refuses any change to it that is not
  a marker plus well-formed slug/title entries.  PRD §9.4's three —
  triangular arbitrage, cross-exchange latency arbitrage, sub-30-minute
  liquidity-taking — are the initial denylist, transcribed as slugs; widening
  it (adding a mechanism a later finding proved dead) is PRD §9's
  highest-value human input in the same sense widening the legal set is, so it
  happens in review, in the document — never as a side effect of a run.

* **is rejected** — the answer is a value, for the same reason feature 212's
  :meth:`SignalThemeGate.admit` returns one and feature 205's
  :meth:`SignalContract.adopt` returns one: a campaign driver diagnoses why a
  branch's proposal was refused, feature 209 decides whether to retry, and a
  gate that raised would have taken that decision from the caller.
  :meth:`DeadTerritoryGate.require` is the bridge for the caller on its last
  line before it opens a node, and only there does
  :class:`~signal_agent.errors.DeadTerritoryError` appear.  The refusal opens
  with :data:`DEAD_TERRITORY_CODE` — the greppable word feature 213's own
  sentence names — and, like feature 212's, carries the offending spelling
  verbatim, the set it was screened against with each dead mechanism listed,
  and the section that made the list the human's decision.

**Why this is a second law and not a parameter of the first.**  Feature 212's
:meth:`SignalThemeGate.admit` already answers *is this root legal?* — and it
would be tempting to have it also answer *and is it dead?* on the same call.
It is deliberately not asked there, and the refusal vocabulary is the reason:
feature 212's refusal reports ``illegal_theme`` / ``not_a_theme``, whose
sentence says *"the human never admitted this space"*, and a dead-territory
refusal wearing that code would send an operator to widen a document the human
already widened.  The two authorities are genuinely different — feature 212
says which *territory* the campaign is willing to search, this law says which
*mechanism* cannot pay for itself inside that territory — so they are two
gates, and feature 212's law is left exactly as it was written: carrying
nothing about viability, restating nothing.

**Exact membership, by the same grammar as the allowlist — and the one place
they differ is the verdict.**  The denylist uses the same slug grammar
(:data:`_themes._SLUG_RE`, reached through :mod:`signal_agent._themes` rather
than restated) and the same exact-membership rule: ``sub-30-minute-liquidity-
taking-v2`` is a *different* mechanism from ``sub-30-minute-liquidity-taking``,
not a narrower spelling of it, and refusing it on a prefix would be widening
the denylist from inside a submission.  What differs from
:attr:`signal_agent.LegalThemes.covers` is only the polarity of the verdict:
the allowlist's ``covers`` returns *True when the root is admitted*; this
denylist's ``covers`` returns *True when the root is dead*.  The same word,
opposite meaning — and the opposite meaning is the whole reason the two laws
are two classes rather than one gate with a flag.

**Fail open, where feature 212 fails closed — the one asymmetry, and it is
load-bearing.**  Feature 212's builder, when the committed legal set cannot be
read, falls back to an *empty set* — which admits nothing, so every proposal
is refused.  That is the right failure for an allowlist: no legal set means no
space, and authoring into no space must refuse.  This law's builder, when the
committed denylist cannot be read, falls back to an *empty denylist* — which
refuses nothing, so every proposal is admitted.  That is the right failure for
a denylist: a down guardrail is less catastrophic than a system that refuses
*every* proposal, and the space still exists (feature 212 still judges it).
The compiler *refuses* an empty denylist — because a list that names no dead
mechanism is the absence of PRD §9.4's decision ("Do not let the agent open
roots there"), not a strict denylist — and the builder bypasses that refusal
on the drift path, hand-building the empty denylist the same way feature 212's
builder hand-builds the empty set.  The division is the same one
:func:`sandbox.build_sandbox_isolation` draws between what composition may
raise and what a caller that *requires* something must hear: the factory builds
every registered component on every ``create_app()`` call, so a builder that
raised on a drifted artifact would take composition down for every unrelated
feature in the workspace.

Stdlib only, and import-cheap — :mod:`enum`, :mod:`json`, :mod:`pathlib`,
:mod:`re` and the member's own errors, reaching :mod:`signal_agent._themes`
for the shared slug grammar — so the factory's scan, which imports this
package to fire its ``@register``, pays nothing for it.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

from . import _themes
from .errors import DeadTerritoryError, DeadTerritorySetError

__all__ = [
    "COMMITTED_DEAD_TERRITORY",
    "DEAD_TERRITORY_CODE",
    "DEAD_TERRITORY_COMPONENT_NAME",
    "DEAD_TERRITORY_POLICY_KIND",
    "LIVE_TERRITORY_CODE",
    "NOT_A_ROOT_CODE",
    "DeadTerritory",
    "DeadTerritoryGate",
    "DeadTerritoryReason",
    "DeadTerritoryVerdict",
    "committed_dead_territory",
    "compile_dead_territory",
    "dead_territory_gate",
    "load_dead_territory",
]

#: The marker a document declares itself with — the same discipline feature
#: 212's committed legal set (:data:`signal_agent.LEGAL_THEMES_POLICY_KIND`)
#: and feature 167's committed import allowlist take, so a stray JSON file
#: carrying a ``mechanisms`` key cannot be read as this configuration.
DEAD_TERRITORY_POLICY_KIND: Final[str] = "signal-agent-dead-territory"

#: The committed artifact, shipped beside the law that checks it, so a
#: checkout cannot hold one without the other.
COMMITTED_DEAD_TERRITORY: Final[Path] = Path(__file__).with_name(
    "dead_territory.json"
)

#: The greppable code feature 213's own refusal carries — its subject written
#: as a token, the feature's sentence naming the territory in so many words.
#: An operator grepping a campaign log for the proposals that opened *in dead
#: territory* finds them by the feature's own word.  This is the code one
#: verdict carries, not the code every refusal carries: the not-a-root case
#: below opens with its own, for the reason :attr:`DeadTerritoryReason.NOT_A_ROOT`
#: states, and the live case opens with :data:`LIVE_TERRITORY_CODE`.
DEAD_TERRITORY_CODE: Final[str] = "dead_territory"

#: The token every live root's sentence carries — the feature's own subject
#: written as a word, so an operator grepping a campaign log for the proposals
#: that *became* nodes finds them by it.  Its mirror is the refusal, which
#: opens with :data:`DEAD_TERRITORY_CODE` instead; an admission is not a code
#: an operator greps a campaign for, the same asymmetry
#: :data:`signal_agent.LEGAL_THEME_CODE` has against
#: :attr:`signal_agent.ThemeReason.LEGAL`.
LIVE_TERRITORY_CODE: Final[str] = "live_territory"

#: The code the not-a-root refusal opens with — its own, not
#: :data:`DEAD_TERRITORY_CODE`.  :attr:`DeadTerritoryReason.NOT_A_ROOT` is a
#: different verdict and says so in the first word, the discipline feature
#: 212's ``NOT_A_THEME_CODE`` and feature 205's ``NOT_SOURCE`` already follow:
#: a refusal that opened with another reason's code would be quoting feature
#: 213's headline while its own text says the root was never a mechanism to
#: judge.
NOT_A_ROOT_CODE: Final[str] = "not_a_root"

#: The component name this law registers under — beside feature 212's
#: ``signal-agent-themes`` and feature 205's ``signal-agent``: the factory's
#: registry is keyed by name and a later registration of the same name
#: *replaces* the earlier one, so the category's later features each take their
#: own seat on the member rather than overwriting an earlier law.  Prefixed
#: for the same reason :data:`signal_agent.THEMES_COMPONENT_NAME` is — an
#: unprefixed ``signal-agent`` a second time would replace feature 205's law —
#: and ``signal-agent-dead-territory`` sorts between ``signal-agent`` and
#: ``signal-agent-themes`` in the name-sorted ``app.order``, keeping the
#: member's three components contiguous in the category they belong to.
DEAD_TERRITORY_COMPONENT_NAME: Final[str] = "signal-agent-dead-territory"


def _require_mapping(value: Any, what: str) -> Mapping:
    """Return ``value`` as a mapping, refusing anything else.

    A compiler that guessed at the meaning of a stray list or string would be
    writing policy rather than reading it — the stance
    :func:`signal_agent.compile_legal_themes` states for its own document, and
    here it is what keeps "the configured dead-territory list" a fact about a
    file rather than about a reader's improvisation.
    """
    if not isinstance(value, Mapping):
        raise DeadTerritorySetError(
            f"{what} must be a mapping, got {type(value).__name__}: "
            f"{value!r}. A dead-territory list is a structured document, and a "
            f"compiler that guessed at the meaning of a stray list or string "
            f"would be writing policy rather than reading it — refused, fail "
            f"closed (feature 213)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value.strip():
        raise DeadTerritorySetError(
            f"{what} must be a non-empty string, got {value!r} "
            f"({type(value).__name__}). A field that does not say what it is "
            f"cannot be trusted to say which mechanism is dead, and a list "
            f"compiled from a blank one is a list with a hole in it (feature "
            f"213, refused fail closed)."
        )
    return value


class DeadTerritory:
    """A compiled dead-territory list: the mechanisms a root must not open in.

    What :func:`compile_dead_territory` returns is not the document — it is the
    document plus the guarantee that every slug in it is well-formed, listed
    once, and carries a title.  Holders (the gate, an operator script, a CI
    check that recompiles the committed artifact) cite that guarantee rather
    than re-derive it.

    **Membership is exact, and its polarity is inverted from the allowlist.**
    Unlike :class:`signal_agent.LegalThemes`, whose :attr:`~signal_agent.
    LegalThemes.covers` returns *True when the root is admitted*, this
    denylist's :meth:`covers` returns *True when the root is dead*.  The same
    word, opposite meaning: an entry names a mechanism that is refused, not one
    that is permitted.  ``sub-30-minute-liquidity-taking-v2`` is a different
    mechanism from ``sub-30-minute-liquidity-taking``, not a narrower spelling
    of it, and admitting it on a prefix would let a dead root through — the
    one thing PRD §9.4 says must not happen.
    """

    __slots__ = ("_mechanisms", "_slug_set", "_slugs", "_titles", "kind")

    def __init__(
        self, *, kind: str, mechanisms: tuple[tuple[str, str], ...]
    ) -> None:
        self.kind = kind
        self._mechanisms = mechanisms
        # Built once at compile rather than per probe, the same trade the
        # allowlist's ``_slug_set`` and the import allowlist's ``_term_set``
        # make: the gate asks ``covers`` once per proposal and the pipeline
        # offers thousands, so a denylist that re-derived itself per call would
        # be doing the compile's work on the refusal's clock.
        self._slugs = tuple(slug for slug, _ in mechanisms)
        self._titles = dict(mechanisms)
        self._slug_set = frozenset(self._slugs)

    def slugs(self) -> tuple[str, ...]:
        """Every dead mechanism, in document order."""
        return self._slugs

    def title(self, slug: object) -> str | None:
        """The human title of a dead mechanism, or ``None`` when it is not one.

        The read side a refusal and a dashboard both want: ``sub-30-minute-
        liquidity-taking`` is legible to the pipeline and opaque to the human
        deciding whether to widen the list, and the title is PRD §9.4's own
        wording rather than a second description someone wrote here.
        """
        return self._titles.get(slug) if isinstance(slug, str) else None

    def covers(self, slug: object) -> bool:
        """Whether the configured list names a mechanism as dead.

        Exact membership, and *inverted from the allowlist*: ``True`` means the
        root is dead and must be refused.  A value that is not a string names
        no mechanism and is dead by nothing — the conservative answer, and the
        same one the gate's live verdict gives it.
        """
        return isinstance(slug, str) and slug in self._slug_set

    def __contains__(self, slug: object) -> bool:
        # The duck-checkable spelling of ``covers`` — "is this mechanism dead?"
        # is the question a caller holding the list asks.
        return self.covers(slug)

    def __len__(self) -> int:
        return len(self._slugs)

    def __iter__(self) -> Iterator[str]:
        return iter(self._slugs)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"DeadTerritory(kind={self.kind!r}, "
            f"mechanisms={list(self._slugs)!r})"
        )


def compile_dead_territory(document: Any) -> DeadTerritory:
    """Compile a dead-territory list, refusing one that cannot be read.

    The seam the configuration turns on.  The document is read whole — marker,
    then entries — and each entry is held to the grammar before a
    :class:`DeadTerritory` is handed out, so no caller ever screens a proposal
    against a list holding a slug no ``theme_root`` value could equal.  A
    refusal propagates as an exception, the compile-time half of "System
    rejects" (feature 213): a drifted artifact is never applied.

    A document that lists no mechanisms is **refused** — the opposite reading
    from an empty denylist at *runtime*, which the builder's fail-open path
    below reaches deliberately.  The difference is *who* produced the empty
    list: the compiler refuses a committed artifact that names nothing, because
    a dead-territory list that names no dead mechanism is the absence of PRD
    §9.4's decision ("Do not let the agent open roots there"), not a strict
    denylist, and a proposal screened against it would be admitted into
    territory the human never cleared as live.  The builder's fail-open path
    reaches an empty list only when the committed artifact cannot be read — a
    deployment fault it reports, not a decision it makes — and it hand-builds
    that list rather than asking the compiler, so the compiler's refusal is
    never the thing a run silently obeys.
    """
    doc = _require_mapping(document, "a dead-territory list document")

    marker = doc.get("policy")
    if not isinstance(marker, str) or not marker.strip():
        raise DeadTerritorySetError(
            f"a dead-territory list's 'policy' must be a non-empty string, got "
            f"{marker!r} ({type(marker).__name__}). A document that does not "
            f"say what it is cannot be trusted to say which mechanisms are dead "
            f"(feature 213, refused fail closed)."
        )
    if marker != DEAD_TERRITORY_POLICY_KIND:
        raise DeadTerritorySetError(
            f"a dead-territory list must declare itself "
            f"{DEAD_TERRITORY_POLICY_KIND!r}, got {marker!r}. A stray JSON file "
            f"carrying a 'mechanisms' key is not this configuration — refused, "
            f"fail closed (feature 213)."
        )

    raw_mechanisms = doc.get("mechanisms")
    if not isinstance(raw_mechanisms, list):
        raise DeadTerritorySetError(
            f"a dead-territory list's 'mechanisms' must be a list of entries, "
            f"got {type(raw_mechanisms).__name__}: {raw_mechanisms!r}. The list "
            f"is the denylist's whole subject — the mechanisms the agent must "
            f"not open a root in — and a document that cannot enumerate them "
            f"cannot be compiled (feature 213)."
        )
    if not raw_mechanisms:
        raise DeadTerritorySetError(
            "a dead-territory list names no mechanisms. PRD §9.4 makes "
            "'Do not let the agent open roots there' the human's encoding of "
            "what is structurally dead at retail scale; a list that names "
            "nothing is not a strict denylist, it is the absence of that "
            "decision, and every proposal would be admitted with a message "
            "unable to say what would have been refused (feature 213)."
        )

    mechanisms: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_mechanisms):
        entry = _require_mapping(raw, f"dead-territory entry #{index + 1}")
        slug = _require_str(
            entry.get("slug"), f"dead-territory entry #{index + 1} 'slug'"
        )
        title = _require_str(
            entry.get("title"), f"dead-territory entry #{index + 1} 'title'"
        )
        if not _themes._SLUG_RE.match(slug):
            raise DeadTerritorySetError(
                f"a dead-territory list's slug #{index + 1} must be a lowercase "
                f"hyphenated slug, got {slug!r}. The slug is the machine "
                f"spelling the node table's theme_root column holds "
                f"(docs/nullius-tech-architecture.md §9.1), so an entry written "
                f"any other way names no mechanism a proposal could open in — "
                f"the list would carry a hole no submission could fill "
                f"(feature 213, refused fail closed)."
            )
        if slug in seen:
            raise DeadTerritorySetError(
                f"{slug!r} appears twice in the dead-territory list. One "
                f"mechanism listed twice is not a stricter denylist, it is one "
                f"mechanism described twice — and a document carrying two "
                f"titles for one slug is drift with extra steps. Refused "
                f"(feature 213)."
            )
        seen.add(slug)
        mechanisms.append((slug, title))

    return DeadTerritory(
        kind=DEAD_TERRITORY_POLICY_KIND, mechanisms=tuple(mechanisms)
    )


def load_dead_territory(path: Path = COMMITTED_DEAD_TERRITORY) -> DeadTerritory:
    """Read and compile a dead-territory list, refusing an unreadable file.

    Reads through the same law as any change to it would be: the committed
    artifact is not privileged, so a drift written to disk is refused exactly
    as a drift compiled in memory (feature 213).
    """
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise DeadTerritorySetError(
            f"could not read the dead-territory list at {path}: {exc}. PRD §9.4 "
            f"makes the dead mechanisms the human's encoding of what is "
            f"structurally dead at retail scale, and a list that cannot be read "
            f"is not one that admits everything gracefully — it is a deployment "
            f"whose denylist was never declared, and a caller that carried on "
            f"would be authoring into dead territory while believing it was "
            f"screened against §9.4's three (feature 213)."
        ) from exc
    except ValueError as exc:
        raise DeadTerritorySetError(
            f"the dead-territory list at {path} is not valid JSON: {exc}. "
            f"Refused rather than read partially: a list compiled from a "
            f"partially-parsed document is one whose file and whose gate "
            f"disagree (feature 213)."
        ) from exc
    return compile_dead_territory(document)


def committed_dead_territory() -> DeadTerritory:
    """The committed artifact, compiled through the same law as any change.

    The posture an operator gets without writing a stanza — and the document
    feature 213's own tests hold to PRD §9.4's three, so "a root must not open
    in these mechanisms" is a checked fact about a file in the repository
    rather than a claim in a runbook.
    """
    return load_dead_territory(COMMITTED_DEAD_TERRITORY)


class DeadTerritoryReason(enum.StrEnum):
    """Why a root was admitted or refused — the audit vocabulary.

    A :class:`enum.StrEnum` whose *value* is the token its own
    :attr:`DeadTerritoryVerdict.detail` opens with — so the reason is greppable
    in a campaign log without a lookup table, and a refusal never opens with
    another reason's headline.  The three are split by *repair*, not by which
    check happened to fail, the discipline feature 212's
    :class:`~signal_agent.ThemeReason` states for its own three: a caller
    handed a root that is not a root at all has a wiring bug, a caller handed a
    dead one has a proposal to refuse, and a caller handed a live one may open
    the node.
    """

    #: Admitted: the root is not a mechanism the configured list names as dead.
    #: Its detail opens with :data:`LIVE_TERRITORY_CODE` rather than with this
    #: value, the one place this enum and its codes differ — the same
    #: asymmetry feature 212's :attr:`~signal_agent.ThemeReason.LEGAL` has
    #: against :data:`~signal_agent.LEGAL_THEME_CODE`.  "live" is the reason a
    #: caller branches on; "live_territory" is the word a log line opens with,
    #: and an admission is not a code an operator greps a campaign for.
    LIVE = "live"

    #: Refused: the root is a mechanism the configured list names as dead.
    #: Feature 213's headline, and the reason the offending spelling is carried
    #: verbatim — the agent needs to see what it opened in, and the operator
    #: needs to see whether the list should have named it.  Spelled as the code
    #: itself, so branching on the value and grepping for it are the same
    #: string.
    DEAD_TERRITORY = DEAD_TERRITORY_CODE

    #: Refused: the value is not a theme root at all — not a string, or a
    #: string with nothing in it.  Its own reason rather than a spelling of the
    #: dead case because the repair is different in kind: an unset column or a
    #: missing argument is a bug in the *caller*, and an operator looking for a
    #: widened denylist would be looking in the wrong place.  Spelled as the
    #: code itself, for the same reason :attr:`DEAD_TERRITORY` is.
    NOT_A_ROOT = NOT_A_ROOT_CODE


class DeadTerritoryVerdict:
    """One root's verdict: live or dead, why, and in what words.

    ``admitted`` is the one field a caller must check, and it is *computed*
    from the reason rather than set by a constant — the same "computed, never
    assumed" stance :class:`~signal_agent.SourceAdoption`,
    :class:`~signal_agent.ThemeAdmission` and
    :class:`sandbox.ModuleDecision` take for their own answers.  The object
    carries everything the callers downstream need and nothing else:

    * :attr:`theme` — the root as it was handed in, ``None`` for every refusal,
      so a caller that has checked ``admitted`` reads the value rather than a
      sentinel;
    * :attr:`title` — the list's own §9.4 wording for that mechanism,
      ``None`` for every refusal.  Carried because it is the half of the answer
      a human reads;
    * :attr:`detail` — one operator-facing paragraph, the ``dead_territory``
      message feature 213's sentence names, and the sentence a campaign log
      records.

    **Its constructor refuses nothing.**  A caller holding a refusal is the
    caller that most needs one, and it cannot be told about an object it was
    never allowed to build — the discipline
    :class:`~signal_agent.ThemeAdmission` states for its own constructor.
    ``theme`` is taken as given (including ``None``), and the refusals live at
    :meth:`require`.
    """

    __slots__ = ("admitted", "detail", "reason", "theme", "title")

    def __init__(
        self,
        *,
        reason: DeadTerritoryReason,
        detail: str,
        theme: str | None = None,
        title: str | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail
        # A live verdict is admitted; a dead or not-a-root verdict is not.  The
        # polarity is the same shape as the allowlist's admission but the
        # meaning is inverted: here "admitted" means "the mechanism is live",
        # not "the space is legal".
        self.admitted = reason is DeadTerritoryReason.LIVE
        self.theme = theme if self.admitted else None
        self.title = title if self.admitted else None

    def require(self) -> str:
        """Return the live theme root, or raise :class:`DeadTerritoryError`.

        The bridge between the law's returned answer and the exception a caller
        wants on its last line before it opens a node: a live root returns the
        slug the node table's ``theme_root`` column will carry, so a caller can
        write ``theme = gate.admit(root).require()`` and have feature 213
        enforced there rather than remembered.  A refusal raises with this
        verdict's own sentence, so the retry prompt and the log line say the
        same thing.
        """
        if not self.admitted:
            raise DeadTerritoryError(self.detail)
        assert self.theme is not None  # admitted implies a theme, by construction
        return self.theme

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"DeadTerritoryVerdict(reason={self.reason.value!r}, "
            f"theme={self.theme!r})"
        )


class DeadTerritoryGate:
    """Feature 213's law, as the value a composed application carries.

    A facade over this module and the committed dead-territory list it
    compiled — the same shape :class:`signal_agent.SignalThemeGate` gives
    feature 212 and :class:`sandbox.SandboxImports` gives feature 167 — so a
    caller holding the composed component can ask the feature's question, *may
    this proposal open a root in this mechanism?*, without importing this
    submodule by name or re-reading the artifact.

    **It carries the compiled list and nothing else.**  No proposal, no node,
    no campaign, no store, and — load-bearing — no :class:`signal_agent.
    LegalThemes`: an admission is a fact about one string, and a component that
    carried the legal set would make feature 213's viability verdict read
    through feature 212's membership set, collapsing the two questions the
    feature exists to keep apart.

    **The delegation is deliberately thin** — each verb is one call into the
    law above it — because a second implementation of the membership rule or
    the refusal wording here would be a second thing to keep in sync with the
    law, which is the drift the member's one-provenance rule exists to prevent.
    What the class adds is discoverability (the factory's scan composes it), a
    single duck-checkable seam for the category's later features, and the
    *read side* — the dead mechanisms a root must not open in.
    """

    __slots__ = ("_territory",)

    def __init__(self, territory: DeadTerritory) -> None:
        self._territory = territory

    @property
    def territory(self) -> DeadTerritory:
        """The compiled dead-territory list this gate carries.

        Exposed so a caller — a CI check recompiling the committed artifact, an
        operator asking which mechanisms this deployment refuses — reads the
        list rather than re-deriving it.  Reading it refuses nothing: the list
        holds no capability, which is the point of the component being a facade
        rather than an execution path.
        """
        return self._territory

    def dead(self) -> tuple[str, ...]:
        """The dead mechanisms, in the document's own order — feature 213's list.

        The read side an agent's prompt and a dashboard both need: *which
        mechanisms must a root not open in?*  Deliberately a tuple of slugs
        rather than prose.  Naming the refused space is a fact about the
        configuration; a sentence about why each is dead is the prose that
        would over-constrain a search, and the titles are the read side for
        that.
        """
        return self._territory.slugs()

    def covers(self, theme: object) -> bool:
        """Whether the configured list names one theme root as dead.

        The read side of the law: *is this mechanism dead?* is a question a
        deployment should be able to answer without submitting a proposal to
        find out, and answering it from the compiled artifact is what makes the
        denylist a fact about the configuration rather than a claim in a
        runbook.  ``True`` for a root the list names is the answer the gate's
        refusal gives it too — and it is *inverted from*
        :meth:`signal_agent.SignalThemeGate.covers`, which returns True when a
        root is legal: the same word, opposite verdict, the whole reason the
        two laws are two gates.
        """
        return self._territory.covers(theme)

    def title(self, theme: object) -> str | None:
        """The human title of a dead mechanism, or ``None`` when it is not one."""
        return self._territory.title(theme)

    def admit(self, theme: object) -> DeadTerritoryVerdict:
        """Judge one proposal's theme root: admit it only if the mechanism is live.

        The feature's verb.  In order, and each step's own reason:

        1. **it is a theme root** — a non-string, or a string with nothing in
           it, is refused with :attr:`DeadTerritoryReason.NOT_A_ROOT`.  Its own
           reason because the repair is the caller's: an unset ``theme_root`` is
           a bug in the code that built the proposal, not a submission to
           reject;
        2. **the list does not name it as dead** — :meth:`DeadTerritory.covers`
           runs, and a root it names is refused with
           :attr:`DeadTerritoryReason.DEAD_TERRITORY`, carrying the offending
           spelling verbatim and the whole dead list so the agent can re-open
           inside a live mechanism and the operator can see whether it *should*
           have been named.

        The live root is returned **unmodified**.  Admission is a judgement
        about a spelling, never an edit of it: ``theme_root`` is the value
        §9.1's node row persists, and a gate that lowercased or stripped a root
        "into conformance" would be authoring the proposal rather than checking
        it.
        """
        if not isinstance(theme, str) or not theme.strip():
            described = (
                type(theme).__name__
                if not isinstance(theme, str)
                else f"a string of {len(theme)} character(s) containing no theme"
            )
            return DeadTerritoryVerdict(
                reason=DeadTerritoryReason.NOT_A_ROOT,
                detail=(
                    f"{NOT_A_ROOT_CODE}: a proposal's theme root must be a "
                    f"non-empty string, got {described}. PRD §9.4 refuses roots "
                    f"in structurally dead territory, and a proposal that does "
                    f"not carry a theme root cannot be screened against that "
                    f"list at all — this is a bug in the call that built the "
                    f"proposal rather than a mechanism to judge, and no list "
                    f"could name it (feature 213)."
                ),
            )

        if self._territory.covers(theme):
            slugs = self._territory.slugs()
            # An empty set is a *reachable* state here even though the compiler
            # refuses one: the member's builder falls back to it when the
            # committed artifact cannot be read, so a refusal against it must
            # still read as a sentence rather than trailing off into an empty
            # list.  The count and the list are spelled together for that
            # reason.
            listed = (
                f"{len(slugs)} mechanisms: {', '.join(slugs)}"
                if slugs
                else "which names no mechanisms at all"
            )
            return DeadTerritoryVerdict(
                reason=DeadTerritoryReason.DEAD_TERRITORY,
                detail=(
                    f"{DEAD_TERRITORY_CODE}: the proposal opens a root in "
                    f"{theme!r}, which is a mechanism PRD §9.4 names as "
                    f"structurally dead at retail scale (the configured "
                    f"dead-territory list, {self._territory.kind}, {listed}). "
                    f"'Do not let the agent open roots there': a root the list "
                    f"names is a mechanism that cannot pay for itself however "
                    f"well the signal works, and authoring there spends agent "
                    f"calls, evaluation budget and a node's identity on "
                    f"territory that is dead before it is tried. Membership is "
                    f"exact: a near-miss spelling is a different mechanism, not "
                    f"a narrower one. Refused before the node is opened "
                    f"(features 213, 212; §9.4)."
                ),
            )

        return DeadTerritoryVerdict(
            reason=DeadTerritoryReason.LIVE,
            theme=theme,
            title=None,
            detail=(
                f"{LIVE_TERRITORY_CODE}: the proposal's root {theme!r} is not a "
                f"mechanism the configured dead-territory list names as dead, "
                f"so the branch is inside the live space PRD §9.4 leaves open "
                f"and the node may be opened with this theme_root (feature 213)."
            ),
        )

    def require(self, theme: object) -> str:
        """Refuse unless the theme root is a live one.

        The caller's verb: raises :class:`~signal_agent.errors.DeadTerritoryError`
        — carrying the gate's own ``dead_territory`` sentence — when the root
        is dead, and returns the slug when it is live, so a caller can put it
        on the last line before it opens a node and have feature 213 enforced
        there rather than remembered.
        """
        return self.admit(theme).require()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"DeadTerritoryGate(territory={len(self._territory)})"


def dead_territory_gate() -> DeadTerritoryGate:
    """The law, for a caller that wants it directly.

    Not a component — the ``@register`` builder in this member's ``__init__``
    is, and this is the same call minus the composition.  The member's own
    tests and any operator script reach here.
    """
    return DeadTerritoryGate(committed_dead_territory())
