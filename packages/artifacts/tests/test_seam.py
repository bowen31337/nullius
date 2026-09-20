"""The evaluator's step-12 seam: the store's contract, adapted.

Feature 85 (``feature-85-final-persist.md``) specifies the pipeline's
last step as writing "the full artifact to the artifact store" through
an injected ``ArtifactWriter`` — a structural protocol
(``evaluator._artifact``) exposing two operations:

.. code-block:: text

    write_artifact(node_id, campaign_id, filename, payload) -> None
    flush(node_id) -> None

This member contributes the store that seam's durability rests on, and
feature 169's staged-write-then-one-commit discipline is exactly the
discipline that seam is specified over.  The *signatures* are not the
same, though, and these tests exist to keep that distinction honest in
both directions:

* the store must **not** be claimed to *be* the protocol.  Its
  operations are ``write(campaign_id, node_id, filename, data)`` and
  ``commit(campaign_id, node_id)`` — campaign first, raw bytes, and
  neither name the protocol uses.  A store that silently answered to
  ``write_artifact`` with the arguments swapped would be worse than one
  that does not answer at all, so the divergence is pinned here rather
  than left to a docstring.
* the store must **satisfy** the protocol through the adapter the
  workspace contract requires.  Neither member may import the other
  (``packages/evaluator`` imports no sibling, and this member imports
  no evaluator), so the adapter lives with whoever injects the writer.
  What this suite proves is the part that is this member's: a thin
  adapter over the store — key order swapped, payload kind encoded to
  bytes, ``flush`` mapped onto the commit — drives the seam's two
  operations and leaves exactly one published directory per node, never
  a half-written one.

The adapter below is written as a *test* rather than shipped in the
member on purpose.  Shipping it would make this package speak the
evaluator's vocabulary, which is the coupling the workspace contract
exists to prevent; proving it is possible is this member's obligation.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pytest
from artifacts import ArtifactStore, artifact_uri


@dataclass(frozen=True)
class _Payload:
    """A stand-in for ``evaluator._artifact.ArtifactPayload``.

    Only the shape the adapter reads is mirrored: a ``kind`` naming the
    medium and the text the medium carries.  Frozen for the reason the
    evaluator freezes its own — a payload is a value handed across a
    seam, and a value editable between the render and the write is a
    file the renderer no longer vouches for.
    """

    kind: str
    json_text: str | None = None
    code_text: str | None = None


class _StoreWriter:
    """The adapter: the evaluator's seam, carried by this member's store.

    Maps the protocol's spelling onto the store's — node first becomes
    campaign first, a payload becomes the bytes its ``kind`` names, and
    ``flush`` is the store's commit point.  Nothing else: the whole
    point of the seam is that the writer owns the path and the encoding,
    and this store already owns both.
    """

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def write_artifact(
        self,
        node_id: str,
        campaign_id: str,
        filename: str,
        payload: _Payload,
    ) -> None:
        # The seam's key order is node, campaign; the store's is
        # campaign, node.  Swapping them here is the adapter's job, and
        # the one place the two spellings meet.
        self._store.write(
            campaign_id, node_id, filename, _encode(payload)
        )

    def flush(self, node_id: str) -> None:
        # The seam flushes per node and goes looking for the campaign
        # the staged writes named, which the store's commit needs as its
        # first key.  One staged node directory, one campaign parent.
        campaign_id = self._staged_campaign_of(node_id)
        self._store.commit(campaign_id, node_id)

    def _staged_campaign_of(self, node_id: str) -> str:
        staging = self._store.staging_root
        campaigns = [
            entry
            for entry in staging.iterdir()
            if entry.is_dir() and (entry / node_id).is_dir()
        ]
        assert len(campaigns) == 1, (
            f"the seam flushes one node at a time, so its staged writes "
            f"must name exactly one campaign — found {len(campaigns)} "
            f"for node {node_id!r}"
        )
        return campaigns[0].name


def _encode(payload: _Payload) -> bytes:
    """Render a payload's kind to the bytes a file holds."""
    if payload.kind in ("json", "code"):
        text = payload.json_text if payload.kind == "json" else payload.code_text
        assert text is not None, f"a {payload.kind} payload carries its text"
        return text.encode("utf-8")
    raise AssertionError(
        f"a parquet payload's bytes are the encoder's (features 170-173); "
        f"this adapter carries the text kinds — got {payload.kind!r}"
    )


def test_the_store_does_not_claim_the_seams_method_names(
    store: ArtifactStore,
) -> None:
    # The divergence, pinned: the protocol's names are not the store's
    # API.  This is not a gap to close — adapting is the injector's job —
    # but a store that grew ``write_artifact``/``flush`` aliases with
    # the *store's* argument order would be a trap for a caller holding
    # the protocol: it would match structurally and then misbind every
    # key.  So the names must stay absent, not merely different.
    assert not hasattr(store, "write_artifact")
    assert not hasattr(store, "flush")


