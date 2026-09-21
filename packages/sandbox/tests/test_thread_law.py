"""Feature 164 — the thread-pinning environment, missing is refused.

app_spec.xml feature 164: *"System rejects a sandbox invocation missing the
thread-pinning environment."*  §5.2's call site names the environment in its
``env=`` clause, and §12's determinism table gives the pair its own row.  This
file tests the sentence clause by clause, because an environment that satisfied
two of the three would be a different and worse feature:

* **a sandbox invocation** — the subject is *one dispatch*, described either as
  the environment it will be handed or as an object carrying one, which is how
  the same invocation feature 165 describes can be handed to both laws;
* **the thread-pinning environment** — both caps §12 names, each classified into
  absent, pinned or declared-at-something-else, with the third case refused as
  firmly as the first because a worker exported at ``OMP_NUM_THREADS=16`` is
  threaded too and *looks* configured;
* **rejects** — the refusal, in both its returned and its raised shape, and the
  environment the launcher verb hands back on the way *through*.

Three properties this file pins that a reader might expect elsewhere:

* the *pin* and the *cap names* are asserted as data rather than imported from
  ``canary._threads``: the two members must agree on a wire format, and a suite
  that imported one of them would follow a rename rather than catch it — the
  discipline feature 165's suite applies to ``NULLIUS_SIGNAL_SEED``;
* ``check`` and ``require`` never disagree, over the whole cross-product of
  spellings this file exercises: one implementation, two shapes;
* the law reads **no ambient environment**.  ``check()`` takes its subject as an
  argument, so a test never depends on the shell that started pytest — which is
  why this suite needs no clearing fixture where feature 137's does.
"""

from __future__ import annotations

import pytest
from _documents import (
    BYSTANDER,
    MKL,
    MKL_LAYER,
    OMP,
    OMP_LAYER,
    committed_pinning_document,
    thread_pinned_env,
    unpinned_env,
)
from sandbox import (
    ABSENT,
    ENV_MKL,
    ENV_OMP,
    PINNED,
    PINNING_POLICY_KIND,
    POOL_FLOOR_VARIABLE,
    REQUIRED_CAPS,
    SINGLE_THREADED,
    THREAD_PINNING_CODE,
    UNPINNED,
    SandboxInvocation,
    SandboxThreadPinningError,
    SandboxThreads,
    ThreadCap,
    ThreadDecision,
    ThreadPinningDocumentError,
    ThreadPinningPolicy,
    ThreadPinningRequired,
    ThreadReason,
    check_thread_pinning,
    classify_cap,
    compile_thread_pinning_policy,
    sandbox_threads,
)


@pytest.fixture
def law() -> SandboxThreads:
    """The law over the committed artifact — what a composed application holds."""
    return sandbox_threads()


@pytest.fixture
def policy() -> ThreadPinningPolicy:
    return compile_thread_pinning_policy(committed_pinning_document())


class TestTheCapNames:
    """*the thread-pinning environment* — the spelling, pinned as data."""

    def test_the_two_names_are_the_ones_the_architecture_writes(self) -> None:
        """§5.2's call site and §12's row both write these two, and the worker
        on the far side of the seam (``canary._threads``, feature 137) reads the
        same spellings.  Pinned *as data* rather than imported from the canary:
        the sandbox member owns no dependency on the member that drives it, and
        a change to a name is a change to a wire format that has to be argued
        rather than noticed at dispatch time."""
        assert ENV_OMP == "OMP_NUM_THREADS"
        assert ENV_MKL == "MKL_NUM_THREADS"

    def test_the_pin_is_one(self) -> None:
        """§12 fixes *one value*, so the law has no knob: ``0``, ``2`` and
        ``auto`` are all choices the libraries admit and the row does not."""
        assert SINGLE_THREADED == "1"

    def test_the_required_table_pairs_each_variable_with_its_layer(self) -> None:
        """The feature's sentence joins two variables with *and* because neither
        layer is bound by the other's: ``OMP_NUM_THREADS`` governs the
        OpenMP-parallel kernels, ``MKL_NUM_THREADS`` governs MKL's own threading
        independently and outranks it there.  The layer is carried because a
        refusal has to say *which* reduction was left threaded."""
        assert dict(REQUIRED_CAPS) == {ENV_OMP: OMP_LAYER, ENV_MKL: MKL_LAYER}

    def test_the_refusal_code_is_the_features_own_words(self) -> None:
        """A log-grepping operator finds the rejection by the feature's own
        subject, the discipline feature 157's and 167's codes take."""
        assert THREAD_PINNING_CODE == "thread_pinning_required"

    def test_the_policy_kind_is_this_members_own_marker(self) -> None:
        """A stray JSON file carrying a ``caps`` key is not this policy."""
        assert PINNING_POLICY_KIND == "sandbox-thread-pinning"


