# nullius contract

Workspace member for the **contract** plugin (app_spec.xml, category
"Signal Contract & Market Window", feature 4; docs/nullius-tech-architecture.md
§5.1, §19).

## The MarketWindow (feature 4)

A `MarketWindow` is the only thing an LLM-authored signal ever sees: a
point-in-time market view, constructed host-side from a sealed snapshot and
already sliced to its decision time `t`. The design intent is a *physical*
guarantee rather than a checked one — but the anchor of every downstream
guarantee is that **the decision time is fixed at construction**:

```python
from datetime import datetime, timezone
from contract import MarketWindow

window = MarketWindow(t=datetime(2026, 9, 1, tzinfo=timezone.utc),
                      universe=("BTCUSDT", "ETHUSDT"))

window.t          # datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc) — read-only
window.universe   # ('BTCUSDT', 'ETHUSDT') — a tuple, read-only

window.t = datetime(2026, 9, 2, tzinfo=timezone.utc)
# AttributeError: MarketWindow is immutable; cannot set 't'
# (the decision time is fixed at construction)
```

`MarketWindow.t` is persisted once by the constructor and can never be
reassigned: `__setattr__` and `__delattr__` raise unconditionally, the
properties have no setters, and `__slots__` keeps new attributes from being
attached. Reassigning `t` is precisely how look-ahead bias would enter a
backtest — a widened window makes every "point-in-time" result computed from
it quietly wrong — so the class refuses it from any caller: a signal, a
subclass, the sandbox payload channel. The constructor itself is single-shot
(`window.__init__(later_t)` raises `TypeError`), so re-running the one
sanctioned writer cannot move a live window's `t` either. The one documented
limit is
`object.__setattr__(window, "_t", …)` on the private backing slot, which no
pure-Python guard can block; that boundary is the sandbox's job
(architecture §5.2), not this class's.

The constructor also normalizes `t` to a timezone-aware UTC instant. Naive
datetimes are read as UTC (the system-wide convention), aware datetimes in
other zones are converted, and ISO-8601 strings — the representation a
window travels as across the payload boundary — are parsed. Anything else
raises: a `TypeError` for a non-datetime, a `ValueError` for an unparseable
string, and a deliberate rejection for a bare `date`, which names a calendar
day, not an instant.

## Point-in-time universe resolution (feature 13)

`MarketWindow.universe` is a tuple, and for a window built by
`from_memberships` it is a tuple *resolved against that window's own decision
time* — never the wall clock. Those are two separate promises, and only the
first is a container choice: a tuple holds today's roster just as happily.

```python
from contract import MarketWindow

# (symbol, valid_from, valid_to) — a delisting and a listing straddling t.
rows = [
    ("BTCUSDT", "2020-01-01", None),
    ("ETHUSDT", "2020-01-01", "2026-05-01"),   # delisted before t
    ("SOLUSDT", "2021-08-01", "2026-09-01"),   # delisted AFTER t — still tradable at t
    ("DOGEUSDT", "2026-07-01", None),          # listed AFTER t — not tradable at t
]

window = MarketWindow.from_memberships("2026-06-15T12:00:00+00:00", rows)
window.universe   # ('BTCUSDT', 'SOLUSDT') — ETH gone, SOL kept, DOGE not yet
```

Both directions of the failure are silent, which is what makes the coupling
worth having. A symbol delisted *after* `t` must still appear (it was tradable
then; dropping it is the survivorship pruning that flatters a backtest), and
one listed *after* `t` must not (returning it is look-ahead).

The resolution is `resolve_universe(when, memberships)` — pure, clock-free,
and **with no default `when`**. A default of `datetime.now()` would make the
wall-clock reading the convenient one and the correct one the extra typing,
and a reviewer could not tell the two call sites apart. Requiring the argument
forces every caller to name the instant it is resolving for, and
`from_memberships` supplies the window's own frozen `t` so the roster and the
slice instant cannot disagree.

Resolution lives in `contract/resolution.py`, which imports nothing from the
`universe` member: `contract` is Z0, the boundary everything else sits behind,
so depending on a consumer of the contract would invert the stack. Membership
rows are accepted *structurally* — objects with `symbol`/`valid_from`/`valid_to`
(the universe member's real `MembershipInterval`, exercised against this seam
in the suite), mappings of the same keys, or plain triples. Bounds may be
`date`, `datetime` or ISO strings; `valid_from` is inclusive and `valid_to`
exclusive, matching `universe/membership.py` exactly, and `valid_to=None` is
the open horizon. The result is sorted and de-duplicated, so a resolution is
bit-reproducible (feature 46) and a window's universe is a sound `__hash__`
input.

