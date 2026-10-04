"""The token-budget wrapper — feature 7's ceiling on a provider's own spend.

These tests drive :class:`BudgetedProvider` over a :class:`ScriptedProvider`
and assert it is a meter, not a filter: it forwards and counts, refuses the
*next* call once either running total has reached its ceiling, and never
reaches the wrapped provider once it has refused.
"""

from __future__ import annotations

import pytest
from providers import (
    BatchRequest,
    CompletionMalformedError,
    NotImplementedBatchError,
    Provider,
    ProviderError,
    UnknownModelError,
)
from providers._budget import (
    BUDGET_EXHAUSTED_CODE,
    BudgetedProvider,
    BudgetExhaustedError,
)


def test_budget_is_itself_a_provider(scripted_provider, make_completion):
    # Drop-in for what it wraps, on RecordingProvider's own design: a caller
    # holding the interface cannot tell the budget from the provider under it.
    budget = BudgetedProvider(
        scripted_provider(lambda request: make_completion()),
        max_input_tokens=100,
        max_output_tokens=100,
    )
    assert isinstance(budget, Provider)


def test_spent_starts_at_zero(scripted_provider, make_completion):
    budget = BudgetedProvider(
        scripted_provider(lambda request: make_completion()),
        max_input_tokens=100,
        max_output_tokens=100,
    )
    assert budget.spent() == (0, 0)


def test_a_call_under_budget_is_answered_and_counted(
    scripted_provider, make_completion, make_request
):
    inner = scripted_provider(
        lambda request: make_completion(input_tokens=10, output_tokens=5)
    )
    budget = BudgetedProvider(inner, max_input_tokens=100, max_output_tokens=100)

    result = budget.complete(make_request())

    assert result.content == "answer"
    assert budget.spent() == (10, 5)


def test_spent_accumulates_across_calls(scripted_provider, make_completion, make_request):
    inner = scripted_provider(
        lambda request: make_completion(input_tokens=10, output_tokens=5)
    )
    budget = BudgetedProvider(inner, max_input_tokens=100, max_output_tokens=100)

    budget.complete(make_request())
    budget.complete(make_request())

    assert budget.spent() == (20, 10)


def test_a_zero_ceiling_refuses_the_first_call(
    scripted_provider, make_completion, make_request
):
    calls: list[object] = []
    inner = scripted_provider(lambda request: (calls.append(request), make_completion())[1])
    budget = BudgetedProvider(inner, max_input_tokens=0, max_output_tokens=100)

    with pytest.raises(BudgetExhaustedError):
        budget.complete(make_request())

    # Nothing was sent: the refusal fires before the wrapped provider runs.
    assert calls == []
    assert budget.spent() == (0, 0)


def test_either_ceiling_at_zero_refuses(scripted_provider, make_completion, make_request):
    # The ceiling of zero on the *output* side is enough to refuse, even
    # though the input ceiling is untouched.
    inner = scripted_provider(lambda request: make_completion())
    budget = BudgetedProvider(inner, max_input_tokens=100, max_output_tokens=0)

    with pytest.raises(BudgetExhaustedError):
        budget.complete(make_request())


def test_a_call_that_crosses_the_ceiling_is_answered_and_counted_in_full(
    scripted_provider, make_completion, make_request
):
    inner = scripted_provider(
        lambda request: make_completion(input_tokens=80, output_tokens=5)
    )
    budget = BudgetedProvider(inner, max_input_tokens=50, max_output_tokens=100)

    # 80 input tokens crosses the 50-token ceiling outright, but the call is
    # still answered and its usage is still counted in full.
    first = budget.complete(make_request())
    assert first.content == "answer"
    assert budget.spent() == (80, 5)


def test_the_refusal_starts_with_the_call_after_the_one_that_crossed_the_ceiling(
    scripted_provider, make_completion, make_request
):
    calls: list[object] = []

    def respond(request):
        calls.append(request)
        return make_completion(input_tokens=80, output_tokens=5)

    inner = scripted_provider(respond)
    budget = BudgetedProvider(inner, max_input_tokens=50, max_output_tokens=100)

    budget.complete(make_request())
    assert len(calls) == 1

    with pytest.raises(BudgetExhaustedError):
        budget.complete(make_request())

    # The second call never reached the wrapped provider.
    assert len(calls) == 1
    # And the failed call added nothing further to the total.
    assert budget.spent() == (80, 5)


