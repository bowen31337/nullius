"""``contract`` — Z0: the MarketWindow contract and the signal ABI.

Immutable and versioned (docs/nullius-tech-architecture.md §5.1, §19).  This
package is the boundary between the host and LLM-authored code: a signal sees a
:class:`MarketWindow` and nothing else, and the window it sees physically
cannot return data after the decision time.

This package also *is* a component of the composed application: importing it
registers a builder with the application factory
(``app.module_loader.register``), so the module loader discovers it by scanning
the workspace members the root pyproject.toml declares.  No central registry,
router or app factory is edited to wire it in — registration happens as an
import side effect right here.
"""

from __future__ import annotations

from app.module_loader import register

from .window import MarketWindow

__all__ = [
    "CONTRACT_VERSION",
    "MARKET_WINDOW_ABI",
    "MarketWindow",
    "build_market_window_contract",
]

# The signal ABI version.  Feature 15 of the spec ("System versions the signal
# ABI with a contract_version constant that every stored node persists
# alongside its code hash") builds on this: the constant is declared here, next
# to the ABI it versions, so a persisted node's contract_version can never
# drift from the code it describes.
CONTRACT_VERSION = "0.1.0"


#: Where the ABI lives, as a stable importable reference (``module:attribute``).
#:
#: The component advertises the ABI *by name* rather than by handing back the
#: class object, and that is deliberate.  The module loader imports a scanned
#: package under a synthetic name (``_nullius_scanned_<dir>``), so the class
#: object it would return is a *different* class from
#: ``contract.MarketWindow`` as imported normally — two module objects, two
#: classes, and an ``isinstance`` check that silently returns False across the
#: seam.  A name is immune to that: whoever needs the ABI imports it, and gets
#: the one that is already on ``sys.path``.
MARKET_WINDOW_ABI = "contract:MarketWindow"


@register("contract")
def build_market_window_contract() -> dict:
    """Contribute the contract component to the composed application.

    The factory calls this during :func:`app.module_loader.create_app`.  It
    returns a plain, serializable dict — the factory's default reducer folds
    builder results into a dict keyed by component name, and a component must
    never reach back and mutate the factory or the application it returns.
    """
    return {
        "contract_version": CONTRACT_VERSION,
        "market_window": MARKET_WINDOW_ABI,
    }
