"""Feature 212's law: a proposal's theme root must be inside the legal set.

app_spec.xml, "Hypothesis Authoring Agent", feature 212: *System rejects a
proposal whose theme root falls outside the configured legal set, which
returns an illegal_theme error message.*  docs/alpha-engine-prd.md §9 is where
the set comes from and why it is *configured* rather than derived —

    Dream-RSI improves search efficiency *within a space*.  It cannot create
    edge in a space that has none.  Choosing the space is the highest-value
    human input in the system, and it should be encoded as the set of legal
    ``theme_root`` values.

— and §9.3 lists the initial six.  The sentence decomposes into four claims,
and each of them is a seam here rather than a comment:

* **a proposal whose theme root** — the subject is the *root* of a proposal's
  branch, not its source.  Feature 205's law judges the text an agent wrote;
  this law judges the territory the text is *about*, which §9.1's node table
  carries in its own column (``theme_root TEXT NOT NULL``) precisely because
  the two are different facts about one node.  A conforming signal in an
  inadmissible theme is a proposal this system does not want, and a member
  that folded the theme check into adoption would have made one verb answer
  two questions whose repairs differ.

* **falls outside the configured legal set** — *configured* is the load-bearing
  word.  The set is not computed, not inferred from the campaign history and
  not fitted: it is the committed artifact
  (:data:`COMMITTED_LEGAL_THEMES`) that ships beside this law, and
  :func:`compile_legal_themes` refuses any change to it that is not a marker
  plus well-formed slug/title entries.  Widening the hypothesis space is
  PRD §9's *"highest-value human input"*, so it happens in review, in the
  document — never as a side effect of a run.

* **is rejected** — the answer is a value, for the same reason
  :meth:`SignalContract.adopt` returns one: a campaign driver diagnoses why a
  branch's proposal was refused, feature 209 decides whether to retry, and a
  gate that raised would have taken that decision from the caller.
  :meth:`ThemeAdmission.require` is the bridge for the caller on its last line
  before it opens a node, and only there does
  :class:`~signal_agent.errors.IllegalThemeError` appear.

* **which returns an illegal_theme error message** — the greppable code the
  feature's own sentence names, opening the refusal the feature is about: a
  root the set does not name.  It is one verdict's code, not the prefix of
  every refusal — a value that was never a theme root to judge opens with
  :data:`NOT_A_THEME_CODE`, so a log line never quotes feature 212's headline
  for a case whose own text says no set could have admitted it.  The message
  names the offending spelling *verbatim* (``repr``, so a padded or cased
  near-miss is visible), the set it was screened against with each legal slug
  listed, and the section that made the set the human's decision — so an
  operator reading a campaign log knows which of the two happened: the agent
  opened in territory nobody admitted, or the document was widened and the run
  predates the widen.

**Why this is a second law and not a parameter of the first.**  Feature 205's
:meth:`SignalContract.adopt` already takes an optional ``screen`` — the box's
own admission test, duck-read for ``admitted`` and ``detail`` — and a
:class:`ThemeAdmission` would satisfy that shape by accident.  It is
deliberately not passed there, and the refusal vocabulary is the reason: the
box's screen reports ``REFUSED_BY_BOX``, whose sentence says *"the sandbox
refused it"*, and a theme refusal wearing that reason would send an operator to
look for an import-allowlist violation in a proposal whose imports are fine.
The two authorities are genuinely different — the contract says what the box
will *invoke*, the box says what it will *admit*, and this law says which
*territory* the campaign is willing to search — so they are three seams, and
the composed law in :mod:`signal_agent._authoring` is left exactly as feature
205 wrote it: carrying nothing, restating nothing.

**Exact membership, not prefix coverage.**  The sandbox's import allowlist
admits a term and everything *under* it, because a dotted module really does
have submodules and importing ``numpy.linalg`` executes ``numpy``.  A theme
root is not that shape: it is a leaf label the human chose, with no children a
narrower spelling could name.  So ``order-flow-imbalance-v2`` is *not* admitted
by the ``order-flow-imbalance`` entry — it is a different theme that nobody
admitted, and admitting it on a prefix would be widening the hypothesis space
from inside a submission, which is the one thing PRD §9 says must not happen.
That difference from :meth:`sandbox.imports.ImportsAllowlist.covers` is
deliberate and is the reason this member does not ride the sandbox's ceiling
type.

**The neighbouring refusal this is not.**  §9.4 lists what is *structurally
dead at retail scale* — triangular arbitrage, anything with a holding period
under ~30 minutes taking liquidity — and feature 213 makes refusing those a
feature of its own, depending on this one.  The two questions are different:
§9.4 is a finding about a root that is *already inside* the legal set, and a
document that folded the two together would make the second unfixable without
widening the first.  So the set here names §9.3's six and nothing else, and no
entry of it carries a viability judgement.

Stdlib only, and import-cheap — :mod:`enum`, :mod:`json`, :mod:`pathlib`,
:mod:`re` and the member's own errors — so the factory's scan, which imports
this package to fire its ``@register``, pays nothing for it.
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

from .errors import IllegalThemeError, ThemeSetError

__all__ = [
    "COMMITTED_LEGAL_THEMES",
    "ILLEGAL_THEME_CODE",
    "LEGAL_THEMES_POLICY_KIND",
    "LEGAL_THEME_CODE",
    "NOT_A_THEME_CODE",
    "THEMES_COMPONENT_NAME",
    "LegalThemes",
    "SignalThemeGate",
    "ThemeAdmission",
    "ThemeReason",
    "committed_legal_themes",
    "compile_legal_themes",
    "load_legal_themes",
    "signal_theme_gate",
]

#: The marker a document declares itself with — the same discipline feature
#: 167's committed import allowlist and feature 157's committed isolation
#: policy take, so a stray JSON file carrying a ``themes`` key cannot be read
#: as this configuration.
LEGAL_THEMES_POLICY_KIND: Final[str] = "signal-agent-legal-themes"

#: The committed artifact, shipped beside the law that checks it, so a
#: checkout cannot hold one without the other.
COMMITTED_LEGAL_THEMES: Final[Path] = Path(__file__).with_name(
    "legal_themes.json"
)

#: The greppable code feature 212's own refusal carries — its subject written
#: as a token, the feature's sentence naming it in so many words ("which
#: returns an illegal_theme error message").  An operator grepping a campaign
#: log for the proposals that opened *outside* the admitted space finds them by
#: the feature's own word.  This is the code one verdict carries, not the code
#: every refusal carries: the not-a-theme case below opens with its own, for
#: the reason :attr:`ThemeReason.NOT_A_THEME` states.
ILLEGAL_THEME_CODE: Final[str] = "illegal_theme"

#: The token every admitted root's sentence carries — the feature's own subject
#: written as a word, so an operator grepping a campaign log for the proposals
#: that *became* nodes finds them by it.  Its mirror is the refusal, which
#: opens with :data:`ILLEGAL_THEME_CODE` instead; a refusal is a different
#: answer and should not read like an admission with a footnote.  Spelled once
#: here for the same reason :data:`~signal_agent.CONFORMS_CODE` is — the two
#: polarities of one verdict should not be two spellings a caller matches by
#: eye against a string it wrote down itself.
LEGAL_THEME_CODE: Final[str] = "legal_theme"

#: The code the not-a-theme refusal opens with — its own, not
#: :data:`ILLEGAL_THEME_CODE`.  :attr:`ThemeReason.NOT_A_THEME` is a different
#: verdict and says so in the first word, the discipline feature 205's
#: ``NOT_SOURCE`` and ``NOT_CONFORMING`` sentences already follow: a refusal
#: that opened with another reason's code would be quoting feature 212's
#: headline while its own text says the root was never a theme to judge.
NOT_A_THEME_CODE: Final[str] = "not_a_theme"

#: The component name this law registers under — beside feature 205's
#: ``signal-agent``, not instead of it: the factory's registry is keyed by name
#: and a later registration of the same name *replaces* the earlier one, so the
#: category's later features each take their own seat on the member (the
#: bootstrap member's four, the sandbox member's twelve) rather than
#: overwriting the authoring law's.
THEMES_COMPONENT_NAME: Final[str] = "signal-agent-themes"

#: A well-formed theme slug: lowercase alphanumeric runs joined by single
#: hyphens, anchored at both ends.  The grammar is the document's, not the
#: submission's — a slug that is not one names no theme the human could have
#: chosen, and a set compiled with one would be a set with an entry no
#: ``theme_root`` value could ever equal.  Stricter than the node column
#: (TEXT NOT NULL, which accepts anything) on purpose: the column is where a
#: value lands, this is what the set is allowed to say.
_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _require_mapping(value: Any, what: str) -> Mapping:
    """Return ``value`` as a mapping, refusing anything else.

    A compiler that guessed at the meaning of a stray list or string would be
    writing policy rather than reading it — the stance
    :func:`sandbox.imports.compile_imports_allowlist` states for its own
    document, and here it is what keeps "the configured legal set" a fact about
    a file rather than about a reader's improvisation.
    """
    if not isinstance(value, Mapping):
        raise ThemeSetError(
            f"{what} must be a mapping, got {type(value).__name__}: "
            f"{value!r}. The document is structured, and a compiler that "
            f"guessed at the meaning of a stray list or string would be "
            f"writing policy rather than reading it — refused, fail closed "
            f"(feature 212)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value.strip():
        raise ThemeSetError(
            f"{what} must be a non-empty string, got {value!r} "
            f"({type(value).__name__}). A field that does not say what it is "
            f"cannot be trusted to say what the agent may search, and a set "
            f"compiled from a blank one is a set with a hole in it "
            f"(feature 212, refused fail closed)."
        )
    return value


class LegalThemes:
    """A compiled legal theme set: the space a proposal's root is judged in.

    What :func:`compile_legal_themes` returns is not the document — it is the
    document plus the guarantee that every slug in it is well-formed, listed
    once, and carries a title.  Holders (the gate, an operator script, a CI
    check that recompiles the committed artifact) cite that guarantee rather
    than re-derive it, which is why the gate's refusal can say "outside the
    configured legal set" and mean a set that was validated.

    **Membership is exact.**  Unlike
    :class:`sandbox.imports.ImportsAllowlist`, whose coverage is by prefix down
    a dotted module path, a theme root is a leaf label: an entry admits the
    slug itself and nothing else.  ``order-flow-imbalance-v2`` is a different
    theme from ``order-flow-imbalance``, not a narrower spelling of it, and
    admitting it on a prefix would let a submission widen the hypothesis space
    PRD §9 reserves to the human.
    """

    __slots__ = ("_slug_set", "_slugs", "_themes", "_titles", "kind")

    def __init__(
        self, *, kind: str, themes: tuple[tuple[str, str], ...]
    ) -> None:
        self.kind = kind
        self._themes = themes
        # Built once at compile rather than per probe: the gate asks
        # ``covers`` once per proposal and the pipeline offers thousands, so a
        # ceiling that re-derived itself per call would be doing the compile's
        # work on the refusal's clock — the same trade the import allowlist's
        # ``_term_set`` makes.
        self._slugs = tuple(slug for slug, _ in themes)
        self._titles = dict(themes)
        self._slug_set = frozenset(self._slugs)

    def slugs(self) -> tuple[str, ...]:
        """Every legal slug, in document order.

        Document order rather than sorted, deliberately: the artifact is
        reviewed as it is written (§9.3's own order), and a refusal that
        listed the set alphabetically would read differently from the file an
        operator opens to widen it.
        """
        return self._slugs

    def title(self, slug: object) -> str | None:
        """The human title of a legal slug, or ``None`` when it is not one.

        The read side a refusal and a dashboard both want: a log line saying
        ``order-flow-imbalance`` is legible to the pipeline and opaque to the
        human deciding whether to widen the set, and the title is the PRD's own
        §9.3 wording rather than a second description someone wrote here.
        """
        return self._titles.get(slug) if isinstance(slug, str) else None

    def covers(self, slug: object) -> bool:
        """Whether the configured set admits a theme root.

        Exact membership.  A value that is not a string names no theme and is
        admitted by nothing — the conservative answer, and the same one the
        gate's refusal gives it.
        """
        return isinstance(slug, str) and slug in self._slug_set

    def __contains__(self, slug: object) -> bool:
        # The duck-checkable spelling of ``covers`` — "is this theme legal?"
        # is the question a caller holding the set asks.
        return self.covers(slug)

    def __len__(self) -> int:
        return len(self._slugs)

    def __iter__(self) -> Iterator[str]:
        return iter(self._slugs)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"LegalThemes(kind={self.kind!r}, themes={list(self._slugs)!r})"


def compile_legal_themes(document: Any) -> LegalThemes:
    """Compile a legal theme set, refusing one that cannot be read.

    The seam the configuration turns on.  The document is read whole — marker,
    then entries — and each entry is held to the grammar before a
    :class:`LegalThemes` is handed out, so no caller ever screens a proposal
    against a set holding a slug no ``theme_root`` value could equal.  A
    refusal propagates as an exception, the compile-time half of "System
    rejects" (feature 212): a drifted artifact is never applied.

    A document that lists no themes is **refused**, and that is the opposite
    reading from :func:`sandbox.imports.compile_imports_allowlist`, which
    compiles an empty ceiling happily.  The difference is what each set *is*:
    a ceiling that admits nothing is the strongest version of itself, while a
    legal theme set that names nothing is not a strict hypothesis space — it is
    a deployment where PRD §9's highest-value human input was never made, and
    every proposal would be refused with a message that could not say what
    would have been admitted.
    """
    doc = _require_mapping(document, "a legal theme set document")

    marker = doc.get("policy")
    if not isinstance(marker, str) or not marker.strip():
        raise ThemeSetError(
            f"a legal theme set's 'policy' must be a non-empty string, got "
            f"{marker!r} ({type(marker).__name__}). A document that does not "
            f"say what it is cannot be trusted to say which territory the "
            f"agent may search (feature 212, refused fail closed)."
        )
    if marker != LEGAL_THEMES_POLICY_KIND:
        raise ThemeSetError(
            f"a legal theme set must declare itself "
            f"{LEGAL_THEMES_POLICY_KIND!r}, got {marker!r}. A stray JSON file "
            f"carrying a 'themes' key is not this configuration — refused, "
            f"fail closed (feature 212)."
        )

    raw_themes = doc.get("themes")
    if not isinstance(raw_themes, list):
        raise ThemeSetError(
            f"a legal theme set's 'themes' must be a list of entries, got "
            f"{type(raw_themes).__name__}: {raw_themes!r}. The list is the "
            f"set's whole subject — the territory the agent may open a root in "
            f"— and a document that cannot enumerate it cannot be compiled "
            f"(feature 212)."
        )
    if not raw_themes:
        raise ThemeSetError(
            "a legal theme set names no themes. PRD §9 makes choosing the "
            "hypothesis space the human's highest-value input; a set that "
            "names nothing is not a strict space, it is the absence of that "
            "decision, and every proposal would be refused with a message "
            "unable to say what would have been admitted (feature 212)."
        )

    themes: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_themes):
        entry = _require_mapping(raw, f"legal theme entry #{index + 1}")
        slug = _require_str(
            entry.get("slug"), f"legal theme entry #{index + 1} 'slug'"
        )
        title = _require_str(
            entry.get("title"), f"legal theme entry #{index + 1} 'title'"
        )
        if not _SLUG_RE.match(slug):
            raise ThemeSetError(
                f"a legal theme set's slug #{index + 1} must be a lowercase "
                f"hyphenated slug, got {slug!r}. The slug is the machine "
                f"spelling the node table's theme_root column holds "
                f"(docs/nullius-tech-architecture.md §9.1), so an entry "
                f"written any other way names no theme a proposal could open "
                f"in — the set would carry a hole no submission could fill "
                f"(feature 212, refused fail closed)."
            )
        if slug in seen:
            raise ThemeSetError(
                f"{slug!r} appears twice in the legal theme set. One theme "
                f"listed twice is not a wider space, it is one theme described "
                f"twice — and a document carrying two titles for one slug is "
                f"drift with extra steps. Refused (feature 212)."
            )
        seen.add(slug)
        themes.append((slug, title))

    return LegalThemes(kind=LEGAL_THEMES_POLICY_KIND, themes=tuple(themes))


def load_legal_themes(path: Path = COMMITTED_LEGAL_THEMES) -> LegalThemes:
    """Read and compile a legal theme set, refusing an unreadable file.

    Reads through the same law as any change to it would be: the committed
    artifact is not privileged, so a drift written to disk is refused exactly
    as a drift compiled in memory (feature 212).
    """
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise ThemeSetError(
            f"could not read the legal theme set at {path}: {exc}. PRD §9 "
            f"makes the legal theme_root values the human's encoding of the "
            f"hypothesis space, and a set that cannot be read is not one that "
            f"refuses everything gracefully — it is a deployment whose space "
            f"was never declared, and a caller that carried on would be "
            f"authoring into nothing while believing it was authoring into "
            f"§9.3's six (feature 212)."
        ) from exc
    except ValueError as exc:
        raise ThemeSetError(
            f"the legal theme set at {path} is not valid JSON: {exc}. Refused "
            f"rather than read partially: a set compiled from a "
            f"partially-parsed document is one whose file and whose gate "
            f"disagree (feature 212)."
        ) from exc
    return compile_legal_themes(document)


def committed_legal_themes() -> LegalThemes:
    """The committed artifact, compiled through the same law as any change.

    The posture an operator gets without writing a stanza — and the document
    feature 212's own tests hold to PRD §9.3's six, so "a proposal may open a
    root in these territories" is a checked fact about a file in the repository
    rather than a claim in a runbook.
    """
    return load_legal_themes(COMMITTED_LEGAL_THEMES)


class ThemeReason(enum.StrEnum):
    """Why a theme root was admitted or refused — the audit vocabulary.

    A :class:`enum.StrEnum` whose *value* is the token its own
    :attr:`ThemeAdmission.detail` opens with — so the reason is greppable in a
    campaign log without a lookup table, and a refusal never opens with another
    reason's headline.  The three are split by *repair*, not by which check
    happened to fail, the discipline feature 205's
    :class:`~signal_agent.AdoptionReason` states for its own four: a caller
    handed a theme that is not a theme at all has a wiring bug, and a caller
    handed an illegal one has a proposal to refuse.
    """

    #: Admitted: the root is a slug the configured set names.  Its detail opens
    #: with :data:`LEGAL_THEME_CODE` rather than with this value, which is the
    #: one place this enum and its codes differ — the same asymmetry feature
    #: 205's :class:`~signal_agent.AdoptionReason.CONFORMS` has against
    #: :data:`~signal_agent.CONFORMS_CODE`.  "legal" is the reason a caller
    #: branches on; "legal_theme" is the word a log line opens with, and an
    #: admission is not a code an operator greps a campaign for.
    LEGAL = "legal"

    #: Refused: the root is a well-formed value the configured set does not
    #: name.  Feature 212's headline, and the reason the offending spelling is
    #: carried verbatim — the agent needs to see what it opened in, and the
    #: operator needs to see whether the set should have named it.  Spelled as
    #: the code itself, so branching on the value and grepping for it are the
    #: same string.
    ILLEGAL_THEME = ILLEGAL_THEME_CODE

    #: Refused: the value is not a theme root at all — not a string, or a
    #: string with nothing in it.  Its own reason rather than a spelling of
    #: the illegal case because the repair is different in kind: an unset
    #: column or a missing argument is a bug in the *caller*, and an operator
    #: looking for a widened set would be looking in the wrong place.  Spelled
    #: as the code itself, for the same reason
    #: :attr:`ILLEGAL_THEME` is — and so a caller that branches on this value
    #: has already branched on the token the refusal's first word carries.
    NOT_A_THEME = NOT_A_THEME_CODE


class ThemeAdmission:
    """One theme root's verdict: admitted or not, why, and in what words.

    ``admitted`` is the one field a caller must check, and it is *computed*
    from the reason rather than set by a constant — the same "computed, never
    assumed" stance :class:`~signal_agent.SourceAdoption` and
    :class:`sandbox.ModuleDecision` take for their own answers.  The object
    carries everything the callers downstream need and nothing else:

    * :attr:`theme` — the root as it was handed in, ``None`` for every refusal,
      so a caller that has checked ``admitted`` reads the value rather than a
      sentinel;
    * :attr:`title` — the set's own §9.3 wording for that root, ``None`` for
      every refusal.  Carried because it is the half of the answer a human
      reads: ``order-flow-imbalance`` is legible to the pipeline and opaque to
      the operator, and a caller that looked the title up later would be
      asking a set that may since have been widened;
    * :attr:`detail` — one operator-facing paragraph, the ``illegal_theme``
      message feature 212's sentence names, and the sentence a campaign log
      records.

    **Its constructor refuses nothing.**  A caller holding a refusal is the
    caller that most needs one, and it cannot be told about an object it was
    never allowed to build — the discipline
    :class:`~signal_agent.SourceAdoption` states for its own constructor.
    ``theme`` is taken as given (including ``None``), and the refusals live at
    :meth:`require`.
    """

    __slots__ = ("admitted", "detail", "reason", "theme", "title")

    def __init__(
        self,
        *,
        reason: ThemeReason,
        detail: str,
        theme: str | None = None,
        title: str | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.admitted = reason is ThemeReason.LEGAL
        self.theme = theme if self.admitted else None
        self.title = title if self.admitted else None

    def require(self) -> str:
        """Return the admitted theme root, or raise :class:`IllegalThemeError`.

        The bridge between the law's returned answer and the exception a caller
        wants on its last line before it opens a node: an admitted root returns
        the slug the node table's ``theme_root`` column will carry, so a caller
        can write ``theme = gate.admit(root).require()`` and have feature 212
        enforced there rather than remembered.  A refusal raises with this
        admission's own sentence, so the retry prompt and the log line say the
        same thing.
        """
        if not self.admitted:
            raise IllegalThemeError(self.detail)
        assert self.theme is not None  # admitted implies a theme, by construction
        return self.theme

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ThemeAdmission(reason={self.reason.value!r}, "
            f"theme={self.theme!r})"
        )


class SignalThemeGate:
    """Feature 212's law, as the value a composed application carries.

    A facade over this module and the committed legal set it compiled — the
    same shape :class:`sandbox.SandboxImports` gives feature 167 and
    :class:`~signal_agent.SignalContract` gives feature 205 — so a caller
    holding the composed component can ask the feature's question, *may this
    proposal open a root here?*, without importing this submodule by name or
    re-reading the artifact.

    **It carries the compiled set and nothing else.**  No proposal, no node, no
    campaign, no store: an admission is a fact about one string, and a
    component shared across a campaign that carried a proposal would let two
    branches' verdicts be read through each other — the property
    :class:`~signal_agent.SignalContract` states for its own holdings.

    **The delegation is deliberately thin** — each verb is one call into the
    law above it — because a second implementation of the membership rule or
    the refusal wording here would be a second thing to keep in sync with the
    law, which is the drift the member's one-provenance rule exists to prevent.
    What the class adds is discoverability (the factory's scan composes it), a
    single duck-checkable seam for the category's remaining features (213
    depends on this one), and the *read side* — the legal slugs an agent is
    asked to choose among, which is the shape that cannot accidentally become
    guidance.
    """

    __slots__ = ("_themes",)

    def __init__(self, themes: LegalThemes) -> None:
        self._themes = themes

    @property
    def themes(self) -> LegalThemes:
        """The compiled legal set this gate carries.

        Exposed so a caller — a CI check recompiling the committed artifact, an
        operator asking which territories this deployment searches — reads the
        set rather than re-deriving it.  Reading it widens nothing: the set
        holds no capability, which is the point of the component being a facade
        rather than an execution path.
        """
        return self._themes

    def legal(self) -> tuple[str, ...]:
        """The legal slugs, in the document's own order — feature 212's set.

        The read side an agent's prompt and a dashboard both need: *which
        territories may a root open in?*  Deliberately a tuple of slugs rather
        than prose.  PRD C3 and §14.1 forbid injecting directional guidance
        distilled from history into the authoring prompt, and feature 208 makes
        refusing it a feature; naming the admitted space is a fact about the
        configuration, while a sentence about which of them has been paying off
        is the prose prior that over-constrains a search.
        """
        return self._themes.slugs()

    def covers(self, theme: object) -> bool:
        """Whether the configured set admits one theme root.

        The read side of the law: *is this territory legal?* is a question a
        deployment should be able to answer without submitting a proposal to
        find out, and answering it from the compiled artifact is what makes the
        space a fact about the configuration rather than a claim in a runbook.
        ``False`` for a root the set does not name is the answer the gate's
        refusal gives it too.
        """
        return self._themes.covers(theme)

    def title(self, theme: object) -> str | None:
        """The human title of a legal slug, or ``None`` when it is not one."""
        return self._themes.title(theme)

    def admit(self, theme: object) -> ThemeAdmission:
        """Judge one proposal's theme root: admit it only if the set names it.

        The feature's verb.  In order, and each step's own reason:

        1. **it is a theme root** — a non-string, or a string with nothing in
           it, is refused with :attr:`ThemeReason.NOT_A_THEME`.  Its own reason
           because the repair is the caller's: an unset ``theme_root`` is a bug
           in the code that built the proposal, not a submission to reject;
        2. **the set names it** — :meth:`LegalThemes.covers` runs, and a root
           it does not admit is refused with
           :attr:`ThemeReason.ILLEGAL_THEME`, carrying the offending spelling
           verbatim and the whole legal set so the agent can re-open inside it
           and the operator can see whether it *should* have been named.

        The admitted root is returned **unmodified**.  Admission is a judgement
        about a spelling, never an edit of it: ``theme_root`` is the value
        §9.1's node row persists, and a gate that lowercased or stripped a root
        "into conformance" would be authoring the proposal rather than checking
        it, and would let a row's stored theme disagree with the one the set
        was consulted about.
        """
        if not isinstance(theme, str) or not theme.strip():
            described = (
                type(theme).__name__
                if not isinstance(theme, str)
                else f"a string of {len(theme)} character(s) containing no theme"
            )
            return ThemeAdmission(
                reason=ThemeReason.NOT_A_THEME,
                detail=(
                    f"{NOT_A_THEME_CODE}: a proposal's theme root must be a "
                    f"non-empty string, got {described}. PRD §9 encodes the "
                    f"hypothesis space as the set of legal theme_root values, "
                    f"so a proposal that does not carry one cannot be placed "
                    f"on that space at all — this is a bug in the call that "
                    f"built the proposal rather than a territory to refuse, "
                    f"and no set could admit it (feature 212)."
                ),
            )

        if not self._themes.covers(theme):
            slugs = self._themes.slugs()
            # An empty set is a *reachable* state here even though the
            # compiler refuses one: the member's builder falls back to it when
            # the committed artifact cannot be read, so a refusal against it
            # must still read as a sentence rather than trailing off into an
            # empty list.  The count and the list are spelled together for
            # that reason.
            listed = (
                f"{len(slugs)} themes: {', '.join(slugs)}"
                if slugs
                else "which names no themes at all"
            )
            return ThemeAdmission(
                reason=ThemeReason.ILLEGAL_THEME,
                detail=(
                    f"{ILLEGAL_THEME_CODE}: the proposal opens a root in "
                    f"{theme!r}, which is outside the configured legal set "
                    f"({self._themes.kind}, {listed}). PRD §9: 'Dream-RSI "
                    f"improves search efficiency within a space. It cannot "
                    f"create edge in a space that has none,' and choosing the "
                    f"space is the human's highest-value input — so a root the "
                    f"set does not name is one nobody admitted, and authoring "
                    f"there spends agent calls, evaluation budget and a node's "
                    f"identity on territory outside the campaign's remit. "
                    f"Membership is exact: a near-miss spelling is a different "
                    f"theme, not a narrower one. Refused before the node is "
                    f"opened (features 212, 205; §9.3)."
                ),
            )

        return ThemeAdmission(
            reason=ThemeReason.LEGAL,
            theme=theme,
            title=self._themes.title(theme),
            detail=(
                f"{LEGAL_THEME_CODE}: the proposal's root {theme!r} is a theme "
                f"the configured legal set names — "
                f"{self._themes.title(theme)!r} (§9.3) — so the branch is "
                f"inside the hypothesis space PRD §9 reserves to the human and "
                f"the node may be opened with this theme_root (feature 212)."
            ),
        )

    def require(self, theme: object) -> str:
        """Refuse unless the theme root is a legal one.

        The caller's verb: raises :class:`~signal_agent.errors.IllegalThemeError`
        — carrying the gate's own ``illegal_theme`` sentence — when the root is
        refused, and returns the slug when it is admitted, so a caller can put
        it on the last line before it opens a node and have feature 212
        enforced there rather than remembered.
        """
        return self.admit(theme).require()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"SignalThemeGate(themes={len(self._themes)})"


def signal_theme_gate() -> SignalThemeGate:
    """The law, for a caller that wants it directly.

    Not a component — the ``@register`` builder in this member's ``__init__``
    is, and this is the same call minus the composition.  The member's own
    tests and any operator script reach here.
    """
    return SignalThemeGate(committed_legal_themes())
