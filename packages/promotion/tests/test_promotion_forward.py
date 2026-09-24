"""The forward window: feature 300's read, and the arithmetic it answers with.

Feature 300's sentence — *"System timestamps every promoted signal at promotion,
which creates its forward measurement window"* — and the file where *creates its
forward measurement window* is the claim under test.  The three facts the
sentence names are already on the row feature 293 closed: *which* signal is
``node_id``, *when* is ``decided_at``, and *how long* is the criteria's
``min_forward_days``.  What this feature adds is the third thing that sentence
implies and no column holds — the **interval** those two figures span, its end,
and which side of it an instant falls on.

**What this feature is not, asserted as hard as what it is.**  It writes
nothing: the ``forward_record`` table belongs to the ``forward`` plugin
(feature 332's writer), and the module that wrote it would be this member
authoring another plugin's rows.  So the first tests pin the boundary: no
``INSERT``/``UPDATE``/``CREATE TABLE`` in the code, no import of another
workspace member, no ``criteria_mismatch``, no forward-record table named.  It
also reads through feature 293's own seam rather than spelling a second
``SELECT`` — and that is asserted by pinning that this module spells **no**
``SELECT`` at all, which is only true if the read really is delegated.

**The horizon arrives from the caller, and the suite says why.**  The registry
holds the criteria *hash*, not the document, and sha256 is one-way — so the
length cannot be recovered from the row.  The tests pin the consequences: the
keyword is required (no default), zero and negative are refused with their own
message and not inherited from the criteria validator, and the record carries
the row's own ``criteria_hash`` so the length is auditable against the criteria
set it was read under.

**The open row is the load in ``depends_on="293"``, and it is the most
important test here.**  A pre-registration whose ``decided_at`` is ``NULL`` has
no promotion instant, so there is no window — and every substitute is a
fabrication: the reader's clock places the boundary wherever the reading landed,
and the pre-registration's instant starts the window *inside* the in-sample
period, which is exactly what §5's loop exists to exclude.  Both alternatives
are pinned as assertions about what the answer is **not**, so a later author who
"fixes" the refusal by defaulting cannot pass.

**The interval's edges are its own tests.**  Half-open means the closing instant
belongs to *out of sample*: ``open_at`` is ``False`` at ``closes_at`` and
``True`` an instant before, ``elapsed_by`` clamps at both ends rather than going
negative or running past the horizon, and ``elapsed_days`` truncates.  These are
the figures a report compares §5's *"after 90 days"* against, so an off-by-one
instant is not a rounding detail — it is a claim that a signal is still out of
sample one instant after it stopped being.
"""

from __future__ import annotations

import datetime as dt
import inspect
import sqlite3
from pathlib import Path

import pytest
from conftest import (
    CAMPAIGN_ID,
    DEFAULT_CRITERIA_DOCUMENT,
    EPOCH_ID,
    NODE_ID,
    code_of,
)

from promotion import (
    CLOSES_AT_COLUMN,
    DATABASE_URL_ENV,
    DECIDED_AT_COLUMN,
    EPOCH_ID_COLUMN,
    FORWARD_WINDOW_TABLE,
    NODE_ID_COLUMN,
    OPENS_AT_COLUMN,
    PROMOTED_AT_COLUMN,
    PROMOTION_REGISTRY_TABLE,
    PROMOTION_WINDOW_ERROR_CODE,
    WINDOW_DAYS_COLUMN,
    PreRegisterEndpoint,
    PreRegistrationRequest,
    PromotionCriteria,
    PromotionDecisions,
    PromotionError,
    PromotionStoreError,
    PromotionWindow,
    PromotionWindowError,
    PromotionWindows,
    criteria_hash,
    promotion_window,
    promotion_windows,
    record_decision,
    window_closes_at,
)

#: The instants the suite registers, decides and reads at, named so a window
#: assertion reads as a statement about *a stamp and an instant* rather than
#: about literals buried in a call.  ``READ_AT`` is deliberately not on a day
#: boundary relative to ``DECIDED_AT`` — 47 days in — so a truncated count and a
#: rounded one differ, which is the difference ``elapsed_days`` is pinned on.
REGISTERED_AT = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
DECIDED_AT = dt.datetime(2026, 3, 2, tzinfo=dt.UTC)
READ_AT = DECIDED_AT + dt.timedelta(days=47, hours=11)

#: The horizon the suite opens windows with — the criteria's own
#: ``min_forward_days``, spelled here as a constant so a test that reads the
#: document and a test that passes the length are visibly the same number and a
#: change to one shows up as a failure in the other.
FORWARD_DAYS = 90

#: The hash this suite's registrations record, computed from the document the
#: conftest states — the value every "the window reports the row's hash"
#: assertion compares against, so agreement is with the criteria module rather
#: than with this suite's own arithmetic.
EXPECTED_HASH = criteria_hash(PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT))

REPO_ROOT = Path(__file__).resolve().parents[3]


def _request(**overrides) -> PreRegistrationRequest:
    """A well-formed pre-registration, with the named fields overridden."""
    fields = {
        "node_id": NODE_ID,
        "epoch_id": EPOCH_ID,
        "criteria": dict(DEFAULT_CRITERIA_DOCUMENT),
    }
    fields.update(overrides)
    return PreRegistrationRequest(**fields)


@pytest.fixture
def windows(database_url: str) -> PromotionWindows:
    """The window reader, over a decision store on a fresh database.

    No migration has run: the decision store's first act brings the registry to
    the file — one owner, ``0108`` — the contract the schema adapter states, and
    this store inherits it precisely because it reads *through* that store
    rather than holding a connection of its own.  The tests that need a row ask
    for :func:`promoted` instead.
    """
    return PromotionWindows(PromotionDecisions(database_url))


@pytest.fixture
def promoted(seeded_database) -> PromotionWindows:
    """A reader over a database where the node is pre-registered **and decided**.

    The whole precondition feature 300 inherits from ``depends_on="293"``: a
    closed row is a promoted signal, and it is the only thing a window can be
    read off.  Both writes go through the sibling features' own acts rather than
    a raw ``INSERT`` — feature 291's endpoint opens the row at a clock this
    suite names, feature 293's store closes it at a second named clock — so the
    row the window is read from is the row the member's own writers produce, and
    the stamp the window opens at is provably the one 293 placed.  The tests
    that check the *open row* and *absent row* refusals deliberately do not ask
    for this fixture in the decided form; ``registered_only`` is the open case.
    """
    url = seeded_database.database_url
    PreRegisterEndpoint(seeded_database).post(
        _request(), clock=lambda: REGISTERED_AT
    )
    record_decision(NODE_ID, decided_at=DECIDED_AT, database_url=url)
    return PromotionWindows(PromotionDecisions(url))


