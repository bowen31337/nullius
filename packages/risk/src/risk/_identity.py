"""Feature 322's process identity — whose kill this kill is.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 322: *"System runs
the risk supervisor as a separate process, which sends a kill instruction
to the order layer."*  The sentence's first clause is the one this module
exists for: *a separate process* is only a fact a reader can check if the
instruction that process sends says **which process** sent it.  A kill row
that named no sender would leave the order layer holding a refusal it
could not attribute — and §13.3's whole design (the supervisor separate,
so *"a hung strategy process cannot prevent a flatten"*) turns on the
killer and the killed being distinguishable in the record, because the one
failure an operator must be able to rule out after a kill is that the
strategy process killed itself on its way down and called it the
supervisor.

Why this is its own module rather than a function in :mod:`risk.kill` is
the same reason :mod:`router._identity` is its own module: a reader of
the kill switch answers a question about *a process* — *is the
process that sent this kill the process now asking about it?* — and a
reader that re-derived the identity with its own ``socket.gethostname()``/
``os.getpid()`` pair would be a second spelling of one fact, free to drift
from the one the switch files rows under.  A switch whose rows say
``host/41`` and a reader that answers ``host/42`` is exactly the confusion
feature 322's own sentence rules out, so the derivation lives once and
both reach it here.

**Stdlib only, and no I/O that could fail.**  ``socket`` and ``os`` are
imported at module scope because both are the interpreter's own — there is
no third-party import here to defer, so the factory's workspace scan pays
nothing for this module's presence.  Deriving the identity opens no socket
and resolves no name: :func:`socket.gethostname` reads the kernel's own
host name, which is a local call with no network behind it.  That matters
twice over here: the supervisor derives its identity on the send path, and
the order layer may derive its own on the read path to compare against the
row's — and an identity lookup that could block on DNS would be a lookup
a killed order layer could hang on, which is the one thing this member
cannot afford.
"""

from __future__ import annotations

import os
import socket

__all__ = ["PROCESS_ID_SEPARATOR", "process_identity"]

#: The separator between the host half and the pid half of an identity.
#: A forward slash, matching the ``<host>/<pid>`` spelling
#: ``docs/nullius-tech-architecture.md`` §16's live metrics use for their
#: own labels, the conventional ``host/pid`` an operator's log tooling
#: already splits on, and — by design — the same spelling
#: :mod:`router._identity` gives the order router's own identity, so a
#: single operator grep splits both processes' labels the same way.  It is
#: deliberately not ``:``, which would make the identity look like an
#: ``host:port`` socket address — this is a *name* for a process, and
#: nothing in this member ever dials it (§17: no inbound ports on the live
#: trading host).
PROCESS_ID_SEPARATOR = "/"


def process_identity() -> str:
    """This process's identity, as ``<host>/<pid>``.

    The label every kill instruction this process sends is filed under, so
    the order layer reading a standing kill learns *which supervisor*
    sent it — ``host/4711`` — rather than that *a supervisor* did, and an
    operator reconciling a kill (feature 331's noun) has a process to ask
    about.

    **The host and pid halves are read, never configured.**  An identity
    taken from an environment variable or a setting would be an identity
    a deployment could set to the *same* value on two processes — and two
    processes behind one label, where one of them is the strategy process
    and the other the supervisor, is exactly the state feature 322's
    *"separate process"* exists to make impossible.  The kernel already
    distinguishes the two, so the kernel is asked.  Nothing else is added
    — no boot id, no start time, no counter — because a label is not an
    address, and a later feature that must tell a *restart* of one
    supervisor from the original has the instruction's own ``sent_at`` to
    read it off, without this function having to store one.

    Deterministic within a process and cheap to call: two calls in one
    process answer the same string, so a value layer, a seat and a test
    can each ask without holding a cached copy, and the switch caches only
    because it asks once per send rather than once per call.
    """
    host = socket.gethostname() or "unknown-host"
    return f"{host}{PROCESS_ID_SEPARATOR}{os.getpid()}"
