"""The policy-runtime module — app-level entrypoint for the policy-runtime workspace member.

The implementation lives in the ``policy-runtime`` workspace member
(``packages/policy-runtime``, import name ``policy_runtime``), which
self-registers with the application factory under the component name
:data:`COMPONENT_NAME` — scanning the workspace imports it, its ``@register``
decorator fires, and ``create_app()`` composes the campaign tree the
deployment's artifact store holds (app_spec.xml feature 217: *System exposes
an observed accessor which returns a mapping of revealed node ids to
observations*, the read side of docs/nullius-tech-architecture.md §11's
identical ``question.*`` interface an exploration policy is handed during
replay).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/policy-runtime/``): it exposes the composed component
without making the ``app`` package depend on any workspace member at import
time.  Composition stays the factory's job — this module only asks the factory
for the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring the
factory's own "degrade, don't break" stance toward absent components.

The helper below is deliberately the *composition* accessor and nothing more.
It does not re-export the tree, the node model, the observation or the
question: a caller who has the tree reaches
``policy_runtime.policy_question(tree)`` for the read-side adapter,
``tree.observed()`` for the revealed cells, and ``tree.reveal(node_id)`` for a
reveal — and a second spelling of those APIs here would be a second thing to
keep in sync.  This module answers exactly one question — *what is the
composed campaign tree?* — so the features in this category that need the
read-side interface (218's frontier, 219's meta, 220's probe, 222's commit)
can ask it without importing the member directly.

Features 230 and 231 live in the same member but are not reached through this
seat: the admission gate (:func:`policy_runtime.screen_policy`) is a pure static
check over a policy's source, with no store and no deployment state, so it is
reached directly from the member — ``from policy_runtime import screen_policy``
— exactly the way feature 229's :func:`policy_runtime.plan_grid` is, rather than
through the composed application.  This module does not wrap it, because a
second spelling of a pure gate would be a second thing to keep in sync, and the
gate has no component to compose.  Feature 231's deferral check (a learned
component reached from a policy's source) is the fourth static check on that
same gate rather than a second one, so it needs no seat of its own either.

Feature 226 lives in the same member and is likewise not reached through this
seat: the beta scalar (:func:`policy_runtime.read_beta`) is an episode's own
value, read once at initialization and fixed for the episode, with no store and
no component — so it is reached directly from the member — ``from
policy_runtime import read_beta`` — exactly the way the admission gate and
feature 229's :func:`policy_runtime.plan_grid` are.  This module does not wrap
it, because there is nothing here to compose: the scalar belongs to the episode
the replay opens, not to the composed application, and a second spelling of it
would be a second thing to keep in sync.

Feature 223 lives in the same member and is likewise not reached through this
seat: the prefix view (:func:`policy_runtime.prefix_view`) is a pure
construction over a question — it copies the question's own ``observed()``
readings out into a fresh frozen snapshot holding only the cells a policy has
revealed (docs/nullius-tech-architecture.md §10.2, cq-16) — with no store, no
deployment state and no component, so it is reached directly from the member —
``from policy_runtime import prefix_view`` — exactly the way the admission
gate, the beta scalar and feature 229's :func:`policy_runtime.plan_grid` are.
This module does not wrap it, because there is nothing here to compose: the
view belongs to the round a replay hands a policy, not to the composed
application, and a second spelling of it would be a second thing to keep in
sync — and, worse, a second place the prefix-only law would have to hold.

Feature 225 lives in the same member and is likewise not reached through this
seat: the runtime guard (:func:`policy_runtime.guard_policy`) is a *runtime*
extent a replay opens around a policy's episode — the two halves of
docs/nullius-tech-architecture.md §10.2's closing sentence, filesystem access
and any import outside the configured allowlist — with no store and no
component, so it is reached directly from the member — ``from policy_runtime
import guard_policy`` — exactly the way the admission gate, the beta scalar,
the prefix view and feature 229's :func:`policy_runtime.plan_grid` are.  This
module does not wrap it, because there is nothing here to compose: the guard
belongs to the episode the replay runs, not to the composed application.

Feature 224 lives in the same member and is likewise not reached through this
seat: the policy answer surface (:func:`policy_runtime.policy_surface`) is a
pure construction over an episode — it reads the answers the deployment
configured out of it and copies them into a fresh object that refuses every
other name, so ``question.best_so_far`` and ``question.budget_spent`` are
unreachable by an attribute walk (docs/nullius-tech-architecture.md §10.2) —
with no store, no deployment state and no component, so it is reached directly
from the member — ``from policy_runtime import policy_surface`` — exactly the
way the admission gate, the beta scalar, the prefix view and feature 229's
:func:`policy_runtime.plan_grid` are.  This module does not wrap it, because
there is nothing here to compose: the surface belongs to the episode a replay
hands a policy, not to the composed application, and a second spelling of it
would be a second thing to keep in sync — and, worse, a second place the
answer-set law would have to hold.

That last point is worth stating rather than leaving to be inferred, because
feature 225 *does* read a composed artifact — the configured allowlist — and a
seat here would be the natural place to hand one over.  The read is the
member's own: the guard resolves feature 167's ``sandbox-imports`` ceiling
through the sandbox's seat (:mod:`app.modules.sandbox`) and memoises it, which
is the composition the guard needs and the only one it has.  A wrapper here
would be a second spelling of *which* ceiling a policy is judged by — the one
thing §10.2 says is singular — so this module leaves the resolution where it
belongs and exposes only the tree.

Feature 218 lives in the same member and is likewise not reached through this
seat: the legal moves (:meth:`policy_runtime.PolicyQuestion.legal_roots` and
:meth:`policy_runtime.PolicyQuestion.legal_actions`, over the free functions
:func:`policy_runtime.legal_roots` and :func:`policy_runtime.legal_actions`
behind them) are *methods on the read-side question* rather than a construction
of its own — they answer where a walk may **begin** (the tree's parentless
nodes, each a research theme's opening node) and where it may **go next** (a
position's open frontier, one recorded edge on, ascending) — with no store, no
deployment state and no component, so they are reached the way every other read
of the question is: a caller who holds the tree takes
``policy_runtime.policy_question(tree)`` and calls the verbs on it, exactly as it
calls :meth:`~policy_runtime.PolicyQuestion.observed` or
:meth:`~policy_runtime.PolicyQuestion.meta`.  This module does not wrap them,
because there is nothing here to compose: the frontier belongs to the tree the
composed application holds — and the verbs already *read* that tree, so a
wrapper here would be a second spelling of one derivation, and, worse, a second
place the pure-function-of-the-tree law would have to hold.  That law is the
reason this pair is *not* the seat's to shape: the sibling pool's
``legal_actions`` reads its lattice and never its reveal set, so an answer that
moved as cells were probed would break "one policy, both pools" in the walk
itself, and this module exposes only the tree for the reasons its opening
paragraph gives.

Feature 222 lives in the same member and is likewise not reached through this
seat: the terminal commit (:func:`policy_runtime.episode_commit`) is an
episode's own protocol object — one commit naming one node, read once at
termination, with a non-committing policy scored −∞ rather than refused
(docs §598, prd §438) — with no store, no deployment state and no component,
so it is reached directly from the member — ``from policy_runtime import
episode_commit`` — exactly the way the admission gate, the beta scalar, the
prefix view, feature 229's :func:`policy_runtime.plan_grid` and feature 224's
:func:`policy_surface` are.  This module does not wrap it, because there is
nothing here to compose: the commit record belongs to the episode a replay
closes, not to the composed application, and a second spelling of the −∞ or
of the one-commit door would be a second place the termination protocol would
have to hold.

Feature 221 lives in the same member and is likewise not reached through this
seat: the statistical budget (:func:`policy_runtime.budget_account` and the
:meth:`policy_runtime.PolicyQuestion.budget_remaining` reading it feeds) is a
pure function of a stated allowance and the campaign's §8 ``charges_budget``
directives — no store, no deployment state and no component — so it is reached
directly from the member — ``from policy_runtime import budget_account`` —
exactly the way the admission gate, the beta scalar, the prefix view, feature
229's :func:`policy_runtime.plan_grid`, feature 224's
:func:`policy_surface` and feature 222's :func:`policy_runtime.episode_commit`
are.  This module does not wrap it, because there is nothing here to compose:
the allowance belongs to the episode the replay opens and the charges come from
the ledger's rows at the call site that holds them, not to the composed
application — and a second spelling of the statistical-versus-compute
discriminant would be a second place for §10.3's ``− β₁ · trials_charged`` to
be read against the wrong resource.  Note in particular that the seat composes
the *question's tree* and not its budget: a question built from
:func:`policy_runtime.policy_question` with no account answers
:data:`policy_runtime.UNBOUNDED_BUDGET`, which is the honest state of a
composed deployment that has stated no statistical ceiling.

Feature 220 lives in the same member and is likewise not reached through this
seat: the batch reveal
(:meth:`policy_runtime.PolicyQuestion.probe_batch`, with its optional
``on_reveal`` callback and the :meth:`policy_runtime.PolicyQuestion.reveal_many`
delegation beside it) is a *method on the read-side question* rather than a
construction of its own — it grows the question's own reveal set and returns
the observations it newly revealed (docs/nullius-tech-architecture.md §596,
prd §421) — with no store, no deployment state and no component, so it is
reached the way every other read of the question is: a caller who holds the
tree takes ``policy_runtime.policy_question(tree)`` and calls the verb on it,
exactly as it calls :meth:`~policy_runtime.PolicyQuestion.observed` or
:meth:`~policy_runtime.PolicyQuestion.reveal`.  This module does not wrap it,
because there is nothing here to compose: the batch belongs to the episode a
replay runs, not to the composed application, and a second spelling of the verb
would be a second place the prefix-only law, the all-or-nothing validation and
the once-per-new-cell callback would each have to hold.  This is also where the
seat's earlier sentence earns its keep — feature 220 needs the read-side
interface, and what it asks this module for is the *tree*, not a probe.

Feature 219 lives in the same member and is likewise not reached through this
seat: the structural meta accessor
(:meth:`policy_runtime.PolicyQuestion.meta`, over the
:class:`policy_runtime.CellMeta` value and the
:func:`policy_runtime.cell_meta` derivation behind it) is a *method on the
read-side question* rather than a construction of its own — it answers the four
structural fields docs/nullius-tech-architecture.md §595 names (``branch``,
``depth``, ``parent``, ``theme_root``) for any node the tree holds, derived from
the tree's own edges and the node's own record rather than stored beside either
— with no store, no deployment state and no component, so it is reached the way
every other read of the question is: a caller who holds the tree takes
``policy_runtime.policy_question(tree)`` and calls the verb on it, exactly as it
calls :meth:`~policy_runtime.PolicyQuestion.observed` or
:meth:`~policy_runtime.PolicyQuestion.probe_batch`.  This module does not wrap
it, because there is nothing here to compose: the structure belongs to the tree
the composed application holds — and the accessor already *reads* that tree, so
a wrapper here would be a second spelling of one derivation, and, worse, a
second place §634's ``theme_root`` used only via ``meta()`` would have to hold.
This is the seat's opening sentence read one feature on: the reason this module
exposes the tree and nothing else is that 218's frontier, 219's meta, 220's
probe and 222's commit all need the same one thing, and each is spelled where it
belongs.

Where the composed tree is ``None``, that is a statement about the deployment,
not an error: the member was not scanned, or the workspace is empty, or the
deployment's artifact store holds no committed campaign, so there is no tree to
front.  A caller that needs one must not treat ``None`` as "this campaign has
no nodes" — those are different facts, and §10.2's prefix-only enforcement is
precisely the rule that keeps them apart: an absent component is a statement
about composition, while an empty campaign is a statement about what has been
authored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from policy_runtime import CampaignTree

__all__ = ["COMPONENT_NAME", "campaign_tree_component"]

#: The component name the policy-runtime member registers under.  Kept here so
#: anything asking the composed application for the campaign tree — by way of
#: the app package, not the member — shares one spelling.
COMPONENT_NAME = "policy-runtime"


def campaign_tree_component(
    app: Application | None = None,
) -> CampaignTree | Any:
    """Return the composed campaign tree (feature 217's read-side surface).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``policy-runtime`` component is registered — an
    absent component is a discoverable state, not an exception, exactly as an
    empty workspace is for the factory.

    Construction touches nothing: asking for the component is always safe, and
    the member's builder resolves the tree lazily from the deployment's
    artifact store, so composing an application that carries this component
    touches no disk and the tree is read only when a caller demands it.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
