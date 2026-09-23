# Feature 194 — a live exchange recorded into a fixture file keyed by prompt hash

**Spec sentence.** *System records a live provider exchange into a fixture file
keyed by a prompt hash, persisting request and response together.*

**Shape.** plugin, member `providers`, `depends_on=193`.

**Files.** `packages/providers/src/providers/_fixture.py` (feature 194's
module), `_fixture_errors.py` (its error vocabulary), `__init__.py` (import
block, `__all__`, one constant, one builder), `src/app/modules/providers/__init__.py`
(seat widened by one name and one accessor),
`packages/providers/tests/test_fixture.py`, `test_fixture_component.py`,
`conftest.py` (a feature-194 fixture section), `test_pin_component.py` and
`test_served.py` (seat `__all__` widened).

---

## Where the sentence comes from, and what it is the other half of

The prerequisite list at `app_spec.xml:68` names the environment variable the
deployment already documents — `DATABASE_URL, LAKE_ROOT, NULL_SIDECAR_KEY_REF,
EXCHANGE_KEY_REF, **PROVIDER_FIXTURE_DIR**` — and this feature is what fills
that directory. The e2e sentence at `app_spec.xml:1284` is the consumer: *"a
full campaign runs under fixed exploration against fixture-backed agents."*

The member's own modules state the division of labour in as many words.
`_recorder.py` (feature 192's tap):

> It does not hash the prompt or write a file — **that is feature 194's job**,
> and it builds on the `Exchange` this module produces. The recorder hands up a
> clean, ordered list of request/completion pairs; the persistence layer decides
> how to key and store them.

`_recorded.py` (feature 193's source):

> The lookup keys the request by `prompt_hash` rather than by object identity …
> distilled to a stable string so it can be a mapping key **and a fixture-file
> name (feature 194)**.

So 194 is handed its key (`prompt_hash`), its input shape (`Exchange` /
`RecordedResponse`), its destination (the directory `PROVIDER_FIXTURE_DIR`
names) and its consumer (193's backend, via `RecordedProvider(store.responses())`).
It invents none of those; it is the join.

## Where this sits relative to its siblings

| feature | its fact |
| --- | --- |
| 192 | the seam: one request in, one completion out |
| 193 | answers a prompt from the record, with **no** network fallback |
| **194** | **writes an exchange to a file keyed by `prompt_hash`** |
| 195 | the greppable `fixture_missing` code on 193's refusal |
| 169 | the artifact store: `ARTIFACT_ROOT`, one directory per node |

193 and 194 are the read and the write of one record. 195 is the vocabulary of
193's miss. 169 is the nearest *storage* neighbour and the closest comparison
in the tree: same shape of service (a directory, resolved from an env var,
no I/O at construction), different root law (see D3).

## Design decisions

**D1 — a ninth error base, `FixtureStoreError`.** The taxonomy splits by
*question*, not by call site, and every store in this member has argued its own
base the same way: 192 asks *did the call work?*, 203 *is this node's authoring
record pinnable?*, 198/199 *may this model serve the depth role?*, 202 *when may
the runs happen?*, 201 *which endpoint?*, 200 *what does the depth input cost?*,
196 *which family served this root call?*, 197 *what was this campaign's
rotation?* None of them answers *can this exchange be filed as a fixture, and
read back as one?* — a question about a **file**, asked by an object that is not
a provider.

The genuinely close neighbour is 193's `FixtureNotFoundError`, which is
deliberately a `ProviderError`, and the distinction is sharp enough to state:
193's backend **is** a provider, so its refusal is a violation of the provider
contract — *"the provider could not complete this call"* — and a caller's
single `except ProviderError` covers the offline path's every stop. 194's store
is a **directory**, not a provider: nothing in it completes a call, and a
caller's `except ProviderError` around a fixture write would be catching a
phrase about model calls. Folding would also make `except ProviderError` mean
*"the record has no answer for this prompt"* and *"this fixture file is
misfiled"* at once — two repairs (record the prompt, versus repair or delete
the file) under one handle.

**D2 — the file holds exactly the two things the sentence names.** No instant,
no store version, no run id. A fixture file's bytes are a pure function of the
`(request, completion)` pair, which is what makes the keying **value-equal
end to end**: two processes that record the same exchange write byte-identical
files, so the directory is reproducible and a re-capture is a no-op rather than
a diff. The row stores in this member all stamp an instant, and this one
deliberately does not — a row is an *event* with provenance; a fixture is a
*value* addressed by the hash of what it holds, and stamping it would make the
address and the value disagree about identity. It is also what keeps the
idempotence story content-based (D5) rather than clock-based.

**D3 — the root is named, never guessed at.** `PROVIDER_FIXTURE_DIR` (the
spec's own spelling, `app_spec.xml:68`) wins when set; an empty or
whitespace-only value counts as unset, mirroring the shared fixtures' treatment
of an empty `TEST_DATABASE_URL`. With it unset the store **refuses to guess** —
there is no default. This is the one place 194 differs from 169's artifact
store, which defaults to `artifacts/` beside the workspace root, and the
difference is not an oversight: §9.2 *draws* `/artifacts` in the architecture,
so that store has a documented default to land on, while nothing draws a
fixture root anywhere — the deployment names it or there is no fixture store.
A default here would scatter captured exchanges into whatever tree the process
happened to walk up into.

The same stance resolves the composition hazard every other builder in this
member already resolves: `resolve()` returns **`None`** when the variable names
nothing, so the registered builder contributes `None` for a deployment without
a fixture root instead of raising and taking `create_app()` down for every
unrelated feature.

**D4 — one file per prompt hash, flat, named `<digest>.json`.** No sharding. A
shard scheme is *a second key* over the one the sentence names, and a reader
looking for the file for a prompt should be able to compute its path from the
hash alone. JSON because a fixture is an artifact a human reviews in a
pull-request diff: `sort_keys=True` with an indent and a trailing newline, so
the file is deterministic *and* readable — the opposite of `prompt_hash`'s own
compact form, for the opposite reason (a hash is written to be hashed; a file
is written to be read).

**D5 — idempotent re-issue, conflict on a different answer.** Recording the
identical exchange again answers the stored file and **writes nothing** — a
capture retried after an interrupted run is a no-op, and a fixture directory
regenerated from the same record produces the same bytes. A file already filed
under that key holding a *different* completion is `FixtureConflictError`
naming both: one prompt hash has one answer, and the alternative — overwrite —
would let the second capture silently contradict the first, which is precisely
the failure a fixture exists to prevent.

**D6 — the file is self-verifying on read.** Two integrity checks, both
`FixtureCorruptError` naming the path: the `prompt_hash` field must equal the
file's own stem, and it must equal `prompt_hash` of the request it holds. A
file that fails either would be answered for a prompt it does not belong to —
the read side is where a hand-edit or a half-copied directory would otherwise be
laundered into a replay. A stray file whose stem is not a 64-hex key is
**ignored**, not refused: the root is a directory a deployment may keep other
things in, and the temp files a crashed atomic write leaves behind are exactly
that.

**D7 — recognition by parts, answers re-made.** Everything crossing the seam —
the exchange pair, its request, its messages, its completion, its usage — is
recognised structurally with `object.__getattribute__` over a `_PARTS` tuple and
rebuilt from *this* module's classes, the double-import remedy every seam in
this package makes. It is load-bearing here for a reason the siblings do not
have: `prompt_hash` is computed on the re-made request, so the key a caller's
exchange is filed under is this module's canonical key whatever copy built the
request. `object.__getattribute__` rather than `getattr`, so a `__getattr__` hook
cannot fabricate an exchange by answering two names.

A bare `(request, completion)` tuple is **refused**, and that is deliberate:
193's own coercion accepts `(prompt_hash, completion)` pairs, and a tuple-shaped
input here would be indistinguishable from that — a key filed as a request. Only
a pair carrying *named* parts (192's `Exchange`, 193's `RecordedResponse`) is
admitted.

**D8 — a store, not a provider.** The store does not answer prompts. It writes
files and reads them back, and `responses()` hands 193's `RecordedResponse`
pairs to `RecordedProvider`, which is where a missing prompt is still refused as
`FixtureNotFoundError`. A store that also answered calls would be a second
recorded backend beside 193's, and the two would drift about what a miss means.

**D9 — the completion's model need not match the request's.** A tiering or
rotation layer legitimately serves a different model than the caller asked for
— 192's `Completion` says the serving model is *reported, not assumed*, and 196's
whole surface is built on that gap. A store that required the two to agree would
refuse to record exactly the exchanges the rotation exists to produce.

**D10 — `record_all` is a loop, not a transaction.** Persisting a recorder's
tuple of exchanges records each through `record`, in order; a refusal stops the
run and names the exchange it stopped on. Files already written stay written.
That is correct rather than lenient: a fixture file is a value keyed by its own
content, so a partial capture is not a corrupt one — re-running the record
completes it, which is exactly the idempotence D5 provides.

**D11 — the interface's field refusal is translated at this seam.** Fields
re-made from a document or a caller's pair are handed to 192's `Request`,
`Completion` and `Usage` constructors, deliberately: one validation rather than
a second set written here, so a temperature of `"hot"` is refused with the
interface's own precise words. But `CompletionMalformedError` **is** a
`ProviderError`, and the value being refused never reached a provider — it came
out of a caller's hand-built exchange or off disk. Letting it through would hand
a caller holding a fixture directory a phrase about model calls, and its
`except FixtureStoreError` around the read would miss the one failure the read
path exists to catch. So all five construction sites wrap the call and re-raise
through `_from_guard`, which picks `FixtureCorruptError` for a bad document
(repair: the file) and `FixtureStoreError` for a bad exchange (repair: the
call), carrying the guard's own sentence into the message and chaining the
original. This is the same translation the workspace's error-vocabulary rule
demands at every member seam.

The guards are **not uniform**, and that is the non-obvious half: `Request` and
`Completion` raise `CompletionMalformedError`, but the nested `Usage` raises a
bare `ValueError` — a count below zero is a plain out-of-range number, not a
violation of the provider contract. `_FIELD_GUARD` names both, because catching
only the first would let a fixture holding a negative token count raise a
`ValueError` that no caller of this store expects and no `except
FixtureStoreError` of theirs catches. Which constructor objected is not
something a caller filing an exchange should have to know.

## Files

| file | change |
| --- | --- |
| `packages/providers/src/providers/_fixture.py` | new — the store and its record |
| `packages/providers/src/providers/_fixture_errors.py` | new — the ninth base + 2 subclasses |
| `packages/providers/src/providers/__init__.py` | import block, `__all__` (+6), `FixtureFile`, `FixtureStore`, the two errors, `build_fixture_store`; docstring |
| `src/app/modules/providers/__init__.py` | `FIXTURE_STORE_NAME`, `fixture_store_component`, docstring (six registrations → seven) |
| `packages/providers/tests/conftest.py` | feature-194 section: `fixture_root`, `fixture_store`, `capture` |
| `packages/providers/tests/test_fixture.py` | new — the store, the file, the two refusals |
| `packages/providers/tests/test_fixture_component.py` | new — registration + seat |
| `packages/providers/tests/test_pin_component.py` | seat `__all__` widened (10 → 12) |
| `packages/providers/tests/test_served.py` | seat `__all__` widened; registrations six → seven |

## Tests

`test_fixture.py` — the record (a file per exchange, named by the hash, holding
both halves; the completion's model may differ from the request's; the file's
bytes are a pure function of the exchange; a request recorded in one store is
found by an equal request in another); the store (no I/O at construction,
`from_env` reading the variable, blank counting as unset, refusal with no
variable, `resolve` answering `None`, a non-path root refused, a blank root
refused); the write path (the file lands under the key, is valid JSON, is
readable, `path_for` computes it, directories created on first write only, no
temp file left behind after a successful write *or* after a refusal); idempotence
(identical re-record answers the stored file and leaves one file, byte-identical,
`has` true without reading); conflict (a different completion refused naming
both, the stored file untouched); read (`get` answering `None` for an unrecorded
prompt and creating nothing, `get` refusing a misfiled file, a file whose
`prompt_hash` field disagrees with its stem refused, a file whose field
disagrees with its request's hash refused, a non-JSON `*.json` under a 64-hex
stem refused, a stray non-fixture file ignored); `files`/`keys`/`responses`
(sorted by key, value-equal tuples, feeding `RecordedProvider` so the loop closes
offline); `record_all` (in order, partial capture on a refusal, re-running
completing it); the interchange (192's `Exchange`, 193's `RecordedResponse` and a
foreign copy all accepted and re-made; a bare tuple refused; a non-pair refused;
a pair whose completion is not one refused; a malformed field under any of the
interface's guards arriving as *this* feature's error, parametrised over the
record constructors' `CompletionMalformedError` and `Usage`'s bare `ValueError`)
— and the errors (the base is not a `ProviderError`, each subclass under the
base, 193's refusal unaffected).

`test_fixture_component.py` — registration under its own name; composition by
scan; a second composition still holds it; the builder answering `None` with no
`PROVIDER_FIXTURE_DIR` and a bound store with one, creating nothing; the builder
taking no arguments; the seat's name pinned against the member's; the seat
carrying this feature's two exports; the accessor reading the application it is
handed; the composed copy's class and vocabulary asserted by name.

## Verification

- `uv run pytest packages/providers/tests` — **811 → 894 passed** (member
  suite): 66 in `test_fixture.py`, 17 in `test_fixture_component.py`, and the
  seat/registration widens in `test_pin_component.py`, `test_served.py`,
  `test_batch.py` and `test_plugin.py`.
- `uv run pytest` — **1060 passed, unchanged**: the acceptance baseline is held,
  which is what the plugin convention is for — this feature landed without
  editing a single shared file.
- Both run as separate commands; six test basenames collide across trees and a
  combined invocation aborts collection.
- `ruff check` clean on every file this feature touched.

## Explicitly out of scope

- Answering a prompt from the record — 193's backend, unchanged.
- The `fixture_missing` code — 195's, on 193's error, unchanged.
- Choosing what to record (which prompts a campaign asks) — the caller's, and
  the recorder's exchange list is the input.
- Pruning, expiry or a manifest over the fixture directory.
- Any live transport — this member holds none, by construction.
