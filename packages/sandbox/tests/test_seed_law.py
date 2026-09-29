"""Feature 165 — the node seed, into every invocation and onto every record.

app_spec.xml feature 165: *"System passes the node seed into every sandboxed
invocation, persisting that seed on the node record."*  This file tests the
sentence clause by clause, because a seed that satisfied any three of them
would be a different and worse feature:

* **the node seed** — the value is the *node's*, a non-negative integer inside
  the range a ``BIGINT`` column holds, and :func:`sandbox.mint_node_seed`
  derives it from the node's identity so "which stream did this node draw
  from?" is answerable without the store;
* **passes ... into every sandboxed invocation** — *every* one, including the
  ones whose signal happens to draw nothing: the seed travels on the envelope
  and crosses into the child's environment, which is the spelling
  §5.2's call site and the box's own child protocol use;
* **persisting that seed on the node record** — the write half, and its one
  judgement: a record naming a *different* seed is refused rather than
  overwritten, because a record and an invocation are two statements about one
  run;
* **every** — the audit, over a batch that already ran.

The law's shape is asymmetric and the tests follow it: the *constructor* of an
invocation refuses nothing (the caller that most needs to be told its run is
seedless is the one holding the seedless run), so every refusal fires at
:meth:`~sandbox.SandboxSeed.require` or is *returned* by
:meth:`~sandbox.SandboxSeed.check`.  Which one a test uses is itself part of
what it pins: the two must never disagree, and one of the tests below asserts
exactly that over the same inputs.
"""

from __future__ import annotations

import pytest
import sandbox
from _documents import (
    NODE_SEED,
    OTHER_NODE_SEED,
    OTHER_SEED_NODE_ID,
    SEED_NODE_ID,
    SeedRecordRow,
    invocation,
    node_record,
    seedless_invocation,
)
from sandbox import (
    ENV_SIGNAL_SEED,
    MINT_SALT,
    SEED_MAX,
    SEED_MISMATCH_CODE,
    SEED_REQUIRED_CODE,
    SandboxInvocation,
    SandboxSeed,
    SeedDecision,
    SeedReason,
    SeedRecord,
    check_invocation,
    mint_node_seed,
    resolve_seed,
    sandbox_seed,
    seed_record,
)
from sandbox.errors import (
    InvocationSeedError,
    NodeSeedDocumentError,
    SandboxError,
    SandboxSeedError,
)


@pytest.fixture
def law() -> SandboxSeed:
    """The seed law, compiled fresh — feature 165's whole answer."""
    return sandbox_seed()


class TestTheSeedValue:
    """*the node seed* — the value, its shape and its derivation."""

    def test_a_good_seed_is_passed_through_unchanged(self, law: SandboxSeed) -> None:
        """``require`` hands the launcher the integer, not ``None``.

        A verb that returned ``None`` on success would make the caller read the
        seed off the invocation a second time, and the two readings are exactly
        the pair that can drift.
        """
        assert law.require(invocation(seed=NODE_SEED)) == NODE_SEED

    @pytest.mark.parametrize("seed", [0, 1, NODE_SEED, 2**32 - 1, SEED_MAX])
    def test_every_storable_boundary_is_admitted(
        self, law: SandboxSeed, seed: int
    ) -> None:
        """Both ends of the range, inclusive: ``0`` is a seed and ``SEED_MAX``
        is the last one a signed 64-bit column can hold."""
        assert law.require(invocation(seed=seed)) == seed

    def test_the_range_is_the_signed_64_bit_one(self) -> None:
        """Pinned as data, because it is a *storability* bound rather than an
        arithmetic one — §12 writes the seed on the node, so a seed that cannot
        land in the column is a run whose randomness could never be recorded."""
        assert SEED_MAX == 2**63 - 1

    def test_a_seed_is_minted_from_the_node_identity(self) -> None:
        """The derivation is a function of the identity alone: same node, same
        seed — across calls and across processes, which is why it is
        ``sha256`` and not the salted builtin ``hash``."""
        first = mint_node_seed(SEED_NODE_ID)
        second = mint_node_seed(SEED_NODE_ID)
        assert first == second
        assert 0 <= first <= SEED_MAX

    def test_two_nodes_get_two_seeds(self) -> None:
        """A per-node derivation, so a node copied into a second campaign is
        not silently handed a stream another node already drew from."""
        assert mint_node_seed(SEED_NODE_ID) != mint_node_seed(OTHER_SEED_NODE_ID)

    def test_a_minted_seed_always_passes_the_law(self, law: SandboxSeed) -> None:
        """The derivation's output range and the law's accepted range are the
        same range — checked rather than asserted, so a later change to either
        fails here instead of at a launcher."""
        for node in (SEED_NODE_ID, OTHER_SEED_NODE_ID, "a" * 64):
            minted = mint_node_seed(node)
            assert law.require(invocation(node_id=node, seed=minted)) == minted

    def test_the_mint_is_salted_away_from_the_oracle_trio(self) -> None:
        """Feature 115 derives a ``perm_seed`` from the *same* node identity
        under no salt; the two must not produce one number for one node, or a
        deployment would have one value doing two jobs."""
        import hashlib

        unsalted = int.from_bytes(
            hashlib.sha256(f"\x00{SEED_NODE_ID}".encode()).digest()[:8], "big"
        ) >> 1
        assert mint_node_seed(SEED_NODE_ID) != unsalted
        assert MINT_SALT

    @pytest.mark.parametrize("bad", ["", "   ", None, 7, b"node"])
    def test_a_node_identity_that_is_not_a_string_is_refused(self, bad: object) -> None:
        """The derivation is keyed on the identity, so an identity that names
        no node names no stream it could reproduce."""
        with pytest.raises(InvocationSeedError) as raised:
            mint_node_seed(bad)
        assert str(raised.value).startswith(SEED_REQUIRED_CODE)


