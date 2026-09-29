"""``python -m nullius_api``: the entrypoint that boots the transport.

The command feature 4 names on the wire.  These tests pin the order
the entrypoint's own docstring states — engine resolved before the
socket opens, misconfiguration refused as one plain sentence and exit
status 2 — and then boot the real entrypoint as a subprocess against a
per-test database, asking it over HTTP, because an entrypoint tested
only in-process is an entrypoint whose ``-m`` spelling was never run.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import token_for, write_token_file
from nullius_api.__main__ import main
from nullius_api.auth import TOKENS_FILE_ENV
from nullius_api.server import (
    EXECUTION_ENGINE_ENV,
    ExecutionEngineResolutionError,
    resolve_execution_engine,
)

# -- The engine binding ------------------------------------------------------------


def test_an_unset_engine_path_is_the_unbound_state() -> None:
    """Whitespace and absence both mean unbound — the halt route's
    later refusal, never a startup error."""
    assert resolve_execution_engine(None) is None
    assert resolve_execution_engine("") is None
    assert resolve_execution_engine("   ") is None


def test_a_module_attribute_path_binds_the_named_engine() -> None:
    """``module:attribute`` resolves to the object the deployment named."""
    assert resolve_execution_engine("json:dumps") is json.dumps


def test_a_dotted_attribute_path_walks_to_the_engine() -> None:
    """A dotted attribute path resolves through the module's own tree."""
    assert resolve_execution_engine("json:decoder.JSONDecoder") is json.JSONDecoder


def test_a_path_without_both_halves_is_refused_by_name() -> None:
    with pytest.raises(ExecutionEngineResolutionError) as raised:
        resolve_execution_engine("json")
    message = str(raised.value)
    assert EXECUTION_ENGINE_ENV in message
    assert "module:attribute" in message
    assert "Traceback" not in message


def test_a_module_that_cannot_be_imported_is_refused_by_name() -> None:
    with pytest.raises(ExecutionEngineResolutionError) as raised:
        resolve_execution_engine("no_such_module_anywhere:ENGINE")
    assert "no_such_module_anywhere" in str(raised.value)
    assert "ModuleNotFoundError" in str(raised.value)


def test_an_absent_attribute_is_refused_by_name() -> None:
    with pytest.raises(ExecutionEngineResolutionError) as raised:
        resolve_execution_engine("json:no_such_attribute")
    assert "no_such_attribute" in str(raised.value)


# -- Misconfiguration refuses to start ---------------------------------------------


@pytest.fixture(autouse=True)
def _a_token_file_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Give every :func:`main` call in this module a token file.

    Feature 18 reads the tokens *first*, so without this every test
    below — including the two that are about a port and an engine —
    would stop at the token gate instead of at the fault it names.  An
    autouse fixture rather than a parameter because the point is that
    the token file is *not* the subject of those tests: it is the
    baseline a working deployment has, and each test varies exactly one
    thing from it.  The one test that *is* about the missing file
    removes the variable again.
    """
    path = write_token_file(tmp_path / "api-tokens.json")
    monkeypatch.setenv(TOKENS_FILE_ENV, path)
    return path


def test_a_port_out_of_range_refuses_to_start(capsys) -> None:
    """One plain sentence on stderr, exit status 2 — never a traceback."""
    status = main(["--port", "70000"])
    assert status == 2
    written = capsys.readouterr().err
    assert "65535" in written
    assert "Traceback" not in written


def test_the_entrypoint_refuses_to_start_over_a_broken_engine_path(
    monkeypatch, capsys
) -> None:
    """An engine path that does not resolve is a startup refusal — the
    server never opens half-wired."""
    monkeypatch.setenv(EXECUTION_ENGINE_ENV, "no_such_module_anywhere:ENGINE")
    status = main([])
    assert status == 2
    written = capsys.readouterr().err
    assert EXECUTION_ENGINE_ENV in written
    assert "Traceback" not in written


# -- The real entrypoint, booted as a process ---------------------------------------


def _free_port() -> int:
    """A port the kernel confirms free — bound then released, so the
    entrypoint can take it back."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _bootstrap_env(database_url: str, port: int, token_file: str) -> dict[str, str]:
    """The subprocess environment: the test database, the port, the
    token file feature 18 requires, and a PYTHONPATH that carries the
    workspace whatever interpreter runs.

    ``NULLIUS_API_TOKENS_FILE`` is not optional here.  Since feature 18
    a process with no token configured is *refused*, so a boot test
    written before it — which passed only ``DATABASE_URL`` and the port
    — would now be asserting against a server that exited 2, and the
    failure would look like a transport fault rather than the law this
    feature adds.
    """
    from app.module_loader import workspace_scan_roots

    repo_root = Path(__file__).resolve().parents[3]
    entries = [str(repo_root / "src"), *(str(root) for root in workspace_scan_roots())]
    environment = dict(os.environ)
    environment.update(
        {
            "DATABASE_URL": database_url,
            "NULLIUS_API_PORT": str(port),
            "NULLIUS_API_TOKENS_FILE": token_file,
            "PYTHONPATH": ":".join(entries),
        }
    )
    return environment


