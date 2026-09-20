"""Feature 60 — ``cost_model_hash`` over the loaded configuration.

app_spec.xml feature 60: *System persists ``cost_model_hash`` computed over
the loaded configuration, so every score names its fee assumptions.*  This
file pins the formula (:mod:`cost_model.identity`), the value the loader
carries and the column the store writes; :mod:`test_config` pins feature
59's loading half and :mod:`test_persistence` its persist half.

The sentence has three separable claims, each able to fail on its own:

* **computed over the loaded configuration** — the hash names the *bytes*,
  not the label.  The pair feature 59 persists is a string its author chose;
  two documents can carry the same ``(venue, version)`` and price
  differently, and the whole point of the hash is to notice.  So the tests
  that matter most here are the ones where the pair is held *constant* and a
  rate moves.
* **persists** — the row really lands in the store, read back through a
  second connection so the assertion is about what is on disk rather than
  about a value the write happened to return.
* **so every score names its fee assumptions** — the persisted hash is what
  a reader resolves against, and a row that names none is refused rather
  than served.

The formula is also pinned against the two sibling formulas in the
workspace (``snapshot._identity``, ``evaluator._identity``): same sha256,
same 64-hex spelling, same lowercase normalization — one identity convention
across §14.1's triple, so a log line naming all three abbreviates each the
same way.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing

import pytest

from cost_model import (
    COST_MODEL_HASH_COLUMN,
    COST_MODEL_HASH_LENGTH,
    COST_MODEL_TABLE,
    CostModelConfig,
    CostModelConfigError,
    CostModelService,
    CostModelStoreError,
    canonical_cost_model,
    cost_model_digest,
    load_cost_model,
    load_persisted_cost_model,
    normalize_cost_model_hash,
    persist_cost_model,
)
from cost_model.store import connect

# §6.2's document, as the architecture writes it (see cost_model.yaml).
DOCUMENT = """
cost_model:
  version: "2026.09.1"
  venue: binance_spot
  fees:
    taker_bps: 10.0
    maker_bps: 10.0
    discount_token: BNB
  fill_model:
    passive:
      require_trade_through: true
      queue_position_penalty_bps: 1.5
      fill_probability_model: exp_decay_vs_queue_depth
    aggressive:
      walk_book: true
  latency:
    source: measured_from_shadow
    distribution: empirical_p50_p95_p99
  borrow:
    source: exchange_api
