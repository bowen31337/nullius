"""The schema gate — rejecting drifted Parquet batches.

These tests are the feature statement for app_spec.xml feature 27 —
*"System rejects an incoming Parquet batch whose columns drifted from
the declared schema"* — read as behaviour of the schema module:

* a batch whose columns are exactly the declared ones — in any order —
  passes the gate and is committed to the stream's log;
* a batch missing a declared column, carrying an undeclared one, typing
  one differently, or naming one twice is *drift*: :class:`SchemaDrift`
  names exactly what changed, the batch never reaches the store, and
  the watermark does not advance — so the re-fetch after the schema is
  patched claims the same sequence, leaving the log gap-free;
* under the supervisor the rejection is a per-stream failure — §15's
  "halt ingest for that stream; alert; patch" — and every other stream
  keeps ingesting.
"""

from __future__ import annotations

import pytest

from nullius_ingest import (
    ColumnSpec,
    DeclaredSchema,
    InMemorySequenceStore,
    IngestSupervisor,
    IngestWorker,
    ParquetBatch,
    SchemaDrift,
    SchemaValidatingWorker,
    StagingArea,
    StreamClass,
)

#: The declaration a klines stream might make: the §4.1 kline fields,
#: each with the dtype its Parquet footer reports.
KLINE_COLUMNS = {
    "open_time": "int64",
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "volume": "float64",
}

DECLARED = DeclaredSchema.from_mapping(StreamClass.KLINES, KLINE_COLUMNS)


def conforming_batch(payload: bytes = b"kline-rows", rows: int = 3) -> ParquetBatch:
    """A batch whose columns are the declared kline columns, in order."""
    return ParquetBatch(columns=KLINE_COLUMNS, payload=payload, rows=rows)


def make_worker(
    store,
    batches,
    *,
    schema: DeclaredSchema = DECLARED,
    stream=StreamClass.KLINES,
) -> SchemaValidatingWorker:
    """A validating worker whose batches are queued, keyed by sequence.

    ``batches`` maps a resume sequence to the :class:`ParquetBatch` the
    fetch would return, or to ``None`` for an empty fetch — the same
    shape as the resumable-worker tests, so the gate composes with the
    same resume semantics a real fetch carries.
    """

    def build_batch(resume: int) -> ParquetBatch | None:
        if resume not in batches:
            raise KeyError(f"no batch queued for resume sequence {resume}")
        return batches[resume]

    return SchemaValidatingWorker(stream, schema, store, build_batch)


# -- Declaring a schema ------------------------------------------------------


def test_a_schema_from_a_mapping_keeps_declaration_order() -> None:
    schema = DeclaredSchema.from_mapping(StreamClass.KLINES, KLINE_COLUMNS)

    assert schema.stream is StreamClass.KLINES
    assert schema.column_names == tuple(KLINE_COLUMNS)


def test_specs_pairs_and_mappings_declare_the_same_schema() -> None:
    from_mapping = DeclaredSchema.from_mapping(
        StreamClass.KLINES, {"open_time": "int64", "open": "float64"}
    )
    from_pairs = DeclaredSchema(
        StreamClass.KLINES, (("open_time", "int64"), ("open", "float64"))
    )
    from_specs = DeclaredSchema(
        StreamClass.KLINES,
        (
            ColumnSpec(name="open_time", dtype="int64"),
            ColumnSpec(name="open", dtype="float64"),
        ),
    )

    assert from_mapping.columns == from_pairs.columns == from_specs.columns


def test_a_schema_coerces_its_stream_class() -> None:
    schema = DeclaredSchema("klines", {"open": "float64"})
    assert schema.stream is StreamClass.KLINES


def test_an_empty_declaration_is_refused() -> None:
    # A schema declaring nothing is a wiring bug in our code, not drift in
    # foreign data: it fails at construction, never at the gate.
    with pytest.raises(ValueError, match="at least one column"):
        DeclaredSchema(StreamClass.KLINES, {})


def test_a_declaration_repeating_a_column_is_refused() -> None:
    with pytest.raises(ValueError, match="repeats column"):
        DeclaredSchema(
            StreamClass.KLINES,
            (("open", "float64"), ("close", "float64"), ("open", "double")),
        )


def test_a_declaration_with_a_blank_dtype_is_refused() -> None:
    with pytest.raises(ValueError, match="no dtype"):
        DeclaredSchema(StreamClass.KLINES, {"open": ""})


# -- An incoming batch's columns ---------------------------------------------


def test_batch_columns_normalise_from_every_spelling() -> None:
    from_mapping = ParquetBatch(columns={"open": "float64"})
    from_pairs = ParquetBatch(columns=(("open", "float64"),))
    from_specs = ParquetBatch(columns=(ColumnSpec("open", "float64"),))

    assert from_mapping.columns == from_pairs.columns == from_specs.columns
    assert from_mapping.column_names == ("open",)


def test_a_batch_may_name_a_column_twice() -> None:
    # A repeated name is foreign-data drift for the gate to reject, not a
    # construction error — the batch stands as the feed sent it.
    batch = ParquetBatch(columns=(("open", "float64"), ("open", "double")))

    assert batch.column_names == ("open", "open")


