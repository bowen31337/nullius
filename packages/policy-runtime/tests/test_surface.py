"""Feature 224, the policy answer surface — a policy reaches no ``best_so_far``
and no ``budget_spent``, by any attribute walk.

app_spec.xml, "Exploration Policy Runtime", feature 224 (``depends_on=223``):
*System blocks policy access to best_so_far and budget_spent, which rejects an
attribute walk that attempts to reach them.*  The sentence the tests below pin
is docs/nullius-tech-architecture.md §10.2's:

    The policy runtime additionally blocks: ``question.best_so_far``,
    ``question.budget_spent``, filesystem access, and any import outside an
    allowlist.

and prd §12 invariant 3 is where the first two come from: *"The exploration
policy sees **prefix-only** information. No unrevealed scores, no absolute
score targets, no hardcoded node ids."*

Two properties are worth stating because they are what make this an enforcement
rather than a decoration, and each has tests below:

* **the walk is stopped, not the two names.**  The feature's own sentence is
  *"rejects an attribute walk that attempts to reach them"*, and a walk is
  stopped by enumerating what is admitted: an unconfigured name is absent from
  the object, whether it is one of §10.2's two or a field the runtime grows
  next quarter.  Several tests below reach for names that are *not* in §10.2
  for exactly this reason;
* **the surface holds no episode.**  The refusal would be theatre if the
  object one attribute away from the surface were the thing being defended —
  ``surface.observed.__self__.best_so_far`` is the whole barrier gone, so the
  answers are read out and copied at construction and the episode is nowhere
  in the object graph.  This is the same construction feature 223 chose for
  the view, one level out: *absent rather than filtered*.

The refusal is deliberately **two things at once** — a
:class:`~policy_runtime.PolicyAnswerSurfaceError` and an
:class:`AttributeError` — and that is tested here too, because it is what makes
``hasattr``, ``getattr`` with a default, ``contextlib.suppress`` and a
``dir()``-driven loop all behave correctly over the surface rather than
raising *through* a walk that had already decided the name was absent.
"""

from __future__ import annotations

import contextlib
import gc
from typing import Any

import pytest
from policy_runtime import (
    DEFAULT_ANSWERS,
    FORBIDDEN_ANSWERS,
    PolicyAnswerSurfaceError,
    PolicyRuntimeError,
    PolicySurface,
    policy_surface,
)

#: The two names §10.2 blocks, in the bare spelling a policy would reach for.
BLOCKED = ("best_so_far", "budget_spent")


class Episode:
    """A replay episode in miniature — the object feature 224 stands in front of.

    Carries the two facts §10.2 blocks (``best_so_far``, ``budget_spent``)
    alongside the two the default surface admits, because that is what a real
    episode is: the runtime holds both, and the *surface* is the thing that
    decides which of them a policy sees.  A test that built an episode holding
    only the admitted answers would prove nothing — the barrier would be a fact
    about the fixture rather than about this member.

    The answers are *methods*, as §11 spells them (``observed()``,
    ``budget_remaining()``), so the surface is exercised against the interface
    a policy will actually be handed rather than against a dict of values.
    """

    def __init__(self, **overrides: Any) -> None:
        self.best_so_far = overrides.pop("best_so_far", 0.94)
        self.budget_spent = overrides.pop("budget_spent", 37)
        # Stored under a name that is *not* the answer's, deliberately: an
        # instance attribute called ``budget_remaining`` would shadow the method
        # of that name, and the fixture would quietly become an episode whose
        # budget answer is a plain value — the one shape that hides the
        # ``__self__`` leak this module's tests exist to catch.
        self.remaining = overrides.pop("budget_remaining", 63)
        self.observed_cells = overrides.pop("observed_cells", {"n1": {"r2": 0.20}})
        self.actions = overrides.pop("actions", ["n1", "n2"])
        # Kept so a test can show the surface does not carry it out.
        self._ledger = {"trials_charged": 9}

    def observed(self) -> dict[str, Any]:
        return dict(self.observed_cells)

    def budget_remaining(self) -> int:
        return self.remaining

    def legal_actions(self) -> list[str]:
        return list(self.actions)


@pytest.fixture
def episode() -> Episode:
    """A replay episode holding both the admitted and the blocked answers."""
    return Episode()


@pytest.fixture
def surface(episode: Episode) -> PolicySurface:
    """The default surface over that episode — feature 224's object."""
    return policy_surface(episode)


# ---------------------------------------------------------------------------
# the law, in one piece
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", BLOCKED)
def test_a_blocked_answer_is_refused(surface: PolicySurface, name: str) -> None:
    # The feature's own sentence, first and plainly: ``question.best_so_far``
    # and ``question.budget_spent`` are the two §10.2 names, the episode holds
    # both, and the surface refuses both.  The refusal names the law, so a
    # policy author reads what they touched rather than only that it is absent.
    with pytest.raises(PolicyAnswerSurfaceError) as refusal:
        getattr(surface, name)
    detail = str(refusal.value)
    assert name in detail
    assert "§10.2" in detail
    assert "feature 224" in detail