class TestTheClassifier:
    """One place a declared count is read — the gate and the compiler agree."""

    @pytest.mark.parametrize(
        "value",
        [
            "1",
            " 1",
            "\t1",
            "+1",
            " +1",
            "01",
            "１",  # a non-ASCII decimal digit, which int() parses to one
            1,
        ],
    )
    def test_the_pin_admits_the_spellings_the_libraries_read(self, value: object) -> None:
        """``strtol``'s shape with Python's integer grammar behind it: leading
        ``strtol`` whitespace, an optional sign, then a run of decimal digits.
        A value one of the readers resolves to one thread *is* the pin — a law
        that refused ``" 1"`` or ``"+1"`` would be more restrictive than the
        libraries it vouches for, and the readers are the thing being vouched
        for."""
        assert classify_cap(value) == PINNED

    @pytest.mark.parametrize(
        "value",
        [
            "2",
            "0",
            "-1",
            "16",
            "1.0",
            "1e0",
            "auto",
            "many",
            "one",
            "1 2",
            "1 ",
            " 1 ",
            "\t1\r",
            "1\n",
            "",
        ],
    )
    def test_a_declaration_that_is_not_the_pin_is_refused(self, value: object) -> None:
        """Every other string is a declaration that was *made* and does not name
        the pin — a wider count (a choice the row does not make), a blank (which
        the library ignores, applying its own default), and a token no parser
        resolves (a manifest that meant to configure the layer and wrote
        something else).  All are :data:`UNPINNED`, and the refusal for each is
        worded apart.

        **Trailing whitespace is deliberately not trimmed.**  ``"1 "`` and
        ``"1\\n"`` are refused while ``" 1"`` is admitted, because the grammar is
        anchored: a library comparing the whole string sees the trailing
        character, and a law more permissive than the readers it vouches for
        would certify an environment one of them reads as unset."""
        assert classify_cap(value) == UNPINNED

    @pytest.mark.parametrize("value", [True, False, 1.0, b"1", ["1"], {"n": 1}, object()])
    def test_a_value_no_library_reads_as_a_count_is_refused(self, value: object) -> None:
        """A near miss by *type*: ``True`` is an ``int`` in Python, an
        environment carries text, and a container is not a count.

        ``False`` matters as much as ``True``: it is an ``int`` equal to zero,
        so a classifier that did not exclude ``bool`` would read it as the
        "let the library choose" declaration §12's row explicitly does not
        make."""
        assert classify_cap(value) == UNPINNED

    def test_an_undeclared_variable_is_its_own_state(self) -> None:
        """``None`` is :data:`ABSENT` — *no declaration was made* — and is kept
        apart from ``""``, which is a declaration that names nothing.  The two
        are different refusals with different repairs, and collapsing them would
        misdescribe the invocation."""
        assert classify_cap(None) == ABSENT
        assert classify_cap("") == UNPINNED
        assert classify_cap("   ") == UNPINNED

    def test_the_classifier_reads_the_pin_from_the_policy_not_a_constant(
        self, policy: ThreadPinningPolicy
    ) -> None:
        """The gate compares against the *compiled* value, so an admission is
        the declaration arriving at its answer — not a hardcoded "yes, pinned"."""
        assert policy.value(ENV_OMP) == SINGLE_THREADED
        assert policy.layer(ENV_MKL) == MKL_LAYER


