"""Feature 203's write path: a node's authoring model, persisted.

app_spec.xml feature 203: *System persists ``agent_model_id`` per node as a
provider, model and version triple rather than a rolling alias.*  This file
holds the half of that sentence that is about the *row*: the store that writes
the triple onto a node's column, the states a node can be in when a pin asks,
and the answer each one gets.

**The guarantee is split across the schema and the store.**  Revision 0115
declares ``agent_model_id TEXT NOT NULL`` with no default, and the shipped chain
creates the ``node`` table before it adds the column, so the constraint lands on
an empty table and holds from then on: on a tree the chain built, **no node row
can exist without an authoring model**.  The database enforces *that* half, and
the first test below drives it through the DBAPI rather than taking it on faith.
What the database cannot enforce is 0115's own observation — the column is
``TEXT``, so it accepts ``'deepseek-flash'`` — and the remaining tests are the
half the store owns: refusing a value that is not a triple, refusing a triple
that disagrees with the one already recorded, answering an idempotent retry, and
writing the one state the constraint cannot cover, which is a populated tree
whose column was added without it (see the suite's conftest).

Every test runs against a database brought to its shape by the migrations that
own that shape, so nothing here pins the store against a schema this suite
invented.
"""

from __future__ import annotations

import importlib
import sqlite3
import uuid
from contextlib import closing

import pytest
from conftest import DEFAULT_AUTHOR, sqlite_path_of
from providers import (
    AGENT_MODEL_ID_COLUMN,
    MODEL_PIN_REVISION,
    AgentModelPins,
    ModelPin,
    ModelPinConflictError,
    ModelPinError,
    NodeNotRecordedError,
    RollingAliasError,
)

#: The ids these tests pin, taken from architecture §14.1's own tables so a
#: reader can hold the doc and the suite side by side.  ``ROOT`` is the
#: rotation's first member and is what ``make_pin()`` and ``DEFAULT_AUTHOR``
#: both spell, ``DEPTH`` a date-stamped depth model, ``SELF_HOSTED`` a
#: checkpoint of one — the three itches §14.1 says the pinning exists to
#: scratch.
ROOT = ("anthropic", "claude-opus-5", "20260401")
DEPTH = ("deepseek", "deepseek-v4.1-flash", "20260910")
SELF_HOSTED = ("local", "ornith-1.5-35b-a3b", "fp8-2026-05")

#: §14.1's provenance failure, in the spelling that caused it: DeepSeek retired
#: ``deepseek-v4-flash`` while continuing to accept the id, so a node authored
#: under it is recorded under a name that no longer means one model.
RETIRED_ALIAS = "deepseek-v4-flash"


def stored_value(database_url: str, node: str):
    """Read a node's ``agent_model_id`` straight from the table.

    A raw read rather than a call into the store, deliberately: several of these
    tests are about *what the store did not change*, and asking the store to
    confirm that would be asking the thing under test.  The same discipline
    ``packages/discovery/tests`` takes for its ordering-law tests.
    """
    with closing(sqlite3.connect(sqlite_path_of(database_url))) as connection:
        row = connection.execute(
            f"SELECT {AGENT_MODEL_ID_COLUMN} FROM node WHERE id = ?", (node,)
        ).fetchone()
    return None if row is None else row[0]


# ── The schema's half of the guarantee ────────────────────────────────────────


def test_the_database_refuses_a_node_with_no_authoring_model(pins, node_id, plant_node):
    # The half of feature 203 a store cannot be trusted with, driven through the
    # DBAPI so it is a fact rather than a reading of 0115's docstring: on a tree
    # the chain built, planting a node without an authoring model is refused by
    # the *database*.  0115 declared the column `NOT NULL` with no default and
    # called that refusal correct — "a node with no model string is a node the
    # stratification cannot place" — and this is that refusal, arriving before
    # any store of this member is involved.
    #
    # It is also why the tests below can assume every node they plant has an
    # author: the tree has no other kind, which is the state feature 203 wants
    # the world in.
    with pytest.raises(sqlite3.IntegrityError) as refusal:
        plant_node(pins.database_url, node_id, agent_model_id=None)
    assert AGENT_MODEL_ID_COLUMN in str(refusal.value)