@pytest.fixture
def registered_only(seeded_database) -> PromotionWindows:
    """A reader over a database where the node is pre-registered and **open**.

    Feature 291's row with ``decided_at`` still ``NULL``: a hypothesis whose
    deciding evaluation has not run.  A separate fixture from
    :func:`promoted` rather than a flag on it, because the two states are the
    two halves of the feature's precondition and a test should have to say which
    one it is about.
    """
    url = seeded_database.database_url
    PreRegisterEndpoint(seeded_database).post(
        _request(), clock=lambda: REGISTERED_AT
    )
    return PromotionWindows(PromotionDecisions(url))


@pytest.fixture
def raw_row(database_url: str):
    """Read the node's registry row raw, so a test sees the table it reads from.

    The point of the assertions that use it is that the window's figures are the
    *row's* — the stamp feature 293 wrote and the hash feature 291 wrote — and a
    test that asked the store under test would be asking the code to confirm
    itself.
    """

    def _row() -> sqlite3.Row | None:
        connection = sqlite3.connect(Path(database_url.removeprefix("sqlite:///")))
        try:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                f"SELECT {NODE_ID_COLUMN}, {EPOCH_ID_COLUMN}, "
                f"criteria_hash, pre_registered_at, {DECIDED_AT_COLUMN} "
                f"FROM {PROMOTION_REGISTRY_TABLE} WHERE {NODE_ID_COLUMN} = ?",
                (NODE_ID,),
            )
            try:
                return cursor.fetchone()
            finally:
                cursor.close()
        finally:
            connection.close()

    return _row


# -- The boundary: this feature reads, and writes nothing ---------------------------


def test_the_module_authors_no_writing_statement() -> None:
    # The row a window is read off is already complete: ``decided_at`` is
    # feature 293's to place and ``forward_record`` is the forward plugin's to
    # write.  Docstrings are stripped by ``code_of`` so the module may *say* it
    # writes nothing without tripping the test that pins it — and so may name
    # the tables it does not touch.
    from promotion import forward as module

    code = code_of(module)
    for verb in ("INSERT", "UPDATE", "DELETE", "CREATE TABLE", "ALTER TABLE"):
        assert verb not in code, verb


def test_the_module_spells_no_select_of_its_own() -> None:
    # The seam this feature is built on: it reads through feature 293's own
    # ``decision``/``decisions`` act rather than a second reading of one table.
    # A module that delegated the read has no ``SELECT`` in it — which is what
    # makes this a claim about the *delegation* rather than a style preference.
    from promotion import forward as module

    code = code_of(module)
    assert "SELECT" not in code
    assert "sqlite3" not in code
    assert "_connect" not in code
    # ``code_of`` strips docstrings but every *runtime* string survives, so the
    # two seams this test is really about are pinned as calls rather than as
    # words: the module delegates to the sibling's verbs and holds no cursor.
    assert ".decision(" in code
    assert ".decisions()" in code