class TestTheSweep:
    """*rejects* — what the gate answers for one invocation."""

    def test_a_pinned_environment_is_admitted(self, law: SandboxThreads) -> None:
        decision = law.check(thread_pinned_env())
        assert decision.admitted is True
        assert decision.reason == ThreadReason.BY_PINNING
        assert decision.missing == ()
        assert decision.threaded == ()
        assert THREAD_PINNING_CODE not in decision.detail

    def test_a_missing_cap_is_refused_by_name(self, law: SandboxThreads) -> None:
        """The feature's own word: *missing*.  The refusal names the variable
        and the layer it governs, because "the run was unpinned" would leave an
        operator without the one word they can act on."""
        decision = law.check(thread_pinned_env(**{OMP: None}))
        assert decision.admitted is False
        assert decision.reason == ThreadReason.WITHOUT_PINNING
        assert decision.missing == (ENV_OMP,)
        assert decision.detail.startswith(THREAD_PINNING_CODE)
        assert ENV_OMP in decision.detail
        assert OMP_LAYER in decision.detail

    def test_both_caps_missing_is_still_one_refusal(self, law: SandboxThreads) -> None:
        """§12's *and*: an environment that declares neither is refused once,
        naming both, rather than twice with the first one winning — a caller
        that repaired only the variable it was told about would come back."""
        decision = law.check(unpinned_env())
        assert decision.admitted is False
        assert decision.missing == (ENV_OMP, ENV_MKL)
        assert ENV_OMP in decision.detail and ENV_MKL in decision.detail

    def test_an_empty_environment_is_refused(self, law: SandboxThreads) -> None:
        """The degenerate spelling of "missing", and the one a launcher that
        forgot the ``env=`` clause entirely produces."""
        decision = law.check({})
        assert decision.admitted is False
        assert decision.missing == (ENV_OMP, ENV_MKL)

    def test_a_blank_cap_is_refused_as_a_missing_one(self, law: SandboxThreads) -> None:
        """A blank value *looks* configured and names nothing, so the library
        reading it applies its own default — a threaded worker wearing the shape
        of a pinned one, which is the harder of the two failures to notice."""
        decision = law.check(thread_pinned_env(**{OMP: "  "}))
        assert decision.admitted is False
        assert decision.missing == (ENV_OMP,)
        assert "blank" in decision.detail

    def test_a_threaded_cap_is_refused(self, law: SandboxThreads) -> None:
        """The case the feature's word *missing* has to stretch to cover, and
        the reason it does: a worker exported at ``16`` is threaded too, and
        only the absent spelling looks like an accident."""
        decision = law.check(thread_pinned_env(**{MKL: "16"}))
        assert decision.admitted is False
        assert decision.reason == ThreadReason.THREADED_CAP
        assert decision.threaded == (ENV_MKL,)
        assert decision.missing == ()
        assert "16" in decision.detail
        assert MKL_LAYER in decision.detail

    def test_a_cap_that_is_not_the_pin_is_not_a_first_win(self, law: SandboxThreads) -> None:
        """A missing *and* a threaded cap are both reported: two variables are
        two repairs, and a refusal that named one would send the operator away
        satisfied with half the environment fixed."""
        decision = law.check(thread_pinned_env(**{OMP: None, MKL: "8"}))
        assert decision.admitted is False
        assert decision.missing == (ENV_OMP,)
        assert decision.threaded == (ENV_MKL,)
        assert decision.reason == ThreadReason.WITHOUT_PINNING

    def test_a_threaded_pool_floor_is_refused_with_the_caps_pinned(
        self, law: SandboxThreads
    ) -> None:
        """The failure §12's two names do not reach on their own: the floor is
        resolved by the library without consulting the caps, so both can be
        pinned to the letter and the reduction is still partitioned.  Its own
        reason, because the repair is the floor and not a cap."""
        decision = law.check(thread_pinned_env(**{POOL_FLOOR_VARIABLE: "8"}))
        assert decision.admitted is False
        assert decision.reason == ThreadReason.THREADED_POOL
        assert decision.threaded == (POOL_FLOOR_VARIABLE,)
        assert decision.missing == ()

    def test_an_absent_pool_floor_is_not_a_refusal(self, law: SandboxThreads) -> None:
        """The asymmetry, and it is deliberate: nothing here can say what value
        a deployment's own library should default to, so a policy that made the
        floor mandatory would be this member inventing a knob for a library it
        does not own.  Declared-and-wider is refused; undeclared is not."""
        env = thread_pinned_env()
        env.pop(POOL_FLOOR_VARIABLE, None)
        assert law.check(env).admitted is True

    def test_a_floor_at_the_pin_is_not_a_refusal(self, law: SandboxThreads) -> None:
        assert law.check(thread_pinned_env(**{POOL_FLOOR_VARIABLE: "1"})).admitted is True

    def test_the_gate_raises_nothing(self, law: SandboxThreads) -> None:
        """The pipeline offers thousands of these unattended: *"this one is
        unpinned"* has to reach an operator as a fact about a run rather than as
        a crashed evaluator.  Only :meth:`ThreadDecision.require` raises."""
        decision = law.check(unpinned_env())
        assert isinstance(decision, ThreadDecision)
        assert decision.admitted is False

    def test_an_unreadable_subject_is_refused_by_name(self, law: SandboxThreads) -> None:
        """A caller that has been handed the wrong object still needs to be told
        which one it was, and *"what you gave me is not an environment"* is a
        refusal rather than an exception for the same reason the sweep is."""
        for subject in (None, "OMP_NUM_THREADS=1", 7, ["OMP_NUM_THREADS"]):
            decision = law.check(subject)
            assert decision.admitted is False
            assert decision.reason == ThreadReason.UNREADABLE_SUBJECT
            assert type(subject).__name__ in decision.detail

    def test_the_gate_is_a_pure_function_of_the_policy(self) -> None:
        """The gate takes the policy as an argument, so the sweep can be
        exercised against a hand-built declaration — which is what proves the
        admission is *derived* from the compiled value rather than from a
        constant.

        A policy pinning another value refuses the environment that *satisfies*
        §12, and the reason says so: the finding is the policy, not the run, and
        an operator sent looking at the launcher would be reading the wrong
        file.  This is unreachable through a compiled policy — the compiler
        refuses a document pinning anything but :data:`SINGLE_THREADED` — which
        is exactly what makes it worth its own reason rather than being folded
        into *missing*."""
        other = ThreadPinningPolicy(
            kind=PINNING_POLICY_KIND,
            caps=(ThreadCap(name=ENV_OMP, value="2", layer=OMP_LAYER),),
        )
        decision = check_thread_pinning({ENV_OMP: "1"}, other)
        assert decision.admitted is False
        assert decision.reason == ThreadReason.POLICY_MISMATCH
        assert decision.missing == ()
        assert decision.threaded == ()
        assert PINNING_POLICY_KIND in decision.detail

    def test_a_policy_declaring_another_value_still_refuses_the_rest(
        self,
    ) -> None:
        """The mismatch case does not mask a genuine one: a subject that is
        unpinned *and* checked against a hand-assembled policy is refused for
        the unpinned caps, because an operator repairing the run is what that
        refusal is for."""
        other = ThreadPinningPolicy(
            kind=PINNING_POLICY_KIND,
            caps=(ThreadCap(name=ENV_OMP, value="2", layer=OMP_LAYER),),
        )
        decision = check_thread_pinning({}, other)
        assert decision.reason == ThreadReason.WITHOUT_PINNING
        assert decision.missing == (ENV_OMP,)

    def test_the_law_reads_no_ambient_environment(self, law: SandboxThreads, monkeypatch) -> None:
        """The subject is the environment an invocation *carries*, never
        ``os.environ``: a caller that wants to ask about its own process passes
        it.  So a developer shell carrying the caps cannot change a verdict here,
        which is why this suite needs no clearing fixture."""
        monkeypatch.setenv(OMP, "16")
        monkeypatch.setenv(MKL, "16")
        assert law.check(unpinned_env()).admitted is False
        assert law.check(thread_pinned_env()).admitted is True


