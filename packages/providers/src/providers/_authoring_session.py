"""The authoring session — one budgeted provider per pinned model.

additions_spec_llm_authoring.xml, "Authoring Foundation", feature 3: *System
creates one budgeted provider per pinned model for authoring calls with
``providers.AuthoringSession(config, resolve)``, and ``provider_for(role, *,
campaign_id, node_id)`` answers ``(provider, pin)``.  ``resolve`` is a callable
``pin -> Provider``, such as the "live-providers" resolver.*

Feature 2 gave the deployment a file it states its authoring models in and a
:class:`~providers.AuthoringConfig` those models parse into; feature 4 will
give the records those calls leave behind a store.  Between the two sits the
question this module answers: *which provider answers a given call, and on
whose budget?*  Architecture §14.1's role table names three call sites — the
rotated frontier tier that authors roots, the one cheap model that authors
everything deeper, and the policy reviser — and each is a *pinned model* rather
than a provider, so the session's job is to turn a role and a node into a pin
and then into a live provider.

One provider per pin, one budget per provider
---------------------------------------------

A session resolves each pin **once** and wraps the answer in a
:class:`~providers.BudgetedProvider` carrying the config's two ceilings, so
every call to that pin in the session draws on one running budget rather than
one budget per call.  That is the whole reason the session exists as an object
rather than as a pair of free functions: the ceilings feature 2 states are
*per-pin budgets a campaign spends down*, and a caller that re-resolved the pin
on every node would hand each call a fresh, unspent budget — the ceiling would
bound a single answer and never a campaign, which is the opposite of what a
budget is for.  The wrapping happens at :meth:`AuthoringSession.provider_for`
time, lazily, the first time a pin is asked for; the cache means the second
call to the same pin answers the same object, already partially spent.

The pin is the cache key
------------------------

Providers are keyed by the **pin**, not by the role: ``config.depth`` and
``config.policy`` are frequently the same model, and a deployment that named
one model for both roles is one budget, not two.  Keying by role would let two
roles spend the same ceiling twice, which is the §14.1 silent-budget-split this
feature exists to prevent.  :meth:`AuthoringSession.providers` exposes the
resolved map for a caller that wants to read what has been spent.

The rotation, reused rather than re-derived
-------------------------------------------

``role == "root"`` answers the pin the campaign's rotation assigned this root:
``root_tier[rotation_index(campaign_id, node_id, tier)]`` over the
:class:`~providers.FrontierTier` built from the config's ``root_tier``.  This
is deliberately the *same* decision :class:`~providers.RootRotation` records —
the rotation's own arithmetic and the rotation's own tier derivation
(``config.tier``, feature 2's one spelling) — so a root authored through this
session is served by the family the rotation assigned it, and feature 4's
recorder never meets an :class:`~providers.UnassignedRootProviderError`: the
provider the call reports serving and the family the rotation assigned are one
value by construction, not by a caller remembering to look.

The two ids are passed straight to :func:`providers.rotation_index`, which
canonicalizes them through :class:`uuid.UUID` and refuses a value that is not
one — so a root pin asked for under a malformed node id is refused *there*, in
the rotation's own vocabulary, rather than being guessed at here.  The pin is
the only thing this module reads the index for; the tier's size is the whole of
the decision.

The roles, and the one refusal
------------------------------

:data:`~providers.AUTHORING_ROLES` is the closed set — ``root``, ``depth``,
``policy`` — and this module routes on it.  ``root`` rotates, ``depth`` answers
``config.depth`` and ``policy`` answers ``config.policy``; any other role is
:class:`~providers.AuthoringConfigError` naming it, because a role outside the
three is a call site nobody declared and whose model nobody pinned.  The
refusal is feature 2's own type and code word rather than a new one: *which
model serves this role* is a question about the authoring configuration, and a
role the config has no pin for is exactly the config being wrong.

``role_for_depth`` and the root boundary
----------------------------------------

:func:`providers.role_for_depth(child_depth)` answers ``"root"`` when
``child_depth <= ROOT_TIER_MAX_DEPTH`` and ``"depth"`` otherwise — the §14.1
boundary feature 7's author reads off a child's depth to choose a role, stated
once here so the author and this session agree about where the frontier tier
stops.  It is a free function rather than a method because it is a rule about
the tree, not about a deployment's configuration: one campaign's declared tier
does not change where depth 1 ends.

It reads :data:`~providers.ROOT_TIER_MAX_DEPTH` rather than a private copy, so
the boundary this rule states and the boundary feature 196 refuses a root call
past are one number; and it guards its argument the way the tree's own records
do — a bool is refused beside the integers, because ``True`` is an ``int`` in
Python and a depth of ``True`` is a depth of nobody.

Stdlib-only, like the rest of this tree: the session holds a config, a
resolver and a dict of providers, and imports nothing outside this package.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from ._authoring import AUTHORING_ROLES, AuthoringConfig, AuthoringConfigError
from ._budget import BudgetedProvider
from ._pinning import ModelPin
from ._provider import Provider
from ._root import ROOT_TIER_MAX_DEPTH
from ._rotation import rotation_index
from ._usage_store import UsageRecordingProvider, UsageStore

__all__ = ["AuthoringSession", "role_for_depth"]

#: The roles this session routes, by name rather than by index into
#: :data:`providers.AUTHORING_ROLES`: the spec's sentence routes on the two
#: non-rotating roles (*"role depth: the depth pin.  role policy: the policy
#: pin."*) and feature 7 reads ``role_for_depth``'s answer to pick the third,
#: so the three spellings live in one place — this module — and the closed set
#: is feature 2's own tuple rather than a second declaration that could drift
#: from it.
ROOT_ROLE: Final[str] = AUTHORING_ROLES[0]
DEPTH_ROLE: Final[str] = AUTHORING_ROLES[1]
POLICY_ROLE: Final[str] = AUTHORING_ROLES[2]


def role_for_depth(child_depth: object) -> str:
    """The authoring role a child at ``child_depth`` is authored by — the §14.1 split.

    ``"root"`` for a child at or above :data:`providers.ROOT_TIER_MAX_DEPTH`,
    ``"depth"`` for everything deeper: §14.1's role table puts roots at depths
    0–1 on the rotated frontier tier and everything below on the one cheap
    model, and this is that boundary as one comparison.  Feature 7's author
    reads it off a workspace's ``depth + 1`` to choose between the two pins, so
    the rule lives here, beside the session that owns the pins, rather than
    being re-derived by each caller.

    ``<=`` rather than ``<`` because ``child_depth`` is the **child's** depth,
    not the parent's: a child at depth 1 is still a root by §14.1's row
    (*"roots (depth 0–1)"*), and the first child that is not a root is the one
    at depth 2 — the value feature 198's own gate refuses as a root call.

    The argument is guarded, not assumed: a bool is refused beside the
    integers (``True`` is an ``int`` in Python, and a depth of ``True`` must
    not be silently read as depth 1), and so is anything that is not an
    integer at all — a depth that is not a number names no row of the tree and
    no comparison with the boundary.  The refusal is
    :class:`~providers.AuthoringConfigError`, the same vocabulary feature 2's
    record uses for a malformed depth, because this is a question about which
    authoring role a node falls in and the answer is config-level.
    """
    if isinstance(child_depth, bool) or not isinstance(child_depth, int):
        raise AuthoringConfigError(
            f"role_for_depth needs an int depth, got {child_depth!r} "
            f"({type(child_depth).__name__}). The role a child is authored by "
            f"is read off its depth against architecture §14.1's root boundary "
            f"({ROOT_TIER_MAX_DEPTH}), and a value that is not a depth cannot "
            f"be compared with it — including a bool, which Python would "
            f"otherwise read as 0 or 1 and answer a role for a depth nobody "
            f"stated."
        )
    if child_depth < 0:
        raise AuthoringConfigError(
            f"role_for_depth needs a non-negative depth, got {child_depth}. "
            f"Depth zero is a root and there is no shallower node, so a "
            f"negative depth names no role in the tree."
        )
    return ROOT_ROLE if child_depth <= ROOT_TIER_MAX_DEPTH else DEPTH_ROLE


@dataclass(frozen=True)
class _EffortPin:
    """A pin that also states the authoring config's ``effort``, for one resolve call.

    The resolver a session is built over is a ``pin -> Provider`` callable of
    exactly one argument — the composed application's own
    ``LiveProviderResolver.resolve`` is that shape, and widening it is outside
    this module's reach.  So the config's ``effort`` is threaded through the
    *pin* instead: this stand-in carries the same three parts
    :func:`providers._live.live_provider` dispatches on (read, like a real
    pin, on plain attributes), plus ``effort``, which that registry's
    :func:`providers._live._pin_effort` reads and a plain
    :class:`~providers.ModelPin` simply does not have.  Built fresh per
    :meth:`AuthoringSession._bind` call rather than carried on the pin itself,
    so :class:`~providers.ModelPin` stays the three-part triple every other
    reader of a pin already knows.
    """

    provider: str
    model: str
    version: str
    effort: str | None


class AuthoringSession:
    """One provider per pinned model, each on one budget, for a session's calls.

    Built from feature 2's :class:`~providers.AuthoringConfig` and a resolver —
    a callable ``pin -> Provider``, such as the composed application's
    ``live-providers`` resolver — and asked, per call, for the ``(provider,
    pin)`` a role serves.  Every pin it resolves is wrapped once in a
    :class:`~providers.BudgetedProvider` with the config's ceilings and cached,
    so the session is the object that holds a campaign's authoring spend.

    The session does no I/O of its own and reads no environment: the resolver
    it is handed owns *how* a pin becomes a provider (the live registry reads
    credentials at resolve time; a test's fake counts calls), and this class
    only decides *which pin* a role is served by and *how often* each is
    resolved.  So a session built over a fake resolver makes feature 7's suite
    runnable with no network and no credential, which is the constraint this
    addition states in as many words.
    """

    def __init__(
        self,
        config: AuthoringConfig,
        resolve: Callable[[ModelPin], Provider],
        usage_store: UsageStore | None = None,
    ) -> None:
        # The config is held, not copied: it is frozen and value-equal, so a
        # caller keeping a reference cannot change what this session routes.
        # The resolver is held as given and called lazily — resolving at
        # construction would make building a session read every credential the
        # deployment has, which is exactly the composition-time credential read
        # the live resolver's own docstring refuses.
        if not isinstance(config, AuthoringConfig):
            raise AuthoringConfigError(
                f"an AuthoringSession must be built over an AuthoringConfig, "
                f"got {config!r} ({type(config).__name__}). The session binds "
                f"this deployment's authoring pins and enforces the budget "
                f"ceilings it states — a value that is not that config bounds "
                f"nothing and names no pin."
            )
        if not callable(resolve):
            raise AuthoringConfigError(
                f"an AuthoringSession needs a resolver callable "
                f"pin -> Provider, got {resolve!r} ({type(resolve).__name__}). "
                f"The resolver is how a pinned model becomes a live provider "
                f"(the composed application's 'live-providers' component is "
                f"one), and a value that is not callable can turn no pin into "
                f"a provider."
            )
        self._config = config
        self._resolve = resolve
        # Optional, and held as given: when absent, provider_for's return is
        # byte-identical to a session with no usage tracking at all (see
        # provider_for below). When given, it is never touched by this class
        # except to bind it to the UsageRecordingProvider provider_for hands
        # back — the store's own behaviour (pricing, schema, swallowing its
        # own write failures) is entirely UsageRecordingProvider's concern.
        self._usage_store = usage_store
        # The pins by their (provider, model) member key, so a family the
        # rotation picks out of the canonical tier resolves back to the pin the
        # config declared.  Built once from the config's own ``root_tier``,
        # which feature 2 guarantees declares each provider at most once.
        self._pins_by_member = {
            (pin.provider, pin.model): pin for pin in config.root_tier
        }
        # Keyed by the pin, so two roles naming one model share one budget —
        # the §14.1 split a role key would reintroduce.
        self._providers: dict[ModelPin, BudgetedProvider] = {}

    @property
    def config(self) -> AuthoringConfig:
        """The configuration this session binds — the pins and ceilings it holds."""
        return self._config

    @property
    def providers(self) -> dict[ModelPin, BudgetedProvider]:
        """The providers resolved so far, keyed by the pin that serves them.

        A fresh mapping each call, so a reader cannot mutate the session's
        cache by keeping a reference.  Empty until the first
        :meth:`provider_for`, because resolution is lazy.
        """
        return dict(self._providers)

    def _pin_for(
        self, role: str, campaign_id: object, node_id: object
    ) -> ModelPin:
        """The pin that serves ``role`` for this campaign and node.

        The routing itself, separated from the resolution so a caller — or a
        test — can ask *which model* without triggering a provider to be
        built.  Root rotates through feature 197's arithmetic over the
        config's derived tier; depth and policy answer their one pin; anything
        else is feature 2's refusal naming the role.
        """
        if role == ROOT_ROLE:
            # The rotator's own arithmetic, over feature 2's own derivation of
            # the tier — so the family chosen here and the family feature 4
            # records are the same decision, not two that happen to agree.
            # rotation_index canonicalizes the ids and refuses a malformed
            # one in its own vocabulary; a bad node id is refused there.
            #
            # The index is applied to the **tier's** members rather than to
            # ``root_tier`` as the file happened to list them: FrontierTier
            # canonicalises its members into sorted order and
            # RootRotation.assign draws ``declared.providers[index]`` from that
            # canonical order, so indexing the file order would pick a
            # different family than the one the rotation records whenever the
            # file listed its pins out of order — and feature 4's recorder
            # would meet UnassignedRootProviderError, the exact failure this
            # routing exists to prevent.  The pin is recovered from the member
            # by (provider, model), unique because feature 2 refuses a
            # duplicate provider in the tier.
            index = rotation_index(campaign_id, node_id, self._config.tier)
            member = self._config.tier.providers[index]
            return self._pins_by_member[(member.provider, member.model)]
        if role == DEPTH_ROLE:
            return self._config.depth
        if role == POLICY_ROLE:
            return self._config.policy
        raise AuthoringConfigError(
            f"role {role!r} is not one of the authoring roles "
            f"{list(AUTHORING_ROLES)}. Architecture §14.1 draws three call "
            f"sites — the rotated frontier tier that authors roots, the depth "
            f"tier below it, and the policy reviser — and this session routes "
            f"exactly those; a role outside the set names a call site nobody "
            f"declared and a model nobody pinned, which is this deployment's "
            f"authoring configuration being wrong rather than a call to make."
        )

    def provider_for(
        self, role: str, *, campaign_id: object, node_id: object
    ) -> tuple[Provider, ModelPin]:
        """The provider and pin that serve ``role`` for this campaign and node.

        Answers a ``(provider, pin)`` pair: the pin names the model (feature
        7's caller carries it into the :class:`~providers.AuthoringRecord`),
        and the provider is a :class:`~providers.BudgetedProvider` over that
        pin, resolved once per session and cached — so the same pin asked for
        twice answers the same, partially-spent object, and a campaign's calls
        draw down one budget per model.

        ``campaign_id`` and ``node_id`` are required for every role even where
        only the root rotation reads them, because feature 7's caller has both
        at every call site and a signature that sometimes omitted them would
        be two call shapes for one question.  They are used only by the root
        rotation; that is stated here rather than left for the caller to infer.

        When this session was built with a ``usage_store``, the cached
        :class:`~providers.BudgetedProvider` is wrapped, fresh on *this* call,
        in a :class:`~providers._usage_store.UsageRecordingProvider` bound to
        this call's ``campaign_id``, ``node_id``, ``role`` and ``pin`` — so the
        cached object underneath (and the budget it keeps) is unaffected, and
        two calls for the same pin under two different nodes each get a
        recorder bound to their own attribution rather than sharing one. The
        recorder sits *outside* the budget wrapper: a call the budget refuses
        still reaches the recorder's ``except`` clause and is recorded as
        ``refused_budget``, with the budget's own totals and ceilings
        untouched by the recording. With no store configured, this answers
        the cached provider unwrapped — byte-identical to a session built
        before this feature existed.
        """
        pin = self._pin_for(role, campaign_id, node_id)
        provider = self._providers.get(pin)
        if provider is None:
            provider = self._bind(pin)
            self._providers[pin] = provider
        if self._usage_store is None:
            return provider, pin
        return (
            UsageRecordingProvider(
                provider,
                store=self._usage_store,
                campaign_id=campaign_id,
                node_id=node_id,
                role=role,
                pin=pin,
            ),
            pin,
        )

    def _bind(self, pin: ModelPin) -> BudgetedProvider:
        """Resolve ``pin`` once and wrap it in this session's budget.

        The one place a pin meets the resolver, and the one place a
        :class:`~providers.BudgetedProvider` is built.  The ceilings come from
        the config, so every pin in one session is bounded by one deployment's
        statement; the resolver's refusals (a missing credential, a vendor with
        no backend) propagate unchanged, because they name the variable an
        operator acts on and re-wrapping them here would put a vaguer sentence
        in front of it.

        When the config names no ``effort`` the resolver sees ``pin`` exactly
        as handed in — unchanged, for the resolver and for every existing
        caller of this session.  When it does, the resolver sees a
        :class:`_EffortPin` carrying it instead, so the live registry can
        thread the configured effort into :class:`~providers._anthropic.AnthropicProvider`
        without this session's resolver contract (``pin -> Provider``, one
        argument) ever changing — see :class:`_EffortPin` for why the pin,
        and not the call, is where that value rides along.
        """
        effort = self._config.effort
        resolved_pin = (
            pin
            if effort is None
            else _EffortPin(
                provider=pin.provider,
                model=pin.model,
                version=pin.version,
                effort=effort,
            )
        )
        inner = self._resolve(resolved_pin)
        return BudgetedProvider(
            inner,
            max_input_tokens=self._config.max_input_tokens,
            max_output_tokens=self._config.max_output_tokens,
        )
