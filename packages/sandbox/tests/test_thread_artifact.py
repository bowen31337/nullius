"""Feature 164: the committed artifact — the pin the law checks a run against.

The step this file's subject makes checkable: *"a sandbox invocation missing the
thread-pinning environment"* is only a refusable condition if the deployment has
a written-down statement of what *the thread-pinning environment* is.  The
committed document (:data:`~sandbox.COMMITTED_PINNING_POLICY`) is that statement
— the pin a deployment runs with before anyone writes a stanza — and the tests
here read it the way an operator or a CI check would: compiled through the same
refusal as any change to it, holding exactly §12's two names at the pin, and
refusing to drift on disk exactly as it refuses in memory, *whole document
refused rather than the offending block skipped*.

**Why this control ships a committed artifact and features 165 and 166 do not.**
The seed is a value a run is *handed* and the payload channel is a format, a
direction and an alignment — neither is something a deployment could set
differently, so there is nothing for a file to say.  This feature's subject is
the environment a deployment *configures* a run with, which is the same class of
subject feature 157's gVisor posture and 167's import ceiling have: a
configuration is written down before it can be checked, and a pin that lives
only in a constant is a pin nobody can audit for drift.
"""

from __future__ import annotations

import json

import pytest
from _documents import (
    MKL,
    MKL_LAYER,
    OMP,
    OMP_LAYER,
    PIN,
    committed_pinning_document,
    pinning_document,
)
from sandbox import (
    COMMITTED_PINNING_POLICY,
    ENV_MKL,
    ENV_OMP,
    PINNING_POLICY_KIND,
    POOL_FLOOR_VARIABLE,
    SINGLE_THREADED,
    ThreadPinningDocumentError,
    ThreadPinningRequired,
    committed_thread_pinning_policy,
    compile_thread_pinning_policy,
    load_thread_pinning_policy,
)

#: The floor the deployment watches, spelled as *data* rather than imported: the
#: suite pins that the document names ``POLARS_MAX_THREADS``, and a test that
#: read the constant would follow a rename instead of catching one.
FLOOR: str = "POLARS_MAX_THREADS"


class TestTheArtifact:
    """The document on disk, as facts rather than prose."""

    def test_the_artifact_exists_beside_the_module(self) -> None:
        """The committed pin ships with the law that checks against it, so a
        checkout cannot hold one without the other."""
        assert COMMITTED_PINNING_POLICY.exists()

    def test_the_artifact_declares_its_kind(self) -> None:
        """It says what it is — the marker the compile holds it to, so a stray
        JSON file carrying a ``caps`` key cannot be read as this policy."""
        with COMMITTED_PINNING_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["policy"] == PINNING_POLICY_KIND

    def test_the_artifacts_caps_are_exactly_section_twelves_two(self) -> None:
        """The cap list is pinned exactly rather than by membership, so a third
        cap arriving unnoticed fails here — the same property the component test
        pins the member's component list for.  A policy that pinned a *third*
        variable would be a deployment decision made in this file, in review, or
        not at all."""
        with COMMITTED_PINNING_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert [(block["name"], block["value"]) for block in document["caps"]] == [
            (OMP, PIN),
            (MKL, PIN),
        ]

    def test_the_artifact_writes_the_floor_as_a_separate_list(self) -> None:
        """The floors are not caps: a cap is a declaration the environment must
        *carry*, a floor is one the policy refuses to see declared *wider* — a
        variable configured by not being set.  Writing the floor into ``caps``
        would demand every dispatch export it, which is a different and wrong
        law, so the document's shape is pinned as well as its contents."""
        with COMMITTED_PINNING_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert tuple(document["pool_floors"]) == (POOL_FLOOR_VARIABLE,)
        assert POOL_FLOOR_VARIABLE not in {
            block["name"] for block in document["caps"]
        }

    def test_the_artifact_names_the_layer_each_cap_governs(self) -> None:
        """Every cap carries ``layer`` — the library whose reduction is left
        threaded — because that word is what a refusal names to an operator.
        §12's row says *why* the pin is there ('Multi-threaded BLAS reductions
        are non-deterministic in float'), and a document that dropped the layer
        would leave the law able to say *what* to set but not *what it costs*."""
        with COMMITTED_PINNING_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        layers = {block["name"]: block["layer"] for block in document["caps"]}
        assert layers == {OMP: OMP_LAYER, MKL: MKL_LAYER}


