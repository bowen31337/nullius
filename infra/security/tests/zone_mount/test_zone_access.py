"""Feature 147: the gate — every attempt answered, the zone's write always
rejected.

The sentence's consequent, at the seam untrusted code actually meets: *which
rejects a write attempt with a permission error message.*  An attempt is
hostile input by definition — it comes from agent-authored code — so the gate
answers with a decision for every shape and raises for none, the same stance
this category's other gates take.  What the tests below assert is which
*reason* each attempt earns, because the reason is the audit record: the
zone's own words for the zone, and a served read for everything a read-only
mount must serve.

The order of the checks is the order of the sentence: the zone is settled
first — §2's "read-only for every service" outranks everything — then the
mount point, then the operation, then the served read.
"""

from __future__ import annotations

import pytest

from infra.security.tests.zone_mount.helpers import (
    POLICY_RUNTIME,
    SIDECAR_KEY,
    SIGNAL_SANDBOX,
    SNAPSHOT_FILE,
    STAGING_PATH,
    TRAVERSAL_SIDECAR,
    TRIAL_LEDGER_DB,
    UNKNOWN_OPERATION,
    ZONE_NEIGHBOUR,
    ZONE_PARENT,
    zone_access_attempt,
)
from infra.security.zone_mount import (
    ZoneAccessAttempt,
    ZoneAccessDecision,
    ZoneAccessReason,
    authorize_zone_access,
)


class TestEveryZoneWriteIsRejected:
    """The headline: a write at the immutable zone is rejected, in the
    zone's own words."""

    @pytest.mark.parametrize("path", [
        TRIAL_LEDGER_DB,
        SNAPSHOT_FILE,
        SIDECAR_KEY,
    ])
    def test_a_write_inside_a_member_is_rejected(
        self, path: str
    ) -> None:
        """The core case: a write inside a zone member is rejected with the
        feature's own reason, not a generic denial."""
        decision = authorize_zone_access(zone_access_attempt(path=path, operation="write"))
        assert decision.allowed is False
        assert decision.reason is ZoneAccessReason.INSIDE_IMMUTABLE_ZONE

    def test_append_is_rejected(self) -> None:
        """The ledger's own verb — append — is refused onto the zone, the
        same way feature 148's credential law refuses it: the trial ledger's
        appends are the release process's to make."""
        decision = authorize_zone_access(
            zone_access_attempt(path=TRIAL_LEDGER_DB, operation="append")
        )
        assert decision.reason is ZoneAccessReason.INSIDE_IMMUTABLE_ZONE

    def test_chmod_is_rejected(self) -> None:
        """chmod is refused onto the zone — it would be reaching for the
        read-only mount itself."""
        decision = authorize_zone_access(
            zone_access_attempt(path=TRIAL_LEDGER_DB, operation="chmod")
        )
        assert decision.reason is ZoneAccessReason.INSIDE_IMMUTABLE_ZONE

    @pytest.mark.parametrize("path", [
        TRIAL_LEDGER_DB,
        "/zones/z0/trial-ledger/",
        "/zones/z0/../z0/trial-ledger/trials.db",
    ])
    def test_a_traversal_or_trailing_slash_spelling_is_rejected(
        self, path: str
    ) -> None:
        """'Any write attempt' includes any spelling: a traversal or a
        trailing slash that resolves into a member is rejected the same way,
        because containment is decided on where the path resolves."""
        decision = authorize_zone_access(zone_access_attempt(path=path, operation="write"))
        assert decision.reason is ZoneAccessReason.INSIDE_IMMUTABLE_ZONE

    def test_a_write_covering_a_member_is_rejected(self) -> None:
        """A write on the zone's parent — ``/zones/z0`` — reaches every
        child, so it is refused the same way a write inside a member is."""
        decision = authorize_zone_access(
            zone_access_attempt(path=ZONE_PARENT, operation="write")
        )
        assert decision.allowed is False
        assert decision.reason is ZoneAccessReason.INSIDE_IMMUTABLE_ZONE

    def test_a_write_on_the_zones_root_is_rejected(self) -> None:
        """A write on ``/zones`` covers the whole zone — refused."""
        decision = authorize_zone_access(
            zone_access_attempt(path="/zones", operation="write")
        )
        assert decision.reason is ZoneAccessReason.INSIDE_IMMUTABLE_ZONE

    def test_the_rejection_names_the_zone(self) -> None:
        """The detail is the finding an operator reads: it names the zone the
        attempt reached for."""
        decision = authorize_zone_access(
            zone_access_attempt(path=TRIAL_LEDGER_DB, operation="write")
        )
        assert "z0-immutable" in decision.detail

    def test_the_rejection_cites_read_only(self) -> None:
        """The detail quotes §2's posture — mounted read-only for every
        service — so the denial is traceable to the sentence."""
        decision = authorize_zone_access(
            zone_access_attempt(path=TRIAL_LEDGER_DB, operation="write")
        )
        assert "read-only" in decision.detail

    def test_the_attempt_is_answered_not_adopted(self) -> None:
        """Refusing is repeatable: the same attempt answered three times is
        rejected three times, in the same words — there is no state to wear
        down and no partial admit between refusals."""
        attempt = zone_access_attempt(path=TRIAL_LEDGER_DB, operation="write")
        decisions = [authorize_zone_access(attempt) for _ in range(3)]
        assert all(d.allowed is False for d in decisions)
        assert {d.reason for d in decisions} == {
            ZoneAccessReason.INSIDE_IMMUTABLE_ZONE
        }