def test_the_module_imports_no_other_workspace_member() -> None:
    # The workspace's member boundary: no member imports another, and this one
    # in particular does not reach into the ``forward`` plugin whose table its
    # subject is named after.  ``forward_record`` may be *named* in prose — the
    # module has to say what it is not — so the assertion is over the stripped
    # code and over the import nodes specifically.
    import ast

    source = (REPO_ROOT / "packages" / "promotion" / "src" / "promotion" /
              "forward.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert imported, "the module imports nothing, so this test pinned nothing"
    for name in imported:
        head = name.split(".")[0]
        assert head in {"__future__", "datetime", "os", "collections", "typing",
                        "dataclasses", "decision", "errors", "pre_register",
                        "schema"}, name


def test_the_module_never_spells_the_mismatch_verdict() -> None:
    # Feature 292's verdict is the only act in this category that compares a
    # promotion against its recorded hash.  This feature's horizon arrives from
    # the caller *because* it will not recompute the hash to check it — the
    # refusal is 292's, and a module that spelled it would be two features in
    # one file with the second half unchecked by 292's own suite.
    from promotion import forward as module

    assert "criteria_mismatch" not in code_of(module)


def test_the_module_does_not_name_the_forward_record_table() -> None:
    # ``forward_record`` is feature 332's table, in another plugin.  The window
    # this feature answers is what that record is *opened against*, and a module
    # that named the table would be a promotion-side reader of another plugin's
    # rows — the boundary the module docstring draws at length.  Asserted over
    # the stripped code, not the file: the prose has to name it to disclaim it.
    from promotion import forward as module

    assert "forward_record" not in code_of(module)


def test_the_module_registers_nothing_and_adds_no_builder() -> None:
    # The member's registered surface stays feature 291's one store.  A
    # ``@register`` here would fire at import time and compose a component the
    # factory cannot supply — the act is a function of a decided promotion and a
    # caller's horizon — and a second ``build_*`` name would break the
    # member-wide assertion the sibling suites already make.
    from promotion import forward as module

    code = code_of(module)
    assert "@register" not in code
    assert "register(" not in code
    assert [name for name in dir(module) if name.startswith("build_")] == []


def test_the_seat_is_untouched_and_still_answers_one_question() -> None:
    # Feature 300 adds a module, not a component: there is no
    # ``src/app/modules/promotion/forward.py`` seat, because a seat answers *what
    # is the composed registry?* and this feature composes nothing.  Pinned by
    # the absence of the file rather than by reading the seat's contents, so the
    # claim is about this feature's footprint.
    seat = REPO_ROOT / "src" / "app" / "modules" / "promotion"
    assert not (seat / "forward.py").exists()
    assert not (seat / "forward_windows.py").exists()


# -- The witness: the stamp is the row's, and the window reports that row -----------


def test_the_window_opens_at_the_instant_feature_293_stamped(
    promoted: PromotionWindows, raw_row
) -> None:
    # The feature's sentence in one assertion: *timestamps every promoted signal
    # at promotion, which creates its forward measurement window*.  The opening
    # instant is compared against the **table's** copy of ``decided_at``, read
    # raw, so a store that echoed the argument it was handed or reconstructed
    # the stamp from a clock could not pass.  That the two agree is the whole
    # content of ``depends_on="293"``.
    row = raw_row()
    assert row[DECIDED_AT_COLUMN] is not None

    window = promoted.window(NODE_ID, forward_days=FORWARD_DAYS)

    assert window.opened_at == DECIDED_AT
    assert window.opened_at.isoformat() == row[DECIDED_AT_COLUMN]
    assert window.opened_at == window.opened_at.astimezone(dt.UTC)


def row_hash(windows: PromotionWindows) -> str:
    """The hash on the row the window was read from, via the decision store.

    Used by the test below for its second comparison — the store's read rather
    than the table's, so the assertion says the window agrees with *both* the
    arithmetic (``EXPECTED_HASH``) and the persisted row.
    """
    record = windows.decisions.decision(NODE_ID)
    assert record is not None
    return record.criteria_hash


def test_the_window_carries_the_rows_own_criteria_hash_and_epoch(
    promoted: PromotionWindows,
) -> None:
    # The horizon cannot be checked against the row, because the row holds a
    # one-way digest — so the digest is carried *on the window* beside the
    # length, which is what makes the caller's figure auditable rather than
    # merely asserted.  Both are the row's values, compared against the hash the
    # criteria module computes from the document the registration was made with.
    window = promoted.window(NODE_ID, forward_days=FORWARD_DAYS)

    assert window.criteria_hash == EXPECTED_HASH
    assert window.criteria_hash == row_hash(promoted)
    assert window.epoch_id == EPOCH_ID
    assert window.node_id == NODE_ID


def test_the_window_is_the_row_and_not_the_arguments(
    promoted: PromotionWindows,
) -> None:
    # The caller supplies exactly one figure — the horizon — and this pins that
    # it supplies only that: every other field of the window is the row's.  A
    # store that accepted a node id, a hash or an epoch from its caller would
    # let a caller describe a promotion that was never registered, which is the
    # fabrication §13 item 7 exists to prevent.
    parameters = set(
        inspect.signature(PromotionWindows.window).parameters
    )
    assert parameters == {"self", "node_id", "forward_days"}

    parameters = set(inspect.signature(promotion_window).parameters)
    assert parameters == {"node_id", "forward_days", "database_url", "env"}


def test_the_listing_answers_one_window_per_promoted_signal(
    promoted: PromotionWindows,
) -> None:
    # The *every* of the feature's sentence made enumerable — and the listing is
    # compared against the decision store's own listing, so the two readers of
    # the same rows cannot disagree about how many promotions there are.
    closed = promoted.decisions.decisions()

    windows = promoted.windows(forward_days=FORWARD_DAYS)

    assert len(windows) == len(closed) == 1
    assert [window.node_id for window in windows] == [
        record.node_id for record in closed
    ]
    assert windows[0].opened_at == DECIDED_AT


#: The extra hypotheses the multiplicity tests register, and which of them get
#: decided.  Deliberately *not* the suite's ``NODE_ID``: the point of these tests
#: is that the listing is a function of the whole table, so the fixtures below
#: build a table with more than one row in it — the single-row fixtures above
#: cannot tell *one per promoted signal* from *at most one*.
OTHER_NODES = (
    "44444444-4444-4444-8444-444444444444",
    "55555555-5555-4555-8555-555555555555",
    "66666666-6666-4666-8666-666666666666",
)

#: The nodes of :data:`OTHER_NODES` that are decided, by index: the first and
#: the third.  The middle one stays **open**, so the multiplicity test is also a
#: mixed-table test — a listing that filtered by *row exists* rather than by
#: *row is closed* is caught by the same fixture.
DECIDED_OTHERS = (0, 2)


@pytest.fixture
def several_promoted(seeded_database) -> PromotionWindows:
    """A reader over a registry holding **four** rows, two of them open.

    The table the *every* of the feature's sentence is about, rather than a
    single-row stand-in for it: the node ``seeded_database`` supplies and three
    more, each pre-registered through feature 291's own endpoint at its own
    clock, with two of them closed through feature 293's own store.  The two that
    stay open are what makes this fixture prove two things at once — that the
    listing is one window *per promoted signal* (so it must scale past one), and
    that it is a filter on *closed* rather than on *present*.

    The parent rows are written the way the conftest writes them — in the columns
    the migrations declare, through the store's own connection — because a node's
    row is the discovery loop's write and is not this member's to invent.  All
    four registrations share ``EPOCH_ID``: an epoch is a depleting resource
    charged by feature 294, not a per-promotion key, and the registry's foreign
    key is satisfied by the one row the conftest already wrote.
    """
    connection = seeded_database._connect()
    try:
        with connection:
            for node in OTHER_NODES:
                connection.execute(
                    "INSERT INTO node (id, campaign_id, theme_root, depth) "
                    "VALUES (?, ?, ?, ?)",
                    (node, CAMPAIGN_ID, "macro", 1),
                )
    finally:
        connection.close()

    url = seeded_database.database_url
    endpoint = PreRegisterEndpoint(seeded_database)
    for offset, node in enumerate(OTHER_NODES, start=1):
        endpoint.post(
            _request(node_id=node),
            clock=lambda offset=offset: REGISTERED_AT + dt.timedelta(days=offset),
        )
        if offset - 1 in DECIDED_OTHERS:
            record_decision(
                node,
                decided_at=DECIDED_AT + dt.timedelta(days=offset),
                database_url=url,
            )
    return PromotionWindows(PromotionDecisions(url))


def test_the_listing_answers_every_promoted_signal_not_just_one(
    several_promoted: PromotionWindows,
) -> None:
    # The multiplicity the single-row fixtures cannot reach.  With four rows in
    # the table — two closed, two open — the answer must be exactly the two
    # closed ones, each carrying *its own* stamp.  A listing that returned the
    # first match, deduplicated by anything, or filtered on the wrong predicate
    # fails here and passes every single-row test above, which is why this test
    # exists.
    windows = several_promoted.windows(forward_days=FORWARD_DAYS)

    expected_nodes = [OTHER_NODES[i] for i in DECIDED_OTHERS]
    assert sorted(w.node_id for w in windows) == sorted(expected_nodes)
    assert len(windows) == 2
    # Each window's instant is its own row's, not the first row's — the failure a
    # loop that read one row and stamped many would produce.
    by_node = {w.node_id: w for w in windows}
    for index in DECIDED_OTHERS:
        node = OTHER_NODES[index]
        expected = DECIDED_AT + dt.timedelta(days=index + 1)
        assert by_node[node].opened_at == expected, node
    assert len({w.opened_at for w in windows}) == 2


def test_the_listing_omits_every_open_row_in_a_mixed_table(
    several_promoted: PromotionWindows,
) -> None:
    # The omission, now that there is something to omit *beside* something that
    # is listed: the open node is absent while its decided siblings are present,
    # so the listing cannot be passing by returning nothing, and cannot be
    # passing by returning everything.  Compared against feature 293's own
    # listing, so the two readers of one table agree by construction.
    listed = {w.node_id for w in several_promoted.windows(forward_days=FORWARD_DAYS)}
    closed = {r.node_id for r in several_promoted.decisions.decisions()}

    assert listed == closed
    open_nodes = {n for i, n in enumerate(OTHER_NODES) if i not in DECIDED_OTHERS}
    assert open_nodes, "the fixture must leave at least one row open"
    assert not (listed & open_nodes)
    # And the open rows really are in the table — so their absence above is the
    # listing's judgement rather than an absence of rows.
    for node in open_nodes:
        record = several_promoted.decisions.decision(node)
        assert record is not None and record.open is True


def test_the_listing_refuses_an_open_row_by_name_and_lists_around_it(
    several_promoted: PromotionWindows,
) -> None:
    # The two acts side by side over one mixed table: ``window`` refuses an open
    # node by name (there is a single node to name a repair to), while ``windows``
    # omits it (a listing has none).  Pinned together because the difference is
    # the *act* and not the row — the same open row produces both answers, and a
    # later author who "made them consistent" would break one of the two.
    open_node = next(
        n for i, n in enumerate(OTHER_NODES) if i not in DECIDED_OTHERS
    )

    with pytest.raises(PromotionWindowError) as caught:
        several_promoted.window(open_node, forward_days=FORWARD_DAYS)
    assert open_node in str(caught.value)

    assert open_node not in {
        w.node_id for w in several_promoted.windows(forward_days=FORWARD_DAYS)
    }


def test_the_listing_omits_a_row_that_is_still_open(
    registered_only: PromotionWindows,
) -> None:
    # The degenerate case of the mixed table: *every* row open, so the answer is
    # the empty tuple rather than a failure.  A caller enumerating before any
    # decision has run must get nothing to iterate, not an exception — the
    # listing is not the refusal.
    assert registered_only.decisions.decisions() == ()
    assert registered_only.windows(forward_days=FORWARD_DAYS) == ()


# -- The absence: no pre-registration is no promotion is no window ------------------


def test_an_unregistered_node_is_refused_by_name(
    windows: PromotionWindows, database_url: str
) -> None:
    # ``depends_on="291"`` made load bearing: §13 item 7 fixes the criteria
    # before the evaluation, so the row has to exist before there is a window,
    # and a node nobody pre-registered has no promotion to have opened one.  The
    # repair is named in order — pre-register, then decide — because a window
    # opens at the decision's stamp and not at the registration's.
    unregistered = "33333333-3333-4333-8333-333333333333"

    with pytest.raises(PromotionWindowError) as caught:
        windows.window(unregistered, forward_days=FORWARD_DAYS)

    message = str(caught.value)
    assert message.startswith(PROMOTION_WINDOW_ERROR_CODE)
    assert unregistered in message
    assert "feature 291" in message and "feature 293" in message
    assert "never promoted" in message


def test_the_absence_lookup_does_not_create_the_database(
    tmp_path: Path, database_url: str
) -> None:
    # A refused ask must not be a *creator*.  The read goes through the decision
    # store, whose first act is what brings the registry to a fresh file — so a
    # window read on a database nothing has touched would create the tables as a
    # side effect of being refused.  Pinned on the file, because that is the
    # observable: the store's own suite states the contract for the write path,
    # and this asserts the read path does not acquire it.
    reader = PromotionWindows(PromotionDecisions(database_url))

    with pytest.raises(PromotionWindowError):
        reader.window(NODE_ID, forward_days=FORWARD_DAYS)

    # The decision store's read *does* bring the registry up — that is its stated
    # contract, unchanged here, one owner and ``0108`` — and what this feature
    # adds is that it adds no *second* owner: the table that arrives is the one
    # 293's read needs, and no table of another plugin's comes with it.  The
    # check is that the schema this read produced is exactly the schema feature
    # 293's own bootstrap produces — compared against a second database brought
    # up by that bootstrap alone, so the claim is *no drift* rather than a
    # literal list this suite would have to maintain.
    def _tables(url: str) -> set[str]:
        connection = sqlite3.connect(Path(url.removeprefix("sqlite:///")))
        try:
            return {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()

    alone = PromotionWindows(
        PromotionDecisions(f"sqlite:///{tmp_path / 'bootstrap-alone.db'}")
    )
    with pytest.raises(PromotionWindowError):
        alone.window(NODE_ID, forward_days=FORWARD_DAYS)

    assert PROMOTION_REGISTRY_TABLE in _tables(database_url)
    assert _tables(database_url) == _tables(alone.decisions.database_url)


# -- The open row: the load in depends_on="293" -------------------------------------


def test_an_open_row_is_refused_by_name(registered_only: PromotionWindows) -> None:
    # The most important refusal in this file.  A pre-registered row whose
    # ``decided_at`` is still NULL has no promotion instant, so there is no
    # instant for a window to open at — and *now* and *the registration's
    # instant* are both fabrications.  The message names the node, the instant
    # the row *was* opened at and the criteria it was registered under, so an
    # operator can see the row is real and merely unfinished.
    with pytest.raises(PromotionWindowError) as caught:
        registered_only.window(NODE_ID, forward_days=FORWARD_DAYS)

    message = str(caught.value)
    assert message.startswith(PROMOTION_WINDOW_ERROR_CODE)
    assert NODE_ID in message
    assert "open" in message
    assert REGISTERED_AT.isoformat() in message
    assert EXPECTED_HASH in message
    assert "feature 293" in message


def test_the_open_refusal_does_not_default_to_a_start_instant(
    registered_only: PromotionWindows,
) -> None:
    # The two substitutes a later author would reach for, refused as behaviour
    # and not merely as prose.  *Now* would place the boundary wherever the
    # reading happened to land; the *pre-registration's* instant would open the
    # window before the evaluation ran, so it would begin measuring on data that
    # existed when the hypothesis was formed — precisely the contamination §5's
    # loop and ``0108``'s forward record exist to exclude.  A store that
    # defaulted to either would answer here; this one must raise.
    with pytest.raises(PromotionWindowError):
        registered_only.window(NODE_ID, forward_days=FORWARD_DAYS)

    # And the raw row proves which state produced it: an open row, decided_at
    # NULL, is the only thing that can have raised.
    assert registered_only.decisions.decision(NODE_ID).open is True


def test_the_raw_row_is_still_open_after_the_refusal(
    registered_only: PromotionWindows, raw_row
) -> None:
    # The refusal writes nothing — no stamp, no placeholder, no "we looked"
    # marker.  Asserted on the table rather than on the store, so a writer that
    # helpfully closed the row to make the answer possible could not pass.
    before = raw_row()
    assert before[DECIDED_AT_COLUMN] is None

    with pytest.raises(PromotionWindowError):
        registered_only.window(NODE_ID, forward_days=FORWARD_DAYS)

    after = raw_row()
    assert after[DECIDED_AT_COLUMN] is None
    assert dict(after) == dict(before)


# -- The horizon is the caller's, and the suite says why ----------------------------


def test_the_horizon_keyword_is_required_with_no_default() -> None:
    # No default, and that is the design rather than an omission.  The registry
    # holds the criteria *hash* — one-way — so the length cannot be recovered
    # from the row; a default would be this module inventing a horizon nobody
    # registered, which is exactly the fitted-after-the-fact figure §13 item 7
    # exists to prevent.  Pinned as a signature, because that is what a later
    # author would edit.
    for surface in (PromotionWindows.window, promotion_window):
        parameter = inspect.signature(surface).parameters["forward_days"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


def test_a_zero_day_window_is_refused_though_the_criteria_admit_zero() -> None:
    # The boundary is deliberately **not** the criteria validator's.  Feature
    # 291's ``_validated_count`` admits zero — a criterion of zero worlds is a
    # bad pre-registration but a registerable one, and refusing it there would
    # be the pre-registration judging a decision that belongs to the evaluation.
    # Here zero is not a bad window, it is *not a window*: ``closes_at`` would
    # equal ``opened_at``, the half-open interval would be empty, and a forward
    # record opened against it could never hold an observation.  Both halves are
    # asserted, so a later author who "unifies" the two validators fails here.
    assert PromotionCriteria(
        **{**DEFAULT_CRITERIA_DOCUMENT, "min_forward_days": 0}
    ).min_forward_days == 0

    with pytest.raises(PromotionWindowError) as caught:
        PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 0)

    assert str(caught.value).startswith(PROMOTION_WINDOW_ERROR_CODE)
    assert "zero days" in str(caught.value)


@pytest.mark.parametrize(
    "value",
    [-1, True, False, 1.5, "90", None, dt.timedelta(days=90)],
)
def test_a_horizon_that_is_not_a_positive_count_is_refused(value) -> None:
    # ``bool`` first and explicitly, for the reason every count validator in
    # this workspace refuses it: ``True`` is ``1`` in Python, so a flag where a
    # horizon belongs would silently open a one-day window — the shortest a
    # window can be, and a length nobody stated.  A fraction and a
    # ``timedelta`` are refused for the same class of reason: neither names a
    # *whole number of days*, which is the unit the horizon is stated in.
    with pytest.raises(PromotionWindowError) as caught:
        PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, value)

    message = str(caught.value)
    assert message.startswith(PROMOTION_WINDOW_ERROR_CODE)
    # The offending value is named, so an operator sees what they passed.
    assert repr(value) in message


def test_the_horizon_is_validated_before_the_row_is_read(
    windows: PromotionWindows, database_url: str
) -> None:
    # Order matters for a caller's repair: a malformed *ask* is refused without
    # touching a database, so a caller with a bad horizon is told about the
    # horizon rather than about a missing registration it would have had to fix
    # first and would then hit the real refusal on the second attempt.
    with pytest.raises(PromotionWindowError) as caught:
        windows.window(NODE_ID, forward_days=0)

    assert WINDOW_DAYS_COLUMN in str(caught.value)
    assert not Path(database_url.removeprefix("sqlite:///")).exists()


def test_the_horizon_is_validated_before_the_listing_reads(
    windows: PromotionWindows, database_url: str
) -> None:
    # The same ordering on the listing, where it also guarantees something
    # stronger: every window in the returned tuple carries *the same* length, so
    # a caller cannot get a listing whose horizons disagree because the
    # validation happened per row.
    with pytest.raises(PromotionWindowError):
        windows.windows(forward_days=-5)

    assert not Path(database_url.removeprefix("sqlite:///")).exists()


def test_a_horizon_whose_sum_leaves_the_calendar_is_refused_as_a_window_refusal() -> None:
    # There is deliberately **no upper bound on the count itself**, and this test
    # is why.  ``999_999_999`` is the largest horizon ``timedelta`` will accept,
    # so it reads like a natural static bound — but it is accepted here and the
    # *sum* with a real stamp is what leaves the calendar, and ``10**10`` is not
    # even a legal ``timedelta`` argument.  A ceiling checked against the count
    # would therefore be simultaneously too loose (999_999_999 passes and then
    # explodes) and too tight (it would have to refuse figures the calendar can
    # hold for a young enough stamp).  So the check lives where the sum is
    # actually taken, and the reachable limit is a function of ``opened_at``.
    for horizon in (999_999_999, 1_000_000_000, 10**10, 2**63):
        with pytest.raises(PromotionWindowError) as caught:
            window_closes_at(DECIDED_AT, horizon)

        message = str(caught.value)
        assert message.startswith(PROMOTION_WINDOW_ERROR_CODE), horizon
        # Both figures are named: an operator has to know which of the two to
        # change, and the message is the only place they are told.
        assert DECIDED_AT.isoformat() in message, horizon
        assert repr(horizon) in message, horizon


def test_a_record_whose_end_is_uncomputable_is_refused_at_construction() -> None:
    # The worst possible shape for this defect would be a constructor that
    # *accepts* the record and defers the explosion to the first ``closes_at``
    # read — because ``closes_at`` is a property, so a caller's ``try`` around
    # construction would not guard it, and the failure would surface wherever the
    # window was first used rather than where it was built.  Asserted as
    # construction-time so a later author who "simplifies" the eager sum out of
    # ``__post_init__`` fails here rather than in production.
    with pytest.raises(PromotionWindowError):
        PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 10**10)

    # And the corollary: a window that *was* constructed can be read freely.
    window = PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, FORWARD_DAYS)
    assert window.closes_at == window_closes_at(DECIDED_AT, FORWARD_DAYS)


