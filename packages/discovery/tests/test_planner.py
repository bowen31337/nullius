"""Feature 233: the planning step, and the boundary a planning hook may read.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 233: *System
rejects a plan_grid implementation that inspects the current episode, because
planning may read only prior campaign manifests.*  docs/nullius-tech-
architecture.md §605–§606 draws the line — ``plan_grid`` *"runs BEFORE a
campaign. May read only prior campaign manifests."* — and PRD §426 states the
far side: *"Never inspects the current episode."*

Five things are asserted here, in the order the feature's own sentence implies
them: the **context** (what planning may read, and that the episode is absent
from it rather than filtered), the **reach** (an episode-shaped read is refused
and *recorded*, so swallowing it does not help), the **call shape** (an
implementation that demands the episode at its signature), the **admission**
(a hook that stays inside the boundary gets its own return value back
unchanged, and its own failure propagates when it fails without reaching), and
the **ask** (the malformed requests, which are this member's other class).

**The refusals are pinned by class and by code constant, not by prose.**  Like
feature 241's and 242's suites, this file asserts :class:`PlanInspectionError`
and :data:`INSPECTS_EPISODE` / :data:`DEMANDS_EPISODE` rather than
substring-matching a sentence, so the message can be improved without breaking
a test that was only ever about *which* refusal occurred.  The codes *are*
asserted as text, because a code is part of the contract — an operator greps a
log for it — so it is pinned as data rather than left to a message's opening
words.

**The episode vocabulary is transcribed independently, not iterated.**  The
parametrised reach test walks a list written out here from §11's ``question.*``
API, §10.2's blocked pair and PRD §426 — **not** from
:data:`EPISODE_SURFACE`.  A test that iterated the constant would agree with
itself whatever the constant said, which is precisely the failure the list
exists to catch: a name dropped from the constant during a refactor would
otherwise take its own test with it.

**The swallow case is the load-bearing one.**  A seam that only raised would be
a seam any hook could walk through by spelling its reach defensively —
``getattr(ctx, "question", None)`` catches the ``AttributeError`` and carries
on — so the reach is recorded by the context and judged after the call.  Test
:func:`test_a_hook_that_swallows_the_refusal_is_still_refused` is what makes
that a check rather than a hope, and
:func:`test_every_reach_is_named` is the reason the record is a list rather
than a flag.

The suite needs no database and no fixture: feature 233 is a pure function of a
hook and the manifests a caller already holds, which is itself one of the
things pinned below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import discovery
import pytest
from discovery import (
    DEMANDS_EPISODE,
    EPISODE_SURFACE,
    INSPECTS_EPISODE,
    CampaignManifest,
    CampaignPlanningError,
    DiscoveryError,
    PlanContext,
    PlanInspectionError,
    plan_grid,
)

#: The episode-shaped names a planning hook may not read, transcribed here from
#: the three places that name them — §11's ``question.*`` API, §10.2's
#: explicitly blocked pair, and PRD §426's prohibition — rather than from
#: :data:`discovery.EPISODE_SURFACE`.  This is the independent statement the
#: constant is checked against; see the module docstring for why iterating the
#: constant would defeat the purpose.
SPEC_EPISODE_NAMES = (
    # §11's question API — the episode's reading verbs.
    "question",
    "observed",
    "legal_actions",
    "legal_roots",
    "meta",
    "probe_batch",
    "budget_remaining",
    "commit",
    "reveal",
    # §10.2 — "the policy runtime additionally blocks" these two.
    "best_so_far",
    "budget_spent",
    # The campaign's own live state (PRD §426: never inspects *the episode*).
    "episode",
    "tree",
    "frontier",
    "campaign_id",
    "is_null",
)


def _id(manifest: CampaignManifest) -> str:
    """A manifest's campaign id — the key the context orders a history by."""
    return manifest.campaign_id


def _manifest(campaign_id: str | None = None, **counts: int) -> CampaignManifest:
    """A completed campaign's manifest, for the history a hook plans against.

    Built through the real :class:`CampaignManifest` rather than a stand-in,
    because the context validates what it is handed and a double would be this
    suite agreeing with itself: the point of the history is that it is feature
    242's value, read by feature 242's own store.
    """
    import uuid as _uuid

    fields = {
        "branch_count": 3,
        "refine_count": 2,
        "leaf_count": 3,
        "node_count": 5,
        "depth_max": 2,
        "theme_roots": 3,
    }
    fields.update(counts)
    return CampaignManifest(
        campaign_id=campaign_id or str(_uuid.uuid4()),
        calibration_status="ok",
        **fields,
    )


