"""The dedup gate — a duplicate is rejected before it charges a trial.

app_spec.xml, "Tree & Artifact Persistence", feature 179: *System
deduplicates a proposed node against stored ``code_hash`` values, which
rejects an exact duplicate before it charges a trial.*  These tests hold
the gate to that sentence in the three places it can be read:

* **the decision** — :func:`artifacts.reject_duplicate` over the campaign's
  stored hashes as *data*: an exact duplicate is refused, a distinct code
  is returned canonicalized, and the comparison is exact (case folded,
  length and alphabet checked) rather than approximate;
* **the read** — :class:`artifacts.CodeHashIndex` against the ``node``
  table §9.1 declares: the nodes holding a code are read back through the
  lookup ``node_code_hash`` exists to serve, a code the tree does not hold
  and an absent store both answer "nothing stored" rather than raising, and
  a store that cannot be read refuses rather than answering;
* **the ordering** — :meth:`CodeHashIndex.probe`, where the feature's
  "before it charges a trial" is actually enforced.  Three properties get
  their own section, because they are the ones a plausible-looking
  implementation gets wrong: the refusal lands *before* the caller's write
  (so a duplicate never reaches the row), the check and the write share
  one lock (so two proposers of one code cannot both pass), and a failed
  body rolls back rather than leaving a half-built node holding the lock.

The scope is pinned too, and it is the *whole* tree rather than one
campaign: §9.1 draws this feature's index on ``code_hash`` alone (where the
lookup that wants a campaign in its key is spelled separately as
``(campaign_id, parent_id)``), and 0117's argument that the index needs no
``UNIQUE`` — "the dedup gate refuses that pair before either charges a
trial, so the index has no duplicate rows to find" — holds only if the pair
is refused anywhere in the tree.  Re-testing a stored node is the replay
engine's job, which §1 grants the artifact store and no evaluator access to
precisely so it charges no trial.

The suite creates the ``node`` table itself rather than importing a
migration: the tree member owns that DDL (features 97–102) and this member
owns the check that reads it.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

import pytest
from artifacts import (
    CODE_HASH_LENGTH,
    DATABASE_URL_ENV,
    DUPLICATE_CODE_HASH,
    NODE_TABLE,
    ArtifactDeduplicatedError,
    ArtifactProposalError,
    ArtifactsError,
    ArtifactStoreError,
    CodeHashIndex,
    StoredCodeHash,
    canonical_code_hash,
    reject_duplicate,
)

#: Two distinct sha256 digests, spelled as the system computes them — so a
#: test about the *comparison* is never accidentally about the spelling.
SIGNAL_A = hashlib.sha256(b"def signal(): return momentum").hexdigest()
SIGNAL_B = hashlib.sha256(b"def signal(): return carry").hexdigest()


def _insert(connection: sqlite3.Connection, **row: object) -> None:
    """Insert one ``node`` row the way a tree writer would."""
    connection.execute(
        f"INSERT INTO {NODE_TABLE} "
        "(id, parent_id, campaign_id, theme_root, depth, code_hash) "
        "VALUES (:id, :parent_id, :campaign_id, :theme_root, :depth, "
        ":code_hash)",
        {
            "id": "n",
            "parent_id": None,
            "theme_root": None,
            "depth": None,
            **row,
        },
    )


# -- The spelling ----------------------------------------------------------------


def test_a_sha256_hexdigest_is_the_canonical_code_hash() -> None:
    # The one spelling §9.1's CHAR(64) holds: the lowercase hexdigest the
    # system computes.  Returned unchanged, so a caller can chain it.
    assert canonical_code_hash(SIGNAL_A) == SIGNAL_A
    assert len(canonical_code_hash(SIGNAL_A)) == CODE_HASH_LENGTH


def test_the_canonical_spelling_folds_case_rather_than_refusing_it() -> None:
    # "AB…" and "ab…" are one digest written two ways.  A gate that treated
    # them as two codes would let the second spelling of a duplicate
    # through, which is the one thing this feature exists to prevent.
    assert canonical_code_hash(SIGNAL_A.upper()) == SIGNAL_A
    assert canonical_code_hash(f"  {SIGNAL_A.upper()}  ") == SIGNAL_A


@pytest.mark.parametrize(
    "value",
    [
        SIGNAL_A[:63],  # truncated
        SIGNAL_A + "0",  # too long
        "z" * 64,  # not hex
        f"sha256:{SIGNAL_A}",  # an image reference, not a code hash
        "ab" * 32 + "\x00",
        "",
        "   ",
        None,
        123,
        b"a" * 64,
    ],
    ids=[
        "short",
        "long",
        "non-hex",
        "prefixed",
        "nul",
        "empty",
        "blank",
        "none",
        "int",
        "bytes",
    ],
)
def test_a_value_that_is_not_a_code_hash_is_refused_by_name(value: object) -> None:
    # A proposal that cannot state its code identity cannot be compared
    # against anything, so it must be refused rather than skipped: a gate
    # that guessed would pass every duplicate it was handed.
    with pytest.raises(ArtifactProposalError, match="code_hash"):
        canonical_code_hash(value)


def test_a_malformed_hash_is_not_reported_as_a_duplicate() -> None:
    # The two refusals are different facts and a caller acts on them
    # differently: "this proposal is malformed" is the caller's bug, while
    # "this proposal is a repeat" is a verdict to act on by proposing
    # something else.  The malformed one must not carry the duplicate code.
    with pytest.raises(ArtifactProposalError) as caught:
        canonical_code_hash("nope")
    assert not isinstance(caught.value, ArtifactDeduplicatedError)
    assert DUPLICATE_CODE_HASH not in str(caught.value)


# -- The decision, over data ------------------------------------------------------


def test_an_exact_duplicate_is_rejected() -> None:
    # Feature 179's sentence, at its narrowest: the same code hash is
    # already stored, so the proposal is refused.
    with pytest.raises(ArtifactDeduplicatedError) as caught:
        reject_duplicate(SIGNAL_A, [SIGNAL_B, SIGNAL_A])
    assert str(caught.value).startswith(DUPLICATE_CODE_HASH)


def test_a_distinct_code_passes_and_comes_back_canonicalized() -> None:
    assert reject_duplicate(SIGNAL_A, [SIGNAL_B]) == SIGNAL_A
    assert reject_duplicate(SIGNAL_A.upper(), [SIGNAL_B]) == SIGNAL_A


def test_an_empty_tree_rejects_nothing() -> None:
    # The first node of a tree is never a duplicate of anything.
    assert reject_duplicate(SIGNAL_A, []) == SIGNAL_A


def test_a_duplicate_is_rejected_however_the_caller_spelled_either_side() -> None:
    # The comparison is on the canonical form, so neither the proposal's
    # spelling nor the stored one can smuggle a duplicate past the gate.
    with pytest.raises(ArtifactDeduplicatedError):
        reject_duplicate(SIGNAL_A.upper(), [SIGNAL_A])
    with pytest.raises(ArtifactDeduplicatedError):
        reject_duplicate(SIGNAL_A, [f" {SIGNAL_A.upper()} "])


def test_the_refusal_names_the_proposal_and_what_did_not_happen() -> None:
    # The message is the operator's whole account of the rejection: which
    # code, which proposed node, and — the part a caller acts on — that no
    # trial was charged, because the rejection precedes the charge.
    with pytest.raises(ArtifactDeduplicatedError) as caught:
        reject_duplicate(SIGNAL_A, [SIGNAL_A], node_id="node-9")
    message = str(caught.value)
    assert SIGNAL_A in message
    assert "node-9" in message
    assert "no trial was debited" in message
    assert "K_effective" in message


def test_a_corrupt_stored_hash_refuses_rather_than_being_skipped() -> None:
    # A stored row that does not hold a code hash is a tree this gate
    # cannot vouch for.  Silently ignoring it would mean a duplicate hiding
    # behind one corrupt row is charged like a fresh hypothesis — so it is
    # refused, and *not* with the duplicate code, because "the store is not
    # readable" is a different fact from "the proposal is a repeat".
    with pytest.raises(ArtifactProposalError) as caught:
        reject_duplicate(SIGNAL_A, ["not-a-hash"])
    assert not isinstance(caught.value, ArtifactDeduplicatedError)
    assert "stored" in str(caught.value)


def test_a_corrupt_stored_hash_is_refused_even_when_the_proposal_would_pass() -> None:
    # The check cannot be conditional on finding a match: the row it would
    # have hidden behind is exactly the one the gate never got to compare.
    with pytest.raises(ArtifactProposalError):
        reject_duplicate(SIGNAL_A, [SIGNAL_B, "junk"])


def test_the_duplicate_code_is_the_specs_own_word() -> None:
    # Pinned as a value, so the code the message carries and the code the
    # spec names cannot drift apart.
    assert DUPLICATE_CODE_HASH == "duplicate_code_hash"


# -- The stored spelling: the lookup the index serves ------------------------------


def test_the_holders_of_a_stored_code_hash_are_read_back(
    tree_store: object,
    campaign_id: str,
) -> None:
    # The rows feature 179 compares against — every node carrying this code
    # — keyed and sorted by node id so two reads of an unchanged tree answer
    # identically.
    with tree_store.connect() as connection:
        _insert(connection, id="n-b", campaign_id=campaign_id, code_hash=SIGNAL_A)
        _insert(connection, id="n-a", campaign_id=campaign_id, code_hash=SIGNAL_A)
        _insert(connection, id="n-c", campaign_id=campaign_id, code_hash=SIGNAL_B)

    gate = CodeHashIndex.from_env()
    assert gate.holders(SIGNAL_A) == (
        StoredCodeHash("n-a", SIGNAL_A),
        StoredCodeHash("n-b", SIGNAL_A),
    )
    assert gate.holders(SIGNAL_B) == (StoredCodeHash("n-c", SIGNAL_B),)


def test_the_lookup_is_over_the_whole_tree_not_one_campaign(
    tree_store: object, campaign_id: str, other_campaign_id: str
) -> None:
    # §9.1 draws this feature's index on ``code_hash`` *alone* — where the
    # lookup that wants a campaign in its key is spelled separately as
    # ``(campaign_id, parent_id)`` — and 0117 reads the same fact from the
    # constraint side: "two distinct nodes may hash to the same code only by
    # being the same code ... so the index has no duplicate rows to find."
    # That argument holds only if the gate refuses the pair anywhere in the
    # tree.  A campaign-scoped gate would leave one code in two campaigns
    # and hand the index exactly the duplicate rows 0117 says it has none
    # of — so the same code in a *different* campaign is still a duplicate.
    with tree_store.connect() as connection:
        _insert(connection, id="n-1", campaign_id=campaign_id, code_hash=SIGNAL_A)

    gate = CodeHashIndex.from_env()
    with pytest.raises(ArtifactDeduplicatedError):
        gate.check(SIGNAL_A)
    assert gate.holders(SIGNAL_A) == (StoredCodeHash("n-1", SIGNAL_A),)

    # The same code proposed into another campaign is the same node: the
    # campaign it is proposed under is not part of the code's identity.
    with pytest.raises(ArtifactDeduplicatedError), gate.probe(
        SIGNAL_A
    ) as connection:
        _insert(
            connection,
            id="n-2",
            campaign_id=other_campaign_id,
            code_hash=SIGNAL_A,
        )


def test_a_code_the_tree_does_not_hold_is_answered_empty(
    tree_store: object, campaign_id: str
) -> None:
    # The common case, and the answer a proposal path acts on: this is not a
    # listing, so an unrelated stored node is simply not a holder.
    with tree_store.connect() as connection:
        _insert(connection, id="n-1", campaign_id=campaign_id, code_hash=SIGNAL_B)

    gate = CodeHashIndex.from_env()
    assert gate.holders(SIGNAL_A) == ()
    assert gate.check(SIGNAL_A) == SIGNAL_A


def test_an_absent_store_holds_nothing() -> None:
    # No database file at all: no node can be stored in it, so the true
    # answer is "nothing stored" rather than a refusal — a gate that could
    # not distinguish an empty tree from an unopenable one would either
    # charge every duplicate or refuse every proposal.
    gate = CodeHashIndex.from_env()
    assert gate.holders(SIGNAL_A) == ()
    assert gate.check(SIGNAL_A) == SIGNAL_A


def test_a_malformed_proposal_is_refused_before_any_lookup() -> None:
    # Otherwise the query would match nothing and read as "no duplicate" —
    # the silent pass this gate exists to prevent.
    gate = CodeHashIndex.from_env()
    with pytest.raises(ArtifactProposalError):
        gate.holders("not-a-hash")
    with pytest.raises(ArtifactProposalError):
        gate.check("not-a-hash")


def test_a_store_that_exists_without_the_node_table_refuses(
    test_database_url: str,
) -> None:
    # An *unreadable* store is not an empty one: a gate that answered "no
    # duplicate" because its query failed would charge every repeat.  The
    # database file exists here but carries no ``node`` table — the state a
    # deployment is in before the tree migrations land — and that is a
    # failure to read, not a tree with nothing in it.
    with sqlite3.connect(
        Path(test_database_url.removeprefix("sqlite:///"))
    ) as connection:
        connection.execute("CREATE TABLE unrelated (x TEXT)")

    gate = CodeHashIndex.from_env()
    with pytest.raises(ArtifactStoreError, match="must never read as one"):
        gate.holders(SIGNAL_A)


def test_an_absent_database_file_holds_nothing() -> None:
    # Distinct from the above, and deliberately so: a database that does not
    # exist at all cannot hold a node, so "nothing stored" is the *true*
    # answer rather than a read that failed.  Refusing here would make the
    # gate unusable on the very first proposal of a fresh deployment, which
    # is exactly when the tree is empty — the same stance the null oracle's
    # tree-store guard takes toward an absent database.
    gate = CodeHashIndex.from_env()
    assert gate.holders(SIGNAL_A) == ()


def test_an_in_memory_url_is_refused_by_name() -> None:
    # A gate whose store died with the connection that opened it would
    # deduplicate against nothing and charge every duplicate.  Resolution is
    # lazy — construction touches no disk — so the refusal lands at the
    # first operation that needs the store.
    with pytest.raises(ArtifactStoreError, match="in-memory"):
        CodeHashIndex("sqlite:///:memory:").holders(SIGNAL_A)


def test_a_non_sqlite_url_is_refused_by_name() -> None:
    with pytest.raises(ArtifactStoreError, match="sqlite"):
        CodeHashIndex("postgresql://localhost/tree").holders(SIGNAL_A)


def test_the_gate_refuses_an_empty_url() -> None:
    for empty in ("", "   "):
        with pytest.raises(ArtifactStoreError, match=DATABASE_URL_ENV):
            CodeHashIndex(empty)


def test_an_unset_database_url_resolves_no_gate() -> None:
    # The builder contract: a deployment with no relational store composes
    # no gate — a discoverable absence, not an exception, because the
    # factory builds every component on every create_app().
    assert CodeHashIndex.resolve(env={}) is None
    for empty in ("", "   "):
        assert CodeHashIndex.resolve(env={DATABASE_URL_ENV: empty}) is None


def test_resolve_reads_the_configured_url() -> None:
    gate = CodeHashIndex.resolve(env={DATABASE_URL_ENV: "sqlite:///tree.db"})
    assert gate is not None
    assert gate.database_url == "sqlite:///tree.db"


def test_construction_performs_no_io() -> None:
    # The composition contract: building the gate is composition-time work
    # and must not touch the disk, so a factory scan is safe anywhere.
    gate = CodeHashIndex("sqlite:///does/not/exist/tree.db")
    assert gate.database_url == "sqlite:///does/not/exist/tree.db"


# -- The ordering: "before it charges a trial" ------------------------------------


def test_the_probe_yields_the_connection_inside_its_lock(
    tree_store: object, campaign_id: str
) -> None:
    # The body's write lands in the store, and the probe's transaction is
    # the caller's to write through — which is what makes the check and the
    # write one region rather than two.
    gate = CodeHashIndex.from_env()
    with gate.probe(SIGNAL_A) as connection:
        _insert(connection, id="n-1", campaign_id=campaign_id, code_hash=SIGNAL_A)

    assert gate.holders(SIGNAL_A) == (StoredCodeHash("n-1", SIGNAL_A),)


def test_a_duplicate_is_refused_before_the_body_writes_anything(
    tree_store: object, campaign_id: str
) -> None:
    # The feature's whole sentence: "rejects an exact duplicate *before* it
    # charges a trial".  The refusal lands before the body runs, so the
    # caller's charge — which sits inside that body — never happens, and
    # nothing was written for the duplicate.
    with tree_store.connect() as connection:
        _insert(connection, id="n-1", campaign_id=campaign_id, code_hash=SIGNAL_A)

    gate = CodeHashIndex.from_env()
    charged: list[str] = []
    with pytest.raises(ArtifactDeduplicatedError), gate.probe(SIGNAL_A) as connection:
        # A caller's trial charge would live here; that it never runs
        # is the feature.
        charged.append("debited")
        _insert(connection, id="n-2", campaign_id=campaign_id, code_hash=SIGNAL_A)

    assert charged == []
    assert gate.holders(SIGNAL_A) == (StoredCodeHash("n-1", SIGNAL_A),)


def test_a_failed_body_rolls_back_so_no_half_node_lands(
    tree_store: object, campaign_id: str
) -> None:
    # A body that fails after writing must not leave its row behind: the
    # caller's retry would then find its own half-built node holding the
    # code it is about to propose.
    gate = CodeHashIndex.from_env()
    with pytest.raises(RuntimeError, match="boom"), gate.probe(SIGNAL_A) as connection:
        _insert(connection, id="n-1", campaign_id=campaign_id, code_hash=SIGNAL_A)
        raise RuntimeError("boom")

    assert gate.holders(SIGNAL_A) == ()
    # ...and the store is not left locked by the failed probe.
    assert gate.check(SIGNAL_A) == SIGNAL_A


def test_the_lock_is_released_after_a_refusal(
    tree_store: object, campaign_id: str
) -> None:
    # A refusal is a rollback, not a leak: the next proposal — which is what
    # the refusing caller does next — must not block on a lock the refusal
    # left behind.
    with tree_store.connect() as connection:
        _insert(connection, id="n-1", campaign_id=campaign_id, code_hash=SIGNAL_A)

    gate = CodeHashIndex.from_env()
    with pytest.raises(ArtifactDeduplicatedError), gate.probe(SIGNAL_A):
        pass  # pragma: no cover - the refusal precedes the yield

    # The very next proposal of a *different* code succeeds immediately.
    with gate.probe(SIGNAL_B) as connection:
        _insert(connection, id="n-2", campaign_id=campaign_id, code_hash=SIGNAL_B)
    assert len(gate.holders(SIGNAL_B)) == 1


def test_concurrent_proposers_of_one_code_charge_exactly_one_trial(
    tree_store: object, campaign_id: str
) -> None:
    # Migration 0113 names this exposure as feature 179's to close: *"two
    # writers racing feature 179's check can both pass it and both charge a
    # trial"*.  The probe closes it by holding the tree store's write lock
    # across the check *and* the caller's write, so concurrent proposals of
    # one code serialise and every proposer after the first is answered by
    # the first's row.  This is the test that would fail on a plain
    # read-then-write — and it is the reason the gate hands back a
    # connection instead of just answering a yes/no.
    charged: list[int] = []
    refused: list[int] = []
    failures: list[BaseException] = []

    def propose(index: int) -> None:
        gate = CodeHashIndex.from_env()
        try:
            with gate.probe(SIGNAL_A) as connection:
                _insert(
                    connection,
                    id=f"n-{index}",
                    campaign_id=campaign_id,
                    code_hash=SIGNAL_A,
                )
                # Where the caller's debit would go.  It must run exactly
                # once across every proposer of this code.
                charged.append(index)
        except ArtifactDeduplicatedError:
            refused.append(index)
        except BaseException as exc:  # noqa: BLE001 - a regression signal
            # Any other exception is a *finding*: a thread that died of its
            # own error would otherwise look like a proposer that was simply
            # refused, and the totals below would still add to 8.
            failures.append(exc)

    threads = [threading.Thread(target=propose, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert len(charged) == 1, "the trial was charged more than once"
    assert len(refused) == 7
    assert len(charged) + len(refused) == 8, "a proposer went unanswered"
    # And the tree holds exactly the one node the one charge belongs to.
    assert tree_store.rows(campaign_id) == [(f"n-{charged[0]}", SIGNAL_A)]


def test_the_probe_does_not_write_the_node_row_itself(
    tree_store: object, campaign_id: str, node_id: str
) -> None:
    # This member owns the *check*; §9.1's table and its non-metric columns
    # belong to the tree member, so the gate hands back the connection and
    # lets the caller's own writer build the row.  A body that writes
    # nothing therefore leaves nothing — the probe is not a writer.
    gate = CodeHashIndex.from_env()
    with gate.probe(SIGNAL_A):
        pass

    assert gate.holders(SIGNAL_A) == ()


def test_the_connection_is_a_usable_sqlite_connection(
    tree_store: object, campaign_id: str
) -> None:
    # The caller's writer speaks sqlite3; the probe hands it the real thing,
    # on the transaction the lock is held on — not a wrapper whose
    # transaction would be a second, unserialized one.
    gate = CodeHashIndex.from_env()
    with gate.probe(SIGNAL_A) as connection:
        assert isinstance(connection, sqlite3.Connection)
        assert connection.in_transaction


# -- The error taxonomy ------------------------------------------------------------


def test_every_refusal_is_catchable_by_the_members_base_class() -> None:
    # A caller reporting on the artifact path catches one class; the gate's
    # refusals are on that path.
    with pytest.raises(ArtifactsError):
        reject_duplicate(SIGNAL_A, [SIGNAL_A])
    with pytest.raises(ArtifactsError):
        canonical_code_hash("junk")


def test_the_duplicate_verdict_is_a_kind_of_proposal_refusal() -> None:
    # So a caller can catch both with the parent, and separate the verdict
    # from the malformed input by catching the child.
    assert issubclass(ArtifactDeduplicatedError, ArtifactProposalError)
    assert issubclass(ArtifactProposalError, ArtifactsError)
