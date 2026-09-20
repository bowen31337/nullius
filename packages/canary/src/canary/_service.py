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

from ._containers import (
    PinnedContainers,
    pin_containers,
    pinned_containers_from_env,
)

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