def test_a_large_but_computable_horizon_is_still_accepted() -> None:
    # The refusal above must not be so eager that it starts rejecting windows
    # that have a perfectly good end.  A century is far past any registered
    # ``min_forward_days`` and still nowhere near the calendar's edge, so it
    # pins the refusal as a genuine overflow catch rather than a length cap.
    closes = window_closes_at(DECIDED_AT, 36_500)

    assert closes.date() == dt.date(2126, 2, 6)
    assert PromotionWindow(
        NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 36_500
    ).closes_at == closes


def test_a_malformed_node_is_refused_as_a_window_refusal() -> None:
    # The seam translations, asserted on the *class* rather than the message:
    # a caller whose single ``except PromotionWindowError`` guards the window it
    # is about to open must not be defeated by a refusal phrased for feature
    # 291's ask or 293's decision.  Both wrappers are exercised, so neither can
    # silently start leaking the inner class.
    with pytest.raises(PromotionWindowError) as caught:
        PromotionWindows(_StubDecisions()).window("not-a-uuid", forward_days=1)

    assert str(caught.value).startswith(PROMOTION_WINDOW_ERROR_CODE)
    assert "node identity" in str(caught.value)


def test_a_refusal_from_the_decision_read_arrives_as_a_window_refusal(
    windows: PromotionWindows,
) -> None:
    # The read's own refusals — a node holding two rows, a corrupt row — belong
    # to feature 293's vocabulary, and they are re-framed here so the caller
    # sees which act failed.  The stub raises the decision store's own class and
    # the assertion is that the caller catches a *window* error, with the inner
    # message carried through so nothing an operator needs is lost.
    stub = _StubDecisions(
        refusal=PromotionStoreError("promotion_registry_unwritable: boom")
    )

    with pytest.raises(PromotionWindowError) as caught:
        PromotionWindows(stub).window(
            "11111111-1111-4111-8111-111111111111", forward_days=FORWARD_DAYS
        )

    message = str(caught.value)
    assert message.startswith(PROMOTION_WINDOW_ERROR_CODE)
    assert "registry row" in message
    assert "boom" in message


