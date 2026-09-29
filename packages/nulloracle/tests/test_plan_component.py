"""Feature 122's plugin seam and its read through the composed application.

``test_component.py`` pins feature 109's registration, ``test_guard_component.py``
feature 123's, ``test_phi_component.py`` feature 117's, ``test_flip_depth_component.py``
feature 119's, ``test_irprob_component.py`` feature 120's and
``test_type_r_selection_component.py`` feature 118's; this pins feature 122's —
the member's *ninth* component, and the second whose builder needs two things
to resolve rather than one.

Three things make it worth its own suite rather than a section of feature
118's:

* **the member now registers nine components, and every new one re-runs the
  registration trap.**  All nine ``@register`` calls live in the package's
  ``__init__``, and the loader re-executes ``__init__`` on every
  ``create_app()`` while caching submodules — so a registration that lived in
  ``nulloracle.plan`` would fire on the first composition of a process and
  silently drop out of every later one.  The second-application assertion
  below is what catches that, and a single-composition test would pass for
  it.

* **the component needs two composed halves, like the selection's.**  Most
  components resolve from a single source.  This one's store reads the campaign row and the tree's flip depths from a relational
  database *and* the root selections from §7.1's sidecar, so the composed
  component exists only where both resolve — and ``None`` therefore means
  *one of the two is unconfigured*, never *the tree is homogeneous*, which is
  a fact about a world and not about a deployment.  The half-configured
  cases are pinned individually, because a builder that resolved only one
  half would compose a gate that could see flips but not selections — and
  would answer ``homogeneous`` for worlds it never looked at, which is
  precisely the failure feature 122 exists to rule out.

* **the component's name had to be chosen.**
  ``app.order`` is name-sorted, and feature 123's guard must stay immediately
  after the sidecar in it; a ``c...``-prefixed component name would have
  sorted between them and silently broken that adjacency.  The ``plan-``
  prefix lands after the ``ks-*`` and ``null-*`` families and before the
  ``true-ir-*`` and ``type-*`` ones, and the ordering assertions below pin
  both directions so the choice cannot be unmade by a rename nobody reviews.

The load-bearing property is unchanged and restated because the consequence
is the same as the selection's: **the builder must never raise.**  It
resolves ``DATABASE_URL`` and the sidecar's two variables, all of which the
whole workspace shares, so a builder that raised on a scheme it cannot speak
or a key reference it cannot parse would take composition down for every
unrelated feature in the process.
"""

from __future__ import annotations

import inspect
import uuid
from pathlib import Path

import pytest
from nulloracle import (
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    FLIP_DEPTH_COMPONENT_NAME,
    FRACTION_COMPONENT_NAME,
    KEY_REF_ENV,
    KS_GUARD_COMPONENT_NAME,
    NODE_TABLE,
    PLAN_COMPONENT_NAME,
    RESOLUTION_COMPONENT_NAME,
    SIDECAR_PATH_ENV,
    TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
    TYPE_R_COMPONENT_NAME,
    VERDICT_COMPONENT_NAME,
)
from nulloracle import (
    COMPONENT_NAME as SIDECAR_COMPONENT_NAME,
)

from app.module_loader import Application, create_app, scan_components

#: The 32-byte test key the member's conftest and suites use. Not a secret
#: and not derived from anything: every assertion about "the right key opens
#: it" is really an assertion that the same bytes were used twice.
TEST_KEY_HEX = "0f" * 32

#: A campaign id that is a canonical UUID, so a test about the *seam* is never
#: accidentally about id validation.
CAMPAIGN = "7c2e1a40-0000-4000-8000-000000000122"