@pytest.mark.parametrize("name", BLOCKED)
def test_a_blocked_answer_is_refused_under_the_question_prefix(
    surface: PolicySurface, name: str
) -> None:
    # §10.2 and this feature's description spell the two names differently —
    # ``question.best_so_far`` in the document, ``best_so_far`` in the feature —
    # so both renderings are the same refusal rather than one law and one
    # unconfigured name.  A deployment whose banned list arrives from feature
    # 225's armed guard in the dotted spelling meets the same sentence.
    with pytest.raises(PolicyAnswerSurfaceError) as refusal:
        getattr(surface, f"question.{name}")
    assert name in str(refusal.value)


@pytest.mark.parametrize("name", BLOCKED)
def test_the_blocked_pair_is_absent_rather_than_filtered(
    surface: PolicySurface, name: str
) -> None:
    # Feature 223's distinction, one level out: the view does not *screen* an
    # unrevealed node, it has nowhere to hold one — and the surface does not
    # screen ``best_so_far``, it was never configured with it.  The names are
    # absent from every read side the surface offers, which is what "absent"
    # means as opposed to "filtered out on the way to the answer".
    assert name not in surface
    assert name not in list(surface)
    assert name not in dir(surface)
    assert not hasattr(surface, name)
    assert name not in repr(surface)
    assert f"question.{name}" not in dir(surface)


@pytest.mark.parametrize("name", BLOCKED)
def test_an_attribute_walk_reaches_the_blocked_pair_nowhere(
    surface: PolicySurface, name: str
) -> None:
    # The feature's mechanism, spelled as the act it names: a *walk* — the
    # ``dir()``-driven loop a policy would write to discover what it can reach,
    # reading every name it is handed.  Every name the walk is given is one the
    # surface answers; the blocked pair is never among them, and asking for it
    # directly is refused rather than answered.
    reached: list[str] = []
    for candidate in dir(surface):
        value = getattr(surface, candidate)
        reached.append(candidate if callable(value) else repr(value))
    assert name not in reached
    assert not any(name in entry for entry in reached)
    with pytest.raises(PolicyAnswerSurfaceError):
        getattr(surface, name)


def test_a_blocked_answer_cannot_be_reached_through_the_admitted_ones(
    surface: PolicySurface,
) -> None:
    # The hand-off is the whole feature, so it is checked as the walk a policy
    # would actually write: start from the surface, follow every *data* edge,
    # and the episode — which holds both blocked answers — is nowhere in the
    # graph.  A surface that stored the episode's bound methods would fail this
    # on ``__self__``; one that stored a dict of answers passes it, which is
    # why the answers are read out and copied at construction rather than
    # aliased ([feature 224's ``_answer_value``]).
    reached = _data_walk(surface)
    assert not any(isinstance(item, Episode) for item in reached)
    assert not any(item is surface for item in reached[1:])
    # And the admitted answers *are* there — a surface that reached nothing at
    # all would be a barrier that refused its own policy.
    assert surface.observed() == {"n1": {"r2": 0.20}}
    assert surface.budget_remaining() == 63


def test_the_surface_has_no_dict_at_all(surface: PolicySurface) -> None:
    # §10.2's "stray ``__dict__`` access", applied to the surface: the class
    # carries slots and no dictionary, so the stray access does not find
    # screened state — it finds nothing, and is refused with the same sentence
    # an unconfigured name gets.  A surface with a ``__dict__`` would at best
    # hold the copied answers; this one cannot even be asked.
    assert not hasattr(surface, "__dict__")
    with pytest.raises(PolicyAnswerSurfaceError):
        surface.__dict__  # noqa: B018 - the stray access itself, asserted to fail


def test_gc_referents_hold_no_episode(surface: PolicySurface, episode: Episode) -> None:
    # The collector's own view of what the surface holds: its direct referents
    # are the copied answers (and its class, which is code, not data) — never
    # the episode.  This is the check that catches the leak shape a bound
    # method would create, one ``__self__`` away from every answer.
    referents = [
        item for item in gc.get_referents(surface) if not isinstance(item, type)
    ]
    assert len(referents) == 1
    assert isinstance(referents[0], dict)
    assert episode not in referents
    assert episode.best_so_far not in referents[0].values()


