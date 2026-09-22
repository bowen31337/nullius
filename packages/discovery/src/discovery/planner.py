"""The planning step, and the boundary a planning hook may read — feature 233.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 233: *System rejects
a plan_grid implementation that inspects the current episode, because planning
may read only prior campaign manifests.*  docs/nullius-tech-architecture.md
§605–§606 states the boundary verbatim:

    def plan_grid(self, ctx: GridPlanningContext) -> GridPlan:
        \"\"\"Runs BEFORE a campaign. May read only prior campaign manifests.
        Must return a non-None plan on every path, including empty history.\"\"\"

and PRD §426 names what is on the far side of it: *"Plus ``plan_grid(context) ->
GridPlan(branch_count=W, refine_count=R)``, run **before** a campaign, using only
prior-campaign manifests. **Never inspects the current episode.**"*  The reason is
not tidiness.  A plan is what the campaign is *opened with* — §5's one campaign =
one discovery tree — so a planner that could read the episode it is about to
describe would be choosing the width, the depth and the themes of a campaign while
looking at the tree that campaign is supposed to discover; the loop's own
anti-convergence clause (feature 24x's tree growth) assumes the plan was a
*decision*, and §4.1.1's fraction is *fixed at planning time, not learned from the
run*.  Planning is therefore the one call in the cycle that must run against
**history alone**.

**This is the boundary feature 229 names and declines to check.**  The
policy-runtime member's :func:`policy_runtime.plan_grid` is the planning *law* —
a hook must return a non-null plan on every path, including empty history — and it
says in as many words that the rest is somebody else's: *"the hook cannot read past
the prior-manifests-only boundary (that boundary is feature 233's check; 229 hands
the hook a context with nothing in it and asks only 'did it return a plan?')"*.  229
therefore tests the hook against a *synthetic empty* context built by the law, and
cannot answer 233's question even in principle.  This module is that check, run by
the orchestrator on the same path: the hook is invoked against the **real** prior
manifests the caller read, before feature 232's record is created — which is what
makes feature 234's *"failing at planning time so the campaign is never created"* a
thing that can happen at all.

**A member never imports another, so the context is restated rather than
imported.**  ``GridPlanningContext`` lives in the policy-runtime member; this
member cannot reach it, and would not want to — the same discipline that restates
the sqlite path translation, the node-id canonicalization, the ``sqlite_master``
probe, §4.1.1's clip and §7.3's regimes.  :class:`PlanContext` carries the three
reads 229's context fixes a hook's author against — the prior campaign manifests,
the ceiling on parallel branches and the ceiling on refinements per branch — with
the same field names and the same meanings, so a hook written against 229's spelling
runs against this one unmodified.  What it deliberately does **not** carry is the
fourth thing a hook might *want*: anything at all about the episode it is planning.

**Absent rather than filtered — the construction feature 223 established for this
member's sibling member, applied to the planning context.**  docs §10.2's law for
the prefix view is *"``prefix_view()`` constructs a fresh object exposing only
revealed nodes.  It is not a filtered view over the full tree; unrevealed nodes are
not present in the returned structure at all."*  233 is the same sentence with the
episode in place of the unrevealed nodes, and it takes the same remedy: the
:class:`PlanContext` a hook is handed holds prior manifests and the two ceilings and
**nothing else** — no question, no tree, no reveal set, no frontier, no statistical
budget, no node ids, and not even the id of the campaign being planned.  There is
nowhere in the object the current episode *could* be, so the boundary is a fact
about what the object is made of rather than a predicate some later path has to get
right — the argument ``PrefixView``'s docstring makes for itself, restated here for
a different object.

**Every episode-shaped name is refused *and recorded*, at the reach.**  The class
carries ``__slots__``, so normal attribute lookup finds the three permitted reads
and nothing else, and every other name lands in :meth:`PlanContext.__getattr__` —
which raises :class:`~discovery.errors.PlanInspectionError` **and appends the name
to a record before raising**.  The record is the load-bearing half and it is not
belt-and-braces: a hook that writes ``getattr(ctx, "question", None)`` swallows the
``AttributeError`` a bare refusal would raise and quietly gets on with inspecting
whatever it found — so a seam that only raised would be a seam any hook could walk
through by spelling its reach defensively.  The record makes the reach a fact the
*context* kept rather than a fact the *hook* chose to surface, and :func:`plan_grid`
reads it after the call and refuses naming **every** name the hook reached for —
the "name every offender at once" discipline
:meth:`discovery.themes.ThemeSet.assign_all` and
:func:`discovery.manifest.admit_completed_campaigns` both state, so an author
repairs the whole implementation rather than one reach per attempt.

**The call shape is the same question read at the signature.**  A hook declared
``def plan_grid(self, ctx, question)`` — or ``def plan_grid(question, ctx)`` handed
over unbound — is an implementation that *expects the episode at its parameters*,
and it is the one reach that happens before the hook runs at all.  It is refused by
binding the hook's authored signature against the single argument planning has,
under its own code (:data:`DEMANDS_EPISODE`) because its repair is different in
kind: the first face's repair is *stop reading the episode*, this one's is *take the
context alone*.  The check is skipped rather than failed for a callable whose
signature cannot be read (a C function, a builtin) — an unreadable signature is not
evidence of a reach, and refusing it would be a false positive against a legitimate
callable; the record still guards everything such a hook actually reads.  Keyword
parameters *with defaults*, and ``**kwargs``, are admitted: they let the hook run
with the context alone, which is all planning promises.

**This seam judges one thing, and deliberately not the other two.**  What a hook
*returns* is feature 229's law, and what the plan *contains* is features 234–237's;
this module returns the hook's own return value **unchanged** — an admission is a
judgement, never an edit, the stance
:func:`discovery.manifest.admit_completed_campaigns` takes for a manifest it
admits.  A hook that raises *without* reaching for the episode propagates its own
error untouched, for the same reason: a broken planner is not a planner that
inspected the episode, and conflating the two would tell an author to rewrite an
implementation whose actual problem was a typo.  A hook that reached *and then*
failed is refused as an inspection, with the hook's own error chained as the cause —
the recorded reach wins, because it is the fact this feature exists to catch.

**What this seam does not catch, stated rather than hidden.**  A hook that reaches
the episode through something *other than the planning context* — a module global it
imported, the ``self`` of a policy object that was constructed with the question, a
path assembled at runtime out of strings — is not caught here.  The seam judges what
a hook reads **from the context planning hands it**, which is the whole of the
surface planning is given and the surface the sentence is about.  This is the same
honest limit :mod:`policy_runtime.learned` states for its own screen (*"a policy that
reaches a model by spelling the loader dynamically — a name built from a string —
evades this screen"*): the *read* face is closed at the object, the *write* face is
closed by the object's attribute protocol, and a reach through a name the hook
already legitimately holds is the caller's to prevent by what it puts in scope.  It
is worth saying why a ``self``-walk is not screened as a *proxy* for this: §11.1
requires a policy to read ``beta`` once in ``__init__`` and route every threshold
through one ``_schedule``, so a policy object legitimately carries state and
inspecting it is not evidence of anything — a screen over ``self`` would be a
false-positive machine that refused the architecture's own mandated shape.

**No component, no store, no I/O, and the member's surface is unmoved.**  The whole
of this module is a pure function of a hook and the manifests the caller already
holds: no ``DATABASE_URL``, no ``sqlite3``, no table, no file, no clock.  It
therefore inherits feature 241's reason for adding no ``@register`` — *a component
whose builder always answers the same value is a function wearing a component's
name* — with feature 242's sharper one behind it, and the member's registered
surface stays feature 232's single store.  The prior manifests reach the hook the
only way the spec allows: the caller reads them through feature 242's
:meth:`~discovery.manifest.CampaignManifests.completed` — the one authority on
which campaigns are complete — and hands them to :func:`plan_grid`.  Stdlib only,
and import-cheap: :mod:`inspect`, :mod:`collections.abc` and this member's own
values and errors, with no third-party import at module scope, so the factory's
scan (which imports this package to fire its ``@register``) pays nothing for it.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import Any

from .errors import CampaignPlanningError, PlanInspectionError
from .manifest import CampaignManifest

__all__ = [
    "DEMANDS_EPISODE",
    "EPISODE_SURFACE",
    "INSPECTS_EPISODE",
    "PlanContext",
    "plan_grid",
]

#: The code an episode-shaped *read* refusal opens with — the token an operator
#: greps a log for, in the ``illegal_theme`` / ``void_campaign`` tradition this
#: member already follows.  The spec gives feature 233 no ``… error message``
#: phrase of its own (unlike §7.3's ``heterogeneous_world``, §9.4's
#: ``illegal_theme`` and §7.4's ``void_campaign``), so the token is this
#: module's, chosen to say the one thing a reader must get out of the line: *this
#: planning hook read the episode it was supposed to plan*.
INSPECTS_EPISODE = "inspects_episode"

#: The code a *call-shape* refusal opens with — the same sentence as
#: :data:`INSPECTS_EPISODE`, read at the hook's signature rather than at its
#: body, and its own token because its repair is its own: the second code's
#: author has already been told what the first code's author was told, one step
#: earlier.
DEMANDS_EPISODE = "demands_episode"

#: The names that are *the current episode* in this system's vocabulary — the
#: surface a planning hook may not read.  Three sources, each restated here
#: rather than imported (no member imports another):
#:
#: * **§11's ``question.*`` API** — the identical interface a policy is handed
#:   during replay (``question.observed()``, ``legal_actions()``,
#:   ``legal_roots()``, ``meta()``, ``probe_batch()``, ``budget_remaining()``,
#:   ``commit()``).  These are the episode's *reading* verbs; a planner holding
#:   any of them is holding the campaign it is planning.
#: * **§10.2's explicitly blocked pair** — ``question.best_so_far`` and
#:   ``question.budget_spent``, *"the policy runtime additionally blocks"*.  They
#:   are blocked for a policy because they are unrevealed-episode facts; they are
#:   blocked for a planner for the same reason and one more.
#: * **the campaign's own live state** — ``tree``, ``episode``, ``frontier``,
#:   ``campaign``/``campaign_id``, the node vocabulary, ``cells``, and the fields
#:   the information barrier exists to keep from anyone who is not the replay
#:   scorer (``is_null`` — prd §4.2, cq-8 — and ``score``).  A planner that can
#:   name the campaign it is planning has left the prior-manifests-only boundary
#:   whatever it does with the name.
#:
#: It is a frozenset of the *spellings* a reach would use, and the honest limit
#: that comes with any such vocabulary is stated in the module docstring rather
#: than papered over.  What makes the list load-bearing rather than decorative is
#: that the refusal it drives does not depend on the hook *surfacing* it: the
#: reach is recorded whether the hook swallows the error or not.
EPISODE_SURFACE = frozenset(
    {
        # §11's question API — the reading verbs.
        "question",
        "observed",
        "legal_actions",
        "legal_roots",
        "meta",
        "probe_batch",
        "budget_remaining",
        "commit",
        "reveal",
        "reveal_many",
        # §10.2's explicitly blocked pair.
        "best_so_far",
        "budget_spent",
        # The campaign's own live state.
        "episode",
        "tree",
        "node",
        "nodes",
        "frontier",
        "open_nodes",
        "campaign",
        "campaign_id",
        "cells",
        "select",
        "run",
        # The two facts the information barrier keeps from everyone but the
        # replay scorer: prd §4.2 (``is_null`` is readable by exactly one
        # component) and the absolute score target a planner may not author.
        "is_null",
        "score",
        "scores",
        "metrics",
    }
)

#: The three reads a planning context *does* carry — the permitted names, listed
#: once so :meth:`PlanContext.__getattr__` and the class's own docstring cannot
#: disagree about which reads a hook may make.  Restated from the policy-runtime
#: member's ``GridPlanningContext`` (§11): a hook written against that spelling
#: runs against this one unmodified, which is the whole reason the names match.
_PERMITTED_READS = ("prior_campaigns", "max_branches", "max_refinements")

#: What :func:`_takes_the_context_alone` binds to a hook's first parameter to ask
#: whether one argument fits at all.  A private sentinel rather than the context
#: itself, because the question is about the *signature* and nothing here should
#: look like a context a hook could have been handed — and never a real
#: :class:`PlanContext`, which would invite reading it.
_THE_CONTEXT = object()


class PlanContext:
    """The read-only argument handed to ``plan_grid`` — prior manifests, and only those.

    The object a planning hook is handed by :func:`plan_grid`, holding exactly
    what the docs say planning may read — the prior campaign manifests, and the
    runtime's configured ceilings on parallel branches and refinements per branch
    — and *nothing else*.  It is the deliberate counterpart of the policy-runtime
    member's ``GridPlanningContext``, which carries the same three fields for the
    same reason, and the deliberate opposite of it in one respect: this object is
    the *whole* of what a hook can reach, so the boundary §606 draws is a fact
    about what it is made of.

    **An unrevealed-episode fact is absent rather than filtered.**  There is no
    question, no tree, no reveal set, no frontier, no statistical budget and no
    campaign id — not as an attribute, not in a slot, not in a ``__dict__`` (the
    class carries :attr:`__slots__` and no dictionary at all, so the stray
    ``ctx.__dict__`` of docs §10.2 finds ``None`` to read).  This is the
    construction ``policy_runtime.PrefixView`` makes for the object a *policy*
    holds, applied to the object a *planner* holds, and it is chosen over a
    screening predicate for the reason that docstring gives: a filter is one more
    function to get right on one more path, while an absence is a property of the
    object.

    **Every episode-shaped read is refused by name and recorded.**  The three
    permitted reads are slots, so they resolve normally; every other name lands in
    :meth:`__getattr__`, which appends the name to :attr:`inspections` and then
    raises :class:`~discovery.errors.PlanInspectionError`.  The recording happens
    *before* the raise and is what makes the refusal unswallowable — see the module
    docstring for why that half is load-bearing and not belt-and-braces.

    **The context is a snapshot, and it cannot be moved.**  :attr:`prior_campaigns`
    is a tuple, normalised ascending by campaign id at construction, so two
    contexts over one history are equal and a hook cannot reorder the past it
    reasons from.  :meth:`__setattr__` and :meth:`__delattr__` refuse *every* name
    — public, private or shadow — so a hook cannot rewrite the history it was
    handed or attach state beside it; the refusal is an :class:`AttributeError`,
    the attribute protocol's own error, naming the law, the same boundary
    ``PrefixView``'s setter draws around the prefix.  Freshness is a fact about
    identity: :func:`plan_grid` builds a new context per call, so nothing one
    planning call wrote can reach the next.
    """

    #: Four slots and no ``__dict__`` beside them: the three permitted reads,
    #: the record of refused reaches, and nothing a stray access could find.
    #: Sorted, so a reader comparing the two contexts' slots sees the same
    #: order the linter enforces (RUF023).
    __slots__ = ("_inspections", "_max_branches", "_max_refinements", "_prior_campaigns")

    def __init__(
        self,
        prior_campaigns: Iterable[CampaignManifest] = (),
        *,
        max_branches: int = 0,
        max_refinements: int = 0,
    ) -> None:
        # The batch is validated by the caller (``plan_grid``) so that a malformed
        # ask is refused once, in one vocabulary, before a hook ever sees a
        # context; this constructor normalises what it is given rather than
        # re-judging it, the "one adapter, one place" split
        # ``discovery.manifest`` states for its own store.
        object.__setattr__(
            self,
            "_prior_campaigns",
            tuple(sorted(prior_campaigns, key=lambda manifest: manifest.campaign_id)),
        )
        object.__setattr__(self, "_max_branches", max_branches)
        object.__setattr__(self, "_max_refinements", max_refinements)
        object.__setattr__(self, "_inspections", [])

    @property
    def prior_campaigns(self) -> tuple[CampaignManifest, ...]:
        """The prior campaign manifests, ascending by campaign id — read-only.

        The whole of what planning may read, and the *real* history rather than
        the synthetic empty context feature 229's law hands a hook: these are the
        manifests a caller read through
        :meth:`~discovery.manifest.CampaignManifests.completed`, so a planner
        reasoning from them is reasoning from feature 242's own record of the
        campaigns that were walked.  Empty is valid and load-bearing — §606's
        *"including empty history"* — and is the state a fresh deployment plans
        in.
        """
        return self._prior_campaigns

    @property
    def max_branches(self) -> int:
        """The runtime's configured ceiling on parallel branches (``W``).

        Carried so a plan can be bounded against the runtime, the read the
        policy-runtime member's context fixes under this same name.  Zero means
        *no ceiling configured*, which is the honest default for a caller that
        did not state one: a context that invented a bound would be this member
        deciding a campaign's width, which is feature 235's decision.
        """
        return self._max_branches

    @property
    def max_refinements(self) -> int:
        """The runtime's configured ceiling on refinements per branch (``R``).

        The counterpart of :attr:`max_branches`, with the same zero-means-unset
        reading and the same reason for it.
        """
        return self._max_refinements

    @property
    def inspections(self) -> tuple[str, ...]:
        """Every episode-shaped name a hook reached for, in the order it reached.

        The record the refusal is built from, and the reason this feature is a
        *check* rather than a hope: a hook that swallows the
        :class:`~discovery.errors.PlanInspectionError` a reach raises still leaves
        the reach here, so :func:`plan_grid` refuses it naming every name.  Empty
        for a hook that stayed inside the boundary, which is the ordinary case.

        Order is the reach order rather than sorted, because the sequence is the
        author's own — the first thing the implementation went looking for is the
        first thing their repair should address.
        """
        return tuple(self._inspections)

    def __getattr__(self, name: str) -> Any:
        """Refuse and record every read that is not one of the three permitted names.

        Fires only after normal lookup fails, so the permitted reads —
        :attr:`prior_campaigns`, :attr:`max_branches`, :attr:`max_refinements`,
        each a slot or a property — never reach it, and *every* other name does.

        The name is appended to :attr:`inspections` **first**, then the refusal is
        raised: a hook that writes ``getattr(ctx, "question", None)`` catches the
        error and carries on, and the record is what still refuses it.  The
        refusal is a :class:`~discovery.errors.PlanInspectionError`, this member's
        own class, rather than a bare :class:`AttributeError` — a caller catching
        the member's one base class must catch the boundary break
        ([[error-vocabulary-at-member-seams]]), and the message names the name that
        was reached, the boundary the name crossed, and the permitted reads, so an
        author knows what to do instead of only what they did
        ([[feature-233-...]]).  The raise is an ``AttributeError`` subclass so
        that ``hasattr`` and the attribute protocol keep working normally over a
        context — a hook probing with ``hasattr`` gets the honest ``False`` it
        asked for, and the probe is *still* recorded.
        """
        self._inspections.append(name)
        permitted = ", ".join(_PERMITTED_READS)
        raise PlanInspectionError(
            f"{INSPECTS_EPISODE}: the planning hook read {name!r} off the planning "
            f"context — planning may read only prior campaign manifests, and "
            f"{name!r} names the current episode (feature 233, docs §605-§606, PRD "
            f"§426). A plan is what a campaign is opened *with*, so a planner that "
            f"could read the tree it is about to describe would be choosing that "
            f"tree's width, depth and themes while looking at the tree itself; the "
            f"boundary is a fact about the object, which carries {permitted} and "
            f"nothing else. Rewrite the hook to plan from ctx.prior_campaigns — the "
            f"manifests of the campaigns already walked (feature 242's record, read "
            f"through CampaignManifests.completed())"
        )

    def __setattr__(self, name: str, value: object) -> None:
        """Refuse every assignment — the history a hook reasons from cannot move.

        Not just the permitted names but *any* name, public, private or shadow,
        because a context whose attributes could move would be a history the hook
        could rewrite: planning against a past it edited afterwards is planning
        that inspected the episode by other means.  An :class:`AttributeError`,
        the attribute protocol's own error, naming the act and the law — the
        boundary ``policy_runtime.PrefixView``'s setter draws around the prefix,
        drawn here around the manifests.
        """
        raise AttributeError(
            f"a planning context is a snapshot of the campaigns already walked and "
            f"cannot be reassigned (attempted `ctx.{name} = {value!r}`): planning "
            "may read only prior campaign manifests, and a context a hook could "
            "rewrite would be a past it edited rather than one it reasoned from "
            "(feature 233, docs §605-§606)"
        )

    def __delattr__(self, name: str) -> None:
        """Refuse deletion — there is nothing here to remove.

        The same law from the other side: ``del ctx.prior_campaigns`` reaching for
        the history is the reassignment it is not allowed to make, and a context
        with no removable attributes cannot be hollowed out by the hook it was
        handed to.
        """
        raise AttributeError(
            f"a planning context carries the campaigns already walked and nothing "
            f"to delete (attempted `del ctx.{name}`): the history is what it was "
            "built from and cannot be reshaped after the fact (feature 233, docs "
            "§605-§606)"
        )

    def __eq__(self, other: object) -> bool:
        """Content equality — two contexts over one history are one boundary.

        Equality is the three reads, not the identity, so freshness never turns
        into inequality: a caller comparing the context its hook was handed with
        one it built from the same manifests gets ``True``, and gets ``False`` the
        moment the history or a ceiling differs.  The *record* is deliberately not
        part of equality — it is how the context was used, not what it is — since a
        context that compared unequal because a hook had reached into it would be a
        value whose identity depended on a past mistake.  A foreign type answers
        ``NotImplemented``, the honest reflex of a value that compares only with
        its own.
        """
        if not isinstance(other, PlanContext):
            return NotImplemented
        return (
            self._prior_campaigns == other._prior_campaigns
            and self._max_branches == other._max_branches
            and self._max_refinements == other._max_refinements
        )

    def __hash__(self) -> int:
        """The hash of the three reads, matching :meth:`__eq__` — so a caller can
        key a plan's provenance by the history it was planned against."""
        return hash(
            (self._prior_campaigns, self._max_branches, self._max_refinements)
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PlanContext(prior_campaigns={len(self._prior_campaigns)}, "
            f"max_branches={self._max_branches}, "
            f"max_refinements={self._max_refinements})"
        )


def _takes_the_context_alone(hook: Callable[..., Any]) -> bool | None:
    """Whether ``hook`` can run on the planning context alone.

    ``True`` when ``hook(context)`` is a call the signature actually permits — the
    shape §605 gives it.  ``False`` when the bind fails: a required second
    positional is an implementation expecting the episode at its parameters, a
    required keyword-only is a name the seam was never going to pass, and a
    signature with no positional parameter at all cannot be handed the context
    either.  ``None`` when the signature cannot be read at all — a genuinely
    uninspectable C function, ``time.time`` and its kind — because an unreadable
    signature is not evidence of a reach and refusing it would be a false positive
    against a callable that might be perfectly legitimate.

    ``True``/``False`` and ``None`` are deliberately three answers rather than two:
    the caller must refuse on ``False`` and *skip* on ``None``, and collapsing
    "this hook is wrong" into "I could not tell" would either refuse good callables
    or admit bad ones.

    **The check is the bind itself, not a count of parameters.**  The earlier
    spelling counted required positionals and refused on more than one, which
    answered the wrong question in both directions: it admitted a hook that takes
    *none* (``def plan_grid()``), because zero is not more than one — and that hook
    then escaped as a bare ``TypeError`` from the invocation below, outside the
    ``DiscoveryError`` a caller's single ``except`` is written against.  Asking
    whether one positional argument *binds* subsumes every case the count was
    reaching for and answers the zero-parameter one too.  Note that builtins are
    mostly *not* the unreadable case — ``len`` and ``str.upper`` inspect fine and
    answer ``True``; ``None`` is for the C functions with no signature to read.

    **Keyword-only parameters are refused even with a default, and that is not an
    accident of the bind.**  A ``def plan_grid(*, question=None)`` cannot be called
    as ``hook(context)`` — there is no positional parameter for the context to bind
    to — so it is a hook the seam has nothing to hand, which the bind reports
    correctly.  This is the one place the rule is stricter than "what the call
    *requires*": a keyword-only extra is refused on *shape* rather than on demand,
    because a hook with no positional parameter never receives the history at all.

    Where the rule does hold is the positional case: naming a parameter ``question``
    while giving it a default is a hook that runs without one, so it is admitted,
    and the *body* reading it is the first face's business.
    """
    try:
        signature = inspect.signature(hook)
    except (TypeError, ValueError):  # a callable with no readable signature
        return None
    try:
        # A method's unbound ``self`` is the caller's business: a bound method has
        # no ``self`` in its signature, and an unbound one that requires two
        # positional parameters is demanding the episode just as plainly.
        signature.bind(_THE_CONTEXT)
    except TypeError:
        return False
    return True


def plan_grid(
    hook: Callable[..., Any],
    *,
    prior_campaigns: Iterable[Any] = (),
    max_branches: int = 0,
    max_refinements: int = 0,
) -> Any:
    """Run one planning hook against prior manifests alone — feature 233's check.

    The feature's verb, and the orchestrator's planning step: the caller hands in
    the hook it is about to plan a campaign with and the prior manifests it read
    through feature 242's :meth:`~discovery.manifest.CampaignManifests.completed`,
    and gets back whatever the hook returned — *only* if the hook stayed inside the
    prior-manifests-only boundary §606 draws.  It runs **before** feature 232's
    campaign record is created, which is what makes feature 234's *"so the campaign
    is never created"* a thing that can happen at all.

    The steps, each refusal in its own vocabulary and each step's own reason:

    1. **the ask is well formed** — ``hook`` callable, ``prior_campaigns`` a batch
       of this member's :class:`~discovery.manifest.CampaignManifest` (a tuple, a
       list, a generator; a bare ``CampaignManifest`` is wrapped, because refusing
       to plan from one campaign's history for not being a batch would be a seam
       making the caller's problem worse; and a bare *string* is refused rather
       than iterated into characters, the guard
       :meth:`discovery.themes.ThemeSet.assign_all` states for a batch of themes),
       the two ceilings genuine non-negative integers.  Refused with
       :class:`~discovery.errors.CampaignPlanningError` — malformed asks, refused
       before anything runs, the class this member's write path uses for the same
       reason.
    2. **the hook takes the context alone** — a signature that cannot be called
       with one positional argument is refused with :data:`DEMANDS_EPISODE`: a hook
       requiring a second parameter is an implementation expecting the episode at
       its parameters, and a hook taking none cannot be handed the context at all.
       Both are the same repair (*declare ``plan_grid(ctx)``*) and both are refused
       *before* the call, so neither escapes as a bare ``TypeError`` from the
       invocation below — which is what the member's one-``except`` discipline
       requires.  A signature that cannot be read at all (an uninspectable C
       function such as ``time.time``) skips this check rather than failing it,
       because not being able to read a signature is no evidence about it.
    3. **the hook runs under a fresh context** — a new :class:`PlanContext` per
       call over the history as it stands, so nothing an earlier planning call wrote
       can reach this one, and so the history a plan was made against is the history
       that was passed.  The hook is invoked synchronously; an ``async def`` is not
       awaited, because §605 runs the planning hook before a campaign opens and an
       awaitable plan is no plan — but it is not *this* seam's refusal either (229's
       law owns the return shape), so it surfaces as whatever the un-awaited call
       raises, honestly.
    4. **the record is judged** — a hook that reached for an episode-shaped name is
       refused with :data:`INSPECTS_EPISODE`, naming **every** name it reached for,
       whether or not the hook swallowed the error.  A reach that happened *and*
       the hook then failed is refused the same way with the hook's own error
       chained as the cause: the recorded reach wins, because it is the fact this
       feature exists to catch, and the chain keeps the hook's own failure legible
       underneath.  A hook that raised *without* reaching propagates its own error
       unchanged — this seam is not the plan's judge, and a broken planner is not a
       planner that inspected the episode.

    Admitted, the hook's return value is returned **unchanged**: what a plan must
    be is feature 229's law and what it must contain is features 234-237's, and this
    seam editing the value would be it deciding something it was not asked to
    decide — the stance :func:`discovery.manifest.admit_completed_campaigns` takes
    for a manifest it admits.
    """
    if not callable(hook):
        raise CampaignPlanningError(
            f"feature 233 checks a planning hook, got {hook!r} "
            f"({type(hook).__name__}), which is not callable; planning may read "
            "only prior campaign manifests, and this seam can only judge that of an "
            "implementation it can run — pass the policy's authored plan_grid "
            "callable"
        )
    history = _validated_history(prior_campaigns)
    _validated_ceiling(max_branches, "max_branches")
    _validated_ceiling(max_refinements, "max_refinements")

    takes_context_alone = _takes_the_context_alone(hook)
    if takes_context_alone is False:
        raise PlanInspectionError(
            f"{DEMANDS_EPISODE}: the planning hook cannot run on the planning "
            "context alone — planning may read only prior campaign manifests, so "
            "the one argument a hook is handed is the history (feature 233, docs "
            "§605-§606, PRD §426). A hook that declares a second required parameter "
            "expects the current episode at its signature, before it has run a "
            "single line; planning runs before the campaign exists, so there is no "
            "episode to pass it. A hook that declares no parameter accepts no "
            "argument at all, and cannot be handed the history either. Declare the "
            "hook as plan_grid(ctx) — the context carries ctx.prior_campaigns, "
            "ctx.max_branches and ctx.max_refinements, which is the whole of what "
            "planning may read"
        )

    context = PlanContext(
        history, max_branches=max_branches, max_refinements=max_refinements
    )
    try:
        returned = hook(context)
    except BaseException as error:
        # The reach is judged *first*: a hook that inspected the episode and then
        # blew up is refused as an inspection, with its own failure chained so the
        # cause is not lost.  A hook that only blew up is not this feature's
        # business and propagates untouched.
        if context.inspections:
            raise PlanInspectionError(
                _inspection_message(context.inspections)
            ) from error
        raise

    if context.inspections:
        raise PlanInspectionError(_inspection_message(context.inspections))
    return returned


def _inspection_message(reached: tuple[str, ...]) -> str:
    """The refusal for a hook that reached — naming **every** name it reached for.

    One builder so the post-call refusal and the post-exception refusal say the
    same thing, and so the count and the names are rendered in one place: an author
    who reached for two episode facts is told both, rather than repairing one and
    meeting the other on the next attempt — the "name every offender at once"
    discipline this member's theme batch and manifest gate both state.
    """
    listed = ", ".join(repr(name) for name in reached)
    return (
        f"{INSPECTS_EPISODE}: the planning hook read {len(reached)} name(s) off "
        f"the planning context that are not prior campaign manifests — {listed} "
        "(feature 233, docs §605-§606, PRD §426). Planning runs before a campaign "
        "exists and may read only the manifests of the campaigns already walked, so "
        "a hook that reaches for the current episode — its question, its tree, its "
        "frontier, its node ids, its budget or its scores — is planning the "
        "campaign while looking at the campaign, and the plan it returns would be a "
        "description rather than a decision (docs §4.1.1's fraction is fixed at "
        "planning time, not learned from the run). The reach is refused whether or "
        "not the hook caught it: the context records every name it was asked for, "
        "so `getattr(ctx, 'question', None)` is refused exactly as plainly as a "
        "direct read. Rewrite the hook to plan from ctx.prior_campaigns"
    )


def _validated_history(prior_campaigns: Any) -> tuple[CampaignManifest, ...]:
    """Materialise the prior manifests, refusing anything that is not one.

    The seam's adapter, so the hook is handed values rather than spellings — the
    same split :func:`discovery.manifest._validated_batch` makes for its own batch,
    restated here because that helper is private to its module and no member
    reaches across one.  A bare :class:`~discovery.manifest.CampaignManifest` is
    accepted and wrapped: a caller planning with exactly one prior campaign is a
    legitimate caller, and refusing it for not being a batch would be the seam
    making that caller's problem worse.  A string is **not** iterated into
    characters — the guard :class:`~discovery.themes.ThemeSet` states for a set of
    themes, and here it matters for a sharper reason than tidiness: a string read as
    a batch would hand a hook a history of single characters and the refusal would
    arrive as a mangled manifest rather than as *"that is not a batch"*.
    """
    if isinstance(prior_campaigns, CampaignManifest):
        return (prior_campaigns,)
    if isinstance(prior_campaigns, (str, bytes)) or not isinstance(
        prior_campaigns, Iterable
    ):
        raise CampaignPlanningError(
            f"planning takes a batch of prior campaign manifests, got "
            f"{type(prior_campaigns).__name__}; feature 233 lets a planning hook "
            "read only prior campaign manifests, and a value that is not a sequence "
            "of manifests is no history a hook could plan from — read them with "
            "CampaignManifests.completed()"
        )
    history = tuple(prior_campaigns)
    for position, manifest in enumerate(history):
        if not isinstance(manifest, CampaignManifest):
            raise CampaignPlanningError(
                f"the prior-campaign batch's entry at position {position} is "
                f"{type(manifest).__name__}, not a CampaignManifest; the history a "
                "planning hook may read is feature 242's completed-campaign "
                "manifests — the record of what each campaign's tree held — and a "
                "value that is not one tells the hook nothing it is allowed to know "
                "(feature 233)"
            )
    return history


def _validated_ceiling(value: Any, field_name: str) -> int:
    """Refuse a configured ceiling that is not a genuine non-negative integer.

    The same check feature 232 applies to ``workspace_count`` and feature 242 to
    its census counts, restated for the two read-only bounds a context carries: a
    ``bool`` is not a count (the SQLite affinity trap this workspace guards
    elsewhere — ``True`` would read as a ceiling of one), a non-``int`` is not a
    count, and a negative ceiling is not one a runtime could hold.  Named with its
    field, so a refusal says which bound and why.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CampaignPlanningError(
            f"a planning context's {field_name} must be a genuine integer, got "
            f"{value!r} ({type(value).__name__}); the ceilings bound a plan the "
            "hook may author, and a value that is not a count bounds nothing "
            "(feature 233)"
        )
    if value < 0:
        raise CampaignPlanningError(
            f"a planning context's {field_name} must be non-negative, got {value!r}; "
            "a negative ceiling admits no branch, so a context carrying one bounds "
            "nothing (feature 233)"
        )
    return value