class TestTheLauncherVerb:
    """``require`` — one call, the environment to dispatch with or the refusal."""

    def test_require_returns_the_environment_to_dispatch_with(
        self, law: SandboxThreads
    ) -> None:
        """The verb *returns* on success rather than ``None``: a caller that got
        nothing back would read the environment off the invocation a second
        time, and the two readings are exactly the pair that can drift."""
        env = law.require(thread_pinned_env())
        assert env[ENV_OMP] == SINGLE_THREADED
        assert env[ENV_MKL] == SINGLE_THREADED

    def test_require_carries_the_subjects_other_variables_through(
        self, law: SandboxThreads
    ) -> None:
        """This law's table is §12's two names plus one floor: everything else
        the launcher put in the environment — the hash seed, the image digest, a
        deployment's own setting — is the *subject's*, and a verb that dropped it
        would be a launcher winning a fight with the caller."""
        env = law.require(thread_pinned_env())
        assert env[BYSTANDER] == "0"

    def test_require_returns_a_copy_and_never_mutates_the_subject(
        self, law: SandboxThreads
    ) -> None:
        """Two callers dispatching from one decision must not fight over the
        environment they pass — the copy-then-write discipline feature 165's
        ``seed_env`` and ``evaluator._sandbox._child_env`` both apply."""
        base = thread_pinned_env()
        first = law.require(base)
        second = law.require(base)
        assert first is not second
        first["MUTATED"] = "yes"
        assert "MUTATED" not in second
        assert "MUTATED" not in base

    def test_require_writes_the_policys_spelling(self, law: SandboxThreads) -> None:
        """A declaration admitted because it *classified* as the pin — ``" 1"``
        and ``"+1"`` are values a library reads as a count of one — reaches the
        child in the policy's spelling.  This is a normalization and not a
        repair: no value is changed, but a box that compared the raw string
        sees the canonical one."""
        env = law.require(thread_pinned_env(**{MKL: " +1"}))
        assert env[ENV_MKL] == SINGLE_THREADED

    def test_require_raises_the_refusal(self, law: SandboxThreads) -> None:
        with pytest.raises(ThreadPinningRequired) as raised:
            law.require(unpinned_env())
        assert str(raised.value).startswith(THREAD_PINNING_CODE)

    def test_the_refusal_family_is_this_members_own(self) -> None:
        """A caller catching ``SandboxError`` gets this law's refusals beside
        the other four's, rather than a family of its own to discover."""
        import sandbox

        assert issubclass(ThreadPinningRequired, SandboxThreadPinningError)
        assert issubclass(ThreadPinningDocumentError, SandboxThreadPinningError)
        assert issubclass(SandboxThreadPinningError, sandbox.SandboxError)
        assert issubclass(sandbox.SandboxError, Exception)

    def test_the_two_shapes_never_disagree(self, law: SandboxThreads) -> None:
        """The whole cross-product of spellings this file exercises, checked
        both ways: one implementation, two shapes, and a caller never chooses
        which *law* it applies — only which shape it wants the answer in."""
        subjects: list[object] = [
            unpinned_env(),
            thread_pinned_env(),
            thread_pinned_env(**{OMP: None}),
            thread_pinned_env(**{MKL: "16"}),
            thread_pinned_env(**{POOL_FLOOR_VARIABLE: "4"}),
            thread_pinned_env(**{MKL: ""}),
            thread_pinned_env(**{OMP: True}),
            {},
            None,
        ]
        for subject in subjects:
            decision = law.check(subject)
            if decision.admitted:
                assert law.require(subject)[ENV_OMP] == SINGLE_THREADED
                continue
            with pytest.raises(ThreadPinningRequired) as raised:
                law.require(subject)
            assert str(raised.value) == decision.detail