class TestTheCommittedPin:
    """What the compiled artifact holds, and §12's stake in it."""

    def test_the_committed_pin_compiles_from_disk(self) -> None:
        """The loader's whole job, proven: read the committed file, refuse
        nothing about it, hand back a policy."""
        assert committed_thread_pinning_policy().kind == PINNING_POLICY_KIND

    def test_the_committed_pin_holds_section_twelves_two_names(self) -> None:
        """§12's row joins the two variables with *and* — neither layer is
        bound by the other's variable — so a committed policy carrying one would
        certify exactly the threaded deployment the feature refuses."""
        policy = committed_thread_pinning_policy()
        assert set(policy.required_names()) == {ENV_OMP, ENV_MKL}

    def test_every_committed_cap_is_at_the_pin(self) -> None:
        """The artifact's whole claim, read off the compiled object rather than
        the file: no layer of this deployment is left to the machine's core
        count."""
        policy = committed_thread_pinning_policy()
        assert policy.caps()
        for cap in policy.caps():
            assert cap.value == SINGLE_THREADED, cap

    def test_the_compiled_caps_carry_the_policys_own_spelling(self) -> None:
        """A caller asking *what is this pinned to?* reads the pin, and asking
        *which library does this govern?* reads the layer — compiled through the
        same classifier the gate reads an environment with, never off whatever a
        document happened to capitalize."""
        policy = committed_thread_pinning_policy()
        assert policy.value(ENV_OMP) == SINGLE_THREADED
        assert policy.layer(ENV_MKL) == MKL_LAYER

    def test_the_loader_and_the_committed_shortcut_agree(self) -> None:
        """``committed_thread_pinning_policy`` is not privileged: it goes
        through the same read-and-compile as any other path, so a drift in the
        file is refused on both."""
        assert load_thread_pinning_policy(COMMITTED_PINNING_POLICY).pins() == (
            committed_thread_pinning_policy().pins()
        )

    def test_the_committed_artifact_satisfies_the_gate(self) -> None:
        """End to end, and the reason the file exists: the environment §5.2's
        call site builds, checked against the pin the deployment actually ships,
        is admitted.  A drift that made the two disagree would be caught here
        rather than at the first dispatch."""
        from _documents import thread_pinned_env
        from sandbox import check_thread_pinning

        decision = check_thread_pinning(
            thread_pinned_env(), committed_thread_pinning_policy()
        )
        assert decision.admitted is True