# ---------------------------------------------------------------------------
# the walk is stopped by an allowlist, not by the two names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "best_score",
        "dollars_spent",
        "budget",
        "spent",
        "score",
        "_ledger",
        "_best",
        "__dict__",
        "__init__",
        "_answers",
        "legal_actions",
        "meta",
        "commit",
    ],
)
def test_every_unconfigured_name_is_refused(surface: PolicySurface, name: str) -> None:
    # **The test the design turns on.**  Only two of these names are in §10.2 —
    # the rest are a runtime's plausible future fields (``best_score``,
    # ``dollars_spent``), a private ledger, dunders, and answers this surface
    # was simply not configured with.  All of them are refused by *one* rule:
    # they are not among the configured answers.  A denylist of the two
    # documented names would admit every other one here, and a policy that
    # reached ``context.best_score`` would hold the same fact §10.2 withholds
    # under a different spelling.
    with pytest.raises(PolicyAnswerSurfaceError):
        getattr(surface, name)
    assert not hasattr(surface, name)


@pytest.mark.parametrize(
    "name", ["_answers", "__dict__", "__init__", "_ledger", "_best"]
)
def test_the_private_names_are_refused_one_sentence(
    surface: PolicySurface, name: str
) -> None:
    # The surface's own machinery is not an answer: the slot that holds the
    # copied values and the gate that refuses everything else are not names a
    # policy may read, because a read of the slot is a back door past the gate
    # and a read of the gate's class is the law rather than the data.  Every
    # private spelling gets the *same* refusal as any unconfigured name, so the
    # object offers no way to tell a name that exists from one that does not.
    with pytest.raises(PolicyAnswerSurfaceError):
        getattr(surface, name)


def test_the_unconfigured_refusal_does_not_out_the_episode(
    surface: PolicySurface,
) -> None:
    # A refusal that distinguished "blocked" from "absent" would be the
    # denylist's failure mode arriving through the error message instead of
    # through the walk: a policy probing names would learn which ones its
    # episode holds.  So the two sentences are compared rather than assumed —
    # a blocked name and an unconfigured one do not both reveal that the
    # episode has them, and the blocked pair is told apart only by citing
    # §10.2, never by naming what the episode holds.
    with pytest.raises(PolicyAnswerSurfaceError) as blocked:
        surface.best_so_far  # noqa: B018
    with pytest.raises(PolicyAnswerSurfaceError) as unlisted:
        surface.best_score  # noqa: B018
    assert "0.94" not in str(blocked.value)
    assert "0.94" not in str(unlisted.value)
    assert "37" not in str(blocked.value)
    assert "trials_charged" not in str(unlisted.value)


def test_a_name_the_episode_does_not_hold_is_refused_like_one_it_does(
    surface: PolicySurface,
) -> None:
    # The indistinguishability from the other side: ``best_score`` (a name no
    # episode here holds) and ``legal_actions`` (a name *this* episode answers
    # and the surface was not configured with) are refused identically — same
    # error class, same sentence.  A policy learns about the surface's
    # configuration, never about the episode behind it.
    with pytest.raises(PolicyAnswerSurfaceError) as absent:
        surface.best_score  # noqa: B018
    with pytest.raises(PolicyAnswerSurfaceError) as unconfigured:
        surface.legal_actions  # noqa: B018
    assert type(absent.value) is type(unconfigured.value)
    # The sentences differ only in the name the caller themselves spelled —
    # strip it and they are the same refusal, so the surface says nothing
    # different about a name the episode *holds* than about one it does not.
    assert str(absent.value).replace("'best_score'", "X") == str(
        unconfigured.value
    ).replace("'legal_actions'", "X")


def test_a_configured_answer_is_admitted_and_answered(
    episode: Episode,
) -> None:
    # The load-bearing negative: a surface that refused everything would pass
    # every test above and be useless.  A deployment that configures
    # ``legal_actions`` — an answer §11 offers and §10.2 does not block — gets
    # it, while the blocked pair stays refused in the same object.  The two
    # facts are one post-condition because that is what the feature is: not
    # "these names are banned" but "these answers are the ones admitted".
    surface = policy_surface(episode, answers=("observed", "legal_actions"))
    assert surface.legal_actions() == ["n1", "n2"]
    assert surface.observed() == {"n1": {"r2": 0.20}}
    assert not hasattr(surface, "budget_remaining")
    for name in BLOCKED:
        with pytest.raises(PolicyAnswerSurfaceError):
            getattr(surface, name)


def test_the_default_answer_set_is_the_prefix_only_pair() -> None:
    # The default is the *safe* posture rather than the law: §10.2 names two
    # answers as blocked and leaves every other answer to the deployment, so an
    # unconfigured runtime gets the two answers §11 offers that are already
    # prefix-only — the revealed cells and the remaining statistical budget —
    # and nothing that could leak.  ``budget_remaining`` is offered because a
    # policy's own mandate needs it to terminate; ``budget_spent`` is not.
    assert set(DEFAULT_ANSWERS) == {"observed", "budget_remaining"}
    assert "budget_spent" not in DEFAULT_ANSWERS
    surface = policy_surface()
    assert sorted(surface) == sorted(DEFAULT_ANSWERS)
    assert surface.observed() == {}
    assert surface.budget_remaining() == 0


