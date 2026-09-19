"""Feature 59, first half — the YAML configuration is loaded and resolved.

app_spec.xml, "Cost Model & Fill Simulation", feature 59: *System persists
the resolved cost model version string with its venue name after loading
the YAML configuration.*  This file pins the *loading* and *resolving*
halves; :mod:`test_persistence` pins the persisting half, and
:mod:`test_component` pins the wiring.

The tests take the feature's words one at a time, because each can fail
independently:

* **the YAML configuration** — §6.2's document, unaltered, from §6.2's own
  spelling down to the nested mapping under ``cost_model:``.  The shipped
  default is asserted to *be* that document rather than merely resemble it,
  so a default that drifted from the architecture is a red test and not a
  quiet fee change.
* **loading** — a real parse, not a subset: a document whose version is
  quoted, one that is a plain scalar mapping with no ``cost_model`` wrapper,
  and one whose values are YAML's own non-string types.  What comes back is
  the text the document carries, never a re-render of it.
* **the resolved version string with its venue name** — both, always, and
  each validated: a document missing either, or carrying a blank, a number
  or a list where one belongs, is refused by name with the offending value
  in the message.  There is no partial resolution and no default
  substitution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cost_model import (
    COST_MODEL_KEY,
    DEFAULT_COST_MODEL_PATH,
    CostModelConfig,
    CostModelConfigError,
    load_cost_model,
    read_cost_model_document,
)

# §6.2's document, as the architecture writes it.
SPEC_DOCUMENT = """
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


class TestTheShippedDefaultIsSpec6_2:
    """The packaged default is the architecture's own document."""

    def test_the_default_document_exists(self) -> None:
        assert DEFAULT_COST_MODEL_PATH.is_file()

    def test_the_default_loads_to_the_specs_version_and_venue(self) -> None:
        config = load_cost_model(DEFAULT_COST_MODEL_PATH)
        assert config.version == "2026.09.1"
        assert config.venue == "binance_spot"

    def test_loading_with_no_path_reads_the_shipped_default(self) -> None:
        # The fallback is the default document, so an unconfigured
        # deployment still resolves a cost model — §6.2's own.
        assert load_cost_model() == load_cost_model(DEFAULT_COST_MODEL_PATH)

    def test_the_default_carries_the_rest_of_the_spec_document(self) -> None:
        # Feature 59 reads only version and venue, but the shipped file is
        # §6.2's *whole* document: the features that consume the fee
        # schedule, the fill model, the latency source and the borrow source
        # read the same file, so dropping those sections here would silently
        # rob them.  Parsed through the loader's own YAML seam, so this stays
        # a statement about the file and not about a second YAML copy.
        from cost_model import require_yaml

        document = require_yaml().safe_load(
            DEFAULT_COST_MODEL_PATH.read_text(encoding="utf-8")
        )
        model = document[COST_MODEL_KEY]
        assert model["fees"]["taker_bps"] == 10.0
        assert model["fees"]["maker_bps"] == 10.0
        assert model["fees"]["discount_token"] == "BNB"
        assert model["fill_model"]["passive"]["require_trade_through"] is True
        assert model["fill_model"]["passive"]["queue_position_penalty_bps"] == 1.5
        assert (
            model["fill_model"]["passive"]["fill_probability_model"]
            == "exp_decay_vs_queue_depth"
        )
        assert model["fill_model"]["aggressive"]["walk_book"] is True
        assert model["latency"]["source"] == "measured_from_shadow"
        assert model["latency"]["distribution"] == "empirical_p50_p95_p99"
        assert model["borrow"]["source"] == "exchange_api"


