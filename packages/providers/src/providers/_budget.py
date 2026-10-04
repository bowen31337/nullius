"""The token-budget wrapper — feature 7's ceiling on a provider's own spend.

A deployment that calls a live provider (features 2 and 3) is spending real
money per token, and the one thing every one of those calls shares is that
none of them knows what the campaign has already spent — each completes its
own request and returns, with no view of the running total.  This module is
the seam that keeps that total: :class:`BudgetedProvider` wraps any
:class:`~providers.Provider` and adds each answered completion's usage to two
running counts, so a caller that wants a hard ceiling on a campaign's spend
gets one by construction rather than by remembering to check
:class:`~providers.Completion` after every call.

The wrapper is a :class:`~providers.Provider`, on the same design
:class:`~providers.RecordingProvider` uses for the same reason: it is drop-in
for whatever it wraps, because it *is* a provider, so a caller holding the
interface cannot tell the budget from the provider underneath.  Where the
recorder's side effect is keeping an exchange, this wrapper's side effect is
counting one — and refusing the call that would be made once counting says
the ceiling is already reached.

**The refusal is a guard on the *next* call, not a cap on the current one.**
A ceiling bounds what the budget will *let through*, not what any single
answered call may cost: a request that returns more tokens than the headroom
left is still answered in full and its usage is still added to the total —
the ceiling cannot shrink an answer the inner provider already gave — and the
refusal begins with the call that follows, the first one asked with the
ceiling already spent.  :meth:`spent` lets a caller read the two running
totals without triggering either effect, the same read-only accessor
:class:`~providers.RecordingProvider` gives its own kept state.

**The refusal fires before the inner provider is reached, so nothing is
sent.**  :meth:`BudgetedProvider._complete` checks both totals against both
ceilings first and raises :class:`BudgetExhaustedError` there, never calling
:attr:`_inner` at all once either total has reached its ceiling — the same
"refuse before the transport" discipline :mod:`providers._depth` applies
before a call is placed and :mod:`providers._live_http` applies before a
socket opens.  A ceiling of zero is therefore not a special case: it refuses
the first call precisely because zero spent already equals a zero ceiling.

:class:`BudgetExhaustedError` subclasses :class:`~providers.ProviderError`
directly, on this package's own convention (every new error class lives in
the module that raises it and joins the interface's one base): a budget that
refuses a call has not pinned a node and has not mis-selected a depth model,
it is "the provider contract could not be completed this time", exactly the
question :class:`~providers.ProviderError` exists to answer.  Its message
opens with :data:`BUDGET_EXHAUSTED_CODE` — the greppable ``budget_exhausted``
token, on the precedent :mod:`providers._recorded_errors` sets for
``fixture_missing`` — and names all four numbers a caller needs to act on it:
both running totals and both ceilings.

A malformed ceiling, by contrast, raises a bare :class:`ValueError` at
construction rather than a package error: a negative or non-int ceiling is
not a call that the provider contract refused, it is a budget that was never
well-formed enough to enforce anything, and the bool exclusion follows this
package's own rule for every other counted field (:mod:`providers._completion`,
:mod:`providers._depth`) — ``True`` is an ``int`` in Python, and a config
layer handing one over by accident must not be read as a one-token ceiling.

:meth:`check_model` delegates to the wrapped provider rather than accepting
any model: a budget around a provider that pins a served set must refuse the
same models that provider refuses, or a caller holding the budget would see a
looser contract than the one it wrapped.  The batch half of the interface is
untouched — this wrapper implements no ``_complete_batch``, so a batched call
meets the base class's own :class:`~providers.NotImplementedBatchError`
exactly as it would against the bare provider underneath.

The totals are process memory, one running pair per instance, and nothing
here writes them anywhere: a deployment that wants a campaign's spend to
survive past one process is a later spec, the way feature 200's cache rate
and feature 202's run window each persist through their own store once that
need is specified. This module adds no store, because a budget this spec
describes is a ceiling on *this* object's calls, not yet a fact the tree
remembers.
"""

from __future__ import annotations

from typing import Final

from ._completion import Completion
from ._errors import ProviderError
from ._provider import Provider
from ._request import Request

__all__ = ["BUDGET_EXHAUSTED_CODE", "BudgetExhaustedError", "BudgetedProvider"]

#: The greppable code a :class:`BudgetExhaustedError` opens with — the token
#: an operator or a CI check scans a campaign log for, on the precedent
#: :data:`providers.FIXTURE_MISSING_CODE` sets for its own refusal.  Kept
#: beside the error it identifies so the token and the type are one edit.
BUDGET_EXHAUSTED_CODE: Final[str] = "budget_exhausted"


class BudgetExhaustedError(ProviderError):
    """A call was refused because the wrapped provider's token budget is spent.

    Raised by :class:`BudgetedProvider` before its wrapped provider is ever
    reached, once either running total (input or output tokens) has reached
    its ceiling — so the refusal is the last thing that happens on this
    budget's behalf, not a failure partway through a call.  A
    :class:`~providers.ProviderError` directly, never a second base: refusing
    a call for lack of budget is a failure of "the provider contract could not
    be completed this time", the same question every other refusal under that
    base answers, so a caller catching :class:`~providers.ProviderError`
    catches this alongside a malformed completion or a missing provider.

    The message opens with :data:`BUDGET_EXHAUSTED_CODE` and names all four
    numbers a caller needs to act on the refusal: both running totals and
    both ceilings they have met or crossed.
    """

    def __init__(self, message: str) -> None:
        # The code is prefixed here, at the type, so it cannot drift from the
        # constant that names it — the discipline
        # providers.FixtureNotFoundError states for its own code.
        super().__init__(f"{BUDGET_EXHAUSTED_CODE}: {message}")

    @property
    def code(self) -> str:
        """The refusal's greppable code — :data:`BUDGET_EXHAUSTED_CODE`."""
        return BUDGET_EXHAUSTED_CODE


