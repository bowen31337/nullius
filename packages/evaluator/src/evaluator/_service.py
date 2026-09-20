"""The evaluator service: resolve one identity and persist it.

Feature 70's sentence has two verbs — *computes* and *persists* — and this
service is where they are joined. The formula lives in ``_identity``, the
row in ``_store``; a caller that had to wire the two together at every call
site would eventually wire them together differently at one of them, and the
whole point of a provenance hash is that there is exactly one answer to
"which evaluator is this?".

**Everything resolves lazily, and that is load-bearing.** The factory builds
every registered component on every ``create_app()`` — in any environment,
including a bare test process, a factory scan, and the replay path, which
architecture §1 forbids from reaching the evaluator at all ("Replay must
never invoke the evaluator"). So the component builder must not need a
pinned image or a database to *construct* the service: an eager
``from_env`` that refused an unset ``NULLIUS_EVALUATOR_IMAGE`` would take
down composition for every unrelated feature in the workspace, which is
precisely the coupling the one-way factory dependency exists to prevent.

The refusal still happens — it is the feature (see ``_image``; canary
feature 135 states it independently as "rejects a tag-only reference") — but
it happens where it is informative: at the first call that actually needs
the image, naming the deployment's own misconfiguration rather than looking
like a data-path fault. A service constructed with no image is therefore a
perfectly good object; it simply cannot answer :meth:`identity` until it is
told what image it is evaluating with. :meth:`from_env` keeps the strict
spelling for the caller who wants the check at construction time.

**Recording is idempotent by design.** :meth:`record` computes the identity
and persists it; a second call in the same process, or the first call in the
next hundred processes of a deployment, writes the same row and finds it
already there. That is what makes it safe to call on the evaluation path
without a "have I done this already?" branch — the store's assign-once rule
(``_store``) turns the retry into a no-op while still refusing a genuine
contradiction.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Optional

from ._compare import ProvenanceCheck, check_comparable
from ._config import EvaluatorConfig
from ._errors import EvaluatorImageError, EvaluatorProvenanceError, EvaluatorStoreError
from ._identity import EvaluatorIdentity, evaluator_identity
from ._image import ImageRef, coerce_image_ref, parse_image_ref
from ._store import EvaluatorIdentityStore

__all__ = ["ENV_IMAGE", "EvaluatorService", "build_evaluator_service"]

#: The environment variable naming the digest-pinned evaluator image, e.g.
#: ``ghcr.io/nullius/evaluator@sha256:…``. §16 pins the container runtime and
#: the pinning discipline; this variable is where a deployment states the
#: result.
ENV_IMAGE = "NULLIUS_EVALUATOR_IMAGE"


class EvaluatorService:
    """Resolves and persists one evaluator's identity.

    Bound to an image reference, a configuration and a store. The image and
    the store may both be *absent* at construction — see the module docstring
    for why the composed component must be buildable without them — and are
    resolved from the environment on first use instead. A caller may also
    pass any of them explicitly, which wins over the environment, so a test
    or an operator can build a service against a scratch database.
    """

    def __init__(
        self,
        image: "str | ImageRef | None" = None,
        *,
        config: Optional[EvaluatorConfig] = None,
        store: Optional[EvaluatorIdentityStore] = None,
        defaults: Optional[Mapping[str, Any]] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        # An explicit image is parsed here (a pure operation, no registry is
        # consulted), so a tag-only reference handed in by a caller fails at
        # the call site that made the mistake. An image left to the
        # environment is parsed on first use instead — see the module
        # docstring.
        self._image: Optional[ImageRef] = (
            None
            if image is None
            else coerce_image_ref(image)
        )
        self._env = env
        self._config = (
            config if config is not None else EvaluatorConfig(env=env)
        )
        self._defaults = defaults
        # The store is resolved lazily for the same reason the image is: a
        # service with no DATABASE_URL is constructible (composition needs
        # it to be) and refuses at the first write.
        self._store = store

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        *,
        store: Optional[EvaluatorIdentityStore] = None,
        defaults: Optional[Mapping[str, Any]] = None,
        strict: bool = False,
    ) -> "EvaluatorService":
        """Construct the service, optionally insisting the environment is complete.

        With ``strict=False`` (the default) this is the component builder's
        shape: the service is built from whatever the environment provides
        and defers anything missing to first use, so composition never fails
        on this member's configuration (see the module docstring). That
        covers all three inputs — the image, the store, *and* a malformed
        ``NULLIUS_EVALUATOR_CONFIG``, which is parsed on first resolution
        rather than here for exactly the same reason.

        With ``strict=True`` the environment must be complete: an unset,
        empty or tag-only ``NULLIUS_EVALUATOR_IMAGE``, a missing
        ``DATABASE_URL``, and a malformed configuration override are all
        refused here, at construction, with the reason. That is the spelling
        for a deployment entrypoint or a health check — a caller that wants
        to learn at startup rather than at first evaluation that its
        evaluator is unpinned or its overrides unparseable.
        """
        source = os.environ if env is None else env
        service = cls(
            config=EvaluatorConfig(env=source),
            store=store,
            defaults=defaults,
            env=source,
        )
        if strict:
            # Touch every lazily-resolved piece so the refusal lands here.
            service.image  # noqa: B018 - the property raises; that is the point
            service.store  # noqa: B018 - likewise
            service.resolved_config()  # noqa: B018 - parses the override
        return service

    # -- What this service is bound to --------------------------------------

    @property
    def image(self) -> ImageRef:
        """The digest-pinned image this service resolves identities for.

        Resolved from ``NULLIUS_EVALUATOR_IMAGE`` on first access when the
        constructor was given none. Raises
        :class:`~evaluator.EvaluatorImageError` when the variable is unset,
        empty, or carries no digest — a tag is a mutable pointer and cannot
        serve as an identity term (see ``_image``).
        """
        if self._image is None:
            self._image = parse_image_ref(_image_reference(self._environment()))
        return self._image

    @property
    def config(self) -> EvaluatorConfig:
        """The configuration sources this service resolves over."""
        return self._config

    @property
    def store(self) -> EvaluatorIdentityStore:
        """The store this service persists identities into.

        Resolved from ``DATABASE_URL`` on first access when the constructor
        was given none. Raises
        :class:`~evaluator.EvaluatorStoreError` when no store is configured:
        feature 70 says "persists", so there is nothing to degrade to — a
        service that reported success for a write it did not perform would be
        worse than one that refused. A caller who only wants the hash
        computed calls :meth:`identity` (or the module-level
        ``evaluator_digest``) and never touches this property.
        """
        if self._store is None:
            self._store = EvaluatorIdentityStore.resolve(self._environment())
        return self._store

    def resolved_config(self) -> Mapping[str, Any]:
        """The resolved configuration — the identity's second term."""
        return self._config.resolved()

    def _environment(self) -> Mapping[str, str]:
        """The environment mapping this service resolves against.

        The ``env`` the service was constructed with, or the process
        environment when it was given none. Both the image and the store read
        through here, so a test that hands a service an explicit mapping gets
        that mapping for *both* — a service that read one from the mapping
        and the other from the process would be the kind of half-redirected
        seam that passes alone and fails in a suite.
        """
        return os.environ if self._env is None else self._env

    # -- The feature --------------------------------------------------------

    def identity(
        self, config: Optional[Mapping[str, Any]] = None
    ) -> EvaluatorIdentity:
        """Resolve this evaluator's identity: the two terms and their hash.

        ``config``, when given, is layered over the service's own resolved
        configuration as the top source — an ad-hoc run with one setting
        changed — and the result is a full identity, computed but not
        persisted. Use this for a hash-only question (comparing an incoming
        score's provenance, rendering a report); use :meth:`record` when the
        identity is the one this process is running under and has to be
        written down.

        Requires the image (see :attr:`image`); touches no database.
        """
        return evaluator_identity(
            self.image,
            config,
            defaults={},
            # The service's own resolved configuration is the base, so an
            # ad-hoc adjustment sits on top of it rather than under it.
            base=self._config.resolved(),
        )

    def record(
        self, config: Optional[Mapping[str, Any]] = None
    ) -> EvaluatorIdentity:
        """Compute this evaluator's identity and persist it.

        Feature 70's two verbs, in one call: the identity is resolved (see
        :meth:`identity`) and its row written to the store. Idempotent — a
        second call writes the same hash and finds the row already there,
        which the store treats as a no-op rather than a conflict — so it is
        safe to call on the evaluation path without a "have I done this
        already?" branch.

        Returns the identity, so the caller has the value it is about to
        stamp on a score without computing it twice. Raises
        :class:`~evaluator.EvaluatorStoreError` when the write fails; unlike
        the snapshot member, where the sealed directory remains a complete
        record without its row, there is nothing beside the row here — a
        process that believes it recorded its evaluator and did not is
        exactly the state this feature exists to rule out.
        """
        return self.store.persist(self.identity(config))

    def recorded(self) -> Optional[EvaluatorIdentity]:
        """This service's identity as the store holds it, or ``None``.

        Answers "has this process's evaluator been persisted yet?" without
        writing anything — ``None`` when the store holds no row for the hash
        this service resolves to. The identity is computed, not looked up by
        a stored value, so the answer is about *this* evaluator rather than
        about whatever happens to be in the table.
        """
        return self.store.resolve_hash(self.identity().evaluator_hash)

    def recorded_identities(self) -> tuple[EvaluatorIdentity, ...]:
        """Every identity this store holds, ordered by image digest.

        The operator's view: which evaluators has this system run? Read
        through the service so a caller holding the composed component never
        needs the store directly.
        """
        return self.store.identities()

    def comparable(
        self, left_hash: str, right_hash: str
    ) -> ProvenanceCheck:
        """Certify that two scores, by their stored hashes, can be compared.

        Feature 71's end-to-end path: two scores each carry an
        ``evaluator_hash`` as their provenance; this resolves each to the
        identity the store persisted under it and refuses the comparison when
        the two differ. A hash the store holds no row for is a *missing*
        record (:meth:`resolve_hash` returns ``None``), not a mismatch between
        two present ones — so it is refused here with the same message,
        because a score whose provenance was never persisted is not one this
        system can place on an axis with another.

        Requires the store (it is the stored value the comparison is against,
        not a recomputed one — see ``_store``); returns a
        :class:`~evaluator.ProvenanceCheck` naming the shared hash when the
        two scores share an evaluator. Raises
        :class:`~evaluator.EvaluatorProvenanceError` — the
        ``mismatched_provenance`` refusal — when the evaluators differ or a
        score's provenance was never recorded.
        """
        left = self.store.resolve_hash(left_hash)
        if left is None:
            raise EvaluatorProvenanceError(
                f"mismatched_provenance: the score carrying evaluator_hash "
                f"{left_hash!r} was never persisted, so there is no evaluator "
                "this system recorded to compare it under; app_spec.xml "
                "feature 70 persists the identity and feature 71 refuses a "
                "comparison it cannot place — record the score's evaluator "
                "before comparing"
            )
        right = self.store.resolve_hash(right_hash)
        if right is None:
            raise EvaluatorProvenanceError(
                f"mismatched_provenance: the score carrying evaluator_hash "
                f"{right_hash!r} was never persisted, so there is no evaluator "
                "this system recorded to compare it under; app_spec.xml "
                "feature 70 persists the identity and feature 71 refuses a "
                "comparison it cannot place — record the score's evaluator "
                "before comparing"
            )
        return check_comparable(left, right)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        image = "unresolved" if self._image is None else repr(self._image.short)
        return f"EvaluatorService(image={image})"


