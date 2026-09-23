"""The fixture file: a live exchange filed under its prompt hash.

Feature 194's sentence is a *persistence* claim — *"System records a live
provider exchange into a fixture file keyed by a prompt hash, persisting
request and response together"* — so these tests take the sentence apart into
its four claims and assert each one where it can actually be observed:

* **a live provider exchange** — the input is a real
  :class:`providers.Exchange`, driven through a
  :class:`providers.RecordingProvider` over a scripted provider (the
  ``capture`` fixture), not a pair assembled by hand;
* **into a fixture file** — the bytes land **on disk**, in a directory the
  store resolves from ``PROVIDER_FIXTURE_DIR``, and the file is readable by a
  human in a diff;
* **keyed by a prompt hash** — the address is
  :func:`providers.prompt_hash`, computed, never searched for, and a request
  equal by value in another process finds the same file;
* **persisting request and response together** — the file holds both halves,
  and reading it back yields both, so a fixture that lost one half would be
  caught here rather than by a campaign whose replay answered nothing.

The last section closes the loop the two features make: a directory this store
captured, handed to feature 193's :class:`providers.RecordedProvider`, which
answers a prompt with no network access at all — *"a full campaign runs under
fixed exploration against fixture-backed agents"*, as the end-to-end sentence
puts it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from providers import (
    FIXTURE_DIR_ENV,
    FIXTURE_SUFFIX,
    Completion,
    Exchange,
    FixtureConflictError,
    FixtureCorruptError,
    FixtureFile,
    FixtureNotFoundError,
    FixtureStore,
    FixtureStoreError,
    Message,
    ProviderError,
    RecordedProvider,
    RecordedResponse,
    Request,
    Usage,
    prompt_hash,
)


def _ask(content="q", *, model="m", **kwargs):
    """A request spelled directly, for the tests that do not need a capture."""
    return Request(
        messages=(Message(role="user", content=content),), model=model, **kwargs
    )


def _answer(content="a", *, model="m", **usage):
    """A completion spelled directly, for the tests that do not need a capture."""
    return Completion(
        content=content,
        model=model,
        usage=Usage(
            input_tokens=usage.get("input_tokens", 1),
            output_tokens=usage.get("output_tokens", 2),
            cache_read_tokens=usage.get("cache_read_tokens", 0),
        ),
    )


# ── The record: one file, keyed by the prompt, holding both halves ────────────


def test_a_live_exchange_is_filed_into_a_file(fixture_store, capture, fixture_root):
    # The sentence's load-bearing verb: the exchange goes **to disk**.  A store
    # that kept it in memory would satisfy nothing — the whole point of a
    # fixture is that it outlives the process that captured it.
    exchange = capture(lambda request: _answer("a1", model=request.model))

    filed = fixture_store.record(exchange)

    assert filed.path.is_file()
    assert filed.path.parent == fixture_root


def test_the_file_is_named_by_the_prompt_hash(fixture_store, capture):
    # *"keyed by a prompt hash"* — the address is feature 193's own key, not a
    # second naming scheme.  A reader that has the request can compute the path
    # without searching, which is what makes a fixture directory readable by a
    # tool that was never told what is in it.
    exchange = capture(lambda request: _answer("a1", model=request.model))

    filed = fixture_store.record(exchange)

    assert filed.path.name == f"{prompt_hash(exchange.request)}{FIXTURE_SUFFIX}"
    assert filed.key == prompt_hash(exchange.request)


def test_the_file_persists_the_request_and_the_response_together(fixture_store, capture):
    # *"persisting request and response together"* — both halves, in one file.
    # A fixture that split them, or that kept only the answer, could not say
    # which response matched which prompt, and the replay would answer the
    # wrong question.
    exchange = capture(lambda request: _answer("a1", model=request.model))

    filed = fixture_store.record(exchange)

    document = json.loads(filed.path.read_text(encoding="utf-8"))
    assert document["request"]["messages"] == [{"role": "user", "content": "q"}]
    assert document["request"]["model"] == exchange.request.model
    assert document["completion"]["content"] == exchange.completion.content
    assert document["completion"]["usage"] == {
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_read_tokens": 0,
    }


def test_the_filed_fixture_carries_both_halves_back(fixture_store, capture):
    # The round trip, in one assertion: what comes out of the store is what went
    # in — the same ask and the same answer, by value.  This is the property
    # every other test in this file leans on.
    exchange = capture(lambda request: _answer("a1", model=request.model))

    filed = fixture_store.record(exchange)

    assert filed.request == exchange.request
    assert filed.completion == exchange.completion


def test_the_file_is_readable_json_a_reviewer_can_diff(fixture_store, capture):
    # A fixture is an artifact a human reviews in a pull request, which is why
    # it is written pretty-printed and key-sorted rather than in the compact
    # form `prompt_hash` hashes.  A hash is written to be hashed; a file is
    # written to be read.
    exchange = capture(lambda request: _answer("a1", model=request.model))

    filed = fixture_store.record(exchange)

    text = filed.path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert '\n  "completion"' in text
    # Key-sorted, so two processes that captured the same exchange write the
    # same bytes: "completion" < "prompt_hash" < "request".
    assert text.index('"completion"') < text.index('"prompt_hash"')
    assert text.index('"prompt_hash"') < text.index('"request"')


def test_the_file_carries_its_own_key(fixture_store, capture):
    # The file is self-verifying: it declares the key it is filed under, and
    # the store checks that field on read.  It is redundant on purpose — it is
    # what lets a fixture copied under the wrong name be refused rather than
    # answered for a prompt it does not belong to.
    exchange = capture(lambda request: _answer("a1", model=request.model))

    filed = fixture_store.record(exchange)

    document = json.loads(filed.path.read_text(encoding="utf-8"))
    assert document["prompt_hash"] == filed.key


def test_the_bytes_are_a_pure_function_of_the_exchange(fixture_root, capture):
    # Two captures of one exchange, in two stores, write **byte-identical**
    # files.  That is what makes the directory reproducible and a re-capture a
    # no-op: nothing about *when* or *where* the capture happened is in the
    # file, because a fixture is a value addressed by its own content rather
    # than an event with provenance.
    exchange = capture(lambda request: _answer("a1", model=request.model))
    other_root = fixture_root.parent / "fixtures-again"

    first = FixtureStore(fixture_root).record(exchange)
    second = FixtureStore(other_root).record(exchange)

    assert first.path.read_bytes() == second.path.read_bytes()


def test_the_completions_serving_model_may_differ_from_the_request(fixture_store):
    # Feature 192 reports the model that *served* an answer rather than assuming
    # the one that was asked for, and feature 196's whole surface is built on
    # that gap: a tiering or rotation layer legitimately answers a call with a
    # different family's model.  A store that required the two to agree would
    # refuse to record exactly the exchanges the rotation exists to produce.
    request = _ask(model="claude-opus-5")
    served = _answer("a1", model="gpt-5.6-sol")

    filed = fixture_store.record(Exchange(request=request, completion=served))

    assert filed.completion.model == "gpt-5.6-sol"
    assert fixture_store.get(request).completion.model == "gpt-5.6-sol"


def test_an_equal_request_in_another_store_finds_the_file(
    fixture_root, capture, make_request
):
    # *"keyed by a prompt hash"* means the key is the request's **value**, not
    # its object identity — so a request built fresh, in another store over the
    # same directory, lands on the same file.  That is how a fixture written by
    # one process is read by the next.
    exchange = capture(lambda request: _answer("a1", model=request.model))
    FixtureStore(fixture_root).record(exchange)

    # Built by the same helper the capture used, from scratch: an equal request
    # carrying the same *value* in a different object.
    equal_request = make_request(bodies=(("user", "q"),))
    assert equal_request is not exchange.request
    assert equal_request == exchange.request
    assert FixtureStore(fixture_root).has(equal_request) is True


# ── The store: where the directory comes from ────────────────────────────────


def test_construction_performs_no_io(fixture_root):
    # Composing an application must be safe in any environment, so the root is
    # held rather than made: the directory appears only when a capture needs it.
    # A store that mkdir'd at construction would create directories on every
    # `create_app()` call, in every process, whether or not a fixture was ever
    # recorded.
    store = FixtureStore(fixture_root)

    assert store.root == fixture_root
    assert not fixture_root.exists()


def test_the_store_reads_the_directory_the_spec_names(fixture_root):
    # The env var is the spec's own spelling (`app_spec.xml`'s prerequisites
    # list documents `PROVIDER_FIXTURE_DIR` beside `DATABASE_URL` and
    # `LAKE_ROOT`), so a deployment has one name for one directory.
    assert FixtureStore.from_env({FIXTURE_DIR_ENV: str(fixture_root)}).root == (
        fixture_root
    )


def test_a_blank_directory_counts_as_unset():
    # The shared fixtures' treatment of an empty `TEST_DATABASE_URL`, applied
    # here: whitespace is not a directory, and reading it as one would file
    # fixtures into "" — which Path turns into the current directory.
    assert FixtureStore.resolve({FIXTURE_DIR_ENV: "   "}) is None


def test_from_env_refuses_to_guess_at_a_directory(fixture_root):
    # The one place this store parts company with the artifact store, which
    # defaults to `artifacts/` beside the workspace root: §9.2 *draws*
    # `/artifacts` in the architecture so that store has a documented default,
    # while nothing draws a fixture root.  A default here would file captured
    # exchanges into whatever tree the process walked up into, and a fixture
    # written to a wrong root is one no replay will find again.
    with pytest.raises(FixtureStoreError):
        FixtureStore.from_env({})

    # ...and the refusal names the variable to set, because "which knob" is the
    # whole repair.
    with pytest.raises(FixtureStoreError) as excinfo:
        FixtureStore.from_env({})
    assert FIXTURE_DIR_ENV in str(excinfo.value)


def test_resolve_answers_none_rather_than_raising():
    # The builder's door.  The factory calls every registered builder on every
    # `create_app()`, so a builder that raised on an unset variable would take
    # composition down for every unrelated feature in the workspace.  `None` is
    # a discoverable state — a deployment that captures no fixtures — not an
    # error.
    assert FixtureStore.resolve({}) is None
    # ...and a variable that *is* set resolves to a store, so the door is a
    # door and not a wall: `None` means "no fixture root", nothing else.
    assert FixtureStore.resolve({FIXTURE_DIR_ENV: "fixtures"}).root == Path(
        "fixtures"
    )


def test_a_blank_root_is_refused_by_name():
    # Path("") silently becomes ".", so a blank root would file fixtures into
    # the process's working directory — found or not depending on where the
    # process started, which is worse than no store at all.
    with pytest.raises(FixtureStoreError):
        FixtureStore("")


def test_a_root_that_is_not_a_path_is_refused_by_name():
    # The seam's error vocabulary, never the standard library's TypeError: a
    # caller catching FixtureStoreError gets the same answer whichever
    # malformation it met.
    with pytest.raises(FixtureStoreError):
        FixtureStore(None)  # type: ignore[arg-type]


def test_the_directory_appears_only_when_a_capture_needs_it(fixture_store, fixture_root):
    # Before the write: nothing.  After: the root and the file.  The store
    # creates its own root lazily, the way every store in this member creates
    # its own table lazily — and a read must not do it at all (see below).
    assert not fixture_root.exists()

    fixture_store.record(Exchange(request=_ask(), completion=_answer()))

    assert fixture_root.is_dir()


def test_a_read_does_not_bring_the_directory_into_being(fixture_root):
    # A read of a store that has never recorded creates nothing — the same
    # stance every store in this member takes for its own table, and the reason
    # `get` answers None rather than raising on a missing directory.
    store = FixtureStore(fixture_root)

    assert store.get(_ask()) is None
    assert store.files() == ()
    assert not fixture_root.exists()


def test_path_for_computes_the_address_without_touching_disk(fixture_store, fixture_root):
    # Public because a tool that wants to *look* at a fixture should not have to
    # re-derive the naming: a second spelling of the address is a second thing
    # to keep in sync, and a tool that guessed it wrong would report a recorded
    # prompt as unrecorded.
    path = fixture_store.path_for(_ask())

    assert path == fixture_root / f"{prompt_hash(_ask())}{FIXTURE_SUFFIX}"
    assert not fixture_root.exists()


def test_has_reports_a_filed_prompt_without_reading_it(fixture_store, capture):
    # A caller's chance to probe the record before committing to a capture —
    # the question the read path asks, without opening the file and without
    # raising.
    exchange = capture(lambda request: _answer("a1", model=request.model))
    fixture_store.record(exchange)

    assert fixture_store.has(exchange.request) is True
    assert fixture_store.has(_ask("never asked")) is False


def test_the_write_leaves_no_temp_file_behind(fixture_store, fixture_root):
    # The atomic write goes through a dot-prefixed temp file in the destination
    # directory and then renames it onto the final name.  The rename is what
    # makes it atomic, and the *cleanup* is what keeps the directory exactly the
    # set of fixtures it holds: a leftover temp would be a stray file in a
    # directory a deployment reviews in a diff, and — because it is dot-prefixed
    # and not a key — one `files()` would silently skip while a human reading
    # `ls -a` would have to wonder about it.
    fixture_store.record(Exchange(request=_ask(), completion=_answer()))

    leftovers = [entry.name for entry in fixture_root.iterdir() if entry.name.startswith(".")]
    assert leftovers == []
    assert len(fixture_store.files()) == 1


def test_a_failed_write_leaves_no_temp_file_behind(fixture_store, fixture_root):
    # The same property on the failure path, which is the one that matters: the
    # `finally: unlink()` exists for the write that raises partway through, and
    # a refusal the store itself produces must not strand its temp either.  A
    # conflict is refused *before* anything is opened, so this asserts the whole
    # observable state rather than only the file: no temp, and the stored
    # fixture still the only thing in the directory.
    filed = fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    with pytest.raises(FixtureConflictError):
        fixture_store.record(
            Exchange(request=_ask(), completion=_answer("contradiction"))
        )

    assert [entry.name for entry in fixture_root.iterdir()] == [filed.path.name]


# ── Idempotence, and the one thing that is a conflict ────────────────────────


def test_recording_the_identical_exchange_again_writes_nothing(fixture_store, capture):
    # A capture retried after an interrupted run is the same record arriving
    # twice, not a contradiction: it must be a no-op, or re-running a capture
    # would churn the directory and every fixture would have to be re-reviewed.
    exchange = capture(lambda request: _answer("a1", model=request.model))
    first = fixture_store.record(exchange)
    before = first.path.read_bytes()

    second = fixture_store.record(exchange)

    assert second.key == first.key
    assert second.path.read_bytes() == before


def test_the_identical_record_arriving_twice_leaves_one_file(fixture_store, capture):
    # The directory's cardinality, asserted directly: idempotence is about
    # *files*, and a store that appended rather than answered would leave two.
    exchange = capture(lambda request: _answer("a1", model=request.model))

    fixture_store.record(exchange)
    fixture_store.record(exchange)

    assert len(fixture_store.files()) == 1


def test_a_second_answer_for_one_prompt_is_refused(fixture_store):
    # One prompt hash has one answer — that is what addressing a fixture by its
    # prompt *means*.  Overwriting would let the second capture silently
    # contradict the first, and a replay would then answer a prompt with an
    # exchange nobody reviewed, which is the whole failure a fixture prevents.
    request = _ask()
    fixture_store.record(Exchange(request=request, completion=_answer("stored")))

    with pytest.raises(FixtureConflictError):
        fixture_store.record(Exchange(request=request, completion=_answer("other")))


def test_the_conflict_names_the_key_and_leaves_the_stored_file_untouched(fixture_store):
    # The refusal happens *after* the existing file is read and *before*
    # anything is written, so a contradiction cannot destroy the fixture it
    # contradicts — and the message names the key, so the caller knows which
    # prompt it is looking at.
    request = _ask()
    filed = fixture_store.record(
        Exchange(request=request, completion=_answer("stored"))
    )
    before = filed.path.read_bytes()

    with pytest.raises(FixtureConflictError) as excinfo:
        fixture_store.record(
            Exchange(request=request, completion=_answer("other"))
        )

    assert filed.key in str(excinfo.value)
    assert filed.path.read_bytes() == before


def test_the_conflict_message_carries_both_completions(fixture_store):
    # The repair is "decide which capture to keep", and that decision needs both
    # values in front of the caller — the refusal's whole job.
    request = _ask()
    fixture_store.record(Exchange(request=request, completion=_answer("stored")))

    with pytest.raises(FixtureConflictError) as excinfo:
        fixture_store.record(
            Exchange(request=request, completion=_answer("offered"))
        )

    message = str(excinfo.value)
    assert "stored" in message
    assert "offered" in message


def test_a_different_completion_for_an_equal_prompt_still_conflicts(
    fixture_store, capture, make_request
):
    # The conflict is keyed on the **prompt's value**, not on object identity —
    # the same value-equality the whole keying story rests on.  A fresh, equal
    # request carrying a different answer is still one prompt answered twice.
    exchange = capture(lambda request: _answer("a1", model=request.model))
    fixture_store.record(exchange)

    with pytest.raises(FixtureConflictError):
        fixture_store.record(
            Exchange(
                request=make_request(bodies=(("user", "q"),)),
                completion=_answer("different", model=exchange.request.model),
            )
        )


# ── The read path: verification, because a directory is a directory ──────────


def test_get_answers_none_for_a_prompt_never_recorded(fixture_store):
    # None means *never recorded*, which is the honest answer for a prompt no
    # file holds — and is not the same as a store that failed to read, which
    # raises.  A caller must be able to tell the two apart, because one repair
    # is "record the prompt" and the other is "fix the directory".
    assert fixture_store.get(_ask("never asked")) is None


def test_a_read_of_a_damaged_file_refuses_rather_than_reporting_it_unrecorded(
    fixture_store,
):
    # The distinction the previous test draws, from the other side: a file that
    # IS there but cannot be read must never be reported as an unrecorded
    # prompt, or a caller would record over a fixture it could have repaired.
    filed = fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    filed.path.write_text("not json at all", encoding="utf-8")

    with pytest.raises(FixtureCorruptError):
        fixture_store.get(_ask())


def test_a_file_filed_under_the_wrong_name_is_refused(fixture_store):
    # The first of the two verification checks: the file's own `prompt_hash`
    # field must equal the name it is filed under.  A fixture copied under
    # another prompt's name would otherwise answer a question nobody captured
    # an answer to.
    filed = fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    document = json.loads(filed.path.read_text(encoding="utf-8"))
    document["prompt_hash"] = "0" * 64
    filed.path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureCorruptError) as excinfo:
        fixture_store.get(_ask())

    assert filed.path.name in str(excinfo.value)


def test_a_file_whose_request_disagrees_with_its_key_is_refused(fixture_store):
    # The second check: the declared key must also equal prompt_hash of the
    # **request the file holds**.  A document whose two halves came from
    # different captures would otherwise replay an exchange nobody made —
    # exactly the state a hand-edit or a half-copied tree leaves behind.
    filed = fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    document = json.loads(filed.path.read_text(encoding="utf-8"))
    document["request"]["messages"] = [{"role": "user", "content": "something else"}]
    filed.path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureCorruptError):
        fixture_store.get(_ask())


def test_an_unparseable_file_under_a_key_is_refused(fixture_store):
    # The third shape of the same failure: bytes filed under a fixture's name
    # that are not this store's JSON at all.  Reconstructing a fixture from a
    # partial document would be inventing an exchange and filing it under a key
    # that claims it was captured.
    filed = fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    filed.path.write_text("{truncated", encoding="utf-8")

    with pytest.raises(FixtureCorruptError):
        fixture_store.get(_ask())


def test_a_document_of_the_wrong_shape_is_refused(fixture_store):
    # Valid JSON that is not a fixture — a bare list, say.  It parses, and it
    # still is not a request and a completion.
    filed = fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    filed.path.write_text("[]", encoding="utf-8")

    with pytest.raises(FixtureCorruptError):
        fixture_store.get(_ask())


def test_a_fixture_missing_one_half_is_refused(fixture_store):
    # "persisting request and response **together**": a document carrying only
    # one of them is not the pair the sentence names.
    filed = fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    document = json.loads(filed.path.read_text(encoding="utf-8"))
    del document["completion"]
    filed.path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureCorruptError):
        fixture_store.get(_ask())


def test_a_malformed_field_is_refused_by_the_records_own_guard(fixture_store):
    # The fields are handed to the interface's constructors, so a fixture
    # carrying a temperature outside the legal range is refused by the *same*
    # guard that refuses a caller's — one validation, not a second set written
    # here.  The interface's own sentence is carried into the message, so the
    # reader is told *which field* and *why* without unwrapping a traceback.
    filed = fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    document = json.loads(filed.path.read_text(encoding="utf-8"))
    document["request"]["temperature"] = 5.0
    filed.path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureCorruptError) as excinfo:
        fixture_store.get(_ask())

    assert "temperature" in str(excinfo.value)
    # ...and the original is chained, so nothing is lost by translating.
    assert isinstance(excinfo.value.__cause__, ProviderError)


def test_a_corrupt_fixture_is_refused_in_this_features_vocabulary(fixture_store):
    # The load-bearing half of the previous test, asserted as the *class* rather
    # than merely "an error".  The guard that refuses the bad field is feature
    # 192's, and its `CompletionMalformedError` **is** a `ProviderError` — so
    # without a translation this read would raise a phrase about model calls for
    # bytes that were never sent anywhere, and a caller's `except
    # FixtureStoreError` around `get` would miss the one failure the read path
    # exists to catch.  A test that caught `Exception` would pass under either
    # vocabulary and prove nothing.
    filed = fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    document = json.loads(filed.path.read_text(encoding="utf-8"))
    document["request"]["temperature"] = 5.0
    filed.path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureCorruptError):
        fixture_store.get(_ask())


@pytest.mark.parametrize(
    "field, mutate",
    [
        ("temperature", lambda document: document["request"].__setitem__("temperature", 5.0)),
        (
            "usage",
            lambda document: document["completion"]["usage"].__setitem__(
                "input_tokens", -1
            ),
        ),
    ],
)
def test_both_of_the_interfaces_guard_vocabularies_arrive_translated(
    fixture_store, field, mutate
):
    # The fact that makes the translation non-obvious, pinned so a later reader
    # does not "simplify" the catch down to one class: the interface's guards
    # are **not uniform**.  `Request` and `Completion` raise
    # `CompletionMalformedError` — a `ProviderError` — while the nested `Usage`
    # raises a bare `ValueError`, since a count below zero is a plain
    # out-of-range number rather than a violation of the provider contract.  A
    # translation catching only the first would let a fixture holding a negative
    # token count raise a `ValueError` that no caller of this store expects and
    # no `except FixtureStoreError` of theirs catches.
    #
    # Parametrised rather than looped, because each case needs its own store:
    # the first case leaves a corrupt file behind, and re-recording over it
    # would raise the *conflict* rather than exercise the read.
    filed = fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    document = json.loads(filed.path.read_text(encoding="utf-8"))
    mutate(document)
    filed.path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureCorruptError) as excinfo:
        fixture_store.get(_ask())

    # The interface's own sentence is carried through, so the reader is told
    # which field and why without unwrapping the chain — and the field named is
    # the one the fixture actually got wrong.
    assert field in str(excinfo.value)


def test_a_malformed_exchange_is_refused_in_this_features_vocabulary(fixture_store):
    # And the same translation on the *write* path, where the bad value came
    # from a caller's hand-built exchange rather than off disk — which is why
    # the class is the base rather than the corruption subclass: the repair is
    # the call, not a file.
    class Stub:
        messages = (type("T", (), {"role": "user", "content": "q"})(),)
        model = "m"
        temperature = "hot"
        max_tokens = 64

    with pytest.raises(FixtureStoreError) as excinfo:
        fixture_store.record(Exchange(request=Stub(), completion=_answer()))

    assert not isinstance(excinfo.value, FixtureCorruptError)
    assert "temperature" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ProviderError)


# ── The listing: what a directory holds ──────────────────────────────────────


def test_files_lists_what_was_captured_in_key_order(fixture_store):
    # Ordered by **key** rather than by directory order, so the listing is
    # value-equal: two stores holding the same fixtures list them in the same
    # order whatever the filesystem hands over, which is what makes a tuple
    # comparison in a suite mean anything.
    for content in ("one", "two", "three"):
        fixture_store.record(
            Exchange(request=_ask(content), completion=_answer(f"a-{content}"))
        )

    keys = [fixture.key for fixture in fixture_store.files()]

    assert keys == sorted(keys)
    assert fixture_store.keys() == tuple(keys)
    assert len(keys) == 3


def test_files_ignores_a_file_that_is_not_a_fixture(fixture_root, fixture_store):
    # The root is a directory a deployment may keep other things in: a README,
    # a manifest, and — the case that actually happens — the dot-prefixed temp
    # file a crashed atomic write leaves behind.  A reader that refused the
    # directory for holding one would be refusing a store for a stranger's file.
    fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    (fixture_root / "README.md").write_text("how to re-record\n")
    (fixture_root / f".{'a' * 64}{FIXTURE_SUFFIX}.deadbeef.tmp").write_text("debris")
    (fixture_root / "notes.txt").write_text("x")

    assert len(fixture_store.files()) == 1


def test_files_still_refuses_bytes_under_a_real_key(fixture_root, fixture_store):
    # ...but a name that *is* a fixture key is the store's own business, and
    # bytes under it that are not the fixture for it are refused rather than
    # skipped.  The distinction is whose file it is: a README is a stranger's,
    # `abcd….json` is this store's.
    fixture_store.record(Exchange(request=_ask(), completion=_answer()))
    (fixture_root / f"{'b' * 64}{FIXTURE_SUFFIX}").write_text("junk")

    with pytest.raises(FixtureCorruptError):
        fixture_store.files()


def test_files_answers_an_empty_tuple_for_a_root_that_is_not_there(fixture_root):
    # The same "a read creates nothing" stance `get` takes, spelled for the
    # listing: no directory, no fixtures, no error.
    assert FixtureStore(fixture_root).files() == ()


def test_responses_hands_back_the_pairs_feature_193_replays(fixture_store):
    # The bridge between the two halves of the recorded-fixture layer: the pairs
    # this returns are exactly what RecordedProvider takes, so the loop closes
    # with no conversion step in between.
    request = _ask()
    answer = _answer()
    fixture_store.record(Exchange(request=request, completion=answer))

    responses = fixture_store.responses()

    assert responses == (RecordedResponse(request=request, completion=answer),)
    assert all(isinstance(entry, RecordedResponse) for entry in responses)


def test_a_fixture_answers_its_own_pair(fixture_store, capture):
    # FixtureFile.response is derived rather than stored, so the pair and the
    # file cannot disagree about what was captured.
    exchange = capture(lambda request: _answer("a1", model=request.model))
    filed = fixture_store.record(exchange)

    assert filed.response == RecordedResponse(
        request=exchange.request, completion=exchange.completion
    )
    assert isinstance(filed, FixtureFile)


# ── The capture: a whole recorder's run, filed ───────────────────────────────


def test_record_all_files_every_exchange_in_order(fixture_store):
    # What a deployment that has just captured a run actually wants: the whole
    # ordered tuple a RecordingProvider hands up, filed in one call.
    exchanges = tuple(
        Exchange(request=_ask(content), completion=_answer(f"a-{content}"))
        for content in ("one", "two", "three")
    )

    filed = fixture_store.record_all(exchanges)

    assert [entry.request for entry in filed] == [
        exchange.request for exchange in exchanges
    ]
    assert fixture_store.keys() == tuple(sorted(fixture_store.keys()))


def test_record_all_refuses_a_value_that_is_not_a_collection(fixture_store):
    # A string is iterable, so it would otherwise be read as one exchange per
    # character — a directory full of nonsense rather than a refusal.  A mapping
    # is refused for the same kind of reason: its keys are a plausible
    # mis-spelling of a collection, and reading them would be guessing at which
    # half of the caller's structure was meant.
    with pytest.raises(FixtureStoreError):
        fixture_store.record_all("abc")

    with pytest.raises(FixtureStoreError):
        fixture_store.record_all({"a": "b"})

    with pytest.raises(FixtureStoreError):
        fixture_store.record_all(7)


def test_a_partial_capture_is_completed_by_re_running_it(fixture_store):
    # record_all is a loop, not a transaction, and that is correct rather than
    # lenient: a fixture is a *value* keyed by its own content, so a partial
    # capture is not a corrupt one.  Re-running the record completes the
    # directory, because every file already filed is answered rather than
    # rewritten — the per-key idempotence doing the work.
    first = Exchange(request=_ask("one"), completion=_answer("a-one"))
    second = Exchange(request=_ask("two"), completion=_answer("a-two"))
    fixture_store.record_all([first])

    filed = fixture_store.record_all([first, second])

    assert len(filed) == 2
    assert len(fixture_store.files()) == 2


def test_a_capture_refused_partway_leaves_the_files_it_filed(fixture_store):
    # The other side of the same decision: the refusal stops the run and names
    # the exchange it stopped on, and the files already written stay written.
    # A transactional capture would have to *undo* good files to report one bad
    # exchange, which is the opposite of what a value-addressed store wants.
    good = Exchange(request=_ask("one"), completion=_answer("a-one"))
    fixture_store.record_all([good])
    clashing = Exchange(request=_ask("one"), completion=_answer("different"))

    with pytest.raises(FixtureConflictError):
        fixture_store.record_all([clashing, Exchange(request=_ask("two"), completion=_answer())])

    assert len(fixture_store.files()) == 1


# ── The interchange: what may be filed ───────────────────────────────────────


def test_both_sibling_shapes_build_the_same_fixture(fixture_store):
    # Feature 192's Exchange and feature 193's RecordedResponse are the same two
    # fields under two names, and the two features produced both — so a caller
    # should not have to convert between them to file a fixture.
    request = _ask()
    answer = _answer()

    from_exchange = fixture_store.record(Exchange(request=request, completion=answer))
    same_key = FixtureStore(fixture_store.root.parent / "other").record(
        RecordedResponse(request=request, completion=answer)
    )

    assert from_exchange.key == same_key.key


def test_a_foreign_copy_of_the_exchange_is_re_made_from_this_modules_classes(
    fixture_store,
):
    # The double-import seam, and here it is load-bearing in a way the sibling
    # features' seams are not: the key is computed by `prompt_hash` on the
    # **re-made** request, so the address a caller's exchange is filed under is
    # this module's canonical address whatever copy built the request.  A
    # dataclass's generated __eq__ answers False between two copies of one
    # source file, so an isinstance gate would refuse the very pair the caller
    # legitimately built.
    #
    # A duck-typed namespace rather than nested classes: a nested class body
    # cannot see a sibling nested class's name while that body is executing
    # (the class is not yet bound), which is a Python scoping rule and not
    # anything about the seam — `SimpleNamespace` says the same thing without
    # tripping over it.
    def _turn(role, content):
        return SimpleNamespace(role=role, content=content)

    foreign = SimpleNamespace(
        request=SimpleNamespace(
            messages=(_turn("user", "q"),),
            model="m",
            temperature=0.0,
            max_tokens=1024,
        ),
        completion=SimpleNamespace(
            content="a",
            model="m",
            finish_reason="stop",
            usage=SimpleNamespace(
                input_tokens=1, output_tokens=2, cache_read_tokens=0
            ),
        ),
    )

    filed = fixture_store.record(foreign)

    assert filed.key == prompt_hash(_ask())
    assert type(filed.request) is Request
    assert type(filed.completion) is Completion


def test_a_bare_tuple_is_refused_because_it_is_193s_key_shape(fixture_store):
    # The refusal that is the interesting half of the interchange story.
    # `(asking, answering)` looks like the obvious input, but
    # `RecordedProvider` already reads a two-tuple as
    # `(prompt_hash, completion)` — and a tuple has no names, so this store
    # cannot tell the two apart.  Accepting one would file a *key* as a request:
    # a fixture whose prompt is a 64-character string, at an address no request
    # would ever find again.
    with pytest.raises(FixtureStoreError) as excinfo:
        fixture_store.record((_ask(), _answer()))

    assert "RecordedProvider" in str(excinfo.value)


def test_a_value_that_is_not_a_pair_is_refused(fixture_store):
    # A backend built around the wrong shape would file nothing and fail
    # nowhere, so the shape is checked before anything is opened.
    for wrong in ("nope", 7, None, {"request": _ask(), "completion": _answer()}):
        with pytest.raises(FixtureStoreError):
            fixture_store.record(wrong)


def test_a_pair_whose_completion_is_not_a_completion_is_refused(fixture_store):
    # "persisting request and response together" — a value that is not the
    # normalized completion feature 192's interface carries is not the response
    # half of that record.
    with pytest.raises(FixtureStoreError):
        fixture_store.record(Exchange(request=_ask(), completion="not a completion"))


def test_a_pair_whose_request_is_not_a_request_is_refused(fixture_store):
    # ...and the ask half.  A fixture is addressed by the prompt that was asked;
    # a value that is not that record has no prompt to key by and no messages to
    # persist.
    with pytest.raises(FixtureStoreError):
        fixture_store.record(Exchange(request="not a request", completion=_answer()))


def test_a_completion_whose_usage_is_malformed_is_refused_in_our_vocabulary(
    fixture_store,
):
    # The nested record's own guard, reached through the structural read: a
    # stub whose usage carries a non-integer count is refused by `Usage`'s
    # constructor, and — like the request's and the completion's — the refusal
    # arrives as this feature's error rather than as the interface's.  The
    # *value* is the point: a caller filing a hand-built exchange catches one
    # vocabulary for every malformation, so it never has to know which of the
    # three constructors happened to be the one to object.
    class Stub:
        content = "a"
        model = "m"
        finish_reason = "stop"
        usage = type(
            "U",
            (),
            {"input_tokens": "many", "output_tokens": 2, "cache_read_tokens": 0},
        )()

    with pytest.raises(FixtureStoreError) as excinfo:
        fixture_store.record(Exchange(request=_ask(), completion=Stub()))

    assert not isinstance(excinfo.value, FixtureCorruptError)
    assert "usage" in str(excinfo.value)


def test_a_request_whose_messages_are_not_a_conversation_is_refused(fixture_store):
    # A string is iterable, so a request whose `messages` is one would be read
    # as one turn per character — the failure mode that produces a nonsense
    # conversation rather than a refusal.
    class Stub:
        messages = "not a conversation"
        model = "m"
        temperature = 0.0
        max_tokens = 64

    with pytest.raises(FixtureStoreError):
        fixture_store.record(Exchange(request=Stub(), completion=_answer()))


# ── The vocabulary ───────────────────────────────────────────────────────────


def test_the_base_is_its_own_question_not_the_call_seams():
    # The taxonomy splits by *question*, not by call site, and this store's
    # question is about **files**: can this exchange be filed under its prompt
    # hash, and read back as one?  It is deliberately unrelated to
    # ProviderError, so a caller's `except ProviderError` around a model call
    # does not silently swallow a fixture-file problem whose repair is
    # completely different.
    assert not issubclass(FixtureStoreError, ProviderError)


def test_both_refusals_join_the_one_base():
    # One handle for every way feature 194's sentence can fail, the way
    # ProviderError gives the call seam one and RootProviderError gives the root
    # provenance one.
    assert issubclass(FixtureConflictError, FixtureStoreError)
    assert issubclass(FixtureCorruptError, FixtureStoreError)


def test_feature_193s_refusal_is_left_exactly_where_it_was():
    # The nearest neighbour, pinned so the split cannot drift: 193's refusal IS
    # a ProviderError — correctly, because that backend *is* a provider — and
    # this store's base is not.  The two answer different questions with
    # different repairs ("record the prompt" versus "fix the file"), which is
    # the whole reason feature 194 does not fold into 193's vocabulary.
    assert issubclass(FixtureNotFoundError, ProviderError)
    assert not issubclass(FixtureConflictError, FixtureNotFoundError)
    assert not issubclass(FixtureCorruptError, FixtureNotFoundError)


def test_the_suffix_is_the_one_a_reader_opens_with():
    # Part of the address rather than decoration: `.json` is what tells a reader
    # which parser opens the file, and `files()` keys on it.
    assert FIXTURE_SUFFIX == ".json"


def test_the_variable_is_the_one_the_spec_documents():
    # The spec's own spelling, matched by value so a rename is one edit and the
    # constant and the literal cannot drift.
    assert FIXTURE_DIR_ENV == "PROVIDER_FIXTURE_DIR"


# ── The loop closes: a captured directory replays with no network ────────────


def test_a_captured_directory_replays_offline(fixture_store):
    # The end-to-end sentence's own claim, reduced to one store and one backend:
    # *"a full campaign runs under fixed exploration against fixture-backed
    # agents"*.  The directory this store filed is handed to feature 193's
    # backend, which answers the prompt from the file — the two features
    # together being the record that makes an offline replay possible.
    request = _ask("what is the mechanism?")
    answer = _answer("momentum", model="claude-opus-5")
    fixture_store.record(Exchange(request=request, completion=answer))

    backend = RecordedProvider(fixture_store.responses())

    assert backend.complete(_ask("what is the mechanism?")).content == "momentum"


def test_a_directories_recorded_set_is_the_prompts_it_holds(fixture_store):
    # The directory's record, read the way a backend's is: the same question
    # feature 193 answers with `recorded()`, asked of the files.
    requests = [_ask("one"), _ask("two")]
    for request in requests:
        fixture_store.record(Exchange(request=request, completion=_answer()))

    backend = RecordedProvider(fixture_store.responses())

    assert set(backend.recorded()) == {
        prompt_hash(request) for request in requests
    }
    assert set(backend.recorded()) == set(fixture_store.keys())


def test_a_prompt_the_directory_does_not_hold_is_still_refused_by_193(
    fixture_store,
):
    # The one thing feature 194 must not change: a prompt with nothing filed is
    # refused by the backend with no live fallback.  The store has no opinion on
    # this — it answers None — and the backend is where the hard stop lives,
    # which is exactly why the two are separate objects.
    fixture_store.record(Exchange(request=_ask("recorded"), completion=_answer()))
    backend = RecordedProvider(fixture_store.responses())

    with pytest.raises(FixtureNotFoundError):
        backend.complete(_ask("never recorded"))
