"""Feature 160's compile: what may become a ceiling, and what is refused.

The compiler is the trusted-code half of *"System applies a seccomp syscall
allowlist"*: an operator or a CI check writes the document, and a document that
is not a denying ceiling is refused **whole** rather than partly applied.  This
suite is the exhaustive half of that contract — every refusal the law promises,
one test per promise, each asserting the *code* and the *repair* rather than
merely that something raised.

The refusals fall into four families, and the split is the one the law's own
docstring makes:

* **the marker** — a document that does not say what it is is not this policy,
  and a stray JSON file carrying an ``allow`` key must not be read as one;
* **the default action** — the widening drift, which is what this law exists
  for.  ``allow`` is the spelling a launcher's default takes, and ``log``,
  ``trace`` and ``notify`` are the three that *look* like controls while
  observing a syscall and letting it through; a spelling this law has never
  heard of leaves the whole posture undecided and is refused rather than
  assumed to deny;
* **the terms** — a term that is not a lower_snake_case syscall name (a padded
  spelling, an upper-case one, a dotted module term from another law's ceiling,
  a leading underscore, an empty string, a non-string) and a term listed twice;
* **the termination** — a ceiling with no way for the process to end.  This is
  deliberately the *opposite* reading from feature 167's empty allowlist, and
  the test that says so is here rather than in that law's suite.

The compiler returns a value rather than raising on the *good* path, and the
last class pins what that value is: a validated ceiling whose default action and
terms a caller can cite without re-checking, and which reads no further than the
three keys this law names.
"""

from __future__ import annotations

import pytest
from _documents import (
    ADMITTED_SYSCALL,
    ALLOW_ACTION,
    DOTTED_TERM,
    EMPTY_TERM,
    INVENTED_SYSCALL,
    KILL_ACTION,
    LEADING_UNDERSCORE_TERM,
    PADDED_TERM,
    UNKNOWN_ACTION,
    UPPERCASE_TERM,
    syscalls_document,
)
from sandbox.syscalls import (
    ALLOWING_ACTIONS,
    DENYING_ACTIONS,
    SYSCALLS_COMPONENT_NAME,
    SYSCALLS_POLICY_KIND,
    TERMINATION_SYSCALLS,
    compile_syscalls_policy,
)

#: The name of the class a document refusal raises.  Compared as a *string*
#: rather than with ``pytest.raises(SyscallsDocumentError)`` because the
#: loader's synthetic module copy means a composed component's exception is
#: structurally but not identically the canonically-imported one — the same
#: discipline the sibling suites apply to their own refusals.
_DOCUMENT_ERROR = "SyscallsDocumentError"


def _refuse(document: object) -> str:
    with pytest.raises(Exception) as raised:
        compile_syscalls_policy(document)
    return f"{type(raised.value).__name__}: {raised.value}"


def _assert_document_error(message: str) -> None:
    assert message.startswith(_DOCUMENT_ERROR), message


class TestTheMarker:
    """A document must declare itself this law's configuration."""

    def test_a_missing_marker_is_refused(self) -> None:
        message = _refuse({"default_action": KILL_ACTION, "allow": ["exit"]})
        _assert_document_error(message)

    def test_another_laws_marker_is_refused(self) -> None:
        # The near-miss that matters: this member ships five other JSON
        # artifacts, and one of *them* dropped into this seat would be a
        # deployment reading a cgroup budget as a syscall ceiling.
        for marker in (
            "sandbox-cgroup-limits",
            "sandbox-imports",
            "sandbox-timeout",
            "sandbox-isolation",
            "sandbox-thread-pinning",
        ):
            message = _refuse(
                {
                    "policy": marker,
                    "default_action": KILL_ACTION,
                    "allow": ["exit"],
                }
            )
            _assert_document_error(message)
            assert marker in message, marker

    def test_a_blank_marker_is_refused(self) -> None:
        _assert_document_error(
            _refuse({"policy": "", "default_action": KILL_ACTION, "allow": ["exit"]})
        )

    def test_a_non_string_marker_is_refused(self) -> None:
        _assert_document_error(
            _refuse({"policy": 160, "default_action": KILL_ACTION, "allow": ["exit"]})
        )

    def test_the_committed_marker_is_the_laws_own_spelling(self) -> None:
        assert SYSCALLS_POLICY_KIND == "sandbox-syscalls"
        assert (
            compile_syscalls_policy(
                {
                    "policy": "sandbox-syscalls",
                    "default_action": KILL_ACTION,
                    "allow": ["exit"],
                }
            ).kind
            == SYSCALLS_POLICY_KIND
        )


