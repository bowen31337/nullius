"""Feature 59, second half — the resolved pair is persisted.

app_spec.xml feature 59: *System persists the resolved cost model version
string with its venue name after loading the YAML configuration.*  This
file pins the *persists … with its venue name* half; :mod:`test_config`
pins the loading half.

Four claims, each able to fail on its own:

* **it is persisted** — the row is really in the store, read back through a
  second connection so the assertion is about what landed on disk and not
  about an in-memory value the write happened to return.
* **the version string and its venue name** — both, in one row, and they
  identify it: the pair is the key, because a version alone does not say
  whose fee schedule it is.
* **after loading the YAML** — the persisted value is the *loaded* value.
  A test that hand-builds a config and persists it proves the store works
  but not that the feature's sentence holds, so the round trip here starts
  from a document on disk and goes through the loader.
* **re-loading converges** — the same signed artifact loaded twice leaves
  one row, and a store accumulates exactly the distinct cost models it has
  been asked to price against.
"""

from __future__ import annotations

from contextlib import closing

import pytest

from cost_model import (
    COST_MODEL_TABLE,
    CostModelConfig,
    CostModelService,
    CostModelStoreError,
    load_cost_model,
    load_persisted_cost_model,
    persist_cost_model,
)
from cost_model.store import connect

DOCUMENT = """
cost_model:
  version: "2026.09.1"
  venue: binance_spot
"""


def rows(database_url: str) -> list[tuple]:
    """Every row of the table, straight from the store.

    A raw read on a fresh connection, so an assertion is about the bytes on
    disk rather than about the writer's return value.
    """
    with closing(connect(database_url)) as connection:
        return connection.execute(
            f"SELECT venue, version, source, resolved_at FROM {COST_MODEL_TABLE}"
        ).fetchall()


class TestTheResolvedPairIsPersisted:
    def test_a_loaded_config_lands_in_the_store(
        self, document, test_database_url: str
    ) -> None:
        config = load_cost_model(document(DOCUMENT))
        persist_cost_model(config, test_database_url)
        (row,) = rows(test_database_url)
        assert row[0] == "binance_spot"
        assert row[1] == "2026.09.1"

    def test_the_persisted_value_is_the_loaded_value(
        self, document, test_database_url: str
    ) -> None:
        # Feature 59's sentence has an order — load, *then* persist — and
        # this is that order: the row must carry the identity the loader
        # resolved from the document, not one the caller supplied beside it.
        path = document(DOCUMENT)
        loaded = load_cost_model(path)
        written = persist_cost_model(loaded, test_database_url)
        assert written == loaded
        back = load_persisted_cost_model(
            loaded.venue, loaded.version, test_database_url
        )
        assert back is not None
        assert (back.venue, back.version) == (loaded.venue, loaded.version)

    def test_the_round_trip_is_lossless_including_provenance(
        self, document, test_database_url: str
    ) -> None:
        loaded = load_cost_model(document(DOCUMENT))
        persist_cost_model(loaded, test_database_url)
        back = load_persisted_cost_model(
            loaded.venue, loaded.version, test_database_url
        )
        assert back == loaded

    def test_the_provenance_column_records_the_document_path(
        self, document, test_database_url: str
    ) -> None:
        path = document(DOCUMENT)
        persist_cost_model(load_cost_model(path), test_database_url)
        (row,) = rows(test_database_url)
        assert row[2] == str(path)

    def test_the_stamp_is_a_utc_instant(self, document, test_database_url: str) -> None:
        persist_cost_model(
            load_cost_model(document(DOCUMENT)), test_database_url
        )
        (row,) = rows(test_database_url)
        assert row[3].endswith("+00:00")

    def test_a_miss_is_none_and_an_existing_row_is_returned(
        self, document, test_database_url: str
    ) -> None:
        persist_cost_model(
            load_cost_model(document(DOCUMENT)), test_database_url
        )
        assert (
            load_persisted_cost_model("binance_spot", "2026.09.1", test_database_url)
            is not None
        )
        # A cost model this store has never priced against is a discoverable
        # state, not an exception.
        assert (
            load_persisted_cost_model("kraken_spot", "2026.09.1", test_database_url)
            is None
        )
        assert (
            load_persisted_cost_model("binance_spot", "2025.01.1", test_database_url)
            is None
        )


class TestLoadingTheSameArtifactTwiceConverges:
    def test_repeated_loads_leave_one_row(
        self, document, test_database_url: str
    ) -> None:
        path = document(DOCUMENT)
        for _ in range(3):
            persist_cost_model(load_cost_model(path), test_database_url)
        assert len(rows(test_database_url)) == 1

    def test_reloading_refreshes_provenance_without_changing_identity(
        self, document, tmp_path, test_database_url: str
    ) -> None:
        # `source` is provenance, allowed to move; the pair is identity, and
        # is not.  A relocated artifact must not read as a second schedule.
        first = document(DOCUMENT, "one.yaml")
        persist_cost_model(load_cost_model(first), test_database_url)
        second = document(DOCUMENT, "two.yaml")
        persist_cost_model(load_cost_model(second), test_database_url)
        (row,) = rows(test_database_url)
        assert row[0] == "binance_spot" and row[1] == "2026.09.1"
        assert row[2] == str(second)

    def test_distinct_versions_are_distinct_rows(
        self, document, test_database_url: str
    ) -> None:
        persist_cost_model(
            load_cost_model(document(DOCUMENT, "a.yaml")), test_database_url
        )
        persist_cost_model(
            load_cost_model(
                document(
                    'cost_model:\n  version: "2027.01.1"\n  venue: binance_spot\n',
                    "b.yaml",
                )
            ),
            test_database_url,
        )
        assert len(rows(test_database_url)) == 2

    def test_the_same_version_at_two_venues_is_two_rows(
        self, document, test_database_url: str
    ) -> None:
        # The whole reason the pair is the key: §6.2 writes the same schema
        # per venue, so "2026.09.1" is not one cost model — it is one per
        # venue, and a key that dropped the venue would collapse them.
        persist_cost_model(
            load_cost_model(document(DOCUMENT, "a.yaml")), test_database_url
        )
        persist_cost_model(
            load_cost_model(
                document(
                    'cost_model:\n  version: "2026.09.1"\n  venue: kraken_spot\n',
                    "b.yaml",
                )
            ),
            test_database_url,
        )
        assert len(rows(test_database_url)) == 2


