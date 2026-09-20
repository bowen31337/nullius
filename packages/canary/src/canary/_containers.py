"""Every evaluation container, pinned at once — the sweep.

Feature 135's word is *every*: not "the evaluator's image is pinned"
(the evaluator member's own feature 70 already folds that one digest
into that one hash) but "every evaluation container the deployment runs
is pinned by digest". The difference is the difference between an
identity and an audit. An identity names one thing; an audit asks the
set — and a set assertion that stopped at the first offender, or passed
when it enumerated nothing, would be an audit in name only.

Three decisions shape this module:

**The refusal is collective and complete.** :func:`pin_containers`
parses every entry and raises *one* :class:`~canary.CanaryImageError`
naming *every* offender — role, environment variable where one backs
the role, and the reference as written. A sweep that reported only the
first refusal would be re-run N times to learn what one run should have
said, and the operator of a nightly assertion (§12: the canary is "the
cheapest high-value test in the system") reads the whole deployment's
state in one message. The set is all-or-nothing to match: a declaration
that pins the evaluator and tags the runner never yields a partial
value a caller could mistake for a swept deployment.

**Empty is refused, not passed.** A pin sweep over zero containers is
green because it checked nothing — vacuous green, the one reading the
nightly canary must never allow ("non-determinism does not announce
itself; it just slowly makes every conclusion wrong", §12). A caller
with a genuinely empty deployment has no evaluation path to guard and
no business asking for the sweep.

**The declared set is one table.** :data:`IMAGE_ENV_VARS` is the single
place the roles and their environment variables are written down. Today
it names the one container the evaluation path runs — the evaluator
image, read from the same ``NULLIUS_EVALUATOR_IMAGE`` the evaluator
service itself resolves, so a deployment states a pin once and both the
identity and the audit read it. Later features in this category add
containers to *this table* when they add containers to the path — the
nightly replay runner of feature 142 joins here, not in a second
registry somebody has to remember to sweep too.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Optional

from ._errors import CanaryImageError
from ._image import PinnedImage, _require_role, parse_pinned_image

__all__ = [
    "EVALUATOR_ROLE",
    "IMAGE_ENV_VARS",
    "PinnedContainers",
    "pin_containers",
    "pinned_containers_from_env",
]

#: The role of the container the evaluation pipeline runs inside — the
#: image ``evaluator_hash``'s first term is computed over (feature 70)
#: and the one container every §6.1 step executes in. Kept as a named
#: constant rather than a bare string so the sweep, the service and the
#: tests share one spelling of "the evaluator".
EVALUATOR_ROLE = "evaluator"

#: The declared evaluation containers: role → the environment variable
#: naming that container's image reference. The sweep reads exactly this
#: table — a container that is not declared here is a container nobody
#: promised to pin, and a variable that is not read here is a pin the
#: sweep would silently ignore. Later features extend this mapping; they
#: do not add a second one beside it.
IMAGE_ENV_VARS: Mapping[str, str] = {
    EVALUATOR_ROLE: "NULLIUS_EVALUATOR_IMAGE",
}


@dataclass(frozen=True)
class PinnedContainers:
    """An immutable set of pins — the sweep's positive result.

    Built by :func:`pin_containers` or :func:`pinned_containers_from_env`
    (or directly from :class:`~canary.PinnedImage` values, validated the
    same way): sorted by role, free of duplicates, never empty. Iteration
    yields the pins in role order; :attr:`digests` is the comparison view
    (role → digest) and :attr:`references` the operator's view (role →
    the reference as written).
    """

    #: The pins, sorted by role.
    images: tuple[PinnedImage, ...]

    def __post_init__(self) -> None:
        # Normalize before checking emptiness, so a generator handed in
        # (falsy even when it will yield values) cannot slip an empty or
        # half-built set past the non-vacuity guarantee.
        images = tuple(self.images)
        if not images:
            raise CanaryImageError(_EMPTY_DECLARATION)
        seen: set[str] = set()
        for image in images:
            if not isinstance(image, PinnedImage):
                raise CanaryImageError(
                    f"a pin must be a PinnedImage, got {image!r}; the sweep "
                    "compares digests it parsed itself, not strings a "
                    "caller asserts are pins"
                )
            if image.role in seen:
                raise CanaryImageError(
                    f"the {image.role} container is declared twice; a role "
                    "with two pins is two containers wearing one word, and "
                    "the sweep could not say which one the evaluation path "
                    "runs in"
                )
            seen.add(image.role)
        object.__setattr__(
            self, "images", tuple(sorted(images, key=lambda pin: pin.role))
        )

    @property
    def roles(self) -> tuple[str, ...]:
        """The declared roles, in sorted order."""
        return tuple(image.role for image in self.images)

    @property
    def digests(self) -> dict[str, str]:
        """Role → digest — the view comparisons and reports run over."""
        return {image.role: image.digest for image in self.images}

    @property
    def references(self) -> dict[str, str]:
        """Role → the reference as written — the operator's view."""
        return {image.role: image.reference for image in self.images}

    def __getitem__(self, role: str) -> PinnedImage:
        """The pin declared for ``role``; ``KeyError`` when there is none."""
        for image in self.images:
            if image.role == role:
                return image
        raise KeyError(role)

    def __contains__(self, role: object) -> bool:
        return isinstance(role, str) and any(
            image.role == role for image in self.images
        )

    def __len__(self) -> int:
        return len(self.images)

    def __iter__(self) -> Iterator[PinnedImage]:
        return iter(self.images)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"PinnedContainers(roles={self.roles!r})"


