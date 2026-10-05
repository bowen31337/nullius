"""The exploration policy — the law that picks the next batch to expand.

additions_spec_campaign_driver.xml, "Exploration Policy" category, feature 4:
*System creates the exploration policy that selects the next batch of nodes to
expand, with orchestrator._policy.load_exploration_policy(env=None). The
policy's select(prefix_view) answers a list of node ids.*  Feature 3
(:mod:`orchestrator._live_tree`) builds the question a round is asked over;
this module is the other half the round loop (spec B, feature 6) reaches for —
the thing that actually answers *which* unrevealed nodes get expanded next.

**Two sources, one shape.**  ``NULLIUS_EXPLORATION_POLICY`` names a source file
an operator authored — admitted through :func:`policy_runtime.screen_policy`
(features 230/231's static gate), imported under
:data:`policy_runtime.POLICY_MODULE_NAME` and run under
:func:`policy_runtime.guard_policy` (feature 225's runtime guard) every time it
is asked.  Unset, the policy is the committed :class:`BaselinePolicy` — a
plain ranking rule, trusted system code rather than an admitted artifact, and
therefore never screened or guarded.  Both are handed back wearing the same
:class:`ExplorationPolicy` face — one ``select(prefix_view) -> list[str]`` —
so spec B's round loop calls either exactly the same way.

**The answer is checked once, in one place, for both sources.**  A hand-authored
policy's ``select`` is arbitrary code the gate only screened statically; a
batch it hands back that names a node the view never revealed, repeats one, or
is not a ``list`` at all would corrupt the round silently if trusted.  So
:class:`ExplorationPolicy` validates every answer against the view it was
handed, regardless of which source produced it — the baseline passes this by
construction, and the check is what makes a misbehaving custom policy fail
loud rather than hand the loop a batch it cannot act on.

**Why the baseline cannot really honour "one per theme root" against the live
tree.**  :mod:`orchestrator._live_tree`'s payload deliberately carries no
``theme_root`` key (its own docstring states why: the module reads only
``id``, ``parent_id``, ``depth`` and ``ic_mean``), and
:func:`policy_runtime.prefix_view` copies only the five observation fields —
neither carries a theme.  docs §634 confines ``theme_root`` to
``question.meta()`` alone, which a bare :class:`~policy_runtime.PrefixView`
does not expose at all.  :class:`BaselinePolicy` therefore reads a cell's theme
through ``prefix_view.meta(node_id).theme_root`` when the view it was handed
happens to expose a callable ``meta`` (duck-typed, the same seam discipline
:func:`policy_runtime.prefix_view` itself keeps), and falls back to the node's
own id as a singleton theme when it does not — which is always, for the live
tree's view today.  That fallback is deliberate rather than a gap papered
over: grouping by a constant key would collapse every batch to one pick the
moment no theme signal exists, which is a worse failure than a per-theme cap
that has nothing yet to divide.
"""

from __future__ import annotations

import os
import sys
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from policy_runtime import (
    POLICY_MODULE_NAME,
    PolicyRuntimeError,
    guard_policy,
    screen_policy,
)

__all__ = [
    "DEFAULT_BASELINE_WIDTH",
    "EXPLORATION_POLICY_ENV",
    "POLICY_LOAD_CODE",
    "BaselinePolicy",
    "ExplorationPolicy",
    "PolicyLoadError",
    "load_exploration_policy",
]

#: The environment variable naming a custom policy's source file.  Unset (or
#: blank), the committed :class:`BaselinePolicy` is the policy.
EXPLORATION_POLICY_ENV = "NULLIUS_EXPLORATION_POLICY"

#: The greppable word every :class:`PolicyLoadError` message leads with — a
#: caller greps one word for *the configured exploration policy could not be
#: loaded or answered* and reaches every face of it: a refused admission, an
#: unreadable file, a missing ``select``, or a malformed batch.
POLICY_LOAD_CODE = "policy_load"

#: :class:`BaselinePolicy`'s own width when :func:`load_exploration_policy`
#: builds it from an unset environment.  Spec B's round loop re-slices every
#: policy's answer to its own operator-configured ``width`` regardless
#: (``policy.select(...)[:width]``), so this default only bounds a direct call
#: to the loaded policy outside that loop; chosen generously so the loop's own
#: slice, not this one, is the limiting factor in practice.
DEFAULT_BASELINE_WIDTH = 8


