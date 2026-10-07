"""bug_spec_effort_wiring.xml, bug 1 — a null authoring temperature must not crash.

Feature 5 of additions_spec_real_campaign_path.xml made
``providers.AuthoringConfig.temperature`` optional (``None`` for a deployment
pinning a model whose vendor rejects the field outright, e.g.
``claude-opus-5-5``) and added ``effort`` in its place, but
``signal_agent._llm_author`` was never updated: it called
``float(self._config.temperature)`` unconditionally at all three sites that
build a request or a record — ``__call__`` (the child path), ``author_root``
(the root path) and ``_author`` (the record every call site shares, so a
retry reaches it too) — and ``float(None)`` is a ``TypeError``.

This suite drives all three call sites with a recording fake provider and
pins the fix's claims:

* a ``None`` config temperature never crashes, and the
  :class:`providers.Request` the author builds carries ``temperature == 0.0``
  — :class:`~providers.Request` has no optional form of the field, and 0.0 is
  its own "no knob turned" default, the same value an unstated
  ``AgentSampling.temperature`` defaults to;
* a stated temperature is passed through to the request unchanged, exactly as
  before this fix;
* the :class:`~providers.AuthoringRecord` this author hands back always
  records a full :class:`~providers.AgentSampling` — node persistence's
  contract (:func:`providers.require_agent_sampling`) refuses anything that
  names fewer than the four required keys, so a two-key mapping like
  ``{"effort": "high"}`` is not a smaller valid record, it is a record
  persistence cannot accept at all (the regression this suite now guards: a
  real campaign on a no-sampling pin stopped after its first root because the
  record built here carried only ``effort``).  A ``None`` config temperature
  means the model was sent no ``temperature`` and no ``top_p`` at all — the
  no-sampling extension's honest reading of that absence is ``None`` for
  both, ``"adaptive"`` for ``thinking`` (the 5.x family's reasoning is not a
  flag the caller turns on or off), and ``effort`` carried when the config
  named one; a stated temperature still records the ``AgentSampling`` it
  always has, with ``thinking`` at its ordinary ``False`` default.

No network, no credential, no database: the provider is the suite's own
``FakeProvider`` fake, borrowed from :mod:`test_llm_author` along with its
other fixtures, the same convention :mod:`test_llm_author_root` uses.
"""

from __future__ import annotations

from providers import AgentSampling, require_agent_sampling

from test_llm_author import (  # isort: skip
    CONFORMING_ANSWER,
    CONFORMING_CODE,
    ROOT_MODEL,
    UNPARSEABLE_ANSWER,
    FakeProvider,
    build_author,
    completion,
    make_config,
    workspace,
)

ROOT_ID = "8f14e45f-cea3-4f93-8d2e-0000000000bb"
CAMPAIGN_ID = "8f14e45f-cea3-4f93-8d2e-000000000001"
THEME_ROOT = "momentum"


# ── The child path: LLMSignalAuthor.__call__ ──────────────────────────────────


def test_call_with_temperature_none_does_not_crash_and_states_no_temperature() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, config=make_config(temperature=None))
    result = author(workspace())
    assert result.code == CONFORMING_CODE
    # Request.temperature has no optional form; a None config temperature is
    # represented by the dataclass's own "no knob turned" default, 0.0 — never
    # float(None).
    assert provider.requests[0].temperature == 0.0
    # No temperature or top_p was sent, thinking is adaptive (the 5.x
    # family), and no effort was configured — the full four-plus-effort
    # record node persistence's contract requires, never a bare mapping.
    assert result.record.sampling == AgentSampling(
        temperature=None, top_p=None, thinking="adaptive"
    )
    assert require_agent_sampling(result.record.sampling).to_dict() == {
        "temperature": None,
        "top_p": None,
        "thinking": "adaptive",
        "seed": 0,
    }


def test_call_with_temperature_none_and_effort_records_effort_not_temperature() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(
        provider=provider, config=make_config(temperature=None, effort="high")
    )
    result = author(workspace())
    assert provider.requests[0].temperature == 0.0
    assert result.record.sampling == AgentSampling(
        temperature=None, top_p=None, thinking="adaptive", effort="high"
    )
    assert require_agent_sampling(result.record.sampling).to_dict() == {
        "temperature": None,
        "top_p": None,
        "thinking": "adaptive",
        "seed": 0,
        "effort": "high",
    }


def test_call_with_stated_temperature_is_passed_through_unchanged() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, config=make_config(temperature=0.6))
    result = author(workspace())
    assert provider.requests[0].temperature == 0.6
    assert result.record.sampling == AgentSampling(temperature=0.6)


# ── The root path: LLMSignalAuthor.author_root ────────────────────────────────


def test_author_root_with_temperature_none_does_not_crash() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, config=make_config(temperature=None))
    result = author.author_root(CAMPAIGN_ID, THEME_ROOT, root_id=ROOT_ID)
    assert result.code == CONFORMING_CODE
    assert provider.requests[0].temperature == 0.0
    assert result.record.sampling == AgentSampling(
        temperature=None, top_p=None, thinking="adaptive"
    )


def test_author_root_with_stated_temperature_is_passed_through_unchanged() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, config=make_config(temperature=0.3))
    result = author.author_root(CAMPAIGN_ID, THEME_ROOT, root_id=ROOT_ID)
    assert provider.requests[0].temperature == 0.3
    assert result.record.sampling == AgentSampling(temperature=0.3)


# ── The retry path: both calls, and the record _author builds afterward ──────


def test_retry_with_temperature_none_does_not_crash_on_either_call() -> None:
    provider = FakeProvider(
        [
            completion(UNPARSEABLE_ANSWER, model=ROOT_MODEL),
            completion(CONFORMING_ANSWER, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(
        provider=provider, config=make_config(temperature=None, effort="medium"), max_retries=1
    )
    result = author(workspace())
    assert result.code == CONFORMING_CODE
    assert provider.calls == 2
    # Both the first call and the retry carried the same "no knob turned"
    # value — the fix applies at every call this loop makes, not just the
    # first.
    assert provider.requests[0].temperature == 0.0
    assert provider.requests[1].temperature == 0.0
    assert result.record.sampling == AgentSampling(
        temperature=None, top_p=None, thinking="adaptive", effort="medium"
    )


def test_retry_with_stated_temperature_records_agent_sampling() -> None:
    provider = FakeProvider(
        [
            completion(UNPARSEABLE_ANSWER, model=ROOT_MODEL),
            completion(CONFORMING_ANSWER, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(
        provider=provider, config=make_config(temperature=0.5), max_retries=1
    )
    result = author(workspace())
    assert provider.calls == 2
    assert result.record.sampling == AgentSampling(temperature=0.5)