def test_the_blocked_pair_is_named_once_and_under_both_spellings() -> None:
    # ``FORBIDDEN_ANSWERS`` exists for the *refusal* rather than for the walk —
    # an unlisted name is refused for not being configured, so naming these two
    # adds nothing to what a policy reaches.  What it buys is a constructor and
    # a gate that can say *why* for the two names the document names, and a
    # deployment's banned list (feature 224 renders ``question.best_so_far``;
    # the armed guard of feature 225 renders ``question.best_so_far`` too)
    # comparing equal here rather than drifting apart.
    assert FORBIDDEN_ANSWERS == {
        "best_so_far",
        "budget_spent",
        "question.best_so_far",
        "question.budget_spent",
    }
    assert set(DEFAULT_ANSWERS) & FORBIDDEN_ANSWERS == set()


# ---------------------------------------------------------------------------
# the refusal is an AttributeError as well as the member's own error
# ---------------------------------------------------------------------------


def test_the_refusal_is_an_attribute_error(surface: PolicySurface) -> None:
    # **The doubling is the feature.**  ``hasattr``, ``getattr`` with a default,
    # ``contextlib.suppress(AttributeError)`` and every ``dir()``-driven loop
    # terminate on the attribute protocol's own error; a refusal that were only
    # a ``PolicyRuntimeError`` would raise *through* a walk that had already
    # decided the name was absent, and ``hasattr`` would answer a question
    # about the law rather than about the surface.
    with pytest.raises(PolicyAnswerSurfaceError) as refusal:
        surface.best_so_far  # noqa: B018
    assert isinstance(refusal.value, AttributeError)


def test_the_refusal_is_still_the_members_own_error(surface: PolicySurface) -> None:
    # And the other half: a caller that never heard of the attribute protocol
    # catches it the way this member's every other failure is caught — the
    # single-``except`` discipline the rest of the error vocabulary keeps.
    with pytest.raises(PolicyRuntimeError):
        surface.best_so_far  # noqa: B018
    assert issubclass(PolicyAnswerSurfaceError, PolicyRuntimeError)
    assert issubclass(PolicyAnswerSurfaceError, AttributeError)
    # The two bases are genuinely two, and neither implies the other: a
    # ``PolicyRuntimeError`` is not an ``AttributeError``, so the doubling is a
    # decision this class makes rather than a fact about the hierarchy it sits
    # in — which is why it is pinned here rather than assumed.
    assert not issubclass(PolicyRuntimeError, AttributeError)
    assert not issubclass(AttributeError, PolicyRuntimeError)


def test_hasattr_answers_false_rather_than_raising(surface: PolicySurface) -> None:
    # The spelling a policy reaches for first.  ``hasattr`` swallows exactly
    # ``AttributeError``, so the refusal being one is what makes this return
    # ``False`` — the honest answer to "does this surface answer
    # ``best_so_far``?" — rather than propagating a refusal through a probe.
    assert hasattr(surface, "best_so_far") is False
    assert hasattr(surface, "observed") is True


def test_getattr_with_a_default_answers_the_default(surface: PolicySurface) -> None:
    # The defensive spelling: a policy that probes a name it is not sure of
    # gets its default, exactly as it would over any other object, so the
    # surface is closed without being hostile.
    sentinel = object()
    assert getattr(surface, "best_so_far", sentinel) is sentinel
    assert getattr(surface, "budget_spent", None) is None


def test_suppress_swallows_the_refusal(surface: PolicySurface) -> None:
    # ``contextlib.suppress`` is how a policy writes "read this if it exists",
    # and it is spelled in terms of ``AttributeError`` — so the doubling is
    # what makes the idiom behave over the surface exactly as it does over any
    # other object.
    with contextlib.suppress(AttributeError):
        surface.best_so_far  # noqa: B018
    with contextlib.suppress(AttributeError):
        surface.nothing_at_all  # noqa: B018
    # And the read that *would* have found something still works, so the
    # suppression is shown to be about the refusal rather than about the
    # surface having gone silent.
    assert surface.observed() == {"n1": {"r2": 0.20}}


def test_the_hiding_spellings_of_an_attribute_read_are_refused(
    surface: PolicySurface,
) -> None:
    # A policy that spells the read dynamically — the shape feature 231's
    # docstring names as evading a static screen — is judged by the same gate,
    # because the gate is the attribute protocol rather than a syntax a parser
    # reads.  ``getattr`` with a name built from strings is the spelling a
    # source-level screen cannot see.
    # The name is assembled at run time — here from the parts a policy could
    # read off the surface itself — so no static screen over the policy's source
    # can see which attribute the read will land on.  The gate is the attribute
    # protocol rather than a parser, so it judges the read whatever spelling
    # produced the name.
    parts = ("best", "so", "far")
    bare = "_".join(parts)
    dotted = f"question.{bare}"
    assert bare in FORBIDDEN_ANSWERS and dotted in FORBIDDEN_ANSWERS
    for spelling in (bare, dotted):
        with pytest.raises(PolicyAnswerSurfaceError):
            getattr(surface, spelling)


