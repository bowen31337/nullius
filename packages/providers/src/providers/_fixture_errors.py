"""The failure modes of the fixture-file store — feature 194.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 194: *System
records a live provider exchange into a fixture file keyed by a prompt hash,
persisting request and response together.*  This module is the vocabulary of
that store's refusals, and it is a **ninth base class** in this package — one
that deliberately shares no ancestor with :class:`providers.ProviderError`,
:class:`providers.ModelPinError`, :class:`providers.DepthModelError`,
:class:`providers.DepthScheduleError`, :class:`providers.BatchRoutingError`,
:class:`providers.DepthCacheError`, :class:`providers.RootProviderError` or
:class:`providers.RootRotationError`, for the same reason those eight share
none with each other: a caller's ``except`` clause answers one question, and
the nine questions are different ones.

* :class:`~providers.ProviderError` answers *did the model call work?*
* :class:`~providers.ModelPinError` answers *is this node's authoring record
  pinnable?*
* :class:`~providers.DepthModelError` answers *may this model serve the depth
  role?*
* :class:`~providers.DepthScheduleError` answers *when may this campaign's
  depth runs happen?*
* :class:`~providers.BatchRoutingError` answers *which endpoint does this call
  go to?*
* :class:`~providers.DepthCacheError` answers *what does the depth role's input
  cost, and what rate did this campaign measure there?*
* :class:`~providers.RootProviderError` answers *which of the rotated families
  took this root call?*
* :class:`~providers.RootRotationError` answers *what did the campaign's
  rotation assign to which root?*
* :class:`FixtureStoreError` answers *can this exchange be filed as a fixture
  under its prompt hash, and read back as one?*

Why this is a ninth base and not a subclass of the first
--------------------------------------------------------

The temptation is real, and it is worth stating precisely because the nearest
neighbour is the one this feature is most easily confused with.

**Not under :class:`~providers.ProviderError`.**  That base is the *call*
seam's — its own docstring fixes the scope: *"the failure modes of **this**
seam and no other — a malformed completion, a missing provider, an unknown
model — raised at the interface's own guardrails"*, so that *"a caller catching
``ProviderError`` is catching 'the provider contract was violated'"*.  Feature
194's store is a **directory**.  Nothing in it places a call, forwards one, or
answers one; it writes files and reads them back.  A caller's ``except
ProviderError`` wrapped around a fixture write would be catching a phrase about
model calls, and the repair it would suggest — fix the provider — is not the
repair a misfiled fixture needs.

**Not under :class:`~providers.FixtureNotFoundError`, and this is the sharp
one.**  Feature 193's refusal *is* deliberately a
:class:`~providers.ProviderError`, and that is right for 193's reason:
:class:`~providers.RecordedProvider` **is** a provider, so a prompt with no
recorded response is a violation of the provider contract — *"the provider
could not complete this call"* — and a CI check that the loop never fell back to
a live network gets *one* handle for every way the offline path can stop.  The
two features ask different questions about the same record, and folding them
would make one ``except`` mean two things with two different repairs:

* *"this prompt has no recorded response"* — 193's, repaired by **recording the
  prompt** (with this store), and by nothing else;
* *"this exchange cannot be filed, or this file is not the fixture it claims to
  be"* — 194's, repaired by **fixing the file or the exchange**, and by nothing
  193 can do.

A caller that caught both under one handle could not tell which repair it owed,
which is exactly the collapse each of this package's taxonomies refuses in its
own docstring.

**Why it is not one of the store bases either.**  :class:`RootProviderError`,
:class:`RootRotationError`, :class:`DepthCacheError` and
:class:`DepthScheduleError` are all *member-owned-table* vocabularies: each one
guards a row this member writes into a database it resolved from
``DATABASE_URL``.  This store touches no database at all — it resolves a
directory and writes files into it — so a caller that configured no database
must still be able to file a fixture, and a caller catching
:class:`DepthCacheError` to learn its measurement was refused must not have a
fixture-file refusal answered in its place.  The question is not *what does the
row say* but *what does the file say*.

The two failures, and why there are exactly two
------------------------------------------------

The sentence is a **persistence** statement — one exchange in, one file out,
addressed by the prompt's hash — and it fails in exactly two places: at the
write, when the address is already taken by a different answer, and at the
read, when the bytes at an address are not the fixture they claim to be.

* :class:`FixtureConflictError` — **a prompt hash already filed with a
  different response.**  The store's write path is idempotent on *content*:
  re-recording the identical exchange answers the stored file and writes
  nothing, because a capture retried after an interrupted run must be a no-op
  and a fixture directory regenerated from the same record must produce the same
  bytes.  But one prompt hash has **one** answer — that is what addressing a
  fixture by its prompt means — so a second exchange carrying the same prompt
  and a *different* completion is refused rather than written.  Overwriting
  would let the second capture silently contradict the first, which is precisely
  the failure a fixture exists to prevent: a replay would answer a prompt with
  an exchange nobody reviewed.  The refusal names both files' contents' models
  and the key, so the caller can see which value is stored and which it asked
  for.

* :class:`FixtureCorruptError` — **the bytes at a key are not the fixture for
  that key.**  A fixture file is self-verifying: it carries its own
  ``prompt_hash``, and the store checks that field against the file's name and
  against the hash of the request the file holds.  A file that fails either
  check would be answered for a prompt it does not belong to, so it is refused
  naming the path — the read side is where a hand-edit, a half-copied directory
  or an interrupted rename would otherwise be laundered into a replay.  The
  third shape of the same failure is a file that is not readable as this
  store's JSON at all: bytes filed under a fixture's name that do not parse
  into a request and a completion are not a fixture, and guessing at them would
  be answering from a file nobody wrote.

The base is also raised *directly*, for the failures no subclass describes: a
root that is not a path, a root that is blank, an exchange whose parts cannot be
recognised, a completion that is not one.  These are malformed *descriptions*
rather than failed *persistence*, and the move is the one
:class:`providers.RootProviderError` makes for a serving provider that is not a
name and :class:`providers.DepthCacheError` makes for a non-finite price: a
contract violation that is genuinely none of the named cases has no subclass to
wear, and minting one class per call site is how a taxonomy stops describing
anything.

Stdlib-only, like the rest of this tree: these errors describe a directory of
files and an exchange the interface carried, and nothing here dials a provider,
opens a socket, or imports an SDK.
"""

