"""``contract_version`` — feature 15 of app_spec.xml.

"System versions the signal ABI with a ``contract_version`` constant that
every stored node persists alongside its code hash."

The sentence has two halves, and the suite pins both:

* **the constant versions the signal ABI.**  There is exactly one definition of
  the number, and it lives in ``contract`` next to the ABI it versions — the
  entrypoint the sandbox executes, the window the signal is handed, the shape
  the return must have.  So the tests below check that the stamp *resolves to
  that ABI* (:func:`describe_contract_version`) rather than merely being a
  string, and that reading it through any of the accessors gives the same
  answer.
* **every stored node persists it alongside its code hash.**  This is the half
  that is easy to declare and easy to get wrong, because the failure is
  invisible: a row with a code hash and no stamp looks like a row with a code
  hash, and nothing downstream notices until two nodes written against
  different ABIs are compared as if they were commensurable.  So the tests
  drive a real persist/read round trip through the mapping a writer hands to
  storage, and refuse to let either field go missing.

What the suite deliberately does **not** test is what happens to a stale node.
The ``node`` table, its columns and its migrations are features 97-102; the
writer that persists a row belongs to them, and no code in ``discovery/``
exists yet.  Feature 15's job is the stamp and the check, so
:func:`compare` is pinned as a *value* — ``compatible`` / ``stale`` /
``malformed`` — and the suite asserts it never raises, because an audit over a
five-month-old tree has to describe a bad row rather than abort on it.

The one place a raise *is* required is the writer's boundary
(:class:`NodeAbiRecord`): a writer that persists an unreadable stamp has
recorded provenance nobody can ever check, and it is the last caller who can
still do something about that.  Both directions are pinned below.
"""

from __future__ import annotations

import contract
import pytest

from contract import (
    CONTRACT_VERSION,
    CONTRACT_VERSION_FIELD,
    NODE_ABI_RECORD_FIELDS,
    Compatibility,
    ContractVersionError,
    NodeAbiRecord,
    compare,
    contract_version,
    describe_contract_version,
    node_abi_record,
    parse_contract_version,
    read_node_abi_record,
    require_supported_contract_version,
)

CODE_HASH = "a3f1" * 16  # 64 hex characters, the shape feature 98's column takes


# --------------------------------------------------------------------------
# The constant versions *this* ABI
# --------------------------------------------------------------------------


def test_the_stamp_is_declared_beside_the_abi_it_versions():
    # One definition of the number, in the package the ABI lives in. A second
    # copy is how a persisted node's stamp drifts from the code it describes.
    assert contract.CONTRACT_VERSION == CONTRACT_VERSION == "0.1.0"
    assert contract_version() == CONTRACT_VERSION


def test_the_stamp_resolves_to_the_abi_it_declares():
    # A version string on its own is uninterpretable: it says a node was
    # written against "0.1.0" without saying what "0.1.0" was. The record
    # names the pieces the ABI is actually made of, so a run can be read back
    # after the fact from data rather than from a git checkout.
    described = describe_contract_version()
    assert described["contract_version"] == CONTRACT_VERSION
    assert described["market_window"] == contract.MARKET_WINDOW_ABI == "contract:MarketWindow"
    assert described["entrypoint"] == contract.SIGNAL_ENTRYPOINT == "signal"


def test_the_field_name_is_the_one_the_composed_component_already_advertises():
    # The writer's column and the factory's record name the same fact the same
    # way, so nothing has to translate at a boundary and nothing can drift.
    from app.module_loader import create_app

    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "packages" / "contract" / "src"
    component = create_app(src).get("contract")
    assert CONTRACT_VERSION_FIELD in component
    assert component[CONTRACT_VERSION_FIELD] == CONTRACT_VERSION
    assert NODE_ABI_RECORD_FIELDS == (CONTRACT_VERSION_FIELD, "code_hash")


# --------------------------------------------------------------------------
# Reading a stored node's stamp
# --------------------------------------------------------------------------


def test_the_record_carries_the_stamp_beside_the_code_hash():
    record = node_abi_record(code_hash=CODE_HASH)
    assert record.contract_version == CONTRACT_VERSION
    assert record.code_hash == CODE_HASH
    # The mapping a writer persists, keyed by the spellings storage uses.
    assert record.as_dict() == {
        CONTRACT_VERSION_FIELD: CONTRACT_VERSION,
        "code_hash": CODE_HASH,
    }


def test_a_persisted_record_reads_back_as_what_was_written():
    # The round trip through the plain mapping: this is the whole of "every
    # stored node persists it alongside its code hash" as far as this feature
    # can pin it — the pair goes in, and the same pair comes back.
    written = node_abi_record(code_hash=CODE_HASH).as_dict()
    read = read_node_abi_record(written)
    assert read == NodeAbiRecord(CONTRACT_VERSION, CODE_HASH)
    assert read.as_dict() == written