class TestTheInvocation:
    """*a sandbox invocation* — the subject's shapes, and the shared envelope."""

    def test_an_invocation_carrying_an_env_is_a_readable_subject(
        self, law: SandboxThreads
    ) -> None:
        """The seam that makes this law composable with feature 165's: §5.2's
        call site is *one* description of a run, so a launcher hands the same
        ``SandboxInvocation`` to the seed law and to this one rather than
        describing the run twice — which is how the two descriptions drift."""
        invocation = SandboxInvocation(node_id="n", seed=7, env=thread_pinned_env())
        assert law.check(invocation).admitted is True
        assert law.require(invocation)[ENV_MKL] == SINGLE_THREADED

    def test_an_invocation_with_no_env_is_refused(self, law: SandboxThreads) -> None:
        """An invocation whose environment declares nothing is exactly the
        feature's subject — not an unreadable object, since the envelope's env
        is a mapping (empty) rather than absent."""
        invocation = SandboxInvocation(node_id="n", seed=7)
        decision = law.check(invocation)
        assert decision.admitted is False
        assert decision.reason == ThreadReason.WITHOUT_PINNING
        assert decision.missing == (ENV_OMP, ENV_MKL)

    def test_a_plain_mapping_is_a_readable_subject(self, law: SandboxThreads) -> None:
        """A launcher that built its environment before describing the run hands
        the mapping directly — there is no envelope to wrap it in, and requiring
        one would make this law demand a shape it does not need."""
        assert law.check(dict(thread_pinned_env())).admitted is True

    def test_a_foreign_objects_none_env_is_an_unreadable_subject(
        self, law: SandboxThreads
    ) -> None:
        """A record type of the caller's own may carry ``env`` as ``None``, and
        that is an absent *environment* rather than a crash inside the gate: the
        law refuses it by name, the same as any other object it cannot read."""

        class Row:
            env = None

        decision = law.check(Row())
        assert decision.admitted is False
        assert decision.reason == ThreadReason.UNREADABLE_SUBJECT


