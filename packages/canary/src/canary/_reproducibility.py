"""Two runs, one seed, one comparison — bit-identity as a byte verdict.

app_spec.xml feature 145 (this plugin's, in the "Determinism Guarantees &
Nightly Canary" category): *"System asserts bit-identical output across two
runs of the same seeded signal, which returns a byte-level comparison
result."* docs/nullius-tech-architecture.md §12's determinism table ends on
the row this check is the mechanical half of — "Float reproducibility |
Fixed reduction order; no ``fastmath``; no GPU in the eval path" — and §5.1
supplies the surface it runs against: a signal is ``signal(ctx, seed)``, and
the seed is "the only argument that carries randomness" into an otherwise
pure function. §1 folds the whole thing into the replay guarantee ("Pinned
images, pinned seeds, single-threaded BLAS in eval workers"); this module is
what turns that sentence into something a run can *fail*.

Four decisions carry the feature, and each is a pin rather than a knob.

**The comparison is over bytes, and that is the point.**
The feature's own word is "bit-identical", so the unit is a byte string and
the verdict is ``left == right`` at the byte level — no tolerance, no
``isclose``, no relative epsilon. §12's *nightly* canary (feature 143)
compares a score against a recorded constant to ``1e-12``, which is the right
instrument for "did the world move?"; a tolerance of zero is the right
instrument for "did the machine move?", and the two are not
interchangeable. ``-0.0`` and ``0.0`` are the same number and different
bytes; a NaN equals nothing, itself included, so a float comparison of two
identical NaN panels reports a divergence that is not there; and the
smallest real float divergence — a threaded reduction reassociating, a
``fastmath`` contraction collapsing a fused multiply-add — is exactly the
kind of difference a tolerance is built to forgive, which is why a
tolerance is what lets it hide. Bytes compare where floats would excuse.
This is also why the check never normalizes: any canonicalization applied
here (sorting, rounding, re-encoding) is an opportunity for the two runs to
be made to agree, and a comparison that can be satisfied by editing the
comparison is not an assertion.

**The runs are a callable seam, and their *content* is the caller's.**
The seam this module takes is ``SeededSignal`` — one integer seed in, that
run's output bytes out — so the caller closes over everything else: the
window, the materialized payload, the serialization, and whether the second
run happens in this process or in a second one. That last one is the reason
the seam exists rather than a hard-coded "call it twice". Two in-process
calls catch a signal that reads a clock, samples unseeded randomness, mutates
global state, or depends on a set's iteration order; two calls in *separate
interpreters* catch strictly more (an interpreter whose string hash seed
differs, a library whose import side effects order differently), and a
caller that wants that strength expresses it by handing in a callable that
spawns — the sandbox member's own runner (features 157-168) is exactly such a
callable, once it lands. This module deliberately does not choose for the
caller, and deliberately does not *serialize* for the caller either:
canonical bytes come from the layers that own them — the evaluator's Arrow
IPC channel (§5.2, feature 166), the artifact renderer (which is
"deterministic: two renders of one attribution produce byte-identical JSON"),
the feature store's payload encoding ("the replay path compares payloads")
— and a canary that invented its own encoding would be asserting identity in
a spelling nothing else in the system reads. The pin here is the *check*,
not the bytes.

**The verdict is a value; the refusal is opt-in.**
"Returns a byte-level comparison result" is the feature's own clause, so
:func:`compare_runs` returns a :class:`ByteComparison` and does not raise for
a divergence — the same split the contract draws between "what is a
conforming return" and "what happens to a non-conforming one". A caller
assembling a nightly report wants the verdict for *every* field it checked,
so a check that raised on the first divergence would have to be caught and
re-entered to learn the rest, and the comparison would stop being a record.
:func:`require_identical` — and :func:`assert_bit_identical`, the one-line
spelling over a signal and a seed — is the raising form for the caller for
whom a divergence is a stop: §15's "Replay non-determinism → Halt dreaming;
bisect the image diff" is a caller that wants the exception. Both spellings
run the same comparison and return the same value when it passes; neither is
a different assertion.

**A broken signal is not a determinism verdict.**
If the signal raises, the exception propagates untouched — the same stance
:mod:`contract.signal` takes when it compiles an agent's source ("Raises the
compilation error verbatim ... rather than being wrapped into something a
caller has to unwrap"). A signal that cannot run at all has not told this
check anything about determinism, and reporting it as a divergence would
blame the machine for the signal's bug. The narrow exception is a run that
*returns* something the comparison cannot mean — a ``str``, a list, a
``polars.Series`` nobody serialized — because there the canary was handed a
value it cannot compare bytes over, and that is a
:class:`~canary.CanaryReproducibilityError` naming the type and the remedy
rather than a ``TypeError`` from somewhere inside the scan.

**The layering note.** Stdlib-only — :mod:`hashlib`, a dataclass and a loop
— with no polars, no pyarrow, no lake, no environment and no numerics, so
importing this member on every factory scan (including the replay path §1
keeps away from anything that could perturb it) still costs composition
nothing. :class:`~canary.CanaryService` answers a different question ("is this
deployment pinned?", feature 135) and is deliberately left alone: this check
is about an *output*, so it is not a second verb on that service and does not
become a property of a pinned deployment. It is instead carried by
:class:`BitReproducibility`, the stateless facade the composed component
holds beside the pin sweep — mirroring what the tripwires member does for its
own pure-function probe and what the evaluator does for features 70+ — so the
check is *discoverable* through the application factory's scan rather than
only through an import. Both spellings reach the same functions, so nothing
is duplicated by having them: a caller may equally write
``from canary import assert_bit_identical``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from ._errors import CanaryReproducibilityError

__all__ = [
    "BitReproducibility",
    "ByteComparison",
    "SeededSignal",
    "assert_bit_identical",
    "compare_bytes",
    "compare_runs",
    "require_identical",
]

#: The shape a seeded signal must have for this check: one integer seed in,
#: the run's output bytes out. The caller binds everything else — the window,
#: the payload, the serialization, and whether the run happens here or in
#: another interpreter — so the only thing the two runs are allowed to vary
#: in is nothing at all. See the module docstring.
SeededSignal = Callable[[int], bytes]

#: The field name a comparison carries when the caller did not name one. The
#: feature's word is "output"; kept as a constant because it is the word a
#: verdict's message leads with, and a caller filing several verdicts in one
#: report needs the default to be one spelling rather than a literal each
#: call site repeats.
DEFAULT_FIELD = "output"

#: Length of a content digest — a sha256 hex string, matching the width every
#: ``CHAR(64)`` provenance column carries. Deliberately not spelled with the
#: ``sha256:`` prefix the image pins use: that prefix belongs to an image
#: *reference* (see ``_image``), and a digest of run output is a content hash
#: of the same family the snapshot member's ``sha256_file`` returns —
#: lowercase hex, no algorithm tag. The two vocabularies stay apart so a
#: report cannot show a run digest where an image digest belongs.
_DIGEST_HEX_LENGTH = 64

_HEX = frozenset("0123456789abcdef")


def _digest(data: bytes) -> str:
    """The lowercase hex sha256 of one run's bytes.

    The one place a run's identity is computed, so the passing path (which
    reports the shared digest) and the failing path (which reports both)
    cannot disagree about what "the same bytes" hashes to. Bare hex rather
    than ``sha256:<hex>`` — see the module's note on the two digest
    vocabularies.
    """
    return hashlib.sha256(data).hexdigest()


def _require_bytes(value: object, *, run: str, field: str) -> bytes:
    """Refuse a run whose output is not bytes, naming the type it is.

    A comparison over bytes needs bytes, so a run that returned a ``str``, a
    list or an un-serialized ``polars.Series`` is a *caller* error — the
    comparison is undefined, not false — and the message says which of the
    two runs and what it got, so the caller learns where to serialize rather
    than reading a ``TypeError`` raised inside the scan. ``bytes`` only:
    a ``bytearray`` or ``memoryview`` is converted by the caller in one call,
    which keeps "the unit of this comparison" stated at the call site rather
    than inferred from whatever a run happened to hand back.
    """
    if not isinstance(value, bytes):
        raise CanaryReproducibilityError(
            f"the {run} of the {field!r} signal returned "
            f"{type(value).__name__}, not bytes: a bit-identical assertion "
            "compares the runs' output bytes, so the run must hand over the "
            "serialized form. Serialize at the layer that already owns the "
            "encoding — the sandbox's Arrow IPC channel, the artifact "
            "renderer, the feature store's payload — and pass "
            "``bytes(...)`` if you hold a bytearray or memoryview"
        )
    return value


def _require_seed(seed: object) -> int:
    """Refuse a seed that is not a plain integer.

    Booleans are refused explicitly because ``isinstance(True, int)``: a seed
    of ``True`` is a broken caller, not a seed of 1, and the whole point of
    this check is that the *seed* is the run's only source of randomness
    (feature 11 pins it as a required integer argument) — so a seed that is
    not an integer makes the assertion meaningless rather than wrong.
    Negatives are accepted: nothing in the system assigns seeds by index, and
    Python's own ``random.seed`` takes them.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise CanaryReproducibilityError(
            f"a seeded signal's seed must be an integer, got "
            f"{type(seed).__name__}; the seed is the run's only source of "
            "randomness (feature 11), so two runs under a seed that is not "
            "an integer are not two runs of the same seeded signal"
        )
    return seed


