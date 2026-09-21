"""Feature 205 — the agent writes a signal function conforming to the contract.

app_spec.xml: *"Agent writes a signal function conforming to the declared
contract, which returns source that the sandbox executes."*
docs/nullius-tech-architecture.md §5.1 declares the contract
(``def signal(ctx: MarketWindow, seed: int) -> pl.Series``) and §5.2 shows
what consumes what the agent wrote (``sandbox.run(entrypoint="signal",
code=node.code, ...)``).

Each claim in that sentence is tested separately, because a law that
satisfied any two of them would be a different and worse feature:

* **conforming to the declared contract** — adoption is a judgement made
  against the *contract's own* declaration, not this member's memory of it.
  A proposal that compiles and does not declare the entrypoint is refused,
  and the refusal carries the validator's own sentence;
* **returns source** — what adoption yields is the exact text §5.2's
  ``code=node.code`` will carry.  Not a normalized copy, not a wrapped
  module: the same string, byte for byte, so the ``code_hash`` this law
  computes is the hash of what the box executes;
* **that the sandbox executes** — the adopted source is handed to the real
  :class:`evaluator.SignalSandbox` and returns a score vector.  This is the
  leg that makes the feature's last clause checkable rather than assumed:
  everything else in this file is a statement about a string, and this is
  the one that says the string runs.

Every refusal below is asserted on the *returned value* rather than with
``pytest.raises``, because the law answers as a value — a campaign driver
diagnoses why a branch's proposal failed (feature 209) and a gate that raised
would have taken that decision from it.  :meth:`SourceAdoption.require` is
tested separately, as the one seam where refusal becomes an exception.
"""

from __future__ import annotations

import polars as pl
import pytest
from signal_agent import (
    CONFORMS_CODE,
    AdoptionReason,
    AgentSourceError,
    SignalContract,
    signal_contract,
    source_code_hash,
)

#: A conforming proposal: §5.1's entrypoint, the declared parameters, a polars
#: series positional against the universe.  A module constant rather than a
#: fixture, because several claims below are about *this text* — that adoption
#: returns it unmodified, that its sha256 is the tree's ``code_hash`` — and a
#: fixture rebuilding it per test would make "the same source" a claim about
#: two constructions rather than about one string.
CONFORMING_SOURCE = (
    "def signal(ctx, seed):\n"
    "    return pl.Series([1.0] * len(ctx.universe))\n"
)

#: A source that is Python, compiles, and is not this contract's source: the
#: entrypoint is named something else.  Feature 205's word *conforming* is
#: exactly the difference between this string and :data:`CONFORMING_SOURCE`.
NON_CONFORMING_SOURCE = (
    "def propose(ctx, seed):\n"
    "    return pl.Series([1.0] * len(ctx.universe))\n"
)


def _requires_contract():
    """The contract member's own ABI, for the claims that compare against it."""
    return pytest.importorskip("contract")


# -- conforming to the declared contract -------------------------------------


def test_a_conforming_proposal_is_adopted(law: SignalContract) -> None:
    adoption = law.adopt(CONFORMING_SOURCE)
    assert adoption.adopted
    assert adoption.reason is AdoptionReason.CONFORMS
    assert adoption.problems == ()
    assert CONFORMS_CODE in adoption.detail


def test_a_proposal_with_the_wrong_entrypoint_name_is_refused(
    law: SignalContract,
) -> None:
    # Feature 205's word is *conforming*, and the entrypoint's name is the
    # first thing conformance means: §5.2 looks the function up by name.
    adoption = law.adopt(NON_CONFORMING_SOURCE)
    assert not adoption.adopted
    assert adoption.reason is AdoptionReason.NOT_CONFORMING
    assert adoption.source is None
    assert adoption.code_hash is None
    assert any("signal" in problem for problem in adoption.problems)


def test_the_refusal_carries_the_validators_own_sentences(law: SignalContract) -> None:
    # The problems are the contract validator's, not this member's paraphrase:
    # feature 206 reads every prior proposal and feature 209 decides whether to
    # retry, and both need *what was wrong* in the words the contract used.
    contract = _requires_contract()
    source = "def signal(ctx, wrong_name):\n    return None\n"
    adoption = law.adopt(source)
    assert not adoption.adopted
    assert adoption.problems == tuple(contract.validate_signal_signature(source))
    assert adoption.problems  # and the tuple is not empty