class TestTheInvocation:
    """*passes ... into every sandboxed invocation* — the envelope and the env."""

    def test_an_invocation_carries_the_seed_into_the_child_env(
        self, law: SandboxSeed
    ) -> None:
        """The seed is one value written in two places — §5.2's ``seed=``
        argument and the child's environment, which is the spelling
        ``evaluator._sandbox`` actually crosses it in — and this object is
        where the two are made to agree."""
        inv = invocation(seed=NODE_SEED)
        assert inv.env[ENV_SIGNAL_SEED] == str(NODE_SEED)

    def test_the_decision_hands_back_an_environment_too(self, law: SandboxSeed) -> None:
        """``seed_env`` is the transport, written onto a *copy*: two
        invocations built from one environment must not fight over it, the
        same copy-then-write discipline the determinism variables take."""
        base = {"OMP_NUM_THREADS": "1"}
        env = law.check(invocation()).seed_env(base)
        assert env[ENV_SIGNAL_SEED] == str(NODE_SEED)
        assert env["OMP_NUM_THREADS"] == "1"
        assert ENV_SIGNAL_SEED not in base

    def test_the_constructor_refuses_nothing(self) -> None:
        """The load-bearing asymmetry: the caller that most needs to be told
        its invocation is seedless is the one *holding* the seedless
        invocation, and it cannot be told about an object it was never allowed
        to build.  So the refusal lives at the gate, not here."""
        inv = SandboxInvocation(node_id=SEED_NODE_ID)
        assert inv.seed is None
        assert isinstance(inv, SandboxInvocation)

    def test_an_invocation_copies_the_env_it_is_handed(self) -> None:
        """A caller that mutates the mapping it passed cannot change what an
        invocation carries after the fact."""
        shared = {"KEEP": "yes"}
        inv = invocation(env=shared)
        shared["KEEP"] = "no"
        shared["SNEAKED"] = "in"
        assert inv.env["KEEP"] == "yes"
        assert "SNEAKED" not in inv.env

    def test_reseeding_returns_a_copy_and_leaves_the_original(self) -> None:
        """An invocation describes a run that either happened or did not; a
        launcher that re-seeded one in place would leave two callers holding
        descriptions of two runs that are the same object."""
        original = invocation(seed=NODE_SEED)
        reseeded = original.with_seed(OTHER_NODE_SEED)
        assert reseeded.seed == OTHER_NODE_SEED
        assert reseeded.env[ENV_SIGNAL_SEED] == str(OTHER_NODE_SEED)
        assert original.seed == NODE_SEED
        assert original is not reseeded

    def test_a_seed_named_as_text_in_the_env_is_corrected_not_obeyed(self) -> None:
        """The argument is the authority and the env is the transport: a
        hand-built env that disagrees with the seed carried here is corrected,
        so the two spellings cannot diverge in flight."""
        inv = invocation(seed=NODE_SEED, env={ENV_SIGNAL_SEED: "999"})
        assert inv.env[ENV_SIGNAL_SEED] == str(NODE_SEED)

    def test_the_invocation_models_only_the_seed_half_of_the_call(self) -> None:
        """The limits are 162's and 163's, the payload is 166's; a boundary
        that also modelled them would be a second, divergent copy of
        ``evaluator._sandbox``'s call shape."""
        assert SandboxInvocation.__slots__ == ("component", "env", "node_id", "seed")