def _require_ceiling(value: object, field: str) -> int:
    """Return ``value`` as a non-negative ceiling, refusing anything else.

    Shared by both of :class:`BudgetedProvider`'s constructor arguments,
    because they fail the same way and owe the caller the same explanation:
    a ceiling is a count of tokens, so it must be an ``int`` (excluding
    ``bool``, which is an ``int`` subclass in Python a config layer could
    hand over by accident) and it must not be negative — a ceiling below
    zero describes no budget any call could be measured against.  Zero
    itself is a legal ceiling: a deployment that wants to refuse every call
    states it, the same way :func:`providers.flat_pricing` lets a caller
    state a rate card's flat case rather than leaving a field unset.
    """
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(
            f"BudgetedProvider.{field} must be a non-negative int, got "
            f"{value!r} ({type(value).__name__}). A ceiling is a count of "
            f"tokens the running total is compared against; a value that is "
            f"not a non-negative count describes no budget a call could be "
            f"measured against."
        )
    return value


class BudgetedProvider(Provider):
    """A provider that refuses a call once its own running spend is exhausted.

    Wraps any :class:`~providers.Provider` and keeps two running totals —
    input tokens and output tokens — adding each answered completion's usage
    to them.  Drop-in for what it wraps, on
    :class:`~providers.RecordingProvider`'s own design: a caller holding the
    interface cannot tell the budget from the provider underneath, so a
    deployment slides it in front of a live backend to cap a campaign's spend
    without changing how the campaign calls it.

    Once either total has *reached* its ceiling, the next :meth:`complete`
    raises :class:`BudgetExhaustedError` before the wrapped provider is
    reached — nothing is sent.  A call made while headroom remains is
    answered and counted in full even when its usage crosses the ceiling
    outright: the ceiling bounds what is let through, not what a single
    answer may cost, so the refusal always begins with the call *after* the
    one that crossed it.  :meth:`spent` reads both totals without changing
    either.
    """

    def __init__(
        self,
        inner: Provider,
        *,
        max_input_tokens: int,
        max_output_tokens: int,
    ) -> None:
        # The wrapped provider is the thing whose spend is being bounded, held
        # by type for the reason providers.RecordingProvider's constructor
        # gives for its own: a budget around anything that is not a provider
        # has nothing to forward to, and would refuse every call it was
        # supposed to be metering rather than the one its ceiling names.
        if not isinstance(inner, Provider):
            raise ProviderError(
                f"a BudgetedProvider must wrap a Provider, got {inner!r} "
                f"({type(inner).__name__}). The budget meters a provider's "
                f"calls; something that is not a provider has no complete() "
                f"to forward through and no usage this wrapper could count."
            )
        self._inner = inner
        self._max_input_tokens = _require_ceiling(max_input_tokens, "max_input_tokens")
        self._max_output_tokens = _require_ceiling(
            max_output_tokens, "max_output_tokens"
        )
        self._input_tokens = 0
        self._output_tokens = 0

    def spent(self) -> tuple[int, int]:
        """The running totals so far: ``(input_tokens, output_tokens)``.

        Read-only — calling this never counts anything and never triggers
        the refusal, so a caller can check headroom before deciding whether
        to place another call.
        """
        return (self._input_tokens, self._output_tokens)

    def check_model(self, model: str) -> str:
        """Delegate to the wrapped provider's own served-model check.

        A budget around a provider that pins a served set must refuse the
        same models that provider refuses — accepting any model here would
        give a caller holding the budget a looser contract than the one it
        wrapped, the one thing a drop-in wrapper must never do.
        """
        return self._inner.check_model(model)

    def _complete(self, request: Request) -> Completion:
        # The ceiling check reads only the totals as they stood after the
        # last completed call, so it is the headroom decision for *this*
        # call: a call that previously crossed a ceiling is not revisited
        # here, it already raised nothing and was counted in full, and this
        # is where the refusal it earned actually lands.
        if (
            self._input_tokens >= self._max_input_tokens
            or self._output_tokens >= self._max_output_tokens
        ):
            raise BudgetExhaustedError(
                f"the token budget is exhausted: input tokens "
                f"{self._input_tokens:,} of {self._max_input_tokens:,} spent, "
                f"output tokens {self._output_tokens:,} of "
                f"{self._max_output_tokens:,} spent. A BudgetedProvider "
                f"refuses a call once either running total has reached its "
                f"ceiling, before its wrapped provider is ever reached, so "
                f"nothing more is sent once a campaign's budget runs out."
            )
        completion = self._inner.complete(request)
        # Counted only after the wrapped provider actually answers, so a call
        # that raised adds nothing to either total — the same "completed
        # round trips, not attempts" discipline providers.RecordingProvider
        # keeps its own record by.
        self._input_tokens += completion.usage.input_tokens
        self._output_tokens += completion.usage.output_tokens
        return completion