class TestTheDefaultAction:
    """The widening drift — the refusal this whole law exists for."""

    @pytest.mark.parametrize("action", ALLOWING_ACTIONS)
    def test_a_non_denying_action_is_refused(self, action: str) -> None:
        # Each of the four by name, because each is a different near-miss:
        # ``allow`` is the launcher's default, and ``log``/``trace``/``notify``
        # are the three that observe a syscall and let it through.  A filter
        # whose default is any of them is not a narrower box but no box.
        message = _refuse(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": action,
                "allow": ["exit"],
            }
        )
        _assert_document_error(message)
        assert action in message
        assert "deny" in message or "denying" in message

    def test_the_error_names_what_a_non_denying_default_would_mean(self) -> None:
        # The refusal is read by an operator at a CI failure, so it has to say
        # *why* the document is refused rather than only that it is: a box
        # running under it would be an ordinary container that believes it is
        # sandboxed.
        message = _refuse(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": ALLOW_ACTION,
                "allow": ["exit"],
            }
        )
        assert "seccomp" in message
        assert "sandboxed" in message or "sandbox" in message

    def test_an_unknown_action_is_refused_rather_than_assumed(self) -> None:
        # Not one of the four non-denying spellings and not a denying one
        # either: a compiler that read it as denying would be inventing a
        # kernel behaviour from a string, and the deployment's entire posture
        # would rest on that guess.
        message = _refuse(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": UNKNOWN_ACTION,
                "allow": ["exit"],
            }
        )
        _assert_document_error(message)
        assert UNKNOWN_ACTION in message
        assert "kill" in message and "errno" in message

    def test_a_missing_action_is_refused(self) -> None:
        message = _refuse({"policy": SYSCALLS_POLICY_KIND, "allow": ["exit"]})
        _assert_document_error(message)
        assert "default_action" in message

    def test_a_blank_action_is_refused(self) -> None:
        message = _refuse(
            {"policy": SYSCALLS_POLICY_KIND, "default_action": "  ", "allow": ["exit"]}
        )
        _assert_document_error(message)

    def test_a_non_string_action_is_refused(self) -> None:
        message = _refuse(
            {"policy": SYSCALLS_POLICY_KIND, "default_action": 9, "allow": ["exit"]}
        )
        _assert_document_error(message)

    def test_an_action_is_compared_case_insensitively_and_normalised(self) -> None:
        # ``KILL`` is the same kernel action as ``kill``, and a policy that
        # carried the raw spelling would put a string in a violation record that
        # no comparison against :data:`KILL_ACTION` would match — so the
        # compiled policy carries the canonical spelling.
        policy = compile_syscalls_policy(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": "  KILL  ",
                "allow": ["exit"],
            }
        )
        assert policy.default_action == KILL_ACTION

    @pytest.mark.parametrize("action", sorted(DENYING_ACTIONS))
    def test_both_denying_spellings_compile(self, action: str) -> None:
        # Two legal ceilings rather than one, and they are genuinely different
        # facts about a box: ``kill`` terminates on SIGSYS, ``errno`` fails the
        # offending call and lets the process continue.  A compiler admitting
        # only one would be a law about taste rather than about whether the
        # ceiling denies.
        policy = compile_syscalls_policy(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": action,
                "allow": ["exit"],
            }
        )
        assert policy.default_action == action

    def test_the_denying_set_and_the_allowing_tuple_are_disjoint(self) -> None:
        # If a spelling appeared in both, the compiler's two checks would
        # disagree about it — one refusing, one admitting — and the earlier
        # branch would win silently.  Pinned so the pair cannot drift.
        assert not DENYING_ACTIONS.intersection(ALLOWING_ACTIONS)
        assert len(ALLOWING_ACTIONS) == len(set(ALLOWING_ACTIONS))


