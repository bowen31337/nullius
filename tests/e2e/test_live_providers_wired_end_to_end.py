"""End-to-end: the live-providers member, driven through the *shipped* system.

The live-providers addition (``additions_spec_live_providers.xml``) built six
things under ``packages/providers`` — a stdlib HTTP door, an Anthropic backend,
one OpenAI-compatible backend, a registry that turns a pinned model into a
bound backend, an operator smoke-check command, and the package's export seam
with a composed ``live-providers`` component.  Every one of those already has a
member suite of its own (``packages/providers/tests``), and none of those
suites would notice if the pieces were never *wired*: a member suite proves a
module's behaviour, not that the assembled application reaches it.

This journey is the wiring check.  It drives the two entrypoints a deployment
actually runs —

* ``create_app().get("live-providers")``, the composed application's door to
  the backends, and
* ``python -m providers.live_check``, the runnable smoke check the operator
  runs by hand —

and it follows a call all the way out to the wire and back: a pin resolved
through composition, a request placed through a scripted transport (no socket
is opened anywhere in this file), the answer checked for the model that served
it, captured to a fixture directory, and replayed **offline** through the
recorded backend with the transport removed.  That last step is the point of
the whole addition: a live answer becomes an offline fixture, so a campaign
can run against a recording and touch no network at all.

**How the wire is faked without a socket, and without a test-only app.**  The
shipped backends read ``providers._live_http._urllib_transport`` as the default
transport (feature 1's own statement: *the default transport is
urllib.request; tests inject a callable*).  In-process tests inject that
callable through the registry's ``transport`` argument, which is a shipped
seam, not a fixture.  The *subprocess* test cannot pass a Python callable
across the process boundary, so it stages a one-line ``sitecustomize`` module
that rebinds that same function; the child then runs the real
``python -m providers.live_check`` with the real ``os.environ`` and the real
argument parser, and the only thing replaced is the socket.  Nothing in this
file builds its own application: the composed object under test is
``create_app()``'s, exactly as production builds it.

**The credential is fake and is hunted for.**  Every call here runs on a
key-shaped fake.  The journey asserts the fake is on the wire (a call without
it would not be a real call) and absent from every rendering the deployment
produces — the summary line, the refusal line, a backend's ``repr`` — because a
credential that reached any of those would have travelled into a log or a bug
report.

**The scanned copy is the copy under test.**  The module loader imports each
member under ``_nullius_scanned_<package>``, so the ``Provider`` an assembled
application hands back is an instance of the *scanned* copy's class, and
``isinstance`` against the directly imported ``providers`` names is ``False``
for one and the same source file.  This file recognises the composed objects
through the scanned copy — the member suite's own convention — rather than
weakening the check to a duck-typed guess, so the seam the production loader
creates is the one exercised.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.module_loader import create_app, registered_components, workspace_scan_roots

# tests/e2e/<file> -> e2e -> tests -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The component name the member registers its live resolver under.  Spelled
#: once here and read through the composed application by name, so a rename in
#: the member surfaces as a failed composition rather than a silently skipped
#: assertion.
LIVE_PROVIDERS_COMPONENT = "live-providers"

#: The variable the Anthropic pin's credential is read from.
ANTHROPIC_KEY_ENV = "NULLIUS_ANTHROPIC_API_KEY"
OPENAI_KEY_ENV = "NULLIUS_OPENAI_API_KEY"
DEEPSEEK_KEY_ENV = "NULLIUS_DEEPSEEK_API_KEY"
SELF_HOSTED_URL_ENV = "NULLIUS_SELF_HOSTED_BASE_URL"

#: A fake credential — key-shaped, not key-real.  The journey hunts for the
#: literal value everywhere the deployment could render one, so it must be a
#: value that would be a real leak if it ever appeared.
FAKE_KEY = "fake-nullius-e2e-key-not-a-credential"

#: The pin the Anthropic journeys run against, and the model the scripted
#: vendor answer names as having served it (§14.1: the served model is copied
#: verbatim, and a vendor serving another model is the finding).
ANTHROPIC_PIN = "anthropic/claude-opus-5/20260401"
ANTHROPIC_MODEL = "claude-opus-5"

#: The prompt the smoke check sends when the operator names none — asserted
#: against the body that reached the wire, not against the source constant.
DEFAULT_PROMPT = "Reply with the single word: ok"


# ── The scanned copy, and the scripted wire ──────────────────────────────────


def _scanned_package(composed: object) -> ModuleType:
    """The member's package as the module loader imported it.

    The loader imports each member under ``_nullius_scanned_<pkg>``, so the
    resolver and the providers an assembled application hands back belong to
    the *scanned* copy of ``providers``.  Resolving the class's module and then
    its package root reaches that copy's full public surface — the copy to
    build requests with, recognise providers from and catch refusals from —
    which is what keeps this journey honest about the production seam instead
    of comparing objects across two copies of one source file.
    """
    submodule = importlib.import_module(type(composed).__module__)
    return importlib.import_module(submodule.__package__)


def _transport(*script: Any) -> Any:
    """A transport answering ``script`` in order, recording every send.

    Feature 1's ``Transport`` shape — ``(url, headers, body_bytes, timeout) ->
    (status, response_headers, body_bytes)`` — injected in place of
    ``urllib.request`` so no socket is opened.  The recorded sends are the wire
    seen from outside: the URL, the headers and the decoded body of every call,
    which is how this journey reads what left the machine.  When the script runs
    out its last entry repeats; a ``BaseException`` in the script is raised
    instead of answered.
    """
    calls: list[dict[str, Any]] = []

    def _send(
        url: str, headers: dict[str, str], body_bytes: bytes, timeout: float
    ) -> tuple[int, dict[str, str], bytes]:
        calls.append(
            {
                "url": url,
                "headers": {name.lower(): value for name, value in headers.items()},
                "body": json.loads(body_bytes),
                "timeout": timeout,
            }
        )
        answer = script[min(len(calls), len(script)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    _send.calls = calls  # type: ignore[attr-defined]
    return _send


def _ok(body: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    """A 2xx transport answer carrying ``body`` as UTF-8 JSON."""
    return 200, {}, json.dumps(body).encode("utf-8")


def _anthropic_answer(
    *,
    model: str = ANTHROPIC_MODEL,
    text: str = "ok",
    stop_reason: str = "end_turn",
    input_tokens: int = 7,
    output_tokens: int = 2,
    cache_read: int = 0,
    cache_creation: int = 0,
) -> dict[str, Any]:
    """A Messages-API success body naming ``model`` as the serving model."""
    usage: dict[str, int] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if cache_read:
        usage["cache_read_input_tokens"] = cache_read
    if cache_creation:
        usage["cache_creation_input_tokens"] = cache_creation
    return {
        "content": [{"type": "text", "text": text}],
        "model": model,
        "usage": usage,
        "stop_reason": stop_reason,
    }


@pytest.fixture(scope="module")
def application() -> Any:
    """The composed application, built once through the shipped factory.

    ``create_app()`` with no arguments is the production door: it scans the
    declared workspace, imports every member and calls every builder.  It is the
    expensive thing here (the factory composes the whole system), so one
    application serves the suite — and it is deliberately the *real* one, not a
    root restricted to this member, because "does the assembled application
    carry the live resolver" is the wiring question under test.
    """
    return create_app()


@pytest.fixture(scope="module")
def providers_pkg(application: Any) -> ModuleType:
    """The scanned ``providers`` package the composed application holds."""
    return _scanned_package(application.get(LIVE_PROVIDERS_COMPONENT))


# ── The composition: the shipped application carries the live resolver ───────


def test_the_factory_is_the_loader_the_registry_registered_into(
    application: Any,
) -> None:
    """The registration is the wiring story: the registry holds the builder.

    Read through the registry the factory reads from — after a ``create_app()``
    has scanned, so the component the factory actually calls is the one
    asserted on, not through ``providers.build_live_providers``, which can
    differ by module copy.  The fixture is requested so the composition has
    happened; the registry is a process-global, so it is empty only before any
    scan and populated here because ``application`` has run one.
    """
    names = {component.name for component in registered_components()}
    assert LIVE_PROVIDERS_COMPONENT in names


def test_create_app_composes_the_live_providers_resolver(application: Any) -> None:
    """``create_app().get("live-providers")`` answers a resolver with ``resolve``.

    The addition's own sentence: the composed application's door to the live
    backends is reached by name, never by importing a private module.  The
    resolver is stateless — it reads the environment at resolve time and folds
    nothing in at build time — so a composition succeeds on a box with no
    credentials at all.
    """
    assert LIVE_PROVIDERS_COMPONENT in application
    resolver = application.get(LIVE_PROVIDERS_COMPONENT)
    assert callable(resolver.resolve)
    assert vars(resolver) == {}


def test_the_resolver_builds_a_provider_off_the_composed_application(
    application: Any, providers_pkg: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pin resolved through composition is a real backend, not a stub.

    The returned object is checked against the ``Provider`` base the resolver's
    own ``resolve`` annotation names — the scanned copy's, which is the class
    the object is genuinely an instance of across the loader's seam.
    """
    monkeypatch.setenv(ANTHROPIC_KEY_ENV, FAKE_KEY)
    resolver = application.get(LIVE_PROVIDERS_COMPONENT)
    pin = providers_pkg.ModelPin("anthropic", ANTHROPIC_MODEL, "20260401")

    provider = resolver.resolve(pin)

    base = inspect.get_annotations(type(resolver).resolve, eval_str=True)["return"]
    assert isinstance(provider, base)
    assert type(provider).__name__ == "AnthropicProvider"


