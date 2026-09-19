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

from .payload import (
    PAYLOAD_MAGIC,
    PAYLOAD_VERSION,
    MarketWindowPayload,
    NoPayloadError,
    PayloadChannel,
    PayloadFormatError,
    frames_alias_payload,
    window_from_payload,
    serialize_window,
)
from .features import (
    FEATURE_FRAME_PREFIX,
    FeatureAccessError,
    feature_frame_name,
    feature_frame_names,
    parse_feature_frame_name,
    select_feature_frame,
    validate_lookback,
)
from .borrow import (
    BORROW_FRAME_NAME,
    BORROW_REQUIRED_COLUMNS,
    BorrowAccessError,
    check_borrow_frame,
    validate_borrow_lookback,
)
from .bookfeat import (
    BOOKFEAT_FRAME_PREFIX,
    BOOKFEAT_REQUIRED_COLUMNS,
    BookfeatAccessError,
    bookfeat_frame_name,
    bookfeat_frame_names,
    check_bookfeat_frame,
    parse_bookfeat_frame_name,
    select_bookfeat_frame,
    validate_bookfeat_lookback,
)
from .trades import (
    TRADES_FRAME_NAME,
    TRADES_REQUIRED_COLUMNS,
    TradesAccessError,
    check_trades_frame,
    truncate_trades_frame,
    validate_trades_lookback,
)
from .resolution import resolve_universe
from .signal import (
    SIGNAL_ENTRYPOINT,
    SIGNAL_SEED_ARG,
    SIGNAL_SIGNATURE,
    SignalReturnProblem,
    SignalSignature,
    describe_signal_signature,
    validate_signal_return,
    validate_signal_signature,
)
from .version import (
    CONTRACT_VERSION_FIELD,
    NODE_ABI_RECORD_FIELDS,
    Compatibility,
    ContractVersionError,
    NodeAbiRecord,
    compare,
    contract_version,
    describe_contract_version,
    node_abi_record,
    parse_contract_version,
    read_node_abi_record,
    require_supported_contract_version,
)
from .violation import (
    CONTRACT_VIOLATION,
    INDEX_LABEL_FIELD,
    OUTCOME_OK,
    QUOTE_ASSETS,
    SignalReturnOutcome,
    absent_symbol_problems,
    check_signal_return,
    is_symbol_label,
    return_index,
    universe_symbols,
)
from .window import MarketWindow, inspect_accessors

__all__ = [
    "BOOKFEAT_FRAME_PREFIX",
    "BOOKFEAT_REQUIRED_COLUMNS",
    "BORROW_FRAME_NAME",
    "BORROW_REQUIRED_COLUMNS",
    "CONTRACT_VERSION",
    "CONTRACT_VERSION_FIELD",
    "CONTRACT_VIOLATION",
    "FEATURE_FRAME_PREFIX",
    "FeatureAccessError",
    "INDEX_LABEL_FIELD",
    "MARKET_WINDOW_ABI",
    "NODE_ABI_RECORD_FIELDS",
    "OUTCOME_OK",
    "QUOTE_ASSETS",
    "SIGNAL_ENTRYPOINT",
    "SIGNAL_SEED_ARG",
    "SIGNAL_SIGNATURE",
    "TRADES_FRAME_NAME",
    "TRADES_REQUIRED_COLUMNS",
    "BookfeatAccessError",
    "BorrowAccessError",
    "TradesAccessError",
    "Compatibility",
    "ContractVersionError",
    "MarketWindow",
    "MarketWindowPayload",
    "NoPayloadError",
    "NodeAbiRecord",
    "PAYLOAD_MAGIC",
    "PAYLOAD_VERSION",
    "PayloadChannel",
    "PayloadFormatError",
    "SignalReturnOutcome",
    "SignalReturnProblem",
    "SignalSignature",
    "absent_symbol_problems",
    "bookfeat_frame_name",
    "bookfeat_frame_names",
    "build_market_window_contract",
    "check_bookfeat_frame",
    "check_borrow_frame",
    "check_signal_return",
    "check_trades_frame",
    "compare",
    "contract_version",
    "describe_contract_version",
    "describe_signal_signature",
    "feature_frame_name",
    "feature_frame_names",
    "frames_alias_payload",
    "inspect_accessors",
    "parse_feature_frame_name",
    "parse_bookfeat_frame_name",
    "select_feature_frame",
    "select_bookfeat_frame",
    "truncate_trades_frame",
    "validate_borrow_lookback",
    "validate_bookfeat_lookback",
    "validate_lookback",
    "validate_trades_lookback",
    "is_symbol_label",
    "node_abi_record",
    "parse_contract_version",
    "read_node_abi_record",
    "require_supported_contract_version",
    "resolve_universe",
    "return_index",
    "universe_symbols",
    "validate_signal_return",
    "validate_signal_signature",
    "window_from_payload",
    "serialize_window",
]

# The signal ABI version.  Feature 15 of the spec ("System versions the signal
# ABI with a contract_version constant that every stored node persists
# alongside its code hash") builds on this: the constant is declared here, next
# to the ABI it versions, so a persisted node's contract_version can never
# drift from the code it describes.
#
# :mod:`contract.version` is what a node writer actually reaches for — it turns
# this constant into the pair that gets persisted (the stamp beside the code
# hash), answers "is a stored stamp the ABI this build speaks", and refuses to
# persist a stamp no reader could compare.  The constant stays here, one import
# away from the ABI it versions, so the number has exactly one definition.
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