class _StubDecisions:
    """A decision store's ``decision`` seam, standing in for the real read.

    Feature 300 duck-checks that seam rather than class-checking it — the
    factory's scan imports the member under a synthetic module name, so the
    composed store is never the same class object a direct import yields — and
    this stub is that seam with nothing behind it: it lets the *translation*
    tests drive the refusal path without manufacturing a corrupt row in SQLite,
    which would be testing SQLite's dynamic typing rather than this module's
    wrappers.  ``refusal`` is what the read raises, or ``None`` for no row.
    """

    def __init__(self, refusal: PromotionError | None = None) -> None:
        self._refusal = refusal

    def decision(self, node_id):
        if self._refusal is not None:
            raise self._refusal

    def decisions(self):
        return ()


def test_a_reader_over_something_that_is_not_a_decision_store_is_refused() -> None:
    # The seam is checked at construction, before any call, because it is a fact
    # about the *store* rather than about any one window: a reader with nothing
    # to read through names no registry, and one that accepted it would fail
    # identically — or on only half its questions — which is the wrong place and
    # the wrong shape for discovering a wiring fault.  A ``TypeError`` rather
    # than a window refusal, because no operator can fix it by pre-registering or
    # deciding anything.  ``PromotionDecisions`` *the class* is in the list
    # because a class object exposes no instance methods: the seam is on the
    # *composed store*, and a caller that passed the type instead of an instance
    # has the same fault as one that passed a string.
    for wrong in (None, "sqlite:///x.db", PromotionDecisions, object()):
        with pytest.raises(TypeError) as caught:
            PromotionWindows(wrong)
        assert "decision" in str(caught.value)