def test_the_key_order_is_the_stores_own(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # ``write``/``commit`` take campaign first.  Asking the store in the
    # protocol's order (node, campaign) must not land a directory under
    # the node's name at the top level — the failure mode a swapped
    # signature would hide.
    store.write(campaign_id, node_id, "code.py", b"x")
    published = store.commit(campaign_id, node_id)
    assert published == store.root / campaign_id / node_id
    assert not (store.root / node_id).exists()


def test_the_adapter_drives_the_seam_to_one_published_directory(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The seam's two operations, end to end: every staged write, then one
    # flush.  Afterwards the node holds exactly the files the seam wrote,
    # at exactly the §9.2 address — which is the property feature 85
    # relies on and feature 169 provides.
    writer = _StoreWriter(store)

    writer.write_artifact(
        node_id,
        campaign_id,
        "decay_profile.json",
        _Payload(kind="json", json_text='{"fast": 0.5}'),
    )
    writer.write_artifact(
        node_id,
        campaign_id,
        "code.py",
        _Payload(kind="code", code_text="def signal(): ...\n"),
    )
    writer.flush(node_id)

    assert store.files(campaign_id, node_id) == (
        "code.py",
        "decay_profile.json",
    )
    assert store.read(campaign_id, node_id, "code.py") == b"def signal(): ...\n"


def test_a_seam_failure_before_the_flush_publishes_nothing(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The seam's stated guarantee — "a failure before it leaves nothing
    # half-written" — carried by this store.  A staged write that is
    # never flushed must leave no directory at the node's address at
    # all, so a reader walking the store cannot see a partial node.
    writer = _StoreWriter(store)
    writer.write_artifact(
        node_id,
        campaign_id,
        "decay_profile.json",
        _Payload(kind="json", json_text="{}"),
    )

    assert not store.has_node(campaign_id, node_id)
    assert (campaign_id, node_id) not in [
        (c, n) for c in store.campaign_ids() for n in store.node_ids(c)
    ]


def test_the_seam_flushes_one_node_without_disturbing_its_sibling(
    store: ArtifactStore, campaign_id: str, node_id: str, other_node_id: str
) -> None:
    # ``flush`` is per node, so a campaign's other nodes are untouched:
    # one node's publish is never another node's — the "one directory per
    # node" invariant read from the seam's side, and the reason the
    # adapter can resolve the campaign from the staged directory alone.
    writer = _StoreWriter(store)
    for target, text in ((node_id, "first"), (other_node_id, "second")):
        writer.write_artifact(
            target,
            campaign_id,
            "code.py",
            _Payload(kind="code", code_text=text),
        )
    writer.flush(node_id)

    assert store.has_node(campaign_id, node_id)
    assert not store.has_node(campaign_id, other_node_id)


def test_a_parquet_payload_is_not_the_adapters_to_encode(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The seam hands the writer a payload of three kinds; this member's
    # store holds bytes and does not encode.  The Parquet encoding is
    # features 170-173's (a layer above this one), so the adapter — which
    # carries only the text kinds — must refuse loudly rather than write
    # a file with no content, which is the failure a payload the adapter
    # silently mis-rendered would produce.
    writer = _StoreWriter(store)
    with pytest.raises(AssertionError, match="parquet"):
        writer.write_artifact(
            node_id,
            campaign_id,
            "signal_returns.parquet",
            _Payload(kind="parquet"),
        )


def test_the_protocol_the_adapter_satisfies_is_structural(
    store: ArtifactStore,
) -> None:
    # The evaluator's protocol is structural — it is never imported here,
    # and this suite must not import it either (the workspace contract).
    # What can be pinned without the import is that the adapter exposes
    # exactly the two callables the seam calls, with the seam's arity, so
    # a rename on either side shows up as a failure here rather than as
    # an ``AttributeError`` deep inside a pipeline step.
    writer: Any = _StoreWriter(store)
    assert callable(writer.write_artifact)
    assert callable(writer.flush)

    write_params = list(
        inspect.signature(writer.write_artifact).parameters
    )
    flush_params = list(inspect.signature(writer.flush).parameters)
    assert write_params == ["node_id", "campaign_id", "filename", "payload"]
    assert flush_params == ["node_id"]


def test_the_adapter_writes_under_the_configured_root(
    store: ArtifactStore,
    artifact_root: Path,
    campaign_id: str,
    node_id: str,
) -> None:
    # Everything the seam writes lands under the root the deployment
    # configured, keyed campaign then node — the address the tree store's
    # ``node.artifact_uri`` column names (§9.1) and replay later reads.
    writer = _StoreWriter(store)
    writer.write_artifact(
        node_id,
        campaign_id,
        "code.py",
        _Payload(kind="code", code_text="pass\n"),
    )
    writer.flush(node_id)

    assert unquote(urlparse(artifact_uri(store, campaign_id, node_id)).path) == str(
        artifact_root / campaign_id / node_id
    )