def test_the_store_names_the_column_and_revision_0115_declares(pins, node_id, plant_node):
    # The store names one column and one table, and this pins both against the
    # migration rather than against a literal: the constant this member renders
    # and reads is the column 0115 actually adds.  A store that spelled it from
    # memory would be a store whose tests pass against its own typo.
    from conftest import TRIO_MIGRATION, load_migration

    plant_node(pins.database_url, node_id)
    trio = load_migration(TRIO_MIGRATION)
    assert AGENT_MODEL_ID_COLUMN in trio.COLUMNS
    assert AGENT_MODEL_ID_COLUMN in trio.NOT_NULL_COLUMNS
    assert MODEL_PIN_REVISION == trio.REVISION
    with closing(sqlite3.connect(sqlite_path_of(pins.database_url))) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(node)")}
    assert AGENT_MODEL_ID_COLUMN in columns


# ── A node already carries the model that authored it ─────────────────────────


def test_a_node_already_authored_by_this_model_is_answered_not_rewritten(
    pins, plant_node, node_id, make_pin
):
    # The shape every node has on a chain-built tree: it was planted *with* an
    # author, because the column demands one.  Pinning the same model is
    # therefore the idempotent retry §14 demands of the workers this runs on —
    # answered by the row rather than written — and `stamped=False` is what tells
    # a caller that this call changed nothing.
    plant_node(pins.database_url, node_id, agent_model_id=str(make_pin(*ROOT)))
    answer = pins.persist(node_id, make_pin(*ROOT))

    assert answer.stamped is False
    assert answer.node_id == node_id
    assert answer.pin == make_pin(*ROOT)
    assert answer.agent_model_id == "anthropic/claude-opus-5/20260401"
    assert stored_value(pins.database_url, node_id) == "anthropic/claude-opus-5/20260401"


def test_a_retry_is_answered_as_a_model_and_not_as_an_object(
    pins, plant_node, node_id, make_pin
):
    # The retry is compared as *models*: a caller that rebuilt the pin from a
    # config file holds a different object with the same three names, and that is
    # the same model.  A comparison by identity would refuse this retry as a
    # conflict with itself, which is the failure this assertion exists to catch.
    plant_node(pins.database_url, node_id, agent_model_id=str(make_pin(*ROOT)))
    rebuilt = ModelPin(provider=ROOT[0], model=ROOT[1], version=ROOT[2])
    assert rebuilt is not make_pin(*ROOT)
    assert pins.persist(node_id, rebuilt).stamped is False


def test_the_store_reads_back_the_triple_the_row_holds(pins, plant_node, node_id, make_pin):
    # Round trip through the column, which is the only place the value lives: the
    # store holds no cache, because a memo would make *"which model wrote this
    # node?"* a question about this process's history rather than about the world
    # — and the whole failure feature 203 defends against is a value that looks
    # right in one process and means something else in another.
    plant_node(pins.database_url, node_id, agent_model_id=str(make_pin(*DEPTH)))
    assert pins.load(node_id) == make_pin(*DEPTH)
    # ...and through a *second* store over the same database, which is the
    # deployment that actually reads this column: the model-stratum ablation runs
    # in another process, days later.
    assert AgentModelPins(pins.database_url).load(node_id) == make_pin(*DEPTH)


@pytest.mark.parametrize("parts", [ROOT, DEPTH, SELF_HOSTED])
def test_every_shape_of_real_deployment_id_survives_the_column(
    pins, plant_node, node_id, make_pin, parts
):
    # The three §14.1 tiers — a hosted frontier rotation, a date-stamped depth
    # model, a self-hosted checkpoint — all render to TEXT and parse back.  A
    # value type that survived only one of them would force a caller to choose
    # between the architecture's recommendation and the store's.
    plant_node(pins.database_url, node_id, agent_model_id="/".join(parts))
    assert pins.load(node_id) == make_pin(*parts)


