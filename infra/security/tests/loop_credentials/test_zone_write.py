"""Feature 148: the gate — every zone write answered, none allowed.

The law's answer-time half.  An attempt is hostile input by definition
— it comes from agent-authored code — so the gate answers with a
decision for every shape and raises for none, the same stance the
egress gate takes for dial-outs and the access gate for arrivals.  What
the tests below assert is which *reason* each attempt earns, because
the reason is the audit record: §2's own words — "Z1 has no credential
for Z0" — for the zone, the named credential for a work area the grant
really holds.

The last group proves the derivation is real: the gate allows by
*consulting* the compiled set, not by listing blessed paths — a
hand-built set with a rogue zone write is allowed by the very same
consultation at its scratch area, and still rejected at the zone,
because the zone's check stands in front of the consultation rather
than in place of it.
"""

from __future__ import annotations

import pytest

from infra.security.loop_credentials import (
    ComponentCredentials,
    CredentialOperation,
    GrantedCredential,
    ImmutableZone,
    LoopCredentialPolicy,
    Permission,
    ZoneWriteAttempt,
    ZoneWriteDecision,
    ZoneWritePermissionRejected,
    ZoneWriteReason,
    authorize_zone_write,
    compile_loop_credential_policy,
)
from infra.security.tests.loop_credentials.helpers import (
    ARTIFACT_DROP_SIGNAL,
    EVALUATOR_IMAGE,
    POLICY_RUNTIME,
    SIGNAL_ROLE,
    SIGNAL_SANDBOX,
    SNAPSHOT_FILE,
    TRAILING_SLASH_LEDGER,
    TRAVERSAL_SIDECAR,
    TRIAL_LEDGER_DB,
    UNGRANTED_PLACE,
    UNKNOWN_OPERATION,
    UNKNOWN_ORIGIN,
    WORK_AREA_SIGNAL,
    ZONE_CONTRACT,
    ZONE_COST_MODEL,
    ZONE_NAME,
    ZONE_NEIGHBOUR,
    ZONE_SNAPSHOTS,
    ZONE_TRIAL_LEDGER,
    document_with_extra_permission,
    document_with_zone_write,
)

# Every write-side operation the vocabulary names — the enumeration
# "every write" has to cover at the gate.
_ALL_WRITES = [op.value for op in CredentialOperation.write_vocabulary()]


def _attempt(
    origin: str = SIGNAL_SANDBOX,
    path: str = TRIAL_LEDGER_DB,
    operation: str = "append",
) -> ZoneWriteAttempt:
    """One attempt, defaulted to the sentence's own shape: a component
    of the grant, a place of the zone, the ledger's own verb."""
    return ZoneWriteAttempt(origin=origin, path=path, operation=operation)


# ── every write at the zone, answered, never allowed ────────────────────


