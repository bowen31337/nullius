"""Feature 267's composition: the third registration.

The FDR_deploy store is the member's second component beside the
objective and its first store-bound one, and this suite pins the growth
from the member's side: the third ``@register`` in ``scoring/__init__.py``
(all builders fire from the one file, the convention the loader's
synthetic-name re-execution demands), the name's two spellings
agreeing, and the composed application carrying the store key —
``create_app().get("scoring-fdr-deploy")`` answers *what is the composed
FDR_deploy store?*, the same shape of question the objective's name
(``scoring``) answers for feature 256 and the scorer's
(``scoring-null-pick-rate``) for 265: the growth this member's own
registration reserved when 265 landed.

**Why this component degrades where the objective never can.**  The
objective's builder cannot fail and reads no environment, so its
``None`` can only mean the member was absent from the scan.  This
builder composes *deployment state*: it resolves the database the
environment names, and where nothing names one it answers ``None`` —
contributing no store, never failing composition.  The two ``None``s
are different facts with different repairs (composition against
configuration), and the tests here pin that the store's ``None`` is
the deployment-shaped one: the key is present in the composed
application (the registration fired; ``order`` records it) while the
value is ``None`` (no database to hold).  A caller that needs to
persist a campaign's figure must refuse on that ``None`` rather than
read it as a trend of zero rows — the empty history is a measurement of
what has been closed out, and absence is not.

What these tests deliberately do not reach: the store's own laws
(``test_fdr_store.py``), the free verb's (``test_fdr.py``), and the
objective's own composition (``test_component.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import scoring as member

from app.module_loader import Application, create_app


def test_the_two_spellings_of_the_name_agree() -> None:
    # The member's surface and the law module's own (the one spelling,
    # imported into the surface rather than restated so the two cannot
    # drift) are one string — and the prefix keeps the store sorting
    # beside, never inside, the member's other components.
    assert member.FDR_COMPONENT_NAME == "scoring-fdr-deploy"
    assert member._fdr.FDR_COMPONENT_NAME == member.FDR_COMPONENT_NAME


def test_the_scanned_application_carries_the_store_key() -> None:
    # The registration fired: the composed application carries the key
    # and its order records the composition — even though this suite's
    # environment names no database, so the value composed under it is
    # None (the next test).  The key and the value are different facts.
    app = create_app()
    assert member.FDR_COMPONENT_NAME in app
    assert member.FDR_COMPONENT_NAME in app.order
    # And the growth sorts beside, never inside: name-sorted, the three
    # components of this member stand in the order their names spell.
    order = list(app.order)
    assert (
        order.index(member.COMPONENT_NAME)
        < order.index(member.FDR_COMPONENT_NAME)
        < order.index(member.SCORER_COMPONENT_NAME)
    )
    # And the other two components are untouched by the growth: the
    # three registrations coexist, each under its own name.
    assert app.get(member.COMPONENT_NAME) is not None


def test_the_builder_composes_none_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Nothing names a relational store (the conftest's autouse scrub
    # holds for the whole suite, and the builder reads the process
    # environment only): the honest answer is None — contributing no
    # store — never an exception and never a store with nowhere to
    # write.  Asked directly, the builder answers the same thing the
    # composition did.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert member.build_fdr_deploy_store() is None
    assert create_app().get(member.FDR_COMPONENT_NAME) is None


def test_a_named_database_composes_the_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The other half of the degrade law: a ``DATABASE_URL`` the
    # environment names composes a real store, whose URL is the one
    # named — and composing it touches no database, the promise every
    # store-bound builder here makes (construction holds the URL; the
    # schema lands at the first verb).  Behaviour, not identity: the
    # composed store is the loader's own copy of the class, so the
    # round trip through it is the proof the law crossed composition
    # whole — the same discipline the objective's cross-copy test
    # spells field for field.
    from conftest import (  # type: ignore[import-not-found] - suite-local
        CAMPAIGN_ONE,
    )

    url = f"sqlite:///{tmp_path / 'composed-store.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    built = member.build_fdr_deploy_store()
    assert built is not None
    assert built.database_url == url
    composed = create_app().get(member.FDR_COMPONENT_NAME)
    assert type(composed).__name__ == "FdrDeployStore"
    assert type(composed).__module__.endswith("scoring._fdr")
    assert composed.database_url == url
    assert not (tmp_path / "composed-store.db").exists()
    assert composed.persist(CAMPAIGN_ONE, member.CalibrationFigures(1.0, 0.0)) == 0.9
    assert composed.fdr(CAMPAIGN_ONE) == 0.9
    assert (tmp_path / "composed-store.db").exists()


def test_the_component_survives_a_second_composition() -> None:
    # The loader re-executes ``__init__.py`` (where all three @register
    # calls live) on every create_app() but caches submodules; a
    # registration that lived in _fdr.py would fire on the first
    # composition of a process and silently drop out of this one.  The
    # assertion is on the SECOND application — against the first, it
    # passes vacuously.
    first = create_app()
    second = create_app()
    assert member.FDR_COMPONENT_NAME in first
    assert member.FDR_COMPONENT_NAME in second


def test_the_builder_never_raises_on_a_url_it_cannot_speak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The factory builds every component on every create_app() call, so
    # a builder that raised on a misrouted URL would take composition
    # down for every unrelated feature in the workspace.  It composes
    # the store instead and leaves the refusal to the first verb, where
    # the operator's repair (a misrouted ``DATABASE_URL``) belongs:
    # *no store is configured* (None, quiet) and *the store cannot
    # speak its URL* (a named refusal, at the use) are different facts,
    # and only the second may be loud.
    monkeypatch.setenv("DATABASE_URL", "postgres://metrics.internal:5432/nullius")
    built = member.build_fdr_deploy_store()
    assert built is not None
    with pytest.raises(member.FdrDeployError):
        built.history()


# -- reading the composed application ------------------------------------------


def test_the_application_answers_none_when_the_component_is_absent() -> None:
    # An application composed without this member answers None, not an
    # exception: the "degrade, don't break" stance of the composition.
    # The application here is built directly over an unrelated component
    # so the absence is about composition, not configuration — the other
    # None is pinned above, where the environment is the absent thing.
    without = Application(components={"unrelated": object()}, order=("unrelated",))
    assert member.FDR_COMPONENT_NAME not in without
    assert without.get(member.FDR_COMPONENT_NAME) is None


def test_the_stores_none_is_not_the_objectives_none() -> None:
    # The three components beside one another in the same member, and the
    # two None facts among them: an application that carries neither
    # member refuses them all (composition), while an application that
    # carries the member in an unconfigured environment still composes
    # the objective (arithmetic cannot degrade) and declines the store
    # (deployment state did).  The distinction is the docstrings' own
    # law, and this is its one-test spelling.
    app = create_app()
    assert app.get(member.COMPONENT_NAME) is not None
    assert app.get(member.FDR_COMPONENT_NAME) is None