from __future__ import annotations

__all__ = [
    "FixtureConflictError",
    "FixtureCorruptError",
    "FixtureStoreError",
]


class FixtureStoreError(Exception):
    """Base of the fixture-file taxonomy — an exchange could not be filed or read back.

    One base class so a deployment's fixture capture and a suite can catch
    every failure of feature 194's sentence — an exchange whose parts cannot
    be recognised, a root that is not a path, a key already filed with a
    different answer, a file that is not the fixture it claims to be — with a
    single ``except``, the way :class:`providers.ProviderError` gives the
    call seam one handle and :class:`providers.RootProviderError` gives the
    root provenance one.

    The base is deliberately unrelated to all eight of the others, and the
    sharpest distinction is with feature 193's
    :class:`~providers.FixtureNotFoundError` — which *is* a
    :class:`~providers.ProviderError`, correctly, because that backend **is** a
    provider and a prompt with no recorded response is a violation of the
    provider contract.  This store is a **directory**: nothing in it completes
    a call, and its failures are about **files**, not calls.  Folding the two
    would make one ``except`` mean *"record the prompt"* and *"fix the file"*
    at once, and a caller could not tell which repair it owed.

    Also raised directly for the malformations no subclass describes — a
    non-request offered as an exchange's ask, a completion that is not one, a
    root that is blank or not a path — on the grounds the module docstring
    gives: those are bad *descriptions* rather than failed *persistence*, and
    the taxonomy splits by question, not by call site.
    """


class FixtureConflictError(FixtureStoreError):
    """A prompt hash already filed with a different response.

    One prompt hash has one answer — that is what addressing a fixture by its
    prompt *means*, and the value-equality feature 192's
    :class:`~providers.Request` guarantees is what makes the address stable
    across processes.  So the write path is idempotent on **content**:
    re-recording the identical exchange answers the stored file and writes
    nothing, because a capture retried after an interrupted run is the same
    record arriving twice.  But a second exchange carrying the same prompt and
    a *different* completion is not a retry — it claims one prompt was
    answered two ways.

    Raised by :meth:`providers.FixtureStore.record`, naming the key and the
    text of both files' contents, so the caller can see which value is stored
    and which it asked for.  The stored file is **not touched**: the refusal
    happens after the existing file has been read and *before* anything is
    written, so a contradiction cannot destroy the fixture it contradicts.

    The repair is to read the stored fixture back
    (:meth:`providers.FixtureStore.get`) and decide which of the two captures
    is the one to keep — deleting the file is a deliberate act with the
    evidence in hand, never a side effect of recording over it.  What is never
    available is recording a second answer under a taken key, because then a
    replay would answer a prompt with an exchange nobody reviewed, which is
    the whole failure a fixture exists to prevent.
    """


class FixtureCorruptError(FixtureStoreError):
    """The bytes at a key are not the fixture for that key.

    A fixture file is **self-verifying**: it carries its own ``prompt_hash``
    field, and the store checks that field twice — against the file's own name,
    and against :func:`providers.prompt_hash` of the request the file holds.  A
    file failing either check belongs to a prompt other than the one it is filed
    under, and answering it would hand a caller an exchange nobody captured for
    the prompt it asked.

    The third shape of the same failure is a file filed under a fixture's name
    that cannot be read as this store's JSON at all — unparseable bytes, or a
    parsed document that does not carry a request and a completion.  Such a file
    is not a fixture, and reconstructing one from a partial document would be
    inventing an exchange and filing it under a key that claims it was captured.

    Raised by :meth:`providers.FixtureStore.get` and its readers, naming the
    path, on the ground the read side is where corruption would otherwise be
    laundered: a fixture directory is a directory, and a hand-edit, a
    half-copied tree or an interrupted rename all arrive here.  A file whose
    *name* is not a fixture key at all is a different case and is **not** this
    error — :meth:`providers.FixtureStore.files` ignores what it cannot key, so
    a deployment may keep a README beside its fixtures and a crashed atomic
    write's temp file is not mistaken for one.

    The repair is the file, not the record: restore the fixture from the run
    that captured it, or delete it so the prompt reads as unrecorded (feature
    193's :class:`~providers.FixtureNotFoundError`) rather than as recorded
    wrong.  What is never available is answering from bytes the store cannot
    vouch for, because a replayed campaign whose answers came from an
    unverified file is a campaign whose results nobody can reproduce.
    """