def test_a_uuid_object_addresses_the_same_node_as_its_text(pins, plant_node, node_id):
    # The column is a UUID primary key, so a mixed-case or object spelling must
    # not make one node look like two — here, in the question of which model
    # authored it.  The normalization is the one every store joining `node.id`
    # applies.
    plant_node(pins.database_url, node_id, agent_model_id=DEFAULT_AUTHOR)
    assert pins.load(uuid.UUID(node_id)) == ModelPin(*ROOT)
    assert pins.load(uuid.UUID(node_id).urn.replace("urn:uuid:", "").upper()) == ModelPin(*ROOT)


# ── A node authored by a different model ──────────────────────────────────────


def test_a_node_already_authored_by_another_model_refuses_the_second_triple(
    pins, plant_node, node_id, make_pin
):
    # A node's author is history, not a field.  `agent_model_id` is the axis the
    # M3 paired comparison is stratified on (PRD §5a, architecture §14.1
    # mitigation 3), so re-stamping would move every score this node carries into
    # another stratum while leaving the scores themselves untouched — a silent
    # reclassification of evidence, which is the worst kind of quiet.
    plant_node(pins.database_url, node_id, agent_model_id=str(make_pin(*DEPTH)))
    with pytest.raises(ModelPinConflictError) as refusal:
        pins.persist(node_id, make_pin(*ROOT))

    # The refusal names both triples, because an operator reading it has to see
    # which two runs are claiming one node — a message naming only one would
    # leave them to go and look the other up.
    message = str(refusal.value)
    assert "deepseek/deepseek-v4.1-flash/20260910" in message
    assert "anthropic/claude-opus-5/20260401" in message
    # ...and the row is not touched by the refused call.
    assert stored_value(pins.database_url, node_id) == "deepseek/deepseek-v4.1-flash/20260910"


def test_a_partial_disagreement_is_a_full_conflict(pins, plant_node, node_id, make_pin):
    # One part different is a different model, and it is refused on exactly the
    # same grounds: the *version* is the part §14.1's DeepSeek story turns on, so
    # a rule that only refused when all three differed would let the very
    # re-routing this feature exists to catch write over itself.
    plant_node(pins.database_url, node_id, agent_model_id=str(make_pin(*DEPTH)))
    with pytest.raises(ModelPinConflictError):
        pins.persist(node_id, make_pin(*DEPTH[:2], "20260911"))


def test_a_conflict_is_raised_on_the_write_path_and_never_by_load(
    pins, plant_node, node_id, make_pin
):
    # `load` answers *what model authored this node* and has no opinion to
    # defend: a model it does not recognise is still the honest answer to that
    # question.  Refusing there would make the store unable to report the very
    # heterogeneity the stratification exists to find.  Only `persist` has an ask
    # that can disagree with the row.
    plant_node(pins.database_url, node_id, agent_model_id=str(make_pin(*DEPTH)))
    assert pins.load(node_id) == make_pin(*DEPTH)


# ── A rolling alias already in the column ─────────────────────────────────────


def test_an_alias_already_in_the_column_is_refused_rather_than_overwritten(
    pins, plant_node, node_id, make_pin
):
    # The one case where refusing costs something real — the caller has the
    # correct triple in hand and the store declines to use it — and it is still
    # the right answer.  A store that quietly replaced the alias would erase the
    # only evidence that this node was authored under a re-routed id, which is
    # the corruption §14.1's mitigation exists to make *visible*.  So the refusal
    # is raised and the alias is left where it is.
    plant_node(pins.database_url, node_id, agent_model_id=RETIRED_ALIAS)
    with pytest.raises(RollingAliasError) as refusal:
        pins.persist(node_id, make_pin(*DEPTH))
    assert RETIRED_ALIAS in str(refusal.value)
    assert stored_value(pins.database_url, node_id) == RETIRED_ALIAS