def test_a_record_missing_either_half_is_refused_by_name():
    # Both halves are required, and the failure names the missing field rather
    # than surfacing later as an unexplained KeyError inside a comparison loop.
    with pytest.raises(KeyError, match="code_hash"):
        read_node_abi_record({CONTRACT_VERSION_FIELD: CONTRACT_VERSION})
    with pytest.raises(KeyError, match=CONTRACT_VERSION_FIELD):
        read_node_abi_record({"code_hash": CODE_HASH})


def test_a_record_that_is_not_a_mapping_is_refused_by_type():
    with pytest.raises(TypeError, match="mapping"):
        read_node_abi_record("0.1.0/abc123")


def test_a_null_column_reads_as_a_row_carrying_no_pair():
    # A NULL stamp is the ordinary state of a row written before the stamp
    # existed, or by a writer whose column defaults to NULL — not a
    # programming error. It is reported as "this row does not carry the pair",
    # name by name, rather than escaping as a bare ContractVersionError about
    # a version string; `compare` is the tolerant answer for exactly this row.
    with pytest.raises(KeyError, match=CONTRACT_VERSION_FIELD):
        read_node_abi_record({CONTRACT_VERSION_FIELD: None, "code_hash": CODE_HASH})
    with pytest.raises(KeyError, match="code_hash"):
        read_node_abi_record({CONTRACT_VERSION_FIELD: CONTRACT_VERSION, "code_hash": None})
    # The same row the strict reader refuses is the one `compare` describes.
    assert compare(None).status == "malformed"


def test_the_record_can_carry_a_deliberately_older_stamp():
    # A migration re-stamping rows, or a backfill of a node executed by an
    # older build, names the version explicitly rather than claiming to be
    # current — the default is the running ABI, not the only option.
    record = node_abi_record(code_hash=CODE_HASH, contract_version="0.0.9")
    assert record.contract_version == "0.0.9"
    assert record.compatibility().status == "stale"
    assert record.compatibility().direction == "older"


def test_omitting_the_stamp_defaults_but_an_empty_one_does_not():
    # "I did not name a version" and "I named an empty one" are different
    # statements. An `or` here would collapse them and silently stamp the
    # running ABI onto a caller who passed "" — the quietly-uncheckable
    # provenance this module exists to refuse. The default fires on None
    # alone; an empty explicit stamp is refused, by name.
    assert node_abi_record(code_hash=CODE_HASH, contract_version=None).contract_version == (
        CONTRACT_VERSION
    )
    with pytest.raises(ContractVersionError, match="empty"):
        node_abi_record(code_hash=CODE_HASH, contract_version="")


def test_the_window_is_accepted_for_call_site_clarity_and_read_for_nothing():
    # A caller holding the window it just ran should be able to say so rather
    # than reconstruct the fact from the clock. Nothing is read off it: the
    # ABI version belongs to the code, not to the data.
    from datetime import datetime, timezone

    from contract import MarketWindow

    window = MarketWindow(t=datetime(2026, 9, 1, tzinfo=timezone.utc), universe=("BTCUSDT",))
    assert node_abi_record(window, code_hash=CODE_HASH) == NodeAbiRecord(
        CONTRACT_VERSION, CODE_HASH
    )


# --------------------------------------------------------------------------
# The stamp is a readable, orderable version
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [("0.1.0", (0, 1, 0)), ("1", (1,)), ("2.3", (2, 3)), (" 1.0.0 ", (1, 0, 0))],
)
def test_a_stamp_parses_into_its_numeric_components(stamp, expected):
    assert parse_contract_version(stamp) == expected


def test_components_compare_numerically_not_lexically():
    # The reason the parse exists at all: "0.10.0" orders after "0.9.0", which
    # a string comparison would get backwards and hide.
    assert parse_contract_version("0.10.0") > parse_contract_version("0.9.0")
    assert compare("0.10.0", current="0.9.0").direction == "newer"
    assert compare("0.9.0", current="0.10.0").direction == "older"


@pytest.mark.parametrize("stamp", ["", "  ", "v1", "0.1.0-rc1", "2026-09-01", "0.-1", "0.1.x"])
def test_a_stamp_that_cannot_be_ordered_is_refused(stamp):
    # A version is a declaration, and one that cannot be ordered is not a
    # declaration the system can act on. A date and a git sha are named in the
    # message because they are the two things a caller reaches for instead.
    with pytest.raises(ContractVersionError, match="dotted numeric"):
        parse_contract_version(stamp)


def test_a_non_string_stamp_is_refused_by_type():
    with pytest.raises(ContractVersionError, match="must be a string"):
        parse_contract_version(1)
    with pytest.raises(ContractVersionError, match="must be a string"):
        parse_contract_version(True)  # bool is an int subclass; still not a stamp