# -- The context: what planning may read, and what is absent --------------------


def test_a_context_carries_the_three_reads_and_nothing_else() -> None:
    """Planning's whole surface is the history and the two ceilings.

    §605 fixes the three reads a hook's author is written against — the prior
    campaign manifests, the ceiling on parallel branches and the ceiling on
    refinements per branch — and this suite pins that the context exposes
    exactly those, so a hook written against the policy-runtime member's
    ``GridPlanningContext`` runs against this one unmodified.  The names are
    the contract, not an implementation detail: two members restate this
    spelling rather than import it, and the restatement is only honest if the
    names agree.
    """
    history = (_manifest(), _manifest())
    context = PlanContext(history, max_branches=8, max_refinements=4)
    assert context.prior_campaigns == tuple(
        sorted(history, key=lambda manifest: manifest.campaign_id)
    )
    assert context.max_branches == 8
    assert context.max_refinements == 4
    # Empty history is valid and load-bearing — §606's "including empty
    # history" — and is the state a fresh deployment plans in.
    empty = PlanContext()
    assert empty.prior_campaigns == ()
    assert (empty.max_branches, empty.max_refinements) == (0, 0)


def test_the_history_is_normalised_ascending_by_campaign_id() -> None:
    """Two contexts over one history are one history, whatever order it came in.

    The context sorts by campaign id at construction, so a hook cannot tell a
    differently-ordered batch from an ordered one and two contexts built from
    the same manifests compare equal.  The order is the *identity* of a
    campaign, not an accident of how the caller's query returned — the same
    normalisation discipline feature 241's ``ThemeSet`` applies to a configured
    space and feature 217's tree applies to its nodes.
    """
    first, second = _manifest(), _manifest()
    # The two orders are chosen by campaign id rather than assumed, so the test
    # exercises a genuinely reversed batch whatever UUIDs `_manifest` minted.
    later, earlier = max(first, second, key=_id), min(first, second, key=_id)
    ascending = PlanContext((earlier, later))
    descending = PlanContext((later, earlier))
    assert ascending == descending
    assert [m.campaign_id for m in descending.prior_campaigns] == [
        earlier.campaign_id,
        later.campaign_id,
    ]


def test_the_episode_is_absent_from_the_context_rather_than_filtered() -> None:
    """There is nowhere in the context the current episode could be.

    docs §10.2's law for the prefix view — *"It is not a filtered view over the
    full tree; unrevealed nodes are not present in the returned structure at
    all"* — restated for the planning context by feature 233.  The claim is
    about what the object is **made of**: the episode names are not slots, the
    class carries no ``__dict__`` at all (so the stray ``ctx.__dict__`` access
    §10.2 names finds ``None`` to read), and no attribute of the context
    reaches one.  A screening predicate would make the boundary a function to
    get right; an absence makes it a property of the object.
    """
    context = PlanContext((_manifest(),), max_branches=4, max_refinements=2)
    assert PlanContext.__slots__ == (
        "_inspections",
        "_max_branches",
        "_max_refinements",
        "_prior_campaigns",
    )
    # No instance dictionary beside the slots — the stray access finds nothing.
    assert not hasattr(context, "__dict__")
    for name in SPEC_EPISODE_NAMES:
        assert name not in PlanContext.__slots__, name
    # And the object graph reachable from the context holds no episode either:
    # the history it carries is feature 242's manifests, which carry counts and
    # a status and no tree.  ``campaign_id`` is excluded from this half of the
    # check, and the exclusion is the point rather than a convenience: a *prior*
    # manifest's id is a prior campaign's, which is exactly what planning may
    # read, while the name on the episode surface means *the campaign being
    # planned*.  The same spelling names two different facts, and only the
    # second is refused — which is why the refusal is a fact about the context
    # (that has no campaign_id at all, as asserted just above) rather than about
    # the name.
    for manifest in context.prior_campaigns:
        for name in set(SPEC_EPISODE_NAMES) - {"campaign_id"}:
            assert not hasattr(manifest, name), (name, manifest)


