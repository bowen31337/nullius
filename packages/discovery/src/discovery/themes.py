"""The configured legal theme set, and the refusal when a theme is outside it.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 241: *System
rejects a root theme outside the configured legal set when assigning a
research theme.*  The module owns exactly one question — **is this theme in
the deployment's configured legal set?** — and the verb that refuses an
assignment when it is not.

**Why the legal set is configuration and not a schema.**  ``node.theme_root``
is ``TEXT NOT NULL`` (``migrations/versions/0118_node_table.py``, feature 97)
and carries **no** ``CHECK``, deliberately: the set of legal themes is *the
human's input* and changes as the research programme moves, while the schema
is fixed and versioned.  docs/alpha-engine-prd.md §9 states the split in as
many words — *"Dream-RSI improves search efficiency within a space.  It
cannot create edge in a space that has none.  Choosing the space is the
highest-value human input in the system, and it should be encoded as the set
of legal ``theme_root`` values."*  So the refusal lives in the orchestrator's
assignment path, where a planner's declaration meets the space the deployment
declared, and not in the tree's DDL.

**The initial set is PRD §9.3's, and it is the default.**  §9.3 lists the six
research themes the programme starts from, and they are transcribed here as
canonical slugs — :data:`DEFAULT_LEGAL_THEMES` — with the mapping from each
PRD sentence to its slug written out in that constant's docstring, so a reader
can check the transcription rather than trust it.  An **unset**
:data:`LEGAL_THEMES_ENV` resolves to that set, which is the same stance
:func:`canary.allowlist_from_env` takes for §12's import ceiling: a deployment
that declared nothing still has a space, because "nothing configured" must not
silently mean "anything is legal" — that reading would turn a missing
environment variable into an off switch for the feature's whole sentence.  A
variable that is **set and blank** is the strictest space (no theme is legal),
which is a stance an operator can hold on purpose, never a gap.

**A theme identifier is a lowercase slug, and the spelling is canonical.**  A
legal set entry and an assigned theme both have the form
``^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`` (casefolded first — ``"Momentum"`` and
``"  momentum "`` are the same theme as ``"momentum"``, and :meth:`ThemeSet.assign`
answers with the canonical form, so a theme's identity cannot split in two at
the seam the policy conditions on: architecture §11.1 exposes ``theme_root``
through ``question.meta()`` and §11's family-conditional thresholds are keyed
on it, and two spellings of one family would be two families).  What is
**not** done is guessing: ``"order_flow_imbalance"``, ``"order flow
imbalance"`` and ``"order.flow"`` are each one keystroke from a real theme and
are refused rather than normalised into one — the same
refuse-don't-silently-normalise stance feature 232's
:func:`~discovery.campaign._validated_campaign_type` states for §7.3's two
regimes, and for the same reason: a silent repair stores a declaration nobody
made.

**One error class carries both faces of the refusal**, the way
:class:`~canary.CanaryImportError` carries both faces of §12's determinism
floor: a theme being *assigned* that the set does not admit (feature 241's own
sentence), and a *configured* term that is not a theme identifier at all (a
legal set is how the space is enforced, so a term it cannot judge leaves the
check unable to answer).  Every message begins with :data:`ILLEGAL_THEME`
(``illegal_theme``) — the code app_spec.xml feature 212 names for this refusal
— so an operator grepping a log finds it by the feature's own word, the
convention §7.3's ``heterogeneous_world`` and §7.1's ``is_null_column``
refusals already follow here.

**A batch refuses collectively.**  :meth:`ThemeSet.assign_all` names *every*
offending theme in one refusal rather than the first, which is
:func:`canary.screen_imports`'s reason spelled for a different screen: a
planner that learned one illegal root per attempt would be replanned to learn
the rest, and each attempt is a planning call.  A grid plan assigns several
roots at once — architecture §11.1's ``plan.theme_roots`` — so the batch is the
honest shape of the act, not a convenience.

**The boundaries, stated here so they are not re-implemented.**  Four
neighbouring refusals are *not* this module's, and each belongs where the fact
it needs lives:

* feature 213's structurally-dead-territory refusal (sub-30-minute
  liquidity-taking roots) is PRD §9.4's list of spaces that are dead at retail
  scale; it is the signal-agent member's, and it is a judgement about a
  *mechanism*, not a membership test against a configured set;
* feature 212's ``illegal_theme`` refusal is the *proposal*-level twin of this
  one — the same question asked one layer up, at agent authoring time;
* feature 234's "fewer than three distinct theme roots" is the **planning**
  path's check, made at planning time so the campaign is never created, and
  the distinctness of a grid is its subject rather than any one theme's
  legality;
* feature 218's ``legal_roots()`` is the *policy-facing runtime's* accessor —
  the themes a policy may open a walk in — and answering a policy is a
  different act from refusing a planner.

This module is the predicate those four reach for; none of them is this module.

**Stdlib only, and import-cheap.**  ``os``, ``re`` and a dataclass; no
third-party import at module scope, so the factory's scan — which imports this
package to fire its ``@register`` — pays nothing for the predicate.  Nothing
here reads the environment at import time: the default constant is built
through the same validation a configured value passes through (so a default
that ever drifted past the identifier grammar would fail this member's import
loudly rather than first failing a planner quietly), and the variable is read
by :func:`legal_themes_from_env` when a caller asks for it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import IllegalThemeError

__all__ = [
    "DEFAULT_LEGAL_THEMES",
    "DEFAULT_THEME_SET",
    "ILLEGAL_THEME",
    "LEGAL_THEMES_ENV",
    "THEME_ROOT_COLUMN",
    "ThemeSet",
    "assign_theme",
    "legal_themes_from_env",
]

#: The error code feature 241's refusal carries, in the spec's own vocabulary
#: for it.  The message begins with this word so the rejection is greppable by
#: the feature that defines it — the convention §7.3's ``heterogeneous_world``
#: (``nulloracle.plan``) and §7.1's ``is_null_column`` refusals already follow
#: in this workspace, and app_spec.xml feature 212 names ``illegal_theme`` as
#: the message this refusal returns.
ILLEGAL_THEME = "illegal_theme"

#: The environment variable naming the deployment's legal theme set — the
#: space the research programme declared, comma-separated theme identifiers.
#: Unset means :data:`DEFAULT_LEGAL_THEMES` (PRD §9.3's initial six); set and
#: blank means the strictest space (nothing legal); set to a term that is not
#: a theme identifier is a refusal naming this variable, because a legal set
#: is how the space is enforced and not a way around it.
LEGAL_THEMES_ENV = "NULLIUS_LEGAL_THEMES"

#: The column a legal theme is planted in — feature 97's, declared
#: ``TEXT NOT NULL`` by ``migrations/versions/0118_node_table.py``.  Spelled
#: here because it is the column this feature's refusal is *about* (the theme
#: a root is assigned, the value architecture §11.1 exposes through
#: ``question.meta()`` and §11's family-conditional thresholds key on), and
#: because 0118's own description of it — *"the research theme this node's
#: root was planted in"* — is the fact this module's predicate guards.
THEME_ROOT_COLUMN = "theme_root"

#: A well-formed theme identifier: a lowercase slug, anchored at both ends so
#: a leading or trailing separator, an empty segment or a dot-joined path is
#: refused rather than matched, and starting with a letter so a bare number
#: names no theme.  Applied to the **casefolded, stripped** form, so the
#: caller's casing and surrounding whitespace are insignificant while the
#: spelling itself is not.
_THEME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

#: PRD §9.3's initial six theme roots, in the order §9.3 numbers them, as
#: canonical slugs.  Each line of §9.3 is transcribed rather than
#: paraphrased, so a reader can check the mapping against the PRD's own
#: numbering:
#:
#: ``1.`` *Cross-sectional momentum and short-term reversal, small/mid-cap
#: universe* → ``cross-sectional-momentum``;
#: ``2.`` *Order-flow imbalance and microstructure features from the free L2
#: feed* → ``order-flow-imbalance``;
#: ``3.`` *Borrow-rate and funding-state conditioning* →
#: ``borrow-rate-conditioning``;
#: ``4.`` *Volatility-state and dispersion regimes* → ``volatility-dispersion``;
#: ``5.`` *Mechanical calendar and event effects* → ``calendar-events``;
#: ``6.`` *Cross-asset and cross-venue state divergence (state, not price)* →
#: ``cross-asset-divergence``.
#:
#: The slugs are this member's spelling of the PRD's themes and not the PRD's
#: own words, which is deliberate: the set is *the human's input* and a
#: deployment widens or narrows it through :data:`LEGAL_THEMES_ENV` with
#: whatever spelling it prefers (casing and spacing are insignificant).  What
#: the constant fixes is the *default*, so that a deployment which configured
#: nothing still has PRD §9's space rather than an unconstrained one.
#:
#: The tuple is the PRD's order because a default set is documentation as
#: well as data — it is what an operator reads to learn what §9.3 said — while
#: :class:`ThemeSet` sorts its own terms, so the *resolved* set is canonical
#: and this constant's order reaches nothing but a reader.
DEFAULT_LEGAL_THEMES: tuple[str, ...] = (
    "cross-sectional-momentum",
    "order-flow-imbalance",
    "borrow-rate-conditioning",
    "volatility-dispersion",
    "calendar-events",
    "cross-asset-divergence",
)


def _canonical(value: object) -> str | None:
    """The canonical form of a theme identifier, or ``None`` if it is not one.

    Strip, casefold, then match :data:`_THEME_RE` — nothing more.  Three steps
    and no repair: lowercasing and stripping whitespace are the two places
    where a *spelling of the same value* differs, while every other
    difference (an underscore, a space, a dot) is a different string that
    looks like a theme, and this function answers ``None`` for it rather than
    quietly rewriting the caller's declaration into one.
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip().casefold()
    return candidate if _THEME_RE.match(candidate) else None