class PolicyLoadError(Exception):
    """The configured exploration policy could not be loaded, or it misanswered.

    Every face this module itself refuses: ``NULLIUS_EXPLORATION_POLICY``
    naming a file that cannot be read, source :func:`policy_runtime.screen_policy`
    refuses, an admitted module carrying no top-level ``select``, and an
    answer — from either source — that names an id outside the view, repeats
    one, or is not a ``list``.  Kept apart from :class:`policy_runtime.PolicyRuntimeError`
    and its children deliberately: those are the admission gate's and the
    runtime guard's own vocabulary for a *policy's source or its reach*, raised
    by that member and propagated here unchanged, while this class is this
    module's own — a fact about *how the call to load or run a policy was
    made*, the same split :mod:`orchestrator._live_tree`'s ``LiveTreeError``
    draws against the tree's own refusals.
    """


@dataclass(frozen=True)
class BaselinePolicy:
    """The committed exploration policy — a plain, auditable ranking rule.

    Answers up to :attr:`width` revealed node ids, highest ``ic_insample``
    first, at most one per theme root per batch, ties broken by node id.  A
    view with no revealed node answers ``[]``.  See the module docstring for
    why the per-theme cap is read through an optional ``meta(node_id)`` on the
    view rather than demanded of it.
    """

    width: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.width, bool)
            or not isinstance(self.width, int)
            or self.width <= 0
        ):
            raise PolicyLoadError(
                f"{POLICY_LOAD_CODE}: BaselinePolicy's width must be a "
                f"positive integer, got {self.width!r} "
                f"({type(self.width).__name__}): it answers at most this many "
                "node ids per batch, and a width that names no positive count "
                "names no batch size"
            )

    def select(self, prefix_view: Any) -> list[str]:
        """Rank every revealed node, then take the batch, one per theme root."""
        observed = _revealed(prefix_view)
        if not observed:
            return []
        ranked = sorted(observed.values(), key=_rank_key)
        chosen: list[str] = []
        used_themes: set[Any] = set()
        for observation in ranked:
            if len(chosen) >= self.width:
                break
            node_id = observation.node_id
            theme = _theme_key(prefix_view, node_id)
            if theme in used_themes:
                continue
            used_themes.add(theme)
            chosen.append(node_id)
        return chosen


class ExplorationPolicy:
    """The object :func:`load_exploration_policy` answers — one ``select``, either source.

    Wraps the raw ``select`` callable (an admitted module's top-level
    function, or a bound :meth:`BaselinePolicy.select`) and, for an admitted
    module only, runs it under :func:`policy_runtime.guard_policy` every call
    — the runtime guard is a property of *authored* code, not of this
    member's own trusted :class:`BaselinePolicy`.  Every answer, from either
    source, is validated against the view it was computed over before it is
    handed back: not a ``list``, a repeated id, or an id the view never
    revealed each raise :class:`PolicyLoadError`.
    """

    __slots__ = ("_guarded", "_select")

    def __init__(self, select: Callable[[Any], Any], *, guarded: bool) -> None:
        self._select = select
        self._guarded = guarded

    def select(self, prefix_view: Any) -> list[str]:
        if self._guarded:
            with guard_policy(policy_module=POLICY_MODULE_NAME):
                answer = self._select(prefix_view)
        else:
            answer = self._select(prefix_view)
        return _validated_answer(answer, prefix_view)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ExplorationPolicy(guarded={self._guarded})"


def load_exploration_policy(env: Mapping[str, str] | None = None) -> ExplorationPolicy:
    """Load the configured exploration policy — the feature's verb.

    Reads :data:`EXPLORATION_POLICY_ENV` from ``env`` (the process environment
    when ``env`` is ``None``).  Unset or blank, the policy is
    :class:`BaselinePolicy` at :data:`DEFAULT_BASELINE_WIDTH`, unguarded and
    unscreened — trusted system code.  Named, the file's text must be admitted
    by :func:`policy_runtime.screen_policy`; a refusal raises
    :class:`PolicyLoadError` naming the refusal's reason and detail.  An
    admitted file is imported as :data:`policy_runtime.POLICY_MODULE_NAME`
    under :func:`policy_runtime.guard_policy`, and its top-level ``select``
    function becomes the policy — missing or non-callable, that is also a
    :class:`PolicyLoadError`.

    Either way, the answer is :class:`ExplorationPolicy`: one ``select``,
    validated the same way regardless of which source answered it.
    """
    source = os.environ if env is None else env
    named = source.get(EXPLORATION_POLICY_ENV)
    if named is None or not named.strip():
        return ExplorationPolicy(
            BaselinePolicy(DEFAULT_BASELINE_WIDTH).select, guarded=False
        )
    named = named.strip()

    text = _read_source(named)
    decision = screen_policy(text)
    if not decision.adopted:
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: {EXPLORATION_POLICY_ENV} names {named!r}, "
            f"whose source was refused admission ({decision.reason.value}): "
            f"{decision.detail}"
        )

    module = _import_admitted(named, decision.source or text)
    select_fn = getattr(module, "select", None)
    if not callable(select_fn):
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: {EXPLORATION_POLICY_ENV} names {named!r}, "
            "which was admitted but carries no top-level select function: "
            "the policy's contract is select(prefix_view), and a module "
            "without one names no policy to run"
        )
    return ExplorationPolicy(select_fn, guarded=True)