class TestTheRefusal:
    """The refusals, each with its own reason — the repair differs."""

    def test_a_seedless_invocation_is_refused_by_name(self, law: SandboxSeed) -> None:
        with pytest.raises(InvocationSeedError) as raised:
            law.require(seedless_invocation())
        assert str(raised.value).startswith(SEED_REQUIRED_CODE)

    def test_omitting_the_seed_is_the_same_state_as_passing_none(
        self, law: SandboxSeed
    ) -> None:
        """Two spellings of one absence, deliberately not split apart: a caller
        forced to catch both would miss the one its launcher produced."""
        omitted = SandboxInvocation(node_id=SEED_NODE_ID)
        explicit = seedless_invocation(node_id=SEED_NODE_ID)
        assert law.check(omitted).reason is law.check(explicit).reason
        assert law.check(omitted).reason is SeedReason.WITHOUT_SEED

    @pytest.mark.parametrize(
        "value",
        ["7", b"7", 7.0, True, False, [7], (7,), object()],
    )
    def test_a_seed_that_is_not_an_integer_is_refused(
        self, law: SandboxSeed, value: object
    ) -> None:
        """A string seed is the spelling an environment variable carries, a
        ``bool`` is an ``int`` in Python and not a seed anyone meant to write,
        and a *float* is refused even when integral: the seed is stored as an
        integer, and a store tolerating both spellings is one where two records
        can say the same seed differently."""
        decision = law.check(invocation(seed=value))
        assert decision.admitted is False
        assert decision.reason is SeedReason.MALFORMED_SEED
        assert SEED_REQUIRED_CODE in decision.detail

    @pytest.mark.parametrize("value", [-1, -NODE_SEED, SEED_MAX + 1, 2**64])
    def test_an_integer_outside_the_storable_range_is_its_own_reason(
        self, law: SandboxSeed, value: int
    ) -> None:
        """Split from *malformed*, because a negative or oversized integer is a
        seed-shaped value with a value-shaped problem: an operator reading
        ``malformed-seed`` would go looking for a type bug."""
        decision = law.check(invocation(seed=value))
        assert decision.admitted is False
        assert decision.reason is SeedReason.OUT_OF_RANGE
        assert SEED_REQUIRED_CODE in decision.detail

    def test_a_negative_seed_names_the_range_and_not_the_type(
        self, law: SandboxSeed
    ) -> None:
        """The order of the checks is the order a reader wants them in: ``-1``
        has the right type and the wrong value, and the message must not send
        an operator looking for a bound when the value never had the type to be
        bounded by one."""
        detail = law.check(invocation(seed=-1)).detail
        assert str(SEED_MAX) in detail
        assert "not an integer" not in detail

    def test_a_refusal_carries_the_value_the_type_and_the_reason_it_matters(
        self, law: SandboxSeed
    ) -> None:
        """One body of prose per reason, and a refusal says what an operator
        needs to act on it: which value was offered, which type it was spelled
        in — the two facts that locate the bug — and the rule it broke.

        The rule is the *storage* one rather than an arbitrary validation: each
        consequence sentence names where the seed is written (§12's node
        record), because a refusal a reader cannot connect to the determinism
        contract is one they will work around.
        """
        detail = law.check(invocation(seed="7")).detail
        assert "'7'" in detail
        assert "str" in detail
        assert "node record" in detail
        assert "refused rather than coerced" in detail

    def test_each_malformed_spelling_gets_its_own_sentence(
        self, law: SandboxSeed
    ) -> None:
        """One reason, three diagnoses: a string, a ``bool`` and a float all
        fail as *malformed*, and collapsing them to one sentence would tell an
        operator holding ``True`` about environment variables."""
        text = law.check(invocation(seed="7")).detail
        flag = law.check(invocation(seed=True)).detail
        real = law.check(invocation(seed=7.0)).detail
        assert len({text, flag, real}) == 3
        # Each names the spelling it is about, so the three are told apart by
        # their diagnosis and not only by their wording.
        assert "environment variable" in text
        assert "``int``" in flag
        assert "float" in real

    def test_a_refused_decision_hands_back_no_seed(self, law: SandboxSeed) -> None:
        """A caller reading ``decision.seed`` after checking ``admitted`` has
        the integer rather than a sentinel, on every path."""
        for bad in (None, "7", -1):
            decision = law.check(invocation(seed=bad))
            assert decision.seed is None

    def test_a_refused_decision_carries_no_environment(self, law: SandboxSeed) -> None:
        """An unseeded environment is not a transport of anything, and handing
        one back would let a spawn proceed with the law's answer dropped."""
        with pytest.raises(InvocationSeedError):
            law.check(seedless_invocation()).seed_env()

    def test_the_exception_is_this_member_s_own(self, law: SandboxSeed) -> None:
        """Not a ``ValueError``: the box untrusted code is put inside must not
        carry a dependency whose refusals a caller could confuse with the
        standard library's, and a caller catching ``SandboxError`` gets every
        refusal of this member."""
        assert issubclass(InvocationSeedError, SandboxSeedError)
        assert issubclass(SandboxSeedError, SandboxError)
        assert not issubclass(InvocationSeedError, ValueError)

    def test_the_decision_and_the_exception_never_disagree(
        self, law: SandboxSeed
    ) -> None:
        """One classification behind both shapes, checked over the whole
        vocabulary of ways a value can fail to be a seed."""
        candidates = [None, "7", 7.0, True, -1, SEED_MAX + 1, [1], object()]
        for value in candidates:
            decision = law.check(invocation(seed=value))
            assert decision.admitted is False
            with pytest.raises(InvocationSeedError) as raised:
                decision.require()
            assert str(raised.value) == decision.detail

    def test_an_admitted_decision_requires_cleanly(self, law: SandboxSeed) -> None:
        """``require`` on a decision that admitted the run is a no-op returning
        the seed, so a caller can use it unconditionally on the last line."""
        assert law.check(invocation()).require() == NODE_SEED