def _require_field(field: object) -> str:
    """Refuse a field name that cannot be named in a verdict.

    Same argument the pin sweep makes for a role: the field is the word a
    comparison's message leads with and the word a report files a verdict
    under, so a field that is not a non-empty string is a verdict that
    cannot say what it compared.
    """
    if not isinstance(field, str) or not field.strip():
        raise CanaryReproducibilityError(
            f"a comparison's field must be a non-empty string, got {field!r}; "
            "the field is the word the verdict names what it compared, so a "
            "field that cannot be named cannot be reported"
        )
    return field


@dataclass(frozen=True)
class ByteComparison:
    """The byte-level result of comparing two runs of one seeded signal.

    Feature 145's "byte-level comparison result", as a value: whether the two
    runs agreed, the sha256 of each, both lengths, and — when they did not
    agree — the offset of the first differing byte and how many positions
    differ in all. Frozen and hashable, so a verdict can be filed, compared
    across checks without recomputing, or carried beside the score it
    certifies.

    The fields exist to make a divergence *actionable* rather than merely
    loud, which is §15's demand on this failure: its recovery is "halt
    dreaming; bisect the image diff", and bisecting needs to know what kind
    of divergence it is looking at. The two digests answer "same bytes?"
    exactly; the lengths answer "did the run produce a different result set"
    (a length that moved is not a rounding difference); the first differing
    offset answers "one float, or everything from here on"; and
    :attr:`differing_bytes` answers "a low bit of one value, or the whole
    panel". A divergence at offset 7 with one differing byte is a
    reassociated reduction; a divergence at offset 24 with every byte
    differing is a different computation wearing the same name, and the two
    want opposite responses.

    **The length is not the comparison, and the digest is not either.** The
    verdict is :attr:`identical`, computed by comparing the bytes themselves;
    the digests are carried for reporting and could not have produced the
    verdict on their own (a caller comparing digests has already computed
    them, and would learn *that* two runs differ without learning *where*).
    Both are stated here so a reader can tell a check that ran from a check
    that was summarized: this record is only ever built by
    :func:`compare_bytes`, over bytes it held.

    Attributes
    ----------
    field:
        What was compared — ``"output"`` unless the caller named something
        narrower, so a report over several fields can file each verdict.
    identical:
        The verdict: the two runs' bytes were equal, element for element.
    left_digest / right_digest:
        The lowercase hex sha256 of each run. Equal exactly when
        :attr:`identical` is true.
    left_length / right_length:
        The byte length of each run — the field that separates "the same
        result, slightly different bits" from "a different result".
    first_difference:
        The offset of the first position at which the runs differ, or
        ``None`` when they are identical. When one run is a strict prefix of
        the other this is the first position past the shorter run — the place
        the missing bytes would have been.
    differing_bytes:
        How many positions differ, counting positions present in only one run
        when the lengths differ. ``0`` exactly when :attr:`identical`.
    seed:
        The seed both runs were executed under, when the caller knew it. It
        is not a term of the comparison — the comparison is over bytes — and
        it is carried because a verdict nobody can tie back to a seed is a
        verdict about nothing in particular.
    """

    field: str
    identical: bool
    left_digest: str
    right_digest: str
    left_length: int
    right_length: int
    first_difference: int | None
    differing_bytes: int
    seed: int | None = None

    def __post_init__(self) -> None:
        # A verdict is a statement about bytes some path actually held, so
        # every field is checked against the others before the value exists.
        # The alternative — trusting the constructor — is a record that can
        # say "identical" while carrying two different digests, which is
        # precisely the shape of a report nobody can act on: §12's whole
        # point is that non-determinism "does not announce itself", and a
        # self-contradicting verdict would announce the wrong thing.
        _require_field(self.field)
        for name in ("left_digest", "right_digest"):
            digest = getattr(self, name)
            if (
                not isinstance(digest, str)
                or len(digest) != _DIGEST_HEX_LENGTH
                or not set(digest) <= _HEX
            ):
                raise CanaryReproducibilityError(
                    f"a comparison's {name} must be {_DIGEST_HEX_LENGTH} "
                    f"lowercase hex characters, got {digest!r}; the digest "
                    "names the bytes a run produced, so a value that is not "
                    "one names no run"
                )
        for name in ("left_length", "right_length"):
            length = getattr(self, name)
            if isinstance(length, bool) or not isinstance(length, int) or length < 0:
                raise CanaryReproducibilityError(
                    f"a comparison's {name} must be a non-negative integer, "
                    f"got {length!r}; a run's length in bytes is never "
                    "negative"
                )
        if isinstance(self.differing_bytes, bool) or not isinstance(
            self.differing_bytes, int
        ):
            raise CanaryReproducibilityError(
                "a comparison's differing_bytes must be an integer, got "
                f"{self.differing_bytes!r}"
            )
        if self.identical:
            if self.left_digest != self.right_digest:
                raise CanaryReproducibilityError(
                    "a comparison cannot report bit-identical runs whose "
                    f"digests differ ({self.left_digest} vs "
                    f"{self.right_digest}): equal bytes hash equally, so a "
                    "verdict carrying two digests is a record that would "
                    "lie to the operator reading it"
                )
            if self.first_difference is not None or self.differing_bytes != 0:
                raise CanaryReproducibilityError(
                    "a comparison cannot report bit-identical runs while "
                    f"naming a first difference at {self.first_difference!r} "
                    f"and {self.differing_bytes} differing byte(s)"
                )
        else:
            if self.left_digest == self.right_digest:
                raise CanaryReproducibilityError(
                    "a comparison cannot report a divergence between runs "
                    f"that hash equally ({self.left_digest}): the digest is "
                    "the same value, so either the bytes were equal or one "
                    "of the two was not hashed as it was compared"
                )
            if self.first_difference is None or self.differing_bytes < 1:
                raise CanaryReproducibilityError(
                    "a comparison that reports a divergence must name where "
                    "it starts and how much differs, got "
                    f"first_difference={self.first_difference!r} and "
                    f"differing_bytes={self.differing_bytes}"
                )

    @property
    def ok(self) -> bool:
        """The verdict under the spelling the rest of the workspace uses.

        :class:`~evaluator.SandboxResult` says ``ok``, the contract's
        compatibility record says ``compatible``; this is ``identical`` under
        the name a caller reaching for "did the check pass" will try first,
        so neither spelling has to be looked up.
        """
        return self.identical

    @property
    def message(self) -> str:
        """One human-readable sentence: the verdict, and what it rests on.

        Composed rather than stored, because every part of it is already a
        field — a stored copy would be a second place for the verdict's
        wording to live, and a record edited after the fact would then
        disagree with its own message. A passing verdict names the shared
        digest and the length (what was asserted and over how much); a
        failing one names both digests, both lengths, the offset and the
        count, and points at §15's recovery, because the operator reading it
        is deciding whether to re-pin an image or halt a night's dreaming.
        """
        seed = "seed not recorded" if self.seed is None else f"seed {self.seed}"
        if self.identical:
            return (
                f"the runs of the {self.field!r} signal are bit-identical "
                f"({seed}): {self.left_length} byte(s), sha256 "
                f"{self.left_digest}"
            )
        return (
            f"the runs of the {self.field!r} signal are not bit-identical "
            f"({seed}): run 1 produced {self.left_length} byte(s) with "
            f"sha256 {self.left_digest}, run 2 produced "
            f"{self.right_length} byte(s) with sha256 {self.right_digest}; "
            f"they first differ at byte offset {self.first_difference} and "
            f"{self.differing_bytes} position(s) differ in all. "
            "Non-determinism does not announce itself — it slowly makes every "
            "conclusion wrong (architecture §12) — so this is §15's "
            "'Replay non-determinism' failure: halt dreaming and bisect the "
            "image diff rather than re-running until the two sides happen to "
            "agree"
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        state = "identical" if self.identical else "divergent"
        return (
            f"ByteComparison(field={self.field!r}, {state}, "
            f"left={self.left_length}B, right={self.right_length}B, "
            f"first_difference={self.first_difference!r})"
        )


def compare_bytes(
    left: bytes,
    right: bytes,
    *,
    field: str = DEFAULT_FIELD,
    seed: int | None = None,
) -> ByteComparison:
    """Compare two runs' output bytes, byte for byte.

    The whole comparison, over bytes the caller already holds: the verdict is
    ``left == right`` element for element, and the scan that follows a
    divergence is one pass to find the first offset that differs and count
    the rest. It is a pure function of its two arguments — no environment, no
    clock, no encoding, no tolerance — so a caller holding two persisted
    payloads (a recorded run and a replayed one) compares them exactly as
    :func:`compare_runs` compares two fresh ones, and neither path can
    disagree with the other about what "identical" means.

    The scan runs only after a divergence, and this matters more than it
    looks: the passing path — a nightly canary on a healthy deployment —
    costs one ``memcmp``, while the offset-and-count work is paid on the
    night the answer is already "no". A comparison that walked the bytes
    eagerly would put an O(n) Python loop on every green run to serve a red
    one that is by definition rare, and §12 calls this "the cheapest
    high-value test in the system".
    """
    field = _require_field(field)
    left_bytes = _require_bytes(left, run="first run", field=field)
    right_bytes = _require_bytes(right, run="second run", field=field)
    if seed is not None:
        _require_seed(seed)

    left_digest = _digest(left_bytes)
    right_digest = _digest(right_bytes)
    # The C-level comparison decides the verdict; the digest is reporting,
    # never the test — two different byte strings cannot collide on sha256,
    # but a verdict read off a digest would be a verdict about the hash
    # rather than about the bytes the feature names.
    if left_bytes == right_bytes:
        return ByteComparison(
            field=field,
            identical=True,
            left_digest=left_digest,
            right_digest=right_digest,
            left_length=len(left_bytes),
            right_length=len(right_bytes),
            first_difference=None,
            differing_bytes=0,
            seed=seed,
        )

    first_difference: int | None = None
    differing_bytes = 0
    for index, (left_byte, right_byte) in enumerate(zip(left_bytes, right_bytes)):
        if left_byte != right_byte:
            differing_bytes += 1
            if first_difference is None:
                first_difference = index
    if len(left_bytes) != len(right_bytes):
        # Every position past the shorter run differs by absence. When the
        # shorter run is a strict prefix of the longer one this is also the
        # first difference — the place the missing bytes would have been.
        differing_bytes += abs(len(left_bytes) - len(right_bytes))
        if first_difference is None:
            first_difference = min(len(left_bytes), len(right_bytes))
    assert first_difference is not None  # equal lengths and no diff is impossible here

    return ByteComparison(
        field=field,
        identical=False,
        left_digest=left_digest,
        right_digest=right_digest,
        left_length=len(left_bytes),
        right_length=len(right_bytes),
        first_difference=first_difference,
        differing_bytes=differing_bytes,
        seed=seed,
    )


def compare_runs(
    signal: SeededSignal,
    seed: int,
    *,
    field: str = DEFAULT_FIELD,
) -> ByteComparison:
    """Run a seeded signal twice and compare the two runs' output bytes.

    Feature 145's sentence, executed: "two runs of the same seeded signal",
    the *same* seed handed to both, the two outputs compared byte for byte.
    The signal is called twice with one identical argument, so a non-empty
    difference between the runs can only have come from the signal — from a
    clock it read, a source of randomness it did not take from its seed, a
    global it mutated, or a reduction whose order was not fixed. That is the
    feature's whole power: the two runs are separated by nothing, so anything
    they disagree about is non-determinism by construction.

    The callable seam is where the strength of the check is chosen (see the
    module docstring): the default reading is two calls in this process, and
    a caller that wants the second run in a second interpreter hands in a
    callable that spawns one. Nothing here inspects, resets or re-seeds
    anything between the calls — a check that tidied up after the first run
    would be testing a signal nobody runs.

    A signal that raises propagates its own exception: a run that could not
    execute has said nothing about determinism, and wrapping it would report
    the machine's fault for the signal's bug. A signal that *returns*
    non-bytes is refused by :func:`compare_bytes` with the type named.
    """
    field = _require_field(field)
    seed = _require_seed(seed)
    if not callable(signal):
        raise CanaryReproducibilityError(
            f"a seeded signal must be callable, got {type(signal).__name__}; "
            "the check runs it twice with one seed, so it needs the run "
            "itself, not its output"
        )
    # Two calls, one argument, no state touched in between. The order is the
    # feature's: the first run is the one a report calls "run 1".
    first = _require_bytes(signal(seed), run="first run", field=field)
    second = _require_bytes(signal(seed), run="second run", field=field)
    return compare_bytes(first, second, field=field, seed=seed)


def require_identical(comparison: ByteComparison) -> ByteComparison:
    """Return ``comparison`` when the runs agreed, else raise.

    The strict half of the pair, for the caller where a divergence is a stop
    rather than a datum — §15's "Halt dreaming; bisect the image diff", a
    promotion gate, a health check. Returns the *verdict* rather than a bare
    ``None`` so the raising spelling and the returning spelling chain the
    same value: a caller can assert and still hold the digest, the lengths
    and the seed for its record.

    A non-verdict argument is a caller error: there is nothing to assert
    about a value that never compared anything, and reporting it as a
    divergence would put a broken call site in the same class as a broken
    run.
    """
    if not isinstance(comparison, ByteComparison):
        raise CanaryReproducibilityError(
            "require_identical asserts a ByteComparison, got "
            f"{type(comparison).__name__}; the verdict is what a comparison "
            "returns, so a caller holding something else has not compared "
            "anything yet"
        )
    if not comparison.identical:
        raise CanaryReproducibilityError(comparison.message)
    return comparison


def assert_bit_identical(
    signal: SeededSignal,
    seed: int,
    *,
    field: str = DEFAULT_FIELD,
) -> ByteComparison:
    """Assert that two runs of one seeded signal are bit-identical.

    The one-line form a nightly runner, a replay guard or a test reaches for:
    run the signal twice under ``seed``, compare the bytes, and raise
    :class:`~canary.CanaryReproducibilityError` on a divergence — carrying
    the digests, the lengths, the first differing offset and the count, which
    is what §15's "bisect the image diff" recovery needs to start from.
    Returns the (passing) :class:`ByteComparison` when the runs agree, so the
    caller that wants the digest for its record does not run the check twice.

    Deliberately a different *spelling*, not a different assertion:
    :func:`compare_runs` is the same comparison with the verdict left as a
    value, which is what a caller filing one line per field in a nightly
    report wants.
    """
    return require_identical(compare_runs(signal, seed, field=field))


class BitReproducibility:
    """Feature 145's check, as the value a composed application carries.

    A stateless facade over the four functions above, so a caller holding the
    composed canary component can reach the check without importing this
    member's submodules by name — the same role
    :class:`~tripwires.TimeShuffleTripwire` plays for the leakage probe and
    the evaluator's service plays for features 70+.  The class carries no
    state: ``__slots__`` is empty and it defines no ``__init__``, which is the
    honest shape for a check that is a pure function of its inputs and reads
    nothing from the environment.  There is no seed, no window and no
    serialization to configure here — every one of those is an argument to the
    call that uses it — so two callers comparing two candidates can never
    observe each other, and there is nothing a deployment could mis-set.

    The delegation is deliberately *thin* — each method is one call to the
    function that owns the comparison — because a second implementation of the
    byte scan is exactly what this package's one-provenance rule forbids.  What
    this class adds is discoverability (the factory's scan composes it) and a
    single duck-checkable seam (``assert_identical``/``run``/``bytes``) for the
    app seat and the features that follow, not arithmetic.
    """

    __slots__ = ()

    def assert_identical(
        self,
        signal: SeededSignal,
        seed: int,
        *,
        field: str = DEFAULT_FIELD,
    ) -> ByteComparison:
        """Assert two runs of ``signal`` under ``seed`` are bit-identical.

        Feature 145's whole sentence, through the composed component: run it
        twice, compare the bytes, raise
        :class:`~canary.CanaryReproducibilityError` on a divergence.  Same
        function, same verdict, same refusal as
        :func:`assert_bit_identical` — a caller reaching the check through
        the composed application and one importing the member agree by
        construction.
        """
        return assert_bit_identical(signal, seed, field=field)

    def run(
        self,
        signal: SeededSignal,
        seed: int,
        *,
        field: str = DEFAULT_FIELD,
    ) -> ByteComparison:
        """Run the signal twice and *return* the byte comparison — no refusal.

        The non-raising spelling, for a caller filing one verdict per field
        in a nightly report: a divergence is a value it records rather than an
        exception that stops it collecting the rest.
        """
        return compare_runs(signal, seed, field=field)

    def bytes(
        self,
        left: bytes,
        right: bytes,
        *,
        field: str = DEFAULT_FIELD,
        seed: int | None = None,
    ) -> ByteComparison:
        """Compare two payloads the caller already holds.

        Exposed on the component because the caller that most needs a
        bit-identity verdict is holding an *already-materialized* pair — a
        recorded run and a replayed one, two persisted payloads read back
        from the artifact store — not a signal to run twice.  Same function
        the fresh-run path funnels through, so a recorded-vs-replayed verdict
        and a fresh-vs-fresh one cannot disagree about what "identical"
        means.
        """
        return compare_bytes(left, right, field=field, seed=seed)
