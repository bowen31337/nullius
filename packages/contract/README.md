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

## No accessor takes a timestamp (feature 10)

The read-only `t` covers one of the two ways a window could be widened —
reassignment.  The other is an accessor that takes a time: `ctx.bars("1m",
as_of=tomorrow)` would return rows the window was sliced to exclude, which is
look-ahead bias entering through a *signature* rather than an assignment
(docs/nullius-tech-architecture.md §5.1).  Feature 10 forbids it: "System
rejects any MarketWindow accessor that receives a timestamp argument, because
no timestamp a caller passes may widen the window."

The refusal is structural, enforced at *class-definition* time, not a comment
and not a runtime check a caller could miss.  `MarketWindow` is built with the
`_EnforceNoTimestampAccessor` metaclass, which scans every subclass as it is
defined and raises `TypeError` the moment one declares an accessor that takes a
timestamp — so a widening accessor added by a later feature module, a signal's
attempted subclass, or a monkeypatch is rejected the instant it is written,
before any window carrying it can be built:

```python
class WideningWindow(MarketWindow):
    def bars(self, freq, lookback, as_of=None):   # TypeError: no accessor may take one
        return None
```

A parameter is matched as a timestamp by its normalized spelling (lower-cased,
underscores removed), so `as_of`, `AsOf`, `AS_OF` and `at` all match; a
`*args`/`**kwargs` catch-all does not, since it is not a named slot a caller
fills with a time.  The error names the offending accessor and the parameter,
so the rejection is actionable.

`inspect_accessors()` is the explicit, callable form of the same rule, for a
caller that wants to introspect the surface rather than rely on the class
failing to construct.  It enumerates every public accessor — every attribute
that is a function or a property and not a dunder — raises on a widening one,
and otherwise returns the accessor names:

```python
from contract import inspect_accessors

inspect_accessors()   # ('feature', 'frames', 't', 'to_arrow', 'universe') — none takes a time
```

The check is over the *class*, so one inspection covers every window that will
ever be built, and it is import-safe and clock-free, so it can run as a
self-check wherever the window is loaded — including the factory's workspace
scan.

**Scope, stated honestly.**  This is an *accessor* check, not a blanket "no
method takes a time" check.  `MarketWindow.from_memberships(t, ...)`
legitimately takes `t` as its first argument — that is feature 13's
point-in-time construction path, which resolves the universe as of the
window's own frozen `t`.  A constructor is not an accessor a signal calls on
`ctx`; it is the sanctioned place a timestamp belongs.  Both the metaclass and
`inspect_accessors` exclude classmethods for exactly that reason, so the
constructor's `t` is never flagged.  The read-only `t` guard (feature 4) covers
the assignment path; the metaclass covers the accessor path; between them a
window has no widening surface at all.

The composed application exposes the same surface from the `app` package
namespace at `app.modules.contract.window_accessor_names()`, which calls
`inspect_accessors()` and returns the accessor names — or raises, exactly as
the member does, since a widening accessor is a hard failure of the boundary
every signal is evaluated against, not a discoverable absent state.

## `feature(name, version)` — exactly one version (feature 9)

§5.1 declares `feature(name: str, version: str, lookback: int) -> pl.DataFrame`,
and §4.4 says why the version is not optional: `feature_version` is a component
of a stored feature's *identity* — *"A changed definition gets a new
`feature_version`; it never overwrites."*  Version 1 and version 2 of one
feature are different definitions' output, so feature 9's clause — "returns rows
for that exact version only" — is the whole content of the accessor:

```python
from contract import MarketWindow, feature_frame_name

window = MarketWindow(
    t="2026-09-01T12:00:00+00:00",
    universe=("BTCUSDT",),
    frames={
        feature_frame_name("vol", "1"): v1_table,   # the old definition
        feature_frame_name("vol", "2"): v2_table,   # the revised one
    },
)

window.feature("vol", "2")            # v2's rows — the version asked for
window.feature("vol", "2", lookback=20)  # its trailing 20 rows
window.feature("vol", "1")            # v1's rows — NOT v2's
window.feature("vol", "3")            # empty: the version was never computed
```

**The version is part of the frame's name, not a column in it.**  Frame names
are what feature 14's payload manifest records, so version identity travels to
the sandbox for free: a window that crossed the channel as Arrow IPC bytes still
answers `feature("vol", "2")` correctly.  A version carried as a *column* would
be a row-level fact a caller could forget to filter on, and "forgot to filter on
the version column" is precisely the bug feature 9 exists to make unaskable.