class TestTheRecord:
    """*persisting that seed on the node record* — the write half."""

    def test_a_seed_lands_on_the_record(self) -> None:
        record = node_record(seed=None)
        written = seed_record(record, NODE_SEED)
        assert record["seed"] == NODE_SEED
        assert written.seed == NODE_SEED
        assert written.superseded is None
        assert written.reseeded is False

    def test_the_receipt_names_the_node_and_the_seed(self) -> None:
        written = seed_record(node_record(seed=None), NODE_SEED)
        assert written.node_id == SEED_NODE_ID

    def test_rewriting_the_same_seed_is_idempotent_and_not_news(self) -> None:
        """An idempotent write that reported a supersession would make every
        re-persist look like a re-seed."""
        record = node_record(seed=NODE_SEED)
        written = seed_record(record, NODE_SEED)
        assert written.superseded is None
        assert written.reseeded is False
        assert record["seed"] == NODE_SEED

    def test_the_record_may_be_an_object_as_well_as_a_mapping(self) -> None:
        """Both shapes occur in this repository: §9.1's row arrives from a
        relational driver as a mapping, the members' own records carry the
        field as an attribute."""
        record = SeedRecordRow(seed=None)
        written = seed_record(record, NODE_SEED)
        assert record.seed == NODE_SEED
        assert written.seed == NODE_SEED

    def test_a_record_naming_a_different_seed_is_refused_not_overwritten(
        self,
    ) -> None:
        """The one judgement in the module that could have gone the other way,
        and the reason it does not: a record and an invocation are two
        statements about *one* run, and silently overwriting leaves an artifact
        produced from one seed beside a record saying another."""
        record = node_record(seed=OTHER_NODE_SEED)
        with pytest.raises(NodeSeedDocumentError) as raised:
            seed_record(record, NODE_SEED)
        assert str(raised.value).startswith(SEED_MISMATCH_CODE)
        assert record["seed"] == OTHER_NODE_SEED

    def test_the_mismatch_names_both_values(self) -> None:
        """A reader sees which of the two the disagreement is about, rather
        than being told only that they differ."""
        detail = None
        try:
            seed_record(node_record(seed=OTHER_NODE_SEED), NODE_SEED)
        except NodeSeedDocumentError as exc:
            detail = str(exc)
        assert detail is not None
        assert str(OTHER_NODE_SEED) in detail
        assert str(NODE_SEED) in detail

    def test_a_record_is_read_back(self) -> None:
        assert resolve_seed(node_record(seed=NODE_SEED)) == NODE_SEED
        assert resolve_seed(SeedRecordRow(seed=OTHER_NODE_SEED)) == OTHER_NODE_SEED

    def test_a_record_naming_no_seed_is_refused_by_name(self) -> None:
        """Refused rather than answered with a ``None`` — every caller of
        ``resolve_seed`` has already decided it *has* a node and wants its
        seed, and a ``None`` would travel one frame further before becoming an
        unexplainable absence."""
        with pytest.raises(NodeSeedDocumentError) as raised:
            resolve_seed(node_record(seed=None))
        assert str(raised.value).startswith(SEED_MISMATCH_CODE)

    def test_the_reader_does_not_mint_a_replacement(self) -> None:
        """Minting here would write a second answer over a question that was
        settled when the node was created — and would make a seedless node
        indistinguishable from a seeded one."""
        with pytest.raises(NodeSeedDocumentError) as raised:
            resolve_seed(node_record(seed=None))
        assert "mint" in str(raised.value)

    @pytest.mark.parametrize("bad", ["7", 7.0, True, -1])
    def test_a_record_whose_seed_is_not_a_seed_is_refused(self, bad: object) -> None:
        """A record whose seed is a string or a negative number is one no
        replay could draw from; the record is refused rather than the field
        skipped, because a caller told "no seed" would go on to mint a second
        one and overwrite the evidence."""
        with pytest.raises(NodeSeedDocumentError) as raised:
            resolve_seed(node_record(seed=bad))
        assert str(raised.value).startswith(SEED_MISMATCH_CODE)

    def test_writing_a_seed_that_is_not_a_seed_is_refused(self) -> None:
        """One check, two seams: a caller cannot get an unvalidated value onto
        a record by taking the write path instead of the invocation path."""
        for bad in ("7", -1, None, True):
            with pytest.raises(InvocationSeedError):
                seed_record(node_record(seed=None), bad)

    def test_an_unidentified_record_still_produces_a_readable_refusal(self) -> None:
        """The node id is read while *building an error message*: a record that
        names none must not raise a second failure inside the first."""
        with pytest.raises(NodeSeedDocumentError) as raised:
            resolve_seed({})
        assert "<unidentified node>" in str(raised.value)

    def test_a_record_that_cannot_carry_a_seed_is_refused(self) -> None:
        """A record this law cannot write is one whose seed will not be
        persisted, and a caller has to hear that rather than infer it from a
        silent no-op."""

        class Frozen:
            __slots__ = ()

        with pytest.raises(NodeSeedDocumentError) as raised:
            seed_record(Frozen(), NODE_SEED)
        assert str(raised.value).startswith(SEED_MISMATCH_CODE)

    def test_the_written_record_is_a_type_of_this_member(self) -> None:
        assert isinstance(seed_record(node_record(seed=None), NODE_SEED), SeedRecord)


