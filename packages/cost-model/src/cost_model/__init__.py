"""``cost_model`` — Z0: the shared cost library's configuration identity.

app_spec.xml, "Cost Model & Fill Simulation", feature 59: *System persists
the resolved cost model version string with its venue name after loading
the YAML configuration.*  docs/nullius-tech-architecture.md §6.2 fixes the
document (a ``cost_model`` block carrying ``version``, ``venue``, the fee
schedule, the fill model, the latency source and the borrow source) and
states the rule that makes the identity matter: *"``cost_model_hash`` is
part of every score's provenance triple"* — so the version string and its
venue are not decoration, they are half of what makes two scores
comparable at all.

This package is the **single shared cost library** §6.2 requires: *"Shared
library used by both the evaluator and the live execution engine.
Divergence between these two is exactly the quantity β₄ penalizes, so they
must be the same code, not two implementations of the same document."*
Feature 59 lands its first half — the configuration identity, loaded from
the YAML document and persisted.  The features that consume it (the fee
schedule of 61-62, the fill model of 63-66, the book walk of 66, the
latency distribution of 67, the borrow series of 68) layer on top of this
package's resolved value rather than beside it, which is what keeps one
schedule from becoming two.

Feature 67 layers onto that identity: *System persists an empirical p50,
p95 and p99 latency distribution measured from shadow runs rather than an
assumed constant.*  It is the ``latency`` section of §6.2's document made
concrete — ``source: measured_from_shadow``, ``distribution:
empirical_p50_p95_p99`` — and it follows the same rule as the identity:
the distribution is measured from the tape and written down, never assumed.
:mod:`cost_model.latency` holds the distribution (the samples and the three
quantiles derived from them) and :mod:`cost_model.latency_store` persists
it, keyed by the ``(venue, version)`` identity feature 59 already persists
and the instant the latency was measured, so a cost model's latency is a
history that accumulates as shadow runs pile up rather than one assumed
number.  It, too, layers on the resolved identity rather than beside it.

This package also *is* a component of the composed application: importing
it registers a builder with the application factory
(``app.module_loader.register``), so the module loader discovers it by
scanning the workspace members the root pyproject.toml declares.  No
central registry, router or app factory is edited to wire it in —
registration happens as an import side effect right here.

The registration lives in this module and deliberately not in a submodule:
``app.module_loader._import_package`` re-executes a package's
``__init__.py`` on every ``create_app()`` call, but a submodule already
cached in ``sys.modules`` under the loader's synthetic name is not
re-executed — so a ``@register`` in a submodule would fire on the first
composition of a process and silently drop out of every later one.

PyYAML is a declared dependency of this member but its import is deferred
to first use (:func:`cost_model.config.require_yaml`), so the factory's
workspace scan — which imports this module to fire the registration below
— does not need a YAML parser installed.  That keeps the member
import-safe in every environment the workspace contract promises one will
be: the factory scan, a test sandbox, the deterministic replay path.
"""

from __future__ import annotations

from app.module_loader import register

from .config import (
    COST_MODEL_KEY,
    COST_MODEL_PATH_ENV,
    DEFAULT_COST_MODEL_PATH,
    CostModelConfig,
    load_cost_model,
    read_cost_model_document,
    require_yaml,
)
from .errors import (
    CostModelConfigError,
    CostModelError,
    CostModelStoreError,
)
from .latency import (
    DEFAULT_QUANTILES,
    QUANTILE_METHOD,
    EmpiricalLatencyDistribution,
    quantile,
)
from .latency_store import (
    LATENCY_TABLE,
    load_latency_distributions,
    load_latest_latency_distribution,
    persist_latency_distribution,
)
from .service import CostModelService, build_cost_model_service
from .store import (
    COST_MODEL_TABLE,
    DATABASE_URL_ENV,
    load_persisted_cost_model,
    persist_cost_model,
)

__all__ = [
    "COMPONENT_NAME",
    "COST_MODEL_KEY",
    "COST_MODEL_PATH_ENV",
    "COST_MODEL_TABLE",
    "DATABASE_URL_ENV",
    "DEFAULT_COST_MODEL_PATH",
    "DEFAULT_QUANTILES",
    "LATENCY_TABLE",
    "QUANTILE_METHOD",
    "CostModelConfig",
    "CostModelConfigError",
    "CostModelError",
    "CostModelService",
    "CostModelStoreError",
    "EmpiricalLatencyDistribution",
    "build_cost_model_service",
    "load_cost_model",
    "load_latency_distributions",
    "load_latest_latency_distribution",
    "load_persisted_cost_model",
    "persist_cost_model",
    "persist_latency_distribution",
    "quantile",
    "read_cost_model_document",
    "require_yaml",
]

__version__ = "0.1.0"

#: The component name this member registers under — the key a composed
#: :class:`~app.module_loader.Application` carries the cost model service
#: at, and the name the seat in the app namespace
#: (``src/app/modules/cost-model``) asks for.  Spelled once here so the
#: member, the factory's registry and the seat cannot drift apart.
COMPONENT_NAME = "cost-model"


@register(COMPONENT_NAME)
def build_cost_model() -> CostModelService:
    """Component builder: the cost model service bound to the environment.

    Takes no arguments — that is the factory's registration protocol — and
    resolves its configuration from the environment at build time, so a
    composed application always carries a service for the document and the
    store the process is actually pointed at
    (``NULLIUS_COST_MODEL_PATH`` and ``DATABASE_URL``, the latter set per
    test by the shared fixtures).

    Construction performs no I/O: the document is read on the first
    ``resolved()``/``load()`` call and the store is opened on the first
    persist, so composing the application never touches a file or a
    database.  The builder names
    :func:`~cost_model.service.build_cost_model_service` rather than
    repeating its body, so the registered builder and the importable symbol
    are one thing.
    """
    return build_cost_model_service()
