"""The "signal-author" component: composition over the two configurations.

additions_spec_llm_authoring.xml, "Signal Agent Author", feature 8: *System
creates a "signal-author" component, registered with ``@register`` in
``signal_agent/__init__.py``.  Its builder answers an ``LLMSignalAuthor``
wired to this member's own components and to a
``providers.AuthoringSession`` over the "live-providers" resolver, or
``None`` when ``providers.load_authoring_config()`` answers ``None``.*

Three contracts, held from the composition side this feature owns:

* **the two configurations the sentence names** — ``create_app()`` with the
  variable unset answers ``None``, and ``create_app()`` with a config file
  named answers an ``LLMSignalAuthor``.  The author is pinned by name,
  module and wiring — never ``isinstance``, for the loader-copy reason the
  member's other component tests state — and the wiring is the feature's
  own subject: the session binds the config the named file holds and the
  ``live-providers`` resolver, the four collaborators are this member's
  own laws, and the session has resolved nothing.  That empty provider
  cache is the observable form of the sentence's *"It makes no model call,
  and reads no API key"*: a pin meets the resolver only inside
  ``provider_for``, which nothing has called.

* **the sentence's *"and nothing else"*** — a near-miss variable holding
  the very path the real one would leaves the component ``None``, a blank
  value counts as unset (the door's own idiom, held end to end through
  composition), composition writes nothing back into the environment, and
  a config-file composition succeeds with every live-provider credential
  variable deleted: the builder's decision reads one variable, and the
  first credential question is asked at the first call, not here.

* **the unchanged half** — the nine components this member contributed
  before this feature still compose beside the author under their own
  names in both configurations, the seven names the sentence adds to
  ``__all__`` are exported and resolvable, and every entry of ``__all__``
  still names an attribute of the package, so an edit that removed,
  renamed or misspelled an export fails here rather than in whatever
  downstream import first notices.

No test in this file opens a network connection, reads a real credential
or places a model call.  The config document names models — §14.2's own
pin spellings, the same fixture vocabulary the providers member's
committed config suite uses, which are pins and not credentials — and
never a key; the composer never resolves a provider, so no transport
exists to fall back on.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import providers
import pytest
import signal_agent as member

from app.module_loader import Application, Registration, create_app

MEMBER_SRC = Path(member.__file__).resolve().parent.parent

#: The one variable the builder reads, spelled in the test module rather
#: than imported — the providers suite's own discipline, so a rename of the
#: member's constant is a failing test about the *feature text* rather than
#: a suite that follows the code.
VARIABLE = "NULLIUS_AUTHORING_CONFIG"

#: A near-miss spelling of it, for the "and nothing else" half: one letter
#: short, holding the very path the real variable would.
NEAR_MISS = "NULLIUS_AUTHORING"

#: The component's own name, pinned the same way as :data:`VARIABLE`.
COMPONENT = "signal-author"

#: The seven names the sentence adds to ``__all__``, in its own order.
EXPORTS = (
    "LLMSignalAuthor",
    "AuthoredSignal",
    "AuthoringRefusedError",
    "parse_authored",
    "ParsedProposal",
    "AuthoredOutputError",
    "build_authoring_prompt",
)

#: The nine components the member contributed before this feature — the
#: "every existing component ... unchanged" half, asserted together with
#: the author in both configurations so the claim is about one composition
#: and not about two applications that happened not to interfere.
LAWS = (
    "signal-agent",
    "signal-agent-anti-convergence",
    "signal-agent-dead-territory",
    "signal-agent-diagnosis",
    "signal-agent-guidance",
    "signal-agent-history",
    "signal-agent-proposal-history",
    "signal-agent-stated-mechanism",
    "signal-agent-themes",
)

#: §14.2's own roots row, as the pin strings a deployment writes.  Taken
#: from the providers member's committed config suite, which states the
#: rule this fixture follows: the only provider names are the
#: architecture's own model spellings, which are pins and not credentials.
ROOT_PINS = (
    "anthropic/claude-opus-5/20260401",
    "openai/gpt-5.6-sol/20260701",
    "google/gemini-3.1-pro/20260801",
)

#: The depth and policy pins of a full document — §14.2's own depth row for
#: the one, the third frontier family for the other, so the fixture reads
#: like the deployment it stands in for.
DEPTH_PIN = "deepseek/deepseek-v4-flash/20260910"
POLICY_PIN = "google/gemini-3.1-pro/20260801"


def document() -> dict:
    """A full authoring document: the seven keys, with the knobs stated.

    The one builder every composition test starts from, so the seven keys
    are spelled in one place and a test that changes one is a test about
    *that key* — the same discipline the providers suite's own document
    builder states for its own.
    """
    return {
        "root_tier": list(ROOT_PINS),
        "depth": DEPTH_PIN,
        "policy": POLICY_PIN,
        "temperature": 0.4,
        "max_tokens": 4096,
        "max_input_tokens": 60000,
        "max_output_tokens": 8192,
    }


def write_config(tmp_path: Path) -> str:
    """Write the document as the JSON file a deployment would name."""
    target = tmp_path / "authoring.json"
    target.write_text(json.dumps(document()), encoding="utf-8")
    return str(target)


def compose_unset(monkeypatch: pytest.MonkeyPatch) -> Application:
    """Compose the member with the variable removed from the environment."""
    monkeypatch.delenv(VARIABLE, raising=False)
    return create_app(MEMBER_SRC, registry=Registration())


def compose_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Application, str]:
    """Compose the member with the variable naming a written config file."""
    path = write_config(tmp_path)
    monkeypatch.setenv(VARIABLE, path)
    return create_app(MEMBER_SRC, registry=Registration()), path


def assert_laws_compose(app: Application) -> None:
    """The nine laws still answer under their own names, in this composition."""
    for name in LAWS:
        assert name in app, name
        assert app.get(name) is not None, name


def assert_is_the_author(author: object, path: str) -> None:
    """The composed component is the author, across the loader's copies.

    Name, then module, then wiring — never ``isinstance``, because the scan
    imports the member under a synthetic name and a class check across the
    two copies cannot hold.  The wiring is the feature's own subject, and
    it is read rather than driven: the callable's public surface is
    ``__call__`` itself, which would place a model call, so the
    collaborators are inspected on the handles the constructor set and the
    session is asked through its own public properties.
    """
    assert callable(author)
    assert type(author).__name__ == "LLMSignalAuthor"
    assert type(author).__module__.endswith("signal_agent._llm_author")

    session = author._session
    assert type(session).__name__ == "AuthoringSession"
    assert type(session).__module__ == "providers._authoring_session"
    # Over the config the named file holds — the frozen config's own
    # value equality, over a config built the same way the builder's was.
    assert session.config == providers.AuthoringConfig.from_file(path)
    # Resolved nothing: no pin has met the resolver, so no call was placed
    # and no credential variable was read.  This is the observable form of
    # "It makes no model call, and reads no API key".
    assert session.providers == {}

    # Over the "live-providers" resolver: the held callable is that law's
    # bound resolve, recognised structurally for the loader-copy reason.
    resolver = session._resolve.__self__
    assert type(resolver).__name__ == "LiveProviderResolver"
    assert type(resolver).__module__ == "providers"

    # Wired to this member's own components — name and module again, the
    # four collaborators the author's constructor names.
    for attribute, law, module in (
        ("_contract", "SignalContract", "signal_agent._authoring"),
        (
            "_anti_convergence",
            "AntiConvergenceGate",
            "signal_agent._anti_convergence",
        ),
        ("_guidance", "PromptGuidanceGate", "signal_agent._guidance"),
        ("_history_store", "ProposalHistoryStore", "signal_agent._proposal"),
    ):
        wired = getattr(author, attribute)
        assert type(wired).__name__ == law, attribute
        assert type(wired).__module__.endswith(module), attribute

    # The one config wired twice — the session binds it and the author
    # rolls its sampling from it, so the two cannot disagree.
    assert author._config == session.config


# -- The name and the exports -------------------------------------------------


def test_the_component_name_is_the_specs_spelling() -> None:
    # The spec's own spelling and the member's are one string; the member's
    # constant exists so the composed application, the builder and this
    # suite share it rather than three literals that can drift.
    assert member.SIGNAL_AUTHOR_COMPONENT_NAME == "signal-author"
    assert "SIGNAL_AUTHOR_COMPONENT_NAME" in member.__all__


def test_the_seven_names_are_exported() -> None:
    # The sentence's own list, in ``__all__`` and resolvable on the package:
    # three classes and the refusal from feature 7, the parse pair from
    # feature 6, the prompt builder from feature 5.
    for name in EXPORTS:
        assert name in member.__all__, name
        assert getattr(member, name) is not None, name
    for kind in (
        member.LLMSignalAuthor,
        member.AuthoredSignal,
        member.AuthoringRefusedError,
        member.ParsedProposal,
        member.AuthoredOutputError,
    ):
        assert isinstance(kind, type)
    assert callable(member.parse_authored)
    assert callable(member.build_authoring_prompt)


def test_every_all_entry_names_an_attribute() -> None:
    # The unchanged half's guard: this feature added names to ``__all__``
    # without touching one that was already there, and the cheap strong
    # form of that claim is structural — no duplicates, and every entry
    # resolves on the package — so a removal, rename or misspelling fails
    # here rather than in whatever downstream import first notices.
    assert len(member.__all__) == len(set(member.__all__))
    for name in member.__all__:
        assert hasattr(member, name), name


# -- The unset configuration --------------------------------------------------


def test_an_unset_variable_answers_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # The sentence's other half: unset is not an error, because a
    # deployment that authors nothing is a real state and its builders
    # answer None.  The name is still registered and still ordered — the
    # component exists and its value is the absence, which is what a
    # caller's `in app` distinguishes from `app.get` returning None for a
    # name nothing registered.
    app = compose_unset(monkeypatch)
    assert COMPONENT in app
    assert COMPONENT in app.order
    assert app.get(COMPONENT) is None
    assert_laws_compose(app)


def test_a_blank_variable_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # The door's own idiom, held end to end through composition: empty and
    # whitespace-only are the spellings of "named nothing".
    monkeypatch.setenv(VARIABLE, "   ")
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(COMPONENT) is None


def test_a_near_miss_variable_is_not_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "reads NULLIUS_AUTHORING_CONFIG, and nothing else": the wrong
    # spelling, holding the very path the right one would, leaves the
    # component None — the decision turns on the one name.  And composition
    # writes nothing back into the environment while it makes it.
    monkeypatch.delenv(VARIABLE, raising=False)
    monkeypatch.setenv(NEAR_MISS, write_config(tmp_path))
    before = dict(os.environ)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(COMPONENT) is None
    assert dict(os.environ) == before


# -- The configured composition -----------------------------------------------


def test_a_config_file_answers_the_author(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The sentence's first half: a named config file composes the author
    # itself, wired as the feature states, beside the nine unchanged laws.
    app, path = compose_configured(tmp_path, monkeypatch)
    assert COMPONENT in app
    assert_is_the_author(app.get(COMPONENT), path)
    assert_laws_compose(app)


def test_composition_needs_no_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The constraint the addition states in as many words, held as the
    # observable it is: with every live-provider credential variable
    # deleted from the environment, a config-file composition still
    # answers the author.  The resolver owns the key question and asks it
    # only inside resolve(), which nothing has called.
    for name in providers.LIVE_PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(name, raising=False)
    app, path = compose_configured(tmp_path, monkeypatch)
    assert_is_the_author(app.get(COMPONENT), path)


def test_the_builder_reads_the_environment_of_the_moment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One process, two compositions, two answers: the unset application
    # carries None and the configured one an author, which pins the
    # per-build read (the environment of the moment the question is asked,
    # not a value frozen at import).  Asserted on the *second* application
    # for the registration hazard too: a ``@register`` outside
    # ``__init__.py`` would fire once and silently drop out of every later
    # ``create_app()``.
    monkeypatch.delenv(VARIABLE, raising=False)
    first = create_app(MEMBER_SRC, registry=Registration())
    monkeypatch.setenv(VARIABLE, write_config(tmp_path))
    second = create_app(MEMBER_SRC, registry=Registration())
    assert first.get(COMPONENT) is None
    assert type(second.get(COMPONENT)).__name__ == "LLMSignalAuthor"


def test_the_ten_names_sort_with_the_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "signal-author" sorts after every "signal-agent-*" name — "u" follows
    # "g" — so the nine laws stay contiguous in the name-sorted order and
    # the author sits immediately after the category it serves.
    app = compose_unset(monkeypatch)
    names = list(app.order)
    assert set(names) == {*LAWS, COMPONENT}
    assert names == sorted(names)
    assert names.index(COMPONENT) == names.index("signal-agent-themes") + 1