@dataclass(frozen=True)
class ThemeSet:
    """The deployment's legal theme set — the space, validated and canonical.

    Feature 241's configured set as a value: the theme identifiers the
    orchestrator may assign to a root, canonicalised and deduplicated.
    Construction validates every term and refuses — naming every offender at
    once — a set carrying a term that is not a theme identifier, because the
    set is how PRD §9's space is enforced and a term it cannot judge would
    leave an assignment unanswerable rather than refused.  The grammar is the
    one :meth:`assign` applies, so a term can never be simultaneously
    unassignable and configured as legal.

    Frozen, so a set that has been resolved from a deployment's configuration
    cannot be edited into a wider space by a caller who kept a reference —
    the same discipline :class:`discovery.campaign.CampaignRecord` and
    :class:`nulloracle.plan.CampaignPlan` state, and for the same reason: the
    value is the record of a human decision (which research spaces this
    deployment is allowed to explore), and a mutable one would let the
    decision be widened in memory while the configuration said otherwise.

    Membership is exact after canonicalisation.  :meth:`assign` is the
    feature's verb — it *refuses* — while :meth:`is_legal` and ``in`` answer
    the same question as a bool for a caller that wants to branch rather than
    catch, the pair :meth:`canary.ImportAllowlist.covers` and
    ``term in allowlist`` already are.
    """

    #: The legal theme identifiers, sorted and deduplicated — canonical
    #: lowercase slugs.  May be empty: the strictest space, refusing every
    #: theme, which is a deployment stance an operator can hold on purpose
    #: (a research programme between spaces) and never a vacuous one.
    themes: tuple[str, ...]

    def __post_init__(self) -> None:
        # Checked here so it cannot be skipped by whichever spelling built the
        # value — the default constant, the environment read, or a caller's
        # explicit construction all pass through this one validation.
        if isinstance(self.themes, str) or not isinstance(self.themes, Iterable):
            raise IllegalThemeError(
                f"{ILLEGAL_THEME}: a legal theme set must be a sequence of "
                f"theme identifiers, got {type(self.themes).__name__}; a "
                "single string would be one theme iterated "
                "character by character, which admits nothing and refuses "
                "nothing legibly"
            )
        checked: list[str] = []
        refusals: list[str] = []
        for term in self.themes:
            canonical = _canonical(term)
            if canonical is None:
                refusals.append(
                    f"{term!r}: a theme identifier is a lowercase slug such as "
                    "'order-flow-imbalance' (letters, digits and single "
                    "hyphens, starting with a letter); a legal set is how the "
                    "space is enforced, so a term that is not a theme "
                    "identifier is one no assignment could be judged against "
                    "— fix the entry or drop it"
                )
                continue
            checked.append(canonical)
        if refusals:
            raise IllegalThemeError(
                f"{ILLEGAL_THEME}: the configured legal theme set "
                f"({LEGAL_THEMES_ENV}) carries terms that are not theme "
                f"identifiers — {len(refusals)} of "
                f"{len(refusals) + len(checked)} entries refused:\n  "
                + "\n  ".join(refusals)
            )
        object.__setattr__(self, "themes", tuple(sorted(set(checked))))

    # -- The space ---------------------------------------------------------

    def is_legal(self, theme: object) -> bool:
        """Whether a theme is in the configured legal set.

        The question without the refusal: ``True`` for a canonical member of
        the set, ``False`` for everything else — a theme outside it, a
        misspelling of one inside it, and a value that is not a string at all.
        Case and surrounding whitespace are insignificant, so ``"Momentum "``
        and ``"momentum"`` answer alike and :meth:`assign` hands back the one
        canonical spelling.
        """
        canonical = _canonical(theme)
        return canonical is not None and canonical in self.themes

    def __contains__(self, theme: object) -> bool:
        # The duck-checkable spelling of `is_legal` — "may I plant a root in
        # this theme?" is the question a caller holding the set asks, and it
        # is the same question feature 218's legal_roots() answers for a
        # policy from the other side.
        return self.is_legal(theme)

    def assign(self, theme: object) -> str:
        """Assign a research theme, refusing one outside the legal set.

        Feature 241's sentence as one call: the theme a root would be planted
        in goes in, its **canonical** form comes out, or
        :class:`~discovery.errors.IllegalThemeError` is raised naming the
        theme, the configured set and the repair.  Called before any node is
        expanded — a theme that cannot be assigned is a root the planner must
        not open, which is exactly PRD §9.4's instruction about the spaces
        that are dead at retail scale: *"Do not let the agent open roots
        there."*

        The canonical form is the *caller's* banked value and the one a later
        reader joins on, so the two places a theme can be spelled differently
        — the caller's casing, and whitespace around it — are folded here
        rather than stored, and the row feature 241's refusal protects carries
        one spelling of each family.

        The refusal is one class for two faces of the same question: a value
        that is not a theme identifier at all (a number, a blank string, a
        path or a sentence) is refused for the same reason a well-formed
        theme the deployment did not configure is — the set does not admit it
        — and the message distinguishes the two so the repair is legible.
        """
        canonical = _canonical(theme)
        if canonical is not None and canonical in self.themes:
            return canonical
        raise IllegalThemeError(self._refusal(theme, canonical))

    def assign_all(self, themes: Iterable[object]) -> tuple[str, ...]:
        """Assign a batch of research themes, refusing every illegal one at once.

        The shape a grid plan actually needs — architecture §11.1's
        ``plan.theme_roots`` is a list, and a campaign is multi-theme by
        construction — validated as one unit: every theme is checked before
        any is returned, and a batch carrying an illegal one is refused
        **naming all of them**, so a planner is not replanned once per
        offending root to learn the rest.  The collective refusal is
        :func:`canary.screen_imports`'s stance, applied to this screen.

        The returned tuple is in the order the caller gave, canonicalised,
        and **keeps duplicates**: how many *distinct* themes a campaign's grid
        must span is feature 234's law, checked at planning time so the
        campaign is never created, and a batch helper that quietly deduplicated
        would be pre-empting a decision this feature was not asked to make.

        A batch must be an **ordered sequence** of themes, and the three
        things that are not one are refused by name:

        * a **string**, for the reason :meth:`ThemeSet.__post_init__` refuses
          one — ``"abc"`` is read as the three themes ``a``, ``b`` and ``c``,
          each of them a legal identifier, so a deployment whose space is
          ``{"a", "b", "c"}`` would accept one mistyped theme as three
          assignments and *report success*;
        * a **mapping**, which is iterable and would hand over its *keys* —
          the same silent reading of one value as several, and never what a
          caller passing a mapping meant;
        * an **unordered set**, whose iteration order is the container's
          rather than the caller's, and which varies with the hash seed: this
          member's paths are reproducibility-sensitive (a campaign's roots are
          the arrangement feature 234 counts distinct themes over), so a batch
          whose order the caller never gave is not one this helper will
          report back.

        Anything else that iterates — a list, a tuple, a generator — is a
        sequence of themes by the caller's own arrangement.
        """
        if isinstance(themes, (str, bytes, Mapping, set, frozenset)) or not isinstance(
            themes, Iterable
        ):
            raise IllegalThemeError(
                f"{ILLEGAL_THEME}: a theme batch must be an ordered sequence "
                f"of theme identifiers (a list, tuple or generator), got "
                f"{themes!r} ({type(themes).__name__}); a string is one theme "
                "iterated character by character — 'abc' read as the themes "
                "'a', 'b' and 'c' — and a mapping or an unordered set hands "
                "over values in an order the caller never gave, so either "
                "could be accepted as assignments nobody made rather than "
                "refused as one"
            )
        requested = list(themes)
        canonical: list[str] = []
        refusals: list[str] = []
        for theme in requested:
            form = _canonical(theme)
            if form is not None and form in self.themes:
                canonical.append(form)
                continue
            refusals.append(f"  {self._refusal(theme, form)}")
        if refusals:
            raise IllegalThemeError(
                f"{ILLEGAL_THEME}: {len(refusals)} of {len(requested)} "
                "assigned themes are outside the configured legal set:\n"
                + "\n".join(refusals)
            )
        return tuple(canonical)

    # -- The words ---------------------------------------------------------

    def _refusal(self, theme: object, canonical: str | None) -> str:
        """The message a refused assignment carries — one fact, two repairs.

        Every message begins with :data:`ILLEGAL_THEME` and names the
        deployment's whole legal set, because the answer to "why was this
        refused?" is "because the space is these six and not that one" —
        a message that named neither would leave an operator re-reading the
        configuration to find out what the set was.  The two forms are split
        because the repairs differ: a well-formed theme outside the set means
        *widen the space, or pick a theme inside it*, while a value that is
        not a theme identifier means *this is not a theme at all*.
        """
        configured = ", ".join(self.themes) if self.themes else "nothing (the configured set is empty)"
        if canonical is None:
            return (
                f"{ILLEGAL_THEME}: {theme!r} "
                f"({type(theme).__name__}) is not a theme identifier, so it "
                "names no research theme this deployment could assign; a "
                "theme is a lowercase slug such as 'order-flow-imbalance' "
                f"(letters, digits and single hyphens, starting with a "
                f"letter), and the configured legal set is {configured}. "
                f"Assign a theme from that set, or widen it through "
                f"{LEGAL_THEMES_ENV} — {THEME_ROOT_COLUMN} is the research "
                "theme a root is planted in (architecture §11.1's "
                "family-conditional thresholds are keyed on it), so a value "
                "that is not one of its spellings is a root no later reader "
                "could group"
            )
        return (
            f"{ILLEGAL_THEME}: the research theme {canonical!r} is outside "
            f"the configured legal set ({configured}); PRD §9 encodes the "
            "research space as the set of legal theme_root values — "
            "*\"Choosing the space is the highest-value human input in the "
            "system\"* — and assigning a root outside it would open the "
            "campaign in a space nobody chose. Assign one of the configured "
            f"themes, or widen the space through {LEGAL_THEMES_ENV} if the "
            "theme genuinely belongs in it"
        )

    def __iter__(self) -> Iterator[str]:
        return iter(self.themes)

    def __len__(self) -> int:
        return len(self.themes)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ThemeSet(themes={self.themes!r})"