def test_the_refusal_names_both_totals_and_both_ceilings(
    scripted_provider, make_completion, make_request
):
    inner = scripted_provider(
        lambda request: make_completion(input_tokens=120, output_tokens=40)
    )
    budget = BudgetedProvider(inner, max_input_tokens=100, max_output_tokens=100)
    budget.complete(make_request())

    with pytest.raises(BudgetExhaustedError) as refusal:
        budget.complete(make_request())

    message = str(refusal.value)
    assert message.startswith(f"{BUDGET_EXHAUSTED_CODE}: ")
    assert "120" in message  # the input total
    assert "40" in message  # the output total
    assert message.count("100") == 2  # both ceilings


def test_the_refusal_carries_its_own_code(scripted_provider, make_completion, make_request):
    inner = scripted_provider(lambda request: make_completion())
    budget = BudgetedProvider(inner, max_input_tokens=0, max_output_tokens=0)

    with pytest.raises(BudgetExhaustedError) as refusal:
        budget.complete(make_request())

    assert refusal.value.code == BUDGET_EXHAUSTED_CODE == "budget_exhausted"


def test_check_model_delegates_to_the_inner_provider(
    scripted_provider, make_completion, make_request
):
    inner = scripted_provider(lambda request: make_completion(), models={"allowed"})
    budget = BudgetedProvider(inner, max_input_tokens=100, max_output_tokens=100)

    assert budget.check_model("allowed") == "allowed"
    with pytest.raises(UnknownModelError):
        budget.check_model("not-allowed")
    with pytest.raises(UnknownModelError):
        budget.complete(make_request(model="not-allowed"))


def test_batches_are_refused_by_the_base_classs_not_implemented_error(
    scripted_provider, make_completion, make_request
):
    inner = scripted_provider(lambda request: make_completion())
    budget = BudgetedProvider(inner, max_input_tokens=100, max_output_tokens=100)

    with pytest.raises(NotImplementedBatchError):
        budget.complete_batch(BatchRequest(requests=(make_request(),)))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_input_tokens": -1},
        {"max_output_tokens": -1},
        {"max_input_tokens": 1.5},
        {"max_output_tokens": "100"},
        {"max_input_tokens": True},
        {"max_output_tokens": False},
        {"max_input_tokens": None},
    ],
)
def test_a_malformed_ceiling_raises_value_error_at_construction(
    kwargs, scripted_provider, make_completion
):
    inner = scripted_provider(lambda request: make_completion())
    full = {"max_input_tokens": 100, "max_output_tokens": 100}
    full.update(kwargs)
    with pytest.raises(ValueError):
        BudgetedProvider(inner, **full)


def test_a_malformed_ceiling_is_refused_before_a_provider_error(scripted_provider, make_completion):
    # A ValueError, never a ProviderError: a malformed ceiling never got well
    # enough formed to be a provider-contract question at all.
    inner = scripted_provider(lambda request: make_completion())
    with pytest.raises(ValueError) as refusal:
        BudgetedProvider(inner, max_input_tokens=-1, max_output_tokens=100)
    assert not isinstance(refusal.value, ProviderError)


def test_budget_refuses_a_non_provider():
    with pytest.raises(ProviderError):
        BudgetedProvider("not a provider", max_input_tokens=100, max_output_tokens=100)  # type: ignore[arg-type]


def test_budget_exhausted_error_is_a_provider_error():
    assert issubclass(BudgetExhaustedError, ProviderError)


def test_a_call_that_raised_is_not_counted(make_request):
    class Raising(Provider):
        def _complete(self, request):
            raise CompletionMalformedError("boom")

    budget = BudgetedProvider(Raising(), max_input_tokens=100, max_output_tokens=100)

    with pytest.raises(CompletionMalformedError):
        budget.complete(make_request())

    assert budget.spent() == (0, 0)


def test_a_total_exactly_at_the_ceiling_refuses_the_next_call_one_token_under_does_not(
    scripted_provider, make_completion, make_request
):
    # "Has reached" means >=, pinned on both sides of the boundary: a total
    # one token under the ceiling still has headroom, and a total exactly at
    # it does not.
    inner = scripted_provider(
        lambda request: make_completion(input_tokens=99, output_tokens=0)
    )
    budget = BudgetedProvider(inner, max_input_tokens=100, max_output_tokens=100)
    budget.complete(make_request())
    assert budget.spent() == (99, 0)
    budget.complete(make_request())  # 99 + 99 >= 100, but this call still had headroom
    assert budget.spent() == (198, 0)

    with pytest.raises(BudgetExhaustedError):
        budget.complete(make_request())