class TestThePolicy:
    """The compiled declaration — the read side a deployment audits with."""

    def test_the_policy_reports_what_it_requires(self, policy: ThreadPinningPolicy) -> None:
        assert policy.required_names() == (ENV_OMP, ENV_MKL)
        assert policy.kind == PINNING_POLICY_KIND
        assert policy.pool_floors() == (POOL_FLOOR_VARIABLE,)

    def test_pins_is_a_fresh_environment_shaped_mapping(
        self, policy: ThreadPinningPolicy
    ) -> None:
        """``pins()`` hands out the declaration as a mapping a launcher can use
        *instead of* the environment it built — and a fresh one per call, so a
        caller cannot mutate the policy by writing to what it read."""
        pins = policy.pins()
        assert pins == {ENV_OMP: SINGLE_THREADED, ENV_MKL: SINGLE_THREADED}
        pins["MUTATED"] = "yes"
        assert "MUTATED" not in policy.pins()

    def test_an_unlisted_name_is_none_rather_than_a_default(
        self, policy: ThreadPinningPolicy
    ) -> None:
        """The lookup decides nothing: a name outside §12's row has no declared
        value, and "unknown" is not "pinned" — the same stance
        ``IsolationPolicy.isolation_of`` takes for an unlisted component."""
        assert policy.value("PYTHONHASHSEED") is None
        assert policy.layer("PYTHONHASHSEED") is None
        assert policy.cap("PYTHONHASHSEED") is None

    def test_the_component_delegates_to_the_same_law(self) -> None:
        """Every verb the component offers is one call into the module, so a
        second implementation of the classifier or the sweep cannot drift into
        existence — the member's one-provenance rule."""
        law = sandbox_threads()
        assert law.policy.kind == PINNING_POLICY_KIND
        assert law.required() == (ENV_OMP, ENV_MKL)
        assert law.value(ENV_OMP) == SINGLE_THREADED
        assert law.pool_floors() == (POOL_FLOOR_VARIABLE,)
        assert law.admits(thread_pinned_env()) is True
        assert law.admits(unpinned_env()) is False
        assert law.pins() == {ENV_OMP: SINGLE_THREADED, ENV_MKL: SINGLE_THREADED}

    def test_the_law_carries_no_environment_of_its_own(self) -> None:
        """A component shared across runs that held an *environment* would let
        two invocations share a description, and the concrete failure is a run
        dispatched under another run's environment — the property features 166's
        and 165's components state for their channel and their seed, sharper
        here.  So the composed value holds the compiled policy and nothing
        else."""
        assert SandboxThreads.__slots__ == ("_policy",)

    def test_the_law_is_reachable_without_the_component(self) -> None:
        """Every name the module's ``__all__`` promises is really there — the
        member's own ``__init__`` imports the law, and a name listed but not
        bound fails only for the caller who reaches for it."""
        import sandbox

        for name in (
            "SandboxThreads",
            "ThreadDecision",
            "ThreadReason",
            "ThreadPinningPolicy",
            "ThreadCap",
            "check_thread_pinning",
            "classify_cap",
            "compile_thread_pinning_policy",
            "committed_thread_pinning_policy",
            "load_thread_pinning_policy",
            "sandbox_threads",
            "COMMITTED_PINNING_POLICY",
            "PINNING_POLICY_KIND",
            "POOL_FLOOR_VARIABLE",
            "REQUIRED_CAPS",
            "SINGLE_THREADED",
            "THREADS_COMPONENT_NAME",
            "THREAD_PINNING_CODE",
            "ENV_OMP",
            "ENV_MKL",
            "SandboxThreadPinningError",
            "ThreadPinningRequired",
            "ThreadPinningDocumentError",
        ):
            assert name in sandbox.__all__, name
            assert hasattr(sandbox, name), name