# -- The arithmetic: the interval's edges are its own tests --------------------------


def test_the_window_closes_one_horizon_after_it_opens() -> None:
    # ``closes_at`` is derived, and this is the derivation: the stamp plus the
    # horizon.  A stored end date would be free to disagree with the two figures
    # it is computed from, which is the argument the module docstring makes for
    # leaving it out of the table.
    window = PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 90)

    assert window.closes_at == DECIDED_AT + dt.timedelta(days=90)
    assert window.horizon == dt.timedelta(days=90)
    assert window.closes_at == window_closes_at(DECIDED_AT, 90)


def test_the_standalone_arithmetic_validates_the_horizon_first() -> None:
    # The order is load bearing rather than incidental: a malformed horizon is
    # refused *as a horizon* rather than surfacing as a ``TypeError`` from
    # inside ``timedelta``, which is a shape a caller would have to catch code
    # words out of.  A naive stamp is refused too, and by the same rule the
    # record applies, so the standalone answer and the record's cannot disagree.
    with pytest.raises(PromotionWindowError):
        window_closes_at(DECIDED_AT, 0)

    with pytest.raises(PromotionWindowError) as caught:
        window_closes_at(dt.datetime(2026, 3, 2), 90)  # noqa: DTZ001 - the refusal's subject

    assert "aware" in str(caught.value) or "offset" in str(caught.value)


def test_the_interval_is_half_open_at_the_closing_instant() -> None:
    # The single boundary the whole forward loop is built around.  At
    # ``closes_at`` the signal **has** the track record — the window is what
    # produced it — so an instant there is out of sample and must not be counted
    # as inside.  One microsecond earlier is inside.  A window that included its
    # closing instant would let a forward observation land at the moment the
    # signal stopped being out of sample.
    window = PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 90)
    epsilon = dt.timedelta(microseconds=1)

    assert window.open_at(DECIDED_AT) is True
    assert window.open_at(window.closes_at - epsilon) is True
    assert window.open_at(window.closes_at) is False
    assert window.open_at(window.closes_at + epsilon) is False


