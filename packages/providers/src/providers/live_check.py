"""The live-provider smoke test — one real model call, one JSON line.

``python -m providers.live_check --pin PROVIDER/MODEL/VERSION [--prompt
TEXT] [--max-tokens N] [--record DIR]`` is the first thing a deployment runs
against a pin before trusting it: it builds the live provider feature 4's
:func:`providers._live.live_provider` names for the pin, sends it exactly one
user message, checks the answer with :func:`providers._live.require_served`
(the §14.1 check — a vendor must serve the model the pin named, or a
dated snapshot of it, never something else), and prints one line describing
what came back. Optionally, ``--record DIR`` files the exchange as a fixture
through :class:`providers.FixtureStore`, so a live answer captured here
becomes an offline fixture feature 193's backend can replay later.

**Why a separate command rather than a library call.**  Every other module
in this member is import-safe and touches no network; this is the one place
the addition is deliberately allowed to open a socket, and it is a command
rather than a function precisely so that fact is visible — a deployment runs
it by hand (or from a smoke-test job) to answer "does this pin still work
the way it did yesterday?", never imports it into a request path.

**What this module never does.**  It never reads a credential directly: the
key lives in whatever environment variable :func:`providers._live.
live_provider` resolves for the pin's vendor, and this module only ever
holds the *built provider*, never the string. Every line this command
writes — the success line and the one-line refusal alike — is built from
the pin, the completion and the error's own message, none of which can
carry a vendor credential; the door the provider's transport runs through
(:mod:`providers._live_http`) is what scrubs a credential out of a transport
failure's own message before it ever reaches here.

**Exit codes.**  ``0`` for a served, checked completion, printed (and
recorded, when asked). ``1`` for any :class:`~providers.ProviderError` the
pin, the call or the served-model check raised — one line on stderr naming
the refusal's own code word and its message. ``2`` for a bad argument: a
missing ``--pin``, a ``--pin`` that is not a clean ``provider/model/version``
triple, or a ``--max-tokens`` that is not an integer — argparse's own usual
door, so the message and the exit status are the ones every other command in
this workspace already gives a bad invocation.

**Testability is every keyword of** :func:`main`. ``env`` is the mapping
:func:`providers._live.live_provider` reads the vendor's credential from
(``os.environ`` when ``None``); ``transport`` is the callable feature 1's
door sends through (``urllib.request`` when ``None``); ``emit`` is what the
one success line is printed with (:func:`print` by default, so a caller can
capture it as a value instead of parsing captured stdout); ``clock`` is
what measures ``latency_ms`` (:func:`time.monotonic` by default, read once
around the one call this command makes). A test drives the whole command
with a fake key and a scripted transport and never opens a socket, and the
suite that keeps the credential out of every rendering reads it straight off
``capsys`` — this module's own stdout and stderr, not a mock.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from ._errors import ProviderError
from ._fixture import FixtureStore
from ._live import live_provider, require_served
from ._live_http import Transport
from ._pin_errors import RollingAliasError
from ._pinning import ModelPin
from ._recorder import Exchange
from ._request import Message, Request

__all__ = [
    "CONTENT_PREVIEW_LENGTH",
    "DEFAULT_PROMPT",
    "main",
]

#: The prompt a call carries when the caller names none — short, and
#: answerable by every pinned vendor without the answer itself being
#: interesting, because the point of this command is "did the call
#: complete and was it served by the right model", not "is the answer
#: good".
DEFAULT_PROMPT: Final[str] = "Reply with the single word: ok"

#: How much of the completion's content the summary line carries.  Long
#: enough to recognise the answer, short enough that a line this command
#: prints is a line an operator can read at a glance rather than a
#: transcript to scroll through.
CONTENT_PREVIEW_LENGTH: Final[int] = 200


def _parse_pin(value: str) -> ModelPin:
    """Read ``--pin``'s value as a :class:`~providers.ModelPin`.

    The argument's own ``type=`` callable, so a value that is not a clean
    ``provider/model/version`` triple is refused by argparse itself — one
    stderr message and exit code 2, the same door every bad argument in
    this workspace leaves through — rather than reaching the call and
    being refused mid-run as a :class:`~providers.ProviderError`.
    :class:`~providers.RollingAliasError` is translated into
    :class:`argparse.ArgumentTypeError`, which is the one exception
    argparse's own ``type=`` machinery already knows how to turn into that
    door.
    """
    try:
        return ModelPin.parse(value)
    except RollingAliasError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _build_parser() -> argparse.ArgumentParser:
    """The command's one parser, built fresh per call so a test owns its state."""
    parser = argparse.ArgumentParser(
        prog="python -m providers.live_check",
        description=(
            "Make one real model call through the live-provider registry, "
            "check it was served by the pinned model, and print one JSON "
            "line describing what came back."
        ),
    )
    parser.add_argument(
        "--pin",
        required=True,
        type=_parse_pin,
        metavar="PROVIDER/MODEL/VERSION",
        help="the pinned model to call",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help=f"the user message to send (default: {DEFAULT_PROMPT!r})",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="the output ceiling to request (default: the interface's own)",
    )
    parser.add_argument(
        "--record",
        type=Path,
        default=None,
        metavar="DIR",
        help="file the exchange as a fixture in this directory (feature 194)",
    )
    return parser