"""


def rows(database_url: str) -> list[tuple]:
    """Every row of the table, straight from the store.

    A raw read on a fresh connection, so an assertion is about the bytes on
    disk rather than about the writer's return value.
    """
    with closing(connect(database_url)) as connection:
        return connection.execute(
            f"SELECT venue, version, source, resolved_at, {COST_MODEL_HASH_COLUMN}"
            f" FROM {COST_MODEL_TABLE}"
        ).fetchall()


class TestTheFormula:
    """What the hash is over, and the byte-level spelling of that."""

    def test_it_is_a_sha256_hex_digest(self, document) -> None:
        # The spec's column is CHAR(64); the value must be exactly that,
        # lowercase, matching the sibling evaluator_hash and snapshot_hash.
        digest = load_cost_model(document(DOCUMENT)).hash
        assert len(digest) == COST_MODEL_HASH_LENGTH == 64
        assert digest == digest.lower()
        assert set(digest) <= set("0123456789abcdef")

    def test_it_is_the_sha256_of_the_canonical_spelling(self, document) -> None:
        # The formula stated literally, so the preimage is not a private
        # detail of the implementation: sha256 of the canonical JSON, UTF-8.
        config = load_cost_model(document(DOCUMENT))
        expected = hashlib.sha256(
            canonical_cost_model(config.document).encode("utf-8")
        ).hexdigest()
        assert config.hash == expected == cost_model_digest(config.document)

    def test_the_same_configuration_hashes_the_same_anywhere(self, document) -> None:
        # Determinism is what lets a stored row be checked against a score's
        # stamp at all: same bytes, same value, in any process.
        first = load_cost_model(document(DOCUMENT, "one.yaml"))
        second = load_cost_model(document(DOCUMENT, "two.yaml"))
        assert first.hash == second.hash

    def test_a_different_fee_rate_is_a_different_hash(self, document) -> None:
        # The claim the feature exists for: the pair is the *label*, and the
        # hash is what notices that two documents sharing a label priced
        # differently.  Version and venue are held constant on purpose.
        base = load_cost_model(document(DOCUMENT, "a.yaml"))
        repriced = load_cost_model(
            document(DOCUMENT.replace("taker_bps: 10.0", "taker_bps: 12.5"), "b.yaml")
        )
        assert (repriced.venue, repriced.version) == (base.venue, base.version)
        assert repriced.hash != base.hash

    @pytest.mark.parametrize(
        "edit",
        [
            "maker_bps: 10.0",
            "discount_token: BNB",
            "queue_position_penalty_bps: 1.5",
            "walk_book: true",
            "require_trade_through: true",
            "fill_probability_model: exp_decay_vs_queue_depth",
            "source: measured_from_shadow",
            "distribution: empirical_p50_p95_p99",
            "source: exchange_api",
        ],
    )
    def test_every_section_is_inside_the_hash(self, document, edit: str) -> None:
        # "the loaded configuration" is the whole §6.2 document, not the fee
        # block: the fill model and the latency and borrow sources change
        # what a post-cost return means just as much as a basis point does.
        base = load_cost_model(document(DOCUMENT, "a.yaml"))
        changed = load_cost_model(
            document(DOCUMENT.replace(edit, ""), "b.yaml")
        )
        assert changed.hash != base.hash

    def test_the_pair_itself_is_inside_the_hash(self, document) -> None:
        # The hash covers the labels too, so a score's stamp changes when the
        # cost model is renamed — which is why the pair is *one of* the
        # things the hash pins rather than all of it.
        base = load_cost_model(document(DOCUMENT, "a.yaml"))
        renamed = load_cost_model(
            document(
                DOCUMENT.replace("venue: binance_spot", "venue: kraken_spot"),
                "b.yaml",
            )
        )
        assert renamed.hash != base.hash


class TestTheCanonicalSpelling:
    """Two documents that mean one configuration produce one hash."""

    def test_key_order_does_not_matter(self, document) -> None:
        base = load_cost_model(document(DOCUMENT, "a.yaml"))
        reordered = load_cost_model(
            document(
                "cost_model:\n"
                "  venue: binance_spot\n"
                "  version: \"2026.09.1\"\n"
                "  fees:\n"
                "    maker_bps: 10.0\n"
                "    taker_bps: 10.0\n"
                "    discount_token: BNB\n"
                "  fill_model:\n"
                "    passive:\n"
                "      queue_position_penalty_bps: 1.5\n"
                "      require_trade_through: true\n"
                "      fill_probability_model: exp_decay_vs_queue_depth\n"
                "    aggressive:\n"
                "      walk_book: true\n"
                "  latency:\n"
                "    distribution: empirical_p50_p95_p99\n"
                "    source: measured_from_shadow\n"
                "  borrow:\n"
                "    source: exchange_api\n",
                "b.yaml",
            )
        )
        assert reordered.hash == base.hash

    def test_comments_and_whitespace_do_not_matter(self, document) -> None:
        # A hash that read the file's *text* would move when someone
        # annotated a signed artifact.  YAML discards comments before the
        # model exists, so they never reach the formula.
        base = load_cost_model(document(DOCUMENT, "a.yaml"))
        annotated = load_cost_model(
            document(
                "# an operator's note\n" + DOCUMENT.replace("  venue:", "\n  venue:"),
                "b.yaml",
            )
        )
        assert annotated.hash == base.hash

    def test_the_outer_cost_model_wrapper_is_not_part_of_the_hash(
        self, document
    ) -> None:
        # A larger settings file that *wraps* the model under ``cost_model:``
        # is the same cost model as a bare document carrying those bytes.
        # Folding the wrapper's other sections in would move the hash for
        # reasons that have nothing to do with fees.
        bare = load_cost_model(
            document(DOCUMENT.replace("cost_model:\n", ""), "bare.yaml")
        )
        wrapped = load_cost_model(
            document(
                DOCUMENT.replace("cost_model:", "other_section: 1\ncost_model:"),
                "wrapped.yaml",
            )
        )
        assert bare.hash == wrapped.hash

    def test_the_canonical_spelling_is_printable(self, document) -> None:
        # A hash whose preimage cannot be printed is a hash nobody can debug:
        # an operator asking "why did this score's stamp move" needs to see
        # the two spellings that differ.
        base = load_cost_model(document(DOCUMENT, "a.yaml"))
        spelled = canonical_cost_model(base.document)
        assert json.loads(spelled)["version"] == "2026.09.1"
        assert " " not in spelled.replace('"2026.09.1"', "")
        assert "\n" not in spelled


class TestTheFormulaRefusesWhatItCannotPin:
    """A value JSON cannot carry is a value the hash cannot pin."""

    def test_a_non_finite_rate_is_refused(self, document) -> None:
        # `json.dumps` renders NaN as the non-JSON token `NaN`, and NaN is
        # not even equal to itself — a fee that cannot be compared to its own
        # reload is not a pinned configuration.
        path = document(
            'cost_model:\n  version: "2026.09.1"\n  venue: binance_spot\n'
            "  fees:\n    taker_bps: .nan\n"
        )
        with pytest.raises(CostModelConfigError, match="non-finite"):
            load_cost_model(path)

    def test_the_refusal_names_the_offending_path(self, document) -> None:
        path = document(
            'cost_model:\n  version: "2026.09.1"\n  venue: binance_spot\n'
            "  fees:\n    taker_bps: .inf\n"
        )
        with pytest.raises(CostModelConfigError, match="fees.taker_bps"):
            load_cost_model(path)

    def test_a_non_string_key_is_refused(self, document) -> None:
        # YAML reads `1: x` as an integer key, and a mapping keyed half by
        # strings and half by integers cannot be sorted at all.
        path = document(
            'cost_model:\n  version: "2026.09.1"\n  venue: binance_spot\n'
            "  fees:\n    1: x\n"
        )
        with pytest.raises(CostModelConfigError, match="non-empty string"):
            load_cost_model(path)

    def test_a_value_json_has_no_form_for_is_refused(self, document) -> None:
        # A `!!binary` blob is `bytes`; JSON has no scalar for it, and
        # pinning "something" in its place would be a hash over bytes nobody
        # can reproduce.  The fix is quoted in the message.
        path = document(
            'cost_model:\n  version: "2026.09.1"\n  venue: binance_spot\n'
            "  fees:\n    taker_bps: !!binary aGk=\n"
        )
        with pytest.raises(CostModelConfigError, match="quote it"):
            load_cost_model(path)


class TestNormalizingAPersistedHash:
    """The one place the 64-hex spelling is enforced."""

    def test_case_is_normalized_not_refused(self) -> None:
        # A hash pasted from a database, a log line or a report is commonly
        # uppercase and means the same value.
        digest = "a" * 64
        assert normalize_cost_model_hash(digest.upper()) == digest

    def test_an_image_digest_is_refused(self) -> None:
        # `sha256:<hex>` belongs to an image reference; accepting it here
        # would let a caller compare a digest against a hash and get
        # "different" for the wrong reason.
        with pytest.raises(CostModelConfigError, match="algorithm prefix"):
            normalize_cost_model_hash("sha256:" + "a" * 64)

    def test_a_short_hash_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="64 hex"):
            normalize_cost_model_hash("abc123")

    def test_a_non_hex_token_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="64 hex"):
            normalize_cost_model_hash("z" * 64)

    def test_a_non_string_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="must be a"):
            normalize_cost_model_hash(42)  # type: ignore[arg-type]


class TestTheLoadedConfigCarriesTheHash:
    """The loader folds the hash from the same parse it resolved the pair from."""

    def test_loading_attaches_a_hash(self, document) -> None:
        config = load_cost_model(document(DOCUMENT))
        assert config.hash
        assert config.hash == cost_model_digest(config.document)

    def test_the_hash_prefix_is_the_first_six_characters(self, document) -> None:
        config = load_cost_model(document(DOCUMENT))
        assert config.hash_prefix == config.hash[:6]

    def test_the_config_carries_the_document_it_hashed(self, document) -> None:
        # Keeping the document is what makes the hash honest: it is the very
        # mapping the pair was resolved from, not a re-read of the file.
        config = load_cost_model(document(DOCUMENT))
        assert config.document is not None
        assert config.document["fees"]["taker_bps"] == 10.0

    def test_a_hash_disagreeing_with_its_own_document_is_refused(
        self, document
    ) -> None:
        # An instance whose hash disagrees with its own document would
        # persist a row naming a configuration it does not describe.
        loaded = load_cost_model(document(DOCUMENT))
        with pytest.raises(CostModelConfigError, match="does not match"):
            CostModelConfig(
                version=loaded.version,
                venue=loaded.venue,
                hash="0" * 64,
                document=loaded.document,
            )

    def test_a_supplied_hash_that_agrees_is_accepted(self, document) -> None:
        loaded = load_cost_model(document(DOCUMENT))
        rebuilt = CostModelConfig(
            version=loaded.version,
            venue=loaded.venue,
            hash=loaded.hash.upper(),
            document=loaded.document,
        )
        assert rebuilt.hash == loaded.hash

    def test_two_configs_are_the_same_cost_model_by_hash_not_by_pair(
        self, document
    ) -> None:
        base = load_cost_model(document(DOCUMENT, "a.yaml"))
        repriced = load_cost_model(
            document(DOCUMENT.replace("taker_bps: 10.0", "taker_bps: 12.5"), "b.yaml")
        )
        assert base.reference == repriced.reference
        assert not base.describes_same_cost_model(repriced)
        assert base.describes_same_cost_model(
            load_cost_model(document(DOCUMENT, "c.yaml"))
        )

    def test_a_pair_with_no_hash_cannot_be_compared(self) -> None:
        # Two empty hashes are equal, so comparing them would report two
        # hand-built pairs as *the same cost model* on the strength of both
        # having named nothing — the exact false match the hash prevents.
        pair = CostModelConfig(version="2026.09.1", venue="binance_spot")
        with pytest.raises(CostModelConfigError, match="no cost_model_hash"):
            pair.describes_same_cost_model(pair)

    def test_a_pair_with_no_hash_has_no_prefix(self) -> None:
        pair = CostModelConfig(version="2026.09.1", venue="binance_spot")
        with pytest.raises(CostModelConfigError, match="no cost_model_hash"):
            _ = pair.hash_prefix

    def test_a_pair_is_still_a_legitimate_value(self) -> None:
        # Feature 59's value, and what a service is handed for a config it
        # resolved elsewhere: the requirement is on the *row*, not the value.
        pair = CostModelConfig(version="2026.09.1", venue="binance_spot")
        assert pair.reference == "binance_spot/2026.09.1"
        assert pair.hash == ""


class TestTheHashIsPersisted:
    """Feature 60's verb, against the bytes on disk."""

    def test_a_loaded_config_lands_its_hash(
        self, document, test_database_url: str
    ) -> None:
        config = load_cost_model(document(DOCUMENT))
        persist_cost_model(config, test_database_url)
        (row,) = rows(test_database_url)
        assert row[4] == config.hash

    def test_the_persisted_hash_is_the_loaded_hash(
        self, document, test_database_url: str
    ) -> None:
        loaded = load_cost_model(document(DOCUMENT))
        persist_cost_model(loaded, test_database_url)
        back = load_persisted_cost_model(
            loaded.venue, loaded.version, test_database_url
        )
        assert back is not None
        assert back.hash == loaded.hash

    def test_the_round_trip_is_lossless(self, document, test_database_url: str) -> None:
        loaded = load_cost_model(document(DOCUMENT))
        persist_cost_model(loaded, test_database_url)
        back = load_persisted_cost_model(
            loaded.venue, loaded.version, test_database_url
        )
        assert back == loaded

    def test_a_bare_pair_is_refused_rather_than_written(
        self, test_database_url: str
    ) -> None:
        # Feature 60's sentence is about the *row*: a row naming no fee
        # assumptions is one a later reader could resolve a score against and
        # learn nothing.
        with pytest.raises(CostModelStoreError, match="cost_model_hash"):
            persist_cost_model(
                CostModelConfig(version="2026.09.1", venue="binance_spot"),
                test_database_url,
            )

    def test_the_refusal_leaves_the_store_untouched(
        self, document, test_database_url: str
    ) -> None:
        with pytest.raises(CostModelStoreError):
            persist_cost_model(
                CostModelConfig(version="2026.09.1", venue="binance_spot"),
                test_database_url,
            )
        assert rows(test_database_url) == []