def test_a_context_cannot_be_moved_or_hollowed_out() -> None:
    """The history a hook reasons from cannot be rewritten or deleted.

    A context whose attributes could move would be a past the hook edited — and
    planning against a past it edited afterwards is inspecting the episode by
    other means.  Every assignment is refused, not merely the permitted names,
    because a shadow attribute attached beside the earned ones would be state
    the hook put there; the refusal is an ``AttributeError``, the attribute
    protocol's own error, naming the law.
    """
    context = PlanContext((_manifest(),))
    with pytest.raises(AttributeError) as raised:
        context.prior_campaigns = ()
    assert "cannot be reassigned" in str(raised.value)
    with pytest.raises(AttributeError) as raised:
        context.sneaky = "state the hook attached"
    assert "cannot be reassigned" in str(raised.value)
    with pytest.raises(AttributeError) as raised:
        del context.prior_campaigns
    assert "nothing to delete" in str(raised.value)
    # The refusals above did not move the history.
    assert len(context.prior_campaigns) == 1


def test_a_fresh_context_is_built_per_call() -> None:
    """Nothing one planning call wrote can reach the next.

    Freshness is a fact about identity — the prefix-view discipline, restated:
    a hook handed a context per planning call cannot carry state between
    campaigns, so one campaign's plan cannot be shaped by the previous
    campaign's hook invocation.  The two contexts are equal because the history
    is, and distinct because they are different objects.
    """
    seen: list[PlanContext] = []

    def hook(ctx: PlanContext) -> str:
        seen.append(ctx)
        return "plan"

    plan_grid(hook, prior_campaigns=[_manifest()])
    plan_grid(hook, prior_campaigns=[_manifest()])
    assert len(seen) == 2
    assert seen[0] is not seen[1]


# -- The reach: refused, and recorded ------------------------------------------


@pytest.mark.parametrize("name", SPEC_EPISODE_NAMES)
def test_an_episode_shaped_read_is_refused_by_name(name: str) -> None:
    """Every name on the episode surface is refused, and the name is named.

    Parametrised over the independently transcribed list — see the module
    docstring — so a name dropped from the constant is caught here rather than
    silently escaping the boundary.  The refusal echoes the name the hook
    reached for, because an author's repair is *stop reading that*, and a
    refusal that only said "you inspected the episode" would leave them
    guessing which line did it.
    """

    def hook(ctx: PlanContext) -> object:
        return getattr(ctx, name)

    with pytest.raises(PlanInspectionError) as raised:
        plan_grid(hook, prior_campaigns=[_manifest()])
    message = str(raised.value)
    assert message.startswith(INSPECTS_EPISODE)
    assert repr(name) in message


def test_a_direct_attribute_read_is_refused_at_the_reach() -> None:
    """The plain spelling of a reach is refused where it happens.

    ``ctx.question`` resolves through normal lookup, misses, and lands in
    ``__getattr__`` — so the refusal arrives *during* the hook rather than only
    after it returns.  Both halves matter: the raise is what stops a hook that
    would otherwise plan from the episode, and the record below is what stops
    one that catches it.
    """

    def hook(ctx: PlanContext) -> object:
        return ctx.question

    with pytest.raises(PlanInspectionError) as raised:
        plan_grid(hook, prior_campaigns=[])
    assert str(raised.value).startswith(INSPECTS_EPISODE)


def test_a_hook_that_swallows_the_refusal_is_still_refused() -> None:
    """The reach is recorded by the context, so catching it does not help.

    **This is the test that makes feature 233 a check rather than a hope.**  A
    seam that only raised would be walked through by
    ``getattr(ctx, "question", None)``: the hook catches the ``AttributeError``
    — which the refusal is, deliberately — gets its default, and plans from
    whatever it found.  The context appends the name to its record *before*
    raising, so the reach is a fact the context kept rather than a fact the
    hook chose to surface, and ``plan_grid`` refuses after the call.  The hook
    below returns a perfectly good plan; it is refused anyway, on the reach.
    """

    def hook(ctx: PlanContext) -> tuple[str, int]:
        question = getattr(ctx, "question", None)  # swallowed on purpose
        return ("a fine-looking plan", 0 if question is None else 1)

    with pytest.raises(PlanInspectionError) as raised:
        plan_grid(hook, prior_campaigns=[_manifest()])
    assert str(raised.value).startswith(INSPECTS_EPISODE)
    assert "'question'" in str(raised.value)