#: The empty-declaration refusal, spelled once because it is an argument
#: rather than a diagnostic: the sweep exists to be non-vacuous.
_EMPTY_DECLARATION = (
    "a container declaration naming no containers pins nothing: a pin "
    "sweep over an empty set is green because it checked nothing, and "
    "vacuous green is the one reading the nightly determinism canary "
    "must never allow (architecture §12); declare at least the evaluator "
    "container to make the sweep mean something"
)


def pin_containers(references: Mapping[str, str]) -> PinnedContainers:
    """Pin a declaration of containers: role → image reference, all at once.

    Every entry is parsed by :func:`~canary.parse_pinned_image`; every
    failure is collected; one :class:`~canary.CanaryImageError` names
    them all (see the module docstring for why the refusal is complete
    rather than first-wins). A role backed by a variable in
    :data:`IMAGE_ENV_VARS` has that variable named in its entry, so an
    operator reading the refusal knows where to fix. Returns the
    :class:`PinnedContainers` — all-or-nothing, so a caller can never
    hold a partial sweep dressed as a passed one.
    """
    if not isinstance(references, Mapping):
        raise CanaryImageError(
            "a container declaration must be a mapping of role to image "
            f"reference, got {type(references).__name__}; the sweep reads "
            "one declaration, not a sequence of maybe-related strings"
        )
    if not references:
        raise CanaryImageError(_EMPTY_DECLARATION)
    # A malformed role key is a caller programming error, not a pin
    # failure — it is refused here, immediately, rather than collected
    # into the sweep's message where it would have to be named by a word
    # it does not have.
    for role in references:
        _require_role(role)
    return _sweep(
        (role, IMAGE_ENV_VARS.get(role), reference)
        for role, reference in references.items()
    )


def pinned_containers_from_env(env: Mapping[str, str]) -> PinnedContainers:
    """Resolve the declared evaluation containers from an environment.

    Reads every role in :data:`IMAGE_ENV_VARS` from ``env`` — the same
    mapping seam the evaluator service resolves through, so a test or an
    operator can hand the sweep an environment without touching the
    process. A variable that is unset or blank is a refusal, not a skip:
    an evaluation container nobody named is an evaluation container
    nobody pinned, and a sweep that quietly dropped it would pass while
    the path it guards ran unpinned.
    """
    return _sweep(
        (role, variable, (env.get(variable) or ""))
        for role, variable in sorted(IMAGE_ENV_VARS.items())
    )


def _sweep(
    entries: Iterable[tuple[str, Optional[str], str]],
) -> PinnedContainers:
    """Parse every ``(role, variable, reference)`` entry, refuse completely.

    The one place the feature's *every* is enforced mechanically: no
    entry is skipped, no failure is dropped, and the refusal raised
    carries all of them in sorted role order. ``variable`` is ``None``
    for a role :data:`IMAGE_ENV_VARS` does not back, and the entry then
    names the role alone. A reference that is blank (or not a string at
    all) is routed through the unset refusal when a variable backs the
    role, and through the parser's own refusal otherwise — the parser's
    message names the value it was given, which is the more informative
    half of the pair when there is no variable to point at.
    """
    failures: list[str] = []
    pins: list[PinnedImage] = []
    for role, variable, raw in sorted(entries, key=lambda entry: entry[0]):
        prefix = (
            f"{variable} (the {role} container)"
            if variable is not None
            else f"the {role} container"
        )
        blank = isinstance(raw, str) and not raw.strip()
        unset = variable is not None and (
            raw is None or (isinstance(raw, str) and not raw.strip())
        )
        if unset:
            failures.append(
                f"{prefix}: {variable} is not set, so the {role} container "
                "is not pinned — an evaluation container nobody named is "
                "an evaluation container nobody pinned (app_spec.xml "
                "feature 135); set it to a digest-pinned reference, for "
                f"example ghcr.io/nullius/{role}@sha256:<64 hex>"
            )
            continue
        if blank:
            failures.append(
                f"{prefix}: no image reference was given (got {raw!r})"
            )
            continue
        try:
            pins.append(parse_pinned_image(raw, role=role))
        except CanaryImageError as refusal:
            failures.append(f"{prefix}: {refusal}")
    if failures:
        raise CanaryImageError(
            "the evaluation containers are not pinned by digest — "
            f"{len(failures)} of {len(failures) + len(pins)} declared "
            "refused:\n  " + "\n  ".join(failures)
        )
    return PinnedContainers(tuple(pins))