class TestTheTerms:
    """What may be listed as a syscall the box admits."""

    @pytest.mark.parametrize(
        "term",
        [
            UPPERCASE_TERM,
            DOTTED_TERM,
            PADDED_TERM,
            LEADING_UNDERSCORE_TERM,
            EMPTY_TERM,
            "read v2",
            "read;write",
            "read-write",
            "1read",
            "read2x3_",
        ],
    )
    def test_a_malformed_term_is_refused(self, term: str) -> None:
        # Each names no syscall a kernel can be asked about, and a ceiling
        # compiled with one would be a ceiling with a hole no attempt could
        # match — the term would look like a control and admit nothing, which
        # is the quiet failure this grammar exists to prevent.
        message = _refuse(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": KILL_ACTION,
                "allow": [term, "exit"],
            }
        )
        _assert_document_error(message)
        assert "lower_snake_case" in message

    def test_a_non_string_term_is_refused(self) -> None:
        _assert_document_error(
            _refuse(
                {
                    "policy": SYSCALLS_POLICY_KIND,
                    "default_action": KILL_ACTION,
                    "allow": [60, "exit"],
                }
            )
        )

    def test_a_none_term_is_refused(self) -> None:
        _assert_document_error(
            _refuse(
                {
                    "policy": SYSCALLS_POLICY_KIND,
                    "default_action": KILL_ACTION,
                    "allow": [None, "exit"],
                }
            )
        )

    def test_the_refusal_names_the_position(self) -> None:
        # An operator fixing a forty-term list needs to know *which* term is
        # wrong, and a message that said only "a term is malformed" would send
        # them reading the file by eye.
        message = _refuse(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": KILL_ACTION,
                "allow": ["read", "write", UPPERCASE_TERM, "exit"],
            }
        )
        assert "#3" in message

    def test_a_duplicate_term_is_refused(self) -> None:
        # One syscall listed twice is not a wider ceiling, it is one term
        # described twice — and the applied policy would be whichever spelling
        # came last, which is drift with extra steps.
        message = _refuse(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": KILL_ACTION,
                "allow": ["read", "write", "read", "exit"],
            }
        )
        _assert_document_error(message)
        assert "read" in message
        assert "twice" in message

    def test_the_allow_key_must_be_a_list(self) -> None:
        # A string is the near-miss: it is iterable, so a compiler that merely
        # looped over it would admit the letters ``r``, ``e``, ``a``, ``d`` as
        # four syscalls and refuse nothing.
        message = _refuse(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": KILL_ACTION,
                "allow": "read,write,exit",
            }
        )
        _assert_document_error(message)
        assert "list" in message

    def test_a_missing_allow_key_is_refused(self) -> None:
        _assert_document_error(
            _refuse({"policy": SYSCALLS_POLICY_KIND, "default_action": KILL_ACTION})
        )

    def test_a_well_formed_term_that_names_no_real_syscall_compiles(self) -> None:
        # The grammar and the membership are *different checks*, and this is the
        # test that says so: ``zzz_not_a_syscall`` is a legal term — no spec
        # pins a kernel's syscall table, and this law reads names rather than
        # numbers — and it is still admitted only for a process that names it.
        # A compiler that tried to validate terms against a syscall table would
        # be a second, disagreeing copy of the kernel's.
        policy = compile_syscalls_policy(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": KILL_ACTION,
                "allow": [INVENTED_SYSCALL, "exit"],
            }
        )
        assert policy.admits(INVENTED_SYSCALL) is True

    def test_the_terms_keep_their_document_order(self) -> None:
        # Order is what a reviewer reads and what a round-tripped filter is
        # compared field by field against, so it is preserved rather than
        # sorted or set-ified.
        policy = compile_syscalls_policy(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": KILL_ACTION,
                "allow": ["write", "read", "exit", "exit_group"],
            }
        )
        assert policy.allowed() == ("write", "read", "exit", "exit_group")

    def test_a_single_well_formed_termination_is_enough(self) -> None:
        # Either spelling, alone: the kernel registers both and a signal's
        # interpreter calls whichever its libc chose, so requiring one specific
        # name would refuse a legal deployment.
        for term in sorted(TERMINATION_SYSCALLS):
            policy = compile_syscalls_policy(
                {
                    "policy": SYSCALLS_POLICY_KIND,
                    "default_action": KILL_ACTION,
                    "allow": [ADMITTED_SYSCALL, term],
                }
            )
            assert policy.admits(term) is True