# --------------------------------------------------------------------------
# The check a reader runs: a value, never an exception
# --------------------------------------------------------------------------


def test_the_running_abi_reads_back_as_compatible():
    verdict = compare(CONTRACT_VERSION)
    assert isinstance(verdict, Compatibility)
    assert verdict.status == "compatible"
    assert verdict.compatible is True
    assert verdict.direction == "same"
    assert verdict.current == verdict.stored == CONTRACT_VERSION


def test_a_stamp_from_another_abi_is_stale_in_both_directions():
    # "stale" covers both directions deliberately — a stamp from the future is
    # not *more* compatible than one from the past — and a caller that wants
    # the direction reads it off the verdict.
    older = compare("0.0.9")
    newer = compare("9.0.0")
    assert older.status == newer.status == "stale"
    assert older.compatible is False and newer.compatible is False
    assert older.direction == "older"
    assert newer.direction == "newer"
    assert "not" in older.message and "commensurable" in older.message


def test_a_node_with_no_stamp_at_all_is_malformed_not_an_error():
    # A row predating the stamp, or one a writer filled in only half of. The
    # audit must be able to say so.
    verdict = compare(None)
    assert verdict.status == "malformed"
    assert verdict.stored is None
    assert verdict.direction is None
    assert "records no contract_version" in verdict.message


def test_an_unreadable_stored_stamp_is_malformed_rather_than_a_raise():
    verdict = compare("nonsense")
    assert verdict.status == "malformed"
    assert verdict.stored == "nonsense"
    assert "unreadable contract_version" in verdict.message


def test_the_reader_never_raises_whatever_the_row_holds():
    # The property that makes an audit over an old tree possible at all.
    for stored in (None, "", "v1", 1, 0.1, ["0.1.0"], {"v": 1}, "0.1.0", "99.0.0"):
        assert compare(stored).status in {"compatible", "stale", "malformed"}


def test_the_comparison_is_a_pure_function_of_its_inputs():
    # No clock, no environment: the same stamp gives the same verdict twice.
    assert compare("0.0.9") == compare("0.0.9")
    assert compare("0.0.9", current="1.0.0").current == "1.0.0"


# --------------------------------------------------------------------------
# The writer's boundary: the one place persisting a bad stamp is refused
# --------------------------------------------------------------------------


def test_a_writer_cannot_persist_a_stamp_no_reader_could_compare():
    with pytest.raises(ContractVersionError, match="dotted numeric"):
        NodeAbiRecord(contract_version="unreleased", code_hash=CODE_HASH)


def test_a_writer_cannot_persist_a_record_without_a_code_hash():
    # A stamp with no code hash names a contract but not the source it was
    # written against; the pair is the record.
    with pytest.raises(ValueError, match="code_hash"):
        NodeAbiRecord(contract_version=CONTRACT_VERSION, code_hash="")
    with pytest.raises(ValueError, match="code_hash"):
        NodeAbiRecord(contract_version=CONTRACT_VERSION, code_hash="   ")


def test_the_strict_check_admits_the_running_abi_and_refuses_anything_else():
    # What a sandbox about to execute a node's code calls: running source
    # written against a different entrypoint contract fails far from its
    # cause, so the refusal belongs at the boundary where the stamp is known.
    assert require_supported_contract_version(CONTRACT_VERSION) == CONTRACT_VERSION
    with pytest.raises(ContractVersionError, match="older"):
        require_supported_contract_version("0.0.9")
    with pytest.raises(ContractVersionError, match="records no contract_version"):
        require_supported_contract_version(None)


# --------------------------------------------------------------------------
# The stamp tracks the build, not a cached copy of it
# --------------------------------------------------------------------------


def test_the_verdict_follows_the_running_version_when_it_moves(monkeypatch):
    # Which ABI is current is read live rather than frozen at import, so a
    # build that bumps the constant sees stored stamps flip to stale. A cached
    # copy would make the one thing this module exists to compare untestable.
    monkeypatch.setattr(contract, "CONTRACT_VERSION", "0.2.0")
    assert contract_version() == "0.2.0"
    verdict = compare("0.1.0")
    assert verdict.status == "stale"
    assert verdict.direction == "older"
    assert verdict.current == "0.2.0"


def test_a_node_is_stamped_with_the_abi_that_is_actually_running(monkeypatch):
    monkeypatch.setattr(contract, "CONTRACT_VERSION", "0.2.0")
    assert node_abi_record(code_hash=CODE_HASH).contract_version == "0.2.0"


def test_the_declared_abi_record_stays_composed_after_this_feature():
    # Whatever else changed, the composed component is unchanged — declaring
    # the version does not perturb the ABI record the factory advertises.
    from app.module_loader import create_app

    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "packages" / "contract" / "src"
    component = create_app(src).get("contract")
    assert component["contract_version"] == contract_version()
    assert component["market_window"] == "contract:MarketWindow"