class TestLoadingTheYamlConfiguration:
    """The document is parsed as YAML, and the values come back verbatim."""

    def test_a_file_is_loaded_and_resolved(self, document) -> None:
        config = load_cost_model(document(SPEC_DOCUMENT))
        assert config.version == "2026.09.1"
        assert config.venue == "binance_spot"

    def test_a_wrapperless_document_resolves(self, document) -> None:
        # An operator may hand this member a document that *is* the model
        # rather than one carrying it under a `cost_model` key.  Both
        # spellings resolve, so neither is a surprise.
        path = document('version: "2026.09.1"\nvenue: binance_spot\n')
        config = load_cost_model(path)
        assert (config.version, config.venue) == ("2026.09.1", "binance_spot")

    def test_the_wrapper_takes_precedence_over_top_level_keys(self, document) -> None:
        # A larger settings document may hold other sections beside the
        # model.  Precedence is stated, not guessed: a `cost_model` key wins,
        # so a top-level `version` belonging to something else is never
        # mistaken for the cost model's.
        path = document(
            'version: "9999.1"\nvenue: not_the_cost_model\n'
            "cost_model:\n"
            '  version: "2026.09.1"\n'
            "  venue: binance_spot\n"
        )
        config = load_cost_model(path)
        assert (config.version, config.venue) == ("2026.09.1", "binance_spot")

    def test_real_yaml_is_parsed_not_a_subset(self, document) -> None:
        # Anchors, multi-line strings and nested lists are YAML the document
        # may legitimately grow.  A hand-rolled subset would silently mean
        # something else here — which is the one failure mode a fee schedule
        # may not have.
        path = document(
            "cost_model:\n"
            '  version: "2026.09.1"\n'
            "  venue: >\n"
            "    binance_spot\n"
            "  notes: &note\n"
            "    - taker\n"
            "    - maker\n"
            "  mirrored: *note\n"
        )
        config = load_cost_model(path)
        assert config.version == "2026.09.1"
        # The folded scalar's trailing newline is stripped by the resolver,
        # not silently carried into the persisted venue.
        assert config.venue == "binance_spot"

    def test_surrounding_whitespace_is_stripped_from_the_pair(self, document) -> None:
        path = document(
            "cost_model:\n"
            '  version: "  2026.09.1  "\n'
            '  venue: "  binance_spot  "\n'
        )
        config = load_cost_model(path)
        assert config.version == "2026.09.1"
        assert config.venue == "binance_spot"

    def test_the_source_records_where_the_document_came_from(self, document) -> None:
        path = document(SPEC_DOCUMENT)
        assert load_cost_model(path).source == str(path)

    def test_an_unknown_yaml_constructor_is_refused_not_executed(
        self, document
    ) -> None:
        # The document is operator-writable where this member runs, so
        # `safe_load` is load-bearing: the arbitrary-object constructor a
        # plain `load` honours must never build a Python object named by the
        # file's content.
        path = document(
            "cost_model:\n"
            '  version: "2026.09.1"\n'
            "  venue: !!python/object/apply:os.system ['echo pwned']\n"
        )
        with pytest.raises(CostModelConfigError, match="not valid YAML"):
            load_cost_model(path)


