"""The canary service: resolve the deployment's pins, refuse everything else.

Feature 135's sentence has a subject the size of a deployment — *every
evaluation container* — and this service is where that subject is read
off the environment and held to the contract. The vocabulary lives in
``_image`` and the sweep in ``_containers``; a caller that had to wire
the two together at every call site would eventually wire them
differently at one of them, and the whole point of a nightly assertion
is that there is exactly one answer to "is this deployment pinned?".

**Nothing is resolved at construction, and that is load-bearing.** The
factory builds every registered component on every ``create_app()`` —
in a bare test process, in a factory scan, and on paths that have no
evaluation containers to pin at all. So the component builder must
construct this service without a complete environment: an eager
resolution that refused an unset ``NULLIUS_EVALUATOR_IMAGE`` would take
down composition for every unrelated feature in the workspace, which is
precisely the coupling the one-way factory dependency exists to prevent.
The refusal still happens — it is the feature — but it happens where it
is informative: at the first call that actually asks whether the
deployment is pinned, naming the deployment's own misconfiguration
rather than looking like a composition fault. :meth:`from_env` keeps
the strict spelling for the caller who wants the check at construction
time: a nightly runner's entrypoint, a health check, the moment before
dreaming is allowed to continue.

**The environment mapping is the single seam.** Both the explicit
``images`` declaration and the environment read through the same
``env`` the service was constructed with, so a test that hands a
service a mapping gets that mapping for both — a service that read one
source from the mapping and the other from the process would be the
kind of half-redirected seam that passes alone and fails in a suite.
An explicit ``images`` mapping wins over the environment when both are
present, mirroring the evaluator service's explicit image: a caller
that spells the declaration is testing that spelling, not the shell it
happened to run under.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Optional

from ._allowlist import ImportAllowlist, allowlist_from_env
from ._containers import (
    PinnedContainers,
    pin_containers,
    pinned_containers_from_env,
)
from ._device import DevicePaths, reject_gpus_from_env
from ._inference import ModelInference
from ._replay import CanaryReplay
from ._reproducibility import BitReproducibility

__all__ = ["CanaryService", "build_canary_service"]


class CanaryService:
    """Resolves and asserts the deployment's pinned evaluation containers.

    Bound to an image declaration — a role → reference mapping — or to
    an environment it reads :data:`~canary.IMAGE_ENV_VARS` from. Both
    may be *absent* at construction (see the module docstring for why
    the composed component must be buildable without them) and are
    resolved on first use instead, through :attr:`containers`, which is
    the feature's verb: it returns the :class:`~canary.PinnedContainers`
    the declaration resolves to, or raises
    :class:`~canary.CanaryImageError` naming every container that is
    not pinned by digest.
    """

    def __init__(
        self,
        images: Optional[Mapping[str, str]] = None,
        *,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        # An explicit declaration is swept here (a pure parse, no
        # registry is consulted), so a tag-only reference handed in by
        # a caller fails at the call site that made the mistake — the
        # same stance the evaluator service takes for its explicit
        # image. A declaration left to the environment is swept on
        # first use instead, so composition never depends on one.
        self._pins: Optional[PinnedContainers] = (
            None if images is None else pin_containers(images)
        )
        self._devices: Optional[DevicePaths] = None
        self._allowlist: Optional[ImportAllowlist] = None
        self._env = env

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        *,
        images: Optional[Mapping[str, str]] = None,
        strict: bool = False,
    ) -> "CanaryService":
        """Construct the service, optionally insisting the pins resolve.

        With ``strict=False`` (the default) this is the component
        builder's shape: the service is built from whatever the
        environment provides and defers the sweep to first use, so
        composition never fails on this member's configuration (see the
        module docstring).

        With ``strict=True`` the declaration must resolve now: an
        unset, blank or tag-only reference behind any variable in
        :data:`~canary.IMAGE_ENV_VARS` is refused here, at construction,
        with the reason — the spelling for a nightly runner's
        entrypoint or a health check, a caller that wants to learn at
        startup that its evaluation path is unpinned rather than at the
        first sweep that matters.
        """
        source = os.environ if env is None else env
        service = cls(images, env=source)
        if strict:
            # Touch the lazily-resolved sweep so the refusal lands here.
            service.containers  # noqa: B018 - the property raises; that is the point
        return service

    # -- The category's other assertions ------------------------------------

    @property
    def reproducibility(self) -> BitReproducibility:
        """Feature 145's bit-identity check, carried beside the pin sweep.

        A stateless facade — constructed per access, holding nothing — so the
        composed canary component exposes the whole category's assertions
        from one value, the way the tripwires member's probe and the
        evaluator's service expose theirs. Deliberately *not* a lazy or
        strict-lazily-resolved property like :attr:`containers`: this check
        reads no environment and can refuse nothing, so there is nothing to
        defer and no misconfiguration for a construction to discover. A
        caller comparing two runs does not have to hold a *pinned*
        deployment to do it, and a deployment whose pins are unset is still
        perfectly able to learn that its bytes diverged.
        """
        return BitReproducibility()

    @property
    def replay(self) -> "CanaryReplay":
        """Feature 142's nightly replay, carried beside the pin sweep.

        A stateless facade — constructed per access, holding nothing — so the
        composed canary component exposes the whole category's assertions from
        one value, the way the tripwires member's probe and the evaluator's
        service expose theirs.  Deliberately *not* a lazy or
        strict-lazily-resolved property like :attr:`containers`: the replay is a
        pure function of the frozen pair it is handed, reads no environment and
        can refuse nothing about the deployment, so there is nothing to defer and
        no misconfiguration for a construction to discover.  A caller replaying a
        frozen pair does not have to hold a *pinned* deployment to do it, and a
        deployment whose pins are unset is still perfectly able to replay the
        pair it froze.
        """
        return CanaryReplay()

    @property
    def inference(self) -> "ModelInference":
        """Feature 146's inference refusal, carried beside the replay it guards.

        A stateless facade — constructed per access, holding nothing — so the
        composed canary component exposes the category's guard from the same
        value it exposes the replay, the way :attr:`replay` and
        :attr:`reproducibility` expose theirs. Deliberately *not* a lazy or
        strict-lazily-resolved property like :attr:`containers` and
        :attr:`devices`: the refusal reads no environment and can refuse
        nothing at construction — it is a fact about where a *call* sits, and
        the refusal lands on the call itself, in ``inference.call``, when that
        call is made from inside a replay. Nothing to resolve, nothing a
        deployment could misset, and no misconfiguration for a construction
        to discover.

        The replay this service carries at :attr:`replay` already runs under
        the guard (feature 142's ``replay_pair`` enters the replay path's
        dynamic extent around its whole computation), so this surface is the
        *other* half of feature 146: the seam a learned component calls a
        model through, discoverable from the composed application rather
        than only by import — a refusal the factory's scan cannot see is a
        refusal a future member would route around.
        """
        return ModelInference()

    # -- What this service is bound to --------------------------------------

    @property
    def containers(self) -> PinnedContainers:
        """The deployment's pinned evaluation containers — the sweep.

        The explicit declaration when the constructor was given one;
        otherwise :data:`~canary.IMAGE_ENV_VARS` resolved from the
        environment the service was constructed with. Raises
        :class:`~canary.CanaryImageError` when any declared container
        is unset or not pinned by digest — a tag is a mutable pointer
        and cannot serve as a pin (see ``_image`` and ``_containers``).
        Resolved once and cached: a deployment that re-reads its pins
        mid-run could observe two different truths about the same
        night, and the second read would say nothing about the first.
        """
        if self._pins is None:
            self._pins = pinned_containers_from_env(self._environment())
        return self._pins

    @property
    def devices(self) -> DevicePaths:
        """The eval and replay paths, swept and found GPU-free — feature 140.

        :data:`~canary.DEVICE_ENV_VARS` resolved from the environment the
        service was constructed with: each path's variable names the device
        that path runs on, and the sweep refuses a GPU (or an unrecognized
        device) in either, naming the path, the variable and the value. An
        unset or blank variable is the CPU — the contract's desired state,
        reached by declaring nothing — so it is recorded as the CPU rather
        than refused. Resolved once and cached: a deployment that re-read its
        device state mid-run could observe two different truths about the same
        night, and the second read would say nothing about the first.

        Deliberately lazy, like :attr:`containers` and unlike
        :attr:`reproducibility`: the device sweep reads the environment, so it
        can refuse, and the refusal names the deployment's own misconfiguration
        rather than taking composition down — the factory builds this component
        on every ``create_app()``, in a bare test process and on paths with no
        GPU to guard. The refusal lands at the first call that asks whether the
        deployment is GPU-free, where it is informative.
        """
        if self._devices is None:
            self._devices = reject_gpus_from_env(self._environment())
        return self._devices

    @property
    def allowlist(self) -> ImportAllowlist:
        """The searched-code import allowlist — feature 139's ceiling.

        :data:`~canary.IMPORT_ALLOWLIST_ENV` resolved from the environment
        the service was constructed with: the dotted module terms searched
        code may import, defaulting to the deterministic stdlib working set
        when the deployment declared nothing. A configured allowlist that
        tries to admit a term the determinism floor refuses — ``time``, a
        ``datetime`` clock constructor, an unseeded ``random`` spelling —
        is refused here, naming the variable and every offending term,
        because the allowlist is the mechanism §12's "No wall clock in
        searched code" row is enforced through, not a way around it. The
        floor itself is applied per submission, in
        ``allowlist.screen(source)``, which is the seam a searched module
        is screened at. Resolved once and cached, like :attr:`containers`
        and :attr:`devices`: a deployment that re-read its allowlist
        mid-run could screen two submissions under two different ceilings
        and never know which one spoke.

        Deliberately lazy, exactly like the device sweep: the resolution
        reads the environment and can refuse, and the refusal names the
        deployment's own misconfiguration rather than taking composition
        down — the factory builds this component on every
        ``create_app()``, in a bare test process and on paths with no
        searched code to screen. The refusal lands at the first call that
        asks for the ceiling, where it is informative.
        """
        if self._allowlist is None:
            self._allowlist = allowlist_from_env(self._environment())
        return self._allowlist

    def _environment(self) -> Mapping[str, str]:
        """The environment mapping this service resolves against.

        The ``env`` the service was constructed with, or the process
        environment when it was given none. The explicit-declaration
        path does not read through here (it was swept at construction),
        so the seam governs exactly the resolution that is left — the
        environment's — and a test that hands a service a mapping gets
        that mapping for the whole resolution.
        """
        return os.environ if self._env is None else self._env

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        state = "unresolved" if self._pins is None else repr(self._pins.roles)
        return f"CanaryService(containers={state})"


def build_canary_service(
    env: Optional[Mapping[str, str]] = None,
    *,
    images: Optional[Mapping[str, str]] = None,
) -> CanaryService:
    """Build the service the composed application carries.

    The one-shot convenience the component builder uses, kept beside the
    class so a test and the factory construct it the same way. Deliberately
    *not* strict: the factory builds this component on every
    ``create_app()``, so it must succeed without a pinned environment and
    refuse later, where the refusal is informative (see the module
    docstring). A caller that wants the check at construction uses
    ``CanaryService.from_env(strict=True)`` — this function is the
    composition spelling, not the operator's. A refused declaration is
    not papered over either way: :class:`~canary.CanaryImageError` is
    the only failure this member has, and it propagates to the caller
    that asked for the sweep — never to the factory that merely built
    the component.
    """
    return CanaryService.from_env(env, images=images)
