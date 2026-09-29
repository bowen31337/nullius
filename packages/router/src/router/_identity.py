"""Feature 320's process identity, shared by the member's two seams.

app_spec.xml, "Order Routing & Venue Filters", feature 320: *"System
persists order submission health independently of feed health, running the
router in its own process."*  The sentence's third clause is the one this
module exists for: *the router in its own process* is only a fact a reader
can check if a persisted reading says **which process** produced it.

Why this is its own module rather than a function in
:mod:`router.submission_health` is the same reason :mod:`router.errors`
is its own module: a reader of the submission-health store answers a question
about *a process* — *is the router that is running right now the process
whose record a reader holds?* — and a reader that re-derived the identity
with its own ``socket.gethostname()``/``os.getpid()`` pair would be a
second spelling of one fact, free to drift from the one the store files
rows under.  A store whose rows say ``host/41`` and a reader that answers
``host/42`` is exactly the confusion this feature's own sentence rules
out, so the derivation lives once and both reach it here.

**Stdlib only, and no I/O that could fail.**  ``socket`` and ``os`` are
imported at module scope because both are the interpreter's own — there is
no third-party import here to defer, so the factory's workspace scan pays
nothing for this module's presence.  Deriving the identity opens no socket
and resolves no name: :func:`socket.gethostname` reads the kernel's own
host name, which is a local call with no network behind it.  That matters
because this function is called on the order path's own hot path, and a
liveness label that could block on DNS would be a liveness label the router
cannot afford to take.
"""

from __future__ import annotations

import os
import socket

__all__ = ["PROCESS_ID_SEPARATOR", "process_identity"]

#: The separator between the host half and the pid half of an identity.
#: A forward slash, matching the ``<host>/<pid>`` spelling
#: ``docs/nullius-tech-architecture.md`` §16's live metrics use for their
#: own labels and the conventional ``host/pid`` an operator's log tooling
#: already splits on.  It is deliberately not ``:``, which would make the
#: identity look like an ``host:port`` socket address — this is a *name*
#: for a process, and nothing in this member ever dials it.
PROCESS_ID_SEPARATOR = "/"


def process_identity() -> str:
    """This process's identity, as ``<host>/<pid>``.

    The label every submission-health row this process files is grouped by,
    so a reader can ask about one router — ``host/4711`` — rather than about
    the deployment's submissions as an undifferentiated pool.

    **The host and pid halves are read, never configured.**  An identity
    taken from an environment variable or a setting would be an identity a
    deployment could set to the *same* value on two processes, which is the
    one state the identity exists to make impossible: two routers behind one
    label, each reading the other's rejections as its own.  The kernel
    already distinguishes the two, so the kernel is asked.  Nothing else is
    added — no boot id, no start time, no counter — because a label is not
    an address and a later feature that wants to tell a *restart* of one pid
    from the original has the persisted observations' own timestamps to read
    it off, without this function having to store one.

    Deterministic within a process and cheap to call: two calls in one
    process answer the same string, so a value layer, a seat and a test can
    each ask without holding a cached copy, and the store caches only
    because it asks once per write rather than once per call.
    """
    host = socket.gethostname() or "unknown-host"
    return f"{host}{PROCESS_ID_SEPARATOR}{os.getpid()}"
