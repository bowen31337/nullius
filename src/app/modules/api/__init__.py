"""The api member's seat in the ``app`` package namespace.

The member (``packages/api``, import name ``nullius_api``) is the HTTP
transport over the composed application; it registers no component of
its own; it composes the application and serves the endpoints the other
members register. See additions_spec_journeys.xml.

Every route but ``GET /healthz`` requires a bearer token, read from the
JSON file ``NULLIUS_API_TOKENS_FILE`` names, and each token carries one
of four scopes — ``metrics:read``, ``research``, ``evaluator``, ``risk``
— which the route's own row in ``nullius_api.routes.API_ROUTES`` states
(feature 18).  A deployment that names no token file is refused at
startup rather than served open, so this seat still registers nothing:
the transport's whole configuration is the flag surface, that variable
and the execution-engine path.

Feature 21 adds two more variables to that surface and no component
either: a bind other than the loopback interface must name a
certificate and key in ``NULLIUS_API_TLS_CERT`` and
``NULLIUS_API_TLS_KEY`` or the server refuses to start, and with them
it serves HTTPS through the standard library's ``ssl`` module, so a
bearer token never crosses a network in cleartext.  The seat registers
nothing for this either — there is no endpoint behind it, only the
address the transport is willing to take.

Feature 20 adds the transport's testimony and no component: one
structured access-log record per request — whatever the outcome — on
the ``nullius_api.access`` logger, carrying the token's scope *name*,
the verb, the route, the status and the latency in milliseconds, and
never the request body and never the token (feature 19 already refused
to echo the body; this is the log-shaped half of the same law).  A
deployment points one handler at ``nullius_api`` and receives the
stream; the member persists nothing for it, because the sentence names
a logger and not a store.
"""