def test_a_defaulted_seed_is_refused(law: SignalContract) -> None:
    # §12's determinism contract: a signal cannot sample randomness under a
    # defaulted seed, because then the signature stops naming the source of
    # randomness.  The validator enforces it; this pins that adoption does.
    adoption = law.adopt("def signal(ctx, seed=0):\n    return None\n")
    assert not adoption.adopted
    assert any("required" in problem for problem in adoption.problems)


def test_source_that_does_not_compile_is_refused_with_the_syntax_error(
    law: SignalContract,
) -> None:
    adoption = law.adopt("def signal(ctx, seed)\n    return None\n")
    assert not adoption.adopted
    assert adoption.reason is AdoptionReason.NOT_CONFORMING
    assert any("does not compile" in problem for problem in adoption.problems)


def test_a_non_string_proposal_is_refused_by_type(law: SignalContract) -> None:
    # A proposal that is not text is its own reason, not a spelling of the
    # blank case: the retry wants the agent to emit code, not to emit a
    # better-typed something else.
    adoption = law.adopt({"code": CONFORMING_SOURCE})
    assert not adoption.adopted
    assert adoption.reason is AdoptionReason.NOT_SOURCE


def test_a_blank_proposal_is_refused_before_the_validator_runs(
    law: SignalContract,
) -> None:
    adoption = law.adopt("   \n\t\n")
    assert not adoption.adopted
    assert adoption.reason is AdoptionReason.BLANK_SOURCE
    # Not NOT_CONFORMING: a blank submission has no entrypoint to be missing,
    # so a compile-error-shaped refusal would send the operator looking for a
    # signature bug instead of a truncated response.
    assert adoption.problems == ()


# -- returns source ----------------------------------------------------------


def test_the_adopted_source_is_returned_unmodified(law: SignalContract) -> None:
    # Adoption is a judgement about the agent's source, never an edit of it:
    # the tree's code_hash is the hash of exactly what the sandbox executes, so
    # a law that normalized whitespace would produce a row whose identity
    # disagrees with the bytes the box ran.
    source = "\n\n" + CONFORMING_SOURCE + "\n# a trailing comment\n"
    adoption = law.adopt(source)
    assert adoption.adopted
    assert adoption.require() is source


def test_the_code_hash_is_sha256_of_the_adopted_text(law: SignalContract) -> None:
    adoption = law.adopt(CONFORMING_SOURCE)
    assert adoption.code_hash == source_code_hash(CONFORMING_SOURCE)
    assert len(adoption.code_hash) == 64
    assert adoption.code_hash == adoption.code_hash.casefold()


def test_the_abi_record_pairs_the_code_hash_with_the_running_abi(
    law: SignalContract,
) -> None:
    # Feature 15: a stored node carries the contract_version beside its code
    # hash.  The pair is built from *this* adoption, so the stamp describes the
    # ABI the source was checked against.
    contract = _requires_contract()
    adoption = law.adopt(CONFORMING_SOURCE)
    record = adoption.abi_record()
    assert record.code_hash == adoption.code_hash
    assert record.contract_version == contract.CONTRACT_VERSION
    assert record.as_dict() == {
        "contract_version": contract.CONTRACT_VERSION,
        "code_hash": adoption.code_hash,
    }


def test_require_raises_the_members_own_error_on_a_refusal(
    law: SignalContract,
) -> None:
    # The last line before persisting, and the only place a refusal becomes an
    # exception.  The error is this member's, so a caller's `except` clause
    # catches what this member promises it will.
    adoption = law.adopt(NON_CONFORMING_SOURCE)
    with pytest.raises(AgentSourceError) as raised:
        adoption.require()
    # The raised sentence is the returned one, verbatim: the retry prompt and
    # the log line say the same thing rather than being two accounts.
    assert raised.value.args[0] == adoption.detail
    # And the refusal carries the contract's own problems, which is what
    # feature 209's retry diagnosis reads (feature 209 depends on this one).
    assert adoption.problems
    assert all(problem in adoption.detail for problem in adoption.problems)


def test_abi_record_on_a_refusal_raises_too(law: SignalContract) -> None:
    # A refused proposal has no code hash and therefore no ABI record: the pair
    # is the identity of a node, and a proposal that was never adopted is not
    # one.
    with pytest.raises(AgentSourceError):
        law.adopt("").abi_record()


def test_source_code_hash_refuses_a_non_string() -> None:
    with pytest.raises(AgentSourceError):
        source_code_hash(b"def signal(ctx, seed): pass")