class TestTheStoreRefusesWhatItCannotHonor:
    def test_an_unconfigured_store_is_refused_by_name(self, monkeypatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(CostModelStoreError, match="DATABASE_URL"):
            persist_cost_model(
                CostModelConfig(version="2026.09.1", venue="binance_spot")
            )

    def test_a_non_sqlite_url_is_refused_by_scheme(self) -> None:
        with pytest.raises(CostModelStoreError, match="postgres"):
            persist_cost_model(
                CostModelConfig(version="2026.09.1", venue="binance_spot"),
                "postgres://u:p@h:5432/nullius",
            )

    def test_a_host_in_a_sqlite_url_is_refused(self) -> None:
        with pytest.raises(CostModelStoreError, match="host"):
            persist_cost_model(
                CostModelConfig(version="2026.09.1", venue="binance_spot"),
                "sqlite://elsewhere/db.sqlite",
            )

    def test_a_scheme_less_url_carries_no_path(self) -> None:
        with pytest.raises(CostModelStoreError, match="no database path"):
            persist_cost_model(
                CostModelConfig(version="2026.09.1", venue="binance_spot"),
                "sqlite:///",
            )

    def test_a_write_failure_is_a_store_error_not_a_silent_skip(
        self, tmp_path
    ) -> None:
        # The row is the point of the feature, so a configured-but-broken
        # store raises rather than shrugging: an unconfigured store is a
        # supported state, a broken one is not.  A regular file where the
        # store's directory must be is unwritable in a way no retry fixes,
        # which makes it the honest stand-in for a genuinely broken store.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        with pytest.raises(CostModelStoreError, match="binance_spot/2026.09.1"):
            persist_cost_model(
                CostModelConfig(version="2026.09.1", venue="binance_spot"),
                f"sqlite:///{blocker}/store.db",
            )


class TestTheServiceRunsTheSentenceInOrder:
    """load → persist → hand back, with no way to do one without the other."""

    def test_resolved_loads_persists_and_returns(
        self, document, test_database_url: str
    ) -> None:
        service = CostModelService(
            config_path=document(DOCUMENT), database_url=test_database_url
        )
        config = service.resolved()
        assert (config.venue, config.version) == ("binance_spot", "2026.09.1")
        assert rows(test_database_url), "resolved() must persist, not just load"

    def test_the_returned_identity_is_the_persisted_one(
        self, document, test_database_url: str
    ) -> None:
        # The caller evaluates against the very identity that landed — that
        # is what `resolved` returning the config buys.
        service = CostModelService(
            config_path=document(DOCUMENT), database_url=test_database_url
        )
        config = service.resolved()
        (row,) = rows(test_database_url)
        assert (row[0], row[1]) == (config.venue, config.version)

    def test_a_bad_document_writes_nothing(self, document, test_database_url: str) -> None:
        # The load is first, so its failure lands before any store is
        # touched: a misconfiguration leaves the store exactly as it was.
        from cost_model import CostModelConfigError

        service = CostModelService(
            config_path=document("cost_model:\n  venue: binance_spot\n"),
            database_url=test_database_url,
        )
        with pytest.raises(CostModelConfigError):
            service.resolved()
        # The table may exist (the reader creates the schema); the point is
        # that no row was written.
        assert rows(test_database_url) == []

    def test_the_load_does_not_re_read_the_document(
        self, document, tmp_path, test_database_url: str
    ) -> None:
        # The document is a signed Z0 artifact; re-parsing it per call would
        # let a mid-process edit change the identity a caller prices against.
        path = document(DOCUMENT)
        service = CostModelService(config_path=path, database_url=test_database_url)
        assert service.resolved().version == "2026.09.1"
        path.write_text(
            'cost_model:\n  version: "9999.9"\n  venue: tampered\n', encoding="utf-8"
        )
        assert service.resolved().version == "2026.09.1"

    def test_loading_a_new_path_replaces_the_cached_config(
        self, document, test_database_url: str
    ) -> None:
        service = CostModelService(database_url=test_database_url)
        assert service.load(document(DOCUMENT, "a.yaml")).version == "2026.09.1"
        newer = service.load(
            document(
                'cost_model:\n  version: "2027.01.1"\n  venue: binance_spot\n',
                "b.yaml",
            )
        )
        assert newer.version == "2027.01.1"

    def test_a_service_bound_to_a_config_never_reads_a_document(
        self, test_database_url: str
    ) -> None:
        resolved = CostModelConfig(version="2026.09.1", venue="binance_spot")
        service = CostModelService(resolved, database_url=test_database_url)
        assert service.load() is resolved

    def test_binding_both_a_config_and_a_path_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            CostModelService(
                CostModelConfig(version="2026.09.1", venue="binance_spot"),
                config_path="somewhere.yaml",
            )

    def test_persisting_without_a_store_names_the_variable(
        self, document, monkeypatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        service = CostModelService(config_path=document(DOCUMENT))
        with pytest.raises(CostModelStoreError, match="DATABASE_URL"):
            service.resolved()