class TestRepricingARowWithoutAVersionBump:
    """The case the pair-as-key alone would hide."""

    def test_the_hash_column_moves_under_a_constant_pair(
        self, document, test_database_url: str
    ) -> None:
        # A rate edited without a version bump: the row is *the same* cost
        # model by label, and the hash column is how a reader sees that the
        # fee assumptions under it moved.  Upserting onto one row is
        # deliberate — a second row beside it would leave scores pointing at
        # the stale one.
        persist_cost_model(
            load_cost_model(document(DOCUMENT, "a.yaml")), test_database_url
        )
        first = rows(test_database_url)[0][4]
        persist_cost_model(
            load_cost_model(
                document(
                    DOCUMENT.replace("taker_bps: 10.0", "taker_bps: 12.5"),
                    "b.yaml",
                )
            ),
            test_database_url,
        )
        (row,) = rows(test_database_url)
        assert row[4] != first
        assert (row[0], row[1]) == ("binance_spot", "2026.09.1")

    def test_reloading_the_same_artifact_leaves_one_unchanged_row(
        self, document, test_database_url: str
    ) -> None:
        path = document(DOCUMENT)
        for _ in range(3):
            persist_cost_model(load_cost_model(path), test_database_url)
        (row,) = rows(test_database_url)
        assert row[4] == load_cost_model(path).hash


