"""The fixture file — feature 194's record of a live exchange.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 194: *System
records a live provider exchange into a fixture file keyed by a prompt hash,
persisting request and response together.*  This module is the join the
recorded-fixture layer is made of: feature 192's seam gives one normalized
request and one normalized completion, :mod:`providers._recorder` keeps them as
an :class:`~providers.Exchange`, :func:`providers.prompt_hash` distils the ask
to a stable address, and this module **writes the pair to a file at that
address** — one file per prompt, holding both halves, so
:class:`providers.RecordedProvider` (feature 193) can answer the prompt offline
for as long as the file exists.

The prerequisite list names the destination, and has since before this feature
existed: ``app_spec.xml``'s environment block documents
``DATABASE_URL, LAKE_ROOT, NULL_SIDECAR_KEY_REF, EXCHANGE_KEY_REF,
PROVIDER_FIXTURE_DIR``.  This module is what fills ``PROVIDER_FIXTURE_DIR``.
The consumer is stated from the spec's other end, at the end-to-end sentence:
*"a full campaign runs under fixed exploration against fixture-backed agents"* —
which is only possible if something wrote the fixtures first.  That something
is this store.

The division of labour is the member's own, stated in as many words by its
neighbours.  :mod:`providers._recorder` says of its tap: *"It does not hash the
prompt or write a file — that is feature 194's job, and it builds on the
:class:`Exchange` this module produces.  The recorder hands up a clean, ordered
list of request/completion pairs; the persistence layer decides how to key and
store them."*  :mod:`providers._recorded` says of its key: the request's
value-equal form is *"distilled to a stable string, so it can be a mapping key
and a fixture-file name (feature 194)"*.  So this module invents neither the
key nor the input shape nor the consumer: it is the storage contract the two
siblings deliberately left to it.

What the file holds, and what it deliberately does not
------------------------------------------------------

The file holds exactly the two things the sentence names — the request and the
response — serialized as the interface's own fields:

.. code-block:: json

   {
     "prompt_hash": "<the file's own stem>",
     "request": {"messages": [...], "model": ..., "temperature": ..., "max_tokens": ...},
     "completion": {"content": ..., "model": ..., "finish_reason": ..., "usage": {...}}
   }

**No instant, no store version, no run id.**  A fixture file's bytes are a pure
function of the ``(request, completion)`` pair, and that is a design decision
rather than an omission.  It is what makes the keying value-equal *end to end*:
two processes that capture the same exchange write byte-identical files, so the
directory is reproducible and a re-capture is a no-op rather than a diff.  It is
also what keeps the idempotence story content-based: the store compares the
stored file to the offered exchange by **what they hold**, never by when they
were written.  Every store in this member that writes a *row* stamps an instant,
and the reason this one does not is the reason the two are different things: a
row is an **event** with provenance, while a fixture is a **value** addressed by
the hash of its own contents — stamping it would make the address and the value
disagree about what the file's identity is.

Note that the completion's ``model`` is written and read back **whatever it
is**, including when it differs from the request's.  Feature 192 reports the
*serving* model rather than assuming the asked-for one, and feature 196's whole
surface is built on that gap; a store that required the two to agree would
refuse to record exactly the exchanges the deployment's root rotation exists to
produce.

One file per prompt, flat, named by the hash
--------------------------------------------

``<sha256 hex>.json`` sits directly in the store's root.  There is no sharding,
and that is again a decision: a shard prefix would be *a second key* over the
one the sentence names, and a reader looking for the fixture of a prompt should
be able to compute its path from the hash alone.  The extension is ``.json`` for
the same reason the encoding is JSON rather than the compact form
:func:`providers.prompt_hash` hashes — a fixture is an artifact a human reviews
in a pull-request diff.  So the file is written with ``sort_keys=True``, an
indent, and a trailing newline: deterministic *and* readable, the opposite of
the hash's own compact separators, for the opposite reason (a hash is written to
be hashed; a file is written to be read).

The write is **atomic** — a dot-prefixed temp file in the destination directory,
then :func:`os.replace` onto the final name.  The temp lives beside its target
so the rename stays on one filesystem and is therefore a rename rather than a
copy, which is the discipline ``feature_store``'s materialisation already
follows for its own atomic writes.  A reader therefore never meets a
half-written fixture: the bytes under a key are either the whole previous file
or the whole new one.

The root is named, never guessed at
-----------------------------------

:data:`PROVIDER_FIXTURE_DIR_ENV` wins when set; an empty or whitespace-only
value counts as unset, mirroring the shared fixtures' treatment of an empty
``TEST_DATABASE_URL``.  With it unset the store **refuses to guess**, and that
is the one place this store differs from the artifact store
(:class:`artifacts.ArtifactStore`), which defaults to ``artifacts/`` beside the
workspace root.  The difference is not an oversight: §9.2 *draws* ``/artifacts``
in the architecture, so that store has a documented default to land on, while
nothing anywhere draws a fixture root — the deployment names it or there is no
fixture store.  A default here would scatter captured exchanges into whatever
tree the process happened to walk up into, which is worse than a refusal the
deployment fixes by naming the directory the spec already lists.

The same stance resolves the composition hazard every builder in this member
resolves the same way: :meth:`FixtureStore.resolve` returns **``None``** when
the variable names nothing, so the registered builder contributes ``None`` for a
deployment without a fixture root rather than raising — the factory builds every
registered component on every ``create_app()`` call, and a builder that raised
would take composition down for every unrelated feature.  ``None`` is a
discoverable state, not an error.

Idempotence, and the one thing that is a conflict
-------------------------------------------------

Re-recording the **identical** exchange answers the stored file and writes
nothing.  That is what makes a capture retried after an interrupted run a no-op,
and what makes a directory regenerated from one record produce the same bytes.
A file already filed under that key holding a **different** completion is
:class:`~providers.FixtureConflictError`, naming both, and the stored file is
left untouched — the refusal happens after the file is read and before anything
is written.  One prompt hash has one answer, and overwriting would let a second
capture silently contradict the first, which is precisely the failure a fixture
exists to prevent.

The read side verifies, because a directory is a directory
----------------------------------------------------------

A fixture file carries its own ``prompt_hash``, and :meth:`FixtureStore.get`
checks that field twice: against the file's own stem, and against
:func:`providers.prompt_hash` of the request the file holds.  Either mismatch is
:class:`~providers.FixtureCorruptError` naming the path, because a file that
fails either check belongs to a prompt other than the one it is filed under, and
answering it would hand a caller an exchange nobody captured for the prompt it
asked.  A file whose stem is not a fixture key at all is **ignored** rather than
refused: a deployment may keep a README beside its fixtures, and the temp file a
crashed atomic write leaves behind is exactly that shape.

A store, not a provider
-----------------------

This module does not answer prompts, and that is load-bearing.
:class:`providers.RecordedProvider` is feature 193's backend, and the whole
point of separating the two is that a *source* can refuse a missing fixture as
:class:`~providers.FixtureNotFoundError` precisely because it has no live
transport to fall back to.  A store that also answered calls would be a second
recorded backend beside 193's, and the two would drift about what a miss means.
So this object writes files and reads them back, and
:meth:`FixtureStore.responses` hands 193's :class:`~providers.RecordedResponse`
pairs to :class:`~providers.RecordedProvider`, which is where the loop closes.

Recognition by parts, answers re-made
-------------------------------------

Everything crossing this seam — the exchange pair, its request, its messages,
its completion, its usage — is recognised **structurally** with
``object.__getattribute__`` over a :data:`_PARTS` tuple and rebuilt from *this*
module's classes.  The workspace's module loader imports every member twice —
once by file path under ``_nullius_scanned_<dir>``, once as the importable
member — so two class objects exist over one source file and a dataclass's
generated ``__eq__`` answers ``False`` between them for every value.  Here it is
load-bearing in a way the siblings' seams are not: the key is computed by
:func:`providers.prompt_hash` on the **re-made** request, so the address a
caller's exchange is filed under is this module's canonical address whatever
copy built the request.

``object.__getattribute__`` rather than ``getattr``, so an arbitrary object's
``__getattr__`` cannot fabricate an exchange by answering two names — this
function decides what may be written into a fixture, and a hook that answered
two attributes would be a hook that offered a recorded exchange.

Recognition decides *what shape* a value is; the interface's constructors then
decide whether its **fields** are legal, so the validation stays single-sourced
rather than written a second time here.  That is one seam crossing, and it is
translated: the constructors refuse a field with `CompletionMalformedError` — a
`ProviderError` — or, for the nested `Usage`, a bare `ValueError`, and neither is
the right answer for a value that came off disk or out of a caller's hand-built
exchange and never reached a provider.  All five construction sites re-raise
through :func:`_from_guard`, so a caller catching `FixtureStoreError` catches
every way feature 194's sentence can fail.  See :data:`_FIELD_GUARD`.

A bare ``(request, completion)`` tuple is **refused**, and that too is
deliberate: :meth:`providers.RecordedProvider` legitimately accepts
``(prompt_hash, completion)`` pairs, and a tuple-shaped input here would be
indistinguishable from one of those — a *key* filed as a request.  Only a pair
carrying **named** parts is admitted, which is exactly 192's
:class:`~providers.Exchange` and 193's :class:`~providers.RecordedResponse`;
both are accepted, because the two features produced both and a caller should
not have to convert between them to file a fixture.

Stdlib-only, like the rest of this tree: the file half of the recorded-fixture
layer is pure filesystem work, and an import-safe member with no dependencies
cannot break another member's resolution.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, NoReturn

from ._completion import Completion, Usage
from ._errors import CompletionMalformedError
from ._fixture_errors import (
    FixtureConflictError,
    FixtureCorruptError,
    FixtureStoreError,
)
from ._recorded import RecordedResponse, prompt_hash
from ._request import Message, Request

__all__ = [
    "FIXTURE_DIR_ENV",
    "FIXTURE_SUFFIX",
    "FixtureFile",
    "FixtureStore",
]

#: The environment variable naming the fixture store's root — the one spelling
#: of "where the captured exchanges live".  It is the spec's own spelling, not
#: this module's invention: ``app_spec.xml``'s prerequisites list documents
#: ``PROVIDER_FIXTURE_DIR`` alongside ``DATABASE_URL`` and ``LAKE_ROOT``, and a
#: second name for one directory is a deployment that points only one of them
#: at the right place.  The shared test fixtures set it per test; a deployment
#: points it at the directory its recorded exchanges are kept in.
FIXTURE_DIR_ENV: Final[str] = "PROVIDER_FIXTURE_DIR"

#: The extension every fixture file carries.  ``.json`` because a fixture is an
#: artifact a human reviews in a diff, and the extension is what tells a reader
#: which parser opens it.  Part of the address rather than decoration: a file
#: without it is not a fixture this store will answer from.
FIXTURE_SUFFIX: Final[str] = ".json"

#: The characters a fixture's stem is made of — a sha256 hex digest, which is
#: what :func:`providers.prompt_hash` returns.  Spelled as data so the store's
#: own key check and this constant cannot drift: a file whose stem is not
#: exactly this many hex characters is not a fixture key, and
#: :meth:`FixtureStore.files` ignores it rather than refusing it (a README, a
#: crashed write's temp file) — see the module docstring.
_HEX_DIGITS: Final[str] = "0123456789abcdef"
_KEY_LENGTH: Final[int] = 64

#: The parts of an exchange pair, in the order :func:`_pair_from_parts` reads
#: them.  The *names* are the point: a two-tuple has no names, and 193's
#: coercion legitimately reads a two-tuple as ``(key, completion)`` — so a
#: tuple offered here would be a key filed as a request.  Recognition is
#: structural over these two attributes, for the reason the module docstring
#: gives (the double-import seam).
_PAIR_PARTS: tuple[str, ...] = ("request", "completion")

#: The parts of a request and of a completion, for the same structural
#: recognition.  Spelled here rather than imported from the classes' own
#: modules because the seam's business is *reading* a foreign copy's fields,
#: and a reader that consulted the class it is not sure it has would not be a
#: structural reader at all.
_REQUEST_PARTS: tuple[str, ...] = (
    "messages",
    "model",
    "temperature",
    "max_tokens",
)
_MESSAGE_PARTS: tuple[str, ...] = ("role", "content")
_COMPLETION_PARTS: tuple[str, ...] = (
    "content",
    "model",
    "usage",
    "finish_reason",
)
_USAGE_PARTS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
)

#: What the interface's constructors raise when they refuse a **field**, as
#: opposed to a shape.  Both classes are here, and the second is the surprising
#: one: :class:`~providers.Request` and :class:`~providers.Completion` raise
#: :class:`~providers.CompletionMalformedError`, but the nested
#: :class:`~providers.Usage` raises a bare ``ValueError`` — a count below zero
#: is a plain out-of-range number rather than a violation of the provider
#: contract.  Catching only the first would let a fixture holding a negative
#: token count raise a ``ValueError`` no caller of this store is expecting, so
#: the tuple names both and :func:`_from_guard` treats them alike: whichever
#: constructor objected, the value was read from a file or a caller's exchange
#: and never reached a provider.
_FIELD_GUARD: tuple[type[BaseException], ...] = (
    CompletionMalformedError,
    ValueError,
)


@dataclass(frozen=True)
class FixtureFile:
    """One fixture file as the store holds it: its key, its path, and its exchange.

    The unit :meth:`FixtureStore.get` answers with and :meth:`FixtureStore.files`
    lists.  ``key`` is the :func:`providers.prompt_hash` the file is filed
    under, ``path`` is where it actually sits, and ``request``/``completion``
    are the exchange the bytes hold, re-made from **this** module's classes —
    so a caller holds one value type whatever copy wrote the file, and
    ``fixture.request == some_request`` compares by what was asked rather than
    by which import built it.

    Frozen and value-equal for the reason every record in this member is: two
    reads of one file are the same fixture, and a suite can assert a whole
    fixture against an expected one rather than reaching into fields.
    """

    key: str
    path: Path
    request: Request
    completion: Completion

    @property
    def response(self) -> RecordedResponse:
        """The exchange as feature 193's backend takes it — the pair, unwrapped.

        The bridge between the two halves of the recorded-fixture layer: a
        fixture read off disk is exactly the ``(request, completion)`` pair
        :class:`providers.RecordedProvider` answers from, so
        ``RecordedProvider([f.response for f in store.files()])`` replays a
        directory with no conversion step in between.  Derived rather than
        stored, so the pair and the file cannot disagree about what was
        captured.
        """
        return RecordedResponse(request=self.request, completion=self.completion)


class FixtureStore:
    """The directory of fixture files, keyed by prompt hash — feature 194's store.

    Bound to a root at construction (see :meth:`from_env` and :meth:`resolve`).
    Every path the store touches lives under that root: ``<key>.json`` for the
    fixtures, and dot-prefixed temp files beside them for the duration of a
    write.  **Construction performs no I/O** — the root is held, not made, so
    the store is safe to build at composition time in any environment, and the
    directory appears only when a write needs it.

    The store writes files and reads them back, and answers no prompts: a
    recorded backend is feature 193's, and the two are separate objects for the
    reason :mod:`providers._recorder` sets out — a source can refuse a missing
    fixture only because it is not also the thing writing them.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        if isinstance(root, str) and not root.strip():
            # Path("") would silently become "." — filing fixtures into the
            # current directory is never what a caller meant, and the fixtures
            # would then be found or not depending on where the process
            # started.
            raise FixtureStoreError(
                f"the fixture root must be a non-empty path — got an empty "
                f"string; {FIXTURE_DIR_ENV} names the directory a deployment's "
                f"recorded exchanges live in, and a root of '.' would scatter "
                f"them into whatever directory the process happened to start in"
            )
        try:
            self._root = Path(root).expanduser()
        except (TypeError, ValueError) as exc:
            raise FixtureStoreError(
                f"the fixture root must be a usable path — got {root!r}: {exc}"
            ) from exc

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> FixtureStore:
        """The store ``PROVIDER_FIXTURE_DIR`` names, refusing to guess at one.

        :data:`PROVIDER_FIXTURE_DIR_ENV` wins when set; an empty or
        whitespace-only value counts as unset, mirroring the shared fixtures'
        treatment of an empty ``TEST_DATABASE_URL``.  With it unset this
        **raises** rather than defaulting anywhere, which is where this store
        deliberately parts company with the artifact store's ``from_env``:
        §9.2 draws ``/artifacts`` in the architecture so that store has a
        documented default, while nothing draws a fixture root — a default here
        would file captured exchanges into whatever tree the process walked up
        into, and a fixture written to a wrong root is one no replay will find
        again.  A deployment names the directory, or it has no fixture store.

        :meth:`resolve` is the builder's door: it answers ``None`` instead of
        raising, because the factory calls every registered builder on every
        ``create_app()`` and a builder that raised would take composition down
        for unrelated features.  This method is the door for a caller that has
        decided it needs a fixture store and must not proceed without one.
        """
        source = os.environ if env is None else env
        raw = source.get(FIXTURE_DIR_ENV, "").strip()
        if not raw:
            raise FixtureStoreError(
                f"{FIXTURE_DIR_ENV} is not set, so there is no directory to "
                f"file recorded exchanges in. Feature 194 keys a fixture by its "
                f"prompt hash and writes it into the directory this variable "
                f"names (app_spec.xml's prerequisites list it beside "
                f"DATABASE_URL and LAKE_ROOT); nothing else in the system draws "
                f"a fixture root, so this store refuses to guess at one rather "
                f"than filing captured exchanges into whatever tree the process "
                f"happened to start in"
            )
        return cls(raw)

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> FixtureStore | None:
        """The store ``PROVIDER_FIXTURE_DIR`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment that captures no fixtures, which composes no
        fixture-store component — a discoverable state, not an exception —
        while the caller that must record an exchange is the caller that must
        not find itself in it, for the reason
        :func:`providers.build_fixture_store` states on its own ``None``.

        The split from :meth:`from_env` is the split every builder in this
        member makes: ``resolve`` is what composition asks (may answer
        ``None``), ``from_env`` is what a decided caller asks (raises, naming
        the variable to set).
        """
        source = os.environ if env is None else env
        raw = source.get(FIXTURE_DIR_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def root(self) -> Path:
        """The directory the fixtures live in, wherever the deployment mounted it."""
        return self._root

    # -- Addresses ----------------------------------------------------------

    def path_for(self, request: Request) -> Path:
        """Where the fixture for ``request`` sits — computed, never searched for.

        The keying rule of the whole feature in one line: hash the prompt, name
        the file after the digest, and put it in the root.  Public because a
        caller that wants to know whether a fixture *would* be written, or to
        point a tool at one, should not have to re-derive the naming — a second
        spelling of the address is a second thing to keep in sync, and a tool
        that guessed it wrong would look in the wrong place and report a
        recorded prompt as unrecorded.

        Refuses a non-request through :func:`providers.prompt_hash`, which is
        the one place that question is answered.
        """
        return self._root / f"{prompt_hash(request)}{FIXTURE_SUFFIX}"

    def has(self, request: Request) -> bool:
        """Whether this prompt's fixture exists — without reading it.

        A caller's chance to probe the record before committing to a capture,
        without opening the file and without raising: whether the prompt this
        request asks has been filed.  Answers the question the read path asks —
        is there a file at the prompt's address — so a launcher can decide
        "replay offline" versus "record this prompt first" without consuming
        anything.
        """
        return self.path_for(request).is_file()

    # -- The write path -----------------------------------------------------

    def record(self, pair: object) -> FixtureFile:
        """File one exchange under its prompt hash, and answer the stored file.

        Feature 194's sentence as one call: an exchange in, the file that holds
        it out — the capture and its persistence as one act, because an
        exchange captured and not filed is the sentence with its second half
        missing.  The steps, and why each is where it is:

        1. **Recognise the exchange** — the pair's two named parts, each
           re-made from this module's classes — *before anything is opened*, so
           a malformed exchange is refused without touching a directory.
        2. **Compute the key** — :func:`providers.prompt_hash` of the re-made
           request, the address the sentence names.
        3. **Read what is already there, if anything.**  The existing file is
           read *before* the write for one reason: a contradiction must not be
           able to destroy the fixture it contradicts.
        4. **Answer the stored file when the record is identical** — the
           idempotent half.  A capture retried after an interrupted run is the
           same record arriving twice and must be a no-op, so nothing is
           written and the file's own bytes are left exactly as they were.
        5. **Refuse when the key is taken by a different answer** —
           :class:`~providers.FixtureConflictError`, naming the key, with the
           stored file untouched.
        6. **Write atomically**, then read the file back and answer it, so a
           caller holds one record shape from one source of truth — the
           bytes that are on disk, not the ones this call intended to write.

        Refuses, in this order, each naming what it is about: an exchange whose
        parts cannot be recognised (the base
        :class:`~providers.FixtureStoreError`); a file at the key that is not a
        readable fixture (:class:`~providers.FixtureCorruptError`, since a
        contradiction cannot be judged against bytes that do not parse); a key
        already filed with a different completion
        (:class:`~providers.FixtureConflictError`); a root that cannot be
        created or written (:class:`~providers.FixtureStoreError`).
        """
        exchange = _pair_from_parts(pair)
        key = prompt_hash(exchange.request)
        path = self._root / f"{key}{FIXTURE_SUFFIX}"
        payload = _encode(key, exchange.request, exchange.completion)
        existing = self._read_if_present(path, key)
        if existing is not None:
            stored = _fixture_at_path(existing, path, key)
            if (
                stored.request == exchange.request
                and stored.completion == exchange.completion
            ):
                # The identical record arriving twice: a retry, not a
                # contradiction.  Nothing is written — the file already holds
                # exactly these bytes — so a re-capture is a no-op and a
                # directory regenerated from one record is unchanged.
                return stored
            raise FixtureConflictError(
                f"the prompt {key} is already filed with a different response. "
                f"The fixture at {path} holds the completion "
                f"{stored.completion!r}, and the exchange offered for it holds "
                f"{exchange.completion!r}. One prompt hash has one answer — "
                f"that is what addressing a fixture by its prompt means — so "
                f"the second capture is refused rather than written; the stored "
                f"file is untouched, because a contradiction must not destroy "
                f"the fixture it contradicts. Read the stored fixture back and "
                f"decide which capture is the one to keep; do not record over "
                f"it, because then a replay would answer this prompt with an "
                f"exchange nobody reviewed."
            )
        _write_atomically(path, payload)
        # Read back rather than re-encode: the caller holds what the file says,
        # so the returned fixture and a later ``get`` of the same key cannot
        # disagree about the exchange — one source of truth, the bytes.
        return _fixture_at_path(
            self._read_back(path, key), path, key
        )

    def record_all(self, pairs: object) -> tuple[FixtureFile, ...]:
        """File a whole recorder's exchange list, in order.

        The convenience the two sibling features' shapes ask for:
        :meth:`providers.RecordingProvider.exchanges` hands up an ordered tuple
        of :class:`~providers.Exchange`, and a deployment that has just
        captured a run wants all of it filed.  This is a loop over
        :meth:`record` and deliberately **not** a transaction — a refusal stops
        the run and names the exchange it stopped on, and the files already
        written stay written.

        That is correct rather than lenient, and it is the same property the
        per-key idempotence gives: a fixture file is a **value** keyed by its
        own content, so a partial capture is not a corrupt one.  Re-running the
        record over the same exchanges completes the directory, because every
        file already filed is answered rather than rewritten.  A transactional
        capture would instead have to *undo* good files to report one bad
        exchange, which is the opposite of what a value-addressed store wants.

        A non-iterable, or a string (which would otherwise be read as one
        exchange per character), is refused before anything is filed.
        """
        if isinstance(pairs, (str, bytes, Mapping)):
            raise FixtureStoreError(
                f"a fixture capture takes a collection of exchanges, got "
                f"{pairs!r} ({type(pairs).__name__}). Feature 194 files one "
                f"fixture per prompt hash, and a value that is itself a single "
                f"string or a mapping is not a collection of exchanges — "
                f"reading it as one would file fixtures for a run nobody made."
            )
        if not isinstance(pairs, Iterable):
            raise FixtureStoreError(
                f"a fixture capture takes a collection of exchanges, got "
                f"{pairs!r} ({type(pairs).__name__}), which is not iterable. "
                f"The capture is the list of exchanges a recorder kept, and a "
                f"value that holds no exchanges holds no record."
            )
        return tuple(self.record(pair) for pair in pairs)

    # -- The read path ------------------------------------------------------

    def get(self, request: Request) -> FixtureFile | None:
        """The fixture filed for ``request``, or ``None`` when none is.

        ``None`` means *this prompt was never recorded here* — nothing has
        filed it — which is the honest answer for a prompt no file holds, and
        the answer on a root that does not exist yet (a store that has never
        recorded created nothing, and a **read does not create it**).  It does
        **not** mean the read failed: a file that is there but is not the
        fixture it claims to be raises :class:`~providers.FixtureCorruptError`,
        so a caller can never mistake a damaged store for an unrecorded prompt
        — the same distinction :meth:`providers.RecordedProvider.has` and
        :meth:`providers.RootProviderRotation.get` draw on their own sides.

        The fixture is **verified, not merely parsed**: see
        :func:`_fixture_at_path` for the two checks, both of which exist
        because this read is the point at which a hand-edited or half-copied
        directory would otherwise be laundered into a replay.
        """
        path = self.path_for(request)
        key = prompt_hash(request)
        raw = self._read_if_present(path, key)
        if raw is None:
            return None
        return _fixture_at_path(raw, path, key)

    def files(self) -> tuple[FixtureFile, ...]:
        """Every fixture in the store, ordered by key.

        The whole record, read once: what a launcher hands
        :class:`providers.RecordedProvider` to replay a directory, and what a
        suite asserts on to confirm exactly which prompts were captured.

        Ordered by **key** rather than by directory order, so the listing is
        value-equal — two stores holding the same fixtures list them in the
        same order whatever order the filesystem happens to hand them over,
        which is what makes a tuple comparison in a suite mean anything.  A file
        whose stem is not a fixture key is **ignored** rather than refused, and
        that is the deliberate half: a deployment may keep a README beside its
        fixtures, and the dot-prefixed temp file a crashed atomic write leaves
        behind is exactly that shape.  A file whose stem *is* a key but whose
        bytes are not the fixture for it still refuses
        (:class:`~providers.FixtureCorruptError`) — naming the path, because
        that one is the store's problem, not a stranger's file.
        """
        if not self._root.is_dir():
            return ()
        found: list[FixtureFile] = []
        for entry in self._root.iterdir():
            key = _key_of(entry.name)
            if key is None or not entry.is_file():
                continue
            raw = self._read_if_present(entry, key)
            if raw is None:
                # Removed between the listing and the read: a concurrent
                # capture re-organising the directory, not a fixture this read
                # can be wrong about.
                continue
            found.append(_fixture_at_path(raw, entry, key))
        found.sort(key=lambda fixture: fixture.key)
        return tuple(found)

    def keys(self) -> tuple[str, ...]:
        """Every prompt hash this store can answer — ``files()``, unwrapped.

        The record's addresses, in the same order, so a suite can assert on
        exactly which prompts were captured without reading the exchanges —
        the shape :meth:`providers.RecordedProvider.recorded` gives for a
        backend built in memory.
        """
        return tuple(fixture.key for fixture in self.files())

    def responses(self) -> tuple[RecordedResponse, ...]:
        """Every fixture as feature 193's pair — the record, ready to replay.

        The one call that closes the loop the two features make: the pairs this
        returns are exactly what :class:`providers.RecordedProvider` takes, so
        ``RecordedProvider(store.responses())`` answers offline from the
        directory this store captured — the end-to-end sentence's
        *"fixture-backed agents"*, with nothing between the file and the
        backend but this method.
        """
        return tuple(fixture.response for fixture in self.files())

    # -- Internals ----------------------------------------------------------

    def _read_if_present(self, path: Path, key: str) -> str | None:
        """The text at ``path``, or ``None`` when no file is there.

        One reader for the write path's existing-file probe and the read path's
        lookup, so the two cannot disagree about what "filed" means.  A missing
        file is ``None`` — not an error and not an empty string, which would be
        an unreadable fixture rather than an absent one — while a file that is
        there and cannot be read raises, naming the key: an unreadable file is
        a store problem the caller has to know about, not an unrecorded prompt.
        """
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise FixtureStoreError(
                f"the fixture at {path} (prompt {key}) could not be read: "
                f"{exc}. The file is there, so this prompt *is* recorded — a "
                f"read that cannot see it is a store this module will not "
                f"report as an unrecorded prompt, because the two repairs "
                f"differ (fix the directory, versus record the prompt)."
            ) from exc

    def _read_back(self, path: Path, key: str) -> str:
        """Read a fixture this call just wrote, refusing a write that did not land.

        The write path's read-back goes through the read path rather than
        re-encoding the exchange in hand, so a file this store cannot later
        read is refused *here* — at the write that made it — instead of being
        reported as a successful capture and discovered broken by a replay.
        """
        raw = self._read_if_present(path, key)
        if raw is None:
            raise FixtureStoreError(
                f"the fixture written for prompt {key} could not be read back "
                f"from {path}. The file is the record — a fixture that cannot "
                f"be re-read is one this store cannot vouch for, and answering "
                f"it would be reporting a capture that did not land."
            )
        return raw


# ── The file's own encoding ───────────────────────────────────────────────────
#
# The shape written here is the contract between this feature and every reader
# of a fixture directory — including a human reading a diff — so it is spelled
# in one place, as one encoder and one decoder, with the reader's two
# verification checks beside them.  Nothing else in this module builds or parses
# a fixture document.


def _encode(key: str, request: Request, completion: Completion) -> str:
    """The bytes of a fixture file: the key and the two halves, as canonical JSON.

    ``sort_keys=True`` and an indent, unlike the compact form
    :func:`providers.prompt_hash` hashes, for the reason the module docstring
    gives: a hash is written to be hashed, a file is written to be read — and
    the two must not be confused, because a fixture that was compact would be
    unreadable in a review and one that was ordered by insertion would diff
    differently in two processes that captured the same exchange.

    The ``prompt_hash`` field is written **first among the keys** by sort order
    and carries the same value as the file's stem.  It is redundant on purpose:
    it is what makes the file self-verifying on read, so a fixture copied under
    the wrong name, or hand-edited, or assembled by a script that got the
    address wrong, is refused rather than answered.
    """
    return (
        json.dumps(
            {
                "prompt_hash": key,
                "request": {
                    "messages": [
                        {"role": message.role, "content": message.content}
                        for message in request.messages
                    ],
                    "model": request.model,
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens,
                },
                "completion": {
                    "content": completion.content,
                    "model": completion.model,
                    "finish_reason": completion.finish_reason,
                    "usage": {
                        "input_tokens": completion.usage.input_tokens,
                        "output_tokens": completion.usage.output_tokens,
                        "cache_read_tokens": completion.usage.cache_read_tokens,
                    },
                },
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def _fixture_at_path(raw: str, path: Path, key: str) -> FixtureFile:
    """Verify and read one fixture document, refusing anything that is not one.

    The read path's whole verification, in one place so ``get``, ``files`` and
    ``record``'s read-back cannot disagree about what a valid fixture is.  Two
    checks, and each exists for its own failure:

    * the document's ``prompt_hash`` field must equal the **key it was filed
      under** — the file's stem, or the address ``get`` computed — so a fixture
      copied to the wrong name is refused instead of answering a prompt it does
      not belong to;
    * that same field must equal :func:`providers.prompt_hash` of the
      **request the file holds**, so a document whose two halves came from
      different captures is refused instead of replaying an exchange nobody
      made.

    Both refusals name the path: the reader holding the file needs to see which
    one it is, and a message about a hash would send it looking at the wrong
    thing.
    """
    document = _parse_document(raw, path)
    claimed = document.get("prompt_hash")
    if claimed != key:
        raise FixtureCorruptError(
            f"the fixture at {path} declares prompt_hash {claimed!r}, but it is "
            f"filed under {key!r}. A fixture is self-verifying — the file "
            f"carries the key it belongs to — and this one belongs to a "
            f"different prompt, so answering it would hand a caller an exchange "
            f"nobody captured for the prompt it asked. Restore the fixture from "
            f"the run that captured it, or delete it so the prompt reads as "
            f"unrecorded rather than as recorded wrong."
        )
    request = _request_from_document(document.get("request"), path)
    completion = _completion_from_document(document.get("completion"), path)
    recomputed = prompt_hash(request)
    if recomputed != claimed:
        raise FixtureCorruptError(
            f"the fixture at {path} declares prompt_hash {claimed!r}, but the "
            f"request it holds hashes to {recomputed!r}. The two halves of a "
            f"fixture are one capture — the ask that was made and the answer it "
            f"got — and this file's request is not the ask its key names, so a "
            f"replay would answer this prompt with an exchange nobody made. "
            f"Restore the fixture from the run that captured it, or delete it "
            f"so the prompt reads as unrecorded rather than as recorded wrong."
        )
    return FixtureFile(
        key=key, path=path, request=request, completion=completion
    )


def _parse_document(raw: str, path: Path) -> Mapping[str, Any]:
    """Read a fixture file's text as this store's JSON object, refusing the rest.

    Bytes filed under a fixture's name that do not parse — a truncated file, a
    half-copied directory, an interrupted rename from some other tool — are not
    a fixture, and reconstructing one from a partial document would be inventing
    an exchange and filing it under a key that claims it was captured.  A
    document that parses to something other than an object is refused the same
    way, for the same reason.
    """
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FixtureCorruptError(
            f"the fixture at {path} is not readable as JSON: {exc}. A fixture "
            f"file is the pair this store wrote — a request and its completion "
            f"— and bytes that do not parse are not that pair; guessing at them "
            f"would be answering from a file nobody captured. Restore the "
            f"fixture from the run that captured it, or delete it so the prompt "
            f"reads as unrecorded rather than as recorded wrong."
        ) from exc
    if not isinstance(document, dict):
        raise FixtureCorruptError(
            f"the fixture at {path} holds a JSON {type(document).__name__} "
            f"rather than an object. A fixture is written as an object carrying "
            f"its key and its two halves, and a document of another shape is "
            f"not one this store can read the exchange out of."
        )
    return document


def _request_from_document(value: object, path: Path) -> Request:
    """Rebuild a request from a fixture document, refusing a malformed one.

    The fields are read and handed to :class:`~providers.Request`, whose own
    constructor validates them — so a fixture carrying a temperature outside
    ``[0, 2]`` or a blank model is refused by the same guard that refuses a
    caller's, naming the same reason, rather than by a second set of checks
    written here.  What this function refuses itself is only the *shape*: a
    value that is not an object carrying the request's fields, which no
    constructor can be handed.
    """
    if not isinstance(value, dict):
        raise FixtureCorruptError(
            f"the fixture at {path} carries a request that is a JSON "
            f"{type(value).__name__} rather than an object. The two halves a "
            f"fixture persists are the ask and the answer, and a request that "
            f"is not the object it was written as is a file this store cannot "
            f"read an exchange out of."
        )
    messages = value.get("messages")
    if not isinstance(messages, list):
        raise FixtureCorruptError(
            f"the fixture at {path} carries a request whose messages are "
            f"{type(messages).__name__} rather than a list. A request is an "
            f"ordered conversation, and a value that is not a sequence of turns "
            f"is not the ask this feature persisted."
        )
    try:
        return Request(
            messages=tuple(
                Message(role=turn["role"], content=turn["content"])
                for turn in messages
            ),
            model=value["model"],
            temperature=value["temperature"],
            max_tokens=value["max_tokens"],
        )
    except (KeyError, TypeError, IndexError) as exc:
        raise FixtureCorruptError(
            f"the fixture at {path} carries a request missing or mistyping "
            f"{exc!r}. A fixture holds the normalized request and the "
            f"normalized completion feature 192's interface carries, and one "
            f"that cannot be rebuilt into that shape cannot be replayed."
        ) from exc
    except _FIELD_GUARD as exc:
        # The interface's guard refusing a *field* — a temperature off the
        # scale, a blank model — rather than a missing key.  Translated at the
        # seam: see :func:`_from_guard` for why a fixture read must not raise
        # the call seam's error.
        _from_guard("request", value, str(path), exc, corrupt=True)


def _completion_from_document(value: object, path: Path) -> Completion:
    """Rebuild a completion from a fixture document, refusing a malformed one.

    The same split :func:`_request_from_document` makes: this function guards
    the *shape* — an object carrying usage — and :class:`~providers.Completion`
    and :class:`~providers.Usage` validate the fields, so a fixture holding a
    negative token count is refused by the same guard that refuses a provider's,
    with the same words, rather than by checks written a second time here.

    ``finish_reason`` is passed through as written, including when absent: the
    field is optional on the record and defaults to ``stop``, so a fixture
    written by an older capture — or by hand, for a minimal fixture — reads back
    as the natural end rather than being refused for a field the file never had.
    """
    if not isinstance(value, dict):
        raise FixtureCorruptError(
            f"the fixture at {path} carries a completion that is a JSON "
            f"{type(value).__name__} rather than an object. The two halves a "
            f"fixture persists are the ask and the answer, and a completion "
            f"that is not the object it was written as is a file this store "
            f"cannot read an exchange out of."
        )
    usage = value.get("usage")
    if not isinstance(usage, dict):
        raise FixtureCorruptError(
            f"the fixture at {path} carries a completion whose usage is "
            f"{type(usage).__name__} rather than an object. A completion "
            f"carries its token accounting as a normalized record — feature "
            f"192's Usage — and an answer that is not carrying one is not the "
            f"completion this feature persisted."
        )
    try:
        return Completion(
            content=value["content"],
            model=value["model"],
            usage=Usage(
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cache_read_tokens=usage.get("cache_read_tokens", 0),
            ),
            finish_reason=value.get("finish_reason", "stop"),
        )
    except (KeyError, TypeError) as exc:
        raise FixtureCorruptError(
            f"the fixture at {path} carries a completion missing or mistyping "
            f"{exc!r}. A fixture holds the normalized completion feature 192's "
            f"interface carries, and one that cannot be rebuilt into that shape "
            f"cannot be replayed."
        ) from exc
    except _FIELD_GUARD as exc:
        # The interface's guard refusing a field of the answer or its usage — a
        # negative token count, a finish reason outside the closed set —
        # translated at the seam, for the reason :func:`_from_guard` gives.
        _from_guard("completion", value, str(path), exc, corrupt=True)


# ── The interface's guard, translated at the seam ─────────────────────────────


def _from_guard(
    part: str,
    value: object,
    source: str,
    cause: BaseException,
    *,
    corrupt: bool,
) -> NoReturn:
    """Re-raise the interface's field refusal as *this* module's.

    The one place feature 194 has to translate a sibling's error type, and it
    translates because the two features name different questions.  Feature 192's
    :class:`~providers.CompletionMalformedError` is a
    :class:`~providers.ProviderError` and its docstring fixes that scope: it is
    raised at the *interface's* guardrails, so a caller catching
    ``ProviderError`` is catching *"the provider contract was violated"*.  Every
    field this module re-makes is handed to that guard, deliberately — one
    validation rather than a second set written here, so a temperature of
    ``"hot"`` is refused with the interface's own words.

    But the value being refused here never reached a provider.  It came out of a
    caller's hand-built exchange or off **disk**, and the caller holding a
    fixture directory is catching :class:`~providers.FixtureStoreError` — so
    letting that error through would hand it a phrase about model calls for a
    file that was never sent anywhere, and its ``except FixtureStoreError``
    around the read would miss the one failure the read path exists to catch.
    A generated ``__eq__`` is exactly as strict: the sibling's vocabulary is a
    different class object in the composed copy.

    :data:`_FIELD_GUARD` names the two classes the callers catch, and they are
    two because the interface's own guards are not uniform: the record
    constructors raise :class:`~providers.CompletionMalformedError` while the
    nested :class:`~providers.Usage` raises a bare ``ValueError``.  Which of
    them objected is not something a caller of *this* store should have to know
    — the value was read from a file either way — so both arrive here.

    ``corrupt`` picks the class and the message, because *which file* is the
    repair: a bad document means the fixture is not the one its key claims (fix
    the file), while a bad exchange means the caller handed the store something
    that is not a record (fix the call).  The original is chained, so the
    interface's own precise wording — *temperature must be a number* — is still
    in the traceback for whoever wants it.
    """
    detail = f"{value!r} ({type(value).__name__})"
    # The guard's own sentence, carried rather than merely chained: it names the
    # field and the reason — "a request's temperature must be a number, got
    # 'hot'" — and a caller reading one message should not have to unwrap a
    # traceback to learn which field was wrong.
    reason = str(cause)
    if corrupt:
        raise FixtureCorruptError(
            f"the fixture at {source} carries a {part} the interface refuses: "
            f"{reason} The file is {detail}. A fixture holds the normalized "
            f"request and completion feature 192's interface carries — that is "
            f"what makes it replayable — so a field the interface's own guard "
            f"rejects is a file this store cannot read an exchange out of, not "
            f"a call to make. Restore the fixture from the run that captured "
            f"it, or delete it so the prompt reads as unrecorded rather than "
            f"as recorded wrong."
        ) from cause
    raise FixtureStoreError(
        f"an exchange's {part} is not one the interface accepts: {reason} "
        f"The value offered was {detail}. A fixture persists the normalized "
        f"records feature 192's interface carries, and this one cannot be one "
        f"of them."
    ) from cause


# ── The exchange, recognised by its parts ─────────────────────────────────────


def _pair_from_parts(value: object) -> RecordedResponse:
    """Re-make one exchange from its two named parts, refusing anything else.

    Recognition is **structural** — the two attributes :data:`_PAIR_PARTS`
    names, read on ``object.__getattribute__`` — rather than by class, because
    the module loader gives every member two class objects over one source file
    (see the module docstring).  ``object.__getattribute__`` rather than
    ``getattr`` so an arbitrary object's ``__getattr__`` cannot fabricate an
    exchange by answering two names: this function decides what may be written
    into a fixture, and a hook that answered two attributes would be a hook that
    offered a recorded exchange.

    A **bare two-tuple is refused**, and the refusal is the interesting half of
    this function.  ``(asking, answering)`` looks like the obvious input, but
    :meth:`providers.RecordedProvider` already reads a two-tuple as
    ``(prompt_hash, completion)`` — and a tuple has no names, so this function
    cannot tell the two apart.  Accepting one would mean filing a *key* as a
    request: a fixture whose "prompt" is a 64-character string, whose address is
    the hash of that string, and which would never be found by the request it
    was supposed to record.  So the pair must carry **named** parts, which is
    exactly 192's :class:`~providers.Exchange` and 193's
    :class:`~providers.RecordedResponse` — the two shapes the sibling features
    actually produce, both accepted so a caller does not have to convert between
    them to file a fixture.

    The answer is always a :class:`~providers.RecordedResponse` built from this
    module's classes, whatever copy the caller's parts came from — so
    ``prompt_hash`` of the re-made request is *this* module's canonical key, and
    the address a fixture is filed under does not depend on which import built
    the request.
    """
    try:
        parts = tuple(
            object.__getattribute__(value, part) for part in _PAIR_PARTS
        )
    except AttributeError:
        raise FixtureStoreError(
            f"an exchange to file must carry a request and a completion (the "
            f"attributes {', '.join(_PAIR_PARTS)}), got {value!r} "
            f"({type(value).__name__}). Feature 192's Exchange and feature "
            f"193's RecordedResponse are both that pair and both work here — "
            f"but a bare (request, completion) tuple does not, because "
            f"RecordedProvider reads a two-tuple as (prompt_hash, completion) "
            f"and this store cannot tell the two apart: filing one would key a "
            f"fixture by the hash of a hash, at an address no request would "
            f"ever find again."
        ) from None
    return RecordedResponse(
        request=_request_from_parts(parts[0]),
        completion=_completion_from_parts(parts[1]),
    )


def _request_from_parts(value: object) -> Request:
    """Re-make the exchange's ask from its parts, refusing anything else.

    The same structural recognition :func:`_pair_from_parts` makes, one level
    down, and for the same reason — except that here it also decides the
    **address** of the fixture, since ``prompt_hash`` is computed on what this
    function returns.  The parts are read whatever their types and handed to the
    constructors, which refuse a malformed one precisely — a stub carrying
    ``temperature="hot"`` is told its temperature is not a number, not that it
    is "not a request" — so recognition stays cheap and the validation stays
    single-sourced: there is one shape check, the record's own.
    """
    if isinstance(value, Request):
        # Fast path, and the same answer either way: re-made below, so the
        # result is always this module's class and always this module's shape.
        return value
    try:
        parts = tuple(
            object.__getattribute__(value, part) for part in _REQUEST_PARTS
        )
        turns = tuple(
            object.__getattribute__(turn, part)
            for turn in _turns_of(value)
            for part in _MESSAGE_PARTS
        )
    except AttributeError:
        raise FixtureStoreError(
            f"an exchange's request must carry "
            f"({', '.join(_REQUEST_PARTS)}), got {value!r} "
            f"({type(value).__name__}). A fixture is addressed by the prompt "
            f"that was asked — the hash of the normalized request feature 192's "
            f"interface carries — and a value that is not that record has no "
            f"prompt to key by and no messages to persist."
        ) from None
    try:
        return Request(
            messages=tuple(
                Message(role=turns[index], content=turns[index + 1])
                for index in range(0, len(turns), 2)
            ),
            model=parts[1],
            temperature=parts[2],
            max_tokens=parts[3],
        )
    except _FIELD_GUARD as exc:
        # Recognition decided this value was a request *by its parts*; the
        # interface's guard is what then refuses a malformed one.  Translated
        # at the seam — see :func:`_from_guard` — so a caller filing a
        # hand-built exchange catches :class:`FixtureStoreError`, not a phrase
        # about model calls for a call that was never placed.
        _from_guard("request", value, "", exc, corrupt=False)


def _turns_of(value: object) -> tuple[object, ...]:
    """The messages a request-shaped value carries, as a tuple.

    Split out so :func:`_request_from_parts` reads the conversation through one
    accessor: ``messages`` is read once, structurally, and a value whose
    conversation is not iterable is refused by the ``AttributeError`` the
    surrounding recognition already handles — a request whose ``messages`` is a
    string would otherwise be read as one turn per character, the failure mode
    ``_require_members`` in :mod:`providers._root` names for its own
    collection.
    """
    messages = object.__getattribute__(value, "messages")
    if isinstance(messages, (str, bytes, Mapping)):
        raise FixtureStoreError(
            f"an exchange's request carries messages of "
            f"{type(messages).__name__}, which is not a conversation. A "
            f"request is an ordered list of turns, and reading a string or a "
            f"mapping as one would persist a conversation nobody asked."
        )
    return tuple(messages)


def _completion_from_parts(value: object) -> Completion:
    """Re-make the exchange's answer from its parts, refusing anything else.

    The answer's own structural recognition, one level down from
    :func:`_pair_from_parts`.  Note that the completion's ``model`` is read and
    kept **whatever it is**: a tiering or rotation layer legitimately serves a
    different model than the caller asked for, feature 192 reports the serving
    model rather than assuming the asked-for one, and a store that required the
    two to agree would refuse to record exactly the exchanges the deployment's
    root rotation exists to produce.
    """
    if isinstance(value, Completion):
        return value
    try:
        parts = tuple(
            object.__getattribute__(value, part) for part in _COMPLETION_PARTS
        )
        usage = _usage_from_parts(parts[2])
    except AttributeError:
        raise FixtureStoreError(
            f"an exchange's completion must carry "
            f"({', '.join(_COMPLETION_PARTS)}), got {value!r} "
            f"({type(value).__name__}). The sentence persists the request "
            f"**and the response together**, and a value that is not the "
            f"normalized completion feature 192's interface carries is not the "
            f"response half of that record."
        ) from None
    try:
        return Completion(
            content=parts[0],
            model=parts[1],
            usage=usage,
            finish_reason=parts[3],
        )
    except _FIELD_GUARD as exc:
        # Same translation as the request's, one half over: the fields came off
        # a caller's completion, never off a provider.
        _from_guard("completion", value, "", exc, corrupt=False)


def _usage_from_parts(value: object) -> Usage:
    """Re-make a completion's token accounting from its parts, refusing the rest.

    The third level of the same recognition, and the last: a completion's usage
    is the one nested record a fixture carries, so it is the one place the
    structural read would otherwise stop.  Re-made from this module's
    :class:`~providers.Usage`, whose constructor refuses a negative or
    non-integer count — so a fixture cannot hold a completion whose accounting
    lies, whichever copy built it.
    """
    if isinstance(value, Usage):
        return value
    try:
        parts = tuple(
            object.__getattribute__(value, part) for part in _USAGE_PARTS
        )
    except AttributeError:
        raise FixtureStoreError(
            f"a completion's usage must carry ({', '.join(_USAGE_PARTS)}), got "
            f"{value!r} ({type(value).__name__}). A completion carries its "
            f"token accounting as a normalized record so cost and fill "
            f"accounting downstream never re-parse a provider payload; a "
            f"fixture holding an answer without one is not the completion this "
            f"feature persists."
        ) from None
    try:
        return Usage(
            input_tokens=parts[0],
            output_tokens=parts[1],
            cache_read_tokens=parts[2],
        )
    except _FIELD_GUARD as exc:
        # The last level of the recognition, and the last place the interface's
        # guard can refuse a field a caller supplied.
        _from_guard("completion's usage", value, "", exc, corrupt=False)


# ── The filesystem, and one atomic write ──────────────────────────────────────


def _key_of(name: str) -> str | None:
    """The fixture key ``name`` spells, or ``None`` when it is not one.

    The one place this module decides what a fixture file is *called*.
    ``None`` rather than a refusal for a name that is not a key, and that is a
    decision: the store's root is a directory a deployment may keep other things
    in — a README, a manifest, the temp file a crashed atomic write left behind
    — and a reader that refused the directory for holding one would be refusing
    a store for a stranger's file.  A name that *is* a key is a different
    matter, and the bytes under it are checked properly by
    :func:`_fixture_at_path`.
    """
    if not name.endswith(FIXTURE_SUFFIX):
        return None
    stem = name[: -len(FIXTURE_SUFFIX)]
    if len(stem) != _KEY_LENGTH or any(char not in _HEX_DIGITS for char in stem):
        return None
    return stem


def _write_atomically(path: Path, payload: str) -> None:
    """Write ``payload`` to ``path`` so a reader never sees a partial file.

    A temp file **in the destination directory**, then :func:`os.replace` onto
    the final name — the discipline ``feature_store``'s materialisation follows
    for its own atomic writes.  The temp lives beside its target so the rename
    stays on one filesystem and is therefore a rename rather than a copy, which
    is what makes it atomic: a reader of ``path`` sees either the whole previous
    file or the whole new one, never a half-written fixture.  The temp is
    dot-prefixed and carries a random suffix, so it is invisible to
    :meth:`FixtureStore.files` (:func:`_key_of` refuses the name) and two
    concurrent captures of different prompts cannot collide on it.

    The directory is created **here**, on the first write, and nowhere else:
    construction performs no I/O, and a read of a store that has never recorded
    must not bring a directory into being — the same lazy-schema stance every
    store in this member takes for its own table.

    The temp file is removed in a ``finally`` that swallows only
    ``FileNotFoundError``: after a successful replace the temp is already gone,
    so the unlink is a no-op; after a failure it is the cleanup that keeps a
    crashed write from leaving debris.  Any other error is allowed to travel —
    an unlink that fails is a store problem, not a detail.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FixtureStoreError(
            f"the fixture root {path.parent} could not be created: {exc}. "
            f"Feature 194 files one fixture per prompt hash under the "
            f"directory {FIXTURE_DIR_ENV} names, and a store whose root cannot "
            f"be made is one no capture can land in."
        ) from exc
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise FixtureStoreError(
            f"the fixture for {path.stem} could not be written to {path}: "
            f"{exc}. The exchange was captured and could not be filed, and a "
            f"capture that did not land must be reported rather than assumed — "
            f"a replay would otherwise find the prompt unrecorded at the moment "
            f"it needed it."
        ) from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
