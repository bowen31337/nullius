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

## Versions of the ABI (feature 15)

`CONTRACT_VERSION` is declared in the package next to the ABI it versions, and
`contract.version` is what a node writer actually reaches for. Feature 15's
sentence — a `contract_version` constant that *every stored node persists
alongside its code hash* — is two halves, and they answer different questions:

- the **code hash** says *which source* was stored;
- the **contract version** says *which ABI that source was written against* —
  the entrypoint name, the window it is handed, the shape of the vector it
  returns.

Persisting both is what makes two nodes comparable. Without the stamp, an ABI
change is invisible: two rows with different code hashes look like two
experiments, when the truth may be that the same experiment was run twice
against signatures that no longer agree — and every comparison downstream
(paired ΔIR, dedup by `code_hash`, the replay path) silently assumes they are
commensurable.

```python
from contract import compare, describe_contract_version, node_abi_record

describe_contract_version()
# {'contract_version': '0.1.0', 'market_window': 'contract:MarketWindow',
#  'entrypoint': 'signal'}   — what "0.1.0" actually meant

record = node_abi_record(code_hash=code_hash)   # the pair a writer persists
record.as_dict()
# {'contract_version': '0.1.0', 'code_hash': 'a3f1…'}

compare(record.contract_version)
# Compatibility(status='compatible', direction='same', …)
compare("0.0.9").status, compare("0.0.9").direction   # ('stale', 'older')
```

Three things are deliberate:

- **`compare` returns a value, it never raises.** `compatible` / `stale` /
  `malformed`, with the direction (`older`/`newer`) alongside. An audit over a
  five-month-old tree must be able to *describe* a row with a missing or
  unreadable stamp, not abort on it. What a mismatch costs is the caller's
  decision — a replay may refuse the node, an audit may only flag it.
- **The predicate is equality, not a range.** Nothing in the ABI is
  additive-only today, so a lower-bounded ">= 0.1.0" would be a promise this
  package cannot keep and would read an ABI change as compatible. A future
  compatible extension will be a deliberate edit here, with a test that says so.
- **Version strings are dotted numeric, never a date or a git sha.** They have
  to be *orderable* for "this node is older than the current ABI" to mean
  anything; `parse_contract_version` refuses anything else, and components
  compare numerically so `0.10.0` sorts after `0.9.0`.

The strict counterpart is `require_supported_contract_version`, which raises —
for the callers where proceeding on a mismatch is meaningless, most concretely
a sandbox about to execute a node's code. The `node` table and the writer that
persists a row are features 97–102; this feature owns the stamp, the record
shape and the check.

## The signal entrypoint (feature 11)

A node is a single function with a single, well-known name — the shape the
sandbox executes it under (`entrypoint="signal"`, architecture §5.2):

```python
def signal(ctx: MarketWindow, seed: int) -> pl.Series:
    """Pure. Returns index=symbol, value=float score. Sign and scale are free."""
```

The two parameters are the whole surface a signal may reach for: the window
(the only thing carrying data) and the seed (the only thing carrying
randomness). The seed is **required**, not defaulted — a signal that sampled
randomness with a default would look identical at the call site to one that
did not, and determinism would be a hope rather than a signature. The
entrypoint name and the seed argument's name are declared once, so the agent,
the sandbox and the validator cannot drift apart over a spelling:

```python
from contract import SIGNAL_ENTRYPOINT, SIGNAL_SEED_ARG, describe_signal_signature

SIGNAL_ENTRYPOINT           # 'signal'
SIGNAL_SEED_ARG             # 'seed'
describe_signal_signature() # SignalSignature(entrypoint='signal', window_arg='ctx', seed_arg='seed')
```

**"A Polars series indexed by symbol" is positional, not a labelled axis.**
Polars has no string index — a `Series` has no `.index` attribute, no
`index=` constructor keyword, and `series["A"]` raises. So the *i*-th value is
the score for the *i*-th symbol of `ctx.universe`: the window carries the
labels, the series carries the values, in the window's stable ordering
(feature 13's sorted universe, feature 46's stable ordering). That is exactly
the pairing `validate_signal_return` checks.

Two validators make the contract checkable, and both return problem lists
rather than raising, so the caller (the authoring loop, the evaluator) keeps
the decision about what a non-conformance costs:

```python
from contract import validate_signal_signature, validate_signal_return

# The source half (feature 205): does the agent's code expose signal(ctx, seed)?
validate_signal_signature(code)   # -> [] when the source declares a conforming entrypoint

# The value half (feature 11's return): is this a well-formed signal vector?
validate_signal_return(result, window.universe)   # -> [] when result is a finite float series of the right length
```

`validate_signal_signature` compiles the source and inspects the resulting
function's parameters — it does **not** run it (running untrusted code is the
sandbox's job, under its limits). `validate_signal_return` checks that the
return is a `polars.Series`, that its dtype is floating point, that its length
matches the universe, and that every value is a finite float. Each names the
failure; feature 12 (which depends on this one) is the consumer that maps a
failure — e.g. a return naming a symbol absent from the universe — onto a
`contract_violation` outcome.

polars is a declared dependency of this member (it is the signal return type),
but it is imported lazily — `validate_signal_return` reaches for it only when
a return is actually inspected — so the factory's workspace scan does not need
it installed, exactly as pyarrow stays deferred behind `require_arrow`.

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

Feature 15 is pinned by `test_contract_version.py`: that the stamp resolves to
the ABI it declares (rather than being a bare string), the persist/read round
trip of the record's two fields and the refusal of either half going missing,
numeric ordering (`0.10.0 > 0.9.0`), the refusals of an unorderable stamp, and —
the property that makes an audit possible — that `compare` answers
`compatible`/`stale`/`malformed` for *every* value a row might hold without
raising. The last test in the file asserts the composed ABI record is
unperturbed by any of it.