def test_the_resolver_refuses_a_pin_whose_variable_is_unset(
    application: Any,
    providers_pkg: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing credential is a refusal *naming the variable*, never its value.

    ``resolve`` reads ``os.environ`` at call time, so the refusal is driven by
    the ambient environment here rather than by any folded-in state.
    """
    monkeypatch.delenv(ANTHROPIC_KEY_ENV, raising=False)
    resolver = application.get(LIVE_PROVIDERS_COMPONENT)
    pin = providers_pkg.ModelPin("anthropic", ANTHROPIC_MODEL, "20260401")

    with pytest.raises(providers_pkg.ProviderNotConfiguredError) as caught:
        resolver.resolve(pin)

    message = str(caught.value)
    assert ANTHROPIC_KEY_ENV in message
    assert FAKE_KEY not in message


# ── The live call: a pin, a request, an answer, over the scripted wire ───────


def test_a_pinned_anthropic_call_completes_over_the_wire(
    providers_pkg: ModuleType,
) -> None:
    """The registry's provider places a real call and normalizes the answer.

    Driven through the shipped registry function ``live_provider`` with
    feature 1's transport seam injected.  The journey asserts the wire facts a
    caller depends on — the URL, the credential header, the folded system
    prompt — and the normalized completion that comes back.
    """
    pin = providers_pkg.ModelPin("anthropic", ANTHROPIC_MODEL, "20260401")
    transport = _transport(
        _ok(_anthropic_answer(input_tokens=9, output_tokens=2, cache_read=1))
    )
    provider = providers_pkg.live_provider(
        pin, {ANTHROPIC_KEY_ENV: FAKE_KEY}, transport
    )

    request = providers_pkg.Request(
        messages=(
            providers_pkg.Message(role="system", content="be terse"),
            providers_pkg.Message(role="user", content="hello"),
        ),
        model=ANTHROPIC_MODEL,
    )
    completion = provider.complete(request)

    sent = transport.calls[0]
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["headers"]["x-api-key"] == FAKE_KEY
    assert sent["headers"]["anthropic-version"] == "2023-06-01"
    # System messages fold into the top-level ``system`` field; the shift is
    # what tells a caller the backend, not the request, owns the wire shape.
    assert sent["body"]["system"][0]["text"] == "be terse"
    assert [m["role"] for m in sent["body"]["messages"]] == ["user"]

    assert completion.content == "ok"
    assert completion.model == ANTHROPIC_MODEL
    assert completion.finish_reason == "stop"
    # input_tokens counts *every* input token — the billed figure plus any
    # cache-creation and cache-read tokens — so the scripted 9 billed plus 1
    # cache-read arrives as 10, with the cache-read figure reported separately.
    assert completion.usage.input_tokens == 10
    assert completion.usage.output_tokens == 2
    assert completion.usage.cache_read_tokens == 1


def test_require_served_refuses_a_vendor_that_served_another_model(
    providers_pkg: ModuleType,
) -> None:
    """The §14.1 check catches a silently-swapped model, end to end.

    A vendor answers under the pinned id but names a different model; the
    completion is refused, naming both sides, the moment it arrives.
    """
    pin = providers_pkg.ModelPin("anthropic", ANTHROPIC_MODEL, "20260401")
    transport = _transport(
        _ok(_anthropic_answer(model="some-other-model", text="oops"))
    )
    provider = providers_pkg.live_provider(
        pin, {ANTHROPIC_KEY_ENV: FAKE_KEY}, transport
    )
    completion = provider.complete(
        providers_pkg.Request(
            messages=(providers_pkg.Message(role="user", content="hi"),),
            model=ANTHROPIC_MODEL,
        )
    )

    with pytest.raises(providers_pkg.ServedModelMismatchError) as caught:
        providers_pkg.require_served(pin, completion)

    assert caught.value.code == "served_model_mismatch"
    assert ANTHROPIC_MODEL in str(caught.value)
    assert "some-other-model" in str(caught.value)


def test_a_dated_snapshot_of_the_pinned_model_is_admitted(
    providers_pkg: ModuleType,
) -> None:
    """A serving model that is the pin plus a ``-`` suffix is the same line."""
    pin = providers_pkg.ModelPin("anthropic", ANTHROPIC_MODEL, "20260401")
    completion = providers_pkg.Completion(
        content="ok",
        model=f"{ANTHROPIC_MODEL}-20260401",
        usage=providers_pkg.Usage(input_tokens=1, output_tokens=1),
    )
    assert providers_pkg.require_served(pin, completion) is completion


# ── The other vendors the one OpenAI-compatible backend serves ──────────────


def test_openai_sends_the_openai_length_cap_and_the_cached_input_figure(
    providers_pkg: ModuleType,
) -> None:
    pin = providers_pkg.ModelPin("openai", "gpt-5", "20260101")
    transport = _transport(
        _ok(
            {
                "choices": [
                    {"message": {"content": "hi"}, "finish_reason": "stop"}
                ],
                "model": "gpt-5",
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "prompt_tokens_details": {"cached_tokens": 3},
                },
            }
        )
    )
    provider = providers_pkg.live_provider(
        pin, {OPENAI_KEY_ENV: FAKE_KEY}, transport
    )
    completion = provider.complete(
        providers_pkg.Request(
            messages=(providers_pkg.Message(role="user", content="q"),),
            model="gpt-5",
        )
    )

    sent = transport.calls[0]
    assert sent["url"] == "https://api.openai.com/v1/chat/completions"
    assert sent["headers"]["authorization"] == f"Bearer {FAKE_KEY}"
    assert "max_completion_tokens" in sent["body"]
    assert "max_tokens" not in sent["body"]
    assert completion.usage.cache_read_tokens == 3


def test_deepseek_uses_its_own_length_cap_and_cache_field(
    providers_pkg: ModuleType,
) -> None:
    pin = providers_pkg.ModelPin("deepseek", "deepseek-chat", "20260101")
    transport = _transport(
        _ok(
            {
                "choices": [
                    {"message": {"content": "yo"}, "finish_reason": "stop"}
                ],
                "model": "deepseek-chat",
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 1,
                    "prompt_cache_hit_tokens": 2,
                },
            }
        )
    )
    provider = providers_pkg.live_provider(
        pin, {DEEPSEEK_KEY_ENV: FAKE_KEY}, transport
    )
    completion = provider.complete(
        providers_pkg.Request(
            messages=(providers_pkg.Message(role="user", content="q"),),
            model="deepseek-chat",
        )
    )

    sent = transport.calls[0]
    assert sent["url"] == "https://api.deepseek.com/chat/completions"
    # DeepSeek takes the other spelling of the length cap and reports the cache
    # hit under its own field — the vendor table's whole reason for existing.
    assert "max_tokens" in sent["body"]
    assert "max_completion_tokens" not in sent["body"]
    assert completion.usage.cache_read_tokens == 2


def test_self_hosted_takes_its_base_url_from_the_environment_and_sends_no_auth(
    providers_pkg: ModuleType,
) -> None:
    """The one vendor whose destination is configuration, with no key at all."""
    pin = providers_pkg.ModelPin("self-hosted", "llama-3", "local")
    transport = _transport(
        _ok(
            {
                "choices": [
                    {"message": {"content": "s"}, "finish_reason": "stop"}
                ],
                "model": "llama-3",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
        )
    )
    provider = providers_pkg.live_provider(
        pin, {SELF_HOSTED_URL_ENV: "http://127.0.0.1:8123"}, transport
    )
    provider.complete(
        providers_pkg.Request(
            messages=(providers_pkg.Message(role="user", content="q"),),
            model="llama-3",
        )
    )

    sent = transport.calls[0]
    assert sent["url"] == "http://127.0.0.1:8123/chat/completions"
    assert "authorization" not in sent["headers"]


# ── The budget: a ceiling that stops the next call before it is sent ────────


def test_the_budget_refuses_the_call_after_the_ceiling_is_spent(
    providers_pkg: ModuleType,
) -> None:
    """A wrapped backend answers until its ceiling, then refuses without sending.

    One budgeted provider over one scripted transport: the first call is
    answered and counted, the second is refused before the transport is
    reached — so the wire sees exactly one send.
    """
    pin = providers_pkg.ModelPin("anthropic", ANTHROPIC_MODEL, "20260401")
    transport = _transport(_ok(_anthropic_answer(input_tokens=5, output_tokens=4)))
    inner = providers_pkg.live_provider(pin, {ANTHROPIC_KEY_ENV: FAKE_KEY}, transport)
    budgeted = providers_pkg.BudgetedProvider(
        inner,
        max_input_tokens=100,
        max_output_tokens=4,
    )
    request = providers_pkg.Request(
        messages=(providers_pkg.Message(role="user", content="hi"),),
        model=ANTHROPIC_MODEL,
    )

    budgeted.complete(request)
    assert budgeted.spent() == (5, 4)

    with pytest.raises(providers_pkg.BudgetExhaustedError) as caught:
        budgeted.complete(request)

    assert caught.value.code == "budget_exhausted"
    assert len(transport.calls) == 1


# ── The offline half: a live answer becomes a fixture, and replays ──────────


def test_a_live_exchange_becomes_a_fixture_and_replays_offline(
    providers_pkg: ModuleType, tmp_path: Path
) -> None:
    """The addition's reason for existing: record once, replay with no wire.

    A live call is captured through the recorder, filed by the fixture store,
    and then answered **offline** by the recorded backend — which has no
    transport to fall back to, so a prompt it never saw is refused rather than
    reaching for the network.
    """
    pin = providers_pkg.ModelPin("anthropic", ANTHROPIC_MODEL, "20260401")
    transport = _transport(_ok(_anthropic_answer(text="recorded answer")))
    live = providers_pkg.live_provider(pin, {ANTHROPIC_KEY_ENV: FAKE_KEY}, transport)
    recorder = providers_pkg.RecordingProvider(live)
    request = providers_pkg.Request(
        messages=(providers_pkg.Message(role="user", content="capture me"),),
        model=ANTHROPIC_MODEL,
    )
    live_completion = recorder.complete(request)

    fixture_dir = tmp_path / "fixtures"
    store = providers_pkg.FixtureStore(fixture_dir)
    files = store.record_all(recorder.exchanges())
    assert len(files) == 1
    assert list(fixture_dir.glob("*.json"))

    # The replay backend is built from what is on disk, and answers the same
    # prompt with the same completion — value-equal, across a process boundary
    # in a real deployment.
    replayed = providers_pkg.RecordedProvider(store.responses())
    assert replayed.complete(request) == live_completion

    unseen = providers_pkg.Request(
        messages=(providers_pkg.Message(role="user", content="never recorded"),),
        model=ANTHROPIC_MODEL,
    )
    with pytest.raises(providers_pkg.FixtureNotFoundError) as caught:
        replayed.complete(unseen)
    assert caught.value.code == "fixture_missing"


# ── The runnable smoke check: the shipped command, in a real child process ──


#: The staged module that rebinds the door's default transport in the child.
#: It replaces exactly one name — the socket — and nothing else: the child runs
#: the real ``python -m providers.live_check``, with the real environment and
#: the real argument parser.  It dumps the call it received (URL, headers,
#: body) so the journey can read what left the process.
_SITECUSTOMIZE = '''
import json
import os

import providers._live_http as _live_http


def _fake_transport(url, headers, body_bytes, timeout):
    with open(os.environ["NULLIUS_E2E_DUMP"], "w", encoding="utf-8") as handle:
        json.dump(
            {
                "url": url,
                "headers": {name.lower(): value for name, value in headers.items()},
                "body": json.loads(body_bytes),
            },
            handle,
        )
    with open(os.environ["NULLIUS_E2E_REPLY"], "rb") as handle:
        return 200, {}, handle.read()


_live_http._urllib_transport = _fake_transport
'''


def _child_pythonpath(stage: Path) -> str:
    """The import surface the child interpreter needs to be the deployment.

    The application factory's ``src`` plus every declared workspace member's
    scan root — the same declaration the production loader reads — plus the
    directory holding the staged ``sitecustomize``, so ``python -m
    providers.live_check`` reaches ``app``, ``providers`` and the staged
    transport exactly as a real invocation would.
    """
    entries = [str(REPO_ROOT / "src"), str(stage)]
    for root in workspace_scan_roots():
        entry = str(root)
        if entry not in entries:
            entries.append(entry)
    inherited = os.environ.get("PYTHONPATH", "")
    if inherited:
        entries.append(inherited)
    return os.pathsep.join(entries)


def _run_live_check(
    tmp_path: Path,
    *argv: str,
    reply: dict[str, Any],
    key: str = FAKE_KEY,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Run the shipped command in a child, returning its result and dumps."""
    stage = tmp_path / "sitecustomize"
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    reply_path = tmp_path / "reply.json"
    reply_path.write_text(json.dumps(reply), encoding="utf-8")
    dump_path = tmp_path / "call.json"

    environment = {
        **os.environ,
        "PYTHONPATH": _child_pythonpath(stage),
        ANTHROPIC_KEY_ENV: key,
        "NULLIUS_E2E_REPLY": str(reply_path),
        "NULLIUS_E2E_DUMP": str(dump_path),
    }
    completed = subprocess.run(
        [sys.executable, "-m", "providers.live_check", *argv],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return completed, dump_path, stage


def test_the_smoke_check_command_makes_one_real_call_and_prints_one_json_line(
    tmp_path: Path,
) -> None:
    """``python -m providers.live_check --pin ...`` from a fresh interpreter.

    The module is run as a command in its own process, over the scripted wire,
    and its single stdout line is parsed as JSON — the contract an operator's
    smoke-test job depends on.
    """
    completed, dump_path, _ = _run_live_check(
        tmp_path, "--pin", ANTHROPIC_PIN, reply=_anthropic_answer(text="ok")
    )

    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["pin"] == ANTHROPIC_PIN
    assert payload["served_model"] == ANTHROPIC_MODEL
    assert payload["finish_reason"] == "stop"
    assert payload["input_tokens"] == 7
    assert payload["output_tokens"] == 2
    assert payload["cache_read_tokens"] == 0
    assert payload["content"] == "ok"

    # The call actually left the process, carrying the pin's model and the
    # default prompt — read off the wire, not off the source.
    sent = json.loads(dump_path.read_text(encoding="utf-8"))
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["body"]["model"] == ANTHROPIC_MODEL
    assert sent["body"]["messages"][0]["content"][0]["text"] == DEFAULT_PROMPT


def test_the_smoke_check_records_a_live_answer_as_an_offline_fixture(
    tmp_path: Path,
) -> None:
    """``--record DIR`` files the exchange, and the fixture replays."""
    record_dir = tmp_path / "recorded"
    completed, _, _ = _run_live_check(
        tmp_path,
        "--pin",
        ANTHROPIC_PIN,
        "--record",
        str(record_dir),
        reply=_anthropic_answer(text="filed"),
    )
    assert completed.returncode == 0, completed.stderr

    from providers import FixtureStore, Message, RecordedProvider, Request

    store = FixtureStore(record_dir)
    files = store.files()
    assert len(files) == 1

    replayed = RecordedProvider(store.responses())
    request = Request(
        messages=(Message(role="user", content=DEFAULT_PROMPT),),
        model=ANTHROPIC_MODEL,
    )
    assert replayed.complete(request).content == "filed"


def test_the_smoke_check_refuses_a_missing_credential_on_stderr(
    tmp_path: Path,
) -> None:
    """A pin whose variable is unset exits 1 with one line naming the variable."""
    stage = tmp_path / "sitecustomize"
    stage.mkdir()
    environment = {
        **os.environ,
        "PYTHONPATH": _child_pythonpath(stage),
    }
    environment.pop(ANTHROPIC_KEY_ENV, None)
    completed = subprocess.run(
        [sys.executable, "-m", "providers.live_check", "--pin", ANTHROPIC_PIN],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 1
    assert ANTHROPIC_KEY_ENV in completed.stderr
    assert completed.stdout == ""


def test_the_smoke_check_rejects_a_bad_argument_with_exit_two(tmp_path: Path) -> None:
    """No ``--pin`` is argparse's own refusal: exit 2, before any call."""
    completed, _, _ = _run_live_check(tmp_path, reply=_anthropic_answer())

    assert completed.returncode == 2
    assert "pin" in completed.stderr


def test_the_credential_never_appears_in_the_commands_own_output(
    tmp_path: Path,
) -> None:
    """The fake key stays on the wire and off stdout and stderr.

    The whole point of the secret-scrubbing door: the credential authenticates
    the call and reaches nothing the deployment renders.  Both the success run
    and a refusal are checked, because a refusal is one of the three places a
    credential must never reach.
    """
    success, dump_path, _ = _run_live_check(
        tmp_path, "--pin", ANTHROPIC_PIN, reply=_anthropic_answer()
    )
    assert FAKE_KEY not in success.stdout
    assert FAKE_KEY not in success.stderr
    # And it *was* on the wire — otherwise the assertion above would be trivially
    # true and would prove nothing.
    assert json.loads(dump_path.read_text(encoding="utf-8"))["headers"].get(
        "x-api-key"
    ) == FAKE_KEY

    # A vendor error carries the vendor's own message through the door; the key
    # must not ride along in the refusal line.
    refusing, _, _ = _run_live_check(
        tmp_path / "refusal",
        "--pin",
        ANTHROPIC_PIN,
        reply={
            "type": "error",
            "error": {"type": "authentication_error", "message": "invalid x-api-key"},
        },
    )
    assert refusing.returncode == 1
    assert FAKE_KEY not in refusing.stdout
    assert FAKE_KEY not in refusing.stderr


# ── The export seam: the names a caller composes and imports against ────────


#: The twelve names the addition's sixth feature adds to ``__all__``, mapped to
#: the private module that owns each — the export seam's own contract, asserted
#: as a re-export (the same object the owning module holds), not a copy.
LIVE_EXPORTS = {
    "AnthropicProvider": "_anthropic",
    "ProviderRequestError": "_anthropic",
    "OpenAICompatProvider": "_openai_compat",
    "live_provider": "_live",
    "require_served": "_live",
    "LIVE_PROVIDER_ENV_VARS": "_live",
    "ServedModelMismatchError": "_live",
    "BudgetedProvider": "_budget",
    "BudgetExhaustedError": "_budget",
    "ProviderHostRefusedError": "_live_http",
    "ProviderTransportError": "_live_http",
    "ProviderHTTPError": "_live_http",
}


def test_every_live_backend_name_is_exported_from_the_package(
    providers_pkg: ModuleType,
) -> None:
    """Each of the twelve names is listed in ``__all__`` and is the owner's own.

    Asserted on the *scanned* package — the copy the assembled application
    actually holds — so the export seam is checked where production reads it.
    """
    for name, owner in LIVE_EXPORTS.items():
        assert name in providers_pkg.__all__, f"{name} missing from __all__"
        assert hasattr(providers_pkg, name), f"{name} not exported"
        owner_module = importlib.import_module(f"{providers_pkg.__name__}.{owner}")
        assert getattr(providers_pkg, name) is getattr(owner_module, name), (
            f"{name} is a copy, not the {owner} module's own object"
        )


def test_the_vendor_table_names_one_variable_per_vendor(
    providers_pkg: ModuleType,
) -> None:
    """Every live variable is ``NULLIUS_``-prefixed, and every vendor is covered."""
    table = providers_pkg.LIVE_PROVIDER_ENV_VARS
    assert set(table) == {"anthropic", "openai", "deepseek", "google", "self-hosted"}
    assert all(variable.startswith("NULLIUS_") for variable in table.values())