def test_the_code_hash_agrees_with_the_member_that_stores_it() -> None:
    # §9.1's code_hash has three writers — this law at adoption, the artifact
    # store at persistence, the evaluator at execution — and they must spell it
    # the same way to the byte, because a tree row whose code_hash disagrees
    # with the text the sandbox ran is a node no replay reproduces.  Feature
    # 179 deduplicates on the stored one, so an adoption hash that differed
    # from it by so much as a case fold would make every agent proposal look
    # novel.  The store's spelling is importable here, so the agreement is
    # checked rather than asserted in a comment.
    artifacts = pytest.importorskip("artifacts")

    stored = artifacts.source_code_hash(CONFORMING_SOURCE)
    assert source_code_hash(CONFORMING_SOURCE) == stored
    # And the store's own checker accepts ours — the two spellings agree on
    # what a legal code_hash even is, not merely on these bytes.
    assert artifacts.canonical_code_hash(stored) == stored


def test_adopting_the_same_source_twice_yields_the_same_identity(
    law: SignalContract,
) -> None:
    # Feature 179 deduplicates on this hash and feature 207's history replays
    # from it, so it has to be a function of the source alone — no clock, no
    # campaign, no per-adoption salt.
    first = law.adopt(CONFORMING_SOURCE)
    second = law.adopt(CONFORMING_SOURCE)
    assert first.code_hash == second.code_hash
    # And two proposals that differ at all are two identities: the hash is over
    # the bytes, not over a normalized form of them.
    assert law.adopt(CONFORMING_SOURCE + "\n").code_hash != first.code_hash


# -- the declaration the agent is asked to write against ---------------------


def test_the_declaration_is_read_out_of_the_contract(law: SignalContract) -> None:
    # Not restated here: the entrypoint, its parameters and the window's
    # accessor surface all come from the contract, so a later feature that
    # widened the surface would fail here rather than in a prompt.
    contract = _requires_contract()
    declaration = law.declaration()
    assert declaration["entrypoint"] == contract.SIGNAL_ENTRYPOINT == "signal"
    assert declaration["window_arg"] == "ctx"
    assert declaration["seed_arg"] == "seed"
    assert declaration["signature"] == "signal(ctx, seed)"
    assert declaration["contract_version"] == contract.CONTRACT_VERSION
    assert declaration["market_window"] == contract.MARKET_WINDOW_ABI
    assert declaration["accessors"] == contract.inspect_accessors()


def test_the_declaration_carries_facts_and_no_guidance(law: SignalContract) -> None:
    # PRD C3 and §14.1: directional guidance distilled from history must not be
    # injected into the authoring prompt ("the paper's Figure 5 found this
    # consistently underperformed"), and feature 208 makes refusing it a
    # feature.  A declaration of the ABI cannot over-constrain a search; prose
    # about where to look can.  There is deliberately no field for a suggested
    # mechanism, a theme hint or a summary of what has been tried.
    declaration = law.declaration()
    assert set(declaration) == {
        "entrypoint",
        "window_arg",
        "seed_arg",
        "signature",
        "returns",
        "market_window",
        "contract_version",
        "accessors",
        "purity",
    }


def test_validate_reports_a_non_string_as_a_problem_rather_than_raising(
    law: SignalContract,
) -> None:
    problems = law.validate(None)
    assert len(problems) == 1
    assert "must be text" in problems[0]


def test_validate_is_empty_exactly_when_adoption_succeeds(
    law: SignalContract,
) -> None:
    for source in (CONFORMING_SOURCE, NON_CONFORMING_SOURCE, "def signal(ctx): pass"):
        assert (law.validate(source) == ()) == law.adopt(source).adopted


# -- what the sandbox executes -----------------------------------------------


def _run_in_sandbox(source: str, universe=("AAA", "BBB", "CCC")):
    """Hand ``source`` to the evaluator's real sandbox, over a real window.

    The last clause of feature 205 is *"which returns source that the sandbox
    executes"*, and this is how that clause is checked: not by simulating the
    box, but by running the adopted text through
    :class:`evaluator.SignalSandbox` over a materialized
    :class:`contract.MarketWindow` — the same call site §5.2 shows.
    """
    pyarrow = pytest.importorskip("pyarrow")
    contract = _requires_contract()
    pytest.importorskip("evaluator")

    from evaluator import SignalSandbox

    frames = {
        "bars:1d": pyarrow.table(
            {"symbol": list(universe), "open_time": list(range(1, len(universe) + 1))}
        )
    }
    window = contract.MarketWindow(
        "2026-09-01T00:00:00Z", universe=tuple(universe), frames=frames
    )
    return SignalSandbox().run(source, window, seed=11)