def _image_reference(env: Mapping[str, str]) -> str:
    """Read the pinned image reference from the environment, or say what is missing.

    Split out so the refusal for an *unset* variable is spelled once, with
    the remedy (a digest-pinned reference, and why a tag will not do), rather
    than being re-derived at the call site — :func:`parse_image_ref` already
    refuses a tag-only value with its own message, and this only has to cover
    the variable being absent or blank.
    """
    raw = (env.get(ENV_IMAGE) or "").strip()
    if not raw:
        raise EvaluatorImageError(
            f"{ENV_IMAGE} is not set, so there is no pinned evaluator image "
            "to compute evaluator_hash over (app_spec.xml feature 70); set "
            "it to a digest-pinned reference, for example "
            "ghcr.io/nullius/evaluator@sha256:<64 hex> — a tag is a mutable "
            "pointer and cannot serve as an identity term"
        )
    return raw


def build_evaluator_service(
    env: Optional[Mapping[str, str]] = None,
    *,
    store: Optional[EvaluatorIdentityStore] = None,
    defaults: Optional[Mapping[str, Any]] = None,
) -> EvaluatorService:
    """Build the service the composed application carries.

    The one-shot convenience the component builder uses, kept beside the
    class so a test and the factory construct it the same way — the same
    shape ``universe.build_universe_service`` has. Deliberately *not*
    strict: the factory builds this component on every ``create_app()``, so
    it must succeed without a pinned image or a database and refuse later,
    where the refusal is informative (see the module docstring).
    """
    return EvaluatorService.from_env(env, store=store, defaults=defaults)