# ---------------------------------------------------------------------------
# snapshot semantics, and the value shape
# ---------------------------------------------------------------------------


def test_the_surface_is_a_snapshot_not_a_live_view(episode: Episode) -> None:
    # Feature 223's "fresh" half applied to the answers: they are read out at
    # construction, so an episode that moves afterwards does not move what a
    # held surface answers.  The contrary design — a live surface over the
    # episode — would let a policy read the episode's state without an
    # attribute walk at all, which is the leak this feature closes.
    surface = policy_surface(episode)
    episode.remaining = 1
    episode.observed_cells = {"n9": {"r2": 0.99}}
    assert surface.budget_remaining() == 63
    assert surface.observed() == {"n1": {"r2": 0.20}}


def test_a_mapping_answer_is_copied_out_and_fresh_per_call(
    episode: Episode,
) -> None:
    # The mapping the policy read is its own: writing into it moves the policy's
    # copy and not the surface, and two reads are equal but distinct — the
    # guarantee ``PolicyQuestion.observed`` and ``PrefixView.observed`` both
    # make, kept one seam further out.  A surface whose mapping moved on a read
    # would be a set of answers the policy could shape without earning them.
    surface = policy_surface(episode)
    first, second = surface.observed(), surface.observed()
    assert first is not second
    assert first == second
    first["ghost"] = {"r2": 0.0}
    assert "ghost" not in surface.observed()
    assert episode.observed_cells == {"n1": {"r2": 0.20}}


def test_a_value_answer_is_answered_as_a_callable(episode: Episode) -> None:
    # Every answer on this surface is a callable, because every answer on §11's
    # ``question.*`` interface is one — ``observed()``, ``legal_actions()``,
    # ``budget_remaining()``.  A surface that answered a name with a bare value
    # would hand a policy a different interface from the one §11 specifies for
    # the same name, and a policy written against one pool would break in the
    # other.  The episode here answers with a plain int; the surface still
    # hands a policy a verb.
    surface = policy_surface(episode)
    assert callable(surface.budget_remaining)
    assert surface.budget_remaining() == 63


def test_two_surfaces_over_one_episode_are_equal_and_hashable(
    episode: Episode,
) -> None:
    # A frozen value over frozen answers: equality is content, so two surfaces
    # of one episode are one posture however their rounds were built — and the
    # value hashes, so a replay can key a ledger by the object it handed a
    # policy without a wrapper.  The hash is over the *names*, because an
    # answer may be a mapping and therefore unhashable.
    first, second = policy_surface(episode), policy_surface(episode)
    assert first is not second
    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1
    assert first != policy_surface(episode, answers=("observed",))
    assert policy_surface(episode) != "not a surface"


def test_repr_names_the_answers_not_their_values(surface: PolicySurface) -> None:
    # The debugging aid says which answers the surface offers and nothing about
    # what they hold, so a log line carries the posture without echoing the
    # prefix or the episode's state.
    assert repr(surface) == f"PolicySurface(answers={sorted(DEFAULT_ANSWERS)})"
    assert "n1" not in repr(surface)
    assert "0.94" not in repr(surface)


def test_dir_and_iteration_answer_the_configured_set(surface: PolicySurface) -> None:
    # ``dir()`` is the spelling a policy uses to enumerate an object, and
    # answering the configured set directly makes the enumeration honest rather
    # than incidental — the interpreter filters ``dir()`` through ``getattr``
    # with a default, so a name the surface did not answer would disappear
    # anyway.  Every name yielded is one the gate answers, so the walk circles
    # back on itself.
    assert dir(surface) == sorted(DEFAULT_ANSWERS)
    assert list(surface) == list(DEFAULT_ANSWERS)
    assert len(surface) == len(DEFAULT_ANSWERS)
    for name in dir(surface):
        assert getattr(surface, name) is not None


# ---------------------------------------------------------------------------
# the construction: what a deployment may configure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(FORBIDDEN_ANSWERS))
def test_a_blocked_answer_cannot_be_configured(episode: Episode, name: str) -> None:
    # The way this feature is defeated is not a policy reaching past the gate —
    # it is a *deployment* asking for the very surface the feature forbids, and
    # it can happen by accident: a banned-name list arriving from feature 225's
    # armed guard as a list of answers.  Refusing it at construction means the
    # law is enforced by the member rather than by the deployment's care.
    with pytest.raises(PolicyAnswerSurfaceError) as refusal:
        policy_surface(episode, answers=("observed", name))
    assert name in str(refusal.value)
    assert "§10.2" in str(refusal.value)