class TestTheTermination:
    """A ceiling that admits nothing that ends the process is not a control."""

    def test_an_empty_ceiling_is_refused(self) -> None:
        message = _refuse(
            {"policy": SYSCALLS_POLICY_KIND, "default_action": KILL_ACTION, "allow": []}
        )
        _assert_document_error(message)
        assert "end" in message

    def test_a_ceiling_without_either_exit_is_refused(self) -> None:
        message = _refuse(
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": KILL_ACTION,
                "allow": ["read", "write", "mmap"],
            }
        )
        _assert_document_error(message)
        assert "exit" in message

    def test_the_reason_is_the_opposite_reading_from_feature_167s(self) -> None:
        # The law's own argument, pinned as a message rather than left to a
        # comment: a *static* import screen that admits nothing still refuses a
        # module before it runs and returns that refusal as a value, so feature
        # 167 treats its empty ceiling as legal.  A syscall filter over an empty
        # set terminates the box at its first instruction, so there is no run to
        # refuse and nobody left to record it.
        message = _refuse(
            {"policy": SYSCALLS_POLICY_KIND, "default_action": KILL_ACTION, "allow": []}
        )
        assert "167" in message

    def test_the_handoff_to_the_violation_class_is_written_down(self) -> None:
        # §15's recovery column rests on the box being killable: the process
        # dies, the kernel's SIGSYS is what makes feature 161's quarantine the
        # right recovery, and a filter that could not end the process would
        # leave the node in a state no law in this member describes.
        message = _refuse(
            {"policy": SYSCALLS_POLICY_KIND, "default_action": KILL_ACTION, "allow": []}
        )
        assert "instruction" in message


class TestTheCompiledCeiling:
    """What the compiler hands back once it has accepted a document."""

    def test_it_returns_a_policy_rather_than_the_document(self) -> None:
        policy = compile_syscalls_policy(syscalls_document())
        assert type(policy).__name__ == "SyscallPolicy"
        assert not isinstance(policy, dict)

    def test_it_is_not_wider_than_the_document(self) -> None:
        policy = compile_syscalls_policy(syscalls_document())
        assert policy.allowed() == ("read", "write", "exit", "exit_group")
        assert policy.kind == SYSCALLS_POLICY_KIND
        assert policy.default_action == KILL_ACTION

    def test_the_membership_probe_reads_only_the_ceiling(self) -> None:
        policy = compile_syscalls_policy(syscalls_document())
        assert policy.admits("read") is True
        assert policy.admits("openat") is False
        assert policy.admits("readv") is False
        assert "read" in policy
        assert "openat" not in policy
        assert len(policy) == 4

    def test_a_non_string_name_is_admitted_by_nothing(self) -> None:
        # The conservative answer, and the one the gate's refusal gives the same
        # subject: a name that is not a string names no syscall.
        policy = compile_syscalls_policy(syscalls_document())
        for name in (None, 60, b"read", ["read"], {"read"}, 1.5, True):
            assert policy.admits(name) is False, name

    def test_a_document_that_is_not_a_mapping_is_refused(self) -> None:
        for document in (None, [], "sandbox-syscalls", 160, b"{}", ("read",), 1.0):
            _assert_document_error(_refuse(document))

    def test_the_policy_is_immutable_in_the_sense_that_matters(self) -> None:
        # ``allowed()`` hands back a tuple and a caller that mutated it would
        # have to work at it: the ceiling a launcher arms and the ceiling an
        # audit reads are one object, so a caller cannot widen its own box.
        policy = compile_syscalls_policy(syscalls_document())
        assert isinstance(policy.allowed(), tuple)
        first = policy.allowed()
        assert policy.allowed() is first

    def test_no_attribute_outside_the_ceiling_can_be_attached(self) -> None:
        # ``__slots__`` is what keeps the object from growing a capability: this
        # law is a fact about configuration, and a policy that could be handed a
        # process, a filter handle or a probe would be a mechanism wearing a
        # config's name — the property :meth:`sandbox.SandboxBudget.__slots__`
        # states one law over.  A *declared* field is still writable, which is
        # why this test pins the slots and the membership rule's *behaviour*
        # rather than pretending the object is frozen:
        # :meth:`sandbox.budget.CgroupPolicy` is not frozen either, and the
        # member's rule is that the value a caller *reads* is a copy
        # (:meth:`SyscallPolicy.allowed` hands back a tuple).
        policy = compile_syscalls_policy(syscalls_document())
        assert policy.admits("openat") is False
        with pytest.raises(AttributeError):
            policy.probe = lambda name: True
        with pytest.raises(AttributeError):
            policy.allowed = lambda: ("openat",)
        assert policy.admits("openat") is False

    def test_the_membership_probe_reads_a_set_built_at_compile_time(self) -> None:
        # The probe is a set lookup per attempt rather than a scan of the
        # ceiling: this is called on a refusal's clock inside a runtime, and one
        # scan at compile time answers every call since.  Pinned as a set so a
        # later edit cannot quietly turn the hot path back into a linear scan.
        policy = compile_syscalls_policy(syscalls_document())
        assert isinstance(policy._allowed_set, frozenset)
        assert policy._allowed_set == frozenset(policy.allowed())

    def test_the_policy_carries_no_slots_beyond_its_ceiling(self) -> None:
        # Pinned so the object cannot grow a capability: this law is a fact
        # about configuration, and a policy with a process, a filter handle or
        # a probe in it would be a mechanism wearing a config's name.
        assert type(compile_syscalls_policy(syscalls_document())).__slots__ == (
            "_allowed",
            "_allowed_set",
            "default_action",
            "kind",
        )

    def test_the_component_name_is_its_own_name(self) -> None:
        # The registry replaces a name's earlier registration, so this could not
        # be ``sandbox`` or any sibling's name without silently overwriting a
        # law whose component composition would then look perfect.
        assert SYSCALLS_COMPONENT_NAME == "sandbox-syscalls"

    def test_the_engine_spelling_is_not_a_mechanism_spelling(self) -> None:
        # ``sandbox-seccomp`` would name the mechanism rather than the law, and
        # this member names its components after their subject.
        assert SYSCALLS_COMPONENT_NAME != "sandbox-seccomp"