def test_an_alias_is_refused_on_the_read_path_too(pins, plant_node, node_id):
    # The read side is the other place the corruption would be laundered: a
    # stratum keyed on `'deepseek-v4-flash'` is exactly what feature 203 exists
    # to end, and a store that answered it as a model would hand the ablation a
    # group that is two models wearing one name.  §14.1's whole point is that the
    # id still *looks* fine, so no reader may be allowed to believe it.
    plant_node(pins.database_url, node_id, agent_model_id=RETIRED_ALIAS)
    with pytest.raises(RollingAliasError) as refusal:
        pins.load(node_id)
    assert RETIRED_ALIAS in str(refusal.value)
    assert AGENT_MODEL_ID_COLUMN in str(refusal.value)


def test_the_alias_refusal_names_the_node_so_it_can_be_backfilled(pins, plant_node, node_id):
    # A refusal an operator cannot act on is a refusal that gets worked around.
    # This one has to name the row, because the repair is per-node: the node was
    # authored by whichever model the alias pointed at *at the time*, and only
    # the run that recorded it knows which.
    plant_node(pins.database_url, node_id, agent_model_id=RETIRED_ALIAS)
    with pytest.raises(RollingAliasError) as refusal:
        pins.load(node_id)
    message = str(refusal.value)
    assert node_id in str(refusal.value)
    # ...and the composed report reads as one message.  It embeds the parser's
    # own refusal, which is a whole sentence ending in a full stop, so an
    # un-stripped embedding produces a doubled ".." mid-message — cosmetic, but
    # an operator reads this in a log line and a message that looks
    # mis-assembled is one they trust less.
    assert ".." not in message
    assert message.endswith("§14.1 mitigation 2).")


# ── A node whose column holds nothing (the backfill) ──────────────────────────


def test_a_node_whose_column_holds_nothing_is_backfilled(
    nullable_pins, plant_node, node_id, make_pin
):
    # The state 0115's own docstring names and cannot itself produce on the tree
    # the chain built: a populated table whose column was added without the
    # constraint, which is the additive first step of the repair 0115 calls *"a
    # backfill, not a spell"*.  A backfill is a write, so this is the write — and
    # it answers `stamped=True`, because it is the call that recorded the fact
    # rather than one that found it there.
    plant_node(nullable_pins.database_url, node_id, agent_model_id=None)
    assert stored_value(nullable_pins.database_url, node_id) is None

    answer = nullable_pins.persist(node_id, make_pin(*SELF_HOSTED))

    assert answer.stamped is True
    assert (
        stored_value(nullable_pins.database_url, node_id)
        == "local/ornith-1.5-35b-a3b/fp8-2026-05"
    )
    assert nullable_pins.load(node_id) == make_pin(*SELF_HOSTED)


def test_a_backfill_is_written_once_and_then_answered(
    nullable_pins, plant_node, node_id, make_pin
):
    # The write branch and the retry branch, in that order, on one row — so the
    # two are shown to be a *sequence* rather than two unrelated answers: the
    # first call records the author, and every call after it is answered by the
    # record.  This is the whole life of a node's pin, and the reason `stamped`
    # is a flag on the answer rather than a second method.
    plant_node(nullable_pins.database_url, node_id, agent_model_id=None)
    first = nullable_pins.persist(node_id, make_pin(*SELF_HOSTED))
    second = nullable_pins.persist(node_id, make_pin(*SELF_HOSTED))

    assert (first.stamped, second.stamped) == (True, False)
    assert first.pin == second.pin == make_pin(*SELF_HOSTED)


def test_the_backfilled_value_is_the_one_the_column_would_have_held(
    nullable_pins, plant_node, node_id, make_pin
):
    # The fixture's tree omits 0115's constraint and nothing else, so a value
    # written there is directly comparable with a value written on the
    # chain-built tree: one rendering, one spelling, whichever tree it lands on.
    # If the store rendered differently per tree this test could not be written,
    # which is the point.
    plant_node(nullable_pins.database_url, node_id, agent_model_id=None)
    nullable_pins.persist(node_id, make_pin(*DEPTH))
    assert stored_value(nullable_pins.database_url, node_id) == str(make_pin(*DEPTH))