class TestTheRecordAtTheGate:
    """The two halves meeting: an invocation checked *against* its record."""

    def test_an_invocation_matching_its_record_is_admitted(
        self, law: SandboxSeed
    ) -> None:
        decision = law.check(invocation(seed=NODE_SEED), record=node_record())
        assert decision.admitted is True
        assert decision.seed == NODE_SEED

    def test_an_invocation_contradicting_its_record_is_refused(
        self, law: SandboxSeed
    ) -> None:
        """Feature 165's second half, as a gate: an invocation dispatched under
        one seed and persisted beside a record naming another produces a node
        whose score no replay reproduces and whose record says otherwise."""
        decision = law.check(
            invocation(seed=NODE_SEED), record=node_record(seed=OTHER_NODE_SEED)
        )
        assert decision.admitted is False
        assert decision.reason is SeedReason.RECORD_MISMATCH
        assert SEED_MISMATCH_CODE in decision.detail

    def test_the_mismatch_refusal_reaches_the_launcher_as_an_exception(
        self, law: SandboxSeed
    ) -> None:
        with pytest.raises(InvocationSeedError) as raised:
            law.require(
                invocation(seed=NODE_SEED), record=node_record(seed=OTHER_NODE_SEED)
            )
        assert str(raised.value).startswith(SEED_MISMATCH_CODE)

    def test_a_record_naming_no_seed_is_not_a_mismatch(
        self, law: SandboxSeed
    ) -> None:
        """An unpersisted node is not a contradiction — it is the state the
        write half exists to fill in, and refusing it here would make the first
        run of every node illegal."""
        decision = law.check(
            invocation(seed=NODE_SEED), record=node_record(seed=None)
        )
        assert decision.admitted is True

    def test_a_seedless_invocation_outranks_the_record_question(
        self, law: SandboxSeed
    ) -> None:
        """The run's own seed is settled before the record is consulted: there
        is nothing to compare a record against when the invocation carries no
        seed, and reporting a mismatch would send an operator to the store for
        a fault at the call site."""
        decision = law.check(
            seedless_invocation(), record=node_record(seed=OTHER_NODE_SEED)
        )
        assert decision.reason is SeedReason.WITHOUT_SEED

    def test_an_invocation_can_be_described_from_its_record(self) -> None:
        """The launcher that holds a node record describes its invocation from
        it — and a record with *no* seed is refused rather than silently
        leaving the invocation as it was, because "the record had none so the
        run kept its own" is exactly the two-statements-disagreeing state this
        feature exists to rule out."""
        from_record = SandboxInvocation(node_id=SEED_NODE_ID).with_record(
            node_record(seed=OTHER_NODE_SEED)
        )
        assert from_record.seed == OTHER_NODE_SEED
        with pytest.raises(NodeSeedDocumentError):
            SandboxInvocation(node_id=SEED_NODE_ID).with_record(
                node_record(seed=None)
            )