class TestTheParsedDocumentIsReachable:
    """The parse is a seam, so a later consumer never re-reads the file.

    Feature 60 hashes *the loaded configuration* — the whole §6.2 document,
    not just the pair feature 59 resolves — and a hash taken over a fresh
    re-parse would be a hash of whatever the file says *now*.  These tests
    pin the seam that prevents that divergence.
    """

    def test_the_model_mapping_comes_back_whole(self, document) -> None:
        model, origin = read_cost_model_document(document(SPEC_DOCUMENT))
        assert origin == str(document(SPEC_DOCUMENT))
        assert model["version"] == "2026.09.1"
        assert model["venue"] == "binance_spot"
        # The sections feature 59 does not read are still there — they are
        # what a fee-schedule consumer and feature 60's hash need.
        assert model["fees"]["taker_bps"] == 10.0
        assert model["fill_model"]["passive"]["queue_position_penalty_bps"] == 1.5

    def test_the_returned_mapping_is_read_only(self, document) -> None:
        # A consumer may read the document; it may not mutate it into a
        # different configuration than the one that was loaded.
        model, _ = read_cost_model_document(document(SPEC_DOCUMENT))
        with pytest.raises(TypeError):
            model["version"] = "tampered"  # type: ignore[index]

    def test_a_nested_section_is_read_only_too(self, document) -> None:
        # The sections *are* the configuration: the fee schedule and fill
        # model are the numbers the model resolves to, and every one of
        # them lives a level below the top mapping.  A read-only wrapper
        # that stopped at the top level would let a caller rewrite the
        # schedule while a top-level test still passed.
        model, _ = read_cost_model_document(document(SPEC_DOCUMENT))
        with pytest.raises(TypeError):
            model["fees"]["taker_bps"] = 999.0  # type: ignore[index]
        with pytest.raises(TypeError):
            model["fill_model"]["passive"]["queue_position_penalty_bps"] = 0.0  # type: ignore[index]

    def test_a_nested_sequence_is_read_only_too(self, document) -> None:
        model, _ = read_cost_model_document(
            document('version: "2026.09.1"\nvenue: binance_spot\ntiers: [1, 2]\n')
        )
        # A frozen mapping holding a mutable list is only half frozen.
        assert model["tiers"] == (1, 2)
        with pytest.raises(TypeError):
            model["tiers"][0] = 9  # type: ignore[index]

    def test_a_wrapperless_document_is_also_a_whole_mapping(self, document) -> None:
        model, _ = read_cost_model_document(
            document("version: \"2026.09.1\"\nvenue: binance_spot\nnotes: hi\n")
        )
        assert model["notes"] == "hi"

    def test_the_seam_refuses_document_defects(self, document, tmp_path) -> None:
        # The seam owns *parsing* a document, so it refuses the defects that
        # make one unreadable — and deliberately not the ones that merely
        # make it an incomplete cost model.  A mapping missing `version`
        # parses perfectly well; refusing it is the *resolve* step's job
        # (pinned in TestRefusingABadDocument), and conflating the two here
        # would mean a consumer that only wants the fee schedule had to
        # supply an identity to read it.
        with pytest.raises(CostModelConfigError, match="not valid YAML"):
            read_cost_model_document(document("cost_model: [unclosed\n"))
        with pytest.raises(CostModelConfigError, match="could not read"):
            read_cost_model_document(tmp_path / "absent.yaml")

    def test_an_incomplete_model_still_parses(self, document) -> None:
        # The other half of the division above, stated positively.
        model, _ = read_cost_model_document(
            document("cost_model:\n  venue: binance_spot\n")
        )
        assert model["venue"] == "binance_spot"
        assert "version" not in model

    def test_loading_reads_the_document_once(
        self, document, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The load resolves the pair from the same parse it hands back, so a
        # file edited between the two cannot make the identity and the
        # configuration disagree.
        from cost_model import config as config_module

        path = document(SPEC_DOCUMENT)
        real_read = Path.read_text
        reads = []

        def counting_read(self, *args, **kwargs):
            if self == path:
                reads.append(self)
            return real_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", counting_read)
        config = config_module.load_cost_model(path)
        assert config.version == "2026.09.1"
        assert len(reads) == 1, f"expected one read, saw {len(reads)}"


class TestResolvingThePair:
    """"Resolved" is a validated value, not a string that happened to load."""

    def test_the_reference_pairs_the_venue_with_the_version(self) -> None:
        # Feature 59 persists the version *with* its venue, so the pairing is
        # spelled once and every consumer reads the same one.
        config = CostModelConfig(version="2026.09.1", venue="binance_spot")
        assert config.reference == "binance_spot/2026.09.1"
        assert str(config) == "binance_spot/2026.09.1"

    def test_the_pair_is_the_identity_but_the_source_is_not(self) -> None:
        # Provenance is recorded beside the identity and takes no part in it:
        # the same document loaded from two deployments is one cost model.
        one = CostModelConfig(version="2026.09.1", venue="binance_spot", source="/a")
        two = CostModelConfig(
            version="2026.09.1", venue="binance_spot", source="/b/elsewhere.yaml"
        )
        assert one.version == two.version and one.venue == two.venue

    def test_a_config_is_frozen(self) -> None:
        config = CostModelConfig(version="2026.09.1", venue="binance_spot")
        with pytest.raises(Exception):
            config.version = "2026.09.2"  # type: ignore[misc]

    @pytest.mark.parametrize("key", ["version", "venue"])
    def test_a_blank_component_is_refused(self, key: str) -> None:
        components = {"version": "2026.09.1", "venue": "binance_spot"}
        components[key] = "   "
        with pytest.raises(CostModelConfigError, match=key):
            CostModelConfig(**components)  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", [202609, 1.5, ["2026.09.1"], {"a": 1}, True])
    def test_a_non_string_component_is_refused(self, value) -> None:
        # A bare `version: 1.0` is a YAML float and `str(1.0)` is not a
        # spelling any human wrote, so a non-string is refused with the fix
        # (quote it) rather than re-rendered into a version nobody authored.
        with pytest.raises(CostModelConfigError, match="must be a string"):
            CostModelConfig(version=value, venue="binance_spot")  # type: ignore[arg-type]

    def test_a_numeric_version_in_the_document_is_refused_with_the_fix(
        self, document
    ) -> None:
        path = document("cost_model:\n  version: 1.0\n  venue: binance_spot\n")
        with pytest.raises(CostModelConfigError, match="quote it"):
            load_cost_model(path)


class TestRefusingABadDocument:
    """Every refusal names the offending value and the contract it broke."""

    @pytest.mark.parametrize("key", ["version", "venue"])
    def test_a_missing_component_is_refused_by_name(self, document, key: str) -> None:
        lines = {"version": '  version: "2026.09.1"', "venue": "  venue: binance_spot"}
        body = "\n".join(v for k, v in lines.items() if k != key)
        path = document(f"cost_model:\n{body}\n")
        with pytest.raises(CostModelConfigError, match=key):
            load_cost_model(path)

    def test_a_missing_file_is_refused_with_the_path(self, tmp_path) -> None:
        missing = tmp_path / "no-such-document.yaml"
        with pytest.raises(CostModelConfigError, match="no-such-document"):
            load_cost_model(missing)

    def test_an_empty_document_is_refused(self, document) -> None:
        with pytest.raises(CostModelConfigError, match="empty"):
            load_cost_model(document(""))

    def test_malformed_yaml_is_refused(self, document) -> None:
        with pytest.raises(CostModelConfigError, match="not valid YAML"):
            load_cost_model(document("cost_model:\n  version: [unclosed\n"))

    def test_a_document_that_is_not_a_mapping_is_refused(self, document) -> None:
        with pytest.raises(CostModelConfigError, match="not a cost model document"):
            load_cost_model(document("- just\n- a\n- list\n"))

    def test_a_non_mapping_wrapper_is_refused(self, document) -> None:
        with pytest.raises(CostModelConfigError, match=COST_MODEL_KEY):
            load_cost_model(document("cost_model: 42\n"))

    def test_the_failure_is_both_a_value_error_and_a_cost_model_error(
        self, document
    ) -> None:
        # Dual-inherited on purpose: a bad document is a ValueError the way
        # every config-validation failure in this workspace is, and a
        # CostModelError the way every failure of this package is, so either
        # `except` clause catches it.
        path = document("cost_model:\n  venue: binance_spot\n")
        with pytest.raises(ValueError):
            load_cost_model(path)
        with pytest.raises(Exception) as caught:
            load_cost_model(path)
        from cost_model import CostModelError

        assert isinstance(caught.value, CostModelError)


class TestTheYamlDependencyIsDeferred:
    """PyYAML is needed to parse, and its absence is an environment problem."""

    def test_require_yaml_returns_the_module(self) -> None:
        from cost_model import require_yaml

        assert require_yaml().safe_load("a: 1") == {"a": 1}

    def test_a_missing_yaml_names_the_fix(self, monkeypatch) -> None:
        # A missing *parser* is not a malformed document: it is
        # ModuleNotFoundError naming the dependency, so a caller never reads
        # an environment problem as a corrupt signed artifact.
        import builtins

        from cost_model import config as config_module

        real_import = builtins.__import__

        def refuse_yaml(name, *args, **kwargs):
            if name == "yaml":
                raise ModuleNotFoundError("No module named 'yaml'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse_yaml)
        monkeypatch.delitem(__import__("sys").modules, "yaml", raising=False)
        with pytest.raises(ModuleNotFoundError, match="PyYAML"):
            config_module.require_yaml()