class TestALegacyRowIsRefusedRatherThanInvented:
    """A row written before feature 60 has no hash to serve."""

    @staticmethod
    def _legacy_store(database_url: str) -> None:
        """Write feature 59's three-column row, bypassing the current writer."""
        with closing(connect(database_url)) as connection, connection:
            connection.execute(
                f"""
                INSERT INTO {COST_MODEL_TABLE} (
                    venue, version, source, resolved_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    "binance_spot",
                    "2026.09.1",
                    "/z0/legacy.yaml",
                    "2026-01-01T00:00:00+00:00",
                ),
            )

    def test_the_schema_upgrade_adds_the_column(self, test_database_url: str) -> None:
        # `CREATE TABLE IF NOT EXISTS` cannot evolve an existing table, so a
        # database written by feature 59's schema is brought forward in place
        # — a schema change, not a rewrite of any recorded value.
        self._legacy_store(test_database_url)
        with closing(connect(test_database_url)) as connection:
            columns = {
                row[1]
                for row in connection.execute(f"PRAGMA table_info({COST_MODEL_TABLE})")
            }
        assert COST_MODEL_HASH_COLUMN in columns

    def test_reading_a_legacy_row_is_refused_with_the_recovery(
        self, test_database_url: str
    ) -> None:
        # A plausible-looking hash would be a lie, and `None` would be
        # another (the cost model *is* there) — so the reader names the row
        # and the one-step fix.
        self._legacy_store(test_database_url)
        with pytest.raises(CostModelStoreError, match="predates feature 60"):
            load_persisted_cost_model("binance_spot", "2026.09.1", test_database_url)

    def test_reloading_the_artifact_stamps_the_legacy_row(
        self, document, test_database_url: str
    ) -> None:
        # The recovery the refusal names: the upsert is keyed on the pair, so
        # re-loading the signed artifact fills the column in place.
        self._legacy_store(test_database_url)
        loaded = load_cost_model(document(DOCUMENT))
        persist_cost_model(loaded, test_database_url)
        (row,) = rows(test_database_url)
        assert row[4] == loaded.hash
        back = load_persisted_cost_model("binance_spot", "2026.09.1", test_database_url)
        assert back is not None and back.hash == loaded.hash

    def test_a_legacy_row_for_another_pair_does_not_hide_the_miss(
        self, test_database_url: str
    ) -> None:
        # The refusal is about the row that was found, not about the table:
        # an absent cost model is still the honest ``None``.
        self._legacy_store(test_database_url)
        assert (
            load_persisted_cost_model("kraken_spot", "2026.09.1", test_database_url)
            is None
        )


class TestTheServicePinsAndPersistsTheHash:
    """The composed door a caller reaches feature 60 through."""

    def test_the_service_resolves_the_hash(self, document) -> None:
        service = CostModelService(config_path=document(DOCUMENT))
        assert service.cost_model_hash() == load_cost_model(
            document(DOCUMENT, "again.yaml")
        ).hash

    def test_resolved_persists_the_hash_not_just_the_pair(
        self, document, test_database_url: str
    ) -> None:
        service = CostModelService(
            config_path=document(DOCUMENT), database_url=test_database_url
        )
        config = service.resolved()
        (row,) = rows(test_database_url)
        assert row[4] == config.hash

    def test_the_hash_is_the_one_the_document_produced(
        self, document, test_database_url: str
    ) -> None:
        # The value the caller holds, the value that landed, and the value
        # the document folds to are one value — the ordering `resolved`
        # exists to guarantee.
        service = CostModelService(
            config_path=document(DOCUMENT), database_url=test_database_url
        )
        assert service.resolved().hash == service.cost_model_hash() == rows(
            test_database_url
        )[0][4]

    def test_the_service_reads_back_the_hash(
        self, document, test_database_url: str
    ) -> None:
        service = CostModelService(
            config_path=document(DOCUMENT), database_url=test_database_url
        )
        service.resolved()
        back = service.persisted("binance_spot", "2026.09.1")
        assert back is not None and back.hash == service.cost_model_hash()

    def test_the_hash_is_folded_from_the_one_parse(self, document, monkeypatch) -> None:
        # A second parse would be a hash of whatever the file says *now* —
        # the divergence the provenance triple exists to catch.
        path = document(DOCUMENT)
        service = CostModelService(config_path=path)
        digest = service.cost_model_hash()
        path.write_text(
            'cost_model:\n  version: "9999.9"\n  venue: tampered\n', encoding="utf-8"
        )
        assert service.cost_model_hash() == digest

    def test_the_document_property_is_the_hashed_parse(self, document) -> None:
        # The service's other section readers (the fill models) read the very
        # mapping the hash covers, not a re-read of the file.
        service = CostModelService(config_path=document(DOCUMENT))
        digest = service.cost_model_hash()
        assert cost_model_digest(service.document) == digest

    def test_a_service_bound_to_a_bare_pair_refuses_to_stamp(self) -> None:
        # This is the door a caller stamping a score reaches for, and an
        # empty string is the one answer that would look like a stamp: a
        # caller that got it would write a score naming no fee assumptions.
        service = CostModelService(
            CostModelConfig(version="2026.09.1", venue="binance_spot")
        )
        with pytest.raises(CostModelConfigError, match="no cost_model_hash"):
            service.cost_model_hash()