def test_the_refusal_meets_hasattr_and_hasattr_is_still_recorded() -> None:
    """A probe is a reach, and the attribute protocol keeps working.

    ``hasattr`` catches every ``AttributeError`` including this refusal — which
    is what makes it the right base class for the error, since a hook probing
    an object must get the honest ``False`` it asked for rather than a crash.
    But the probe is still a reach: the hook asked whether the episode was
    reachable, and the context records that it asked.  Both halves are the
    feature: the protocol is not broken, and the boundary is not walked.
    """

    def hook(ctx: PlanContext) -> str:
        assert hasattr(ctx, "tree") is False
        assert hasattr(ctx, "prior_campaigns") is True
        return "plan from history"

    with pytest.raises(PlanInspectionError) as raised:
        plan_grid(hook, prior_campaigns=[_manifest()])
    message = str(raised.value)
    assert "'tree'" in message
    # The *permitted* read beside it was not recorded — the record is of
    # reaches, not of reads.
    assert "'prior_campaigns'" not in message


def test_every_reach_is_named() -> None:
    """A hook that reached twice is told both, not one per attempt.

    The "name every offender at once" discipline feature 241's theme batch and
    feature 242's manifest gate both state, applied to the reach record: an
    author repairs the whole implementation rather than resubmitting to learn
    the next name, and each planning call is a call.  The order is the reach
    order — the first thing the hook went looking for is the first thing its
    repair should address — which is why the record is a list rather than a set.
    """

    def hook(ctx: PlanContext) -> str:
        for name in ("question", "frontier", "budget_remaining"):
            getattr(ctx, name, None)
        return "plan"

    with pytest.raises(PlanInspectionError) as raised:
        plan_grid(hook, prior_campaigns=[])
    message = str(raised.value)
    assert "3 name(s)" in message
    for name in ("question", "frontier", "budget_remaining"):
        assert repr(name) in message
    # In the order the hook reached for them.
    assert (
        message.index("'question'")
        < message.index("'frontier'")
        < message.index("'budget_remaining'")
    )


def test_the_context_records_the_reaches_it_refused() -> None:
    """The record is readable, and it is the reaches rather than the reads.

    ``PlanContext.inspections`` is the record the seam judges, and it is public
    for the same reason ``PrefixView.cells`` is: a reader that walks it finds
    what the hook asked for, which is exactly what the caller needs to know.
    Empty is the ordinary case.

    Both spellings of a reach are recorded — a direct read and a ``getattr``
    with a default — which is the record's whole justification.  The second
    line is written *without* ``raises`` on purpose: the swallow is the case
    the record exists for, and a test that expected a raise there would be
    asserting that the swallow fails, which is not true and not what the
    feature relies on.
    """
    context = PlanContext((_manifest(),))
    assert context.inspections == ()
    with pytest.raises(PlanInspectionError):
        context.episode  # noqa: B018 - the reach itself, asserted to fail
    assert getattr(context, "observed", None) is None  # swallowed, and recorded
    assert context.inspections == ("episode", "observed")


# -- The call shape: the same question at the signature -------------------------


def test_a_hook_that_demands_the_episode_at_its_signature_is_refused() -> None:
    """An implementation expecting the episode at its parameters is refused.

    233's sentence read one step earlier than the body: a hook declared
    ``def plan_grid(self, ctx, question)`` has already decided the episode will
    be passed to it, before it runs a line.  It is refused under its own code
    because its repair differs in kind — *take the context alone* rather than
    *stop reading the episode* — the reason this member splits reasons by
    repair.
    """

    def hook(ctx: PlanContext, question: object) -> str:
        return "plan"

    with pytest.raises(PlanInspectionError) as raised:
        plan_grid(hook, prior_campaigns=[_manifest()])
    message = str(raised.value)
    assert message.startswith(DEMANDS_EPISODE)
    assert "plan_grid(ctx)" in message