class TestEveryZoneWriteIsRejected:
    @pytest.mark.parametrize("operation", _ALL_WRITES)
    @pytest.mark.parametrize(
        "path",
        [
            ZONE_TRIAL_LEDGER,
            TRIAL_LEDGER_DB,
            SNAPSHOT_FILE,
            EVALUATOR_IMAGE,
            TRAILING_SLASH_LEDGER,
        ],
    )
    def test_every_operation_at_every_spelling_is_rejected(
        self, policy, operation: str, path: str
    ) -> None:
        decision = authorize_zone_write(
            _attempt(path=path, operation=operation), policy
        )
        assert decision.allowed is False
        assert (
            decision.reason
            is ZoneWriteReason.NO_WRITE_CREDENTIAL_FOR_IMMUTABLE_ZONE
        )

    @pytest.mark.parametrize("operation", _ALL_WRITES)
    def test_a_traversal_shaped_zone_write_is_rejected(
        self, policy, operation: str
    ) -> None:
        """The attempt is answered on where its path resolves, not on
        how it was typed."""
        decision = authorize_zone_write(
            _attempt(path=TRAVERSAL_SIDECAR, operation=operation), policy
        )
        assert decision.allowed is False
        assert (
            decision.reason
            is ZoneWriteReason.NO_WRITE_CREDENTIAL_FOR_IMMUTABLE_ZONE
        )

    @pytest.mark.parametrize("operation", _ALL_WRITES)
    def test_the_other_component_is_rejected_too(
        self, policy, operation: str
    ) -> None:
        decision = authorize_zone_write(
            ZoneWriteAttempt(
                origin=POLICY_RUNTIME,
                path=ZONE_COST_MODEL,
                operation=operation,
            ),
            policy,
        )
        assert decision.allowed is False
        assert (
            decision.reason
            is ZoneWriteReason.NO_WRITE_CREDENTIAL_FOR_IMMUTABLE_ZONE
        )

    def test_the_headline_names_the_zone_and_the_component(
        self, policy
    ) -> None:
        decision = authorize_zone_write(_attempt(), policy)
        assert ZONE_NAME in decision.detail
        assert SIGNAL_SANDBOX in decision.detail
        assert "'append'" in decision.detail

    def test_the_headline_quotes_the_architectures_own_line(
        self, policy
    ) -> None:
        """The rejection says the true thing in §2's words: not "you
        are not allowed" but "the set holds no write capability for
        it"."""
        decision = authorize_zone_write(_attempt(), policy)
        assert "no write capability" in decision.detail
        assert "Z1 has no credential for Z0" in decision.detail

    def test_an_operation_the_vocabulary_cannot_name_is_not_a_read(
        self, policy
    ) -> None:
        """The zone answers nothing it cannot name — the unnamed
        spelling earns the same headline, which is what makes "every
        write" total rather than enumerated."""
        decision = authorize_zone_write(
            _attempt(operation=UNKNOWN_OPERATION), policy
        )
        assert decision.allowed is False
        assert (
            decision.reason
            is ZoneWriteReason.NO_WRITE_CREDENTIAL_FOR_IMMUTABLE_ZONE
        )
        assert "not of the credential vocabulary" in decision.detail

    @pytest.mark.parametrize("operation", ["", "WRITE", "touch"])
    def test_hostile_operation_spellings_are_answered(
        self, policy, operation: str
    ) -> None:
        """Well-formed and hostile alike: answered, raised for none."""
        decision = authorize_zone_write(
            _attempt(operation=operation), policy
        )
        assert isinstance(decision, ZoneWriteDecision)
        assert decision.allowed is False

    def test_a_non_string_path_is_answered_not_raised(self, policy) -> None:
        attempt = ZoneWriteAttempt(
            origin=SIGNAL_SANDBOX, path=None, operation="write"  # type: ignore[arg-type]
        )
        decision = authorize_zone_write(attempt, policy)
        assert decision.allowed is False
        assert decision.reason is ZoneWriteReason.NO_PERMISSION


# ── reads at the zone: read-only, not unreadable ────────────────────────


class TestZoneReads:
    def test_a_granted_read_at_the_zone_is_allowed(
        self, policy
    ) -> None:
        decision = authorize_zone_write(
            ZoneWriteAttempt(
                origin=POLICY_RUNTIME,
                path=ZONE_CONTRACT + "/windows.py",
                operation="read",
            ),
            policy,
        )
        assert decision.allowed is True
        assert decision.reason is ZoneWriteReason.BY_PERMISSION

    def test_an_ungranted_read_at_the_zone_holds_nothing(
        self, policy
    ) -> None:
        """The zone is read-only, not unreadable — but this component's
        set grants nothing on this member, so the attempt holds no
        capability at all."""
        decision = authorize_zone_write(
            ZoneWriteAttempt(
                origin=SIGNAL_SANDBOX,
                path=ZONE_SNAPSHOTS,
                operation="read",
            ),
            policy,
        )
        assert decision.allowed is False
        assert decision.reason is ZoneWriteReason.NO_PERMISSION
        assert "read-only, not unreadable" in decision.detail


# ── the grant's own places: where the set really holds ──────────────────


