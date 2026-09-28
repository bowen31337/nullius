"""``python -m nullius_api`` — the entrypoint that boots the transport.

The command the spec's feature 4 names on the wire: compose the
application the factory builds, resolve the route table over it, bind
the address the flags and the environment state, and serve.  Nothing
here is a knob the routes care about — the entrypoint's whole job is
the *order* of those four acts, because the order is the safety
posture: the engine named by :data:`NULLIUS_EXECUTION_ENGINE` is bound
*before* the socket opens (a deployment whose engine path is broken is
refused at startup, never served half-wired), and the composition runs
*before* the address is taken (an uncomposable workspace refuses to
start rather than answering every route with the internal error).

Address precedence is the feature sentence's own: ``--host`` /
``--port`` win, then ``NULLIUS_API_HOST`` / ``NULLIUS_API_PORT``, then
127.0.0.1 and the default port — a server started with no
configuration at all serves its operator on the loopback interface and
nothing else.

A misconfiguration is reported as one plain sentence on standard error
and exit status 2 — the same refusal-to-start stance the spec's later
token feature takes for a missing token file, applied here to a port
that is not a port and an engine path that does not resolve.  Never a
traceback: an operator starting the server is exactly the reader the
structured refusals exist for.

The token file is read **first of all**, ahead of the port, ahead of
the engine and ahead of composition, and that order is the safety
posture rather than tidiness: *a missing token file is a refusal to
start, not an open server* (the constraint's own words), so the
credentials are the first thing established and every later step is
downstream of a deployment that has some.  A port that cannot be
parsed is reported before an engine that cannot be imported only
because it is cheaper the other way round; a token file that cannot be
read is reported before both because it is the one failure that would
otherwise serve an open API.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence

from .auth import (
    API_SCOPES,
    TOKENS_FILE_ENV,
    ApiTokenConfigError,
    ApiTokens,
)
from .routes import API_ROUTES
from .server import (
    EXECUTION_ENGINE_ENV,
    ApiConfig,
    ExecutionEngineResolutionError,
    build_server,
    resolve_execution_engine,
)

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    """The flag surface: ``--host`` and ``--port``, nothing else."""
    parser = argparse.ArgumentParser(
        prog="python -m nullius_api",
        description=(
            "Serve the composed application's endpoints over HTTP with "
            "JSON bodies (app_spec.xml's api_endpoints_summary; "
            "additions_spec_journeys.xml feature 4). Binds 127.0.0.1 "
            "unless --host or NULLIUS_API_HOST names another address."
        ),
        epilog=(
            f"{len(API_ROUTES)} routes are declared; the flags, "
            f"{EXECUTION_ENGINE_ENV} and {TOKENS_FILE_ENV} are the "
            "deployment's whole configuration surface. Every route but "
            "GET /healthz needs a bearer token carrying the route's "
            f"scope ({', '.join(API_SCOPES)})."
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        metavar="ADDRESS",
        help=(
            "the interface to bind (default: 127.0.0.1; the "
            "NULLIUS_API_HOST environment answers when the flag is "
            "absent)"
        ),
    )
    parser.add_argument(
        "--port",
        default=None,
        type=int,
        metavar="PORT",
        help=(
            "the TCP port to bind (default: the NULLIUS_API_PORT "
            "environment, else the built-in default)"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Read the tokens, compose, resolve, bind, serve — in that order.

    Returns the process exit status: 0 after a clean shutdown
    (``KeyboardInterrupt`` included — an operator stopping their own
    server is not an error), 2 for a misconfiguration refused before
    the socket opened.  Any other fault while serving is logged by the
    server's own logging; the serve loop is designed not to raise out
    of :meth:`~http.server.BaseServer.serve_forever` for a per-request
    fault (the handler answers those as refusals).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _build_parser().parse_args(argv)

    # The tokens, first and unconditionally: a deployment that
    # configured none gets the refusal before anything else this
    # function could do, so there is no ordering in which a server
    # reaches a bound socket without credentials.  Loaded here rather
    # than left to ``build_server``'s own default so the refusal is
    # reported by name at this door, where the operator is looking.
    try:
        tokens: ApiTokens = ApiTokens.from_env()
    except ApiTokenConfigError as exc:
        print(f"nullius_api: {exc}", file=sys.stderr)
        return 2

    try:
        config = ApiConfig.resolve(host=args.host, port=args.port)
    except ValueError as exc:
        print(f"nullius_api: {exc}", file=sys.stderr)
        return 2

    try:
        engine = resolve_execution_engine(os.environ.get(EXECUTION_ENGINE_ENV))
    except ExecutionEngineResolutionError as exc:
        print(f"nullius_api: {exc}", file=sys.stderr)
        return 2

    # Composition before the socket: a store-bound component that
    # cannot even be *asked* to build is a workspace fault an operator
    # must see at startup, not a server that answers every route with
    # the internal error.  The factory never raises for an unconfigured
    # environment — that resolves to endpoint-less routes the server
    # answers with the unconfigured refusal.
    server = build_server(config, execution_engine=engine, tokens=tokens)
    host, port = server.server_address[:2]
    logging.getLogger("nullius_api.server").info(
        "nullius-api listening on http://%s:%s", host, port
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.getLogger("nullius_api.server").info("nullius-api stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - the entrypoint itself
    raise SystemExit(main())
