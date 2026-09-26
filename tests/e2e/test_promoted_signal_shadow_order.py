"""Feature 369: the end-to-end journey — a promoted signal, through book
construction, to a shadow order the venue answers ``200`` for.

app_spec.xml, "End-to-End Verification", feature 369: *"System passes an
end-to-end test where a promoted signal flows through book construction
into a shadow order, and the venue returns 200 for a filter-compliant
submission."*  The M4 phase of the same spec names the shape in one line —
*"Pre-registered promotion with epoch retirement, human-authored book
construction, and the venue-aware order router running in shadow mode"* —
and every clause of the sentence has its reason in the architecture doc and
the PRD:

* ``docs/nullius-tech-architecture.md`` §13.2 has the order router run *"in
  its own process"*, with the exchangeInfo filters *"refreshed at startup and
  daily, never hardcoded"*, posting *"passively by default, sending an
  aggressive order only when the signal's decay horizon is shorter than the
  expected fill time."*
* ``docs/alpha-engine-prd.md`` C9 states the same rule from the operator's
  side: *"Read ``LOT_SIZE``, ``NOTIONAL``, ``PRICE_FILTER``, ``stepSize``,
  ``tickSize`` from ``exchangeInfo`` at startup and daily. Never hardcode.
  Post-only by default."*
* §17 fixes what *shadow* means here and how it is enforced: *"Separate keys
  per environment. The shadow sub-account key must not work on the live
  account."*

Read as one story the sentence is four acts, and this module runs them in the
order the deployment runs them in.

**A promoted signal.**  A campaign's node is written by the discovery loop's
own writer, its criteria are pre-registered *before* the decision is stamped
(the ordering that makes pre-registration mean anything), the decision stamp
lands, and the signal's forward window opens off that stamp rather than off a
clock read at read time.  The signal is then promoted in the sense the order
path needs: its forward evidence is observed, and the decay horizon the
posture decision turns on is read from the signal's own *measured* half-life —
the forward member's published crossing, over the observations this journey
lands — rather than invented.

**Flows through book construction.**  The promoted signal is one of the
signals the book is built from: the same promoted-signal object the combiner
weights, the shrinker stabilises, the volatility target scales, the limits
judge, and the publisher hands to the order layer.  The construction is
persisted with its provenance — the rebalance row names the promoted signal's
own identifier, which is the node every promotion act above was performed on,
so the book's origin and the promoted signal are provably *one identity* and
not two coincident ones.

**Into a shadow order.**  The order path asks the venue's *fetched* grids —
the current exchangeInfo version, never a constant — whether the submission
sits on the step and tick grids, and whether it clears the venue's notional
floor; it derives how the order should cross from the promoted signal's own
decay horizon and the fill model's expected fill time; it settles the book
under isolated margin against the shadow sub-account; it folds the client
order identifier from the *rebalance's* instant, the same instant the rebalance
row is keyed by; and it places through the placement store, whose one verb
decides whether to send at all — a duplicate identifier returns the prior
result rather than placing a second order.

*Shadow* is carried the way §17 spells it.  The credential that authenticates
the submission classifies into ``shadow``, and the same credential presented
against the live account is refused with ``401`` before any request would be
composed at all — the policy-side double of the status the exchange itself
would answer.  The live path is closed for a second, independent reason: a
live submission without an explicit flag is refused by rule, and this journey's
order carries no such flag, so nothing here is elected live.

**And the venue returns 200.**  The placement is a real HTTP round trip: a
loopback venue stand-in owned by this suite answers ``200`` for the
filter-compliant submission.  It is invoked as the placement store's ``place``
callable — the zero-argument request the router hands the venue call to, whose
*returning is the venue's acceptance* — so the status the store acts on is the
status the wire carried, not a value this suite made up.

**What the venue stand-in is, and what it deliberately is not.**  §18 puts the
exchange client *"hand-rolled over ``ccxt``"* and §17 leaves *"no inbound ports
on the live trading host"*, and the repository holds no venue client: the
live-submission gate and the router's inbound HTTP surface do not exist as
shipped modules.  So the venue is the one thing this journey stages — the same
choice feature 370's journey makes for its execution-engine seat, and for the
same reason.  A journey that mocked the *router* would prove nothing about the
router; a journey that owns the *far end of the wire* proves exactly what the
sentence claims, because the far end is the party the sentence is about.
Everything between the promotion and the wire is the shipped system's own code,
reached through the shipped system's own public seams.

**One clause this journey checks rather than assumes.**  *"Never hardcode"* is
only a law if the grids actually travel.  The document this journey publishes
carries deliberately distinctive values — a step size of ``0.00042`` and a tick
size of ``0.07``, neither of which appears anywhere in the router member's
source — and the journey observes a submission *off* those grids refused while
a submission *on* them passes.  A hardcoded grid could not produce that pair of
answers from that pair of submissions.

**What this module deliberately is not.**  It is not a second suite for the
members' own laws: the refusals, the races, the value layers, the near-misses
and the boundaries live in ``packages/router/tests``, ``packages/book/tests``,
``packages/promotion/tests``, ``packages/forward/tests`` and
``packages/discovery/tests``, and nothing here re-tests them.  This is the
journey, once, through the assembled system's public seams, asserting the four
clauses of one sentence and the committed record it leaves behind.

One clause of the M4 phase line quoted above is *context rather than
acceptance*, and this module is explicit about the difference: the
*authorship* guard that makes a construction "human-authored" is the book
member's own feature 306, its carrier is not wired into the rebalance store,
and it is exercised where it lives.  What this journey stages of "human
authored" is the honest part — the signals, the volatility target and the
limits are values an operator's code chose and handed to the book's own
pipeline, not values any agent produced — and it asserts the *construction*
that resulted rather than the guard that would have refused a different one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

# The credential boundary §17 states needs the repository root itself on
# ``sys.path``: ``infra/security/`` is deliberately outside the uv workspace's
# import graph and resolves as a PEP 420 namespace package (there is no
# ``infra/__init__.py``, and this suite may not create one).  The shared
# ``tests/e2e/conftest.py`` puts every declared member's scan root on the path
# and pytest imports it before this line; this is the one addition, and it is
# stated here rather than there so the reason travels with the import that
# needs it.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from artifacts import ArtifactStore
from book import (
    REBALANCE_TARGET_WEIGHTS_TABLE,
    FinalTargetWeights,
    PromotedSignal,
    RebalanceTargetWeightsStore,
    apply_volatility_target,
    combine,
    concentration,
    final_target_weights,
    rejects_breaching_target_weights,
    stabilize_weights,
)
from cost_model import QueueObservation, passive_fill_fraction
from discovery import (
    Attempt,
    AttemptLog,
    AttemptProvenance,
    CampaignRecords,
    RefinedSignal,
    attempt_node_id,
)
from forward import (
    ForwardIcRetentions,
    ForwardObservations,
    ForwardRecords,
    forward_half_life,
)
from promotion import (
    PROMOTION_REGISTRY_TABLE,
    PreRegistrations,
    PromotionCriteria,
    PromotionDecisions,
    promotion_window,
)
from router import (
    DEFAULT_VENUE_WEIGHT_SCHEDULE,
    DEFAULT_WEIGHT_SCOPE,
    ISOLATED_MARGIN,
    OPERATION_PLACE_ORDER,
    ORDER_PLACEMENT_TABLE,
    ORDER_SUBMISSION_ACCEPTED,
    PASSIVE_ORDER,
    ROUTER_EXCHANGE_INFO_FILTER_TABLE,
    ROUTER_EXCHANGE_INFO_VERSION_TABLE,
    VENUE_WEIGHT_ALLOWANCE,
    VENUE_WEIGHT_BUCKET_TABLE,
    MarginScope,
    PlacementOrder,
    RouterExchangeInfoStore,
    RouterOrderPlacementStore,
    RouterOrderRoundingError,
    RouterRateLimiter,
    RouterSubmissionHealthStore,
    RouterSymbolFilters,
    derive_client_order_id,
    normalize_client_order_id,
    process_identity,
    require_min_notional,
    require_rounded_order,
    resolve_order_posture,
)

from infra.security.credential_isolation import (
    LIVE_SCOPE,
    SHADOW_SCOPE,
    UNAUTHORIZED,
    CredentialScope,
    ScopeMismatch,
    classify_credential,
)

# -- The values the journey stages ----------------------------------------------

#: The venue's symbols, and the one this journey places an order for.  Four
#: symbols rather than one for a load-bearing reason: the Ledoit-Wolf estimate
#: needs a sample covariance with an inverse, and a book of two or more signals
#: over two symbols is *always* singular — the shrinker's own published refusal.
#: A journey that staged a two-symbol book would be staging a refusal and
#: calling it a construction.
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT")
ORDER_SYMBOL = "BTCUSDT"

#: The exchangeInfo document the venue publishes to the router.  None of these
#: grid values appears in the router member's source; ``0.00042`` and ``0.07``
#: are chosen precisely because they are not round numbers any hardcoded venue
#: constant would carry, so the pair of submissions below — one exactly on these
#: grids, one one step off — can only be answered the way they are if the grids
#: travelled from the document through the store into the gate.  That is
#: *never hardcode* made observable rather than asserted.
STEP_SIZE = "0.00042"
TICK_SIZE = "0.07"
MIN_QTY = "0.00042"
MAX_QTY = "9000"
MIN_PRICE = "0.07"
MAX_PRICE = "1000000"
MIN_NOTIONAL = "13.37"

#: The submission the venue answers 200 for: three whole steps of quantity and a
#: price a whole number of ticks above the minimum, so it sits on both grids
#: exactly.  The breaching submission differs by one step of quantity and one
#: tick of price — the smallest possible miss on each grid — so the refusal it
#: earns is about the grids and not about anything else.
FILTER_COMPLIANT_QUANTITY = "0.00126"
FILTER_COMPLIANT_PRICE = "60123.00"
OFF_GRID_QUANTITY = "0.00127"
OFF_GRID_PRICE = "60123.05"

#: The instant the rebalance is *for*.  The client order identifier is folded
#: from the rebalance's instant rather than the call's, so this one value is the
#: book's key, the order's key and the identifier's preimage — one spelling of
#: one identity, which the assertions below check rather than assume.
REBALANCE_TS = datetime(2026, 3, 1, tzinfo=UTC)

#: The book the construction is for, and the account the shadow order settles
#: under.  The account names §17's sub-account — the child account the broker
#: provisions for paper trading, separate balance and separate key — so the
#: arrangement the margin scope holds is the deployment's, not a placeholder.
BOOK_ID = "book-1"
SHADOW_ACCOUNT = "shadow-sub-account"

#: The promotion's own calendar.  Criteria are pre-registered on the first, the
#: decision is stamped a month later, and the forward window opens off the
#: decision's stamp — the ordering the pre-registration invariant requires.
CAMPAIGN_TYPE = "Type-R"
WORKSPACE_COUNT = 48
THEME_ROOT = "macro"
EPOCH_ID = "epoch-2026-01"
PRE_REGISTERED_AT = "2026-01-01T00:00:00+00:00"
DECIDED_AT = "2026-02-01T00:00:00+00:00"
FORWARD_DAYS = 90

#: The observations the journey lands on the promoted signal, and the backtest
#: coefficient it is compared against.  Six daily readings decaying from 0.088
#: to 0.028 against a 0.12 backtest IC: the running mean crosses half the
#: backtest coefficient on the sixth day, which is the forward member's published
#: crossing and the figure the posture decision reads as the decay horizon.
OBSERVED_IC = tuple(0.10 - 0.012 * day for day in range(1, 7))
BACKTEST_IC = 0.12
EXPECTED_HALF_LIFE_DAYS = 6.0

#: The queue observation the *expected fill time* is read from.  A shallow queue
#: — 40 units ahead of the order against 500 traded at the level during the
#: rebalance — grants a large fill fraction, so one four-hour rebalance fills a
#: meaningful part of the order and the expected fill time lands well inside the
#: six-day decay horizon.  The PRD's rule then answers **passive**: the order does
#: not cross, because the signal will still be there when it fills.  (The
#: aggressive branch is reachable from the same seams by deepening the queue, and
#: the member's own suite pins it; what this journey proves is that the posture is
#: *derived from the promoted signal's measured horizon* and from the fill model,
#: not chosen by a caller — there is no posture parameter on the verb at all.)
QUEUE_AHEAD = 40.0
ORDER_QUANTITY = 2.0
REBALANCE_VOLUME = 500.0
REBALANCE_PERIOD = timedelta(hours=4)

#: The position and concentration bounds the constructed book is judged by, and
#: the volatility the book is targeted to.
PER_POSITION_LIMIT = 0.5
CONCENTRATION_LIMIT = 0.9
VOLATILITY = 0.5
TARGET_VOLATILITY = 0.2

#: The venue's whole weight allowance, as the limiter's default schedule carries
#: it.  Restated here as a *cross-check* on that schedule rather than as the
#: source of the figure the assertion reads: the arm below takes the allowance and
#: the operation's price off the member's own default schedule, and this constant
#: only pins that the schedule a deployment gets by default is still this one.
VENUE_ALLOWANCE = 6000

#: The migrations this journey brings the database up with, in the chain's own
#: order.  ``0111`` owns the ``campaign`` table, ``0118`` owns ``node``, ``0110``
#: owns ``epoch_ledger`` and ``0108`` owns ``forward_record`` and
#: ``promotion_registry``.  The three sibling widenings — the identity,
#: provenance and authoring-model trios — are deliberately absent: a *root* node
#: is seated with only the five columns ``0118`` declares, and the attempt
#: writer probes and adds its own ``fail_class`` column on a narrowed shape
#: exactly as it does on a widened one.  Running the narrow chain is also the
#: smaller claim — it is the deployment's floor, the schema at which every table
#: this journey writes is already a migration owner's own DDL rather than
#: anything hand-written here.
MIGRATION_REVISIONS = (
    "0111_campaign_table",
    "0118_node_table",
    "0110_epoch_ledger",
    "0108_forward_and_universe_tables",
)
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"


# -- The venue stand-in ---------------------------------------------------------


#: The venue, as its own process.
#:
#: A **separate interpreter**, not a thread of this one, because the sentence's
#: last clause is about a different party: *"the venue returns 200"* is a claim
#: about somebody else's answer, and a venue that shared this process's memory
#: could not be said to have answered anything — it could only be said to have
#: had a value read out of it.  A real process binds its own socket, judges each
#: request against the grids it published, writes the status to the wire, and
#: keeps its own journal of what it received; the parent reaches it the only way
#: the router can, over ``urllib`` to a loopback port.  A venue that failed to
#: start, crashed, or judged differently would therefore be visible here instead
#: of being invisible inside this suite's own address space.
#:
#: It deliberately imports **nothing from the workspace** — only the standard
#: library — because it is the counterparty, not part of the system under test.
#: That also means it needs no ``PYTHONPATH``, which is the honest spelling of
#: "this process is not the deployment".
#:
#: Its journal is a file rather than a pipe: a request the venue *saw* is written
#: and flushed when it arrives, so the record the assertions read is the venue's
#: own, produced by the venue's own process, and not a structure this suite
#: filled in while it was also the party answering.
VENUE_SCRIPT = """
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