# -- What passes the gate -----------------------------------------------------


def test_a_batch_matching_the_declaration_passes() -> None:
    assert DECLARED.validate(conforming_batch()) is None


def test_column_order_is_not_drift() -> None:
    # Parquet columns are addressed by name, so a reordered-but-equivalent
    # column set has not drifted; rejecting it would cry wolf.
    reordered = dict(reversed(list(KLINE_COLUMNS.items())))

    assert DECLARED.validate(ParquetBatch(columns=reordered)) is None


# -- What the gate rejects ----------------------------------------------------


def test_a_missing_declared_column_is_drift() -> None:
    drifted = {name: dtype for name, dtype in KLINE_COLUMNS.items() if name != "volume"}

    with pytest.raises(SchemaDrift) as raised:
        DECLARED.validate(ParquetBatch(columns=drifted))

    assert raised.value.missing == ("volume",)
    assert raised.value.unexpected == ()
    assert "missing column(s) 'volume'" in str(raised.value)


def test_an_undeclared_column_is_drift() -> None:
    # An exchange *adding* a field is a schema change too (§15): the gate
    # halts for patch, it does not silently ignore the newcomer.
    widened = {**KLINE_COLUMNS, "quote_volume": "float64"}

    with pytest.raises(SchemaDrift) as raised:
        DECLARED.validate(ParquetBatch(columns=widened))

    assert raised.value.unexpected == ("quote_volume",)
    assert raised.value.missing == ()
    assert "unexpected column(s) 'quote_volume'" in str(raised.value)


def test_a_renamed_column_is_reported_as_missing_and_unexpected() -> None:
    # The rename case §15 exists for: the exchange renames ``close`` to
    # ``close_price`` and every batch after it drifts on both ends.
    renamed = {
        **{n: d for n, d in KLINE_COLUMNS.items() if n != "close"},
        "close_price": "float64",
    }

    with pytest.raises(SchemaDrift) as raised:
        DECLARED.validate(ParquetBatch(columns=renamed))

    assert raised.value.missing == ("close",)
    assert raised.value.unexpected == ("close_price",)


def test_a_retyped_column_is_drift() -> None:
    retyped = {**KLINE_COLUMNS, "volume": "double"}

    with pytest.raises(SchemaDrift) as raised:
        DECLARED.validate(ParquetBatch(columns=retyped))

    assert raised.value.retyped == (("volume", "float64", "double"),)
    assert "retyped column(s) 'volume' (declared 'float64', batch 'double')" in str(
        raised.value
    )


def test_dtypes_are_compared_verbatim() -> None:
    # The declaration is the canonical spelling: a footer that spells the
    # dtype differently is drift in the safe direction — halt and patch —
    # not a quiet match.
    respelled = {**KLINE_COLUMNS, "open": "FLOAT64"}

    with pytest.raises(SchemaDrift, match="retyped column"):
        DECLARED.validate(ParquetBatch(columns=respelled))


def test_a_batch_naming_a_column_twice_is_drift() -> None:
    duplicated = (*KLINE_COLUMNS.items(), ("open", "float64"))

    with pytest.raises(SchemaDrift) as raised:
        DECLARED.validate(ParquetBatch(columns=duplicated))

    assert raised.value.duplicated == ("open",)
    assert "duplicated column(s) 'open'" in str(raised.value)


def test_a_batch_with_no_columns_is_all_missing() -> None:
    with pytest.raises(SchemaDrift) as raised:
        DECLARED.validate(ParquetBatch(columns=()))

    assert raised.value.missing == DECLARED.column_names


def test_the_drift_message_names_the_stream() -> None:
    with pytest.raises(SchemaDrift, match="^klines batch drifted"):
        DECLARED.validate(ParquetBatch(columns={"open": "float64"}))


# -- The gate inside a worker cycle ------------------------------------------


def test_a_conforming_batch_is_committed_under_the_next_sequence() -> None:
    store = InMemorySequenceStore()
    worker = make_worker(store, {1: conforming_batch(rows=7)})

    result = worker.run_cycle()

    assert result.rows_written == 7
    assert result.sequence == 1
    assert store.current(StreamClass.KLINES) == 1
    assert store.batches(StreamClass.KLINES)[0].payload == b"kline-rows"


def test_the_gate_runs_against_a_staging_area(tmp_path) -> None:
    # A StagingArea is a batch store, so the gate protects the §4.1 seal
    # boundary directly: what passes lands in staging/<stream>/<seq>.bin.
    area = StagingArea(tmp_path / "staging")
    worker = make_worker(area, {1: conforming_batch(payload=b"rows", rows=2)})

    result = worker.run_cycle()

    assert result.sequence == 1
    assert (tmp_path / "staging" / "klines" / "1.bin").read_bytes() == b"rows"