class TestTheArtifactIsRefusedWhole:
    """A drifted document is refused, and the *whole* of it is.

    Every test below compiles through :func:`load_thread_pinning_policy` from a
    file written to ``tmp_path`` — the path an operator's edit actually takes —
    rather than by calling the compiler directly, so the disk seam is exercised
    as well as the law.  The property under test throughout is that a refusal
    never half-applies: a policy that dropped the offending block and compiled
    the rest would be a deployment whose file and whose dispatched runs disagree,
    which is the next thread count arriving by another route.
    """

    def _write(self, tmp_path, document) -> object:
        path = tmp_path / "pinning.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_a_cap_declared_wider_than_the_pin_is_refused(self, tmp_path) -> None:
        """The headline drift: someone raises a cap to make the box faster.
        §5.2 says in as many words that this is not a performance setting."""
        document = committed_pinning_document()
        document["caps"][1]["value"] = "4"
        with pytest.raises(ThreadPinningRequired) as raised:
            load_thread_pinning_policy(self._write(tmp_path, document))
        assert str(raised.value).startswith("thread_pinning_required")

    def test_a_cap_declared_zero_is_refused(self, tmp_path) -> None:
        """``0`` is the tempting second drift — a library reads it as *however
        many you want* — and it is a count by the classifier's grammar, so it
        reaches the pin comparison rather than the shape refusal.  Pinned so the
        two paths cannot be confused for each other."""
        document = committed_pinning_document()
        document["caps"][0]["value"] = "0"
        with pytest.raises(ThreadPinningRequired):
            load_thread_pinning_policy(self._write(tmp_path, document))

    def test_a_cap_naming_no_count_is_refused(self, tmp_path) -> None:
        """``"many"`` is not a count a library resolves, so it is refused as a
        declaration rather than compared as one — the same classifier the gate
        reads an environment with, which is the member's one-provenance rule."""
        document = committed_pinning_document()
        document["caps"][0]["value"] = "many"
        with pytest.raises(ThreadPinningRequired):
            load_thread_pinning_policy(self._write(tmp_path, document))

    def test_a_whitespace_spelling_of_the_pin_compiles(self, tmp_path) -> None:
        """``" 1"`` is a value a library reads as one, so the compiler admits it
        and *canonicalizes* it: the compiled cap carries :data:`SINGLE_THREADED`
        rather than whatever whitespace the file happened to surround it with.
        This is the compile-side half of the normalization the decision's
        ``require`` promises, and the reason a document and an environment
        cannot disagree about the pin's spelling."""
        document = committed_pinning_document()
        document["caps"][0]["value"] = " +1"
        policy = load_thread_pinning_policy(self._write(tmp_path, document))
        assert policy.value(ENV_OMP) == SINGLE_THREADED

    def test_a_missing_cap_is_refused(self, tmp_path) -> None:
        """Silence is exactly how a threaded deployment looks configured: a
        policy that said nothing about the MKL layer would pin the OpenMP one
        and certify the rest."""
        document = committed_pinning_document()
        document["caps"] = [document["caps"][0]]
        with pytest.raises(ThreadPinningDocumentError) as raised:
            load_thread_pinning_policy(self._write(tmp_path, document))
        assert "MKL_NUM_THREADS" in str(raised.value)

    def test_the_two_names_earn_different_refusals(self, tmp_path) -> None:
        """Each half of §12's row is refused *by name*, so an operator is told
        which layer is unbound rather than that the document is wrong."""
        # ``caps[0]`` is OMP and ``caps[1]`` is MKL — the document's own order —
        # so dropping index *i* must name the variable that was *there*, not the
        # one that survived: the refusal names what the policy is silent about.
        for dropped, named in ((0, "OMP_NUM_THREADS"), (1, "MKL_NUM_THREADS")):
            document = committed_pinning_document()
            del document["caps"][dropped]
            with pytest.raises(ThreadPinningDocumentError) as raised:
                load_thread_pinning_policy(self._write(tmp_path, document))
            assert named in str(raised.value), named

    def test_a_duplicate_cap_is_refused(self, tmp_path) -> None:
        """Two blocks with one name is one knob described twice, and the
        applied policy would be whichever came last — drift with extra steps."""
        document = committed_pinning_document()
        document["caps"].append(dict(document["caps"][0]))
        with pytest.raises(ThreadPinningDocumentError) as raised:
            load_thread_pinning_policy(self._write(tmp_path, document))
        assert "twice" in str(raised.value)

    def test_a_foreign_marker_is_refused(self, tmp_path) -> None:
        """The document must say what it is.  A stray JSON file with a ``caps``
        key — an unrelated deployment's config — is not this policy."""
        document = committed_pinning_document()
        document["policy"] = "some-other-policy"
        with pytest.raises(ThreadPinningDocumentError) as raised:
            load_thread_pinning_policy(self._write(tmp_path, document))
        assert PINNING_POLICY_KIND in str(raised.value)

    def test_caps_that_are_not_a_list_are_refused(self, tmp_path) -> None:
        """A mapping of name to value reads naturally to a human and is not this
        document's grammar; a compiler that guessed at the meaning would be
        writing policy rather than reading it."""
        document = committed_pinning_document()
        document["caps"] = {OMP: PIN}
        with pytest.raises(ThreadPinningDocumentError):
            load_thread_pinning_policy(self._write(tmp_path, document))

    def test_a_cap_without_a_layer_is_refused(self, tmp_path) -> None:
        """The layer is what the refusal names, so a cap that dropped it would
        leave the law able to say *what* to set but not what is being left
        threaded — and the message is the operator's only interface."""
        document = committed_pinning_document()
        del document["caps"][0]["layer"]
        with pytest.raises(ThreadPinningDocumentError):
            load_thread_pinning_policy(self._write(tmp_path, document))

    def test_a_cap_without_a_name_is_refused(self, tmp_path) -> None:
        """An unnamed variable holds nothing to a value, and 'unnamed' is not
        'pinned' — refused rather than skipped."""
        document = committed_pinning_document()
        document["caps"][0]["name"] = "  "
        with pytest.raises(ThreadPinningDocumentError):
            load_thread_pinning_policy(self._write(tmp_path, document))

    def test_an_absent_value_is_refused_rather_than_read_as_the_pin(self, tmp_path) -> None:
        """The one inference the compiler must not make: reading a missing
        ``value`` as the pin would be turning silence into the strongest promise
        the document makes."""
        document = committed_pinning_document()
        del document["caps"][0]["value"]
        with pytest.raises(ThreadPinningDocumentError) as raised:
            load_thread_pinning_policy(self._write(tmp_path, document))
        assert "absent" in str(raised.value)

    def test_a_floor_that_is_also_a_cap_is_refused(self, tmp_path) -> None:
        """One variable, one meaning: a cap must be *carried* at the pin, a
        floor must not be declared *wider*.  A document making one variable both
        would leave a reader unable to say which refusal an environment earns."""
        document = committed_pinning_document()
        document["pool_floors"] = [POOL_FLOOR_VARIABLE, ENV_OMP]
        with pytest.raises(ThreadPinningDocumentError) as raised:
            load_thread_pinning_policy(self._write(tmp_path, document))
        assert "also declared as a cap" in str(raised.value)

    def test_a_duplicate_floor_is_refused(self, tmp_path) -> None:
        """One name is one knob, and a list that names it twice is a file whose
        intent is not readable from it."""
        document = committed_pinning_document()
        document["pool_floors"] = [POOL_FLOOR_VARIABLE, POOL_FLOOR_VARIABLE]
        with pytest.raises(ThreadPinningDocumentError) as raised:
            load_thread_pinning_policy(self._write(tmp_path, document))
        assert "twice" in str(raised.value)

    def test_a_floor_that_is_not_a_string_is_refused(self, tmp_path) -> None:
        """The floors are variable *names*; a number here is a document whose
        author meant something else, refused rather than coerced."""
        document = committed_pinning_document()
        document["pool_floors"] = [4]
        with pytest.raises(ThreadPinningDocumentError):
            load_thread_pinning_policy(self._write(tmp_path, document))

    def test_a_document_that_is_not_a_mapping_is_refused(self, tmp_path) -> None:
        """A list or a string at the top level is a different document that
        happens to be JSON, and a compiler that guessed would be writing it."""
        path = tmp_path / "pinning.json"
        path.write_text(json.dumps([OMP, MKL]), encoding="utf-8")
        with pytest.raises(ThreadPinningDocumentError):
            load_thread_pinning_policy(path)

    def test_an_unreadable_file_is_refused(self, tmp_path) -> None:
        """A policy that cannot be read is not one that refuses nothing
        gracefully — it is one whose deployment has no law at all, so the caller
        is stopped rather than handed an empty policy."""
        with pytest.raises(ThreadPinningDocumentError) as raised:
            load_thread_pinning_policy(tmp_path / "not-there.json")
        assert "could not read" in str(raised.value)

    def test_a_file_of_invalid_json_is_refused(self, tmp_path) -> None:
        """A truncated or hand-edited file reaches the same refusal as a
        well-formed drift: nothing is compiled from a document that cannot be
        parsed."""
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ThreadPinningDocumentError) as raised:
            load_thread_pinning_policy(path)
        assert "JSON" in str(raised.value)

    def test_a_drifted_document_does_not_half_apply(self, tmp_path) -> None:
        """The property the whole class exists for, stated once as behaviour: a
        document with one bad cap and one good one yields *no* policy — not a
        policy carrying the good cap.  A half-applied law is a deployment whose
        file and whose dispatched runs disagree."""
        document = pinning_document(
            caps=[
                {"name": OMP, "value": PIN, "layer": OMP_LAYER},
                {"name": MKL, "value": "8", "layer": MKL_LAYER},
            ]
        )
        with pytest.raises(ThreadPinningRequired):
            load_thread_pinning_policy(self._write(tmp_path, document))


class TestTheCompilerIsNotWiderThanTheFile:
    """The committed artifact and the builder's shortcut read one document.

    A suite that only ever compiled *hand-built* documents could pass while the
    committed file drifted somewhere the shape tests above do not look — an
    extra key, a reordered list, a marker that still matches.  These tests hold
    the two readers to each other over the file itself.
    """

    def test_the_committed_file_and_its_reconstruction_compile_alike(self) -> None:
        """``committed_pinning_document`` is shaped after the file rather than
        read from it, so comparing the two compiled objects is a real check: it
        fails if the file gains a cap, loses a floor or changes a layer."""
        from_file = committed_thread_pinning_policy()
        rebuilt = compile_thread_pinning_policy(committed_pinning_document())
        assert rebuilt.pins() == from_file.pins()
        assert rebuilt.pool_floors() == from_file.pool_floors()
        assert tuple(cap.layer for cap in rebuilt.caps()) == tuple(
            cap.layer for cap in from_file.caps()
        )