def test_an_instant_before_the_window_opens_is_not_open() -> None:
    # The other end: half-open means ``opened_at`` itself **is** inside, and an
    # instant before it is not.  Asserted together with the equality case,
    # because the pair is what a reader is most likely to get wrong in either
    # direction — the same reason feature 293's suite pins its ordering boundary
    # as its own test.
    window = PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 90)

    assert window.open_at(DECIDED_AT) is True
    assert window.open_at(DECIDED_AT - dt.timedelta(microseconds=1)) is False


def test_elapsed_clamps_at_both_ends_and_never_runs_past_the_horizon() -> None:
    # Zero before the window opens rather than negative — the question is *how
    # much of the window has elapsed* and a window that has not begun has had
    # none of it elapse — and the full horizon at and after ``closes_at`` rather
    # than a figure that keeps growing, which would be *how long ago the
    # promotion was*, a different question.  Both clamps are asserted at the
    # boundary and one step beyond it, so an ``abs``-style "fix" fails.
    window = PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 90)
    horizon = dt.timedelta(days=90)

    assert window.elapsed_by(DECIDED_AT - dt.timedelta(days=5)) == dt.timedelta(0)
    assert window.elapsed_by(DECIDED_AT) == dt.timedelta(0)
    assert window.elapsed_by(READ_AT) == READ_AT - DECIDED_AT
    assert window.elapsed_by(window.closes_at) == horizon
    assert window.elapsed_by(window.closes_at + dt.timedelta(days=400)) == horizon


def test_remaining_is_the_complement_and_never_negative() -> None:
    # The complement over the horizon, with the same two clamps: the whole
    # horizon before the window opens — a window that has not begun has all of
    # itself remaining — and zero from ``closes_at`` onward.  A signed remainder
    # would make *how long is left* an answer meaning *how long ago it ran out*,
    # and the two must not collapse into one figure.
    window = PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 90)
    horizon = dt.timedelta(days=90)

    assert window.remaining_at(DECIDED_AT - dt.timedelta(days=5)) == horizon
    assert window.remaining_at(DECIDED_AT) == horizon
    assert window.remaining_at(READ_AT) == horizon - (READ_AT - DECIDED_AT)
    assert window.remaining_at(window.closes_at) == dt.timedelta(0)
    assert window.remaining_at(window.closes_at + dt.timedelta(days=400)) == (
        dt.timedelta(0)
    )
    # And the two are exact complements wherever the window is open — the
    # relation a report relies on when it prints both.
    assert window.elapsed_by(READ_AT) + window.remaining_at(READ_AT) == horizon


def test_elapsed_days_truncates_rather_than_rounding() -> None:
    # The whole days of the window elapsed — the figure §5's *"after 90 days"*
    # is compared against.  Truncated, so the count never runs ahead of the
    # instant it is asked about: 47 days and 11 hours is 47 days elapsed, not 48.
    # A rounding implementation would answer 48 and would report a signal as
    # having completed a day it has not.
    window = PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 90)

    assert window.elapsed_days(READ_AT) == 47
    assert window.elapsed_days(DECIDED_AT + dt.timedelta(hours=23, minutes=59)) == 0
    assert window.elapsed_days(window.closes_at) == 90
    assert window.elapsed_days(DECIDED_AT - dt.timedelta(days=5)) == 0


def test_a_reference_instant_is_held_to_the_same_calendar_as_the_stamp() -> None:
    # A reference instant that is naive, or that is not an instant at all, is
    # refused rather than compared — the same rule the row's own stamp is held
    # to, *used* rather than restated, which is what makes this a claim about the
    # rule and not about a subset of it.  A naive reference is the dangerous case:
    # every comparison below would raise ``TypeError`` from inside the arithmetic
    # rather than a refusal naming the field, and ``open_at`` would report a
    # window as shut for a caller who merely forgot the offset.  A string
    # *is* admitted, because the member's one instant rule admits ISO-8601 text —
    # that is what lets a row read back revalidate — and the assertion says so,
    # so a later author who narrowed the rule here would fail on both halves.
    window = PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 90)
    questions = (window.elapsed_by, window.remaining_at, window.open_at)

    for bad in (
        dt.datetime(2026, 4, 18),  # noqa: DTZ001 - the refusal's subject
        None,
        47,
        dt.date(2026, 4, 18),
    ):
        for question in questions:
            with pytest.raises(PromotionWindowError) as caught:
                question(bad)
            assert str(caught.value).startswith(PROMOTION_WINDOW_ERROR_CODE)
            assert "reference instant" in str(caught.value)

    # The admitted forms, so the refusal above is pinned as *the rule* rather
    # than as "any value at all is refused": an aware instant and its own
    # ISO-8601 text name the same moment and must answer identically.
    aware = DECIDED_AT + dt.timedelta(days=10)
    assert window.elapsed_by(aware) == window.elapsed_by(aware.isoformat())
    assert window.open_at(aware) is True
    # And the naive refusal is specifically about the offset, not about the date:
    # the same wall-clock value *with* an offset is accepted.
    assert window.open_at(dt.datetime(2026, 3, 12, tzinfo=dt.UTC)) is True


def test_the_record_is_frozen_and_revalidates_every_field() -> None:
    # Frozen, because this value is a statement about when a signal stopped
    # being measured on in-sample data: a caller who could edit ``opened_at`` in
    # memory would move the boundary between backtest and out-of-sample that
    # ``0108``'s own docstring calls the point of the forward record.  And
    # revalidated at construction, because SQLite's columns are dynamically
    # typed — a hand-edited row is reachable, and a window rebuilt from one
    # without checks would report a horizon nobody registered.
    window = PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 90)

    with pytest.raises(AttributeError):
        window.opened_at = DECIDED_AT + dt.timedelta(days=1)
    with pytest.raises(AttributeError):
        window.window_days = 1

    for corrupt in (
        ("not-a-uuid", EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 90),
        (NODE_ID, "short", EPOCH_ID, DECIDED_AT, 90),
        (NODE_ID, EXPECTED_HASH, "   ", DECIDED_AT, 90),
        (NODE_ID, EXPECTED_HASH, EPOCH_ID, "not-an-instant", 90),
        (NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 0),
    ):
        with pytest.raises(PromotionWindowError):
            PromotionWindow(*corrupt)