def test_a_drifted_batch_is_rejected_before_any_write(tmp_path) -> None:
    # The rejection is the whole feature: the drifted batch's bytes never
    # reach the append-only log, and the watermark does not advance.
    area = StagingArea(tmp_path / "staging")
    drifted = ParquetBatch(columns={**KLINE_COLUMNS, "vol": "float64"}, payload=b"bad")
    worker = make_worker(area, {1: drifted})

    with pytest.raises(SchemaDrift):
        worker.run_cycle()

    assert area.current(StreamClass.KLINES) == 0
    assert area.staged(StreamClass.KLINES) == ()
    assert not (tmp_path / "staging" / "klines").exists()


def test_after_a_rejection_the_refetched_batch_claims_the_same_sequence(
    tmp_path,
) -> None:
    # §15's patch step: the schema is fixed, the batch is re-fetched, and
    # it lands under the very sequence the drifted one would have — the
    # log keeps no hole and no drift.
    area = StagingArea(tmp_path / "staging")
    drifted = ParquetBatch(columns=KLINE_COLUMNS | {"extra": "float64"})
    worker = make_worker(area, {1: drifted})

    with pytest.raises(SchemaDrift):
        worker.run_cycle()

    patched = make_worker(area, {1: conforming_batch(payload=b"after-patch")})
    result = patched.run_cycle()

    assert result.sequence == 1
    assert (tmp_path / "staging" / "klines" / "1.bin").read_bytes() == b"after-patch"


def test_an_empty_fetch_commits_nothing() -> None:
    store = InMemorySequenceStore()
    worker = make_worker(store, {1: None})

    result = worker.run_cycle()

    assert result.rows_written == 0
    assert result.sequence == 0
    assert store.current(StreamClass.KLINES) == 0


# -- Worker wiring ------------------------------------------------------------


def test_the_validating_worker_satisfies_the_ingest_worker_protocol() -> None:
    worker = make_worker(InMemorySequenceStore(), {})
    assert isinstance(worker, IngestWorker)
    assert worker.stream_class is StreamClass.KLINES


def test_the_worker_coerces_its_stream_class() -> None:
    worker = make_worker(InMemorySequenceStore(), {}, stream="klines")
    assert worker.stream_class is StreamClass.KLINES


def test_a_schema_for_another_stream_cannot_gate() -> None:
    # Gating klines on funding's declaration would reject honest batches
    # for drift they do not have — a wiring bug, failed at construction.
    funding_schema = DeclaredSchema.from_mapping(
        StreamClass.FUNDING, {"funding_rate": "float64"}
    )
    with pytest.raises(TypeError, match="cannot gate"):
        SchemaValidatingWorker(
            StreamClass.KLINES, funding_schema, InMemorySequenceStore(), lambda seq: None
        )


def test_the_worker_rejects_a_non_store() -> None:
    with pytest.raises(TypeError, match="batch store"):
        SchemaValidatingWorker(
            StreamClass.KLINES, DECLARED, "not a store", lambda seq: None  # type: ignore[arg-type]
        )


def test_the_worker_rejects_a_non_callable_factory() -> None:
    with pytest.raises(TypeError, match="callable"):
        SchemaValidatingWorker(
            StreamClass.KLINES, DECLARED, InMemorySequenceStore(), object()  # type: ignore[arg-type]
        )


def test_the_worker_rejects_a_non_parquet_batch_return() -> None:
    worker = make_worker(InMemorySequenceStore(), {1: "not a batch"})  # type: ignore[dict-item]
    with pytest.raises(TypeError, match="ParquetBatch"):
        worker.run_cycle()


# -- Halt ingest for that stream ----------------------------------------------


def test_a_drifted_batch_halts_only_its_stream(tmp_path) -> None:
    # §15 end to end: the drifted klines batch halts klines — as a failure
    # record, the alert — while funding keeps ingesting in the same cycle,
    # because the rejection rides the feature 16 boundary.
    area = StagingArea(tmp_path / "staging")

    klines = make_worker(
        area,
        {
            1: ParquetBatch(
                columns={"open": "float64"}, payload=b"drifted", rows=9
            )
        },
    )
    funding_schema = DeclaredSchema.from_mapping(
        StreamClass.FUNDING, {"symbol": "string", "funding_rate": "float64"}
    )
    funding = make_worker(
        area,
        {
            1: ParquetBatch(
                columns={"symbol": "string", "funding_rate": "float64"},
                payload=b"ok",
                rows=4,
            )
        },
        schema=funding_schema,
        stream=StreamClass.FUNDING,
    )

    report = IngestSupervisor([klines, funding]).run_cycle()

    assert not report.ok
    klines_outcome = report.outcome_for(StreamClass.KLINES)
    assert not klines_outcome.ok
    assert klines_outcome.failure.error_type == "SchemaDrift"
    assert "missing column(s)" in klines_outcome.failure.message
    assert klines_outcome.rows_written == 0

    funding_outcome = report.outcome_for(StreamClass.FUNDING)
    assert funding_outcome.ok
    assert funding_outcome.rows_written == 4

    # The halted stream wrote nothing; the other stream's batch is staged.
    assert area.current(StreamClass.KLINES) == 0
    assert area.current(StreamClass.FUNDING) == 1
    assert (tmp_path / "staging" / "funding" / "1.bin").read_bytes() == b"ok"
