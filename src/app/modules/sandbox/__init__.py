"""The sandbox module — app-level entrypoint for the sandbox workspace member.

The implementation lives in the ``sandbox`` workspace member
(``packages/sandbox``, import name ``sandbox``), which self-registers with the
application factory under the component name :data:`COMPONENT_NAME` — scanning
the workspace imports it, its ``@register`` decorator fires, and
``create_app()`` composes feature 157's isolation law, the value the rest of
the "Untrusted Code Sandbox" category (app_spec.xml, ``plugin="sandbox"``)
builds on: the network namespace (158), the payload-only channel (159), the
seccomp allowlist (160), the cgroup limits (162), the timeout (163), the
thread-pinning check (164), the seed (165), the Arrow payload (166), the
import allowlist (167) and the fail-class vocabulary (168).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/sandbox/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for
the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring the
factory's own "degrade, don't break" stance toward absent components.

**This seat answers exactly one question — *what is the composed isolation
law?* — and does not re-export the law's vocabulary.**  The run decision, the
reason codes, the policy and the component type live in the member, which is
where they are pinned; a caller who has the component calls its verbs —
``admits`` for a decision, ``require`` for the exception a launcher wants on
the last line before it forks, and ``isolation_of`` for the read side — and
each returns or raises the member's own type.  A second spelling of any of
that here would be a second thing to keep in sync, and the member's
one-provenance rule is the reason the category restates its vocabularies
rather than sharing them by import.

**Unlike the tripwires' seat, this one's ``None`` is a real absence.**  The
tripwires component is a stateless facade over a pure function with no
unconfigured state, so its ``None`` means exactly one thing; this component is
the same *shape* but not the same *fact* — it carries the compiled committed
policy, so an application that composed it holds a policy that was read from
disk and checked.  ``None`` therefore still means only "no sandbox component
was registered" — never "registered but not yet configured", because the
member's builder never returns ``None`` and never defers — but a caller
reading a non-``None`` component here is entitled to the stronger conclusion
that the deployment's isolation artifact compiled, which is a property worth
being able to check at the seat rather than inferring from the builder's
docstring.

**Feature 167's law has its own seat here, beside the isolation law's.**  The
import allowlist — *System rejects a submitted module importing anything
outside the configured allowlist, which returns a disallowed_import error
message* — is the category's second control to land, and it composes as its
own component (``sandbox-imports``) rather than a wider ``sandbox`` one, so
this module answers two questions now: *what is the composed isolation law?*
and *what is the composed import allowlist?*  The second accessor below
(:func:`sandbox_imports_component`) mirrors the first in every respect —
``None`` means "no such component was registered", and a non-``None`` value
is proof the committed allowlist artifact compiled — and re-exports nothing
of the law's vocabulary for the same reason the first does: a caller who has
the component calls its verbs (``screen`` for the decision a submission
earns, ``require`` for the exception a launcher wants), and each returns the
member's own type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from sandbox import SandboxImports, SandboxIsolation

__all__ = [
    "COMPONENT_NAME",
    "IMPORTS_COMPONENT_NAME",
    "sandbox_imports_component",
    "sandbox_isolation_component",
]

#: The component name the sandbox member registers under. Kept here so
#: anything asking the composed application for the isolation law — by way of
#: the app package, not the member — shares one spelling.
COMPONENT_NAME = "sandbox"

#: The component name the member's import allowlist registers under — the
#: category's second control, kept beside feature 157's rather than over it,
#: because the factory's registry replaces a name's earlier registration.
#: Kept here for the same reason ``COMPONENT_NAME`` is: one spelling shared
#: by everything that asks for the law through the app package.
IMPORTS_COMPONENT_NAME = "sandbox-imports"


def sandbox_isolation_component(
    app: Application | None = None,
) -> SandboxIsolation | Any:
    """Return the composed sandbox isolation law (feature 157).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``sandbox`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an empty
    workspace is for the factory.

    The returned law is usable immediately: the member's builder compiles the
    committed isolation artifact at build time and resolves nothing from the
    environment, so a non-``None`` component here is proof the policy loaded
    and the deployment's boxes are held to gVisor.  The only refusals a caller
    meets afterwards come from the runs it asks about.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)


def sandbox_imports_component(
    app: Application | None = None,
) -> SandboxImports | Any:
    """Return the composed sandbox import allowlist (feature 167).

    The same contract :func:`sandbox_isolation_component` gives the isolation
    law, for the control that screens a *submitted module's* imports against
    the configured ceiling: with ``app`` given the component is read from
    that application, without it the application is composed first, and
    ``None`` means no ``sandbox-imports`` component was registered — never
    "registered but not yet configured", for the same reason the isolation
    seat's ``None`` cannot mean that either.

    A non-``None`` component here is proof the committed allowlist artifact
    compiled: the member's builder reads it at build time and resolves
    nothing from the environment, so a caller holding the component holds a
    validated ceiling — ``screen(source)`` for the decision a submission
    earns, whose refusal detail is the ``disallowed_import`` message the
    feature's own sentence names.
    """
    application = app if app is not None else create_app()
    return application.get(IMPORTS_COMPONENT_NAME)