def test_a_node_with_no_pin_reads_as_none_rather_than_as_an_error(
    nullable_pins, plant_node, node_id
):
    # `None` means *this node's row records no authoring model*.  It does not
    # mean the node is missing and it does not mean the read failed — those raise
    # — so a caller can never mistake the three for one another.  The same
    # distinction `discovery.CampaignRecords.get` draws between "never planned"
    # and "the read failed".
    plant_node(nullable_pins.database_url, node_id, agent_model_id=None)
    assert nullable_pins.load(node_id) is None


# ── The two absences: no node, no column ──────────────────────────────────────


def test_a_pin_for_a_node_the_tree_does_not_hold_is_refused(nullable_pins, make_pin):
    # A pin is a column *on a node*.  Writing one for an id the tree has never
    # heard of would mean writing a row in the `node` table, which is feature
    # 97's DDL and the discovery tree's rows — so the refusal is not
    # fastidiousness, it is this member declining to reach across a boundary.
    stranger = str(uuid.uuid4())
    with pytest.raises(NodeNotRecordedError) as refusal:
        nullable_pins.persist(stranger, make_pin(*ROOT))
    assert stranger in str(refusal.value)


def test_a_node_that_does_not_exist_is_not_a_node_with_no_pin(
    nullable_pins, plant_node, node_id
):
    # The distinction the store keeps: `load` of a node holding nothing is
    # `None`, and `load` of a node that does not exist is a refusal.  Collapsing
    # them would make *"the tree has never heard of this id"* indistinguishable
    # from *"this node's author was never recorded"* — two facts with two
    # different repairs, which is the same split `ProviderNotConfiguredError`
    # keeps from `CompletionMalformedError`.
    plant_node(nullable_pins.database_url, node_id, agent_model_id=None)
    assert nullable_pins.load(node_id) is None
    with pytest.raises(NodeNotRecordedError):
        nullable_pins.load(str(uuid.uuid4()))


def test_a_tree_store_without_the_column_is_refused_by_naming_the_revision(
    unpinned_database, plant_node, node_id, make_pin
):
    # The one failure whose repair is an operation rather than a value, and the
    # reason this store does *not* take `CampaignRecords`' let-SQLite-speak
    # stance: a database that has run 0118 and not 0115 answers SQLite's own
    # "no such column: agent_model_id" once a statement mentions it, which is a
    # message about a statement rather than about the deployment.  The real
    # report is *this tree store has not reached revision 0115*, and it names it.
    pins = AgentModelPins(unpinned_database)
    plant_node(unpinned_database, node_id, agent_model_id=None)
    with pytest.raises(ModelPinError) as refusal:
        pins.persist(node_id, make_pin(*ROOT))
    message = str(refusal.value)
    assert MODEL_PIN_REVISION in message
    assert AGENT_MODEL_ID_COLUMN in message
    # ...and the read path refuses on the same grounds, because a deployment that
    # cannot write a pin cannot honestly claim to have read one either.
    with pytest.raises(ModelPinError):
        pins.load(node_id)


def test_a_database_with_no_tree_at_all_is_the_same_refusal_seen_lower(
    database_url, make_pin
):
    # A missing `node` table and a `node` table missing the column are one fact —
    # this database has not reached the revision that adds the trio — seen at two
    # depths, and both repairs are the same chain.  So both are one error class,
    # and the message says which depth it found.
    pins = AgentModelPins(database_url)
    with pytest.raises(ModelPinError) as refusal:
        pins.persist(str(uuid.uuid4()), make_pin(*ROOT))
    assert "no node table" in str(refusal.value)


def test_the_column_probe_asks_the_table_rather_than_a_query(
    unpinned_database, plant_node, node_id, make_pin
):
    # The probe is `PRAGMA table_info` on purpose — the move
    # `nulloracle.TreeStoreGuard.audit` makes for the column it keeps absent,
    # *"it asks the table, not the queries"*.  Driven here by asserting the
    # premise the probe reads (the table exists and the column does not) and then
    # the refusal it produces: the store refuses *before* the `UPDATE` that would
    # otherwise raise SQLite's own message, which is what makes the report about
    # the deployment rather than about a statement.
    pins = AgentModelPins(unpinned_database)
    plant_node(unpinned_database, node_id, agent_model_id=None)
    with closing(sqlite3.connect(sqlite_path_of(unpinned_database))) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(node)")}
    assert columns, "the table is there — this is the column-absent depth, not the no-table one"
    assert AGENT_MODEL_ID_COLUMN not in columns
    with pytest.raises(ModelPinError):
        pins.persist(node_id, make_pin(*ROOT))