def test_the_adopted_source_runs_in_the_sandbox() -> None:
    # The feature's last clause, held to the real box rather than to a stand-in.
    law = signal_contract()
    source = law.adopt(
        "def signal(ctx, seed):\n"
        "    return pl.Series([float(seed)] * len(ctx.universe))\n"
    ).require()

    result = _run_in_sandbox(source)
    assert result.fail_class is None, result.detail
    assert result.ok
    assert result.scores is not None
    assert result.scores.to_list() == [11.0, 11.0, 11.0]
    assert result.seed == 11


def test_the_sandbox_rejects_what_the_law_refused_to_adopt() -> None:
    # The two authorities agree, which is the point of checking conformance
    # host-side rather than discovering it at replay time: the box fails to
    # find the entrypoint in exactly the source adoption refused.
    result = _run_in_sandbox(NON_CONFORMING_SOURCE)
    assert result.fail_class == "crash"
    assert "entrypoint" in result.detail


def test_a_proposal_is_returned_as_source_the_box_would_accept() -> None:
    # The pair, end to end and in one test: adoption says yes, and the text it
    # said yes to is the text that produced a score vector.  `pl` is available
    # in the child unbound by the signal, exactly as §5.2's runner provides it.
    law = signal_contract()
    adoption = law.adopt(
        "def signal(ctx, seed):\n    return pl.Series([1.0, -1.0, 0.0])\n"
    )
    assert adoption.adopted
    result = _run_in_sandbox(adoption.require())
    assert result.ok, result.detail
    assert isinstance(result.scores, pl.Series)
    assert result.scores.to_list() == [1.0, -1.0, 0.0]


# -- the optional box screen (feature 167, ridden not rebuilt) ---------------


def test_a_screen_is_not_consulted_when_nothing_was_supplied(
    law: SignalContract,
) -> None:
    # The box's ceiling is the box's; this member does not restate it.  Without
    # a screen, adoption is a statement about the contract alone.
    assert law.adopt(CONFORMING_SOURCE).adopted


def test_a_screen_admits_a_conforming_proposal(law: SignalContract, box_screen) -> None:
    adoption = law.adopt(CONFORMING_SOURCE, screen=box_screen)
    assert adoption.adopted


def test_a_screen_refusal_is_its_own_reason_with_the_boxs_sentence(
    law: SignalContract, box_screen
) -> None:
    # The two authorities are different: the contract says what the box will
    # *invoke*, the box says what it will *admit*.  A signature-correct
    # proposal can still be one the run never executes, and a caller told only
    # "not conforming" would go looking for a signature bug.
    source = (
        "import os\n"
        "def signal(ctx, seed):\n"
        "    return pl.Series([1.0] * len(ctx.universe))\n"
    )
    adoption = law.adopt(source, screen=box_screen)
    assert not adoption.adopted
    assert adoption.reason is AdoptionReason.REFUSED_BY_BOX
    # The box's own message, carried verbatim rather than re-worded.
    assert "disallowed_import" in adoption.detail


def test_a_screen_that_raises_is_refused_rather_than_read_as_an_admission(
    law: SignalContract,
) -> None:
    # A screen that cannot answer has not admitted anything, and reading its
    # failure as an admission would adopt a proposal on the strength of an
    # exception.
    def broken(source: str):
        raise RuntimeError("the box is unreachable")

    with pytest.raises(AgentSourceError) as raised:
        law.adopt(CONFORMING_SOURCE, screen=broken)
    assert "RuntimeError" in str(raised.value)


def test_a_screen_that_answers_an_unreadable_value_is_refused(
    law: SignalContract,
) -> None:
    with pytest.raises(AgentSourceError) as raised:
        law.adopt(CONFORMING_SOURCE, screen=lambda source: "yes")
    assert "admitted" in str(raised.value)


def test_the_boxs_own_error_type_never_escapes_this_law(
    law: SignalContract,
) -> None:
    # The vocabulary rule: a caller of this law writes `except SignalAgentError`
    # and must not be handed an exception from another member's tree that its
    # clause does not catch.  A screen that *raises* the box's own error — which
    # is what a caller passing `screen_module(...).require` would do — is
    # translated here, and the box's sentence survives in the message.
    sandbox_errors = pytest.importorskip("sandbox")

    def screen(source: str):
        raise sandbox_errors.DisallowedImportError("disallowed_import: os")

    with pytest.raises(AgentSourceError) as raised:
        law.adopt(CONFORMING_SOURCE, screen=screen)
    assert not isinstance(raised.value, sandbox_errors.SandboxError)
    assert "DisallowedImportError" in str(raised.value)
