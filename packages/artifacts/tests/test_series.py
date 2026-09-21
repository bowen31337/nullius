"""The IC and turnover series — §9.2's two Parquet files, feature 171.

app_spec.xml, "Tree & Artifact Persistence", feature 171: *System
persists ic_series and turnover_series as Parquet files inside the node
artifact directory.*  These tests hold the layer to that sentence in the
places it can be read:

* **inside the node artifact directory** — each file stages through
  feature 169's write path and publishes by the node's one commit, so it
  sits inside the node's single directory beside every other §9.2 file,
  rolls back with everything else on a discard, and is replaced wholesale
  by a refresh;
* **as Parquet** — real Zstd-compressed Parquet bytes, carrying the
  ``date32``/``float64`` pair this layer pins, sorted by date so two equal
  series stage identical bytes and insertion order is never part of a
  stored series' identity;
* **the two series** — each is persisted, read and checked on its own:
  they are written by two calls and each is independently readable, so
  neither operation demands the other and each invariant answers for one
  name;
* **the refusals** — a series that is not a mapping of calendar dates to
  finite numbers, and a value no Parquet column may carry, all refuse
  *before the first staged byte*; the read side refuses bytes this
  member's writer cannot have produced, and names what is wrong with them.

The *metric* is the evaluator's: what an information coefficient means
(feature 80) and what a fractional turnover is (feature 85) belong to
that package, and it is not imported here (the workspace contract — no
member imports another).  These tests stage series of the shapes those
steps render — ``Mapping[dt.date, float]`` from the metrics,
``dict[str, float]`` keyed by ``date.isoformat()`` from the turnover
renderer — and assert only what this layer owns: the names, the schema,
the canonical row order, the read side and the refusals.

pyarrow is a declared dependency of this member (see ``pyproject.toml``),
so under the canonical invocation (``uv run --all-packages pytest``, what
the acceptance gate runs) it is present; the guard below keeps a partially
installed environment from turning a missing wheel into a collection error
that takes the whole suite down with it, the same guard
``tests/feature-store/test_parquet.py`` takes.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "pyarrow",
    reason="the §9.2 series suite requires pyarrow (a declared dependency)",
)

import pyarrow as pa
from artifacts import (
    DATE_COLUMN,
    IC_SERIES_FILENAME,
    PARQUET_COMPRESSION,
    TURNOVER_SERIES_FILENAME,
    VALUE_COLUMN,
    ArtifactKeyError,
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreError,
    decode_series,
    encode_series,
    ic_series,
    ic_series_is_persisted,
    persist_ic_series,
    persist_turnover_series,
    turnover_series,
    turnover_series_is_persisted,
)

#: conftest.py -> packages/artifacts/tests -> packages/artifacts -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]

D1 = dt.date(2026, 1, 5)
D2 = dt.date(2026, 1, 6)
D3 = dt.date(2026, 1, 7)

#: An information-coefficient series in the shape the evaluator's metrics
#: carry: ``Mapping[dt.date, float]``, one coefficient per rebalance date.
IC = {D1: 0.071, D2: -0.003, D3: 0.052}

#: A turnover series in the shape the evaluator's turnover renderer
#: answers: ``dict[str, float]`` keyed by ``date.isoformat()``, one entry
#: per rebalance that has a predecessor.
TURNOVER = {"2026-01-06": 0.25, "2026-01-07": 0.5}


def _read_parquet(payload: bytes) -> pa.Table:
    """Read raw Parquet bytes back as an Arrow table, for shape assertions."""
    return pa.parquet.read_table(pa.BufferReader(payload))


# -- The §9.2 names and the schema the two files share -----------------------------


def test_the_series_names_are_the_layouts() -> None:
    # §9.2 spells the two lines "ic_series.parquet" and
    # "turnover_series.parquet"; the layer spells them once, and these are
    # those spellings — pinned so a rename on either side of the seam shows
    # up here rather than as a directory silently carrying the wrong name.
    assert IC_SERIES_FILENAME == "ic_series.parquet"
    assert TURNOVER_SERIES_FILENAME == "turnover_series.parquet"


def test_both_series_share_one_pinned_schema() -> None:
    # The shape is the feature's, not the metric's: one ``date``/``value``
    # pair, both types pinned rather than inferred, so a DuckDB scan of
    # either file spells the same two columns and needs no inference to
    # know what it holds.  ``date32`` is the column type that makes a
    # rebalance a pushable predicate; ``float64`` keeps the double the
    # evaluator computed (§9.3's float32 is the resident replay array's
    # decision, an opposite one for an opposite reason).
    table = _read_parquet(
        encode_series(IC, filename=IC_SERIES_FILENAME, campaign_id="c", node_id="n")
    )
    assert table.schema.names == [DATE_COLUMN, VALUE_COLUMN]
    assert pa.types.is_date32(table.schema.field(DATE_COLUMN).type)
    assert pa.types.is_floating(table.schema.field(VALUE_COLUMN).type)


# -- Inside: the files ride feature 169's write path -------------------------------


def test_the_series_stage_inside_the_nodes_staged_set(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The write half: both files join the node's staged set through the
    # store's own write path — no second plumbing — invisible to every
    # read until the commit publishes them.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"returns")

    staged_ic = persist_ic_series(store, campaign_id, node_id, IC)
    staged_turnover = persist_turnover_series(
        store, campaign_id, node_id, TURNOVER
    )

    assert store.staged(campaign_id, node_id) == (
        IC_SERIES_FILENAME,
        "signal_returns.parquet",
        TURNOVER_SERIES_FILENAME,
    )
    staged = store.staging_root / campaign_id / node_id
    assert staged_ic == staged / IC_SERIES_FILENAME
    assert staged_turnover == staged / TURNOVER_SERIES_FILENAME


def test_the_series_publish_inside_the_node_directory(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The commit point is the store's, not this layer's: after the node's
    # one ``commit``, both files sit inside the node's single directory
    # beside every other §9.2 file, keyed by the same two ids.  This is
    # the feature's sentence — "inside the node artifact directory" —
    # read literally.
    store.write(campaign_id, node_id, "exec_trace.json", b"{}")
    persist_ic_series(store, campaign_id, node_id, IC)
    persist_turnover_series(store, campaign_id, node_id, TURNOVER)
    published = store.commit(campaign_id, node_id)

    assert published == store.root / campaign_id / node_id
    assert store.files(campaign_id, node_id) == (
        "exec_trace.json",
        IC_SERIES_FILENAME,
        TURNOVER_SERIES_FILENAME,
    )
    for name in (IC_SERIES_FILENAME, TURNOVER_SERIES_FILENAME):
        assert (published / name).read_bytes().startswith(b"PAR1")


def test_a_discard_rolls_both_series_back(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The rollback half: a pipeline that fails after staging leaves no
    # half-written node — the series vanish with every other staged file,
    # and the node's address holds no directory at all.
    persist_ic_series(store, campaign_id, node_id, IC)
    persist_turnover_series(store, campaign_id, node_id, TURNOVER)

    store.discard(campaign_id, node_id)

    assert store.staged(campaign_id, node_id) == ()
    assert not store.has_node(campaign_id, node_id)


def test_a_refresh_replaces_both_series_wholesale(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A re-persisted node carries the retry's series, never a splice of two
    # runs: the staged set is a mapping keyed by filename, so re-staging
    # keeps the last bytes and the commit replaces the directory as one
    # unit.  Without this, a node would carry the first attempt's IC series
    # beside the retry's turnover.
    persist_ic_series(store, campaign_id, node_id, IC)
    store.commit(campaign_id, node_id)

    retry = {D1: 0.999}
    persist_ic_series(store, campaign_id, node_id, retry)
    persist_turnover_series(store, campaign_id, node_id, TURNOVER)
    store.commit(campaign_id, node_id)

    assert ic_series(store, campaign_id, node_id) == retry
    assert store.files(campaign_id, node_id) == (
        IC_SERIES_FILENAME,
        TURNOVER_SERIES_FILENAME,
    )


def test_the_two_series_are_not_a_pair_the_way_source_and_trace_are(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The feature's sentence says *and*, not *plus* — feature 173's
    # contract is the pair that cannot stage a half, and these two are
    # not it.  Each is written and read on its own, so a node carrying
    # one and not the other is a legitimate state a sweep may meet, and
    # neither operation insists on the other.
    persist_ic_series(store, campaign_id, node_id, IC)
    store.commit(campaign_id, node_id)

    assert ic_series_is_persisted(store, campaign_id, node_id) is True
    assert turnover_series_is_persisted(store, campaign_id, node_id) is False
    assert store.files(campaign_id, node_id) == (IC_SERIES_FILENAME,)


# -- The bytes: canonical row order, and a real Parquet file -----------------------


def test_the_rows_are_sorted_by_date_regardless_of_insertion_order() -> None:
    # Two equal series built in different insertion orders must stage
    # *identical bytes* — the canonical-bytes discipline the JSON writers
    # of this member state, restated for a row-oriented format.  This is
    # what lets replay compare a stored series against the one it is
    # reconstructing and compare content rather than key order.
    forwards = {D1: 0.1, D2: 0.2, D3: 0.3}
    backwards = {D3: 0.3, D2: 0.2, D1: 0.1}

    first = encode_series(
        forwards, filename=IC_SERIES_FILENAME, campaign_id="c", node_id="n"
    )
    second = encode_series(
        backwards, filename=IC_SERIES_FILENAME, campaign_id="c", node_id="n"
    )

    assert first == second
    dates = _read_parquet(first).column(DATE_COLUMN).to_pylist()
    assert dates == [D1, D2, D3]


def test_the_same_series_encodes_to_the_same_bytes_twice() -> None:
    # Determinism is a property of the codec, not of a lucky run: the
    # replay path compares payloads, so the same series must always
    # encode to byte-identical Parquet.
    once = encode_series(
        IC, filename=IC_SERIES_FILENAME, campaign_id="c", node_id="n"
    )
    twice = encode_series(
        IC, filename=IC_SERIES_FILENAME, campaign_id="c", node_id="n"
    )
    assert once == twice


def test_the_file_is_zstd_compressed_parquet() -> None:
    # §4.1's stack table pins "Parquet + Zstd, columnar, compressed,
    # portable", and §9.2 sizes this store in gigabytes — so the codec is
    # asserted against the file's own metadata rather than assumed from
    # the fact that it parsed.
    payload = encode_series(
        IC, filename=IC_SERIES_FILENAME, campaign_id="c", node_id="n"
    )
    assert payload.startswith(b"PAR1")
    metadata = pa.parquet.read_metadata(pa.BufferReader(payload))
    assert (
        metadata.row_group(0).column(0).compression == PARQUET_COMPRESSION.upper()
    )


def test_a_series_keyed_by_iso_text_round_trips_to_date_keys() -> None:
    # The two renderers answer two key spellings — the metrics carry
    # ``dt.date`` and the turnover renderer answers ``date.isoformat()``
    # — and both land here, in the one layer that writes the file.  The
    # read side answers *dates* either way, because that is what a
    # ``date32`` column is: the typed column and the typed answer are one
    # decision, and JSON's parse step is exactly the cost this buys back.
    assert decode_series(
        encode_series(
            TURNOVER, filename=TURNOVER_SERIES_FILENAME, campaign_id="c", node_id="n"
        ),
        filename=TURNOVER_SERIES_FILENAME,
        campaign_id="c",
        node_id="n",
    ) == {D2: 0.25, D3: 0.5}


def test_the_decoded_series_is_in_ascending_date_order() -> None:
    # The read side answers the series in the one order a series has, so a
    # reader walking it meets the rebalances in the order the book turned
    # them over.  Asserted on a mapping built out of order, so the
    # guarantee is the layer's rather than the caller's.
    decoded = decode_series(
        encode_series(
            {D3: 0.3, D1: 0.1, D2: 0.2},
            filename=IC_SERIES_FILENAME,
            campaign_id="c",
            node_id="n",
        ),
        filename=IC_SERIES_FILENAME,
        campaign_id="c",
        node_id="n",
    )
    assert list(decoded) == [D1, D2, D3]


# -- The read side: the series, by the same two keys --------------------------------


def test_the_series_are_read_back_by_the_same_two_keys(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The read side replay stands on: the same store that persisted the
    # directory answers for its contents, keying by the node's two ids.
    # Each reader answers its own file, and the numbers are the ones
    # written rather than a re-derivation.
    persist_ic_series(store, campaign_id, node_id, IC)
    persist_turnover_series(store, campaign_id, node_id, TURNOVER)
    store.commit(campaign_id, node_id)

    assert ic_series(store, campaign_id, node_id) == IC
    assert turnover_series(store, campaign_id, node_id) == {D2: 0.25, D3: 0.5}


def test_a_missing_node_or_file_refuses_and_names_the_missing_half(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # "No node" and "a node missing one file" are different facts, and the
    # refusal names which — the distinction a reconciliation sweep wants,
    # and the one feature 169's read side already draws.
    with pytest.raises(ArtifactNotFoundError, match="no artifact directory"):
        ic_series(store, campaign_id, node_id)

    store.write(campaign_id, node_id, "code.py", b"pass\n")
    store.commit(campaign_id, node_id)
    with pytest.raises(ArtifactNotFoundError, match=IC_SERIES_FILENAME):
        ic_series(store, campaign_id, node_id)
    with pytest.raises(ArtifactNotFoundError, match=TURNOVER_SERIES_FILENAME):
        turnover_series(store, campaign_id, node_id)


def test_a_staged_but_unpublished_series_is_invisible_and_not_persisted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Staged-but-uncommitted is invisible by design — the discipline
    # feature 169 states — so the invariant answers ``False`` and the
    # reader refuses, rather than either half seeing a file the commit
    # has not published.
    persist_ic_series(store, campaign_id, node_id, IC)

    assert ic_series_is_persisted(store, campaign_id, node_id) is False
    with pytest.raises(ArtifactNotFoundError):
        ic_series(store, campaign_id, node_id)


def test_the_read_side_refuses_bytes_its_writer_could_not_have_produced(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Bytes at the right name that are not a file this member's write path
    # emitted are refused rather than answered as a stand-in: a series is
    # one node's per-date measurements, and a value nothing here can
    # produce is a file somebody else put there.
    cases = {
        "not parquet at all": b"date,value\n2026-01-05,0.071\n",
        "empty bytes": b"",
        "truncated": b"PAR1PAR",
    }
    for label, payload in cases.items():
        store.write(campaign_id, node_id, IC_SERIES_FILENAME, payload)
        store.commit(campaign_id, node_id)
        with pytest.raises(ArtifactStoreError) as excinfo:
            ic_series(store, campaign_id, node_id)
        assert "not a Parquet series" in str(excinfo.value), label


def test_a_file_with_the_wrong_columns_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Names *and* types are checked, because a file carrying the right
    # names and the wrong types would decode into keys and values of the
    # wrong shape and be answered as a series.  A ``string`` date column
    # is the case a JSON-shaped file would produce.
    wrong_names = pa.Table.from_pydict({"when": [D1], "ic": [0.071]})
    wrong_types = pa.Table.from_pydict(
        {"date": ["2026-01-05"], "value": [0.071]}
    )
    for label, table, pattern in (
        ("wrong column names", wrong_names, "carries no 'date' column"),
        ("wrong column types", wrong_types, "keyed by calendar dates"),
    ):
        buffer = io.BytesIO()
        pa.parquet.write_table(table, buffer, compression=PARQUET_COMPRESSION)
        store.write(campaign_id, node_id, IC_SERIES_FILENAME, buffer.getvalue())
        store.commit(campaign_id, node_id)
        with pytest.raises(ArtifactStoreError) as excinfo:
            ic_series(store, campaign_id, node_id)
        assert pattern in str(excinfo.value), label


def test_a_file_carrying_a_duplicate_date_or_a_null_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A series is one value per date: a file carrying two would silently
    # collapse to whichever row a dict was built last from, which is a
    # number the writer never wrote.  A null entry is the other shape this
    # layer's writer emits nowhere — an absent measurement is an absent
    # row.
    schema = pa.schema(
        [pa.field(DATE_COLUMN, pa.date32()), pa.field(VALUE_COLUMN, pa.float64())]
    )
    for label, values, pattern in (
        ("duplicate date", {DATE_COLUMN: [D1, D1], VALUE_COLUMN: [0.1, 0.2]}, "twice"),
        ("null value", {DATE_COLUMN: [D1], VALUE_COLUMN: [None]}, "null value"),
        ("null date", {DATE_COLUMN: [None], VALUE_COLUMN: [0.1]}, "null date"),
        (
            "non-finite value",
            {DATE_COLUMN: [D1], VALUE_COLUMN: [float("inf")]},
            "non-finite",
        ),
    ):
        table = pa.Table.from_pydict(values, schema=schema)
        buffer = io.BytesIO()
        pa.parquet.write_table(table, buffer, compression=PARQUET_COMPRESSION)
        store.write(campaign_id, node_id, IC_SERIES_FILENAME, buffer.getvalue())
        store.commit(campaign_id, node_id)
        with pytest.raises(ArtifactStoreError) as excinfo:
            ic_series(store, campaign_id, node_id)
        assert pattern in str(excinfo.value), label


# -- The refusals: nothing bad stages a byte ---------------------------------------


def test_an_empty_series_is_refused_before_anything_is_staged(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A series with no dates measured nothing at all — it is not a sparse
    # measurement to persist honestly but a document no writer of this
    # step produced (the evaluator's metrics refuse an empty IC series by
    # name, and a panel too short to carry a per-date spread is refused a
    # step before).  Refused *before the first staged byte*, so a rejected
    # call never leaves a zero-row file in the staged set.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"returns")

    with pytest.raises(ArtifactStoreError, match="empty series"):
        persist_ic_series(store, campaign_id, node_id, {})

    assert store.staged(campaign_id, node_id) == ("signal_returns.parquet",)


def test_one_date_spelled_two_ways_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # This layer accepts a date and its ISO text as the same key, which
    # makes colliding across the two spellings its problem rather than the
    # caller's: ``{D1: 0.1, "2026-01-05": 0.2}`` is two keys to Python and
    # one row to Parquet, so accepting it would encode a file carrying that
    # date twice — and this layer's own reader refuses a duplicate date, so
    # the writer would have produced bytes it cannot read back.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"returns")

    with pytest.raises(ArtifactStoreError, match="twice"):
        persist_ic_series(
            store, campaign_id, node_id, {D1: 0.1, D1.isoformat(): 0.2}
        )

    # Refused before the first staged byte, like every other refusal here.
    assert store.staged(campaign_id, node_id) == ("signal_returns.parquet",)


def test_a_series_that_is_not_a_mapping_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Text and sequences are refused by name rather than coerced: a
    # string is not a mapping of dates, and a list of numbers carries no
    # dates at all, so a caller that made either mistake is told which.
    for value in ("2026-01-05:0.071", [0.071, 0.052], 0.071, None):
        with pytest.raises(ArtifactStoreError, match="mapping of dates"):
            persist_ic_series(store, campaign_id, node_id, value)


def test_a_datetime_key_is_refused_though_it_is_a_date(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # ``datetime`` *is* a ``date`` in Python, so it would pass a naive
    # ``isinstance`` check — and then key the series by an instant no
    # other date in it can be compared with.  Refused by name, before the
    # date check, because that is the mistake that would surface far from
    # here.
    #
    # The naive datetime is the fixture, not an oversight: this layer
    # refuses a datetime key whatever its tzinfo, and a tz-aware one would
    # leave "is it the naive case only?" untested.  The linter's
    # tz-awareness rule is aimed at datetimes a caller constructs to *use*,
    # which this one never is.
    naive_instant = dt.datetime(2026, 1, 5, 9, 30)  # noqa: DTZ001
    with pytest.raises(ArtifactStoreError, match="datetime"):
        persist_ic_series(store, campaign_id, node_id, {naive_instant: 0.071})


def test_a_key_that_is_not_a_calendar_date_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    for key, pattern in (
        ("05/01/2026", "ISO-8601"),
        ("not a date", "ISO-8601"),
        (20260105, "not a date"),
        (None, "not a date"),
    ):
        with pytest.raises(ArtifactStoreError, match=pattern):
            persist_ic_series(store, campaign_id, node_id, {key: 0.071})


def test_a_non_finite_or_non_numeric_measurement_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # ``nan`` and ``inf`` are what a correlation produces over a constant
    # cross-section, not a measurement, and a coefficient a reader must be
    # able to compare is one a reader must be able to parse.  The refusal
    # names the date, which is the only handle that finds it in a series
    # of a few thousand entries.
    for value, pattern in (
        (float("nan"), "finite"),
        (float("inf"), "finite"),
        (float("-inf"), "finite"),
        (True, "numbers"),
        ("0.071", "numbers"),
        (None, "numbers"),
    ):
        with pytest.raises(ArtifactStoreError, match=pattern):
            persist_ic_series(store, campaign_id, node_id, {D1: value})


def test_a_refused_series_names_the_file_and_the_node(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A node has more than one series, so "a series is malformed" is not
    # actionable on its own: the refusal says which of the node's files
    # was being rendered, and for which node.
    with pytest.raises(ArtifactStoreError) as excinfo:
        persist_turnover_series(store, campaign_id, node_id, {D1: float("nan")})

    message = str(excinfo.value)
    assert TURNOVER_SERIES_FILENAME in message
    assert node_id in message
    assert campaign_id in message


def test_a_malformed_key_refuses_as_a_key_failure(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The two-segment key is the layout (feature 169) and it outranks
    # everything staged through it: a bad key refuses as a key failure
    # rather than as a payload complaint, and names the address that broke.
    with pytest.raises(ArtifactKeyError):
        persist_ic_series(store, campaign_id, "a/b", IC)
    with pytest.raises(ArtifactKeyError):
        persist_ic_series(store, ".staging", node_id, IC)


# -- The layering note: pyarrow is not a composition cost ---------------------------


def test_importing_the_package_does_not_import_pyarrow() -> None:
    # This member is imported by the application factory's workspace scan,
    # so a module-scope ``import pyarrow`` anywhere in the package would
    # make pyarrow a precondition for *composing the application* — a much
    # larger blast radius than these two files need, since feature 169's
    # keying, write path and read side need no Arrow at all and neither
    # does the JSON half of this category.
    #
    # Asserted in a subprocess, because this suite's own imports have
    # already loaded pyarrow into this interpreter (the guard above makes
    # the module import it at collection time).  PYTHONPATH is set from the
    # repo layout rather than inherited, so the check does not silently
    # depend on the workspace member having been installed into the venv —
    # the seam under test is exactly the one that must survive a bare
    # ``uv run``, which installs only the root project.
    script = (
        "import sys; import artifacts, artifacts._series;"
        "assert 'pyarrow' not in sys.modules, 'pyarrow imported at module scope';"
        "print('deferred')"
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(REPO_ROOT / "src"),
                str(REPO_ROOT / "packages" / "artifacts" / "src"),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "deferred"


def test_the_parquet_path_is_the_only_place_that_reaches_for_arrow() -> None:
    # The other half of the same contract, and the half a subprocess cannot
    # show: within this package, ``require_arrow`` is the one function that
    # imports pyarrow, so the deferral is a seam rather than a coincidence
    # of which submodules happen to be imported.  A second ``import
    # pyarrow`` at module scope anywhere in the member would re-introduce
    # the composition cost the deferral exists to avoid, silently, the next
    # time that module is imported.
    #
    # Read as AST rather than as text, because the import under test is
    # *indented* (it sits inside ``require_arrow``'s ``try``) — a textual
    # search for a column-zero import would find nothing and pass for the
    # wrong reason.
    import ast

    import artifacts._series as series_module

    def imports_pyarrow(node: ast.stmt) -> bool:
        """Whether this statement imports pyarrow, by either import form."""
        if isinstance(node, ast.Import):
            return any(
                alias.name == "pyarrow" or alias.name.startswith("pyarrow.")
                for alias in node.names
            )
        if isinstance(node, ast.ImportFrom):
            return node.module == "pyarrow" or (
                node.module or ""
            ).startswith("pyarrow.")
        return False

    tree = ast.parse(Path(series_module.__file__).read_text())
    module_level = [node for node in tree.body if imports_pyarrow(node)]
    assert module_level == [], (
        "pyarrow is imported at module scope, which makes it a precondition "
        "for composing the application"
    )

    # And the deferral is where it is claimed to be: the one function in
    # this module whose body reaches for it.
    importers = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(imports_pyarrow(inner) for inner in ast.walk(node))
    ]
    assert importers == ["require_arrow"]