class TestEveryServiceMeetsTheSameEmptiness:
    """The mount is the same for every service — the posture every service
    runs the zone under."""

    def test_the_signal_sandbox_is_rejected(self) -> None:
        """The first Z1 box: a write at the zone is rejected."""
        decision = authorize_zone_access(
            zone_access_attempt(path=TRIAL_LEDGER_DB, operation="write", service=SIGNAL_SANDBOX)
        )
        assert decision.reason is ZoneAccessReason.INSIDE_IMMUTABLE_ZONE

    def test_the_policy_runtime_is_rejected(self) -> None:
        """Membership, not name: the second Z1 box gets the same rejection."""
        decision = authorize_zone_access(
            zone_access_attempt(path=TRIAL_LEDGER_DB, operation="write", service=POLICY_RUNTIME)
        )
        assert decision.reason is ZoneAccessReason.INSIDE_IMMUTABLE_ZONE

    def test_the_service_is_carried_for_the_audit_line(self) -> None:
        """The claiming service rides the audit line, never widening the
        zone: a write from any service is still rejected."""
        decision = authorize_zone_access(
            zone_access_attempt(path=TRIAL_LEDGER_DB, operation="write", service="evaluator")
        )
        assert "evaluator" in decision.detail
        assert decision.allowed is False

    def test_a_blank_service_is_answered_not_crashed(self) -> None:
        """Hostile shapes included: a blank service still gets a decision,
        never an exception."""
        decision = authorize_zone_access(
            ZoneAccessAttempt(path=TRIAL_LEDGER_DB, operation="write", service="")
        )
        assert decision.allowed is False


class TestReadsAreServed:
    """A read-only mount is not a read-nothing one — §2's Z0 is readable."""

    @pytest.mark.parametrize("path", [TRIAL_LEDGER_DB, SNAPSHOT_FILE, SIDECAR_KEY])
    def test_a_read_inside_a_member_is_served(self, path: str) -> None:
        """Reading a sealed path is always allowed — the zone is readable,
        only its writes are refused."""
        decision = authorize_zone_access(zone_access_attempt(path=path, operation="read"))
        assert decision.allowed is True
        assert decision.reason is ZoneAccessReason.BY_READ

    def test_a_list_inside_a_member_is_served(self) -> None:
        """Listing a member is a read, and is served."""
        decision = authorize_zone_access(
            zone_access_attempt(path="/zones/z0/trial-ledger", operation="list")
        )
        assert decision.allowed is True
        assert decision.reason is ZoneAccessReason.BY_READ

    def test_a_stat_inside_a_member_is_served(self) -> None:
        """Stat-ing a member is a read, and is served."""
        decision = authorize_zone_access(
            zone_access_attempt(path=TRIAL_LEDGER_DB, operation="stat")
        )
        assert decision.allowed is True