class TestTheAudit:
    """*every* — the batch, checked after the fact."""

    def test_a_clean_batch_audits_to_nothing(self, law: SandboxSeed) -> None:
        """An empty tuple is the audit's pass, and deliberately an empty tuple
        rather than ``True``: the useful output is *which* runs failed."""
        refusals = law.seeded([invocation(), invocation(node_id=OTHER_SEED_NODE_ID)])
        assert refusals == ()

    def test_a_seedless_run_in_a_batch_is_found(self, law: SandboxSeed) -> None:
        refusals = law.seeded(
            [invocation(), seedless_invocation(node_id=OTHER_SEED_NODE_ID), invocation()]
        )
        assert len(refusals) == 1
        assert refusals[0].node_id == OTHER_SEED_NODE_ID
        assert refusals[0].reason is SeedReason.WITHOUT_SEED

    def test_the_audit_names_every_offender_in_order(self, law: SandboxSeed) -> None:
        """A screen that reported one offender at a time would be resubmitted
        to learn the rest — the collective refusal this member's import law
        states for its own screen."""
        refusals = law.seeded(
            [
                seedless_invocation(node_id="node-a"),
                invocation(node_id="node-b"),
                invocation(node_id="node-c", seed="7"),
            ]
        )
        assert [d.node_id for d in refusals] == ["node-a", "node-c"]
        assert [d.reason for d in refusals] == [
            SeedReason.WITHOUT_SEED,
            SeedReason.MALFORMED_SEED,
        ]

    def test_records_pair_positionally_with_the_batch(self, law: SandboxSeed) -> None:
        """Passed the records, each invocation is checked against its own — so
        an audit over a tree finds the run whose record drifted, not only the
        runs that went out bare."""
        refusals = law.seeded(
            [invocation(seed=NODE_SEED), invocation(seed=OTHER_NODE_SEED, node_id=OTHER_SEED_NODE_ID)],
            records=[
                node_record(seed=NODE_SEED),
                node_record(node_id=OTHER_SEED_NODE_ID, seed=NODE_SEED),
            ],
        )
        assert len(refusals) == 1
        assert refusals[0].node_id == OTHER_SEED_NODE_ID
        assert refusals[0].reason is SeedReason.RECORD_MISMATCH

    def test_a_batch_of_two_lengths_is_refused_whole(self, law: SandboxSeed) -> None:
        """An audit that silently paired invocation *i* with record *j* would
        report on runs that were never checked."""
        with pytest.raises(InvocationSeedError) as raised:
            law.seeded([invocation()], records=[node_record(), node_record()])
        assert str(raised.value).startswith(SEED_REQUIRED_CODE)

    def test_an_empty_batch_audits_to_nothing(self, law: SandboxSeed) -> None:
        assert law.seeded([]) == ()