Note the shape: `t` is a *constructor* argument and `universe` remains an
accessor taking no argument at all. Feature 10 requires that no accessor
accept a timestamp — one that did would be a caller's chance to widen the
window. Resolving once at construction keeps that door shut.

## The ABI record

Importing the package registers a builder with the application factory
(`app.module_loader.register`), so workspace scanning composes it as the
`"contract"` component — a plain, serializable dict:

```python
{"contract_version": "0.1.0", "market_window": "contract:MarketWindow"}
```

The ABI is advertised **by name** (`contract:MarketWindow`), not as a class
object: the module loader imports scanned packages under synthetic names, so
a class handed across that seam is not the class a normal
`from contract import MarketWindow` yields — an `isinstance` check across
the two silently returns `False`. A name always resolves to the one real
class on `sys.path`. `CONTRACT_VERSION` lives next to the ABI it versions;
stored nodes persist it alongside their code hash (feature 15 builds here).

The composed component is reachable from the `app` package namespace at
`app.modules.contract.contract_component()`, which returns the dict — or
`None` when no contract component is registered.

## The Arrow IPC payload channel (feature 14)

A materialized window travels to the sandbox as Arrow IPC — one self-describing
payload over a channel, with **zero copy** on the read side
(docs/nullius-tech-architecture.md §5.2, `payload=window.to_arrow()`).

```python
import pyarrow as pa
from contract import MarketWindow, PayloadChannel

window = MarketWindow(
    t="2026-09-01T12:00:00+00:00",
    universe=("BTCUSDT", "ETHUSDT"),
    frames={"bars": pa.table({"ts": [1, 2], "close": [61000.5, 61001.0]})},
)

payload = window.to_arrow()      # MarketWindowPayload — the bytes
payload.decision_time            # '2026-09-01T12:00:00+00:00'  (no frame read)
payload.universe                 # ('BTCUSDT', 'ETHUSDT')
payload.frame_names              # ('bars',)

rebuilt = payload.materialize()  # MarketWindow — frames view the payload
rebuilt == window                # True
```

**Why a container and not a bare IPC stream.** Arrow carries metadata per
*schema*; the window's facts (decision time, universe, contract version) are
per *payload*. Encoding them as a synthetic column would make every frame's
schema a lie. So the payload is a framed container: a magic header, a length
table, then a zero-column manifest stream followed by one IPC stream per
frame. The manifest is read without touching a single frame.

**The zero-copy claim.** `materialize()` slices each frame segment out of the
payload buffer rather than copying it, so the returned tables' buffers point
into the payload's own allocation. Values alone cannot prove this — a copying
reader returns identical tables — so `frames_alias_payload()` checks buffer
addresses, and the suite includes a negative control proving that check can
fail.

**Two refusals worth knowing:**

- An **unmaterialized** window cannot be serialized. The sandbox has no
  filesystem mounts, so a window with no frames has no data behind it;
  shipping a header would surface as an unexplainable zero signal far from
  its cause. "No data" is an empty *frame*, not an absent one.
- A **malformed** payload is refused rather than interpreted. These bytes
  arrive over a channel, so a bad magic, an unknown version, a truncated or
  padded body, or an unreadable segment raises `PayloadFormatError`.

`PayloadChannel` is the seam itself — bytes in, bytes out, with no path, fd or
handle, which is what lets the sandbox run with no mounts at all.
`receive()` raises `NoPayloadError` when nothing arrived; that is the
contract-level half of feature 159.

pyarrow is a declared dependency of this member, but it is imported lazily
(`contract._arrow.require_arrow`) so the factory's workspace scan does not
need it installed — only the payload paths do, and they name it when missing.

## Tests

`tests/contract/` (repository-level tree) pins every half: the market-window
contract (read-only `t`, UTC normalization, universe tuple, equality/hash),
the composition wiring (workspace membership, scan-root resolution, factory
composition, single-component registration, seat), the payload channel
(`test_payload.py`: round-trip fidelity, zero-copy by buffer identity with a
negative control, framing, and every malformed-payload refusal), and the
point-in-time resolution (`test_universe_point_in_time.py`: both directions of
the survivorship/look-ahead failure, the `valid_from`/`valid_to` boundary
convention, clock independence, stable ordering, the accepted row shapes, the
refusals, and the structural seam against the universe member's real
`MembershipInterval`).