def test_a_hook_that_requires_a_keyword_only_episode_is_refused() -> None:
    """A keyword-only ``question`` is a demand the seam never intended to meet.

    ``def plan_grid(ctx, *, question)`` binds the context fine, so this is not
    the arity case — it is the *name*: the hook has declared that a parameter
    exists which planning was never going to pass, and the hook has no default
    to fall back on, so it cannot run on the context alone.

    The refusal is on the demand.  Contrast
    :func:`test_a_keyword_only_hook_cannot_be_handed_the_context_at_all`, where
    the refusal is on the *shape* instead — the two arrive at the same code by
    different routes, and keeping both pinned means a later rewrite of the bind
    cannot quietly satisfy one rule by breaking the other.
    """

    def hook(ctx: PlanContext, *, question: object) -> str:
        return "plan"

    with pytest.raises(PlanInspectionError) as raised:
        plan_grid(hook, prior_campaigns=[])
    assert str(raised.value).startswith(DEMANDS_EPISODE)


def test_a_keyword_only_hook_cannot_be_handed_the_context_at_all() -> None:
    """A hook with *no positional parameter* is refused on shape, not on demand.

    ``def plan_grid(*, question=None)`` names an episode-shaped parameter, but it
    would be refused even if that parameter were named ``config`` and defaulted —
    the defect is that there is no positional parameter for the context to bind
    to, so the hook never receives the history it plans from.  This is the one
    place the seam is stricter than "what the call requires", and it is pinned
    separately so the distinction survives.

    The refusal is a :class:`DiscoveryError` rather than the bare ``TypeError``
    ``hook(context)`` would raise, which is the property that matters: a caller
    handling this member's failures with one ``except`` must not be handed a raw
    interpreter error by its own boundary check.
    """

    def hook(*, question: object = None) -> str:
        return "plan"

    with pytest.raises(DiscoveryError) as raised:
        plan_grid(hook, prior_campaigns=[])
    assert isinstance(raised.value, PlanInspectionError)
    assert str(raised.value).startswith(DEMANDS_EPISODE)


def test_optional_extras_are_admitted_because_the_hook_runs_without_them() -> None:
    """A parameter *with a default* is not a demand, and ``**kwargs`` less so.

    What the check counts is what the call **requires**, not what the signature
    names: a hook that names a second parameter but gives it a default runs
    with the context alone, which is the whole of what planning promises, and a
    hook taking ``**kwargs`` is explicitly open to whatever it is handed.  The
    contrary rule — refusing on the *name* — would be a false-positive machine
    against legitimate callables, the same stance the member takes on the
    node-id screen's bare words.
    """

    def optional_hook(ctx: PlanContext, question: object = None) -> str:
        return "plan" if question is None else "planned from the episode"

    def kwargs_hook(ctx: PlanContext, **extras: object) -> str:
        return "plan" if not extras else "planned from extras"

    assert plan_grid(optional_hook, prior_campaigns=[]) == "plan"
    assert plan_grid(kwargs_hook, prior_campaigns=[]) == "plan"


def test_a_hook_that_takes_no_argument_is_refused_rather_than_a_bare_type_error() -> None:
    """A hook taking no parameter is refused, and refused as a *DiscoveryError*.

    The same question at the other end of the arity: ``def plan_grid()`` binds
    the context nowhere, so the seam cannot hand it the history it plans from.
    It is the same repair as a hook demanding a second parameter — *declare
    ``plan_grid(ctx)``* — so it carries the same code.

    The refusal is pinned to the member's base class deliberately, because that
    is the failure this guards: a check that only counted *more than one* required
    positional would admit a zero-parameter hook, and the invocation would then
    raise a bare ``TypeError`` — outside the single ``except DiscoveryError``
    every caller of this member writes.  A boundary that leaks a raw interpreter
    error is a boundary a caller cannot handle, so what is asserted is the
    *family* first and the code second.
    """

    def hook() -> str:
        return "planned from thin air"

    with pytest.raises(DiscoveryError) as raised:
        plan_grid(hook, prior_campaigns=[_manifest()])
    assert isinstance(raised.value, PlanInspectionError)
    assert str(raised.value).startswith(DEMANDS_EPISODE)