@pytest.fixture(autouse=True)
def _no_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test in this module with neither half configured.

    The member's conftest isolates the sidecar's environment — but this
    component's builder *reads* that environment, so a test that wants a
    composed gate has to say so explicitly rather than inherit a
    configuration from whatever invoked pytest.  The database URL is dropped
    here too: it is a variable the whole workspace shares.
    """
    for name in (DATABASE_URL_ENV, SIDECAR_PATH_ENV, KEY_REF_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def both_halves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, Path]:
    """Configure a relational store *and* a sidecar: a composeable deployment."""
    url = f"sqlite:///{tmp_path / 'plan.db'}"
    path = tmp_path / "z0" / "null" / "sidecar.enc"
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    monkeypatch.setenv(SIDECAR_PATH_ENV, str(path))
    monkeypatch.setenv(KEY_REF_ENV, f"hex:{TEST_KEY_HEX}")
    return url, path


def _assert_is_the_campaign_plan_gate(component: object) -> None:
    # The two-module-worlds wrinkle the selection's component suite states:
    # the factory's scan may import the member under a synthetic name, so
    # identity is asserted on the type's own name and module tail rather
    # than with ``isinstance`` against the package's class.
    assert type(component).__name__ == "CampaignPlanGate"
    assert type(component).__module__.endswith("nulloracle.plan")
    assert callable(component.review)


# -- The registration ---------------------------------------------------------------


class TestThePlanGateComponentRegisters:
    def test_the_member_registers_the_plan_gate_component(self) -> None:
        names = [component.name for component in scan_components()]
        assert PLAN_COMPONENT_NAME in names

    def test_the_component_name_is_the_expected_spelling(self) -> None:
        # The hyphen-free ``nulloracle`` prefix is the plugin name the spec's
        # features carry, and the ``plan-`` family prefix places this component
        # after the ``ks-*`` and ``null-*`` families and before the
        # ``true-ir-*`` and ``type-*`` ones in the name-sorted ``app.order`` —
        # the placement that leaves feature 123's guard immediately after the
        # sidecar, pinned by the ordering assertions below.
        assert PLAN_COMPONENT_NAME == "nulloracle-plan-gate"

    def test_the_nine_component_names_are_distinct(self) -> None:
        # Feature 122's component is not a second component under any other
        # name: the nine hold different things on different lifecycles (§7.1's
        # sealed file, the guard journal, the verdict, the fraction, the flip
        # depth, the Type-D resolution, the true-IR probability, the Type-R
        # selection and this gate), and a deployment can carry any of them
        # without the others.
        names = {
            SIDECAR_COMPONENT_NAME,
            KS_GUARD_COMPONENT_NAME,
            VERDICT_COMPONENT_NAME,
            FRACTION_COMPONENT_NAME,
            FLIP_DEPTH_COMPONENT_NAME,
            RESOLUTION_COMPONENT_NAME,
            TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
            TYPE_R_COMPONENT_NAME,
            PLAN_COMPONENT_NAME,
        }
        assert len(names) == 9
        assert PLAN_COMPONENT_NAME not in {
            TYPE_R_COMPONENT_NAME,
            RESOLUTION_COMPONENT_NAME,
            FLIP_DEPTH_COMPONENT_NAME,
        }

    def test_create_app_composes_a_gate_when_both_halves_are_configured(
        self, both_halves: tuple[str, Path]
    ) -> None:
        app = create_app()
        _assert_is_the_campaign_plan_gate(app.get(PLAN_COMPONENT_NAME))
        assert PLAN_COMPONENT_NAME in app
        assert PLAN_COMPONENT_NAME in app.order

    def test_composing_touches_no_file(self, both_halves: tuple[str, Path]) -> None:
        # Construction performs no I/O: the gate resolves its path on first
        # use and the sidecar opens nothing until the first review.  That
        # laziness is why a composed application can carry this component in
        # a process that is not the account §7.1's file is readable by.
        _url, sidecar_path = both_halves
        app = create_app()
        assert app.get(PLAN_COMPONENT_NAME) is not None
        assert not sidecar_path.exists()

    def test_an_environment_with_no_database_url_still_composes(self) -> None:
        # The load-bearing property: with no relational store at all, the
        # builder returns None and the application composes with every other
        # member intact.
        app = create_app()
        assert app.get(PLAN_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_a_database_with_no_sidecar_composes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Half a configuration is not a configuration, and for this gate it
        # is the dangerous half: a gate holding only the database could read
        # the tree's flips but not the sidecar's selections, and a review
        # that answered "homogeneous" off it would bless every mixed world
        # it was shown — so the builder composes nothing rather than a
        # half-gate.
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'plan.db'}")
        app = create_app()
        assert app.get(PLAN_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_a_sidecar_with_no_database_composes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The other half: a sidecar with no tree to read the campaign's
        # declaration and flip depths from has nothing to compare.
        monkeypatch.setenv(SIDECAR_PATH_ENV, str(tmp_path / "sidecar.enc"))
        monkeypatch.setenv(KEY_REF_ENV, f"hex:{TEST_KEY_HEX}")
        app = create_app()
        assert app.get(PLAN_COMPONENT_NAME) is None

    def test_the_builder_never_raises_on_an_unspeakable_scheme(
        self, both_halves: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A deployment that named a Postgres store is expecting a gate, and
        # this one's scheme check is lazy — the URL is refused at the first
        # review, not at composition.  That laziness is the point: the
        # factory builds every registered component on every create_app(),
        # so a builder that raised on a scheme it cannot speak would take
        # down every other member's component too.
        monkeypatch.setenv(DATABASE_URL_ENV, "postgres:///db")
        app = create_app()
        component = app.get(PLAN_COMPONENT_NAME)
        assert type(component).__name__ == "CampaignPlanGate"
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_a_blank_scheme(
        self, both_halves: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A whitespace-only URL counts as unset: resolve() returns None
        # rather than constructing a gate that would fail at first use.
        monkeypatch.setenv(DATABASE_URL_ENV, "   ")
        app = create_app()
        assert app.get(PLAN_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_an_unspeakable_key_reference(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The sidecar's own resolution degrades on a key it cannot supply,
        # and that degradation must reach this builder as "no sidecar", not
        # as an exception: a ``kms:`` reference in a deployment that cannot
        # speak KMS is an unconfigured half, and one member's unconfigured
        # environment is not a fault the other members should pay for.
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'plan.db'}")
        monkeypatch.setenv(SIDECAR_PATH_ENV, str(tmp_path / "sidecar.enc"))
        monkeypatch.setenv(KEY_REF_ENV, "kms:arn:aws:kms:eu-west-1:0:key/not-here")
        app = create_app()
        assert app.get(PLAN_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_a_malformed_key_reference(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'plan.db'}")
        monkeypatch.setenv(SIDECAR_PATH_ENV, str(tmp_path / "sidecar.enc"))
        monkeypatch.setenv(KEY_REF_ENV, "a-bare-path-with-no-scheme")
        app = create_app()
        assert app.get(PLAN_COMPONENT_NAME) is None

    def test_the_component_survives_a_second_composition(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # Must assert on the SECOND application or it passes vacuously: the
        # loader re-executes __init__ on every create_app(), so a @register
        # that lived in ``nulloracle.plan`` would be present in the first
        # and absent here.
        create_app()
        second = create_app()
        _assert_is_the_campaign_plan_gate(second.get(PLAN_COMPONENT_NAME))

    def test_the_builder_is_on_the_package_import_path(self) -> None:
        import nulloracle

        assert callable(nulloracle.build_campaign_plan_gate)
        assert nulloracle.build_campaign_plan_gate.__module__.endswith("nulloracle")

    def test_the_builder_takes_no_arguments(self) -> None:
        # The factory's registration protocol: a builder is a zero-argument
        # callable, and a component that needed an argument could not be
        # composed by the scan at all.
        import nulloracle

        assert inspect.signature(nulloracle.build_campaign_plan_gate).parameters == {}

    def test_the_builder_never_raises_when_configured(
        self, both_halves: tuple[str, Path]
    ) -> None:
        import nulloracle

        assert nulloracle.build_campaign_plan_gate() is not None

    def test_the_builder_needs_no_database_url_argument(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # The resolution is the store's own, so the builder stays a
        # zero-argument callable the scan can invoke — the property every
        # component in this member shares.
        import nulloracle

        builder = nulloracle.build_campaign_plan_gate
        assert "database_url" not in inspect.signature(builder).parameters
        assert builder() is not None

    def test_composing_it_leaves_the_guard_adjacent_to_the_sidecar(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # The names are sorted, and feature 123's guard must stay immediately
        # after the sidecar in ``app.order``; the ``plan-`` prefix places this
        # component after both of them, so the adjacency is untouched.
        app = create_app()
        order = list(app.order)
        assert order.index(KS_GUARD_COMPONENT_NAME) == order.index(SIDECAR_COMPONENT_NAME) + 1

    def test_the_gate_sorts_after_the_null_families(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # The prefix is not cosmetic: ``app.order`` is name-sorted, and a
        # component named ``nulloracle-campaign-plan`` would have sorted
        # *between* the sidecar and the guard, silently breaking the
        # adjacency the previous assertion pins.
        app = create_app()
        order = list(app.order)
        assert order.index(PLAN_COMPONENT_NAME) > order.index(
            KS_GUARD_COMPONENT_NAME
        )
        assert order.index(PLAN_COMPONENT_NAME) > order.index(
            FRACTION_COMPONENT_NAME
        )

    def test_the_gate_sorts_before_the_true_ir_and_type_families(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # The other direction, pinned with it: the ``plan-`` family lands
        # before ``true-ir-*`` and ``type-*``, so the relative order the
        # member's components document — null families, then the planning gate,
        # then the regime writers — is the order the composed application
        # actually carries.
        app = create_app()
        order = list(app.order)
        assert order.index(PLAN_COMPONENT_NAME) < order.index(
            TRUE_IR_FLIP_DEPTH_COMPONENT_NAME
        )
        assert order.index(PLAN_COMPONENT_NAME) < order.index(
            TYPE_R_COMPONENT_NAME
        )


# -- Reading the composed component ---------------------------------------------


class TestReadingTheComposedComponent:
    """The component as ``create_app().get(...)`` hands it to a caller outside
    the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        import nulloracle

        assert (
            nulloracle.PLAN_COMPONENT_NAME
            == PLAN_COMPONENT_NAME
        )

    def test_the_application_exposes_the_composed_gate(
        self, both_halves: tuple[str, Path]
    ) -> None:
        _assert_is_the_campaign_plan_gate(create_app().get(PLAN_COMPONENT_NAME))

    def test_the_component_is_read_from_an_application_it_is_handed(self) -> None:
        application = Application(
            components={PLAN_COMPONENT_NAME: "sentinel"},
            order=(PLAN_COMPONENT_NAME,),
        )
        assert application.get(PLAN_COMPONENT_NAME) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        empty = Application(components={}, order=())
        assert empty.get(PLAN_COMPONENT_NAME) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(
        self,
    ) -> None:
        assert create_app().get(PLAN_COMPONENT_NAME) is None

    def test_a_half_configured_environment_yields_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # This component's ``None`` carries a second meaning worth stating: *one
        # of the gate's two halves is unconfigured*.  It must never be read
        # as *the tree is homogeneous* — that is a fact about a world, and
        # reading it off a deployment would let a mixed world through
        # believing it had been reviewed.
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'plan.db'}")
        assert create_app().get(PLAN_COMPONENT_NAME) is None

    def test_the_composed_component_can_review_a_homogeneous_world(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # Feature 122 through the composition, the quiet half: a Type-R
        # campaign whose selection is sealed reviews to the plan its writers
        # left behind — the path an assembled campaign loop takes after a
        # lawful planting.

        # Both stores from the one composed application — feature 118's
        # selection plants, feature 122's gate reviews — because the two
        # components come from the same *scanned* copy of the member: the
        # package's own ``TypeRSelection`` would refuse the composed gate's
        # sidecar on an ``isinstance`` check, being from a different module
        # object, and an assembled campaign loop holds exactly this pairing.
        app = create_app()
        gate = app.get(PLAN_COMPONENT_NAME)
        selection_store = app.get(TYPE_R_COMPONENT_NAME)
        assert gate is not None and selection_store is not None
        with gate._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, 'Type-R', 12, 0.1667)",
                (CAMPAIGN,),
            )
            for _ in range(12):
                connection.execute(
                    f"INSERT INTO {NODE_TABLE} (id, campaign_id, theme_root, depth) "
                    "VALUES (?, ?, 'macro', 0)",
                    (str(uuid.uuid4()), CAMPAIGN),
                )
        selection_store.persist(CAMPAIGN)
        plan = gate.review(CAMPAIGN)
        assert len(plan.root_selections) == 12
        assert plan.flip_branches == ()

    def test_the_composed_component_can_refuse_a_mixed_world(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # The sentence's own path, end to end through the composition: a flip
        # depth drawn onto a Type-R campaign's tree — the state feature 119's
        # writer does not type-check — and the composed gate pronouncing the
        # ``heterogeneous_world`` refusal on it.
        gate = create_app().get(PLAN_COMPONENT_NAME)
        assert gate is not None
        root = str(uuid.uuid4())
        with gate._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, 'Type-R', 12, 0.1667)",
                (CAMPAIGN,),
            )
            connection.execute(
                f"INSERT INTO {NODE_TABLE} (id, campaign_id, theme_root, depth, "
                "flip_depth) VALUES (?, ?, 'macro', 0, 3)",
                (root, CAMPAIGN),
            )
        # Caught by name, not by ``pytest.raises(HeterogeneousWorldError)``:
        # the composed gate's class is the *scanned* copy (the loader imports
        # each member under a synthetic module name), so the exception it
        # raises is not this suite's class object — the interoperability fact
        # ``test_guard_component.py`` documents, applying here unchanged.
        with pytest.raises(Exception) as raised:
            gate.review(CAMPAIGN)
        assert type(raised.value).__name__ == "HeterogeneousWorldError"
        assert str(raised.value).startswith("heterogeneous_world")

    def test_the_composition_answers_the_members_own_builder(self) -> None:
        # The composition and the builder cannot disagree about what the
        # component is: unconfigured, both answer None.
        import nulloracle

        assert nulloracle.build_campaign_plan_gate() is None
        assert create_app().get(PLAN_COMPONENT_NAME) is None
