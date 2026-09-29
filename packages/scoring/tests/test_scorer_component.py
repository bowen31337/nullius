"""Feature 265's composition: the second registration.

The scorer process is the member's first component beside the objective,
and this suite pins the growth from the member's side: the second
``@register`` in ``scoring/__init__.py`` (both builders fire from the one
file, the convention the loader's synthetic-name re-execution demands),
the name's two spellings agreeing, and the composed application carrying
the process — ``create_app().get("scoring-null-pick-rate")`` answers *what
is the composed scorer process?*, the same shape of question
``create_app().get("scoring")`` answers for feature 256's objective.

**Why this component degrades where the objective never can.**  The
objective's builder cannot fail and reads no environment, so its
``None`` can only mean the member was absent from the scan.  This
builder composes *deployment state*: it resolves the sidecar the
environment names, and where nothing names one it answers ``None`` —
contributing no process, never failing composition.  The two ``None``s
are different facts with different repairs (composition against
configuration), and the tests here pin that the scorer's ``None`` is the
deployment-shaped one: the key is present in the composed application
(the registration fired; ``order`` records it) while the value is
``None`` (no sidecar to hold).  A caller that needs β₂ must refuse on
that ``None`` rather than charge it as ``0.0`` — the clean campaign's
zero is a measurement, and absence is not.

What these tests deliberately do not reach: the verb's own laws
(``test_scorer.py``), the real sealed sidecar and a non-``None``
composition under a configured environment
(``test_scorer_cross_member.py``, which writes one and resolves through
it), and the objective's own composition (``test_component.py``).
"""

from __future__ import annotations

import sys

import pytest
import scoring as member

from app.module_loader import Application, create_app


def test_the_two_spellings_of_the_name_agree() -> None:
    # The member's registration constant and the law module's own (for a
    # caller importing the process without the package surface) are one
    # string — two spellings of one name is exactly the kind of drift a
    # test is cheaper than, and the prefix keeps the process sorting
    # beside, never inside, the member's other component.
    assert member.SCORER_COMPONENT_NAME == "scoring-null-pick-rate"
    assert member._scorer.SCORER_COMPONENT_NAME == member.SCORER_COMPONENT_NAME


def test_the_scanned_application_carries_the_process_key() -> None:
    # The registration fired: the composed application carries the key
    # and its order records the composition — even though this suite's
    # environment names no sidecar, so the value composed under it is
    # None (the next test).  The key and the value are different facts.
    app = create_app()
    assert member.SCORER_COMPONENT_NAME in app
    assert member.SCORER_COMPONENT_NAME in app.order
    # And the objective's component is untouched by the growth: the two
    # registrations coexist, each under its own name.
    assert app.get(member.COMPONENT_NAME) is not None


def test_the_builder_composes_none_without_a_sidecar(monkeypatch) -> None:
    # Nothing names a sidecar (the conftest's autouse scrub holds for the
    # whole suite, and the builder reads the process environment only):
    # the honest answer is None — contributing no process — never an
    # exception and never a process with nothing to hold.  Asked
    # directly, the builder answers the same thing the composition did.
    for gone in ("NULL_SIDECAR_PATH", "NULL_SIDECAR_KEY_REF", "LAKE_ROOT"):
        monkeypatch.delenv(gone, raising=False)
    assert member.build_null_pick_scorer() is None
    assert create_app().get(member.SCORER_COMPONENT_NAME) is None


def test_the_component_survives_a_second_composition() -> None:
    # The loader re-executes ``__init__.py`` (where both @register calls
    # live) on every create_app() but caches submodules; a registration
    # that lived in _scorer.py would fire on the first composition of a
    # process and silently drop out of this one.  The assertion is on
    # the SECOND application — against the first, it passes vacuously.
    first = create_app()
    second = create_app()
    assert member.SCORER_COMPONENT_NAME in first
    assert member.SCORER_COMPONENT_NAME in second


def test_the_builder_never_raises_when_the_sibling_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A workspace without the null oracle member is the same absence as
    # an environment without a sidecar: no carrier to hold, so no
    # process.  Simulated by halting the sibling's import — the seam the
    # law states as importlib-at-call-time — and asserted on the resolve
    # and the builder both, because a builder that raised would take
    # composition down for every unrelated feature in the workspace.
    monkeypatch.setitem(sys.modules, "nulloracle", None)
    assert member.NullPickScorer.resolve() is None
    assert member.build_null_pick_scorer() is None


def test_a_key_that_cannot_resolve_degrades_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # The deployment-shaped half of "never raises": a path that names a
    # file nobody wrote and a key reference no backend can resolve in
    # this process is still not a reason to fail composition — the
    # sidecar's own resolution answers None for an unresolvable key, and
    # this member's builder trusts that contract rather than re-wrapping
    # it.  The distinction stays the oracle's own: *no sidecar
    # configured* (None, quiet) and *the sidecar is broken* (a named
    # refusal, at the read) are different facts, and only the second may
    # be loud.
    monkeypatch.setenv("NULL_SIDECAR_PATH", str(tmp_path / "absent.enc"))
    monkeypatch.setenv("NULL_SIDECAR_KEY_REF", "kms:arn:aws:kms:us-east-1:0:key/x")
    assert member.build_null_pick_scorer() is None


# -- reading the composed application ------------------------------------------


def test_the_application_answers_none_when_the_component_is_absent() -> None:
    # An application composed without this member answers None, not an
    # exception: the "degrade, don't break" stance of the composition.
    # The application here is built directly over an unrelated component
    # so the absence is about composition, not configuration — the other
    # None is pinned above, where the environment is the absent thing.
    without = Application(components={"unrelated": object()}, order=("unrelated",))
    assert member.SCORER_COMPONENT_NAME not in without
    assert without.get(member.SCORER_COMPONENT_NAME) is None


def test_the_scorers_none_is_not_the_objectives_none() -> None:
    # The two components beside each other in the same member, and the
    # two None facts they answer: an application that carries neither
    # member refuses them both (composition), while an application that
    # carries the member in an unconfigured environment still composes the
    # objective (arithmetic cannot degrade) and declines the process
    # (deployment state did).  The distinction is the docstrings' own
    # law, and this is its one-test spelling.
    app = create_app()
    assert app.get(member.COMPONENT_NAME) is not None
    assert app.get(member.SCORER_COMPONENT_NAME) is None