def test_a_bound_method_is_judged_on_what_it_requires() -> None:
    """A bound method carries no ``self``, so it is judged like a plain function.

    §605 spells the hook ``def plan_grid(self, ctx)``, so the canonical policy
    is a *method* — and a bound method's signature is what remains after
    ``self`` is bound, which is exactly one required positional parameter.  The
    seam must admit it, and must refuse its unbound spelling passed with two
    required positionals, because that one is demanding the episode.  Both
    sides of one hook, so the check is about what the call needs rather than
    about how the callable was written.
    """

    class Policy:
        def plan_grid(self, ctx: PlanContext) -> str:
            return f"plan over {len(ctx.prior_campaigns)}"

    policy = Policy()
    assert plan_grid(policy.plan_grid, prior_campaigns=[_manifest()]) == "plan over 1"
    with pytest.raises(PlanInspectionError):
        plan_grid(Policy.plan_grid, prior_campaigns=[])


# -- The admission: the hook's own value, and the hook's own failure ------------


def test_an_admitted_hook_returns_its_own_value_unchanged() -> None:
    """The seam judges the boundary, not the plan.

    What a plan must *be* is feature 229's law and what it must *contain* is
    features 234–237's; feature 233 owns one thing, and a seam that tidyed up
    the value would be deciding something it was not asked to decide.  The
    return value is the hook's own object — identity, not equality — so a
    caller can hand it straight to feature 235's plan law.
    """
    sentinel = object()
    plan_grid(lambda ctx: sentinel, prior_campaigns=[])
    assert plan_grid(lambda ctx: sentinel, prior_campaigns=[]) is sentinel


def test_a_hook_that_raises_without_reaching_propagates_its_own_error() -> None:
    """A broken planner is not a planner that inspected the episode.

    Refusing a hook that merely blew up as an inspection would tell its author
    to rewrite an implementation whose actual problem was a typo, and would
    conflate two facts that need two different repairs.  This seam is not the
    plan's judge: an error raised inside a hook that stayed inside the boundary
    comes out unchanged, in the hook's own class.
    """

    class Boom(RuntimeError):
        pass

    def hook(ctx: PlanContext) -> str:
        raise Boom("a typo, not a boundary break")

    with pytest.raises(Boom):
        plan_grid(hook, prior_campaigns=[_manifest()])


def test_a_hook_that_reached_and_then_failed_is_refused_as_an_inspection() -> None:
    """The recorded reach wins over the hook's own failure, and is chained.

    A hook that inspected the episode and *then* blew up has still inspected
    the episode — that is the fact this feature exists to catch — so the
    refusal is the inspection's, and the hook's own error is chained as the
    cause so the underlying failure is not lost to an operator reading the
    traceback.  The ordering is the whole point: judging the exception first
    would let a hook hide a reach behind any failure it could arrange.
    """

    class Boom(RuntimeError):
        pass

    def hook(ctx: PlanContext) -> str:
        getattr(ctx, "question", None)  # swallowed, then the hook fails
        raise Boom("and then this")

    with pytest.raises(PlanInspectionError) as raised:
        plan_grid(hook, prior_campaigns=[_manifest()])
    assert str(raised.value).startswith(INSPECTS_EPISODE)
    assert isinstance(raised.value.__cause__, Boom)


# -- The ask: the malformed requests, in this member's other vocabulary ---------


@pytest.mark.parametrize(
    "history",
    [
        None,
        42,
        3.5,
        "a string standing in for a batch",
        b"a bytes literal too",
        {"a-mapping": 1},
        [object()],  # a batch whose entry is not a manifest
    ],
)
def test_a_history_that_is_not_a_batch_of_manifests_is_a_planning_error(
    history: object,
) -> None:
    """A malformed ask is :class:`CampaignPlanningError`, not an inspection.

    The two classes split by repair, and this is the planning-error side:
    nothing about the *implementation* is wrong, so the repair is to re-send a
    corrected ask.  A string is refused rather than iterated into characters —
    the guard feature 241's ``ThemeSet`` states for a batch of themes, and here
    it matters for a sharper reason: a string read as a batch would hand the
    hook a history of single characters and the refusal would surface as a
    mangled manifest rather than as *"that is not a batch"*.
    """
    with pytest.raises(CampaignPlanningError) as raised:
        plan_grid(lambda ctx: "plan", prior_campaigns=history)  # type: ignore[arg-type]
    assert not isinstance(raised.value, PlanInspectionError)