#: The default legal set — see :data:`DEFAULT_LEGAL_THEMES`.  Built at import
#: through the same validation a configured value passes through, so a default
#: that ever drifted past the identifier grammar would fail this member's
#: import loudly rather than first failing a planner quietly.
DEFAULT_THEME_SET = ThemeSet(DEFAULT_LEGAL_THEMES)


def legal_themes_from_env(env: Mapping[str, str] | None = None) -> ThemeSet:
    """Resolve the deployment's legal theme set from an environment.

    Reads :data:`LEGAL_THEMES_ENV` out of ``env`` — the mapping seam
    :func:`canary.allowlist_from_env` and :meth:`discovery.CampaignRecords.resolve`
    both take, so a test or an operator can hand the resolution an environment
    without touching the process — or the process environment when ``env`` is
    ``None``.

    Three deployments, three answers, and each is a stance rather than a gap:

    * **unset** → :data:`DEFAULT_THEME_SET`, PRD §9.3's initial six.  A
      deployment that declared nothing still has a space; "nothing configured"
      must not silently read as "anything is legal", which would turn a
      missing variable into an off switch for feature 241's whole sentence.
    * **set and blank** → the empty set, the strictest space: no theme is
      legal.  An operator between research spaces can hold that on purpose,
      and every assignment is then refused by name rather than waved through.
    * **set to terms** → those terms, canonicalised.  A term that is not a
      theme identifier is a refusal naming the variable and every offending
      entry (:class:`~discovery.errors.IllegalThemeError`), because
      configuring the space away is the one reading this resolution exists to
      prevent.

    A value that is not a string at all — an environment mapping a caller
    assembled by hand, or one loaded from a config format that produced a
    list where a comma-separated string was meant — is refused the same way,
    naming what arrived.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    raw = source.get(LEGAL_THEMES_ENV)
    if raw is None:
        return DEFAULT_THEME_SET
    if not isinstance(raw, str):
        raise IllegalThemeError(
            f"{ILLEGAL_THEME}: {LEGAL_THEMES_ENV} (the configured legal theme "
            f"set) must be a comma-separated string of theme identifiers, got "
            f"{raw!r} ({type(raw).__name__}); a legal set the resolver cannot "
            "parse is a space no assignment can be judged against"
        )
    terms = [piece.strip() for piece in raw.split(",")]
    terms = [term for term in terms if term]
    try:
        return ThemeSet(tuple(terms))
    except IllegalThemeError as refusal:
        # Re-raised with the variable named, so an operator who set a bad list
        # learns *which* variable to edit — the ``allowlist_from_env`` remedy.
        # The code stays in front of the variable's name, because it is the
        # greppable contract and a message that led with the variable would be
        # the one shape a log search for the feature's own word missed.
        raise IllegalThemeError(
            f"{ILLEGAL_THEME}: {LEGAL_THEMES_ENV} (the configured legal theme "
            f"set) could not be resolved — {str(refusal).removeprefix(ILLEGAL_THEME + ': ')}"
        ) from refusal


def assign_theme(
    theme: Any,
    *,
    legal: ThemeSet | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Assign a research theme — the module-level spelling of feature 241.

    Feature 241's sentence as one call, for the caller that wants the act
    without holding the set: the theme in, its canonical form out, or
    :class:`~discovery.errors.IllegalThemeError` when it is outside the
    deployment's legal set.  The set is ``legal`` when given, else resolved
    from :data:`LEGAL_THEMES_ENV` by :func:`legal_themes_from_env` — the same
    two-step :func:`discovery.create_campaign` takes for ``DATABASE_URL``, so
    a script and a composed process reach the same configuration.

    The module-level spelling exists for the reason feature 232's
    :func:`~discovery.campaign.create_campaign` does: the verb is what the
    feature's sentence names, and a caller with no interest in the set's
    identity should not have to build one to make an assignment.  A caller
    assigning *several* roots holds the resolved set and calls
    :meth:`ThemeSet.assign_all` instead, so the environment is read once
    rather than once per root.

    No default is applied here beyond the resolver's own: with no ``legal``
    and a *blank* configured variable, every theme is refused, and the refusal
    says so — this function never falls back to an unconstrained space.
    """
    # ``legal is None`` is the documented "resolve it from the environment" —
    # not a missing argument, and not a refusal.  Anything else must be the
    # validated value: a set the caller assembled by hand is refused by name
    # rather than re-validated mid-assignment, the stance
    # :func:`canary.screen_imports` takes toward a ceiling that is not an
    # ``ImportAllowlist``.  The type check is an ``isinstance`` against this
    # module's own class and deliberately not a duck-check on ``assign``: a
    # caller who passes a bare function would be handing over the verb rather
    # than the space, and ``AttributeError`` is not the refusal this feature
    # owes them.
    theme_set = legal_themes_from_env(env) if legal is None else legal
    if not isinstance(theme_set, ThemeSet):
        raise IllegalThemeError(
            f"{ILLEGAL_THEME}: the legal set to assign against must be a "
            f"ThemeSet, got {theme_set!r} ({type(theme_set).__name__}); the "
            "configured space is a validated value, not a loose sequence an "
            "assignment would have to re-validate mid-refusal — pass None to "
            f"resolve the deployment's space from {LEGAL_THEMES_ENV}"
        )
    return theme_set.assign(theme)
