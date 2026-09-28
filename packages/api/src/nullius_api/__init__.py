"""The HTTP transport over the composed application.

The ``api`` workspace member serves what every other member built:
app_spec.xml's ``<api_endpoints_summary>`` promises ten HTTP routes,
each already an in-process endpoint object registered with the factory
(``ops-fdr-deploy``, ``ledger-debit``, ``risk-halt``, …), and nothing
served them over HTTP — the gap docs/user-journeys/RESULTS.md's run 1
records as every API journey ending in ``ERR_CONNECTION_REFUSED``.
This member is the transport that closes it: it composes the
application with :func:`app.module_loader.create_app`, resolves each
route's component from what composition built
(:mod:`nullius_api.routes`), and serves it over the standard library's
:class:`~http.server.ThreadingHTTPServer` with a JSON body for every
response (:mod:`nullius_api.server`), started with ``python -m
nullius_api`` (:mod:`nullius_api.__main__`) and bound to 127.0.0.1
unless a host is named explicitly.

Every route but ``GET /healthz`` needs a bearer token, and the token
carries one of four scopes which the route's own row states
(:mod:`nullius_api.auth` — feature 18): a missing or unknown token
answers 401, a token outside the route's scope answers 403, and a
deployment that names no token file is refused at startup rather than
served open.

The member owns no endpoint and computes no figure.  Its whole law is
the constraint additions_spec_journeys.xml states for it: standard
library only for HTTP (``http.server``, ``json``) so the lockfile gains
no third-party edge; every response a JSON body; an empty store
answered as the members' honest ``null``/empty, never a fabricated
``0.0``; and no response body carrying a traceback or a filesystem
path.  The route-by-route serving behaviour — the retry, absence and
refusal statuses each endpoint's spec line promises — is layered on
this dispatch by the spec's per-route features without reshaping it.
"""

from .auth import (
    API_SCOPES,
    EVALUATOR,
    METRICS_READ,
    RESEARCH,
    RISK,
    TOKENS_FILE_ENV,
    ApiTokenConfigError,
    ApiTokens,
    bearer_token,
    load_tokens,
)
from .json_encoding import JsonEncodingError, dumps
from .routes import (
    API_ROUTES,
    INDEX_SCOPE,
    PRE_REGISTER_WRAP,
    PROMOTE_WRAP,
    ApiRoute,
    ResolvedRoute,
    resolve_routes,
    routes_by_path,
)
from .server import (
    BODY_TOO_LARGE_CLASS,
    COMPONENT_UNCONFIGURED_CLASS,
    DEFAULT_ERROR_CLASS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    EXECUTION_ENGINE_ENV,
    FORBIDDEN_CLASS,
    HOST_ENV,
    INTERNAL_ERROR_CLASS,
    MALFORMED_REQUEST_CLASS,
    MAX_BODY_BYTES,
    METHOD_NOT_ALLOWED_CLASS,
    PORT_ENV,
    PROMOTION_CONFLICT_CODE,
    PROMOTION_PARENT_ABSENT_CODE,
    READ_TIMEOUT_SECONDS,
    REQUEST_STALLED_CLASS,
    ROUTE_NOT_IMPLEMENTED_CLASS,
    TARGET_UNKNOWN_NODE_CLASS,
    UNAUTHENTICATED_CLASS,
    UNKNOWN_ROUTE_CLASS,
    ApiConfig,
    ApiRequest,
    ApiRequestHandler,
    ApiServer,
    ExecutionEngineResolutionError,
    build_server,
    error_payload,
    resolve_execution_engine,
)

__all__ = [
    "API_ROUTES",
    "API_SCOPES",
    "BODY_TOO_LARGE_CLASS",
    "COMPONENT_UNCONFIGURED_CLASS",
    "DEFAULT_ERROR_CLASS",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "EVALUATOR",
    "EXECUTION_ENGINE_ENV",
    "FORBIDDEN_CLASS",
    "HOST_ENV",
    "INDEX_SCOPE",
    "INTERNAL_ERROR_CLASS",
    "MALFORMED_REQUEST_CLASS",
    "MAX_BODY_BYTES",
    "METHOD_NOT_ALLOWED_CLASS",
    "METRICS_READ",
    "PORT_ENV",
    "PRE_REGISTER_WRAP",
    "PROMOTE_WRAP",
    "PROMOTION_CONFLICT_CODE",
    "PROMOTION_PARENT_ABSENT_CODE",
    "READ_TIMEOUT_SECONDS",
    "REQUEST_STALLED_CLASS",
    "RESEARCH",
    "RISK",
    "ROUTE_NOT_IMPLEMENTED_CLASS",
    "TARGET_UNKNOWN_NODE_CLASS",
    "TOKENS_FILE_ENV",
    "UNAUTHENTICATED_CLASS",
    "UNKNOWN_ROUTE_CLASS",
    "ApiConfig",
    "ApiRequest",
    "ApiRequestHandler",
    "ApiRoute",
    "ApiServer",
    "ApiTokenConfigError",
    "ApiTokens",
    "ExecutionEngineResolutionError",
    "JsonEncodingError",
    "ResolvedRoute",
    "bearer_token",
    "build_server",
    "dumps",
    "error_payload",
    "load_tokens",
    "resolve_execution_engine",
    "resolve_routes",
    "routes_by_path",
]