class TestTheModuleLevelVerbs:
    """The law without the component — for a caller that has no application."""

    def test_check_invocation_is_the_gate_the_facade_reaches(self) -> None:
        """One implementation: the component's ``check`` reaches this function
        rather than re-deciding."""
        decision = check_invocation(invocation())
        assert isinstance(decision, SeedDecision)
        assert decision.admitted is True

    def test_the_component_and_the_module_agree(self, law: SandboxSeed) -> None:
        assert law.check(invocation()).admitted is check_invocation(invocation()).admitted
        assert law.require(invocation()) == check_invocation(invocation()).require()

    def test_the_component_carries_nothing(self, law: SandboxSeed) -> None:
        """A seed belongs to one node, and a component held across runs that
        carried one would let two nodes share a stream — the property the
        transfer component states for its channel, in a different quantity."""
        assert law.__slots__ == ()
        with pytest.raises(AttributeError):
            law.seed = NODE_SEED  # type: ignore[attr-defined]

    def test_the_reason_vocabulary_is_one_enumeration_for_both_polarities(
        self,
    ) -> None:
        """A decision's reason is one fact with two polarities and the audit
        line should read the same either way."""
        assert SeedReason.BY_SEED in set(SeedReason)
        for reason in (
            SeedReason.WITHOUT_SEED,
            SeedReason.MALFORMED_SEED,
            SeedReason.OUT_OF_RANGE,
            SeedReason.RECORD_MISMATCH,
        ):
            assert reason in set(SeedReason)
        assert SeedReason.BY_SEED == "by-seed"


class TestTheVocabulary:
    """Feature 165's own spelling, kept where the member's other codes live."""

    def test_the_codes_are_the_features_own_words(self) -> None:
        assert SEED_REQUIRED_CODE == "node_seed_required"
        assert SEED_MISMATCH_CODE == "node_seed_mismatch"

    def test_the_env_spelling_is_the_boxes_own(self) -> None:
        """§5.2's child protocol crosses the seed in the environment, and the
        runner on the far side of that seam (``evaluator._sandbox``, which
        writes ``env["NULLIUS_SIGNAL_SEED"] = str(int(seed))`` at its call
        site) reads this same name.

        The *value* is pinned here as data rather than by importing the
        evaluator: the sandbox member is the box that agent-authored code goes
        inside, and it must not acquire a dependency on the member that drives
        it to check a string one of them has to spell for the other.  A change
        to the name is a change to a wire format, and this is where it has to
        be argued rather than noticed at spawn time.
        """
        assert ENV_SIGNAL_SEED == "NULLIUS_SIGNAL_SEED"

    def test_the_component_name_is_the_feature_s_own_seat(self) -> None:
        assert sandbox.SEED_COMPONENT_NAME == "sandbox-seed"

    def test_the_law_is_reachable_without_the_component(self) -> None:
        """Every name the module's ``__all__`` promises is really there — the
        member's own ``__init__`` imports the law, and a name listed but not
        bound fails only for the caller who reaches for it."""
        for name in (
            "SandboxInvocation",
            "SandboxSeed",
            "SeedDecision",
            "SeedReason",
            "SeedRecord",
            "check_invocation",
            "mint_node_seed",
            "resolve_seed",
            "sandbox_seed",
            "seed_record",
            "ENV_SIGNAL_SEED",
            "SEED_COMPONENT_NAME",
            "SEED_MAX",
            "SEED_MISMATCH_CODE",
            "SEED_REQUIRED_CODE",
            "InvocationSeedError",
            "NodeSeedDocumentError",
            "SandboxSeedError",
        ):
            assert name in sandbox.__all__, name
            assert hasattr(sandbox, name), name

    def test_the_error_types_are_this_members_own_family(self) -> None:
        """A caller that catches ``SandboxError`` gets the seed's refusals
        beside the isolation law's and the import law's, rather than a family
        of its own to discover."""
        assert issubclass(InvocationSeedError, SandboxSeedError)
        assert issubclass(NodeSeedDocumentError, SandboxSeedError)
        assert issubclass(SandboxSeedError, SandboxError)
        assert issubclass(SandboxError, Exception)
