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

from .json_encoding import JsonEncodingError, dumps
from .routes import (
    API_ROUTES,
    PRE_REGISTER_WRAP,
    PROMOTE_WRAP,
    ApiRoute,
    ResolvedRoute,
    resolve_routes,
    routes_by_path,
)
from .server import (
    COMPONENT_UNCONFIGURED_CLASS,
    DEFAULT_ERROR_CLASS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    EXECUTION_ENGINE_ENV,
    HOST_ENV,
    INTERNAL_ERROR_CLASS,
    MALFORMED_REQUEST_CLASS,
    METHOD_NOT_ALLOWED_CLASS,
    PORT_ENV,
    ROUTE_NOT_IMPLEMENTED_CLASS,
    TARGET_UNKNOWN_NODE_CLASS,
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
    "COMPONENT_UNCONFIGURED_CLASS",
    "DEFAULT_ERROR_CLASS",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "EXECUTION_ENGINE_ENV",
    "HOST_ENV",
    "INTERNAL_ERROR_CLASS",
    "MALFORMED_REQUEST_CLASS",
    "METHOD_NOT_ALLOWED_CLASS",
    "PORT_ENV",
    "PRE_REGISTER_WRAP",
    "PROMOTE_WRAP",
    "ROUTE_NOT_IMPLEMENTED_CLASS",
    "TARGET_UNKNOWN_NODE_CLASS",
    "UNKNOWN_ROUTE_CLASS",
    "ApiConfig",
    "ApiRequest",
    "ApiRequestHandler",
    "ApiRoute",
    "ApiServer",
    "ExecutionEngineResolutionError",
    "JsonEncodingError",
    "ResolvedRoute",
    "build_server",
    "dumps",
    "error_payload",
    "resolve_execution_engine",
    "resolve_routes",
    "routes_by_path",
]