# -- Reading and importing the configured file ---------------------------------


def _read_source(named: str) -> str:
    """The configured file's text, or a :class:`PolicyLoadError` naming why not."""
    try:
        return Path(named).read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: {EXPLORATION_POLICY_ENV} names {named!r}, "
            f"which cannot be read: {exc}"
        ) from exc


def _import_admitted(named: str, source: str) -> types.ModuleType:
    """Import admitted ``source`` as :data:`POLICY_MODULE_NAME`, under the guard.

    Registered in :data:`sys.modules` before it runs — the same registration
    :mod:`policy_runtime`'s own guard tests build a policy with — so an import
    the admitted source performs sees the subject the guard judges it by.  Run
    inside :func:`policy_runtime.guard_policy`, so a source that reaches the
    filesystem or an import outside the configured ceiling at its own module
    scope is refused before this call returns, with the runtime guard's own
    error (:class:`~policy_runtime.PolicyFilesystemError` or
    :class:`~policy_runtime.PolicyImportError`), propagated unchanged: that is
    the runtime guard's contract, not this module's to re-spell. Any other
    failure executing the admitted source — a ``NameError``, an assertion
    at import time — is a file that cannot be imported, wrapped as
    :class:`PolicyLoadError`.
    """
    module = types.ModuleType(POLICY_MODULE_NAME)
    sys.modules[POLICY_MODULE_NAME] = module
    try:
        with guard_policy(policy_module=POLICY_MODULE_NAME):
            exec(compile(source, named, "exec"), module.__dict__)  # noqa: S102
    except PolicyRuntimeError:
        raise
    except Exception as exc:
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: {EXPLORATION_POLICY_ENV} names {named!r}, "
            f"which was admitted but raised importing it: {exc!r}"
        ) from exc
    return module


# -- Validating any policy's answer against the view it was handed ------------


def _revealed(prefix_view: Any) -> Mapping[str, Any]:
    """The view's revealed cells, by node id — the one read every path shares."""
    observed = getattr(prefix_view, "observed", None)
    if not callable(observed):
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: a policy is handed a view exposing "
            f"observed() — got {prefix_view!r} ({type(prefix_view).__name__}), "
            "which has none"
        )
    mapping = observed()
    if not isinstance(mapping, Mapping):
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: a view's observed() must answer a mapping "
            f"of node ids to observations, got {mapping!r} "
            f"({type(mapping).__name__})"
        )
    return mapping


def _validated_answer(answer: Any, prefix_view: Any) -> list[str]:
    """Check a policy's raw answer: a list, no duplicate id, every id revealed."""
    if not isinstance(answer, list):
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: a policy's select() must answer a list of "
            f"node ids, got {answer!r} ({type(answer).__name__})"
        )
    revealed = _revealed(prefix_view)
    seen: set[Any] = set()
    for node_id in answer:
        if node_id in seen:
            raise PolicyLoadError(
                f"{POLICY_LOAD_CODE}: the policy's answer names {node_id!r} "
                "twice; a batch names each node at most once"
            )
        seen.add(node_id)
        if node_id not in revealed:
            raise PolicyLoadError(
                f"{POLICY_LOAD_CODE}: the policy's answer names {node_id!r}, "
                "which is not a revealed node in the view it was handed"
            )
    return answer


# -- The baseline's own ranking -------------------------------------------------


def _rank_key(observation: Any) -> tuple[float, str]:
    """Highest ``ic_insample`` first, ties broken by node id — one sort key."""
    value = getattr(observation, "ic_insample", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        rank = float("inf")
    else:
        rank = -float(value)
    return (rank, observation.node_id)


def _theme_key(prefix_view: Any, node_id: str) -> Any:
    """A cell's theme root, read through an optional ``meta()`` — see module docstring."""
    meta_fn = getattr(prefix_view, "meta", None)
    if callable(meta_fn):
        try:
            meta = meta_fn(node_id)
        except (PolicyRuntimeError, AttributeError, TypeError, KeyError, ValueError):
            meta = None
        theme_root = getattr(meta, "theme_root", None) if meta is not None else None
        if isinstance(theme_root, str) and theme_root.strip():
            return theme_root
    return node_id