@pytest.mark.parametrize("name", ["_answers", "__class__", "_ledger"])
def test_a_private_name_cannot_be_configured(episode: Episode, name: str) -> None:
    # A configured name that landed on the surface's own machinery would put a
    # policy's read on the one object the gate cannot defend — the slot that
    # holds the answers, or the class that holds the gate.
    with pytest.raises(PolicyAnswerSurfaceError):
        policy_surface(episode, answers=(name,))


@pytest.mark.parametrize("name", [3, None, "", "   ", ["observed"]])
def test_a_configured_name_must_be_a_non_empty_string(
    episode: Episode, name: Any
) -> None:
    # The configured set is names, and a value that is not a non-empty string
    # names no answer a policy could read.  Refused at construction rather than
    # producing a surface with an unaddressable entry in it.
    with pytest.raises(PolicyAnswerSurfaceError):
        policy_surface(episode, answers=(name,))


def test_an_answer_the_episode_does_not_hold_is_refused(episode: Episode) -> None:
    # A configured answer the episode cannot produce would hand a policy a
    # surface missing one of its answers — which a policy reads as "this
    # episode has no such fact" rather than as a configuration error.  The
    # refusal names the answer, so the deployment hears which one it got wrong.
    with pytest.raises(PolicyAnswerSurfaceError) as refusal:
        policy_surface(episode, answers=("observed", "mechanism_discrimination"))
    assert "mechanism_discrimination" in str(refusal.value)


def test_a_configured_answer_is_read_once_at_construction(episode: Episode) -> None:
    # The read is a *construction-time* act, and the value is what is stored —
    # so the surface is a snapshot rather than a dispatcher that calls into the
    # episode on every read.  Counted rather than asserted, because "read once"
    # is the claim and a surface that read lazily would pass a value check
    # while failing the snapshot half.
    reads: list[str] = []

    class Counting(Episode):
        def observed(self) -> dict[str, Any]:
            reads.append("observed")
            return super().observed()

        def budget_remaining(self) -> int:
            reads.append("budget_remaining")
            return super().budget_remaining()

    surface = policy_surface(Counting())
    assert sorted(reads) == ["budget_remaining", "observed"]
    surface.observed()
    surface.budget_remaining()
    surface.observed()
    assert sorted(reads) == ["budget_remaining", "observed"]


def test_an_answer_needing_an_argument_is_refused(episode: Episode) -> None:
    # §11's answers take no arguments, and the surface copies an answer's value
    # out at construction — so a name whose value is a reader the surface
    # cannot call is refused rather than guessed at.  Inventing arguments would
    # be the surface answering on the episode's behalf, which is one seam
    # closer to being the episode.
    with pytest.raises(PolicyAnswerSurfaceError) as refusal:
        policy_surface(episode, answers=("meta",))
    assert "meta" in str(refusal.value)


def test_a_reader_the_deployment_supplies_is_consulted_per_call(
    episode: Episode,
) -> None:
    # A deployment that configures its own reader — an answer recomputed per
    # call from state it controls — is handed a callable whose result is
    # returned unchanged.  What it is *not* handed is a reference into the
    # object that produced the result: the surface stores the reader and never
    # the episode, so the leak ``_answer_value`` documents cannot arrive
    # through this branch either.
    class WithReader(Episode):
        def observed(self) -> Any:
            return lambda: {"live": True}

    surface = policy_surface(WithReader())
    assert surface.observed() == {"live": True}
    assert surface.observed() == {"live": True}
    reached = _data_walk(surface)
    assert not any(isinstance(item, Episode) for item in reached)


def test_a_bare_surface_answers_the_defaults_as_empty_prefix_data() -> None:
    # ``policy_surface()`` with no episode is not a degraded form: a runtime
    # composes its surface before it has an episode, and the honest answer then
    # is the empty one — a policy has revealed nothing and holds no budget yet.
    # The two defaults get the empty value *of their own kind*, so a policy
    # comparing the budget against a threshold is comparing numbers.
    surface = policy_surface()
    assert surface.observed() == {}
    assert surface.budget_remaining() == 0
    assert isinstance(surface.budget_remaining(), int)
    assert len(surface) == len(DEFAULT_ANSWERS)


def test_the_surface_never_answers_a_blocked_name_even_when_unconfigured() -> None:
    # The forbidden check runs before the configured-set check, so a bare
    # surface — which was configured with neither blocked name, and holds no
    # episode at all — still refuses the pair *as the law* rather than as an
    # unconfigured name.  The order matters: a policy that reached for
    # ``best_so_far`` must be told what it touched whatever the deployment
    # configured.
    surface = policy_surface()
    for name in BLOCKED:
        with pytest.raises(PolicyAnswerSurfaceError) as refusal:
            getattr(surface, name)
        assert "§10.2" in str(refusal.value)


# ---------------------------------------------------------------------------
# the value semantics, from the other side
# ---------------------------------------------------------------------------


