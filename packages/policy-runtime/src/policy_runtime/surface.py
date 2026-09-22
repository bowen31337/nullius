"""Feature 224, the policy answer surface — the object an episode hands a
policy, over a configured set of answers and never over the episode itself.

app_spec.xml, "Exploration Policy Runtime", feature 224 (``depends_on=223``):
*System blocks policy access to best_so_far and budget_spent, which rejects an
attribute walk that attempts to reach them.*  The sentence it enforces is
docs/nullius-tech-architecture.md §10.2's, the same paragraph feature 223 and
feature 225 are the other halves of:

    ``prefix_view()`` constructs a fresh object exposing only revealed
    nodes. It is not a filtered view over the full tree; unrevealed nodes
    are not present in the returned structure at all. A policy cannot
    reach them by introspection, attribute walking, or a stray ``__dict__``
    access.

    The policy runtime additionally blocks: ``question.best_so_far``,
    ``question.budget_spent``, filesystem access, and any import outside an
    allowlist.

**223 closed the object; 224 closes the surface around it.**  The prefix view
is prefix-only *by construction* — there is nowhere in it an unrevealed node
could be — and the runtime guard (225) refuses what a *running* policy reaches
for: a file, an import.  Neither of those says anything about the two names
§10.2 lists first, and the reason is that they are not nodes and not reaches.
``best_so_far`` is the best score the replay has seen so far; ``budget_spent``
is the statistical budget already debited.  Both are facts about **the
episode**, not about the campaign, and both are precisely the information the
information barrier exists to keep from a policy: prd §12 invariant 3 — *"The
exploration policy sees prefix-only information. No unrevealed scores, no
absolute score targets…"* — and the policy's own mandate to terminate on its
statistical budget rather than on how well it is doing (feature 221's
``budget_remaining()`` *is* offered; ``budget_spent`` — what it has already
cost — is not).

**So the thing being defended is not the view; it is *the object the episode
hands the policy*.**  A deployment that passes authored policy code its own
episode object — a replay context, a scorer handle, a runtime that happens to
carry ``self.best_so_far`` — has handed it every one of those facts behind one
attribute walk, and no amount of prefix-only construction inside the view
changes that.  :func:`policy_surface` is the hand-off: it wraps an episode in
a :class:`PolicySurface` that answers **the configured answer set and nothing
else** — every *other* name, including the two §10.2 names, raises.

**Every other name, not just those two, and the choice is the feature.**  The
feature's own sentence names the mechanism as much as the pair: it *"rejects
an attribute walk that attempts to reach them"*.  Three designs were available
and only one of them actually stops a walk:

* **an allowlist, as built** — the surface answers the names the deployment
  configured and refuses every other name.  A walk answers nothing it was not
  handed, so a future field of the runtime is unreachable the day it is added
  rather than the day someone remembers to block it.  This is what §10.2's
  *"cannot reach them by introspection, attribute walking, or a stray
  ``__dict__`` access"* asks for, and it is the same construction feature 167
  uses for imports and feature 225 uses for the ceiling: a barrier enumerates
  what is admitted, never what is forbidden — a denylist protects only the
  names its author thought of, which is the failure mode this feature exists
  to close;
* **a denylist of the two names** — it stops those two reads and nothing else,
  so a policy reaches ``context.best_score`` or ``runtime.dollars_spent`` or a
  private ``_best`` the day the runtime grows one.  It also cannot be honest
  about its own refusal: with no configured set, "this name is blocked" and
  "this name does not exist" are indistinguishable to the walk, and the
  refusal would have to claim a law it cannot see;
* **not wrapping at all** — which is what 225 does with the sentence's other
  two halves, and it is right *there* because a file and an import are caught
  where they happen.  An attribute read is not: the episode object holds the
  answer and the policy reads it, and the only seam between those two facts is
  the object in the middle.

The two names are therefore **not a special case in this module's code**.  They
are refused for the reason every other unlisted name is refused — they are not
among the answers a policy was configured to receive — and the module keeps no
list of them.  Where the pair *is* named is in :func:`policy_surface`, as the
default of the answer set: the only configured set a deployment gets without
saying anything, so the safe posture is what an unconfigured runtime has rather
than what it has to ask for.

**Absent rather than filtered, one level up.**  This is feature 223's design
decision restated for the surface, and the restatement is the point rather
than a coincidence.  223 refuses to build a view that holds the tree and
screens it, because a *predicate* is one more function to get right on one
more path and a policy that reached the predicate's subject would hold the
whole campaign.  The same argument applies here: a surface that held the
episode and screened attribute reads would put the episode one ``object.__getattribute__``,
one ``type(surface).__mro__`` walk, or one ``vars(surface._episode)`` away from
the policy it is defending.  So the surface holds prefix data and only prefix
data — the values the configured answers returned, **copied out at
construction**, never the episode, not even under an underscore, and its class
carries ``__slots__`` and no ``__dict__`` at all.  There is no attribute of
this object that names an episode, and therefore no attribute walk that
reaches one.

**Why the surface is built beneath :func:`prefix_view`, not beside it.**  223's
docstring records the limit this feature closes in its own words: the factory
*"holds no reference to the question or the tree it fronts"* — true of the
question and the tree, and silent about the episode.  A replay's episode holds
the reveal set, the budget and the running best, and a view built inside one
still hands the policy a question whose answers are drawn from it.  The
composition is therefore *surface over view*: the episode's answers are
configured once, the surface is what the episode hands a policy, and any other
object the episode also holds — the tree behind the question, a reveal set, a
ledger — stays outside the configured set and is unreachable from what the
policy was given.

**What this is not.**  It is not feature 223's construction: the prefix view is
unchanged, and a caller may still build one (feature 223's own tests do).  It
is not feature 225's guard: nothing here installs an audit hook, wraps an
import, or reads a ceiling — 224 refuses a *read of its own surface*, which
needs no interpreter instrumentation and no extent; the refusal is structural
and holds at any moment, inside an episode or outside one.  It is not feature
230/231's static screen: that judges a policy's authored **source** before it is
admitted, and this refuses the **object** the admitted policy is handed.  And
it is not the runtime that decides *what* an episode may answer — §10.2 names
the two that are forbidden and leaves the rest to the deployment, so the answer
set is configuration (:data:`DEFAULT_ANSWERS` is only the safe default) rather
than a constant in this file.

**Honest limits, stated as this member states every other one.**  A surface is
a *Python* barrier: a policy that reaches the episode through a name it was
handed by some other route — a closure, a global, an argument the deployment
also passed — holds it, exactly as it would hold a file descriptor under
feature 225.  What the surface guarantees is that *this object* offers no route
to it, which is the whole of what an answer surface can promise and the reason
§10.2 pairs this refusal with the sandbox's rather than relying on it alone.
Two consequences of the construction are worth naming rather than leaving to be
discovered.  ``with contextlib.suppress`` and ``getattr(context, name, default)``
behave correctly on the refusals — the class doubles :class:`AttributeError`
for exactly this — so a policy probing for a name learns only that the surface
does not answer it, never that the *episode* has it.  And the values copied out
are the answers themselves, so a surface is only as prefix-only as the answers
the deployment configured: naming an answer that returns an unrevealed cell
defeats this feature and feature 223 together, which is why the default is the
pair of prefix-only ones and why the constructor *refuses a name* — the
forbidden one, or a private one — rather than trusting a caller to be careful.

Two limits belong to the *class construction* rather than to this feature, and
:class:`policy_runtime.PrefixView` (feature 223) has both of them in exactly the
same measure — which is why they are recorded here rather than engineered
around.  ``vars(surface)`` raises the bare :class:`TypeError` *"vars() argument
must have ``__dict__`` attribute"* rather than this module's refusal, because
CPython's :func:`vars` tests the type's ``tp_dictoffset`` in C and never
performs an attribute access this class could intercept.  A ``__dict__`` that
made the route speak would be the stray dictionary §10.2 names — the surface
would be carrying the very shadow state the feature removes — so the bare
:class:`TypeError`, the :class:`AttributeError` and the refusal all say the same
thing here: there is no dictionary to read.  And ``object.__setattr__`` reaches any slot directly,
bypassing :meth:`PolicySurface.__setattr__` — a fact about Python's slot
protocol, true of every slots class and of the prefix view as much as of this
one, and unreachable from authored policy code that does not already hold
``object``.  The guarantee worth stating is what *survives* that route, and it
is checked rather than asserted: :meth:`__getattribute__` tests
:data:`FORBIDDEN_ANSWERS` **before** it consults the answer set, so a surface
whose answers were rewritten to contain ``best_so_far`` still refuses it.  The
forbidden pair is a property of the class, not of the mapping the class holds.

Stdlib only, and import-cheap: :mod:`collections.abc` and the member's own
error, so the factory's scan pays nothing for the law.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .errors import PolicyAnswerSurfaceError

__all__ = [
    "DEFAULT_ANSWERS",
    "FORBIDDEN_ANSWERS",
    "PolicySurface",
    "policy_surface",
]

#: The answers §10.2 names as blocked, and the only two in the whole document.
#: A policy's *own* mandate is the one offer in docs/alpha-engine-prd.md §C4
#: that mentions a budget — ``question.budget_remaining()``, *"statistical, not
#: compute"* — and the pair here is what that offer leaves out: how well the
#: episode has done so far, and how much of the budget is already gone.  Both
#: are episode facts rather than campaign facts, and both are the information
#: the barrier exists to withhold, so neither may be configured as an answer.
#:
#: The set exists for the *refusal* rather than for the walk: an unlisted name
#: is refused for not being configured, so naming these two adds nothing to
#: what a policy reaches — but it makes the refusal say *why* for the two names
#: the document names, and it makes "a deployment may not configure this one"
#: a fact the constructor can enforce rather than a rule in a runbook.
#: Feature 224 renders ``.question.best_so_far`` and the runtime guard renders
#: ``question.best_so_far``, so a deployment whose banned list arrives from the
#: armed guard (feature 225) still compares equal here.
FORBIDDEN_ANSWERS: frozenset[str] = frozenset(
    {"best_so_far", "question.best_so_far", "budget_spent", "question.budget_spent"}
)

#: The answer set an unconfigured deployment gets — the two answers of §11's
#: ``question.*`` surface that are *already* prefix-only by construction:
#: the revealed cells and the remaining statistical budget.  This is the
#: **default rather than the law**: the sentence names two attributes as
#: blocked and leaves every other answer to the deployment, so a runtime with
#: more to offer configures it, and one that says nothing gets the posture
#: that cannot leak.  The pair is deliberately the *read* side of the surface
#: — :meth:`PolicySurface.observed` and :meth:`PolicySurface.budget_remaining`
#: are both answered by this object from what it copied out — so the default
#: needs no episode at all and a policy handed it holds prefix data and one
#: scalar.
DEFAULT_ANSWERS: tuple[str, ...] = ("observed", "budget_remaining")


class PolicySurface:
    """The answers an episode hands a policy — configured, copied out, and
    closed over everything else.

    The object a replay passes authored policy code in place of its own
    episode (docs §10.2: *"The policy runtime additionally blocks:
    ``question.best_so_far``, ``question.budget_spent``…"*).  It answers the
    names the deployment configured and **refuses every other name** — not
    only the two the document names, because the feature's sentence rejects an
    *attribute walk*, and a walk is stopped by enumerating what is admitted
    rather than what is forbidden.

    Hand-written with ``__slots__`` and a :meth:`__getattribute__` gate, the
    construction feature 223 chose for the same reason: the class carries no
    ``__dict__``, so the stray access §10.2 names finds nothing to read, and no
    attribute — public, private or shadow — can be attached or rebound on a
    held surface.  Its one slot holds **the answers, read out of the episode at
    construction and copied**: no episode, no question, no tree, no reveal set.
    A policy that walks everything reachable from the surface finds the values
    it was configured to receive and nothing else — and because no attribute
    here names an episode, there is no attribute walk that reaches one.

    **Every answer is a callable, because every answer on this surface is one.**
    §11's ``question.*`` interface is verb-shaped all the way down —
    ``observed()``, ``legal_actions()``, ``budget_remaining()`` — and a surface
    that answered a name with a bare value would be handing a policy a
    *different* interface from the one §11 specifies for the same name.  So the
    value read out of the episode at construction is served by a per-name
    accessor, and reading an answer is always ``surface.name()``.  The
    consequence is worth stating: the surface never answers an attribute read
    with live state, only with what was copied, which is the snapshot half of
    feature 223's "fresh" applied to the answers.

    What is *not* configured is refused with
    :class:`~policy_runtime.PolicyAnswerSurfaceError`, which is an
    :class:`AttributeError` as well as a
    :class:`~policy_runtime.PolicyRuntimeError`: a walk spelled ``getattr``,
    ``hasattr``, ``contextlib.suppress`` or a ``dir()``-driven loop terminates
    on the attribute protocol's own error, and a refusal that were not one
    would raise through a walk that had already decided the name was absent.
    """

    #: One slot, private: the answers, as a mapping of name to the value that
    #: name returned.  No ``__dict__`` beside it, and no slot naming an
    #: episode — so there is no shadow state a caller could attach, no
    #: dictionary a stray access could read, and nothing here that leads back
    #: to the object the answers were drawn from.
    __slots__ = ("_answers",)

    def __init__(self, answers: dict[str, Any]) -> None:
        # ``object.__setattr__`` rather than plain assignment, because
        # :meth:`__setattr__` refuses every name — the surface is frozen from
        # the moment it exists, and the constructor's own write is the one
        # write there is.
        object.__setattr__(self, "_answers", dict(answers))

    # -- the attribute protocol -------------------------------------------

    def __getattribute__(self, name: str) -> Any:
        """Answer a configured name, refuse every other — the feature's gate.

        The one place every spelling of an attribute read lands:
        ``surface.observed``, ``getattr(surface, "observed")``,
        ``getattr(surface, name, default)``, ``hasattr``, ``copy``,
        ``pickle``, and the ``dir()``-driven loop a policy would write to find
        what it can reach.  The checks are ordered by what the caller needs to
        hear:

        * the **forbidden pair** is refused first and names the law, so a
          policy that reached for ``best_so_far`` by name is told what it
          touched rather than merely that the name is absent.  The check is on
          the *bare* spelling as well as the dotted one, so both renderings
          the two features use are the same refusal;
        * **a configured name** is answered with the accessor closure
          :func:`_accessor` built for it at construction — the copied-out
          value, never the episode;
        * **every other name** — a private name (``_answers`` and every
          ``_``-prefixed spelling), a ``__dunder__`` the class does not define
          (``__dict__`` among them), an ordinary name the deployment did not
          admit — is refused with *one* sentence, so the object offers no way
          to tell a name that exists from one that does not.  That
          indistinguishability is not incidental: it is the property that makes
          the surface opaque rather than merely closed, and the reason a
          denylist of two names could not have been the design.

        ``__class__`` is the single exception, answered through
        :data:`_PROTOCOL_NAMES`: the interpreter's own protocol reaches for it
        and it resolves to the *class*, which carries no answer and no episode.
        A barrier that broke ``isinstance`` or ``repr`` would be refusing the
        interpreter rather than the policy.
        """
        if name in _FORBIDDEN:
            # Checked before every other rule so ``best_so_far`` — the bare
            # spelling §10.2 lists first — is refused as the law rather than as
            # an unconfigured name, whatever the deployment did.
            raise PolicyAnswerSurfaceError(_forbidden_message(name))
        if name in _PROTOCOL_NAMES:
            return object.__getattribute__(self, name)
        if name.startswith("_"):
            # Every private name, including ``_answers`` and every dunder the
            # class does not define (``__dict__`` among them).
            raise PolicyAnswerSurfaceError(_unlisted_message(name))
        answers = _answers_of(self)
        if name in answers:
            return _accessor(self, name, answers[name])
        raise PolicyAnswerSurfaceError(_unlisted_message(name))

    def __reduce__(self) -> Any:
        """Refuse copy and pickle — the surface is not a thing to reproduce.

        ``copy.copy``, ``copy.deepcopy`` and :mod:`pickle` are attribute-walk
        routes like any other: each asks the object for its own state and
        rebuilds an equivalent one, and a surface that answered would hand a
        caller a *second* surface it could then reshape — or, worse, would hand
        the machinery the answers by a route this gate never sees, since
        ``__reduce_ex__`` is resolved on the type and would bypass
        :meth:`__getattribute__` entirely.

        Refusing here rather than leaving the machinery to fail on its own is
        deliberate, and it is the same choice :class:`PolicySurface.__setattr__`
        makes: CPython's default reflex for an object it cannot reduce is a
        bare ``copy.Error`` or ``PicklingError`` — an unnamed failure in no
        vocabulary at all, which a caller catching this member's one base class
        would miss.  The law is better spoken in this member's own words, and
        the words are the read-side law: a surface is the answers *an episode*
        hands out, so reproducing it is the episode's act, not the policy's.
        """
        raise PolicyAnswerSurfaceError(
            "a policy surface cannot be copied or pickled: the surface is the "
            "set of answers an episode hands a policy, and reproducing it "
            "would hand a caller a second set to reshape and a route to the "
            "constituted answers this gate never sees (feature 224, docs "
            "§10.2). A surface is built once, over the episode that owns it — "
            "by policy_surface() — and read; a caller that wants one builds "
            "one"
        )

    def __copy__(self) -> Any:
        """Refuse ``copy.copy`` — see :meth:`__reduce__`."""
        return self.__reduce__()

    def __deepcopy__(self, memo: Any = None) -> Any:
        """Refuse ``copy.deepcopy`` — see :meth:`__reduce__`."""
        return self.__reduce__()

    def __reduce_ex__(self, protocol: int = 0) -> Any:
        """Refuse every pickle protocol — see :meth:`__reduce__`.

        Defined because :mod:`pickle` calls ``__reduce_ex__`` rather than
        ``__reduce__`` on a modern interpreter: leaving it to :class:`object`
        would let the default implementation run and raise a foreign
        :class:`pickle.PicklingError` from somewhere inside the machinery,
        which is the unnamed failure this member's vocabulary exists to avoid.
        """
        return self.__reduce__()

    def __setattr__(self, name: str, value: object) -> None:
        """Refuse every assignment — the surface cannot be extended or moved.

        Not just the configured names: *any* name, public, private or shadow,
        because a surface whose attributes could move would be a set of answers
        the policy could reshape — hand itself an answer it was not given, or
        attach state beside the admitted ones.  The refusal is
        :class:`~policy_runtime.PolicyAnswerSurfaceError`, so it is catchable
        as the same law from the other side, and the same boundary
        :class:`policy_runtime.PrefixView` and
        :class:`policy_runtime.EpisodeBeta` draw around their own values.
        """
        raise PolicyAnswerSurfaceError(
            f"a policy surface is the set of answers an episode hands a policy "
            f"and cannot be reassigned or extended (attempted "
            f"`surface.{name} = {value!r}`): a surface whose attributes moved "
            "would be a set of answers the policy shaped rather than received "
            "(feature 224, docs §10.2)"
        )

    def __delattr__(self, name: str) -> None:
        """Refuse deletion — there is nothing here to remove.

        The same law from the other side: ``del surface.observed`` reaching for
        an earned answer is the reassignment it is not allowed to make, and a
        surface with no removable attributes cannot be hollowed into a shape
        the configured set does not justify.
        """
        raise PolicyAnswerSurfaceError(
            f"a policy surface carries only the answers an episode configured "
            f"and nothing to delete (attempted `del surface.{name}`): the set "
            "is what the deployment admitted and cannot be reshaped after the "
            "fact (feature 224, docs §10.2)"
        )

    # -- the value semantics ----------------------------------------------

    def __eq__(self, other: object) -> bool:
        """Content equality — two surfaces over one answer set are one surface.

        Equality is the answers, so freshness never turns into identity: a
        replay handing a policy a new surface per round hands it an equal one
        whenever the answers have not moved, and a different one the moment
        they have.  A foreign type answers ``NotImplemented``, the honest
        reflex of a value that compares only with its own.

        The comparison reads the slot through :func:`_answers_of` rather than
        through the attribute protocol — a surface is never asked to *answer* a
        name in order to be compared, so the gate stays a gate and an equality
        test cannot become the one read that leaks.
        """
        if not isinstance(other, PolicySurface):
            return NotImplemented
        return _answers_of(self) == _answers_of(other)

    def __hash__(self) -> int:
        """The hash of the answer names — equal surfaces hash equally.

        Over the *names* rather than the values, because an answer may be a
        mapping (``observed()`` is one) and therefore unhashable, and a value
        that raised from ``__hash__`` would be a surface a replay could not key
        a ledger by.  The configuration is the identity that matters: two
        surfaces answering the same names are one posture.
        """
        return hash(tuple(sorted(_answers_of(self))))

    def __len__(self) -> int:
        """How many answers the surface offers — the configured set's size."""
        return len(_answers_of(self))

    def __contains__(self, name: object) -> bool:
        """Whether ``name`` is a configured answer — the membership ask.

        The read side of the law, spelled the way Python spells it: *"would
        this surface answer ``legal_actions``?"* is a question a deployment
        test or an operator audit should be able to ask without reading a
        refusal as an answer, and it is answered from the configured set rather
        than by attempting the read.  For the forbidden pair the answer is
        ``False`` for the same reason the name is absent from :meth:`__dir__`
        — it was never configured — and answering ``False`` here leaks nothing
        a walk would not have learned, since ``hasattr`` already answers
        ``False``.
        """
        return isinstance(name, str) and name in _answers_of(self)

    def __iter__(self) -> Any:
        """The configured answer names, in configuration order.

        Iteration is the read side rather than the gate: a policy looping over
        the surface walks the names it was handed, which is exactly what it is
        allowed to walk.  It is not a back door — every name yielded is one
        :meth:`__getattribute__` answers.
        """
        return iter(_answers_of(self))

    def __dir__(self) -> list[str]:
        """The configured answer names — so ``dir()`` circles back on itself.

        ``dir()`` is the spelling a policy uses to enumerate an object, and it
        is the one spelling a gate cannot refuse: the interpreter filters
        ``dir()``'s result through ``getattr`` with a default, so a name this
        surface does not answer would silently disappear anyway.  Answering the
        configured set directly makes the enumeration honest rather than
        incidental — a walk over ``dir(surface)`` reaches exactly the answers
        the deployment admitted, and every name it yields is a name
        :meth:`__getattribute__` answers.
        """
        return sorted(_answers_of(self))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"PolicySurface(answers={sorted(_answers_of(self))})"


#: The forbidden pair, as a set for the gate's hot path.  Read from
#: :data:`FORBIDDEN_ANSWERS` rather than restated, so "which answers §10.2
#: blocks" has one spelling in this module.
_FORBIDDEN: frozenset[str] = FORBIDDEN_ANSWERS

#: The private names the gate *forwards* to the class rather than refusing.
#: Two groups, and both are about the interpreter rather than the policy.
#:
#: ``__class__`` is the one name Python needs to treat the surface as an object
#: at all — ``isinstance``, ``type()``, ``repr``, a debugger — and it resolves
#: to :class:`PolicySurface` *the class*, which carries no answer and no
#: episode, so a walk to it reaches the law rather than the data.
#:
#: The four reduction dunders are here for the opposite reason: the copy and
#: pickle machinery does **not** go through :meth:`object.__getattribute__` for
#: them the way an ordinary attribute read does — it asks the *type* — but it
#: does look ``__reduce__`` up through *this* gate on the way to deciding the
#: object is unreducible, and an :class:`AttributeError` raised there is
#: swallowed by the machinery and replaced with a foreign
#: ``copy.Error``/``PicklingError``.  Forwarding them lets
#: :meth:`PolicySurface.__reduce__` speak the refusal in this member's own
#: vocabulary, which is the whole point of routing them: a caller catching
#: :class:`~policy_runtime.PolicyRuntimeError` must not be left holding an
#: unnamed failure because CPython got to the object first.  Every one of the
#: four raises rather than answering, so forwarding them widens nothing.
_PROTOCOL_NAMES: frozenset[str] = frozenset(
    {"__class__", "__copy__", "__deepcopy__", "__reduce__", "__reduce_ex__"}
)


def _forbidden_message(name: str) -> str:
    """The refusal for one of the two answers §10.2 blocks.

    Spelled once for both the gate and the configuration: a policy that reaches
    ``best_so_far`` and a deployment that tries to *configure* it are meeting
    one law, and the sentence they read is the same one.  It names the document
    and quotes the prd invariant the two names follow from, because the repair
    is not obvious from the refusal alone — a policy author who wanted
    ``best_so_far`` needs to know that what is offered instead is
    ``budget_remaining()``, and that the difference is the barrier itself.
    """
    bare = name.rsplit(".", 1)[-1]
    return (
        f"{name!r} is blocked: docs §10.2 names question.{bare} as one of the "
        f"two answers the policy runtime withholds from an exploration policy, "
        f"and it is not among the answers this surface was configured with "
        f"(feature 224). A policy learns how much statistical budget remains "
        f"— budget_remaining() — and never how much it has already spent, and "
        f"never how well its picks have scored: both are facts about the "
        f"episode rather than about the prefix it earned, and reading either "
        f"would be reading past the information barrier the exploration policy "
        f"is defined by (prd §12 invariant 3: 'prefix-only information. No "
        f"unrevealed scores…')"
    )


def _unlisted_message(name: str) -> str:
    """The refusal for a name the surface was not configured with.

    Deliberately *one* sentence for every such name — a private name, a dunder
    the class does not define, an ordinary name the deployment did not admit —
    because the surface must not answer, even by the shape of its refusal,
    whether the name it was asked for exists on anything.  A refusal that
    distinguished "blocked" from "absent" would be the denylist's failure mode
    arriving through the error message instead of through the walk.
    """
    return (
        f"{name!r} is not an answer this policy surface offers: the surface "
        f"carries the answers its episode was configured to hand out — "
        f"{', '.join(sorted(DEFAULT_ANSWERS))} by default — and nothing else, "
        f"so a name outside that set is not present in the object at all "
        f"rather than screened out of it (feature 224, docs §10.2). A policy "
        f"reads the prefix it has revealed, the frontier it may select from, "
        f"its remaining statistical budget and the structural metadata of its "
        f"cells; anything else it needs arrives as an argument the runtime "
        f"passes in, never by walking the surface"
    )


def _answers_of(surface: PolicySurface) -> dict[str, Any]:
    """The answers a surface holds — the one internal read of its slot.

    Spelled module-level, through :func:`object.__getattribute__`, rather than
    as a method: :meth:`PolicySurface.__getattribute__` is a gate that refuses
    every private name, so a method spelled ``self._answers()`` could not read
    its own slot through the attribute protocol — and must not, because a
    method that *were* reachable with the slot's name would be a back door a
    policy's attribute walk could follow one ``getattr(surface, ...)`` at a
    time.  The gate, the value semantics and the two computed answers all read
    the slot through this, so "the answers" has one spelling and the private
    name has one reader.
    """
    return object.__getattribute__(surface, "_answers")


def _answer_value(episode: Any, name: str) -> Any:
    """Read one configured answer out of the episode — **called, and copied**.

    The read happens **once, at construction**, and what is stored is the value
    the answer *produced*, never the attribute it came from.  That distinction
    is load-bearing rather than tidy, and this function is where the feature
    is won or lost:

    * §11's ``question.*`` interface is verb-shaped — ``observed()``,
      ``legal_actions()``, ``budget_remaining()`` — so an episode's answers are
      bound methods.  Storing the method would store a reference to the episode
      inside it (``method.__self__``), and a policy one attribute walk from the
      surface would be holding the very object this feature exists to stand in
      front of: ``surface.observed.__self__.best_so_far`` is the whole barrier
      gone.  So the callable is **called** and its result stored;
    * a result that is a mapping is copied, so a policy scribbling on what it
      read moves its own copy and not the episode's state — the
      ``PolicyQuestion.observed`` guarantee, kept one seam further out;
    * the call also *is* the snapshot.  An episode that reveals more after the
      surface was built answers the held surface nothing new, because what is
      held is the answers as they stood — feature 223's "fresh" half applied to
      the surface rather than to the view.

    A verb the surface cannot call with no arguments is refused rather than
    guessed at: an answer whose shape the deployment did not fix is one this
    member cannot hand a policy as a value, and inventing arguments for it
    would be the surface answering on the episode's behalf.

    An episode that does not answer a configured name at all is refused here
    rather than silently yielding ``None``: a surface that answered nothing for
    a configured name would be a surface a policy reads as "this episode has no
    budget", which is a wrong answer where the honest one is a refusal naming
    the name.  Every refusal here is
    :class:`~policy_runtime.PolicyAnswerSurfaceError` — the same class the gate
    raises — so "this name may not be an answer", "this name is not an answer"
    and "this episode cannot answer the name you configured" are one law read
    at three moments, and a caller catches the configuration's failure with the
    same ``except`` it catches the walk's.
    """
    try:
        value = getattr(episode, name)
    except AttributeError:
        raise PolicyAnswerSurfaceError(
            f"an episode was asked for the answer {name!r} — configured on its "
            f"policy surface — and answered nothing: the surface is built by "
            f"reading a configured answer's value out of the episode "
            f"(feature 224, docs §10.2), and an episode that does not answer a "
            f"name the deployment configured would hand a policy a surface "
            f"missing one of its answers"
        ) from None
    if callable(value):
        try:
            value = value()
        except TypeError:
            raise PolicyAnswerSurfaceError(
                f"the episode's answer {name!r} — configured on its policy "
                f"surface — is a callable the surface cannot read: §11's "
                f"question.* answers take no arguments, and the surface copies "
                f"an answer's *value* out of the episode at construction so "
                f"the held surface is a snapshot holding no reference back to "
                f"it (feature 224, docs §10.2). An answer that needs an "
                f"argument is one a policy receives as an argument, never by "
                f"walking the surface"
            ) from None
    if isinstance(value, dict):
        return dict(value)
    return value


def _empty_answer(name: str) -> Any:
    """The answer a bare surface gives for ``name`` — the defaults, and nothing.

    A runtime may compose a surface before it has an episode — a test, a policy
    handed its surface at construction, a deployment wiring its answer set
    ahead of the replay — and the honest answer then is the empty one rather
    than a refusal: a policy has revealed nothing, and holds no budget yet.
    The two defaults get the empty value *of their own kind* — ``{}`` for the
    prefix and ``0`` for the budget — because those are the two answers
    :data:`DEFAULT_ANSWERS` names and the shapes the member's own
    :class:`PolicySurface` answers them with when it computes them; a surface
    that gave the empty *mapping* for every name would hand a policy a budget
    it could not compare against a threshold.

    Any other configured name gets the same ``{}``, and deliberately: this
    member cannot know what shape a deployment's own answer takes, and an
    answer it invented would be the surface's own value standing in for the
    episode's — the drift this feature exists to prevent.  A deployment that
    configures an answer and hands over no episode is answered with the empty
    mapping and reads its own answer the moment it hands over the episode.
    """
    return {} if name != "budget_remaining" else 0


def _accessor(surface: PolicySurface, name: str, value: Any) -> Any:
    """The callable a configured name answers with — the surface's one verb.

    Every answer on this surface is a callable, because every answer on §11's
    ``question.*`` interface is one: ``observed()``, ``legal_actions()``,
    ``budget_remaining()``.  A surface that answered a name with a bare value
    would hand a policy a *different* interface from the one §11 specifies for
    the same name, and a policy written against one pool would break in the
    other — the identical-interface requirement feature 217 opens this member
    with, applied to the surface rather than to the question.

    The accessor closes over the **copied-out value**, never the episode, so
    calling it twice inside an episode that has moved on answers the snapshot
    both times — feature 223's snapshot half, applied to the answers.  A
    runtime that configures its own *reader* — a deployment that wants an
    answer recomputed per call from state it controls — is handed a callable
    whose result is returned unchanged, so its verb keeps its own meaning; but
    the value it returns is never stored, and the surface therefore never holds
    a reference into it (the leak :func:`_answer_value` documents).

    The mapping case is copied again per call: ``observed()`` returns a fresh
    dict each time, so a policy that writes into what it read moves its own
    copy and not the surface — reading is not revealing, and a mapping that
    moved on a read would be a set of answers the policy could shape without
    earning them.
    """
    if callable(value):

        def delegate() -> Any:
            result = value()
            return dict(result) if isinstance(result, dict) else result

        delegate.__name__ = name
        delegate.__qualname__ = f"PolicySurface.{name}"
        delegate.__doc__ = (
            f"The {name!r} answer this policy surface was configured with — a "
            f"reader the deployment supplied, consulted per call (feature 224, "
            f"docs §10.2). Its result is returned unchanged and never stored, "
            f"so the surface holds no reference into the object that produced "
            f"it; a mapping result is copied, so a policy that writes into what "
            f"it read moves its own copy and not the surface."
        )
        return delegate

    def answer() -> Any:
        return dict(value) if isinstance(value, dict) else value

    answer.__name__ = name
    answer.__qualname__ = f"PolicySurface.{name}"
    answer.__doc__ = (
        f"The {name!r} answer this policy surface was configured with — the "
        f"value read out of the episode at construction and copied, so a "
        f"surface answers the snapshot it was built over (feature 224, "
        f"docs §10.2). A fresh copy per call for a mapping, so a policy that "
        f"writes into what it read moves its own copy and not the surface."
    )
    return answer


def policy_surface(
    episode: Any = None,
    *,
    answers: Iterable[str] | None = None,
) -> PolicySurface:
    """Construct the answer surface an episode hands a policy — the verb.

    The one factory, and the whole of feature 224's construction: the
    configured answers are read out of ``episode`` and copied into a fresh
    :class:`PolicySurface`, and the returned object holds no reference to the
    episode — not under an attribute, not in a slot, not anywhere a policy
    could walk to. ::

        surface = policy_surface(replay_episode)
        batch = policy.select(surface)          # prefix-only, and closed

    ``answers`` is the configured set, and it defaults to
    :data:`DEFAULT_ANSWERS` — the two answers §11's ``question.*`` surface
    offers that are already prefix-only, so the posture a deployment gets
    without saying anything is the one that cannot leak.  A runtime with more
    to offer names it: ``policy_surface(episode, answers=("observed",
    "legal_actions", "budget_remaining"))``.  The set is *configuration* and
    not a constant in this module because §10.2 names two attributes as blocked
    and stops there — which answers a given episode offers is the deployment's
    to decide, and this member's job is to make the decision closed rather than
    to make it.

    Two refusals guard the configuration, and both are aimed at the way this
    feature is defeated rather than at a caller's convenience:

    * **a forbidden answer is refused.**  Configuring ``best_so_far`` or
      ``budget_spent`` — in either the bare or the ``question.``-prefixed
      spelling feature 224 and feature 225 each render — would ask this module
      to build the very surface the feature forbids, and a deployment can do
      that by accident (a banned-name list arriving from the armed guard as a
      list of answers).  Refusing it here means the law is enforced by the
      construction rather than by the deployment's care;
    * **a private name is refused.**  ``_answers``, ``__class__`` and their
      kind name the surface's own machinery rather than an answer, and a
      configured name that landed on them would put a policy's read on the
      object that holds the gate — the one place the gate cannot defend.

    Both are refused with :class:`~policy_runtime.PolicyAnswerSurfaceError`,
    the same class the gate raises, so "this name may not be an answer" and
    "this name is not an answer" are one law read at two moments.

    ``episode`` is optional, and the bare form is not a degraded one: with no
    episode the surface answers the pair of defaults as empty prefix data —
    ``{}`` and ``0`` — which is the honest answer for a runtime that has not
    opened an episode yet and the object a test can hand a policy without
    constructing a world.  With an episode, every configured answer is read
    out of it once (see :func:`_answer_value`), so the surface is a *snapshot*:
    an episode that reveals more afterwards does not change what a held surface
    answers.

    Pure otherwise: no store, no clock, no configuration beyond the arguments,
    and no interpreter state — the refusal is structural and holds whether or
    not an episode is running, which is why 224 needs neither feature 225's
    extent nor feature 223's question to be in force.
    """
    if answers is None:
        configured = list(DEFAULT_ANSWERS)
    else:
        configured = list(answers)
    for name in configured:
        if not isinstance(name, str) or not name:
            raise PolicyAnswerSurfaceError(
                f"a policy surface is configured with answer names — got "
                f"{name!r} ({type(name).__name__}); the surface answers the "
                f"names an episode's configuration admits, and a value that is "
                f"not a non-empty string names no answer a policy could read "
                f"(feature 224, docs §10.2)"
            )
        if name.startswith("_"):
            raise PolicyAnswerSurfaceError(
                f"a policy surface cannot be configured with the private name "
                f"{name!r}: the surface's own machinery — the slot that holds "
                f"the copied-out answers and the gate that refuses everything "
                f"else — is not an answer, and a name that landed on it would "
                f"put a policy's read on the one object the gate cannot defend "
                f"(feature 224, docs §10.2)"
            )
        if name in FORBIDDEN_ANSWERS or name.rsplit(".", 1)[-1] in FORBIDDEN_ANSWERS:
            raise PolicyAnswerSurfaceError(_forbidden_message(name))
    values: dict[str, Any] = {}
    for name in configured:
        values[name] = (
            _empty_answer(name) if episode is None else _answer_value(episode, name)
        )
    return PolicySurface(values)