def _until_it_answers(
    port: int, path: str, scope: str, timeout: float = 30.0
):
    """Poll the booted server until it answers, then return the response.

    ``scope`` is required, not defaulted: every route but ``/healthz``
    needs a credential, and a helper that quietly presented one would
    hide from the caller that it had.  The polling loop does not retry a
    *refusal* — a 401 means the process is up and this test's credential
    is wrong, which is a fact to assert on, not an answer to wait past.
    """
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.request(
                    "GET",
                    path,
                    headers={"Authorization": f"Bearer {token_for(scope)}"},
                )
                response = connection.getresponse()
                return response.status, json.loads(response.read().decode("utf-8"))
            finally:
                connection.close()
        except OSError as exc:
            last = exc
            time.sleep(0.3)
    raise AssertionError(f"the entrypoint never answered: {last!r}")


@pytest.fixture
def token_file(tmp_path: Path) -> str:
    """The token file these boot tests hand the subprocess by path.

    Written rather than read from the autouse fixture's own file purely
    so the path is this test's to state — the subprocess reads whatever
    ``NULLIUS_API_TOKENS_FILE`` names, and naming it explicitly is what
    makes the boot test also a test that the *variable* is honoured.
    """
    return write_token_file(tmp_path / "subprocess-tokens.json")


def test_python_dash_m_boots_and_serves_the_composed_application(
    test_database_url: str, token_file: str
) -> None:
    """The sentence's own command: ``python -m nullius_api`` composes,
    binds the environment's port, and answers HTTP with JSON bodies."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "nullius_api"],
        env=_bootstrap_env(test_database_url, port, token_file),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        status, body = _until_it_answers(port, "/metrics/fdr-deploy", "metrics:read")
        assert status == 200
        # Empty store, honestly empty: the trend is empty and the
        # top-line reads it draws are null, never a fabricated 0.0.
        assert body == {
            "history": [],
            "campaign_id": None,
            "fdr_deploy": None,
            "computed_at": None,
        }

        status, body = _until_it_answers(port, "/nope", "metrics:read")
        assert status == 404
        assert body["error"]["code"] == "unknown_route"

        # The environment's port is the bind: no flag was given, and
        # the process is still serving, not exited after one answer.
        assert process.poll() is None
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            process.kill()
            process.wait(timeout=10)


def test_the_host_flag_overrides_the_loopback_default(
    test_database_url: str, token_file: str
) -> None:
    """``--host`` reaches the bind address — here loopback, named out
    loud, which is also proof the default is a choice not an accident."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "nullius_api", "--host", "127.0.0.1", "--port", str(port)],
        env=_bootstrap_env(test_database_url, port, token_file),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        status, body = _until_it_answers(port, "/ledger/k-effective", "evaluator")
        assert status == 200
        assert body == {"view": {"counts": []}, "counts": [], "total": 0}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            process.kill()
            process.wait(timeout=10)


def test_a_threading_server_survives_its_operator_stopping_it(
    test_database_url: str, token_file: str
) -> None:
    """SIGTERM stops a clean process — the operator's own stop is not a
    crash, and the port is released for the next start."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "nullius_api", "--port", str(port)],
        env=_bootstrap_env(test_database_url, port, token_file),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _until_it_answers(port, "/metrics/regime-coverage", "metrics:read")
    finally:
        process.terminate()
        process.wait(timeout=10)
    # The port answers no more: the socket closed with the process.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    with pytest.raises(OSError):
        connection.request("GET", "/metrics/regime-coverage")
        connection.getresponse()
    connection.close()


# -- No token configured means no server (feature 18) ------------------------------


def test_the_entrypoint_refuses_to_start_with_no_token_file(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """*A missing token file is a refusal to start, not an open server.*

    Driven through :func:`main` rather than a subprocess: the refusal
    happens before the socket, so there is no server to poll and no port
    to reach — the assertion is on the exit status and the sentence, and
    a subprocess would only add a process to wait for.  The environment
    variable is removed rather than pointed at a missing path so this is
    the *unconfigured* case; the file's own absence is covered in
    :mod:`test_auth`.
    """
    monkeypatch.delenv(TOKENS_FILE_ENV, raising=False)
    status = main([])
    assert status == 2
    written = capsys.readouterr().err
    assert TOKENS_FILE_ENV in written
    assert "Traceback" not in written
    assert str(Path.cwd()) not in written  # no filesystem path