# ── The ask, refused before any database is read ──────────────────────────────


def test_a_rolling_alias_is_refused_before_the_database_is_read(nullable_pins, node_id):
    # Validation is ordered so a malformed ask costs nothing: the node id and the
    # triple are both checked before `_connect`, so a caller offering
    # `'deepseek-flash'` never opens the file — and, more to the point, never
    # reaches a store that might otherwise have written something plausible.
    # Asserted by the *refusal* that came out: the node was never planted, so a
    # check that ran after the connection would have raised NodeNotRecordedError
    # instead.
    with pytest.raises(RollingAliasError):
        nullable_pins.persist(node_id, RETIRED_ALIAS)


def test_a_node_id_that_is_not_a_uuid_is_refused(nullable_pins, make_pin):
    # The id joins `node.id`, a UUID primary key, so an id that cannot join it
    # names no node to pin.  Refused as the feature's own error rather than as
    # the standard library's, like every other refusal at this seam.
    with pytest.raises(ModelPinError) as refusal:
        nullable_pins.persist("not-a-uuid", make_pin(*ROOT))
    assert "not-a-uuid" in str(refusal.value)


def test_a_pin_from_the_scanned_copy_of_the_member_is_accepted(
    nullable_pins, plant_node, node_id
):
    # **The deployment case, and a real defect found by driving it rather than by
    # testing this module directly.**  The loader imports every member twice —
    # once as ``_nullius_scanned_providers`` by file path, once as ``providers``
    # — so ``ModelPin`` exists as two distinct class objects over one source file.
    # A `persist` that recognised a pin with ``isinstance(value, ModelPin)``
    # therefore rejected a pin built from the *other* copy, and rejected it with
    # the not-a-string message: a caller holding this feature's own value type
    # was told they "have not pinned a model at all".
    #
    # A suite that only ever builds pins from the module it imported cannot see
    # this, which is why the pin below comes from the scanned copy — the one the
    # composed application's store is an instance of.
    #
    # The scan is run here rather than relied on from another test module, so
    # this test stands alone whatever order the suite is collected in.  The
    # registry is fresh so the scan does not disturb the components the other
    # tests read.
    from app.module_loader import Registration, scan_components

    scan_components(registry=Registration())
    scanned = importlib.import_module("_nullius_scanned_providers")
    assert scanned.ModelPin is not ModelPin, (
        "the two copies are one class, so this test is no longer exercising a "
        "second class object and the loader's double import is what changed"
    )
    # The second half of the same defect, asserted directly: two copies' pins
    # are never equal, so the *stored* value this store parses back and the
    # caller's pin must be brought to one class or the idempotence check
    # answers a conflict whose two sides are the same string.
    assert scanned.ModelPin(*SELF_HOSTED) != ModelPin(*SELF_HOSTED)

    plant_node(nullable_pins.database_url, node_id, agent_model_id=None)

    # The pin is normalized on the way in, so the answer carries *this*
    # module's class and the equality the store relies on holds.
    answer = nullable_pins.persist(node_id, scanned.ModelPin(*SELF_HOSTED))
    assert answer.stamped is True
    assert type(answer.pin) is ModelPin
    assert nullable_pins.load(node_id) == ModelPin(*SELF_HOSTED)

    # ...and a retry with the same scanned pin is answered rather than refused,
    # which is the behaviour a class-blind comparison silently broke: the row
    # and the pin render identically, so a conflict here is unreadable.
    assert nullable_pins.persist(node_id, scanned.ModelPin(*SELF_HOSTED)).stamped is False


