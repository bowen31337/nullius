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
"""
