"""The node metric store's seat in the ``app`` package namespace — feature 130.

app_spec.xml, "Leakage Tripwires", feature 130: *System jitters a declared
lookback by plus or minus 10 percent, persisting perturbation_stability as a
node metric.*  The implementation lives in :mod:`tripwires.lookback` (the
figure) and :mod:`tripwires.node_metric` (its persistence); this module is how
the app package reaches the composed store without importing the member at
module scope.

The member's earlier seats answer *what is the composed tripwire component?*
(:mod:`app.modules.tripwires`), *what is the composed poison store?*
(:mod:`app.modules.tripwires.poison`), *what is the composed replay pool?*
(:mod:`app.modules.tripwires.excise`) and *what is the composed store a
perturbation-stability figure is persisted to?*
(:mod:`app.modules.tripwires.stability`).  This one answers the same shape of
question for the member's sixth component: *what is the composed store a node
metric is persisted to?*

**A fifth seat rather than a second accessor on the stability store's.**  Both
resolve ``DATABASE_URL`` and both persist the same verdict's figure, and that
resemblance is exactly why they must not be reached through one module.
Feature 129's store appends a keyed row to a table it owns and requires no
node row — a figure is legitimately known before the tree is handed the node.
This store updates a column on the node row itself (0114's
``perturb_stability``, the single number the spec's sentence asks to be
readable off the node) and **refuses** a node the tree does not hold, because
a column write is an ``UPDATE`` and an ``UPDATE`` against nothing reports a
metric persisted that no node carries.  A caller asking for one and handed
the other would get an object whose every method means the other feature's
persistence, and the mistake would surface only as a figure missing from the
ledger or a node row never written.

**The ``None`` is the deployment's, not the member's.**  As with the other
store seats: ``None`` means *nothing named a relational store here*, which is
a statement about the deployment rather than about the member, and it is not
the same fact as "the node was never re-run on the lookback axis".  That
second sentence is the one feature 130's refusals exist to make impossible to
blur — :func:`~tripwires.node_metric.record_node_metric` refuses by name when
it resolves no store rather than no-opping, and
:meth:`~tripwires.node_metric.NodeMetricStore.metric_of` refuses a node whose
column is still ``NULL`` — which is why this seat stays silent and hands the
refusal to the caller who actually needs to write.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance.  It deliberately
does **not** re-export the store class, the column name, the error or the
entry points: a caller who has the store calls ``record(...)`` and
``metric_of(...)`` on it, and a second spelling here would be a second thing
to keep in sync.

**Construction touches no database.**  The store resolves its path on first
use, so asking for the component is always safe and the first ``record()`` is
where the file is actually opened — the same promise the member's builder
makes, and the reason composing an application never has the side effect of
creating a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from tripwires import NodeMetricStore

__all__ = ["COMPONENT_NAME", "node_metric_store_component"]

#: The component name the tripwires member registers its node metric store
#: under.  Kept here as well as in the member — the member's other seats each
#: spell their own name twice for the same reason, and ``test_component.py``
#: asserts the two agree — so the two cannot drift apart silently.
COMPONENT_NAME = "tripwires-node-metric"


def node_metric_store_component(app: Application | None = None) -> NodeMetricStore | Any:
    """Return the composed node metric store (feature 130's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``tripwires-node-metric`` component is registered.

    That ``None`` is a statement about the deployment rather than about the
    member: nothing named ``DATABASE_URL``, so there is no relational store
    for a node metric to be written to.  It is deliberately **not** the same
    fact as the stability seat's ``None``, which is the same deployment fact
    about a different table and a different refusal — and not "the node's
    ``perturb_stability`` is still ``NULL``" either, which is a fact about a
    node the caller has not named yet and is refused by name at the store.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