def test_a_single_manifest_is_a_history_of_one() -> None:
    """A caller planning with exactly one prior campaign is a legitimate caller.

    The seam wraps a bare manifest rather than refusing it for not being a
    batch — the same stance feature 242's ``admit_completed_campaigns`` takes
    for a single campaign it is asked to judge, and for the same reason: a seam
    that made the caller's shape its own problem would be making that caller's
    problem worse.
    """
    manifest = _manifest()

    def hook(ctx: PlanContext) -> int:
        return len(ctx.prior_campaigns)

    assert plan_grid(hook, prior_campaigns=manifest) == 1


def test_a_history_is_accepted_from_any_iterable() -> None:
    """Where the batch came from is the caller's business; what is in it is the seam's.

    A tuple, a list and a generator all name the same history, so the seam
    materialises the batch once and judges its *contents* — the split feature
    242's ``_validated_batch`` states for its own gate, restated here because
    the helper is private to its module and no member reaches across one.
    """
    manifests = [_manifest(), _manifest()]
    for history in (tuple(manifests), manifests, iter(manifests), (m for m in manifests)):
        assert plan_grid(lambda ctx: len(ctx.prior_campaigns), prior_campaigns=history) == 2


def test_a_hook_that_is_not_callable_is_a_planning_error() -> None:
    """There is no boundary to judge in a value that cannot be run.

    Feature 233 refuses an *implementation*, and a value that is not callable
    is not one — so the refusal is the planning class's (re-consider the ask),
    not an inspection's (rewrite the implementation).  A string, a ``None`` and
    a number all land here.
    """
    for not_a_hook in (None, "def plan_grid(ctx): ...", 42, object()):
        with pytest.raises(CampaignPlanningError):
            plan_grid(not_a_hook)  # type: ignore[arg-type]


@pytest.mark.parametrize("ceiling", [True, False, 3.5, "4", None, -1])
def test_a_ceiling_that_is_not_a_genuine_non_negative_count_is_refused(
    ceiling: object,
) -> None:
    """The two ceilings are counts, and a count is a genuine non-negative int.

    ``bool`` is an ``int`` subclass, so ``True`` would silently read as a
    ceiling of one — the SQLite affinity trap this workspace guards elsewhere,
    and the same one feature 242's census validators name.  A negative ceiling
    admits no branch, so a context carrying one bounds nothing.
    """
    with pytest.raises(CampaignPlanningError):
        plan_grid(lambda ctx: "plan", max_branches=ceiling)  # type: ignore[arg-type]
    with pytest.raises(CampaignPlanningError):
        plan_grid(lambda ctx: "plan", max_refinements=ceiling)  # type: ignore[arg-type]


# -- Vocabulary, class discipline, and the cross-member pin ---------------------


def test_the_episode_surface_covers_every_name_the_spec_names() -> None:
    """The constant covers what §11, §10.2 and PRD §426 name — as data.

    The constant is checked against the independently transcribed list rather
    than against itself, and the check is one-directional on purpose: the
    constant may hold *more* than the spec's sentence names (the campaign's own
    state is episode-shaped whether or not §426 spells it), but it may not hold
    less, because a missing name is a reach the boundary does not see.
    """
    missing = set(SPEC_EPISODE_NAMES) - EPISODE_SURFACE
    assert not missing, f"EPISODE_SURFACE is missing spec-named reads: {sorted(missing)}"


def test_the_two_codes_are_the_tokens_the_refusals_open_with() -> None:
    """Both codes are pinned as text — an operator greps a log for them.

    The spec gives feature 233 no ``… error message`` phrase of its own, so the
    tokens are this module's; what makes them contract is that every refusal
    opens with one, which is what these assertions fix.  The two are distinct
    because they are two repairs.
    """
    assert INSPECTS_EPISODE == "inspects_episode"
    assert DEMANDS_EPISODE == "demands_episode"
    assert INSPECTS_EPISODE != DEMANDS_EPISODE


def test_the_inspection_refusal_is_a_discovery_error_and_an_attribute_error() -> None:
    """The refusal is catchable by both vocabularies, and is neither sibling.

    It is a :class:`DiscoveryError` so the member's one ``except`` catches it —
    the single-except discipline every class here keeps — and an
    :class:`AttributeError` because it is raised from an attribute access and
    the attribute protocol must keep working over the context.  It is
    deliberately **not** a :class:`CampaignPlanningError` (the ask was not
    malformed) nor a ``VoidCampaignError`` (nothing was voided): it sits beside
    them, on the rule :class:`IllegalThemeError` states — the classes split by
    the repair the caller must make, and no corrected re-request fixes an
    implementation that read the episode.
    """
    assert issubclass(PlanInspectionError, DiscoveryError)
    assert issubclass(PlanInspectionError, AttributeError)
    assert not issubclass(PlanInspectionError, CampaignPlanningError)
    assert not issubclass(CampaignPlanningError, PlanInspectionError)
    assert not issubclass(PlanInspectionError, discovery.VoidCampaignError)