**A miss is an empty frame, never another version's rows.**  The lookup is an
exact match on one frame name; there is no "latest version" resolution, no
prefix match (`"1"` never picks up `"10"`), and no fallback to whatever versions
happen to be present.  That direction matters: an empty `DataFrame` cannot leak
a wrong version's numbers, whereas a substituted one would silently attribute
v2's values to v1 and nothing downstream could tell.  It is the same stance the
system takes elsewhere — a missing partition is an empty result, not an error
(`SnapshotMount.partitions`); a store miss is `None` (`FeatureStore.get`).

**`lookback` is the trailing count.**  `None` (the default) returns every row
the window carries; a non-negative `int` returns the *last* N — the recent end
of an oldest-first frame, which is what a lookback means.  A count larger than
the frame returns the whole frame rather than an out-of-range offset, so an
over-long lookback never reads as "no data".  A negative count or a `bool` is
refused: `lookback=True` would silently mean "the last one row", and a wrong
answer that looks like a right one is exactly the failure this module is built
against.

```python
from contract import FeatureAccessError, feature_frame_names

window.feature("vol", "")             # FeatureAccessError — the *question* is invalid
window.feature("vol", "1", lookback=-1)  # FeatureAccessError — negative count
feature_frame_names(window.frames)    # (('vol', '1'), ('vol', '2')) — which versions exist
```

A malformed name, version or lookback is validated *before* the window is
consulted, so a typo against a window carrying nothing reports the typo rather
than reading as a data gap.  `feature_frame_names()` answers the complementary
question — which versions this window actually carries — which is what makes a
miss distinguishable from a mistake.

**The encoding is total and collision-free.**  A feature frame is named
`feature:<name>:<version>`, and `:` is refused *inside* both components.  That
refusal is load-bearing: without it, `("a:1", "2")` and `("a", "1:2")` would both
spell `feature:a:1:2` — two distinct feature versions addressing one frame,
which is the silent version-mixing feature 9 forbids arriving through the
encoding rather than the lookup.  `feature_frame_name` / `parse_feature_frame_name`
are exported so a host materializing a window and an accessor reading one cannot
drift apart over where the version goes.

The naming and lookup core lives in `contract/features.py`, which is
**stdlib-only**: `require_polars` is reached once per call, on the same lazy seam
as `_arrow.require_arrow` and `signal._require_signal_module`, so the
version-discipline logic is import-safe and testable in every environment the
workspace contract promises one will be.

Note the signature: `feature(self, name, version, lookback=None)` has no
parameter that reads as a timestamp, which is feature 10's requirement — this
accessor can only ever return a *subset* of the rows the window was sliced to
contain, never a row past `t`.

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

## The absent-symbol rejection (feature 12)

Feature 11 checks a return's *values*; feature 12 checks the *claim* the return
makes about which symbol each value belongs to, and emits the outcome a run
records:

```python
import polars as pl
from contract import check_signal_return

check_signal_return(pl.Series("score", [0.1, -0.2, 0.5]), window.universe)
# SignalReturnOutcome(outcome='ok', index=(), absent_symbols=(), problems=())

check_signal_return(pl.Series("DOGEUSDT", [0.3]), ("BTCUSDT",))
# outcome='contract_violation', absent_symbols=('DOGEUSDT',),
#   problems=(SignalReturnProblem(kind='absent_symbol', symbol='DOGEUSDT', ...),)
```

**Why "the index" needs defining.** Polars has no index: a `Series` has no
`.index`, no `index=` keyword, and `series["A"]` raises — which is why feature
11's *conforming* return is a bare series paired positionally. A return that
claims labels anyway does so through whichever carrier Polars offers, and
`return_index` reads all of them:

| carrier | claim |
| --- | --- |
| `pl.DataFrame({"symbol": [...], "score": [...]})` | the `symbol` column |
| `pl.Series([{"symbol": ..., "score": ...}])` | the `symbol` struct field |
| `{"BTCUSDT": 0.5, ...}` | the mapping's keys |
| `pl.Series("DOGEUSDT", [0.3])` | the series' name |

**A series' name is read as an index claim only when it is ticker-shaped**
(upper case, alphanumeric, ending in a known quote asset — `is_symbol_label`,
`QUOTE_ASSETS`). `"DOGEUSDT"` is a claim; `"score"`, `"VOL"`, `"S1"` and
`"momentum"` are names, and a bare series named `"score"` conforms exactly as
feature 11 says it should. The rule defaults to "name", because a false
rejection of a correct signal is the worse error in both directions.

