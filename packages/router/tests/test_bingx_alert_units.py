"""Tests for the alerting systemd units: the ``OnFailure`` hook.

The OnFailure feature of ``additions_spec_bingx_vst_alerts.xml``, the
Telegram alerting spec for the scheduled BingX VST bot: *the system sends
an urgent Telegram alert when a scheduled slot cannot run at all (the
systemd unit fails)*.  A slot that runs to completion — even a refused leg
(exit 1) or a daily-loss halt (exit 3) — prints its summary line and is
alerted from inside the slot; a unit that fails outright has no slot
output, so the rebalance unit names a template in ``OnFailure=`` and
systemd starts one instance of it.  That template runs the urgent door of
:mod:`router.bingx_alert` — ``run.sh vst-alert --unit %i --event
failure`` — whose own behaviour (the message, the scrubbed log lines, the
exit codes) is proven in ``test_bingx_alert.py``.  What is pinned here is
the *wiring*: which unit fires the hook, which instance it passes, and the
environment the hook's own command runs in.

The wiring has two halves, and a test each:

* **The trigger.**  ``OnFailure=nullius-vst-alert@%n.service`` — the
  specifier, not a hard-coded name, so the instance the manager builds
  (``%n`` is the failed unit's own full name, i.e. the template's ``%i``)
  is exactly what ``journalctl --user -u`` wants to read, and exits 1 and
  3 stay in ``SuccessExitStatus`` so a slot that *ran* never pages
  urgently through this hook.
* **The hook.**  The template is a oneshot carrying the same ``PATH`` and
  the same token-file load as the rebalance service — the fix the rebalance
  unit's own suite pins — because ``run.sh vst-alert`` runs ``op run`` and
  then ``uv run`` exactly as a slot does.  The token's value never appears
  in either unit: it is read from the operator's mode-0600 file at start.

These tests read the *shipped* units, not copies: the files the operator
links into ``~/.config/systemd/user/`` are the ones pinned here.  Nothing
is installed or enabled, no test opens a socket or reads a real
credential, and the token in the ``env -i`` run is a synthetic placeholder
— deliberately not shaped like a credential — that reaches the stubbed
child but enters no captured output.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

DEPLOY_SYSTEMD = Path(__file__).resolve().parents[3] / "deploy" / "systemd"

#: The unit whose failure starts the hook, and the template it names.
#: ``OnFailure`` starts a template unit only through an instance; the
#: rebalance unit builds it from the ``%n`` specifier — its own full name.
REBALANCE_UNIT_PATH = DEPLOY_SYSTEMD / "nullius-vst-rebalance.service"
ALERT_TEMPLATE_PATH = DEPLOY_SYSTEMD / "nullius-vst-alert@.service"

#: The failed unit's own full name: what ``%n`` expands to in its
#: ``OnFailure=`` line, and therefore the instance (``%i``) the template
#: runs with — the name the alert quotes and its ``journalctl`` command
#: reads.  Derived from the shipped file's own name, so a rename follows.
FAILED_UNIT_NAME = REBALANCE_UNIT_PATH.name

#: The token file the operator's own ``~/.zshrc`` loads the 1Password
#: service-account token from (mode 0600, outside the repository).
TOKEN_FILE_SUFFIX = "/.config/op/service-token"


def _unit_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _directive(path: Path, name: str) -> str:
    """The single directive line ``name`` in the shipped unit at ``path``.

    A directive that is absent is a *failure* — the hook would not fire,
    or would fire with the manager's inherited environment — so the
    absence is reported rather than silently skipped.  Each directive is
    expected exactly once; a second would shadow the first.
    """
    matches = [
        line
        for line in _unit_text(path).splitlines()
        if line.startswith(f"{name}=")
    ]
    assert matches, f"{path.name} declares no {name}="
    assert len(matches) == 1, f"{path.name} declares {name}= more than once"
    return matches[0]


def _expand(command: str, *, home: str, instance: str) -> str:
    """The line's text as systemd hands it to the kernel, minimally.

    Only the three substitutions the units use are applied, all documented
    in ``systemd.service(5)`` and ``systemd.unit(5)``: the ``%h``
    specifier becomes the operator's home, ``%i`` the instance name the
    manager started the template with, and ``$$`` a single ``$`` —
    systemd's own escape for a dollar it must not expand before the shell
    sees it.  Specifier expansion is textual and ignores the shell's
    quoting, which is why ``--unit %i`` inside the quoted command string
    still expands here.
    """
    return command.replace("$$", "$").replace("%h", home).replace("%i", instance)


# -- The trigger: which failure starts the hook ---------------------------------


def test_the_rebalance_unit_names_the_alert_template_on_failure() -> None:
    """The hook itself: unit failure starts one instance of the template.

    ``%n`` — not a hard-coded instance — so the manager starts
    ``nullius-vst-alert@nullius-vst-rebalance.service.service``, the
    template with the failed unit's own full name as its instance: the
    one spelling ``journalctl --user -u`` accepts as-is.  The template
    must ship beside the unit that names it, or the hook points at
    nothing.
    """
    on_failure = _directive(REBALANCE_UNIT_PATH, "OnFailure")
    assert on_failure == "OnFailure=nullius-vst-alert@%n.service"
    assert ALERT_TEMPLATE_PATH.is_file()


def test_exits_one_and_three_stay_successes_not_failures() -> None:
    """The hook's boundary: a slot that *ran* is never paged urgently.

    Exit 1 (a refused leg) and exit 3 (a daily-loss halt) are slot
    outcomes, reported by the slot itself; they stay in
    ``SuccessExitStatus``, so systemd records the unit as succeeded and
    ``OnFailure`` never fires for them.  Dropping either code from this
    line would turn every refused leg into an urgent *"could not run"*
    page — the false alarm this spec is careful not to send — and hammer
    it on every slot of a day the daily-loss halt stands.
    """
    success = _directive(REBALANCE_UNIT_PATH, "SuccessExitStatus")
    codes = {int(code) for code in success.removeprefix("SuccessExitStatus=").split()}
    assert codes == {0, 1, 3}


# -- The hook: what the started instance runs -----------------------------------


def test_the_template_is_a_oneshot_that_runs_the_alert_command() -> None:
    """The template's shape: one alert, once, naming the failed unit.

    ``--unit %i`` — not a literal unit name — so the same template serves
    any unit that names it in ``OnFailure=``, and the alert always quotes
    the unit that actually failed.
    """
    assert _directive(ALERT_TEMPLATE_PATH, "Type") == "Type=oneshot"
    exec_start = _directive(ALERT_TEMPLATE_PATH, "ExecStart")
    assert exec_start.removeprefix("ExecStart=").startswith("/bin/sh -c ")
    assert "run.sh vst-alert --unit %i --event failure" in exec_start
    # The failed unit is named only through the instance specifier.
    assert "nullius-vst-rebalance" not in exec_start


def test_the_template_carries_the_rebalance_unit_s_own_path() -> None:
    """Same defect, same fix: the hook needs ``uv`` on PATH too.

    The template's ``Environment`` line is the rebalance unit's own —
    ``%h/.local/bin`` first, where ``uv`` lives, then the system
    directories for ``op``, ``/bin/sh`` and the ordinary tools — because
    ``run.sh`` runs ``uv run`` for the alert exactly as it does for a
    slot, and a service inherits neither the login shell's PATH nor its
    token.
    """
    environment = _directive(ALERT_TEMPLATE_PATH, "Environment")
    assert environment == _directive(REBALANCE_UNIT_PATH, "Environment")
    entries = environment.removeprefix("Environment=PATH=").split(":")
    assert entries[:4] == ["%h/.local/bin", "/usr/local/bin", "/usr/bin", "/bin"]


def test_the_template_loads_the_token_file_like_the_rebalance_unit() -> None:
    """Same defect, same fix: ``op`` needs the service-account token.

    The whole prologue before ``exec`` is the rebalance unit's own, byte
    for byte: the token is read from the operator's mode-0600 file at
    start — with the literal-dollar escapes systemd requires — exported,
    and guarded so that a missing or unreadable file fails the unit with
    a message naming it, rather than running ``op`` credential-less.  The
    two units evolve together; a divergence here is a bug, not a choice.
    """
    template_exec = _directive(ALERT_TEMPLATE_PATH, "ExecStart")
    rebalance_exec = _directive(REBALANCE_UNIT_PATH, "ExecStart")

    def prologue(exec_start: str) -> str:
        return exec_start.removeprefix("ExecStart=").split("exec ", 1)[0]

    assert prologue(template_exec) == prologue(rebalance_exec)

    assert "OP_SERVICE_ACCOUNT_TOKEN=" in template_exec
    # The value is read from the operator's file, never written in.  Both
    # substitutions are applied together: systemd turns `%h` into the home
    # and the escaped `$$` into the single `$` the shell then runs.
    expanded = _expand(
        template_exec.removeprefix("ExecStart="),
        home="/home/operator",
        instance=FAILED_UNIT_NAME,
    )
    assert f"$(cat /home/operator{TOKEN_FILE_SUFFIX})" in expanded
    # The dollar of that command substitution is escaped in the *source*,
    # so it survives the manager's own expansion and reaches the shell.
    assert "$$(cat" in template_exec


def test_no_unit_carries_a_literal_service_account_token() -> None:
    """No token, key or secret is ever written into a repository file.

    1Password service-account tokens carry an ``ops_`` prefix; neither
    unit may contain such a string, and any line mentioning the token
    variable must assign it *from* the operator's file.  Comments may name
    the variable without assigning it, which is documentation, not a leak.
    """
    for path in (REBALANCE_UNIT_PATH, ALERT_TEMPLATE_PATH):
        text = _unit_text(path)
        assert "ops_" not in text, path.name
        for index, line in enumerate(text.splitlines(), start=1):
            if line.startswith("#") or "OP_SERVICE_ACCOUNT_TOKEN" not in line:
                continue
            assert "OP_SERVICE_ACCOUNT_TOKEN=" in line, (
                f"{path.name} line {index} mentions the token without "
                "assigning it from the file"
            )
            assert "cat" in line and TOKEN_FILE_SUFFIX in line


# -- The hook's own environment, exercised as systemd would give it --------------


def _template_environment(home: Path) -> dict[str, str]:
    """The environment systemd would give the template's own ``ExecStart``.

    Only the keys ``Environment=PATH`` declares are supplied — a systemd
    user service inherits the manager's environment, whose PATH is the one
    this line overwrites — plus ``HOME`` (which is how ``%h`` resolves)
    and ``USER``.  Nothing else: ``subprocess.run(env=…)`` replaces the
    whole environment, which is the ``env -i`` proof the spec asks for —
    if the unit does not supply PATH and the token itself, the child does
    not see them.
    """
    path = _directive(ALERT_TEMPLATE_PATH, "Environment").removeprefix(
        "Environment=PATH="
    )
    return {
        "PATH": _expand(path, home=str(home), instance=FAILED_UNIT_NAME),
        "HOME": str(home),
        "USER": "operator",
    }


def _run_template(tmp_path: Path, *, token: str | None) -> subprocess.CompletedProcess:
    """Exercise the shipped template ExecStart in a systemd-like environment.

    ``%h`` is the temporary home, so ``%h/projects/nullius/run.sh`` is a
    stub written here rather than the repository's own wrapper — the point
    is the environment and the arguments that reach it, not what the
    wrapper then does.  ``%i`` expands to the failed unit's full name, the
    instance the rebalance unit's ``OnFailure=%n`` builds.  The stub
    records what it was handed *to a file* — never to stdout — so a
    passing run can assert the token arrived without it entering any
    captured output.
    """
    home = tmp_path / "home"
    repo = home / "projects" / "nullius"
    repo.mkdir(parents=True)
    marker = tmp_path / "stub-env.txt"
    stub = repo / "run.sh"
    stub.write_text(
        "#!/bin/sh\n"
        f'printf "ARGV=%s\\nTOKEN=%s\\nPATH=%s\\n" "$*" '
        f'"$OP_SERVICE_ACCOUNT_TOKEN" "$PATH" > "{marker}"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    if token is not None:
        token_file = home / ".config" / "op" / "service-token"
        token_file.parent.mkdir(parents=True)
        token_file.write_text(token, encoding="utf-8")
        token_file.chmod(0o600)

    exec_start = _expand(
        _directive(ALERT_TEMPLATE_PATH, "ExecStart").removeprefix("ExecStart="),
        home=str(home),
        instance=FAILED_UNIT_NAME,
    )
    return subprocess.run(
        ["/bin/sh", "-c", exec_start],
        cwd=repo,
        env=_template_environment(home),
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_missing_token_file_fails_the_alert_hook_closed(tmp_path: Path) -> None:
    """Fails closed: no token file means the hook stops, it does not run ``op``.

    The template's ExecStart runs in an ``env -i`` environment built from
    its own ``Environment=PATH``, with ``run.sh`` replaced by a stub.  A
    missing token file must yield a non-zero exit — the guard's exit 2 —
    with a message naming the file, and ``run.sh`` must never have been
    reached: an urgent alert is not worth running ``op`` without
    credentials.
    """
    result = _run_template(tmp_path, token=None)

    assert result.returncode != 0, result.stdout
    assert TOKEN_FILE_SUFFIX in result.stderr
    # The unit's own message, not merely whatever `cat` printed — so a
    # failure names the token file rather than looking like an unrelated
    # command error.
    assert "unreadable" in result.stderr
    assert not (tmp_path / "stub-env.txt").exists()


def test_the_expanded_exec_start_hands_path_token_and_unit_to_run_sh(
    tmp_path: Path,
) -> None:
    """The whole clause, on the command the template actually ships.

    The ExecStart runs against a stub ``run.sh`` in a bare environment,
    with ``%h`` the temporary home and ``%i`` the failed unit's full name
    — the instance the rebalance unit's ``OnFailure=%n`` builds.  Three
    things must reach the child: the ``%h/.local/bin`` PATH entry (where
    ``uv`` lives), the token read from ``%h/.config/op/service-token``
    (its value never written into the unit), and the failed unit's name
    as the ``--unit`` argument, so the alert names the unit that failed
    and not the template it ran from.
    """
    # A synthetic placeholder, in a temporary directory — not a
    # credential, and deliberately not shaped like one.
    token = "token-value-read-from-the-operators-file"
    result = _run_template(tmp_path, token=token)

    assert result.returncode == 0, result.stderr
    # The placeholder reaches the child only through the operator's file;
    # it enters no captured output on the way.
    assert token not in result.stdout
    assert token not in result.stderr
    recorded = (tmp_path / "stub-env.txt").read_text(encoding="utf-8")
    assert f"ARGV=vst-alert --unit {FAILED_UNIT_NAME} --event failure\n" in recorded
    assert f"TOKEN={token}\n" in recorded
    path_line = next(
        line for line in recorded.splitlines() if line.startswith("PATH=")
    )
    first_entry = path_line.removeprefix("PATH=").split(":")[0]
    assert first_entry == str(tmp_path / "home" / ".local" / "bin")