class TestGrantedPlaces:
    @pytest.mark.parametrize(
        ("path", "operation"),
        [
            (WORK_AREA_SIGNAL, "write"),
            (WORK_AREA_SIGNAL, "create"),
            (WORK_AREA_SIGNAL + "/campaign-9/prop-7.py", "write"),
            (WORK_AREA_SIGNAL, "append"),
            (WORK_AREA_SIGNAL + "/scratch.bin", "delete"),
            (ARTIFACT_DROP_SIGNAL + "/prop-7.py", "create"),
        ],
    )
    def test_the_work_areas_answer_by_permission(
        self, policy, path: str, operation: str
    ) -> None:
        decision = authorize_zone_write(
            _attempt(path=path, operation=operation), policy
        )
        assert decision.allowed is True
        assert decision.reason is ZoneWriteReason.BY_PERMISSION

    def test_the_allowed_decision_names_the_credential(
        self, policy
    ) -> None:
        """The allowed decision cites its evidence — the permission
        that earned it, the way the zone rejection cites the zone."""
        decision = authorize_zone_write(
            _attempt(path=WORK_AREA_SIGNAL, operation="write"), policy
        )
        assert SIGNAL_ROLE in decision.detail
        assert WORK_AREA_SIGNAL in decision.detail
        assert "outside the immutable zone" in decision.detail

    def test_an_ungranted_place_outside_the_zone_holds_nothing(
        self, policy
    ) -> None:
        decision = authorize_zone_write(
            _attempt(path=UNGRANTED_PLACE, operation="write"), policy
        )
        assert decision.allowed is False
        assert decision.reason is ZoneWriteReason.NO_PERMISSION

    def test_a_neighbour_of_the_zone_is_not_the_zone(self, policy) -> None:
        """Segment-wise containment: the headline is the zone's own,
        and a prefix-shared neighbour falls to the consultation."""
        decision = authorize_zone_write(
            _attempt(path=ZONE_NEIGHBOUR, operation="write"), policy
        )
        assert decision.allowed is False
        assert decision.reason is ZoneWriteReason.NO_PERMISSION

    @pytest.mark.parametrize(
        "path", ["work/out.py", "z0/trial-ledger/trials.db", ""]
    )
    def test_a_relative_path_is_never_allowed(self, policy, path: str) -> None:
        """The grant's vocabulary is absolute; a relative place is
        wherever a hostile reader's working directory left it, so no
        permission can cover it and the attempt is rejected."""
        decision = authorize_zone_write(
            _attempt(path=path, operation="write"), policy
        )
        assert decision.allowed is False
        assert decision.reason is ZoneWriteReason.NO_PERMISSION


# ── the origin: membership is how the law is inherited ──────────────────


class TestOrigins:
    def test_an_unlisted_component_holds_nothing_at_all(
        self, policy
    ) -> None:
        decision = authorize_zone_write(
            _attempt(origin=UNKNOWN_ORIGIN, path=TRIAL_LEDGER_DB), policy
        )
        assert decision.allowed is False
        assert decision.reason is ZoneWriteReason.UNKNOWN_COMPONENT

    def test_the_origin_is_settled_before_the_zone(self, policy) -> None:
        """The order of the checks is the order of the sentence: the
        gate answers for the compiled grant's components first, so an
        unknown origin writing the zone is unknown, not headline."""
        decision = authorize_zone_write(
            _attempt(origin=UNKNOWN_ORIGIN), policy
        )
        assert decision.reason is ZoneWriteReason.UNKNOWN_COMPONENT
        assert "vouches for nothing" in decision.detail

    def test_an_unlisted_component_cannot_write_anywhere_either(
        self, policy
    ) -> None:
        decision = authorize_zone_write(
            ZoneWriteAttempt(
                origin=UNKNOWN_ORIGIN,
                path=WORK_AREA_SIGNAL,
                operation="write",
            ),
            policy,
        )
        assert decision.allowed is False
        assert decision.reason is ZoneWriteReason.UNKNOWN_COMPONENT


# ── the derivation: the consultation is real, the zone outranks it ──────


def _rogue_policy() -> LoopCredentialPolicy:
    """A hand-assembled grant holding a write directly on the zone.

    No compiled policy can look like this (the compile refuses a zone
    write in any spelling), which is precisely why the gate's behaviour
    on it is informative: it shows what the consultation alone would
    do — and therefore that the zone rejection on compiled policies
    stands in front of the consultation rather than in place of it.
    """
    rogue = Permission(
        path=ZONE_TRIAL_LEDGER,
        operations=frozenset({"read", "write", "append"}),
    )
    scratch = Permission(
        path="/zones/z1/rogue/work",
        operations=frozenset({"write"}),
    )
    return LoopCredentialPolicy(
        kind="loop-credentials",
        immutable_zone=ImmutableZone(
            name=ZONE_NAME,
            paths=(ZONE_SNAPSHOTS, ZONE_TRIAL_LEDGER),
        ),
        components={
            "rogue": ComponentCredentials(
                name="rogue",
                credentials=(
                    GrantedCredential(
                        name="rogue-role", permissions=(rogue, scratch)
                    ),
                ),
            )
        },
    )