def test_the_row_rendering_names_the_tables_columns_and_its_own() -> None:
    # Three of the six keys are the table's own column names; three are this
    # feature's (`opens_at` is the table's ``decided_at`` under the name this
    # feature asks about, and ``window_days``/``closes_at`` are the two the
    # table deliberately does not hold).  A rendered mapping names the same
    # things the same way the row does, and a fresh dict per call so a caller
    # cannot hand a mutation back into the record.
    window = PromotionWindow(NODE_ID, EXPECTED_HASH, EPOCH_ID, DECIDED_AT, 90)

    row = window.row()
    assert row[NODE_ID_COLUMN] == NODE_ID
    assert row[EPOCH_ID_COLUMN] == EPOCH_ID
    assert set(row) == {
        NODE_ID_COLUMN,
        EPOCH_ID_COLUMN,
        "criteria_hash",
        OPENS_AT_COLUMN,
        WINDOW_DAYS_COLUMN,
        CLOSES_AT_COLUMN,
    }
    assert row[OPENS_AT_COLUMN] == DECIDED_AT == window.opened_at
    assert row[CLOSES_AT_COLUMN] == window.closes_at
    assert row is not window.row()


def test_the_feature_reads_the_decided_at_column_rather_than_respelling_it() -> None:
    # One column, two readers' words for it: feature 293 writes *the instant the
    # decision was recorded* and this feature reads the same value as *the
    # instant the window opens*.  The alias is pinned against the sibling's
    # constant rather than against the literal, so a rename in either module
    # shows up here instead of in a silent drift between two spellings.
    assert PROMOTED_AT_COLUMN is DECIDED_AT_COLUMN
    assert FORWARD_WINDOW_TABLE == PROMOTION_REGISTRY_TABLE


# -- Resolution: the module-level spellings -----------------------------------------


def test_the_module_level_reads_the_database_the_environment_names(
    promoted: PromotionWindows, database_url: str
) -> None:
    # The two spellings resolve their store the same way the sibling features'
    # acts do, so a caller that records through one and reads through the other
    # is reading the row it closed.  Asserted against the store's own answer, so
    # agreement is by comparison rather than by this suite's arithmetic.
    window = promotion_window(NODE_ID, forward_days=FORWARD_DAYS, env={
        DATABASE_URL_ENV: database_url
    })

    assert window == promoted.window(NODE_ID, forward_days=FORWARD_DAYS)
    assert window.opened_at == DECIDED_AT
    assert window.criteria_hash == EXPECTED_HASH


def test_an_explicit_url_wins_over_the_environment(
    promoted: PromotionWindows, database_url: str
) -> None:
    # The precedence every store in this workspace states: an explicit argument
    # wins, else ``DATABASE_URL``.  Pinned with an environment naming a file
    # that holds nothing, so a resolver that consulted the environment first
    # would fail to find the row rather than quietly agree.
    window = promotion_window(
        NODE_ID,
        forward_days=FORWARD_DAYS,
        database_url=database_url,
        env={DATABASE_URL_ENV: "sqlite:///nowhere-at-all.db"},
    )

    assert window.opened_at == DECIDED_AT


def test_the_listing_spelling_resolves_its_store_the_same_way(
    promoted: PromotionWindows, database_url: str
) -> None:
    windows = promotion_windows(
        forward_days=FORWARD_DAYS, env={DATABASE_URL_ENV: database_url}
    )

    assert len(windows) == 1
    assert windows[0].node_id == NODE_ID


def test_a_deployment_naming_no_database_is_refused_by_name() -> None:
    # The silence is the dangerous failure here and not the refusal: a
    # deployment that could not answer where a window opens would leave the
    # forward record's writer choosing its own start instant, which is the state
    # ``0108``'s forward record exists to make impossible.  A blank value is
    # refused by the same check as an absent one, and the message names the
    # variable rather than a path, because the repair is to name a database.
    for env in ({}, {DATABASE_URL_ENV: ""}, {DATABASE_URL_ENV: "   "}):
        with pytest.raises(PromotionWindowError) as caught:
            promotion_window(NODE_ID, forward_days=FORWARD_DAYS, env=env)
        assert str(caught.value).startswith(PROMOTION_WINDOW_ERROR_CODE)
        assert DATABASE_URL_ENV in str(caught.value)


def test_from_env_is_none_when_no_database_is_named() -> None:
    # ``from_env`` is the *composing* spelling and answers ``None`` rather than
    # raising — an unconfigured deployment is a discoverable state, not an
    # error — the stance feature 291's builder takes one module over, so a
    # caller that wants to degrade can ask without catching.
    assert PromotionWindows.from_env({}) is None
    assert PromotionWindows.from_env({DATABASE_URL_ENV: "  "}) is None


def test_from_env_wires_the_same_store_the_environment_names(
    promoted: PromotionWindows, database_url: str
) -> None:
    reader = PromotionWindows.from_env({DATABASE_URL_ENV: database_url})

    assert reader is not None
    assert reader.decisions.database_url == database_url
    assert reader.window(NODE_ID, forward_days=FORWARD_DAYS).opened_at == DECIDED_AT


def test_the_reader_exposes_the_store_it_reads_through(
    promoted: PromotionWindows,
) -> None:
    # The store is a property rather than a private attribute a caller has to
    # reach for, because the composed deployment hands out a *decision* store
    # and the forward window is a second question asked of the same rows — the
    # wiring ``PromotionWindows.__init__`` documents.
    assert isinstance(promoted.decisions, PromotionDecisions)


def test_the_module_level_acts_propagate_the_refusal_unwrapped(
    registered_only: PromotionWindows, database_url: str
) -> None:
    # The refusal already names the node and the fact; re-wrapping it at the
    # module level would put a second message in front of the one an operator
    # needs.  Pinned by the message, not the class alone, so a re-wrap that kept
    # the class would still fail.
    with pytest.raises(PromotionWindowError) as caught:
        promotion_window(
            NODE_ID, forward_days=FORWARD_DAYS, env={DATABASE_URL_ENV: database_url}
        )

    assert str(caught.value).startswith(PROMOTION_WINDOW_ERROR_CODE)
    assert str(caught.value).count(PROMOTION_WINDOW_ERROR_CODE) == 1
