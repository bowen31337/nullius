"""Feature 147: the geometry — where the immutable zone is.

The mount cannot refuse a write onto the zone and the gate cannot answer one
with the zone's own words unless the geometry said which paths are the zone.
The tests below assert recognition is exact: a member is inside, a neighbour
is outside, a traversal-shaped spelling resolves in, and a covering path —
the parent — is recognized for what it is.  The last group proves the
geometry fails closed on a geometry it cannot read.
"""

from __future__ import annotations

import pytest

from infra.security.tests.zone_mount.helpers import (
    ZONE_NEIGHBOUR,
    ZONE_PARENT,
    ZONE_TRIAL_LEDGER,
)
from infra.security.zone_mount import (
    MOUNT_POINT,
    ZONE_PATHS,
    ZoneGeometry,
    ZoneMountError,
    mount_geometry,
)


class TestRecognitionIsExact:
    """A member is inside; everything else is not, for the right reason."""

    def test_a_member_root_is_inside(self) -> None:
        """The zone's own roots are the zone."""
        geometry = mount_geometry()
        assert geometry.covers(ZONE_TRIAL_LEDGER)

    def test_a_place_deep_inside_a_member_is_inside(self) -> None:
        """Containment is segment-wise and deep: a file three levels into a
        member is inside the zone."""
        geometry = mount_geometry()
        assert geometry.covers("/zones/z0/trial-ledger/2026/trials.db")

    def test_a_neighbour_is_outside(self) -> None:
        """A place whose spelling begins like the zone's but is a different
        segment — ``/zones/z0-sidecar`` — is a neighbour, not a member."""
        geometry = mount_geometry()
        assert not geometry.covers(ZONE_NEIGHBOUR)

    def test_the_mount_point_itself_is_outside(self) -> None:
        """The mount point ``/zones`` is the zone's parent's parent: not a
        member, so not inside — the covering paths are the boundary."""
        geometry = mount_geometry()
        assert not geometry.covers(MOUNT_POINT)

    @pytest.mark.parametrize("spelling", [
        "/zones/z0/trial-ledger/",
        "/zones/z0/trial-ledger/./trials.db",
        "/zones/z0/../z0/trial-ledger/trials.db",
    ])
    def test_a_traversal_or_trailing_slash_resolves_in(self, spelling: str) -> None:
        """Containment is decided on where the path resolves, not how it was
        typed: a trailing slash or a ``..`` walk into a member is inside."""
        geometry = mount_geometry()
        assert geometry.covers(spelling)

    def test_a_relative_path_is_nowhere(self) -> None:
        """A relative place resolves nowhere the zone pinned, so it is not
        inside — a permission that moves with the reader is not a member."""
        geometry = mount_geometry()
        assert not geometry.covers("z0/trial-ledger")

    def test_a_non_string_is_nowhere(self) -> None:
        """Hostile shapes included: a non-string path is not inside."""
        geometry = mount_geometry()
        assert not geometry.covers(None)


class TestCoveringPaths:
    """The parent of a member reaches every child — recognized as covering."""

    def test_covering_names_the_member_containing_an_inside_path(self) -> None:
        """For a path inside a member, ``covering`` names that member — the
        first in document order that contains it, so a refusal is findable
        in the file it was written in."""
        geometry = mount_geometry()
        assert geometry.covering("/zones/z0/trial-ledger/trials.db") == (
            "/zones/z0/trial-ledger"
        )

    def test_covering_is_none_for_a_path_that_contains_a_member(self) -> None:
        """A path that contains a member — the parent ``/zones/z0`` — is not
        itself contained by any member, so ``covering`` (which names the
        member a path is inside) returns ``None``. The gate handles a write
        on such a covering path separately, refusing it in the zone's words
        without naming a member it does not sit inside."""
        geometry = mount_geometry()
        assert geometry.covering(ZONE_PARENT) is None

    def test_covering_is_none_for_a_neighbour(self) -> None:
        """A neighbour — ``/zones/z0-sidecar`` — is contained by no member."""
        geometry = mount_geometry()
        assert geometry.covering(ZONE_NEIGHBOUR) is None

    def test_a_member_root_is_covered_by_its_parent(self) -> None:
        """The covering relation the gate relies on: a member root lies under
        its parent, so a write on the parent reaches it."""
        geometry = mount_geometry()
        assert geometry.covering("/zones/z0/snapshots") == "/zones/z0/snapshots"


class TestTheGeometryFailsClosed:
    """A geometry that cannot read the zone cannot refuse a write onto it."""

    def test_no_member_roots_is_refused(self) -> None:
        """A zone with no paths names the zone nowhere."""
        with pytest.raises(ZoneMountError):
            ZoneGeometry(name="z0", paths=())

    def test_a_relative_root_is_refused(self) -> None:
        """A member root that resolves nowhere the mount pinned is refused."""
        with pytest.raises(ZoneMountError):
            ZoneGeometry(name="z0", paths=["z0/trial-ledger"])

    def test_the_filesystem_root_is_refused(self) -> None:
        """A ``/`` root makes the whole filesystem the zone — refused, so the
        geometry keeps saying which place is immutable."""
        with pytest.raises(ZoneMountError):
            ZoneGeometry(name="z0", paths=["/"])

    def test_a_member_inside_a_member_is_refused(self) -> None:
        """A member inside a member adds no place while suggesting the
        smaller one is separately negotiable — the zone is not à la carte."""
        with pytest.raises(ZoneMountError):
            ZoneGeometry(
                name="z0",
                paths=["/zones/z0", "/zones/z0/trial-ledger"],
            )

    def test_the_geometry_carries_its_six_members(self) -> None:
        """The committed geometry is exactly the six §2 roots."""
        geometry = mount_geometry()
        assert geometry.paths == ZONE_PATHS
        assert len(geometry.paths) == 6