def test_a_scanned_pin_that_disagrees_is_still_a_conflict(nullable_pins, plant_node, node_id):
    # The other direction, so the fix above cannot have been "make everything
    # equal": a pin from the scanned copy naming a *different* model is still a
    # conflict, and its message still names two different triples.
    from app.module_loader import Registration, scan_components

    scan_components(registry=Registration())
    scanned = importlib.import_module("_nullius_scanned_providers")
    plant_node(nullable_pins.database_url, node_id, agent_model_id=None)
    nullable_pins.persist(node_id, ModelPin(*DEPTH))

    with pytest.raises(ModelPinConflictError) as refusal:
        nullable_pins.persist(node_id, scanned.ModelPin(*ROOT))
    message = str(refusal.value)
    assert ModelPin(*DEPTH).agent_model_id in message
    assert ModelPin(*ROOT).agent_model_id in message


def test_a_pin_is_accepted_as_either_the_value_type_or_its_render(
    nullable_pins, plant_node, node_id, make_pin
):
    # `require_agent_model_id` normalizes, so a seam handed either a `ModelPin`
    # or the string a config file carries does the same thing — which matters
    # because a campaign's configuration ships the *string* and a caller that has
    # already parsed it holds the pin.
    plant_node(nullable_pins.database_url, node_id, agent_model_id=None)
    nullable_pins.persist(node_id, DEFAULT_AUTHOR)
    assert nullable_pins.load(node_id) == make_pin(*ROOT)


# ── Construction, resolution, and the deployment that has no store ────────────


def test_building_the_store_touches_no_disk(database_url):
    # Composition-time work must not touch the disk — the contract every store in
    # this workspace states — so the path is resolved on first use and a store
    # over a database that does not exist is constructible.
    pins = AgentModelPins(database_url)
    assert not sqlite_path_of(database_url).exists()
    assert pins.database_url == database_url


def test_resolve_answers_none_when_nothing_names_a_store():
    # An absent `DATABASE_URL` is a deployment without a relational store — a
    # discoverable state, not an exception.  The `None` is deliberately not an
    # empty store: an empty store answers *"no node is pinned here"* about every
    # id, and this says there is no database to have pinned one in.
    assert AgentModelPins.resolve({}) is None
    assert AgentModelPins.resolve({"DATABASE_URL": ""}) is None
    assert AgentModelPins.resolve({"DATABASE_URL": "   "}) is None
    resolved = AgentModelPins.resolve({"DATABASE_URL": "sqlite:///tmp/x.db"})
    assert isinstance(resolved, AgentModelPins)


@pytest.mark.parametrize(
    "url",
    ["postgresql://host/db", "sqlite://", "sqlite:///:memory:", "sqlite://host/db"],
)
def test_a_store_url_this_member_cannot_speak_is_refused_by_name(url):
    # The spec's single-machine allowance is what a stdlib store can speak, and a
    # pathless URL would hold a pin in a database that dies with the connection
    # that opened it — so both are refused, by name, at the first use rather than
    # at construction: a pin must outlive the call that recorded it, because the
    # ablation reads the column from another process days later.
    pins = AgentModelPins(url)
    with pytest.raises(ModelPinError):
        _ = pins.path


def test_an_empty_database_url_is_refused_at_construction():
    # The one thing refused *at* construction rather than at first use: a store
    # with no URL at all is not a deployment with an unreachable store, it is a
    # caller that did not say where — and `resolve` already answers `None` for
    # that case, so reaching here means the URL was passed explicitly and is
    # malformed.
    with pytest.raises(ModelPinError):
        AgentModelPins("   ")


def test_the_store_is_the_only_place_that_spells_the_columns_value(
    nullable_pins, plant_node, node_id, make_pin
):
    # One rendering, one read, one write — so the write path and the read path
    # cannot disagree about the stored form.  Asserted by comparing the column
    # against the *value type's own* rendering rather than against a literal
    # spelled here, which would be a second spelling that could drift from the
    # first.
    plant_node(nullable_pins.database_url, node_id, agent_model_id=None)
    nullable_pins.persist(node_id, make_pin(*ROOT))
    assert stored_value(nullable_pins.database_url, node_id) == str(make_pin(*ROOT))