def _refusal_line(exc: ProviderError) -> str:
    """The one stderr line a :class:`~providers.ProviderError` prints as.

    Every refusal in this member that carries a greppable ``code`` already
    opens its own message with it — the discipline each one's docstring
    states: *"the token and the class are one edit and cannot drift
    apart"*.  For the three that carry none
    (:class:`~providers.ProviderNotConfiguredError`,
    :class:`~providers.CompletionMalformedError`,
    :class:`~providers.UnknownModelError`), the class name is the fallback
    code word — the same answer :mod:`router.bingx_flatten`'s own
    ``_refusal_code`` gives for a refusal with no code of its own, so a
    line here always carries a token an operator can grep whichever kind
    of :class:`~providers.ProviderError` stopped the call.
    """
    code = getattr(exc, "code", None) or type(exc).__name__
    message = str(exc)
    prefix = f"{code}: "
    if not message.startswith(prefix):
        message = prefix + message
    return message


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    emit: Callable[[str], object] = print,
    clock: Callable[[], float] | None = None,
) -> int:
    """The command: one real call, one checked completion, one JSON line.

    Builds the pin's live provider (:func:`providers._live.live_provider`),
    sends one user-role message carrying ``--prompt`` (or
    :data:`DEFAULT_PROMPT`), and runs the answer through
    :func:`providers._live.require_served` before trusting it. With
    ``--record DIR`` the checked exchange is filed through
    ``providers.FixtureStore(DIR).record(...)`` before the summary line is
    printed, so a run that could not be filed never reports a success it
    did not fully deliver.

    The summary line — the only thing ``emit`` is called with — carries
    the pin, the model that actually served the call, the finish reason,
    the three usage counts, the measured latency in milliseconds and the
    first :data:`CONTENT_PREVIEW_LENGTH` characters of the answer, as one
    JSON object.

    ``env``, ``transport``, ``emit`` and ``clock`` are every one of this
    command's seams to the outside world: the credential's source, the
    call's wire, the success line's sink and the latency's clock. A caller
    that injects nothing gets the real environment, ``urllib.request``,
    real :func:`print` and :func:`time.monotonic` — a deployment running
    the command for real. Returns ``0`` on a served, checked and (when
    asked) recorded completion; ``1`` when any
    :class:`~providers.ProviderError` stopped the pin, the call or the
    served-model check, after one line on stderr naming the refusal's own
    code word and message; argparse itself exits ``2`` for a bad argument
    before this function's own body ever runs.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    read_clock = time.monotonic if clock is None else clock

    try:
        provider = live_provider(args.pin, env, transport)
        request_kwargs: dict[str, object] = {}
        if args.max_tokens is not None:
            request_kwargs["max_tokens"] = args.max_tokens
        request = Request(
            messages=(Message(role="user", content=args.prompt),),
            model=args.pin.model,
            **request_kwargs,
        )
        started = read_clock()
        completion = provider.complete(request)
        latency_ms = (read_clock() - started) * 1000.0
        completion = require_served(args.pin, completion)
        if args.record is not None:
            FixtureStore(args.record).record(
                Exchange(request=request, completion=completion)
            )
    except ProviderError as exc:
        print(_refusal_line(exc), file=sys.stderr)
        return 1

    emit(
        json.dumps(
            {
                "pin": str(args.pin),
                "served_model": completion.model,
                "finish_reason": completion.finish_reason,
                "input_tokens": completion.usage.input_tokens,
                "output_tokens": completion.usage.output_tokens,
                "cache_read_tokens": completion.usage.cache_read_tokens,
                "latency_ms": round(latency_ms, 3),
                "content": completion.content[:CONTENT_PREVIEW_LENGTH],
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