**Why reject rather than tolerate.** A one-symbol window scored with
`pl.Series("DOGEUSDT", [0.3])` is length-conforming, finite and float — and
attributes DOGE's score to BTCUSDT. Nothing downstream could notice: the
evaluation succeeds and the number is wrong. Feature 11 cannot see it, because
it is a claim about *labels*, not values.

`check_signal_return(result, window)` composes both halves — this feature's
label check and feature 11's value check — into one frozen, JSON-serializable
`SignalReturnOutcome` whose `outcome` is `"ok"` or `"contract_violation"`. It
is a **value, never a raise**: a bad return is a hypothesis that produced a
bad artifact, not a programming error, and the caller decides what it costs
(a retry, a trial charge, a discard). Both checks always run, so a mislabeled
`DataFrame` reports `absent_symbol` *and* `not_a_series` — telling the author
that fixing the labels alone will not make it conform. `problems` is in return
order with the symbol claims first (they name *which* score is wrong);
`absent_symbols` is sorted and de-duplicated for the at-a-glance read, and a
label that is not a non-empty string is reported as `non_string_symbol_label`
rather than as an absent symbol, so nobody hunts for a spelling mistake that
is not there.

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
the accessor contract (`test_market_window_accessors.py`: the window's surface
is enumerated and reported, no accessor takes a timestamp, the metaclass
refuses to *define* a window with a widening accessor — including a subclass —
every timestamp spelling a caller could reach for is detected, and the one
sanctioned place a time belongs — the `from_memberships` constructor — is
excluded; plus that the metaclass does not weaken the window's copy/pickle and
immutability semantics), the composition wiring (workspace membership,
scan-root resolution, factory composition, single-component registration,
seat), the payload channel
(`test_payload.py`: round-trip fidelity, zero-copy by buffer identity with a
negative control, framing, and every malformed-payload refusal), and the
point-in-time resolution (`test_universe_point_in_time.py`: both directions of
the survivorship/look-ahead failure, the `valid_from`/`valid_to` boundary
convention, clock independence, stable ordering, the accepted row shapes, the
refusals, and the structural seam against the universe member's real
`MembershipInterval`).

Feature 9 is pinned by `test_market_window_feature.py`, in the two halves that
fail in opposite directions: that the version is *honoured* (each version's rows
come back as its own, and — the case that matters most — a request for a version
the window does not carry returns nothing rather than the nearest or the latest,
since a values-only check on one version would not catch a mix-up), and that the
*request is validated* (a malformed name, version or lookback is refused, which
is a different fact from a miss, and the malformed request is reported even
against a window carrying nothing). It also pins the encoding
(`feature:<name>:<version>` round-trips, the separator is refused inside a
component so two distinct pairs cannot spell one frame, and distinct pairs give
distinct names), the lookback boundaries (`None` is the whole frame, an
over-long count is the whole frame, `0` is empty, negative and `bool` are
refused), and the one thing this feature could plausibly have broken — that the
version survives the feature 14 payload channel and that the new accessor still
takes no timestamp parameter (feature 10).

Feature 15 is pinned by `test_contract_version.py`: that the stamp resolves to
the ABI it declares (rather than being a bare string), the persist/read round
trip of the record's two fields and the refusal of either half going missing,
numeric ordering (`0.10.0 > 0.9.0`), the refusals of an unorderable stamp, and —
the property that makes an audit possible — that `compare` answers
`compatible`/`stale`/`malformed` for *every* value a row might hold without
raising. The last test in the file asserts the composed ABI record is
unperturbed by any of it.

Feature 12 is pinned by `test_contract_violation.py` in three parts: reading
the index (all four carriers, the struct field winning over the series name,
the nested field deliberately *not* read, and — the case that matters most —
that a conforming bare series claims **nothing**, since a checker that read a
series' name as an index would reject correct signals); the rejection
(`absent_symbol` carrying the symbol and its position, one problem per
offending label, present symbols silent, and a non-string label reported as
malformed rather than absent); and the outcome (`ok` vs `contract_violation`
as a value that never raises, both halves firing on a mislabeled `DataFrame`,
`absent_symbols` sorted and de-duplicated, the record serializing to JSON, and
determinism). Two of its tests reach past the module: one drives a real
`MarketWindow` to prove the window-universe seam is duck-typed rather than
`isinstance`-based, and one imports the package in a subprocess to prove
polars is still deferred — the layering guarantee the whole member rests on.