def test_the_surface_cannot_be_extended_or_moved(surface: PolicySurface) -> None:
    # A surface whose attributes could move would be a set of answers the
    # policy could reshape — hand itself ``best_so_far`` it was not given, or
    # attach state beside the admitted answers.  Every spelling of the write is
    # refused, the same boundary ``PrefixView`` and ``EpisodeBeta`` draw around
    # their own values.
    with pytest.raises(PolicyAnswerSurfaceError):
        surface.observed = lambda: {"n9": {}}  # type: ignore[method-assign]
    with pytest.raises(PolicyAnswerSurfaceError):
        surface.best_so_far = 0.0  # type: ignore[attr-defined]
    with pytest.raises(PolicyAnswerSurfaceError):
        surface._answers = {}  # type: ignore[attr-defined]
    with pytest.raises(PolicyAnswerSurfaceError):
        surface.anything = 1  # type: ignore[attr-defined]
    with pytest.raises(PolicyAnswerSurfaceError):
        del surface.observed  # type: ignore[misc]
    # Nothing moved: the surface still answers what it was configured with.
    assert surface.observed() == {"n1": {"r2": 0.20}}


def test_a_policy_cannot_hand_itself_a_longer_answer_set(
    surface: PolicySurface,
) -> None:
    # The write refusal read as the act it prevents: a policy that tries to
    # *add* the blocked answers to the surface it holds — the shortest route to
    # what §10.2 withholds — cannot, because the object is frozen and has no
    # ``__dict__`` to attach state to.  The attempt is refused and the walk
    # afterwards still reaches nothing.
    for name in BLOCKED:
        with pytest.raises(PolicyAnswerSurfaceError):
            setattr(surface, name, 0.99)
        assert not hasattr(surface, name)


def test_the_blocked_pair_is_a_property_of_the_class_not_of_its_mapping(
    surface: PolicySurface,
) -> None:
    # ``object.__setattr__`` reaches any slot directly, bypassing the member's
    # own ``__setattr__`` — a fact about Python's slot protocol, true of every
    # slots class and of feature 223's prefix view in the same measure, and not
    # reachable from authored policy code that does not already hold ``object``.
    # What matters is what *survives* that route: the gate tests the forbidden
    # pair before it consults the answer set, so a surface whose answers were
    # rewritten to *contain* ``best_so_far`` still refuses it.  The pair is a
    # property of the class, not of the mapping the class happens to hold —
    # which is the difference between this feature and a denylist over stored
    # data, and the reason the check is ordered first in ``__getattribute__``.
    rewritten = dict(object.__getattribute__(surface, "_answers"))
    for name in BLOCKED:
        rewritten[name] = 0.99
    object.__setattr__(surface, "_answers", rewritten)
    for name in BLOCKED:
        with pytest.raises(PolicyAnswerSurfaceError):
            getattr(surface, name)
        assert not hasattr(surface, name)
    # The surface still answers what it was legitimately configured with.
    assert surface.observed() == {"n1": {"r2": 0.20}}


def test_the_two_limits_the_class_construction_shares_with_feature_223(
    surface: PolicySurface,
) -> None:
    # Neither limit is this feature's to fix, and both are *identical* in
    # feature 223's PrefixView — the member records them rather than
    # engineering around them, so they are pinned as facts rather than wished
    # away.
    #
    # ``vars()`` tests the type's ``tp_dictoffset`` in C and never performs an
    # attribute access this class could intercept, so it raises CPython's bare
    # TypeError rather than this member's refusal.  A ``__dict__`` that made
    # the route speak would be the stray dictionary §10.2 names — the very
    # shadow state the feature removes — so the bare TypeError, the
    # AttributeError and the refusal all say one thing: there is no dictionary
    # to read.
    with pytest.raises(TypeError) as bare:
        vars(surface)
    assert "__dict__" in str(bare.value)
    with pytest.raises(PolicyAnswerSurfaceError):
        surface.__dict__  # noqa: B018
    # And no 223-style shadow state is reachable under the private slot either:
    # what a caller reads there is the answers mapping, which holds no episode.
    assert "best_so_far" not in object.__getattribute__(surface, "_answers")


def test_the_write_refusal_is_the_same_law_as_the_read_refusal(
    surface: PolicySurface,
) -> None:
    # One class at both ends, so a caller catching the configuration's failure
    # catches the walk's too — "this name may not be an answer", "this name is
    # not an answer" and "this surface cannot be reshaped" are one law read at
    # three moments.
    with pytest.raises(PolicyAnswerSurfaceError):
        surface.best_so_far = 1.0  # type: ignore[attr-defined]
    with pytest.raises(PolicyAnswerSurfaceError):
        surface.best_so_far  # noqa: B018
    with pytest.raises(PolicyAnswerSurfaceError):
        policy_surface(answers=("best_so_far",))


