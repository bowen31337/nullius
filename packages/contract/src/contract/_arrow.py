"""The Arrow seam: the one place in this package that reaches for pyarrow.

Feature 14 names Arrow IPC as the format a materialized window travels in
(app_spec.xml; docs/nullius-tech-architecture.md §5.2, ``payload=
window.to_arrow()``).  pyarrow is therefore a declared dependency of this
member — but the import itself is deferred to first use, and that is
deliberate rather than incidental.

The ``contract`` package is imported by the application factory's workspace
scan (``app.module_loader``), so anything this package imports at module
scope is imported during composition.  A hard ``import pyarrow`` here would
make pyarrow a precondition for *composing the application*, which is a much
larger blast radius than the feature needs: the window contract, the ABI
record and every accessor that has not materialized anything yet need no
Arrow at all.  Deferring the import keeps the member import-safe in exactly
the environments the workspace contract promises one will be — the factory
scan, a test sandbox, the deterministic replay path — while the payload
paths that genuinely need Arrow raise a named error the moment they are
reached without it.

:func:`coerce_table` lives here rather than in ``payload`` because window
construction needs it too: a frame is normalized to an Arrow table the
moment it enters a window (see :func:`contract.window._as_frames`), not when
the window is serialized.
"""

from __future__ import annotations

__all__ = ["coerce_table", "require_arrow"]


def require_arrow():
    """Import and return pyarrow, or raise a named, actionable error.

    Imported lazily on every call rather than cached in a module global: the
    cost is a ``sys.modules`` dict lookup after the first import, and a cache
    would be a lie in the one environment where this matters — a test that
    installs, removes or monkeypatches pyarrow mid-process.
    """
    try:
        import pyarrow
        import pyarrow.ipc  # noqa: F401 - registers the ``.ipc`` submodule
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ModuleNotFoundError(
            "Arrow IPC serialization requires pyarrow, which is a declared "
            "dependency of the nullius-contract member but is not installed "
            "in this environment; run `uv sync` (or `pip install pyarrow`) "
            "in the workspace root"
        ) from exc
    return pyarrow


def coerce_table(arrow, name: str, frame: object):
    """Normalize one named frame to a :class:`pyarrow.Table`.

    A frame is accepted as an Arrow table or record batch (passed through,
    never copied), or as anything :func:`pyarrow.table` can convert — most
    usefully a Polars frame, which converts through the Arrow C data
    interface without an intermediate Python representation.  Anything else
    is refused *here*, at construction, rather than at serialization time:
    a window whose equality and serialization depend on a frame's type is
    only well defined if the type is pinned when the window is built.
    """
    if isinstance(frame, arrow.Table):
        return frame
    if isinstance(frame, arrow.RecordBatch):
        return arrow.Table.from_batches([frame])
    if frame is None:
        raise TypeError(
            f"frame {name!r} must be an Arrow table, batch or Arrow-convertible "
            "frame, not None"
        )
    try:
        return arrow.table(frame)
    except Exception as exc:  # noqa: BLE001 - pyarrow raises several shapes here
        raise TypeError(
            f"frame {name!r} of type {type(frame).__name__} cannot be "
            f"converted to an Arrow table: {exc}"
        ) from exc
