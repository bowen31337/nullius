"""Feature 168's law: every sandboxed run gets one of §9.1's four fail classes.

app_spec.xml, "Untrusted Code Sandbox", feature 168 — the category's last — is
one sentence with three claims in it:

    System returns a structured fail class of ok, timeout, error or
    tripwire_fail from every sandboxed run.

**"returns" is the first claim, and it is a stance rather than a detail.**  A
fail class is a *value*, never a raise: §5.2's control table records its kill as
an outcome ("Timeout | Hard kill, recorded as ``fail_class=timeout``"), §8's
ledger carries the same four as ``outcome TEXT NOT NULL``, §6.1 step 11 charges
the trial "even if the node fails.  A failed evaluation still consumed a
hypothesis", and :class:`evaluator.SandboxResult` states in its own docstring
that a failed run "is a value, not an exception".  So this module's gate answers,
and :meth:`FailClassDecision.require` returns — the only refusals it raises are
about the *subject*, never about the run's fate.

**"structured" is the second.**  Not a bare string: the word *and* what produced
it.  :class:`FailClass` carries the class, the sandbox-internal class it was read
from (or ``None`` when it arrived already in §9.1's spelling), the node, the
component and the sentence — so *why did this node die?* is answerable from the
record rather than from a log line that has since rotated.

**"from every sandboxed run" is the third, and it is the whole feature.**  Total:
no run escapes classification and there is no fifth value.  That totality is a
property of :data:`FAIL_CLASS_TABLE` rather than a promise in prose — every class
the sandbox stack records is a key, and the table's image is exactly
:data:`NODE_FAIL_CLASSES` — and :meth:`FailClassDecision.require` returning an
object for *all* of them, ``ok`` included, is what makes "every" operational.
That is the one place this law's verb shape differs from its six siblings': their
``require`` returns a value on success and raises on refusal, because their
subjects are refusals.  Here ``ok`` is a member of the vocabulary rather than the
absence of one, so there is no "nothing to return" case.

**This is the vocabulary owner the other six hand off to, and two handoffs are
already written into the code.**  :mod:`sandbox.timeout` restates §9.1's four in
:data:`sandbox.timeout.NODE_FAIL_CLASSES` and says why in its own comment —
*"Feature 168 is the law that owns this vocabulary from the sandbox side; this
module knows it in order to leave the other three values alone."*  Its
:func:`sandbox.timeout.timed_out_record` refuses to write its class over a record
naming a different one (a quarantined seccomp violation that reads as a timeout,
a crash that reads as a hang), and its suite names the owner: *"translating a
seccomp verdict into a timeout would erase an escape attempt, and re-labelling it
is feature 168's job."*  So feature 161's ``sandbox_escape`` — a genuine seccomp
verdict and **not** one of §9.1's four — is translated here rather than refused,
and the runner's own six (``timeout``, ``oom``, ``crash``, ``violation``,
``payload``, ``empty``) collapse into two.

**The table, and the reading behind each row:**

==============  ================  ==================================================
recorded class  §9.1's class      why
==============  ================  ==================================================
``ok``          ``ok``            §9.1's own spelling, passed through untouched
``timeout``     ``timeout``       the runner's wall/CPU kill — §8's own word for it
``error``       ``error``         §9.1's own spelling, passed through untouched
``tripwire_fail`` ``tripwire_fail`` step 10's verdict, §9.1's own spelling
``oom``         ``error``         §8's "failed any other way"
``crash``       ``error``         the signal raised or the child died to a limit
``violation``   ``error``         the signal ran and returned a refused contract
``payload``     ``error``         the window could not be reconstructed
``empty``       ``error``         the child produced no envelope at all
``sandbox_escape`` ``error``      feature 161's seccomp verdict — the handoff
==============  ================  ==================================================

The four pass-throughs are deliberate: a table that mapped ``ok`` to something
else would be a law disagreeing with the column it exists to fill, and one that
renamed ``timeout`` would be a second spelling of feature 163's own class.

**Unreadable is not ``ok``, and it is not ``error`` either.**  A subject naming
neither a class field nor a ``problems`` field says nothing about how the run
ended — an unevaluated §9.1 row, a bare object, a store row whose writer forgot
the column — and reading it as ``ok`` would be the "absence that reads as a
result" failure :mod:`sandbox.transfer` states for its own missing vector: a
failed node counted as a scored one.  So it is refused by name
(:class:`~sandbox.errors.UnclassifiedRunError`,
:data:`FAIL_CLASS_REQUIRED_CODE`).  An *unknown class* is refused separately
(:class:`~sandbox.errors.UnknownFailClassError`,
:data:`FAIL_CLASS_UNKNOWN_CODE`) rather than folded into ``error``, matching
:func:`evaluator._debit.failure_outcome`'s rule that "a drifted vocabulary must
not become a fabricated outcome": folding a misspelt ``"TimeOut"`` into ``error``
would silently convert every wall-clock kill into a generic crash, and the
operator would look for a fault that is not there.

**A ``problems`` list with no class is the ``ok`` leg.**  That is
:class:`evaluator.SandboxResult`'s own declared contract — success is
``fail_class=None`` *and* an empty ``problems``; a non-empty ``problems`` with no
class is a refused contract, §8's "failed any other way", read here as ``error``.
The rule is restated rather than imported, and the law's suite pins the two
agree.

**A raised exception is ``error``, including a raised ``TimeoutError``.**  This
is the sharpest judgement in the module and it is
:func:`evaluator._debit.failure_outcome`'s: "the sandbox records its kills as
values, never exceptions, so a timeout that arrives raised is a host-side failure
wearing a familiar name."  A raised ``TimeoutError`` classified as ``timeout``
would put a host-side bug into §8's column as a wall-clock kill, and every later
"how many trials hit the wall?" query would be answered by a number that counts
a bug among them.

**No committed artifact, and that is stated rather than omitted.**  Features 157,
163, 164 and 167 each ship one because each is a *configuration* a deployment
writes down — which isolation, how long, which pins, which imports — and
:mod:`sandbox.transfer` and :mod:`sandbox.seed` state their reason for having
none: theirs are a *format* and a *value a run is handed*, neither of which a
deployment could set differently.  This law is the second case.  §9.1's four are
a declaration and the mapping into them is fixed by §8's own definitions of the
words, so a ``failclass_policy.json`` would be a knob nobody turns — the
objection :mod:`sandbox.transfer` raises against inventing a file to hold a
constant.

**It does not persist, either.**  The feature's verb is *returns*; the write half
is already owned — :func:`sandbox.timeout.timed_out_record` writes feature 163's
class onto a node record and feature 91's ledger appends the trial row.
:meth:`FailClass.row` hands a caller the store's shape and stops there, because a
``record`` verb here would be a second writer for one column.

**Honest limits.**  This law is the *classification* of a reported outcome, not
the observation of one.  It does not run, kill, measure or detect anything, and
it cannot see a run whose termination nobody recorded — the unreadable case is
exactly that blindness, refused rather than guessed.  What the classification is
worth is bounded by the class the runner wrote down, and the one thing it does
guarantee is that whatever arrives, one of §9.1's four words comes back.

Stdlib-only, like the rest of the member: ``enum``, ``types`` and the typing
helpers — no ``json``, because there is no artifact to read.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from .errors import (
    SandboxFailClassError,
    UnclassifiedRunError,
    UnknownFailClassError,
)

__all__ = [
    "ERROR_FAIL_CLASS",
    "FAIL_CLASS_COMPONENT_NAME",
    "FAIL_CLASS_REQUIRED_CODE",
    "FAIL_CLASS_TABLE",
    "FAIL_CLASS_UNKNOWN_CODE",
    "NODE_FAIL_CLASSES",
    "OK_FAIL_CLASS",
    "SANDBOX_ESCAPE_CLASS",
    "SANDBOX_RUNNER_CLASSES",
    "SOURCE_CLASSES",
    "TIMEOUT_FAIL_CLASS",
    "TRIPWIRE_FAIL_CLASS",
    "FailClass",
    "FailClassDecision",
    "FailClassReason",
    "SandboxFailClass",
    "classify_fail_class",
    "classify_run",
    "sandbox_fail_class",
]

#: The component name this law registers under — beside feature 157's
#: ``sandbox``, feature 167's ``sandbox-imports``, feature 166's
#: ``sandbox-transfer``, feature 165's ``sandbox-seed``, feature 164's
#: ``sandbox-threads`` and feature 163's ``sandbox-timeout``, not instead of any
#: of them: the factory's registry is keyed by name and a later registration of
#: the same name *replaces* the earlier one, so a member carrying seven controls
#: carries seven components, each answering its own feature's question.
FAIL_CLASS_COMPONENT_NAME: Final[str] = "sandbox-failclass"

#: §9.1's column comment, verbatim and in its declaration order:
#: ``fail_class TEXT -- ok | timeout | error | tripwire_fail``.  The four words
#: this feature's sentence names, and the whole vocabulary a *stored* class may
#: hold.  Restated here rather than imported from the ledger or the evaluator
#: for the member's one-provenance reason — the box untrusted code is put inside
#: must not acquire a dependency on the member that drives it — and this
#: module's suite is what makes the restatement safe.
NODE_FAIL_CLASSES: Final[tuple[str, ...]] = (
    "ok",
    "timeout",
    "error",
    "tripwire_fail",
)

#: The four, each spelled once as its own name.  A constant per word rather than
#: callers writing ``"timeout"`` inline, because these are the values a caller
#: branches on — the pipeline's step-10/step-11 decisions and any later "how did
#: the trials end?" query — and a literal at each site is a spelling nobody can
#: rename in one place.
OK_FAIL_CLASS: Final[str] = "ok"
TIMEOUT_FAIL_CLASS: Final[str] = "timeout"
ERROR_FAIL_CLASS: Final[str] = "error"
TRIPWIRE_FAIL_CLASS: Final[str] = "tripwire_fail"

#: The six classes the *runner* records, restated from
#: :class:`evaluator.SandboxResult`'s own docstring, which declares them as its
#: four terminal states — success, contract problem, resource failure, channel
#: failure.  ``timeout`` is one of §9.1's four already; the other five are §8's
#: "failed any other way".  Only the runner's vocabulary a *sandboxed run* can
#: end in is listed: a host-side exception is not a class the runner records, and
#: is handled by the raised-subject branch of :func:`classify_run`.
SANDBOX_RUNNER_CLASSES: Final[tuple[str, ...]] = (
    "timeout",
    "oom",
    "crash",
    "violation",
    "payload",
    "empty",
)

#: Feature 161's class — appended by feature 158's seccomp allowlist's violation
#: path, *"System quarantines a node together with its subtree after a seccomp
#: violation, persisting a sandbox_escape fail class"*.  Spelled with the
#: underscore app_spec.xml gives it, and **not** one of §9.1's four: it is a
#: genuine seccomp verdict rather than a terminal class of the column, which is
#: why :func:`sandbox.timeout.timed_out_record` refuses to write over it and why
#: this law — the vocabulary's owner — is where it becomes ``error``.
SANDBOX_ESCAPE_CLASS: Final[str] = "sandbox_escape"

#: The feature, as data: every class a sandboxed run can be *reported* as, mapped
#: to the one of §9.1's four that names it.  Read-only — a
#: :class:`~types.MappingProxyType` rather than a dict, so a caller cannot widen
#: the vocabulary by writing into the mapping it was handed, which would be a
#: fifth class arriving without a test noticing.
#:
#: **The table is total in both directions, and that is the feature.**  Every key
#: in :data:`SANDBOX_RUNNER_CLASSES` and :data:`SANDBOX_ESCAPE_CLASS` is present,
#: so no reported class is unclassifiable, and the image is exactly
#: :data:`NODE_FAIL_CLASSES`, so no value outside §9.1's four can come back.  The
#: law's suite pins both directions rather than trusting the reader to check
#: them.
FAIL_CLASS_TABLE: Final[Mapping[str, str]] = MappingProxyType(
    {
        # §9.1's own four, passed through untouched: a table that renamed one
        # of these would be a law disagreeing with the column it fills.
        OK_FAIL_CLASS: OK_FAIL_CLASS,
        TIMEOUT_FAIL_CLASS: TIMEOUT_FAIL_CLASS,
        ERROR_FAIL_CLASS: ERROR_FAIL_CLASS,
        TRIPWIRE_FAIL_CLASS: TRIPWIRE_FAIL_CLASS,
        # The runner's other five: §8's "failed any other way", one class each
        # because the finer vocabulary is the runner's to keep — §9.1's column
        # has four values and «why it crashed» belongs in the row's detail.
        "oom": ERROR_FAIL_CLASS,
        "crash": ERROR_FAIL_CLASS,
        "violation": ERROR_FAIL_CLASS,
        "payload": ERROR_FAIL_CLASS,
        "empty": ERROR_FAIL_CLASS,
        # Feature 161's seccomp verdict, translated rather than refused — the
        # handoff feature 163's suite names as this feature's job.
        SANDBOX_ESCAPE_CLASS: ERROR_FAIL_CLASS,
    }
)

#: Every class this law can read — the table's keys, in the table's order.  The
#: read side: a deployment asking *which spellings does this deployment accept
#: from its box?* reads a value rather than inferring it from the table, the
#: same discipline :meth:`sandbox.timeout.SandboxTimeout.wall_s` applies to its
#: budget.
SOURCE_CLASSES: Final[tuple[str, ...]] = tuple(FAIL_CLASS_TABLE)

#: The greppable code every *unreadable subject* refusal carries — the token an
#: operator greps a log for, the discipline
#: :data:`sandbox.imports.DISALLOWED_IMPORT_CODE` and
#: :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE` set for their own laws.
#: Two codes rather than one because the two refusals have different repairs:
#: this one means the caller's record is missing a column, the other means the
#: box wrote a class this deployment's vocabulary does not have.
FAIL_CLASS_REQUIRED_CODE: Final[str] = "fail_class_required"

#: The greppable code every *unknown class* refusal carries.  See above for why
#: it is not the same token as :data:`FAIL_CLASS_REQUIRED_CODE`.
FAIL_CLASS_UNKNOWN_CODE: Final[str] = "fail_class_unknown"

#: The names a subject may carry its class under — the *name* the class is
#: persisted under, in the shapes §9.1's ``node`` row, §8's ledger row and the
#: tripwires' verdict all spell it.  ``fail_class`` first because that is §9.1's
#: column; the other two are the spellings the evaluator's and the ledger's
#: records use for the same fact, and ``terminal_class`` is the third a
#: store-shaped row arrives with.  Restated from
#: :data:`sandbox.timeout._FAIL_CLASS_FIELDS` rather than imported, and pinned by
#: this suite, for the same one-provenance reason the vocabulary is.
#:
#: Reading all three is what lets a §9.1 node row, a §8 ledger row and a
#: tripwire verdict arrive through one reader — a second reader per shape would
#: be three places for "what class does this record name?" to be answered
#: differently.
_FAIL_CLASS_FIELDS: Final[tuple[str, ...]] = (
    "fail_class",
    "outcome",
    "terminal_class",
)

#: The field a subject carries its *contract problems* under — the evaluator's
#: own spelling, and the one this law reads to decide the ``ok`` leg.  The two
#: sequence types are accepted because they are the two a caller's own result
#: record would hold them in; anything else under this name says nothing about
#: how the run ended.
_PROBLEMS_FIELD: Final[str] = "problems"
_PROBLEM_SEQUENCES: Final[tuple[type, ...]] = (list, tuple)


def classify_fail_class(value: Any) -> str | None:
    """One recorded class -> one of §9.1's four, or ``None``.

    The one place a class is read — :func:`classify_run` and
    :class:`FailClass`'s own constructor both reach it — so the gate and the
    value cannot disagree about what a class is, the member's one-provenance
    rule applied to the one vocabulary this law owns.

    The match is **exact**, deliberately: §9.1's column holds one closed
    vocabulary and a store round-trip does not pad it, so ``"timeout "`` and
    ``"TimeOut"`` are *unknown* rather than silently the class they resemble.
    Stripping here would make this law the place a malformed writer's drift
    became invisible — the class would be recorded right and the writer would go
    on writing wrong.

    ``None`` for everything unplaceable — a value that is not a string, a blank
    string, a class outside the table — because the *caller* decides which
    refusal that earns: a subject naming nothing at all and a subject naming a
    class this deployment does not know are different failures with different
    repairs, and only the caller knows which it was handed.
    """
    if not isinstance(value, str) or not value:
        return None
    return FAIL_CLASS_TABLE.get(value)


class FailClass:
    """One sandboxed run's outcome as §9.1's column holds it — structured.

    Feature 168's second word.  A bare ``"timeout"`` answers *how did this run
    end?*; this object answers *and what made it end that way?*, which is the
    question an operator actually has a month later.  So the class is carried
    with the provenance it was read from:

    * :attr:`fail_class` — §9.1's word, one of :data:`NODE_FAIL_CLASSES`;
    * :attr:`source` — the sandbox-internal class it was read from (``"oom"``,
      ``"crash"``, ``"sandbox_escape"``), or ``None`` when the class arrived
      already in §9.1's own spelling and nothing was translated;
    * :attr:`node_id`, :attr:`component`, :attr:`detail` — what a run record
      carries beside the class and a reader correlates on.

    **A record that contradicts itself is refused.**  This class is exported and
    its fields are public, so it can be assembled by hand and — more to the
    point — rebuilt from a store row by a caller that has no gate to run.  Three
    contradictions are refused at construction rather than carried:
    a word outside §9.1's four; a ``source`` outside the vocabulary this law can
    read; and a ``source`` whose table target is a *different* word from the one
    given.  The third is the sharpest: ``FailClass("error", source="timeout")``
    is a record claiming a host-side error and a wall-clock kill at once, and a
    reader of §8's column would have no way to tell which the run actually was.
    The same "the value checks itself" stance
    :class:`sandbox.timeout.TimeoutKill` takes for its own contradiction — a
    kill whose overrun is negative.

    **The constructor is not the gate.**  It validates a *class*; it does not
    answer for a *run*.  A caller holding a raw subject calls
    :func:`classify_run` (or the component's ``check``), which is where the
    unreadable and unknown cases are told apart with their own sentences.
    """

    __slots__ = ("component", "detail", "fail_class", "node_id", "source")

    def __init__(
        self,
        fail_class: str,
        *,
        source: str | None = None,
        node_id: str = "",
        component: str = "",
        detail: str = "",
    ) -> None:
        if not isinstance(fail_class, str) or fail_class not in NODE_FAIL_CLASSES:
            known = ", ".join(repr(cls) for cls in NODE_FAIL_CLASSES)
            raise SandboxFailClassError(
                f"{FAIL_CLASS_UNKNOWN_CODE}: a fail class was assembled with "
                f"{fail_class!r} ({type(fail_class).__name__}), which is not one "
                f"of §9.1's four ({known}). The column comment is "
                f"'fail_class TEXT -- ok | timeout | error | tripwire_fail' and "
                f"there is no fifth value: a record carrying one would be a "
                f"stored outcome no later 'how did the trials end?' query could "
                f"group, and §8's ledger — 'outcome TEXT NOT NULL' — is what "
                f"those queries are answered from. Refused rather than recorded "
                f"(feature 168)."
            )
        if source is not None and source not in FAIL_CLASS_TABLE:
            listed = ", ".join(repr(cls) for cls in SOURCE_CLASSES)
            raise SandboxFailClassError(
                f"{FAIL_CLASS_UNKNOWN_CODE}: a fail class was assembled with "
                f"source = {source!r} ({type(source).__name__}), which is not a "
                f"class this deployment's box is known to report ({listed}). The "
                f"source is the *provenance* of the translation — the runner's "
                f"own class, or feature 161's seccomp verdict — so a value "
                f"outside that vocabulary is a claim about a box this law has "
                f"never seen. Refused rather than carried (feature 168)."
            )
        if source is not None and FAIL_CLASS_TABLE[source] != fail_class:
            raise SandboxFailClassError(
                f"{FAIL_CLASS_UNKNOWN_CODE}: a fail class was assembled naming "
                f"{fail_class!r} while its source is {source!r}, which this "
                f"deployment's vocabulary reads as "
                f"{FAIL_CLASS_TABLE[source]!r}. The two are one fact — a class "
                f"and where it came from — so a record stating both and "
                f"disagreeing with itself is one no reader can resolve: "
                f"a host-side error and a wall-clock kill written as the same "
                f"row. Refused rather than recorded (feature 168)."
            )
        self.fail_class = fail_class
        self.source = source
        self.node_id = node_id
        self.component = component
        self.detail = detail

    @property
    def translated(self) -> bool:
        """Whether this class came out of the sandbox's finer vocabulary.

        ``False`` for the four pass-throughs — the class arrived as §9.1 spells
        it and nothing was decided — and ``True`` for the six the runner records
        and feature 161's seccomp verdict.  The read side of the feature's second
        word: a deployment asking *how much of our box's vocabulary are we
        collapsing?* reads this rather than re-deriving it from the table.
        """
        return self.source is not None

    @property
    def ok(self) -> bool:
        """Whether the run was scored — §9.1's ``ok``.

        A *member of the vocabulary* rather than the absence of one, which is
        this feature's own stance and the reason :meth:`FailClassDecision.require`
        returns an object for every class including this one.  A caller that
        wants "was there a failure?" asks this; one that wants the word reads
        :attr:`fail_class`.
        """
        return self.fail_class == OK_FAIL_CLASS

    def row(self) -> dict[str, Any]:
        """The class as a store-shaped mapping — what a caller writes down.

        ``fail_class`` under §9.1's own column name, with the provenance beside
        it when there was a translation and the node identity when one was given
        — the same "hand out the shape the store wants" discipline
        :meth:`sandbox.timeout.TimeoutKill.row` applies to a kill.  A fresh dict
        per call, never a shared one.

        ``source`` is omitted rather than written as ``None``: §9.1's column is
        the class, the provenance is extra, and a caller writing this mapping
        into a row should not have to decide whether a null column is the store's
        shape or this law's.  What it deliberately *is* not is a writer — this
        module has no ``record`` verb, and the node row's write belongs to
        feature 163's :func:`sandbox.timeout.timed_out_record`.
        """
        row: dict[str, Any] = {"fail_class": self.fail_class}
        if self.source is not None:
            row["source"] = self.source
        if self.node_id:
            row["node_id"] = self.node_id
        return row

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"FailClass(fail_class={self.fail_class!r}, source={self.source!r}, "
            f"node_id={self.node_id!r})"
        )


class FailClassReason(enum.StrEnum):
    """Why a run was classified or refused — the audit vocabulary.

    One enumeration carries the classification and the two refusals, for the
    reason :class:`sandbox.timeout.TimeoutReason`,
    :class:`sandbox.isolation.RunReason` and
    :class:`sandbox.seed.SeedReason` do: a decision's reason is one fact with two
    polarities and the audit line should read the same either way — and the two
    refusals are separate members because the repairs differ.
    """

    #: Classified: the subject named a class this law could place, and the one
    #: of §9.1's four that names it came back.  The feature's headline, and the
    #: *only* reason a decision carries a :class:`FailClass` — a refusal is not a
    #: classification, which is the property :meth:`FailClassDecision.require`
    #: and :attr:`FailClassDecision.refused` are built on.
    CLASSIFIED = "classified"

    #: Refused: the subject says nothing about how the run ended — it names
    #: neither a class field nor a ``problems`` field.  Its own reason because
    #: the repair is the caller's record: a column was not written, not a
    #: vocabulary that has drifted.  Reading it as ``ok`` would be the "absence
    #: that reads as a result" failure this member's transfer law states.
    UNREADABLE_SUBJECT = "unreadable-subject"

    #: Refused: the subject names a class, and it is not one this deployment's
    #: box is known to report.  Kept apart from the last one because the repair
    #: is on the *other* side of the seam — the box wrote a spelling this law has
    #: never seen — and folding it into ``error`` would convert every drifted
    #: wall-clock kill into a generic crash, sending an operator after a fault
    #: that is not there.
    UNKNOWN_CLASS = "unknown-class"


class FailClassDecision:
    """The gate's whole answer: the class, why, and in what words.

    ``fail_class`` is the :class:`FailClass` for a subject this law could
    classify and ``None`` otherwise, so a caller reading ``decision.fail_class``
    after checking :attr:`classified` has the object rather than a sentinel —
    the shape :class:`sandbox.timeout.TimeoutDecision` gives its own ``kill``.

    **There is no ``ok``-means-``None`` state, and that is the feature.**  Every
    other decision in this member has a pass-through that hands back nothing,
    because their subjects are refusals and a run that was not refused has no
    refusal to report.  Here ``ok`` is one of the four values the feature's
    sentence names, so a *classified* run always has a :class:`FailClass` —
    ``ok`` included — and ``None`` means only that this law could not read the
    subject at all.

    :attr:`refused` is deliberately separate from ``not classified`` — they are
    the same fact here — but it is named anyway, because the member's other
    decisions state a refusal as its own property and a caller that read a bare
    falsy as "the run was fine" would treat an unreadable subject as a clean run.
    """

    __slots__ = ("detail", "fail_class", "reason")

    def __init__(
        self,
        *,
        reason: FailClassReason,
        detail: str,
        fail_class: FailClass | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.fail_class = fail_class

    @property
    def classified(self) -> bool:
        """Whether one of §9.1's four came back — the gate's headline.

        True only for :attr:`FailClassReason.CLASSIFIED`.  It is *not* the
        feature's ``ok``: a run classified ``error`` is classified too, and a
        caller asking "was there a failure?" reads
        :attr:`FailClass.ok` on the value rather than this.
        """
        return self.fail_class is not None

    @property
    def refused(self) -> bool:
        """Whether this law could not read the subject at all.

        The two refusal reasons, never :attr:`FailClassReason.CLASSIFIED`.  A
        caller that must not proceed asks this; a caller that only wants the word
        calls :meth:`require` and lets the refusal come out as an exception.
        """
        return self.reason in (
            FailClassReason.UNREADABLE_SUBJECT,
            FailClassReason.UNKNOWN_CLASS,
        )

    def require(self) -> FailClass:
        """Return the class, or raise the refusal — **never ``None``**.

        The bridge between the gate's returned answer and the exception a caller
        wants, and the one place this law's shape differs from its six siblings'
        by construction rather than by accident: their ``require`` returns a
        value on success and raises on refusal, with a pass-through that yields
        nothing to persist.  Here ``ok`` *is* one of the four the feature's
        sentence names, so a classified run always has a :class:`FailClass` to
        return — and "returns a fail class from **every** sandboxed run" is
        enforced on the line after the spawn rather than remembered.

        Which refusal raises which error is deliberate:
        :attr:`FailClassReason.UNREADABLE_SUBJECT` is a
        :class:`~sandbox.errors.UnclassifiedRunError` — the caller's record is
        short a column — and :attr:`FailClassReason.UNKNOWN_CLASS` is a
        :class:`~sandbox.errors.UnknownFailClassError`, naming the offending
        class and the vocabulary so the operator sees which side drifted.  Both
        are :class:`~sandbox.errors.SandboxFailClassError`, so a caller that has
        only one ``except`` still catches the feature.
        """
        if self.refused:
            raise (
                UnclassifiedRunError(self.detail)
                if self.reason is FailClassReason.UNREADABLE_SUBJECT
                else UnknownFailClassError(self.detail)
            )
        # Not an ``assert``: ``python -O`` strips those, and the invariant here
        # — *classified* means a class is carried — is what makes this verb's
        # "returns a class for every run" claim true rather than usually true.
        # A decision assembled by hand with CLASSIFIED and no class would
        # otherwise return ``None`` from a verb whose whole contract is that it
        # cannot, which is the one failure the feature's word *every* rules out.
        if self.fail_class is None:  # pragma: no cover - unreachable by construction
            raise SandboxFailClassError(
                f"{FAIL_CLASS_REQUIRED_CODE}: a fail-class decision was assembled "
                f"as {self.reason!r} while carrying no class. Feature 168's verb "
                f"is *returns a fail class from every sandboxed run*, so a "
                f"classified decision with nothing to return is the one state "
                f"this law cannot have — 'classified' and 'a class is carried' "
                f"are the same fact, and a caller handed a bare ``None`` here "
                f"would have to branch on it at every dispatch (feature 168)."
            )
        return self.fail_class

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"FailClassDecision(reason={self.reason!r}, "
            f"classified={self.classified}, refused={self.refused})"
        )


def _subject_field(subject: object, field: str) -> tuple[bool, Any]:
    """Whether ``subject`` names ``field``, and what it holds — ``(present, value)``.

    Reads a mapping or an object, because both shapes occur in this repository:
    §9.1's ``node`` row arrives from a relational driver as a mapping, while a
    :class:`~evaluator.SandboxResult`, a :class:`sandbox.timeout.TimeoutKill` and
    the tripwires' verdict carry their class as an attribute.  ``present`` is
    reported separately from ``value`` because for this law the difference is the
    whole refusal: a record naming ``fail_class`` with a null value is an
    *unevaluated node*, while a record naming no such field at all is a record
    this law cannot read — and telling them apart is what keeps "nothing yet"
    from being reported as "unreadable vocabulary".
    """
    if isinstance(subject, Mapping):
        return field in subject, subject.get(field, None)
    present = hasattr(subject, field)
    return present, getattr(subject, field, None) if present else None


def _subject_class_field(subject: object) -> tuple[str | None, Any]:
    """The class ``subject`` names and the field it names it under.

    Walks :data:`_FAIL_CLASS_FIELDS` in order, so the three row shapes the
    repository writes arrive through one reader.  A field present but ``None`` is
    remembered rather than returned, because a sibling spelling may carry the
    real class — the "a real class beside a null one still decides" rule
    :func:`sandbox.timeout.timed_out_record` states for its own comparison.
    ``(None, None)`` means the subject names no such field at all, which is the
    unreadable case rather than a null one.
    """
    first_present: str | None = None
    for field in _FAIL_CLASS_FIELDS:
        present, value = _subject_field(subject, field)
        if not present:
            continue
        if first_present is None:
            first_present = field
        if value is None:
            continue
        return field, value
    return first_present, None


def _subject_problems(subject: object) -> tuple[bool, list[Any] | tuple[Any, ...] | None]:
    """The contract problems ``subject`` names — ``(present, problems)``.

    Reported only when the field holds a genuine sequence of problems: a
    ``problems`` field holding something else — a string, a flag, a number —
    says nothing about how the run ended, and reading ``len`` of it would make
    this law's ``ok`` leg depend on a value the evaluator's contract never
    produces.  ``present`` is still ``False`` in that case, so the subject falls
    to the ordinary unreadable refusal rather than being classified from a field
    this law could not read.
    """
    present, value = _subject_field(subject, _PROBLEMS_FIELD)
    if not present or not isinstance(value, _PROBLEM_SEQUENCES):
        return False, None
    return True, value


def _subject_identity(subject: object) -> tuple[str, str]:
    """The ``(node_id, component)`` a subject names — best effort, for prose.

    Read while building a classification rather than for a key, so a subject
    naming neither must still produce a readable sentence rather than a second
    failure inside the first — the discipline
    :func:`sandbox.timeout._record_node_id` states for its own refusal.  Every
    identifier spelling the repository's node shapes use is tried, and anything
    that is not a non-empty string is reported as absent.
    """
    node = ""
    for field in ("node_id", "id", "node"):
        _, value = _subject_field(subject, field)
        if isinstance(value, str) and value.strip():
            node = value
            break
    _, component = _subject_field(subject, "component")
    return node, component if isinstance(component, str) else ""


def _unknown_class_decision(value: Any, *, node_id: str, component: str) -> FailClassDecision:
    """The refusal for a subject naming a class outside the vocabulary."""
    listed = ", ".join(repr(cls) for cls in SOURCE_CLASSES)
    return FailClassDecision(
        reason=FailClassReason.UNKNOWN_CLASS,
        detail=(
            f"{FAIL_CLASS_UNKNOWN_CODE}: the sandboxed run "
            f"({component!r}) was reported with a fail class of {value!r} "
            f"({type(value).__name__}), which is not one of the classes this "
            f"deployment's box is known to report ({listed}). §9.1's column "
            f"holds one closed vocabulary — 'fail_class TEXT -- ok | timeout | "
            f"error | tripwire_fail' — and a drifted class must not become a "
            f"fabricated outcome: folding an unknown spelling into 'error' would "
            f"read every misspelt wall-clock kill as a generic crash and send an "
            f"operator after a fault that is not there. Refused rather than "
            f"translated; either the box has begun reporting a class this law "
            f"has never seen, or the record was written by something that is not "
            f"the runner (feature 168)."
        ),
    )


def _unreadable_decision(subject: object, *, component: str) -> FailClassDecision:
    """The refusal for a subject that says nothing about how the run ended."""
    fields = ", ".join(repr(field) for field in _FAIL_CLASS_FIELDS)
    return FailClassDecision(
        reason=FailClassReason.UNREADABLE_SUBJECT,
        detail=(
            f"{FAIL_CLASS_REQUIRED_CODE}: a sandboxed run ({component!r}) was "
            f"offered to the fail-class gate carrying no class at all "
            f"(got {type(subject).__name__}: {subject!r}). §9.1's column is "
            f"'fail_class TEXT' and feature 168's sentence is *from every "
            f"sandboxed run*, so a record naming none of the fields a class is "
            f"persisted under ({fields}) says nothing about how the run ended — "
            f"and 'unwritten' is not 'ok': reading it as a scored run would be "
            f"the absence that reads as a result, a failed node counted as a "
            f"successful one. Refused rather than classified (feature 168)."
        ),
    )


def _ok_decision(*, node_id: str, component: str) -> FailClassDecision:
    """The ``ok`` leg: no class and no contract problem — the run was scored."""
    return FailClassDecision(
        reason=FailClassReason.CLASSIFIED,
        fail_class=FailClass(
            OK_FAIL_CLASS,
            node_id=node_id,
            component=component,
            detail=(
                f"{OK_FAIL_CLASS}: the sandboxed run of component {component!r} "
                f"returned with no fail class and no contract problem, so it was "
                f"scored — §9.1's 'ok', and a member of the vocabulary rather "
                f"than the absence of one. The reading is the evaluator's own "
                f"(a run is 'ok' when it names no class *and* reports no "
                f"problem), restated here as data and pinned by this suite "
                f"(feature 168)."
            ),
        ),
        detail=(
            f"{OK_FAIL_CLASS}: the run of component {component!r} was scored; no "
            f"fail class is recorded (feature 168)."
        ),
    )


def _error_from_problems(
    problems: Any, *, node_id: str, component: str
) -> FailClassDecision:
    """The refused-contract leg: problems, no class — §8's "failed any other way"."""
    return FailClassDecision(
        reason=FailClassReason.CLASSIFIED,
        fail_class=FailClass(
            ERROR_FAIL_CLASS,
            node_id=node_id,
            component=component,
            detail=(
                f"{ERROR_FAIL_CLASS}: the sandboxed run of component "
                f"{component!r} ran and returned a value the signal contract "
                f"refused — {len(problems)} problem(s) reported and no fail "
                f"class — which is §8's 'failed any other way' under "
                f"{ERROR_FAIL_CLASS!r}. The signal executed, so this is not a "
                f"resource failure; what it returned was rejected, and the "
                f"problems are the detail a reader follows (feature 168)."
            ),
        ),
        detail=(
            f"{ERROR_FAIL_CLASS}: the run of component {component!r} reported "
            f"{len(problems)} contract problem(s) and was not scored "
            f"(feature 168)."
        ),
    )


def _raised_decision(subject: BaseException, *, component: str) -> FailClassDecision:
    """The raised-subject leg: any exception, ``TimeoutError`` included, is ``error``.

    The sharpest judgement in this law, and it is not this law's own: the sandbox
    records its kills as *values*, never exceptions, so a timeout that arrives
    raised is a host-side failure wearing a familiar name — the reading
    :func:`evaluator._debit.failure_outcome` states for the same seam.  A raised
    :class:`TimeoutError` classified as ``timeout`` would put a host-side bug
    into §8's column as a wall-clock kill, and every later "how many trials hit
    the wall?" query would be answered by a number that counts a bug among them.
    """
    kind = type(subject).__name__
    return FailClassDecision(
        reason=FailClassReason.CLASSIFIED,
        fail_class=FailClass(
            ERROR_FAIL_CLASS,
            node_id="",
            component=component,
            detail=(
                f"{ERROR_FAIL_CLASS}: the sandboxed run of component "
                f"{component!r} failed with a raised {kind} ({subject!s}). A "
                f"raised failure is §8's 'failed any other way' — including a "
                f"raised TimeoutError, which is deliberately *not* read as "
                f"{TIMEOUT_FAIL_CLASS!r}: §5.2's timeout is the runner's hard "
                f"kill, recorded as a value (feature 79's 'a failed evaluation "
                f"still consumed a hypothesis'), so a timeout that arrives "
                f"raised is a host-side failure wearing a familiar name. Reading "
                f"it as a wall-clock kill would count a bug among the trials "
                f"that ran out of time (feature 168)."
            ),
        ),
        detail=(
            f"{ERROR_FAIL_CLASS}: the run of component {component!r} raised "
            f"{kind}; recorded as a failure rather than a "
            f"{TIMEOUT_FAIL_CLASS!r} (feature 168)."
        ),
    )


def classify_run(
    subject: object,
    *,
    node_id: str | None = None,
    component: str | None = None,
) -> FailClassDecision:
    """Answer one run: one of §9.1's four, or a refusal naming what was found.

    The gate, and the one place the law is actually applied — every other verb in
    this module (:meth:`SandboxFailClass.check`, :meth:`FailClassDecision.require`)
    reaches this function rather than re-deciding.  **Nothing is raised for any
    run's fate**: a run that timed out, crashed, escaped or was scored is an
    outcome the pipeline records (§6.1 step 11, feature 79), and a gate that
    raised would turn one hung signal into a crashed evaluator over thousands of
    unattended candidates.  What it does refuse — as a decision, worded by reason
    — is a subject it cannot read and a class it does not know.

    ``subject`` may be, in the order the branches are taken:

    * a :class:`FailClass` — this law's own answer, which is *idempotent*: the
      word and the provenance are carried through, so a caller that classifies
      twice gets the same class rather than a second, source-less reading of it;
    * a raised exception — ``error``, on the rule
      :func:`failure_outcome` states (see :func:`_raised_decision`);
    * a class *text* — the vocabulary's own spelling, for a caller holding the
      recorded class rather than a record that carries it;
    * a mapping or an object naming a class under :data:`_FAIL_CLASS_FIELDS`
      (null-valued siblings are passed over, a real class beside a null one
      decides) — which is §9.1's ``node`` row, §8's ledger row, the evaluator's
      :class:`~evaluator.SandboxResult`, feature 163's
      :class:`~sandbox.timeout.TimeoutKill` and the tripwires' verdict all at
      once.  The one reader is the point: five shapes of one fact, and a second
      reader per shape would be five places for "what class does this name?" to
      be answered differently;
    * a mapping or an object naming a ``problems`` sequence and no class — the
      ``ok``/refused-contract leg, the evaluator's own rule restated
      (:func:`_ok_decision`, :func:`_error_from_problems`).

    It returns ``ok`` for a subject that names ``problems`` as an *empty*
    sequence, because that is :class:`evaluator.SandboxResult`'s declared
    success: no class and no problem.  Anything naming neither a class field nor
    a sequence of problems is refused rather than read as ``ok``.

    ``node_id`` and ``component`` override what the subject carries, for a caller
    that knows the identity — a storer mid-write — the same courtesy
    :func:`sandbox.timeout.timed_out_record` extends with its own ``node_id``.
    """
    if isinstance(subject, FailClass):
        # The law's own value, classified again: the word and the *provenance*
        # travel back, which is the half a naive re-read of ``.fail_class`` would
        # lose — and the reason this branch exists rather than being handled by
        # the generic class-field path below.
        return FailClassDecision(
            reason=FailClassReason.CLASSIFIED,
            fail_class=FailClass(
                subject.fail_class,
                source=subject.source,
                node_id=node_id if node_id is not None else subject.node_id,
                component=component if component is not None else subject.component,
                detail=subject.detail,
            ),
            detail=(
                f"{subject.fail_class}: the run of component "
                f"{subject.component!r} was already classified (feature 168)."
            ),
        )

    resolved_node, resolved_component = _subject_identity(subject)
    node = node_id if node_id is not None else resolved_node
    owner = component if component is not None else resolved_component

    if isinstance(subject, BaseException):
        return _raised_decision(subject, component=owner)

    if isinstance(subject, str):
        return _classify_text(subject, node_id=node, component=owner)

    field, value = _subject_class_field(subject)
    if value is not None:
        return _classify_text(value, node_id=node, component=owner, field=field)

    # No class named.  The ``problems`` half decides between "scored", "the
    # contract refused the return" and "this record says nothing at all" — the
    # three states :class:`evaluator.SandboxResult` declares, read here through
    # the one field that tells them apart.
    present, problems = _subject_problems(subject)
    if present and problems is not None:
        if not problems:
            return _ok_decision(node_id=node, component=owner)
        return _error_from_problems(problems, node_id=node, component=owner)

    return _unreadable_decision(subject, component=owner)


def _classify_text(
    value: Any,
    *,
    node_id: str,
    component: str,
    field: str | None = None,
) -> FailClassDecision:
    """Translate one recorded class into §9.1's four — the second half of the gate.

    The four pass-throughs return the class with ``source=None``, because
    nothing was decided and claiming a provenance would be inventing one; the
    six the runner records and feature 161's seccomp verdict return the class
    they translate *to*, with the spelling they came from carried as the
    :attr:`FailClass.source` — which is what makes the translation auditable
    rather than lossy.

    ``field`` is the name the class was found *under*, for the sentence only:
    this law reads three spellings of one fact and a refusal should say which
    one it read, so an operator repairing a writer knows which column to look at.
    """
    resolved = classify_fail_class(value)
    if resolved is None:
        return _unknown_class_decision(value, node_id=node_id, component=component)

    where = f" under {field!r}" if field is not None else ""
    if value in NODE_FAIL_CLASSES:
        return FailClassDecision(
            reason=FailClassReason.CLASSIFIED,
            fail_class=FailClass(
                resolved,
                node_id=node_id,
                component=component,
                detail=(
                    f"{resolved}: the sandboxed run of component {component!r} "
                    f"was reported as {value!r}{where}, which is §9.1's own "
                    f"spelling — nothing was translated and no provenance is "
                    f"claimed (feature 168)."
                ),
            ),
            detail=(
                f"{resolved}: the run of component {component!r} is recorded "
                f"with §9.1's class {resolved!r} (feature 168)."
            ),
        )

    return FailClassDecision(
        reason=FailClassReason.CLASSIFIED,
        fail_class=FailClass(
            resolved,
            source=value,
            node_id=node_id,
            component=component,
            detail=(
                f"{resolved}: the sandboxed run of component {component!r} was "
                f"reported as {value!r}{where}, which is the box's own class "
                f"rather than one of §9.1's four — §9.1's column is 'fail_class "
                f"TEXT -- ok | timeout | error | tripwire_fail' and it has no "
                f"room for it. §8's reading of the four places {value!r} under "
                f"{resolved!r} because it is neither a completed run, nor a "
                f"wall-clock kill, nor step 10's verdict — it is a run that "
                f"failed some other way, and the finer class is kept here as the "
                f"translation's provenance rather than discarded (feature 168)."
            ),
        ),
        detail=(
            f"{resolved}: the run of component {component!r} was reported as "
            f"{value!r} and is recorded under §9.1's class {resolved!r}, with "
            f"{value!r} kept as its source (feature 168)."
        ),
    )


class SandboxFailClass:
    """Feature 168's law, as the value a composed application carries.

    A stateless facade over this module — the same shape
    :class:`sandbox.SandboxIsolation` gives feature 157,
    :class:`sandbox.SandboxImports` 167, :class:`sandbox.SandboxTransfer` 166,
    :class:`sandbox.SandboxSeed` 165, :class:`sandbox.SandboxThreads` 164 and
    :class:`sandbox.SandboxTimeout` 163 — so a caller holding the composed
    component can ask the feature's question, *what is this run's fail class?*,
    without importing the member's submodules by name.

    **It carries nothing at all, and it is the first law in this member that
    can say that.**  Every sibling holds something: an isolation mechanism, an
    allowlist, a channel's format, a seed's salt, an environment's caps, a
    compiled budget.  This law's subject is a *vocabulary* and a *mapping*, both
    fixed by §9.1 and §8 and neither a deployment's to set — so ``__slots__`` is
    empty, the builder has nothing to compile, and there is no committed artifact
    behind the component.  A non-``None`` component at this seat is therefore
    proof only that the law is loaded, which is the reading features 165's and
    166's seats established and the one feature 168's shares.

    **``require`` returns a :class:`FailClass` for every subject it classifies,
    ``ok`` included** — the feature's "every", made operational, and the one
    place this law's verb shape differs from all six siblings'.  See
    :meth:`FailClassDecision.require`.

    **The delegation is deliberately thin** — each verb is one call into this
    module — because a second implementation of the table or the reader here
    would be a second thing to keep in sync, and the member's one-provenance
    rule exists so that cannot happen.
    """

    __slots__ = ()

    def check(self, subject: object) -> FailClassDecision:
        """Answer ``subject``'s fail class — the gate, as a value.

        ``subject`` is anything :func:`classify_run` reads: the evaluator's
        result, a §9.1 node row, a §8 ledger row, a :class:`FailClass`, a
        recorded class text, feature 163's kill, the tripwires' verdict, or the
        exception a host-side step raised.  Nothing is raised for the run's fate;
        the two refusals come back as the decision's reason.
        """
        return classify_run(subject)

    def require(self, subject: object) -> FailClass:
        """Return the class for ``subject``, or raise the refusal — never ``None``.

        The launcher's verb, and the one shape in this member that returns *a
        value for ``ok``*: feature 168's sentence is "from every sandboxed run",
        and ``ok`` is one of the four it names, so a caller that puts this on the
        line after the spawn has a class for every run that comes back rather
        than a pass-through it has to remember to handle.
        """
        return classify_run(subject).require()

    def classes(self) -> tuple[str, ...]:
        """§9.1's four, in §9.1's declaration order — the read side.

        Exposed so a deployment — a CI check, a query builder, a report — reads
        the vocabulary rather than re-spelling it, the discipline
        :meth:`sandbox.SandboxTimeout.wall_s` applies to its budget.  Reading it
        grants nothing: the tuple is §9.1's declaration and this law holds no
        capability to widen it.
        """
        return NODE_FAIL_CLASSES

    def sources(self) -> tuple[str, ...]:
        """Every class this deployment's box is known to report.

        The other half of the audit: :meth:`classes` is what gets *stored* and
        this is what gets *accepted*, so a deployment can check the two against
        what its runner actually writes — the totality claim
        :data:`FAIL_CLASS_TABLE` makes, readable rather than inferred.
        """
        return SOURCE_CLASSES

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "SandboxFailClass()"


def sandbox_fail_class() -> SandboxFailClass:
    """Feature 168's law, fresh — for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the law
    would have nothing to run it *on*, since the law needs a run's reported
    outcome to answer for.  This is the module-level convenience the member's own
    tests and any operator script reach, and it is the same call
    :func:`sandbox.build_sandbox_fail_class` makes minus the composition.
    """
    return SandboxFailClass()