class TestEverythingElse:
    """The mount has no outside, and answers nothing it cannot name."""

    def test_a_write_outside_the_zone_is_not_the_zones_to_refuse(self) -> None:
        """A write at a place outside the immutable zone is not the zone's to
        refuse — the mount governs only the zone, and a write elsewhere is
        feature 148's half, not this one."""
        decision = authorize_zone_access(
            zone_access_attempt(path="/zones/z1/signal-sandbox/work.py", operation="write")
        )
        assert decision.allowed is True
        assert decision.reason is ZoneAccessReason.BY_LOCATION

    def test_a_path_outside_the_mount_point_is_rejected(self) -> None:
        """A path outside the mount point — staging, where the writable area
        lives — is refused as an escape, not resolved to a disk location."""
        decision = authorize_zone_access(
            zone_access_attempt(path=STAGING_PATH, operation="write")
        )
        assert decision.allowed is False
        assert decision.reason is ZoneAccessReason.OUTSIDE_MOUNT_POINT

    def test_an_unnamed_operation_is_rejected(self) -> None:
        """An operation the closed vocabulary cannot name is rejected — the
        zone answers nothing it cannot name, so an unnamed verb is not a
        read and certifies nothing."""
        decision = authorize_zone_access(
            zone_access_attempt(path=TRIAL_LEDGER_DB, operation=UNKNOWN_OPERATION)
        )
        assert decision.allowed is False
        assert decision.reason is ZoneAccessReason.UNNAMED_OPERATION

    def test_a_neighbour_is_not_the_zone(self) -> None:
        """A place that begins like the zone's but is a different segment is
        not inside — the gate does not widen the zone to a neighbour."""
        decision = authorize_zone_access(
            zone_access_attempt(path=ZONE_NEIGHBOUR, operation="write")
        )
        # Not inside the zone, but under the mount point and a write — so it
        # is allowed by location, not refused as a zone write.
        assert decision.allowed is True
        assert decision.reason is ZoneAccessReason.BY_LOCATION


class TestHostileShapesGetDecisions:
    """A gate that answers untrusted code cannot be crashed by it."""

    @pytest.mark.parametrize(
        ("path", "operation"),
        [
            (TRIAL_LEDGER_DB, "write"),
            ("", "write"),
            (None, "write"),
            (TRIAL_LEDGER_DB, ""),
            (TRAVERSAL_SIDECAR, "append"),
        ],
        ids=[
            "well-formed",
            "blank-path-write",
            "null-path-write",
            "blank-operation",
            "traversal-append",
        ],
    )
    def test_every_attempt_shape_is_answered(
        self, path, operation
    ) -> None:
        """Whatever the attempt carries, the gate returns a decision and
        never raises — the zone check is computed over a pinned geometry,
        which is shape-proof by construction."""
        decision = authorize_zone_access(
            ZoneAccessAttempt(path=path, operation=operation, service=SIGNAL_SANDBOX)
        )
        assert isinstance(decision, ZoneAccessDecision)

    def test_a_none_operation_is_answered_not_crashed(self) -> None:
        """A null operation is not of the vocabulary — answered, not
        crashed."""
        decision = authorize_zone_access(
            ZoneAccessAttempt(path=TRIAL_LEDGER_DB, operation=None, service=SIGNAL_SANDBOX)
        )
        assert isinstance(decision, ZoneAccessDecision)