class TestTheDerivationIsReal:
    def test_the_consultation_alone_would_allow_the_zone_write(self) -> None:
        """The set genuinely holds the rogue write — the gate's
        rejection is a check in front of a real consultation, not an
        artifact of consulting an empty set."""
        rogue = _rogue_policy()
        assert rogue.component("rogue").permits(ZONE_TRIAL_LEDGER, "write")

    def test_the_gate_still_rejects_the_zone_write(self) -> None:
        """§2's line outranks everything: even a rogue, hand-assembled
        grant can never read as permission to write the zone."""
        decision = authorize_zone_write(
            ZoneWriteAttempt(
                origin="rogue", path=TRIAL_LEDGER_DB, operation="write"
            ),
            _rogue_policy(),
        )
        assert decision.allowed is False
        assert (
            decision.reason
            is ZoneWriteReason.NO_WRITE_CREDENTIAL_FOR_IMMUTABLE_ZONE
        )

    def test_the_same_consultation_allows_the_scratch_write(self) -> None:
        """The very same set, the very same consultation — allowed
        outside the zone. The difference is the zone check, written,
        not a hardcoded denial."""
        decision = authorize_zone_write(
            ZoneWriteAttempt(
                origin="rogue",
                path="/zones/z1/rogue/work/out.py",
                operation="write",
            ),
            _rogue_policy(),
        )
        assert decision.allowed is True
        assert decision.reason is ZoneWriteReason.BY_PERMISSION

    @pytest.mark.parametrize(
        "operation", _ALL_WRITES + ["read", "list", "stat"]
    )
    @pytest.mark.parametrize(
        "path",
        [
            ZONE_TRIAL_LEDGER,
            TRIAL_LEDGER_DB,
            ZONE_SNAPSHOTS + "/w42.parquet",
            WORK_AREA_SIGNAL,
            UNGRANTED_PLACE,
        ],
    )
    def test_no_allowed_decision_is_ever_aimed_at_the_zone(
        self, policy, operation: str, path: str
    ) -> None:
        """The audit property, swept: across every operation of the
        vocabulary and every place, on a compiled policy — an allowed
        decision's path is never inside the immutable zone."""
        decision = authorize_zone_write(
            _attempt(path=path, operation=operation), policy
        )
        if decision.allowed:
            assert not policy.immutable_zone.covers(path)

    @pytest.mark.parametrize("operation", _ALL_WRITES)
    def test_the_audit_property_survives_even_a_rogue_grant(
        self, operation: str
    ) -> None:
        """And on the rogue one: the zone check stands in front of the
        consultation, so no write — named or not — can read as allowed
        at the zone even when the set says it can.  (A rogue *read* at
        the zone is the consultation's own business: reads are not this
        feature's subject, writes are.)"""
        rogue = _rogue_policy()
        decision = authorize_zone_write(
            ZoneWriteAttempt(
                origin="rogue",
                path=ZONE_TRIAL_LEDGER,
                operation=operation,
            ),
            rogue,
        )
        if decision.allowed:
            assert not rogue.immutable_zone.covers(ZONE_TRIAL_LEDGER)


# ── the gate consults the compiled set, whatever wrote it ───────────────


class TestTheGateConsults:
    def test_a_new_permission_changes_the_answer(self) -> None:
        """The grant is consulted, not cached in the gate's prose: a
        compiled policy that grants a new place answers attempts at it
        differently."""
        policy = compile_loop_credential_policy(
            document_with_extra_permission(
                {"path": "/zones/z1/new-area", "operations": ["write"]}
            )
        )
        decision = authorize_zone_write(
            _attempt(path="/zones/z1/new-area/x", operation="write"), policy
        )
        assert decision.allowed is True

    def test_a_zone_write_in_the_document_never_reaches_the_gate(
        self,
    ) -> None:
        """The compile-time and answer-time halves are one law: the
        document that would put a zone write in the set is refused
        before any gate exists to consult it."""
        with pytest.raises(ZoneWritePermissionRejected):
            compile_loop_credential_policy(
                document_with_zone_write(ZONE_TRIAL_LEDGER, ["append"])
            )