@pytest.mark.parametrize(
    "route",
    ["copy.copy", "copy.deepcopy", "pickle.dumps"],
)
def test_copy_and_pickle_are_refused_in_the_members_own_vocabulary(
    surface: PolicySurface, route: str
) -> None:
    # ``copy`` and ``pickle`` are attribute-walk routes like any other: each
    # asks the object for its own state and rebuilds an equivalent one, so a
    # surface that answered would hand a caller a *second* set to reshape and a
    # route to the answers this gate never sees.  They are refused — and the
    # refusal is this member's own rather than CPython's, because the machinery
    # resolves ``__reduce__``/``__deepcopy__`` on the *type* and its default
    # reflex is a bare ``copy.Error`` or ``PicklingError``, an unnamed failure
    # a caller catching ``PolicyRuntimeError`` would miss.  Forwarding those
    # four dunders through the gate is what lets ``__reduce__`` speak.
    import copy as copy_module
    import pickle as pickle_module

    routes = {
        "copy.copy": lambda value: copy_module.copy(value),
        "copy.deepcopy": lambda value: copy_module.deepcopy(value),
        "pickle.dumps": lambda value: pickle_module.dumps(value),
    }
    with pytest.raises(PolicyAnswerSurfaceError) as refusal:
        routes[route](surface)
    assert "feature 224" in str(refusal.value)
    assert "§10.2" in str(refusal.value)
    # And the surface still answers what it was configured with — a refusal
    # that had broken the object would be a barrier that took its own policy
    # down rather than one that closed a route.
    assert surface.observed() == {"n1": {"r2": 0.20}}


def test_the_reduction_dunders_are_forwarded_but_widen_nothing(
    surface: PolicySurface,
) -> None:
    # The four reduction dunders are in ``_PROTOCOL_NAMES`` and answer with
    # methods, not with data — every one of them raises.  Forwarding them
    # therefore costs the barrier nothing, and a test pins that rather than
    # leaving it to be inferred from the copy test above.
    for name in ("__reduce__", "__reduce_ex__", "__copy__", "__deepcopy__"):
        assert callable(getattr(surface, name, None))
    with pytest.raises(PolicyAnswerSurfaceError):
        surface.__reduce__()
    with pytest.raises(PolicyAnswerSurfaceError):
        surface.__reduce_ex__(2)
    with pytest.raises(PolicyAnswerSurfaceError):
        surface.__deepcopy__({})


def test_isinstance_and_type_still_work_over_the_surface(
    surface: PolicySurface,
) -> None:
    # ``__class__`` is the one private name the gate answers, because the
    # interpreter's own protocol reaches for it and it resolves to the *class*
    # — which carries no answer and no episode.  Refusing it would make the
    # surface hostile to Python (``repr``, ``isinstance``, a debugger) rather
    # than closed to the policy, which is not a trade this feature needs to
    # make; and a policy that walks to the class reaches the law, not the data.
    assert isinstance(surface, PolicySurface)
    assert type(surface) is PolicySurface
    assert surface.__class__ is PolicySurface


def test_the_feature_is_reached_directly_with_no_component() -> None:
    # Feature 224 is a pure construction over an episode — no store, no
    # deployment state, no component — exactly as ``prefix_view`` (223),
    # ``read_beta`` (226), ``plan_grid`` (229) and ``screen_policy`` (230/231)
    # are.  A surface is built and used with no application composed, which is
    # what makes it available to a replay that has an episode and nothing else.
    surface = policy_surface(Episode(), answers=("observed", "budget_remaining"))
    assert surface.observed() == {"n1": {"r2": 0.20}}
    assert surface.budget_remaining() == 63


def _data_walk(root: Any) -> list[Any]:
    """Every object reachable from ``root`` through *data* only.

    The walk a policy could write from the object it holds: attribute values,
    slot values, container elements — never crossing into a class, function or
    method, which are code rather than episode data and hold no answer.  That
    boundary is the honest one: introspection reaching ``PolicySurface`` *the
    class* reaches the gate, not the answers behind it, which is the same
    reading feature 223's own test module takes of its view.
    """
    seen: set[int] = set()
    out: list[Any] = []
    stack: list[Any] = [root]
    while stack:
        candidate = stack.pop()
        if id(candidate) in seen:
            continue
        if isinstance(candidate, type) or callable(candidate):
            continue
        seen.add(id(candidate))
        out.append(candidate)
        if isinstance(candidate, dict):
            stack += list(candidate.keys()) + list(candidate.values())
        elif isinstance(candidate, (list, tuple, set, frozenset)):
            stack += list(candidate)
        else:
            stack += list(getattr(candidate, "__dict__", {}).values())
            stack += [
                getattr(candidate, slot)
                for slot in getattr(type(candidate), "__slots__", ())
                if hasattr(candidate, slot)
            ]
    return out