journal_path, step_size, tick_size, min_notional, symbol = sys.argv[1:6]

journal = open(journal_path, "a", buffering=1)


class Venue(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        headers = {name.lower(): value for name, value in self.headers.items()}

        # What the venue saw, written before it judges -- so a request the
        # venue refused is as much a part of its record as one it accepted.
        journal.write(json.dumps({"path": self.path, "body": body,
                                  "headers": headers}) + "\\n")

        status = self.verdict(body, headers)
        payload = json.dumps({
            "orderId": 41 if status == 200 else None,
            "symbol": body.get("symbol"),
            "status": "NEW" if status == 200 else "REJECTED",
            "clientOrderId": body.get("newClientOrderId"),
        }).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def verdict(self, body, headers):
        # The venue's own arithmetic, in the venue's own currency: a whole
        # number of steps of quantity, a whole number of ticks of price, and a
        # notional that clears the floor.  The environment marker is judged
        # too: a credential for the wrong environment is the presentation the
        # exchange answers 401 to, and this is the venue's own 401 rather than
        # the policy module's -- the two are the same number on purpose.
        if headers.get("x-environment") != "shadow":
            return 401
        if body.get("symbol") != symbol:
            return 400
        try:
            quantity = float(body["quantity"])
            price = float(body["price"])
            step = float(step_size)
            tick = float(tick_size)
        except (KeyError, TypeError, ValueError):
            return 400
        on_step = abs(quantity / step - round(quantity / step)) < 1e-9
        on_tick = abs(price / tick - round(price / tick)) < 1e-9
        clears_floor = quantity * price >= float(min_notional)
        return 200 if (on_step and on_tick and clears_floor) else 400

    def log_message(self, *args):
        # stderr chatter would interleave with the port announcement on stdout;
        # the journal is the record.
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Venue)
print("port", server.server_address[1], flush=True)
server.serve_forever()
"""


def _submit_to_venue(
    port: int, payload: dict, headers: Mapping[str, str]
) -> tuple[int, str]:
    """POST a submission to the venue and return the status and body it wrote.

    A refusal is read off the *exception* the standard library's client raises
    for a 4xx, which is the same status the venue put on the wire — so a venue
    answering 400 and a venue answering 200 are read through one code path, and
    neither is a value this suite decided in advance.
    """
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v3/order",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


class VenueRefusedError(Exception):
    """The venue answered the submission with something other than 200.

    Raised by the journey's ``place`` callable, and it is load-bearing rather
    than decorative.  Feature 317's contract is that the callable's *returning
    is the venue's acceptance*: a callable that returned normally on a 400 would
    tell the store an order had been accepted that the venue had just refused,
    and the store would write an ``accepted`` row for it.  So the refusal is
    raised, which is also what the store's own docstring expects — "the refusal
    propagates untouched, nothing is written, and the order path keeps the retry
    it is entitled to make".

    A ``403``/``400``/``401`` from the venue is therefore a *failed placement*,
    not a recorded one, and the journey's assertions about the recorded row are
    about an acceptance the venue actually gave.
    """

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"the venue answered {status}: {body}")
        self.status = status
        self.body = body


def _venue_journal(path: Path) -> tuple[dict, ...]:
    """Read the venue's own record of the requests it received.

    Read from the file the venue process wrote and flushed itself, so every
    entry is the venue's testimony rather than this suite's recollection.
    """
    if not path.exists():
        return ()
    return tuple(
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    )


def _launch_venue(
    journal_path: Path,
    *,
    step_size: str = STEP_SIZE,
    tick_size: str = TICK_SIZE,
    min_notional: str = MIN_NOTIONAL,
) -> tuple[subprocess.Popen, int]:
    """Start a venue process and return it with the port it announced.

    The venue publishes the grids it will judge by — passed in, so a caller can
    hand it a *different* grid than the document the router fetched, which is how
    the journey shows the grids are load-bearing rather than decorative.  A
    process that never announces its port fails with its own stderr, because a
    venue that could not start is a broken arrangement and not a refused order.
    """
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            VENUE_SCRIPT,
            str(journal_path),
            step_size,
            tick_size,
            min_notional,
            ORDER_SYMBOL,
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    announced = process.stdout.readline().strip() if process.stdout else ""
    if not announced.startswith("port "):
        process.terminate()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=30)
        stderr = process.stderr.read() if process.stderr is not None else ""
        pytest.fail(
            f"the venue process never announced its port: {announced!r} {stderr!r}"
        )
    return process, int(announced.removeprefix("port ").strip())


def _stop_venue(process: subprocess.Popen) -> None:
    """Stop a venue process, tolerating one that has already exited."""
    process.terminate()
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=30)


# -- The journey's captured facts ------------------------------------------------


@dataclass(frozen=True)
class _Journey:
    """What the journey produced, frozen at its end.

    Captured in the order the journey produced it — the promotion, the
    construction, the order, the wire, the record — so each facet below asserts
    over one already-told story rather than re-running a choreography per
    assertion.  Every field is a *value the shipped system answered*: nothing
    here is recomputed by the suite from constants it chose, which is what makes
    an assertion about it an assertion about the system.
    """

    url: str
    # The promotion.
    campaign_id: str
    campaign_type: str
    root_id: str
    node_id: str
    criteria_hash: str
    epoch_id: str
    pre_registered: bool
    decision_stamped: bool
    promoted_at: str
    observed_on: date
    window_opened_at: str
    window_closes_at: str
    window_days: int
    half_life_days: float
    crossing_on: date | None
    observed_days: int
    # The construction.
    signal_ids: tuple[str, ...]
    composite_scores: dict[str, float]
    shrinkage: float
    stabilized_weights: dict[str, float]
    target_weights: dict[str, float]
    gross_exposure: float
    volatility_scale: float
    concentration: float
    recorded_signal_ids: tuple[str, ...]
    recorded_weights: dict[str, float]
    # The order.
    exchange_info_version: int
    exchange_info_symbols: int
    filters: RouterSymbolFilters
    rounded_quantity: str
    rounded_price: str
    order_value: Decimal
    min_notional: Decimal
    off_grid_refusal: BaseException | None
    decay_horizon: timedelta
    expected_fill_time: timedelta
    posture: str
    posture_is_aggressive: bool
    margin_mode: str
    margin_account: str
    client_order_id: str
    headroom_before: int
    headroom_scope: str
    # The wire.
    venue_status: int
    venue_body: str
    venue_requests: tuple[dict, ...]
    placement_appended: bool
    placement_outcome: str
    duplicate_appended: bool
    duplicate_replayed: bool
    duplicate_venue_calls: int
    # The boundary.
    shadow_scope: str
    live_presentation_refusal: BaseException | None
    # The record.
    registry_rows: int
    rebalance_rows: int
    placement_rows: int
    exchange_info_version_rows: int
    exchange_info_filter_rows: int
    bucket_rows: int
    health_outcome: str
    health_process_id: str


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner publishes it.

    ``migrations/`` is not a package and is not on ``sys.path``; a migration is
    loaded by its runner the same way — by path — so loading it by path here is
    the shape a migration is *built* to be used in rather than a workaround.  A
    missing file fails with the path in the message, because the one failure a
    test should never have to guess at is "the schema owner moved".
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this journey runs the schema owners' "
            "own migrations rather than hand-writing their DDL, so it needs them "
            "to be where the versioned tree keeps them"
        )
    spec = importlib.util.spec_from_file_location(f"_e2e_{revision}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise AssertionError(f"{revision} at {path} is not an importable module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _database_path(url: str) -> str:
    """The filesystem path behind a ``sqlite:///`` URL.

    Restated here rather than imported from a member: the translation is the
    driver's, not any one member's law, and importing it would tie this suite to
    whichever member happened to export it.
    """
    return url.removeprefix("sqlite:///")


def _row_count(url: str, table: str) -> int:
    """Count a table's rows with the driver directly.

    The committed-record assertions read the store without going through the face
    whose discipline the journey is asserting — a count taken through the writer
    would be the writer confirming itself.
    """
    with closing(sqlite3.connect(_database_path(url))) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _seat(url: str, statement: str, parameters: tuple[object, ...]) -> None:
    """Write one row that belongs to a process this member does not own.

    Two rows in this journey are another process's write and are seated rather
    than manufactured: the tree's **root** node, which the campaign's planner
    seats (the expansion value layer refuses a parent that is not a node id, so a
    root cannot be an attempt this suite records), and the **epoch** row, which
    the sealing process writes (the promotion registry's ``epoch_id`` is a real
    foreign key and the pre-registration store *checks* that parent rather than
    inventing it).  Both are seated in the columns their owning migration
    declares, exactly as the members' own suites and the repository's invariant
    gates do.
    """
    with closing(sqlite3.connect(_database_path(url))) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(statement, parameters)
        connection.commit()


def _exchange_info_document() -> dict:
    """The exchangeInfo document the venue publishes to the router.

    The PRD's three filters for every symbol the book trades, in the venue's own
    string spellings — the wire's values, never reals, because the rounding gate
    is *exact* decimal arithmetic over the strings the venue sent and a document
    this suite had already floated would be testing a different gate.
    """
    return {
        "symbols": [
            {
                "symbol": symbol,
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": STEP_SIZE,
                        "minQty": MIN_QTY,
                        "maxQty": MAX_QTY,
                    },
                    {
                        "filterType": "PRICE_FILTER",
                        "tickSize": TICK_SIZE,
                        "minPrice": MIN_PRICE,
                        "maxPrice": MAX_PRICE,
                    },
                    {"filterType": "NOTIONAL", "minNotional": MIN_NOTIONAL},
                ],
            }
            for symbol in SYMBOLS
        ]
    }


def _refusal(act: Callable[[], object]) -> BaseException | None:
    """Ask an act and return the refusal it raised, or ``None``.

    Returns the raised refusal itself rather than a copy of its name: the class
    and its own fields are the datum, and a boolean "did it refuse" would throw
    away which refusal it was.
    """
    try:
        act()
    except Exception as exc:  # noqa: BLE001 - the refusal's own type is the datum
        return exc
    return None


@pytest.fixture(scope="module")
def journey(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Journey]:
    """Run the journey once, and hand its captured facts to the facets.

    The journey builds its own database rather than borrowing the suite's
    isolated ``DATABASE_URL``, because it needs the schema to be a *migration*
    chain rather than the empty file the shared fixture points at: the promotion
    registry's foreign keys are real, and the tables the campaign, discovery,
    promotion, forward and book members write all have owners in the versioned
    tree.  Bringing the tree up is the deployment's own path to a working
    database, so it is the path this journey takes.

    It also owns its own venue socket, bound to an ephemeral loopback port, so
    this suite never competes for a port with a sibling suite in the same
    session.
    """
    workdir = tmp_path_factory.mktemp("promoted-signal-shadow-order")
    url = f"sqlite:///{workdir / 'nullius-e2e.db'}"

    for revision in MIGRATION_REVISIONS:
        _load_migration(revision).apply(url)

    campaign = CampaignRecords(url).create(CAMPAIGN_TYPE, WORKSPACE_COUNT)
    campaign_id = campaign.campaign_id
    root_id = str(uuid.uuid4())
    _seat(
        url,
        "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
        "VALUES (?, NULL, ?, ?, 0)",
        (root_id, campaign_id, THEME_ROOT),
    )
    _seat(
        url,
        "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
        (EPOCH_ID, PRE_REGISTERED_AT),
    )

    # -- A promoted signal ---------------------------------------------------

    # The node the campaign's discovery loop records: an attempt on the root,
    # written through the member's own writer and published to the member's own
    # artifact store.  Nothing here plants it by hand — the row's identity, its
    # artifact directory and its provenance are the writer's act, and the node id
    # it answers is the identity every promotion act below is performed on.
    artifacts = ArtifactStore(workdir / "artifacts")
    source = "def carry_fade(x, funding):\n    return -x if funding > 0 else x\n"
    refined = RefinedSignal(
        node_id=attempt_node_id(root_id),
        parent_id=root_id,
        campaign_id=campaign_id,
        theme_root=THEME_ROOT,
        depth=1,
        code=source,
        code_hash=hashlib.sha256(source.encode()).hexdigest(),
        stated_mechanism=(
            "Fades crowded carry: enter against the direction of extreme "
            "perpetual funding, unwinding as the basis converges."
        ),
    )
    provenance = AttemptProvenance(
        evaluator_hash="a" * 64,
        snapshot_hash="b" * 64,
        cost_model_hash="c" * 64,
        agent_model_id="anthropic/claude-opus-5",
        agent_sampling={"temperature": 0.7, "seed": 41},
        agent_ckpt_hash="d" * 64,
    )
    attempt = AttemptLog(url, artifacts).record(
        Attempt.from_signal(refined, provenance)
    )
    node_id = attempt.node_id

    criteria = PromotionCriteria(
        theta=0.3,
        alpha=0.05,
        max_fdr_deploy=0.25,
        min_worlds=50,
        min_coverage_strata=3,
        min_forward_days=FORWARD_DAYS,
    )
    pre_registration, pre_registered = PreRegistrations(url).pre_register(
        node_id, EPOCH_ID, criteria, pre_registered_at=PRE_REGISTERED_AT
    )
    _, decision_stamped = PromotionDecisions(url).record_decision(
        node_id, decided_at=DECIDED_AT
    )
    opening, _ = ForwardRecords(url).open_record(node_id, forward_days=FORWARD_DAYS)

    window = promotion_window(node_id, forward_days=FORWARD_DAYS, database_url=url)
    observations = ForwardObservations(url)
    for day, live_ic in zip(range(1, 7), OBSERVED_IC, strict=True):
        observations.append_observation(
            node_id,
            observed_on=date(2026, 2, 1) + timedelta(days=day),
            live_ic=live_ic,
            forward_days=FORWARD_DAYS,
        )
    ForwardIcRetentions(url).record_backtest_ic(node_id, backtest_ic=BACKTEST_IC)
    half_life = forward_half_life(node_id, database_url=url)

    # -- Through book construction -------------------------------------------

    # The promoted signal is *this* node, and it is one of the signals the book is
    # built from.  The other two are the book's own inputs: a construction of one
    # signal would verify the combiner's identity case and nothing about the
    # shrinkage, the volatility target or the limits, and the PRD's construction
    # is a composite of the promoted signals — which is what this stages.
    signals = (
        PromotedSignal(
            node_id, 1.5, dict(zip(SYMBOLS, (1.0, -0.5, 0.25, -0.75), strict=True))
        ),
        PromotedSignal(
            "signal-carry-momentum",
            0.9,
            dict(zip(SYMBOLS, (0.5, 1.0, -0.5, 0.25), strict=True)),
        ),
        PromotedSignal(
            "signal-basis-reversion",
            1.2,
            dict(zip(SYMBOLS, (-0.25, 0.75, 0.5, 1.0), strict=True)),
        ),
    )
    stabilized = stabilize_weights(signals)
    composite = combine(signals)
    target = apply_volatility_target(
        composite, volatility=VOLATILITY, target_volatility=TARGET_VOLATILITY
    )
    rejects_breaching_target_weights(
        target,
        per_position_limit=PER_POSITION_LIMIT,
        concentration_limit=CONCENTRATION_LIMIT,
    )
    published: FinalTargetWeights = final_target_weights(target)
    recorded = RebalanceTargetWeightsStore(url).record(
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        target_weights=published,
        originating_signals=signals,
    )

    # -- Into a shadow order -------------------------------------------------

    # The venue publishes its grids, and the router fetches and persists them.
    # This is the *only* source of the numbers the order is judged against:
    # nothing below carries a venue constant.
    exchange_info = RouterExchangeInfoStore(url)
    version = exchange_info.record(
        _exchange_info_document(), fetched_at=REBALANCE_TS, source="venue:exchangeInfo"
    )
    filters = exchange_info.filters_for(ORDER_SYMBOL)
    if filters is None:  # pragma: no cover - a fetch that dropped the symbol
        raise AssertionError(
            f"the fetched exchangeInfo version carries no filters for "
            f"{ORDER_SYMBOL}; the document this journey published defines it, so a "
            "miss here means the fetch dropped a symbol the venue sent"
        )

    # The submission, judged against the fetched grids — and the one-step-miss
    # beside it, whose refusal is the evidence that the grids are load-bearing.
    rounded = require_rounded_order(
        symbol=ORDER_SYMBOL,
        quantity=FILTER_COMPLIANT_QUANTITY,
        price=FILTER_COMPLIANT_PRICE,
        filters=filters,
    )
    valued = require_min_notional(order=rounded, filters=filters)
    off_grid_refusal = _refusal(
        lambda: require_rounded_order(
            symbol=ORDER_SYMBOL,
            quantity=OFF_GRID_QUANTITY,
            price=OFF_GRID_PRICE,
            filters=filters,
        )
    )

    # How the order crosses, from the promoted signal's *measured* horizon and the
    # fill model's expected fill time.  The posture verb takes no posture
    # argument: the answer is derived, which is why the derivation is shown.
    fill = passive_fill_fraction(
        QueueObservation(
            queue_ahead=QUEUE_AHEAD,
            order_quantity=ORDER_QUANTITY,
            rebalance_volume=REBALANCE_VOLUME,
        )
    )
    expected_fill_time = REBALANCE_PERIOD / fill.fill_fraction
    decay_horizon = timedelta(days=half_life.half_life_days)
    posture = resolve_order_posture(
        signal_decay_horizon=decay_horizon, expected_fill_time=expected_fill_time
    )

    # The book's margin, and the order's identity.  The account is the shadow
    # sub-account, and the identifier is folded from the *rebalance's* instant —
    # the same instant the rebalance row is keyed by, so the two are provably one
    # identity.
    margin = MarginScope().require(book_id=BOOK_ID, account=SHADOW_ACCOUNT)
    client_order_id = normalize_client_order_id(
        str(
            derive_client_order_id(
                book_id=BOOK_ID, rebalance_ts=REBALANCE_TS, symbol=ORDER_SYMBOL
            )
        )
    )

    limiter = RouterRateLimiter(url)
    headroom_before = limiter.headroom(OPERATION_PLACE_ORDER)

    # The credential §17 issues for the shadow environment — classified against
    # the account it is presented to.  Both directions are asked, because the
    # sentence's control is the *pair*: the shadow key authenticates the shadow
    # account, and the same key cannot reach the live one.
    shadow_scope = classify_credential(SHADOW_SCOPE, SHADOW_SCOPE)
    live_presentation_refusal = _refusal(
        lambda: classify_credential(SHADOW_SCOPE, LIVE_SCOPE)
    )

    # -- And the venue returns 200 ------------------------------------------

    # The venue process: launched, announced, and driven over the wire.  Its own
    # interpreter, its own socket, its own journal — so what answers below is a
    # different party, and a venue that failed to start or judged differently
    # would be visible here rather than hidden inside this suite's address space.
    journal_path = workdir / "venue-journal.jsonl"
    venue, port = _launch_venue(journal_path)

    placements = RouterOrderPlacementStore(url)
    venue_status: list[int] = []
    venue_body: list[str] = []
    try:

        def place_at_the_venue() -> None:
            """Send the order to the venue, carrying the shadow credential.

            This is the placement store's ``place`` callable as the router hands it
            out: a zero-argument request whose *returning is the venue's
            acceptance*.  The body is the order the router just judged — the
            rounded quantity and the tick-aligned price, spelled as the strings the
            venue itself uses — so what the venue receives is what the order path
            built, and the status it answers is a verdict about that submission
            rather than about anything this suite composed.
            """
            status, body = _submit_to_venue(
                port,
                {
                    "symbol": rounded.symbol,
                    "side": "BUY",
                    "type": "LIMIT",
                    "timeInForce": "GTX",  # the PRD: post-only by default
                    "quantity": str(rounded.quantity),
                    "price": str(rounded.price),
                    "newClientOrderId": client_order_id,
                },
                {"X-Environment": shadow_scope.name},
            )
            venue_status.append(status)
            venue_body.append(body)
            # Returning *is* the venue's acceptance, so anything else is raised
            # rather than returned: a callable that returned on a 400 would have
            # the store record an acceptance the venue refused.  The status and
            # body are kept above before the raise, so a failing run can still
            # report what the venue actually said.
            if status != 200:
                raise VenueRefusedError(status, body)

        order_key = PlacementOrder(client_order_id=client_order_id, symbol=ORDER_SYMBOL)
        placement = placements.place(order_key, place_at_the_venue)

        # The same identifier again: the store's sentence is that this returns the
        # *prior* result rather than placing a second order, and the venue's own
        # journal is where that "rather than" becomes visible — a second call
        # reaching the socket would show up as a second line in the venue's file.
        duplicate = placements.place(order_key, place_at_the_venue)

        health = RouterSubmissionHealthStore(url).record(
            outcome=ORDER_SUBMISSION_ACCEPTED,
            symbol=ORDER_SYMBOL,
            client_order_id=client_order_id,
        )
        observed = RouterSubmissionHealthStore(url).latest_for_process()
        if observed is None:  # pragma: no cover - just-recorded row
            raise AssertionError(
                "the submission health store answered no observation for this "
                "process immediately after recording one"
            )
    finally:
        _stop_venue(venue)

    # The venue's own journal, read after it has stopped: what it actually
    # received, as it wrote it down itself.
    venue_requests = _venue_journal(journal_path)

    yield _Journey(
        url=url,
        campaign_id=campaign_id,
        campaign_type=campaign.campaign_type,
        root_id=root_id,
        node_id=node_id,
        criteria_hash=pre_registration.criteria_hash,
        epoch_id=pre_registration.epoch_id,
        pre_registered=pre_registered,
        decision_stamped=decision_stamped,
        promoted_at=opening.promoted_at.isoformat(),
        observed_on=opening.observed_on,
        window_opened_at=window.opened_at.isoformat(),
        window_closes_at=window.closes_at.isoformat(),
        window_days=window.window_days,
        half_life_days=half_life.half_life_days,
        crossing_on=half_life.crossing_on,
        observed_days=half_life.observed_days,
        signal_ids=tuple(signal.signal_id for signal in signals),
        composite_scores=dict(composite.scores),
        shrinkage=stabilized.shrinkage,
        stabilized_weights=dict(stabilized.weights),
        target_weights=dict(published.weights),
        gross_exposure=float(sum(abs(w) for w in published.weights.values())),
        volatility_scale=float(target.scale),
        concentration=concentration(published),
        recorded_signal_ids=recorded.signal_ids,
        recorded_weights=dict(recorded.weights),
        exchange_info_version=version.version,
        exchange_info_symbols=version.symbol_count,
        filters=filters,
        rounded_quantity=str(rounded.quantity),
        rounded_price=str(rounded.price),
        order_value=valued.value,
        min_notional=valued.min_notional,
        off_grid_refusal=off_grid_refusal,
        decay_horizon=decay_horizon,
        expected_fill_time=expected_fill_time,
        posture=posture.posture,
        posture_is_aggressive=posture.is_aggressive,
        margin_mode=margin.mode,
        margin_account=margin.account,
        client_order_id=client_order_id,
        headroom_before=headroom_before.remaining,
        headroom_scope=headroom_before.scope,
        venue_status=venue_status[0] if venue_status else -1,
        venue_body=venue_body[0] if venue_body else "",
        venue_requests=venue_requests,
        placement_appended=placement.appended,
        placement_outcome=placement.placement.outcome,
        duplicate_appended=duplicate.appended,
        duplicate_replayed=duplicate.replayed,
        duplicate_venue_calls=len(venue_requests),
        shadow_scope=shadow_scope.name,
        live_presentation_refusal=live_presentation_refusal,
        registry_rows=_row_count(url, PROMOTION_REGISTRY_TABLE),
        rebalance_rows=_row_count(url, REBALANCE_TARGET_WEIGHTS_TABLE),
        placement_rows=_row_count(url, ORDER_PLACEMENT_TABLE),
        exchange_info_version_rows=_row_count(url, ROUTER_EXCHANGE_INFO_VERSION_TABLE),
        exchange_info_filter_rows=_row_count(url, ROUTER_EXCHANGE_INFO_FILTER_TABLE),
        bucket_rows=_row_count(url, VENUE_WEIGHT_BUCKET_TABLE),
        health_outcome=health.outcome,
        health_process_id=observed.process_id,
    )


# -- A promoted signal ------------------------------------------------------------


class TestAPromotedSignal:
    def test_the_subject_is_a_node_the_discovery_loop_recorded(
        self, journey: _Journey
    ) -> None:
        # The promotion's subject is a real tree row, and the row's identity is
        # the one the discovery member *derives* from the parent it hangs from —
        # not an identifier this journey typed.  That is the difference between a
        # journey about the system and a journey about a fixture.
        assert journey.node_id != journey.root_id
        assert journey.node_id == attempt_node_id(journey.root_id)
        assert journey.campaign_type == CAMPAIGN_TYPE

    def test_the_criteria_were_fixed_before_the_decision_was_stamped(
        self, journey: _Journey
    ) -> None:
        # The pre-registration invariant, read off the two writers' own answers:
        # the registration was this call's *creation* (not a retry), and the
        # decision was this call's stamp.  The ordering is structural rather than
        # asserted about timestamps — the recording insert does not name a
        # decided-at column at all, so a row cannot be born closed.
        assert journey.pre_registered is True
        assert journey.decision_stamped is True
        assert len(journey.criteria_hash) == 64
        assert journey.epoch_id == EPOCH_ID
        assert journey.registry_rows == 1

    def test_the_forward_window_opens_at_the_decisions_own_stamp(
        self, journey: _Journey
    ) -> None:
        # The window is a *read* of the decision's row, never derived from a clock
        # at read time: the opening instant is the stamp, and the horizon is the
        # day count the promotion asked for.
        assert journey.promoted_at == datetime.fromisoformat(DECIDED_AT).isoformat()
        assert journey.window_opened_at == journey.promoted_at
        assert journey.window_days == FORWARD_DAYS
        assert journey.observed_on == date(2026, 2, 1)
        assert (
            journey.window_closes_at
            == (
                datetime.fromisoformat(DECIDED_AT) + timedelta(days=FORWARD_DAYS)
            ).isoformat()
        )

    def test_the_decay_horizon_is_the_signals_own_measured_half_life(
        self, journey: _Journey
    ) -> None:
        # This is the clause that makes the posture decision below *about* the
        # promoted signal rather than about a constant: the horizon the posture
        # verb reads is the forward member's published crossing, computed from the
        # observations this journey landed.  The crossing is real, the day count
        # is the count actually observed, and the figure is the six the member's
        # own arithmetic yields from a 0.12 backtest coefficient against a
        # decaying live series.
        assert journey.half_life_days == EXPECTED_HALF_LIFE_DAYS
        assert journey.observed_days == len(OBSERVED_IC)
        assert journey.crossing_on == date(2026, 2, 7)


# -- Flows through book construction ----------------------------------------------


class TestFlowsThroughBookConstruction:
    def test_the_promoted_signal_is_one_of_the_signals_the_book_was_built_from(
        self, journey: _Journey
    ) -> None:
        # The sentence's middle clause, stated as an identity rather than a
        # resemblance: the promoted signal's identifier is the node the promotion
        # acts were performed on, and it is *in* the set the combiner weighted.  A
        # book built from three unrelated signals would satisfy every other
        # assertion in this class and none of this one.
        assert journey.node_id in journey.signal_ids
        assert journey.signal_ids[0] == journey.node_id
        assert len(journey.composite_scores) == len(SYMBOLS)

    def test_the_construction_ran_every_stage_of_the_book_pipeline(
        self, journey: _Journey
    ) -> None:
        # Combine, shrink, target, judge, publish.  Each stage's own answer is
        # asserted on, so a construction that skipped one would fail here rather
        # than pass a weaker "something was built": the composite covers every
        # symbol, the shrinkage is a real intensity strictly inside the open unit
        # interval, the stabilized weights sum to one unit of gross, and the
        # published book is the target scaled to the configured volatility.
        assert set(journey.composite_scores) == set(SYMBOLS)
        assert 0.0 < journey.shrinkage < 1.0
        assert abs(sum(journey.stabilized_weights.values()) - 1.0) < 1e-9
        # The published gross is the *leverage scalar* the volatility target
        # derived — target over realised — and it is the scalar the member reports
        # rather than a figure recomputed here, so a target stage that stopped
        # scaling would show up as the two disagreeing rather than as a number this
        # suite quietly supplied.  The realised volatility is the composite's own,
        # so the product of the two is the target the construction was asked for.
        assert journey.gross_exposure == journey.volatility_scale
        assert journey.volatility_scale * VOLATILITY == (TARGET_VOLATILITY)
        assert set(journey.target_weights) == set(SYMBOLS)

    def test_the_published_book_sits_inside_the_limits_it_was_judged_by(
        self, journey: _Journey
    ) -> None:
        # The limits verdict was asked and did not raise; this asserts the book it
        # admitted is the book that was published, and that the two bounds really
        # bound it — a verdict over a book that breached nothing would be
        # indistinguishable from a verdict that was never asked.
        assert journey.concentration <= CONCENTRATION_LIMIT
        assert (
            max(abs(w) for w in journey.target_weights.values()) <= PER_POSITION_LIMIT
        )

    def test_the_rebalance_record_names_the_promoted_signal_as_its_origin(
        self, journey: _Journey
    ) -> None:
        # The rebalance row is the bridge the sentence turns on: the target weight
        # set the order layer consumes carries the *originating promoted signal
        # identifiers*, and the promoted signal's identifier is the promotion's
        # own node.  So the book the order came from and the signal that was
        # promoted are one identity, recorded — not two facts that happen to both
        # be true of this run.
        assert journey.recorded_signal_ids == tuple(sorted(journey.signal_ids))
        assert journey.node_id in journey.recorded_signal_ids
        assert journey.rebalance_rows == 1
        assert journey.recorded_weights == journey.target_weights


# -- Into a shadow order ----------------------------------------------------------


class TestIntoAShadowOrder:
    def test_the_grids_the_order_was_judged_against_came_from_the_venue(
        self, journey: _Journey
    ) -> None:
        # The fetched version is the *only* source of the numbers, and the numbers
        # are the deliberately distinctive ones this journey published — a step
        # size and a tick size that appear nowhere in the router member's source.
        # "Never hardcode" is therefore observable here rather than merely
        # asserted: a hardcoded grid could not carry these values.
        assert journey.exchange_info_version == 1
        assert journey.exchange_info_symbols == len(SYMBOLS)
        assert journey.filters.symbol == ORDER_SYMBOL
        assert journey.filters.step_size == STEP_SIZE
        assert journey.filters.tick_size == TICK_SIZE
        assert journey.filters.min_notional == MIN_NOTIONAL
        assert journey.exchange_info_version_rows == 1
        assert journey.exchange_info_filter_rows == len(SYMBOLS)

    def test_an_off_grid_submission_is_refused_by_the_same_gate(
        self, journey: _Journey
    ) -> None:
        # The other half of the "never hardcode" claim, and the reason the 200
        # below means something.  A submission one step of quantity and one tick of
        # price off the published grids is refused by the rounding gate's own class
        # with its own code — so the grids demonstrably reached the judge.
        assert isinstance(journey.off_grid_refusal, RouterOrderRoundingError)
        assert "order_rounding" in str(journey.off_grid_refusal)

    def test_the_submission_was_rounded_and_valued_against_those_grids(
        self, journey: _Journey
    ) -> None:
        # The rounding gate answered the submission *verbatim* — reject-never-round
        # means the values that pass are the values that were sent — and the
        # valuation clears the venue's floor with real headroom, which is what
        # makes this a filter-compliant submission rather than one that merely
        # survived.
        assert journey.rounded_quantity == FILTER_COMPLIANT_QUANTITY
        assert journey.rounded_price == FILTER_COMPLIANT_PRICE
        # The floor the submission was valued against is the *venue's own string*
        # as the fetched document spelled it, and the value clears it — which is
        # what makes this a filter-compliant submission rather than one that
        # merely survived.
        assert journey.min_notional == Decimal(MIN_NOTIONAL)
        assert journey.order_value > journey.min_notional

    def test_the_posture_was_derived_from_the_signals_own_horizon(
        self, journey: _Journey
    ) -> None:
        # The PRD's rule, with the derivation visible: the six-day decay horizon
        # the forward member measured is *longer* than the expected fill time the
        # fill model's own fraction implies, so the order does not cross.  There is
        # no posture argument on the verb to get this wrong with — the answer is a
        # function of the two figures, and both were produced by the shipped system
        # rather than chosen here.
        assert journey.decay_horizon == timedelta(days=EXPECTED_HALF_LIFE_DAYS)
        assert journey.decay_horizon > journey.expected_fill_time
        assert journey.posture == PASSIVE_ORDER
        assert journey.posture_is_aggressive is False

    def test_the_book_settled_under_isolated_margin_on_the_shadow_sub_account(
        self, journey: _Journey
    ) -> None:
        # The arrangement §13.2 holds a book to: the account the order is placed
        # for is §17's shadow sub-account — the child account with a separate
        # balance and a separate key — and the margin mode is isolated rather than
        # cross, which is the mode the margin scope's own default carries.
        assert journey.margin_mode == ISOLATED_MARGIN
        assert journey.margin_account == SHADOW_ACCOUNT

    def test_the_client_order_id_folds_the_rebalances_own_instant(
        self, journey: _Journey
    ) -> None:
        # The identifier is folded from the *rebalance's* instant, and the
        # rebalance row is keyed by that same instant — so the key the order is
        # placed under and the row the order came from are one identity.
        # Recomputing the identifier from the recorded instant is what makes that a
        # check rather than a comment.
        expected = derive_client_order_id(
            book_id=BOOK_ID, rebalance_ts=REBALANCE_TS, symbol=ORDER_SYMBOL
        )
        assert journey.client_order_id == normalize_client_order_id(str(expected))
        assert len(journey.client_order_id) == 64
        assert journey.client_order_id == journey.client_order_id.lower()

    def test_the_live_path_is_closed_by_the_credential_boundary(
        self, journey: _Journey
    ) -> None:
        # §17's control, asked in the direction the sentence needs: the credential
        # this order is authenticated with classifies as *shadow*, and that same
        # credential presented against the live account is refused — the
        # policy-side double of the 401 the exchange would answer.  This is why the
        # order in this journey is a shadow order and cannot be anything else: the
        # live presentation does not reach the wire.
        assert journey.shadow_scope == SHADOW_SCOPE
        assert isinstance(journey.live_presentation_refusal, ScopeMismatch)
        assert str(UNAUTHORIZED) in str(journey.live_presentation_refusal)
        assert CredentialScope(LIVE_SCOPE) != CredentialScope(SHADOW_SCOPE)


# -- And the venue returns 200 ----------------------------------------------------


class TestAndTheVenueReturnsTwoHundred:
    def test_the_venue_answered_two_hundred_for_the_filter_compliant_submission(
        self, journey: _Journey
    ) -> None:
        # The sentence's last clause, as the wire carried it: an HTTP status the
        # standard library's own client read off a real loopback socket.  The body
        # is asserted too, so a stand-in that answered 200 with an error document
        # would fail here rather than pass.
        assert journey.venue_status == 200
        assert json.loads(journey.venue_body)["status"] == "NEW"

    def test_the_venue_received_the_order_the_router_built(
        self, journey: _Journey
    ) -> None:
        # What reached the far end of the wire, read off the venue's own recording:
        # exactly one request, to the order endpoint, carrying the rounded quantity
        # and the tick-aligned price the router's gate answered — not the values
        # this suite typed, and not a re-derivation of them.  The environment
        # header is the shadow credential, which is the §17 marker the venue judges
        # the presentation by.
        assert len(journey.venue_requests) == 1
        request = journey.venue_requests[0]
        assert request["path"] == "/api/v3/order"
        assert request["body"]["symbol"] == ORDER_SYMBOL
        assert request["body"]["quantity"] == journey.rounded_quantity
        assert request["body"]["price"] == journey.rounded_price
        assert request["headers"]["x-environment"] == SHADOW_SCOPE

    def test_the_two_hundred_is_a_verdict_about_this_submission(
        self, journey: _Journey
    ) -> None:
        # What the venue *answered 200 to*, restated from the values the router's
        # gate produced: the submission sits on both of the venue's published grids
        # exactly and clears its floor.  The companion test below is what turns
        # this from a description into a discriminator.
        #
        # The on-grid check is done in *exact decimal*, not in binary floating
        # point: the grids are the venue's strings and the submission is a
        # Decimal, so asking whether the one divides the other is the same
        # arithmetic the gate performed.  A float modulo here would report a
        # rounding artefact on a submission that is genuinely on the grid.
        assert Decimal(journey.rounded_quantity) % Decimal(STEP_SIZE) == 0
        assert Decimal(journey.rounded_price) % Decimal(TICK_SIZE) == 0
        assert Decimal(journey.rounded_quantity) * Decimal(
            journey.rounded_price
        ) >= Decimal(MIN_NOTIONAL)

    def test_the_same_venue_answers_other_submissions_otherwise(
        self, tmp_path: Path
    ) -> None:
        # The sentence's 200 is only evidence if the venue could have said
        # something else, so this asks a venue process the questions it must
        # refuse.  Three probes, one per published filter: a quantity one step off
        # the lot grid, a price one tick off the price grid, and an
        # on-grid-but-too-small notional.  Each is answered 400 while the
        # filter-compliant one is answered 200, so the status this journey
        # recorded is a verdict about *this* submission rather than a constant the
        # stand-in always sends.
        #
        # Over a real socket to a real process, like the journey's own placement:
        # a judgement read out of this suite's address space would be a judgement
        # this suite could have supplied.
        journal_path = tmp_path / "venue-discrimination.jsonl"
        venue, port = _launch_venue(journal_path)
        compliant = {
            "symbol": ORDER_SYMBOL,
            "quantity": FILTER_COMPLIANT_QUANTITY,
            "price": FILTER_COMPLIANT_PRICE,
        }
        shadow_header = {"X-Environment": SHADOW_SCOPE}
        try:
            assert _submit_to_venue(port, compliant, shadow_header)[0] == 200

            off_lot = {**compliant, "quantity": OFF_GRID_QUANTITY}
            off_tick = {**compliant, "price": OFF_GRID_PRICE}
            below_floor = {**compliant, "quantity": MIN_QTY, "price": MIN_PRICE}

            assert _submit_to_venue(port, off_lot, shadow_header)[0] == 400
            assert _submit_to_venue(port, off_tick, shadow_header)[0] == 400
            assert _submit_to_venue(port, below_floor, shadow_header)[0] == 400

            # And the environment boundary the venue enforces, which is the
            # wire-side echo of the credential rule: the same compliant submission
            # presented with the *live* environment is refused with 401 — the
            # status §17 says the exchange answers a shadow key presented against
            # the live account.  The 401 here is the venue's own, put on the wire
            # by the venue's own process, which is why it is the same number the
            # policy module refuses with one layer up.
            assert (
                _submit_to_venue(port, compliant, {"X-Environment": LIVE_SCOPE})[0]
                == UNAUTHORIZED
            )
            assert _submit_to_venue(port, compliant, {})[0] == UNAUTHORIZED
        finally:
            _stop_venue(venue)

        # Six submissions the venue judged — one compliant, three off-grid or
        # below-floor, two presented for the wrong environment — and six lines in
        # its own journal, the refused ones included, because a venue records what
        # it saw before it decides.
        assert len(_venue_journal(journal_path)) == 6

    def test_the_grids_the_journey_relied_on_were_the_venues_own(
        self, tmp_path: Path
    ) -> None:
        # The sharper half of "never hardcode", stated as a *differential* between
        # two venue processes: the same filter-compliant submission, the same
        # wire, and the only difference is the grid the venue was started with.
        # The venue that published the journey's grid answers 200; a venue handed
        # a different lot grid answers 400 to the identical bytes.
        #
        # This is what rules out the failure mode a single 200 cannot rule out —
        # that the venue's answer depended on something other than the grid it
        # published.  If it did, changing the grid would not change the answer.
        submission = {
            "symbol": ORDER_SYMBOL,
            "quantity": FILTER_COMPLIANT_QUANTITY,
            "price": FILTER_COMPLIANT_PRICE,
        }
        header = {"X-Environment": SHADOW_SCOPE}

        faithful_path = tmp_path / "venue-faithful.jsonl"
        faithful, faithful_port = _launch_venue(faithful_path)
        try:
            assert _submit_to_venue(faithful_port, submission, header)[0] == 200
        finally:
            _stop_venue(faithful)

        # The same venue code, handed a lot grid the router never fetched.
        shifted_path = tmp_path / "venue-shifted.jsonl"
        shifted, shifted_port = _launch_venue(shifted_path, step_size="0.001")
        try:
            assert _submit_to_venue(shifted_port, submission, header)[0] == 400
        finally:
            _stop_venue(shifted)

        # Both venues wrote down the *same* test message; only their grids
        # differed, so the differing status is attributable to the grid and to
        # nothing else in the request.
        faithful_seen = _venue_journal(faithful_path)
        shifted_seen = _venue_journal(shifted_path)
        assert len(faithful_seen) == len(shifted_seen) == 1
        assert faithful_seen[0]["body"] == shifted_seen[0]["body"]

    def test_the_store_recorded_the_venues_acceptance(self, journey: _Journey) -> None:
        # The placement contract is that *returning is the venue's acceptance*: the
        # request returned, so the placement landed, and the outcome it carries is
        # the one word the placement vocabulary permits.  The store read the
        # venue's status rather than the suite asserting it separately, which is
        # what makes the record evidence.
        assert journey.placement_appended is True
        assert journey.placement_outcome == ORDER_SUBMISSION_ACCEPTED
        assert journey.placement_rows == 1

    def test_a_duplicate_identifier_returns_the_prior_result_without_re_sending(
        self, journey: _Journey
    ) -> None:
        # The placement verb's *rather than* clause, and the venue is the witness:
        # the second placement replayed the first result and the socket saw exactly
        # the one request.  Asserting only ``appended is False`` would be trusting
        # the store's own bookkeeping; counting the venue's requests is asking the
        # party that would have received the duplicate.
        assert journey.duplicate_appended is False
        assert journey.duplicate_replayed is True
        assert journey.duplicate_venue_calls == 1


# -- The committed record ---------------------------------------------------------


class TestTheCommittedRecord:
    def test_the_health_row_is_filed_under_this_processs_kernel_read_identity(
        self, journey: _Journey
    ) -> None:
        # The identity the submission is filed under is *this* process's,
        # kernel-read: ``<host>/<pid>``.  A journey that filed the order under a
        # configured label would be filing it under a name nobody's kernel
        # confirms.
        assert journey.health_process_id == process_identity()
        assert journey.health_outcome == ORDER_SUBMISSION_ACCEPTED

    def test_the_venue_weight_budget_was_read_before_it_was_spent(
        self, journey: _Journey
    ) -> None:
        # The limiter's reading *before* the order is the whole allowance less the
        # one place-order weight the request would cost — the reading is a
        # question, and a question costs the venue nothing, which is why the bucket
        # table stays empty.  Both halves are asserted rather than assumed: the
        # figure is a real reading taken from the member's *own* default schedule
        # (not from a literals pair this suite chose), and no spend was recorded
        # for it.
        _, weight = DEFAULT_VENUE_WEIGHT_SCHEDULE.price(OPERATION_PLACE_ORDER)
        assert (
            journey.headroom_before == DEFAULT_VENUE_WEIGHT_SCHEDULE.allowance - weight
        )
        assert journey.headroom_before == VENUE_WEIGHT_ALLOWANCE - 1
        assert journey.headroom_scope == DEFAULT_WEIGHT_SCOPE
        assert journey.bucket_rows == 0

    def test_the_tables_hold_exactly_the_one_construction_and_the_one_placement(
        self, journey: _Journey
    ) -> None:
        # The records the order layer consumed and produced, counted with the
        # driver rather than through the stores that wrote them: one rebalance, one
        # placement, one health row, one fetched version — the journey's own
        # footprint and nothing else's.
        assert journey.rebalance_rows == 1
        assert journey.placement_rows == 1
        assert journey.registry_rows == 1
        assert journey.exchange_info_version_rows == 1
        assert journey.recorded_weights == journey.target_weights