class TestTheRefusalsAreTheMembersOwn:
    """The compiler's refusals are this member's vocabulary, not a builtin's."""

    def test_the_refusal_is_not_a_value_error(self) -> None:
        # A document refusal guards a file a deployment wrote, and a caller that
        # caught ``ValueError`` here would be subscribing to every other
        # library's value errors along with it — the reason the member's
        # vocabulary is its own.
        with pytest.raises(Exception) as raised:
            compile_syscalls_policy({"policy": "wrong"})
        assert not isinstance(raised.value, ValueError)
        assert not isinstance(raised.value, KeyError)
        assert not isinstance(raised.value, TypeError)

    def test_the_refusal_derives_from_the_members_base(self) -> None:
        from sandbox.errors import SandboxError, SandboxSyscallError

        with pytest.raises(SandboxSyscallError):
            compile_syscalls_policy({"policy": "wrong"})
        with pytest.raises(SandboxError):
            compile_syscalls_policy({"policy": "wrong"})

    def test_every_message_says_which_feature_refused(self) -> None:
        # Greppable provenance: an operator reading a CI log or a build failure
        # finds the law's own words rather than a bare "invalid document".
        for document in (
            {"policy": "wrong"},
            {"policy": SYSCALLS_POLICY_KIND},
            {"policy": SYSCALLS_POLICY_KIND, "default_action": ALLOW_ACTION},
            {
                "policy": SYSCALLS_POLICY_KIND,
                "default_action": KILL_ACTION,
                "allow": [],
            },
        ):
            assert "feature 160" in _refuse(document)

    def test_a_refusal_does_not_apply_the_document_partly(self) -> None:
        # "Refused whole" stated as behaviour: the compiler never returns a
        # ceiling reduced to the terms that happened to parse, because a caller
        # holding one would be running a box under a policy nobody wrote.  The
        # refusal names the offending term, which is what says the *document* was
        # judged rather than quietly trimmed.
        with pytest.raises(Exception) as raised:
            compile_syscalls_policy(
                {
                    "policy": SYSCALLS_POLICY_KIND,
                    "default_action": KILL_ACTION,
                    "allow": ["read", "write", UPPERCASE_TERM, "exit"],
                }
            )
        assert type(raised.value).__name__ == _DOCUMENT_ERROR
        assert UPPERCASE_TERM in str(raised.value)