def test_no_component_is_registered_by_this_feature() -> None:
    """Feature 233 adds no ``@register`` — the member still registers one name.

    The planning seam closes over no deployment state: no ``DATABASE_URL``, no
    store, no table.  So it inherits feature 241's reason (*a builder that
    always answers the same value is a function wearing a component's name*)
    and the member's registered surface stays feature 232's single store.  A
    component appears here as a *builder* in the package namespace, which is
    what this asserts is absent — the composed surface is checked by the
    member's own component suite.
    """
    assert isinstance(discovery.COMPONENT_NAME, str)
    planners = [
        name
        for name in dir(discovery)
        if name.startswith("build_") and "plan" in name
    ]
    assert planners == []
    assert callable(discovery.plan_grid)


def test_the_seam_reads_no_store_and_opens_no_file() -> None:
    """Feature 233 is pure — the suite needs no database, and that is the claim.

    The prior manifests reach the hook the only way the spec allows: the caller
    reads them through feature 242's ``CampaignManifests.completed`` and hands
    them in.  So the planning step consults no ``DATABASE_URL`` and touches no
    file, which is why this whole suite runs without a fixture — and why the
    module is import-cheap for the factory's scan.

    The check reads the module's **imports and string literals by AST**, not by
    substring over the file text: the docstring argues at length about the
    store this module does *not* touch, so a naive ``"sqlite3" in source`` test
    would fail on the module's own honest prose — the vacuous-red mirror of a
    vacuous green, and a test that would punish documenting the decision.
    """
    import ast

    tree = ast.parse(Path(discovery.planner.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"sqlite3", "os", "pathlib", "urllib"}), imported

    # No *code* in the module mentions the environment variable either.  The
    # docstrings are skipped by node identity rather than by value, because the
    # module argues at length about the store it does not touch — a check that
    # scanned every literal would fail on the module's own honest prose, which
    # is the vacuous-red mirror of a vacuous green: it would punish documenting
    # the decision instead of testing it.
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    code_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }
    assert not any("DATABASE_URL" in literal for literal in code_literals)


def test_the_episode_surface_covers_the_question_api_it_projects() -> None:
    """The cross-member pin: the policy-runtime question's reads are all covered.

    Two members restate this vocabulary rather than import it (no member
    imports another), so nothing but a test keeps the restatements honest.
    Feature 217's :class:`policy_runtime.PolicyQuestion` is the object whose
    *reading verbs* define what the episode is, and every public method it
    exposes is a name a planning hook could try to reach for; a sibling that
    grew a new accessor without this list growing with it would be a reach the
    boundary does not see.

    The import is inside the test, and ``importorskip`` with it, so a workspace
    without the policy-runtime member degrades one test rather than failing the
    collection of this suite — the discipline
    ``packages/discovery/tests/test_cross_member.py`` states for its own
    sibling pins.
    """
    repo_root = Path(__file__).resolve().parents[3]
    sibling_src = repo_root / "packages" / "policy-runtime" / "src"
    if str(sibling_src) not in sys.path:
        sys.path.insert(0, str(sibling_src))
    policy_runtime = pytest.importorskip(
        "policy_runtime", reason="the policy-runtime member is not in this workspace"
    )
    question = policy_runtime.PolicyQuestion
    public_reads = {
        name
        for name in dir(question)
        if not name.startswith("_") and callable(getattr(question, name, None))
    }
    # ``__init__`` and the object protocol are not reads of the episode.
    public_reads -= {"__init__", "__class__", "__repr__", "__eq__", "__hash__"}
    uncovered = public_reads - EPISODE_SURFACE
    assert not uncovered, (
        f"PolicyQuestion exposes reads the planning boundary does not refuse: "
        f"{sorted(uncovered)} — add them to EPISODE_SURFACE (feature 233)"
    )
