"""Feature 113: POST /target's payload — the series and the opaque directive.

app_spec.xml, "Null Oracle & Planted Nulls", feature 113: *System returns a
target series plus a charges_budget directive from POST /target, never which
returns is_null in any form.*  docs/nullius-tech-architecture.md §7.2 spells
the rule the payload is built by::

    if is_null:
        return block_permute(forward_returns, seed=perm_seed, block=20d)
    else:
        return the real forward returns

and §7.2's interface line spells what may cross::

    response: { target_series, charges_budget }   # is_null NEVER appears

``test_target.py`` owns feature 112's two halves — the ask and the answer's
*status*.  This suite owns the third: the payload, and the fact that the bit
which produced it is not in it.

Four properties get their own sections because they are the ones a
plausible-looking implementation gets wrong:

* **the branch rule** — the sidecar's ``is_null`` selects the series, and
  selects it by the *stored* parameters: the permutation is called with the
  entry's own ``perm_seed`` and ``block_days``, so a campaign replayed from
  the same sealed file reproduces the same series (§12).  A route that drew
  a fresh seed per request would serve a *different* world on every ask, and
  the null would stop being a place;
* **the directive is ``not is_null``** — ``True`` exactly for a null node,
  because §8 debits no statistical budget for a signal that was never
  compared to real forward returns, and must therefore not inflate ``K`` in
  the deflation term.  §8's own writing discipline is the shape pinned here:
  *"the evaluator must set this flag without learning ``is_null``, so the
  null oracle returns it alongside the target series as an opaque budget
  directive, never as a label"*;
* **nothing else varies by branch** — the two answers for two nodes of the
  same shape are the same *shape*: same type, same field names, same branches
  taken inside the payload validators, and not one string anywhere on either
  that names the bit.  Feature 114's indistinguishable-response promise is a
  promise about the whole record, and the cheapest way to break it is a
  refusal message that says "this null node has no series";
* **the refusals are refusals, not answers** — a known node whose payload
  cannot be built raises :class:`nulloracle.TargetPayloadError` rather than
  answering 404 (which would deny a node the sidecar just answered for) or an
  empty series (which would measure the evaluation against nothing while §8
  charged it nothing either — a Type-B refund of a debt that was incurred).

The two collaborators §7.2's rule needs are injected, exactly as the
endpoint's docstring says they are: ``targets`` supplies the real forward
returns (pipeline step 4's alignment, feature 75's) and ``permute`` supplies
feature 115's mechanism.  The tests below supply their own stand-ins for both
so the assertions are about *which branch* and *with what parameters* — what
feature 115 does to a series is that feature's suite's to pin.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from types import MappingProxyType
from typing import Any

import pytest
from nulloracle import (
    NOT_FOUND,
    OK,
    NullAssignment,
    NullSidecar,
    TargetEndpoint,
    TargetPayloadError,
    TargetRequest,
    TargetResponse,
    TargetRouteError,
    block_indices,
)

# -- The world under test --------------------------------------------------------


#: The real forward returns pipeline step 4 aligned: a panel, two symbols on
#: five dates, so "did the permutation move the rows" is a question with a
#: visible answer and a single row could not be one.
DAYS = tuple(dt.date(2026, 1, 5) + dt.timedelta(days=i) for i in range(5))

SERIES: dict[dt.date, dict[str, float]] = {
    day: {"BTCUSDT": 0.01 * (index + 1), "ETHUSDT": -0.02 * (index + 1)}
    for index, day in enumerate(DAYS)
}


def _request(node_id: str, **overrides: Any) -> TargetRequest:
    """§7.2's ask for one node, with any term overridden.

    The span covers :data:`DAYS` with room on both sides, so a test that moves
    a date out of the window has to move it *out* rather than to the edge.
    """
    terms: dict[str, Any] = {
        "node_id": node_id,
        "campaign_id": str(uuid.uuid4()),
        "depth": 2,
        "horizon": 5,
        "symbols": ["ETHUSDT", "BTCUSDT"],
        "date_range": (dt.date(2026, 1, 1), dt.date(2026, 2, 20)),
    }
    terms.update(overrides)
    return TargetRequest(**terms)


def _targets(request: Any) -> dict:
    """The real series — pipeline step 4's supply, as a stand-in."""
    return {day: dict(row) for day, row in SERIES.items()}


def _permute(series: Any, *, seed: Any, block_days: Any) -> dict:
    """Feature 115's mechanism at the panel's grain — days are the blocks.

    The same reconciliation the composed route's own closure makes
    (``nulloracle._stored_permutation``): §7.2 writes the permutation over
    ``forward_returns``, which is one series, and the payload is a
    cross-section per rebalance date — so the blocks are runs of consecutive
    *dates*, each carrying its whole row.  The days are gathered through
    ``block_indices`` over positions, which is the form that module's own
    docstring names for a caller permuting something other than floats.

    Note the gather: the date at output slot ``i`` is ``days[i]`` and the row
    under it comes from input slot ``order[i]``.  A mapping holds no order, so
    a permuted *dict* is a rearrangement only if the rows land under
    different dates — gathering each date together with its own row would
    rebuild the identical series, and ``test_the_permutation_moves_rows_across_dates``
    below is the test that says so.
    """
    days = list(series)
    rows = [series[day] for day in days]
    order = block_indices(range(len(days)), seed=seed, block_days=block_days)
    return {
        days[position]: dict(rows[order[position]])
        for position in range(len(days))
    }


class _Recorder:
    """A ``permute`` seam that records how it was called and then delegates.

    The parameters a route passes the permutation are *the contract*: they
    must be the entry's own stored ``perm_seed`` and ``block_days``, not
    anything the route invented.  Delegating afterwards keeps every other
    assertion in a test about the served series rather than about the seam.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []

    def __call__(self, series: Any, *, seed: Any, block_days: Any) -> dict:
        self.calls.append((seed, block_days))
        return _permute(series, seed=seed, block_days=block_days)


def _endpoint(
    sidecar: NullSidecar,
    *,
    targets: Any = _targets,
    permute: Any = _permute,
    past_flip: Any = None,
) -> TargetEndpoint:
    """An endpoint with the seams feature 113's rule needs, supplied."""
    return TargetEndpoint(
        sidecar, targets=targets, permute=permute, past_flip=past_flip
    )


def _written(
    sidecar: NullSidecar,
    node_id: str,
    *,
    is_null: bool,
    perm_seed: int = 7,
    block_days: int = 2,
) -> NullAssignment:
    """Seal one node's entry and hand back what was sealed."""
    entry = NullAssignment(
        node_id=node_id,
        is_null=is_null,
        perm_seed=perm_seed,
        block_days=block_days,
    )
    sidecar.write([entry])
    return entry


class _Ask:
    """A duck-typed request — the route reads its request by attribute.

    The composed endpoint and a directly-imported :class:`TargetRequest` are
    one source under two module names, so ``post`` reads the ask structurally.
    This stand-in exists for the tests that must state the *span* and the
    *cross-section* as something other than a validated pair, so the
    comparison under test is the route's own rather than the request's.
    """

    def __init__(
        self,
        node_id: Any,
        *,
        symbols: Any = ("BTCUSDT", "ETHUSDT"),
        date_range: Any = (dt.date(2026, 1, 1), dt.date(2026, 2, 20)),
    ) -> None:
        self.node_id = node_id
        if symbols is not None:
            self.symbols = symbols
        if date_range is not None:
            self.date_range = date_range


# -- The branch rule -------------------------------------------------------------


class TestTheBitSelectsTheBranch:
    def test_a_real_node_is_served_the_real_series(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §7.2's ``else`` arm, verbatim: the real forward returns, unchanged.
        # Nothing about them is touched — not the values, not the dates, not
        # the row order — because a route that "cleaned" them would be
        # serving a series nobody aligned.
        _written(test_sidecar, node_id, is_null=False)
        response = _endpoint(test_sidecar).post(_request(node_id))
        assert response.status == OK
        assert response.target_series == SERIES

    def test_a_null_node_is_served_a_permutation_of_the_real_series(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §7.2's ``if`` arm: ``block_permute(forward_returns, seed=perm_seed,
        # block=20d)``.  The assertion is the *relation* — same rows, moved —
        # rather than a literal order, because which order feature 115's
        # shuffle produces is that feature's own contract.
        entry = _written(
            test_sidecar, node_id, is_null=True, perm_seed=7, block_days=2
        )
        response = _endpoint(test_sidecar).post(_request(node_id))
        expected = _permute(
            SERIES, seed=entry.perm_seed, block_days=entry.block_days
        )
        assert response.status == OK
        assert response.target_series == expected

    def test_the_two_branches_differ_for_a_permutation_that_moves(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # The test above would also pass on a route that ignored the bit and
        # permuted *everything*, if the permutation moved nothing visible — so
        # the two nodes below are sealed with the same parameters and asked
        # the same question, and their answers must differ.  This is the one
        # place the suite asserts the branches are distinguishable from the
        # *series* alone, which is exactly the assertion an implementation
        # that always permuted (or never did) would fail.
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(
                    node_id=null_node,
                    is_null=True,
                    perm_seed=3,
                    block_days=2,
                ),
                NullAssignment(
                    node_id=real_node,
                    is_null=False,
                    perm_seed=3,
                    block_days=2,
                ),
            ]
        )
        endpoint = _endpoint(test_sidecar)
        null_series = endpoint.post(_request(null_node)).target_series
        real_series = endpoint.post(_request(real_node)).target_series
        assert null_series != real_series
        assert real_series == SERIES

    def test_the_permutation_moves_rows_across_dates(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The trap this whole feature's payload half is built around.  The
        # deterministic stand-in below moves the *rows* to a known
        # displacement: output slot ``i`` takes input slot ``i + 1``, wrapping.
        # A gather that instead carried each date together with its own row
        # would rebuild :data:`SERIES` exactly — and since mapping equality
        # ignores insertion order, *every* other test in this file would still
        # pass while the null branch served the real series.  So this one
        # asserts the values actually moved, by name and by value.
        def _shift(series: Any, *, seed: Any, block_days: Any) -> dict:
            days = list(series)
            rows = [series[day] for day in days]
            return {
                day: dict(rows[(index + 1) % len(days)])
                for index, day in enumerate(days)
            }

        _written(test_sidecar, node_id, is_null=True, perm_seed=0)
        served = _endpoint(test_sidecar, permute=_shift).post(
            _request(node_id)
        ).target_series
        assert served is not None
        assert tuple(served) == tuple(SERIES)
        assert served[DAYS[0]] == SERIES[DAYS[1]]
        assert served[DAYS[-1]] == SERIES[DAYS[0]]
        # And it is not the real series, stated the way a reader would check
        # it rather than as a consequence of the two lines above.
        assert served != SERIES

    def test_the_permutation_is_called_with_the_entries_own_parameters(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §7.1's ``perm_seed`` and ``block_days`` are *stored* — the
        # load-bearing word in feature 115's own sentence — so the route
        # reads them off the entry the sidecar just handed it and never
        # invents one.  A route that drew a fresh seed per request would
        # serve a different null world on every ask, and §12's determinism
        # contract forbids it outright.
        recorder = _Recorder()
        _written(
            test_sidecar, node_id, is_null=True, perm_seed=99, block_days=3
        )
        _endpoint(test_sidecar, permute=recorder).post(_request(node_id))
        assert recorder.calls == [(99, 3)]

    def test_a_permutation_is_not_consulted_for_a_real_node(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The ``else`` arm does not permute, so it does not call the
        # mechanism either — the same "spend the same work" discipline stated
        # from the other side: whatever a real request costs, it is not a
        # permutation, and a route that called one to discard the result
        # would be doing work no branch needs.
        recorder = _Recorder()
        _written(test_sidecar, node_id, is_null=False, perm_seed=99)
        _endpoint(test_sidecar, permute=recorder).post(_request(node_id))
        assert recorder.calls == []

    def test_two_requests_for_one_node_reproduce_one_series(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §12: the sealed world alone fixes the answer.  Two endpoints, two
        # reads of the same file, one series — nothing is remembered between
        # them, and nothing needs to be.
        _written(
            test_sidecar, node_id, is_null=True, perm_seed=5, block_days=2
        )
        first = _endpoint(test_sidecar).post(_request(node_id))
        second = _endpoint(test_sidecar).post(_request(node_id))
        assert first.target_series == second.target_series

    def test_the_payload_sits_behind_a_read_only_proxy(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The caller's own dict must not be a live handle on a response: a
        # series that could be edited after the fact would be the oracle
        # revising an answer already given.
        mutable = {day: dict(row) for day, row in SERIES.items()}
        _written(test_sidecar, node_id, is_null=False)
        response = _endpoint(
            test_sidecar, targets=lambda request: mutable
        ).post(_request(node_id))
        assert isinstance(response.target_series, MappingProxyType)
        with pytest.raises(TypeError):
            response.target_series[DAYS[0]] = {}  # type: ignore[index]


# -- The directive ---------------------------------------------------------------


class TestTheDirectiveIsOpaqueAndExact:
    def test_a_null_node_is_not_charged_budget(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §8's column comment, verbatim: ``charges_budget BOOLEAN NOT NULL,
        # -- FALSE for null nodes``.  A null node's signal was never compared
        # to real forward returns, so it consumed no statistical degrees of
        # freedom; the directive is ``False`` so that ``K_effective`` — which
        # counts only the rows whose directive is true — never inflates.
        # The direction is the whole test: an implementation that inverted it
        # would read as *"charge the null nodes"*, which is the deflation
        # term's failure mode rather than a cosmetic difference.
        _written(test_sidecar, node_id, is_null=True)
        response = _endpoint(test_sidecar).post(_request(node_id))
        assert response.charges_budget is False

    def test_a_real_node_is_charged_budget(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The same fact from the other side: a real node spent real degrees
        # of freedom against real returns, so its evaluation charges, and the
        # ledger's debit is what makes the deflation term honest.
        _written(test_sidecar, node_id, is_null=False)
        response = _endpoint(test_sidecar).post(_request(node_id))
        assert response.charges_budget is True

    def test_the_directive_is_a_genuine_bool(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # Not ``1``, not ``0``, not a truthy string: the directive is the one
        # bit that crosses the barrier (§7.2) and its consumers refuse
        # anything else.  Both branches are checked because both spellings
        # would be wrong in the same way on one side and invisible on the
        # other.
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(node_id=null_node, is_null=True, perm_seed=4),
                NullAssignment(node_id=real_node, is_null=False, perm_seed=0),
            ]
        )
        endpoint = _endpoint(test_sidecar)
        for node in (null_node, real_node):
            budget = endpoint.post(_request(node)).charges_budget
            assert budget is not None
            assert isinstance(budget, bool)

    def test_the_directive_is_exactly_the_negation_of_the_bit(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # §7.2's rule and §8's debit, held together: ``charges_budget`` is
        # ``not is_null``.  The relation is asserted against the entry that
        # was sealed rather than against a literal, so this test states the
        # *rule* and the two above state the two values.
        null_node, real_node = node_ids(2)
        entries = [
            NullAssignment(node_id=null_node, is_null=True, perm_seed=4),
            NullAssignment(node_id=real_node, is_null=False, perm_seed=0),
        ]
        test_sidecar.write(entries)
        endpoint = _endpoint(test_sidecar)
        for entry in entries:
            response = endpoint.post(_request(entry.node_id))
            assert response.charges_budget is (not entry.is_null)

    def test_a_budget_that_is_not_a_bool_is_refused(self) -> None:
        # The response's own contract, stated where it is enforced: the
        # evaluator's ledger refuses a coerced flag, so the route must not
        # emit one.  Both directions of coercion are wrong in their own way:
        # ``bool("false")`` is ``True`` (a null node charged budget it never
        # spent) and a coerced ``0`` is ``False`` (a real node refunded a
        # budget it did) — and ``K_effective`` under-counts in the second,
        # which is the direction §8's deflation cannot absorb.
        for budget in (1, 0, "true", "", None):
            with pytest.raises(TargetPayloadError, match="charges_budget"):
                TargetResponse(
                    status=OK,
                    node_id=str(uuid.uuid4()),
                    target_series=SERIES,
                    charges_budget=budget,
                )

    def test_a_false_directive_is_not_read_as_a_missing_payload(self) -> None:
        # ``False`` is a value, not an absence — the mistake a truthiness
        # check makes, and on this payload it is the *null* branch's value,
        # so a route that used ``if not charges_budget`` to mean "no payload"
        # would refuse every null node it was asked about.  The two null
        # constructions below are told apart by ``is None``, which is what
        # the payload's coherence rule actually asks.
        response = TargetResponse(
            status=OK,
            node_id=str(uuid.uuid4()),
            target_series=SERIES,
            charges_budget=False,
        )
        assert response.charges_budget is False
        assert response.known is True


# -- What may not vary -----------------------------------------------------------


class TestNothingOnTheAnswerNamesTheBranch:
    def test_the_two_answers_have_the_same_shape(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # Feature 114's promise, stated over the payload: the two answers for
        # two nodes of the same shape carry the same fields with the same
        # types.  A route whose null answer carried, say, ``permuted=True``
        # would be a route that varied by branch without saying so.
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(node_id=null_node, is_null=True, perm_seed=4),
                NullAssignment(node_id=real_node, is_null=False, perm_seed=0),
            ]
        )
        endpoint = _endpoint(test_sidecar)
        null_answer = endpoint.post(_request(null_node))
        real_answer = endpoint.post(_request(real_node))
        assert type(null_answer) is type(real_answer)
        assert null_answer.status == real_answer.status
        assert null_answer.detail == real_answer.detail is None
        # ``slots`` dataclasses have no ``__dict__``, so the field set is the
        # class's — and it is the same class, so comparing the field names is
        # the whole statement.  Written through ``dataclasses.fields`` so the
        # test reads the same view a serializer would.
        assert [
            field.name for field in dataclasses.fields(type(null_answer))
        ] == [
            field.name for field in dataclasses.fields(type(real_answer))
        ]
        # And the sets are what they are because both answers carry the
        # payload: a route that omitted a field on one branch would show here
        # as a shortened slot list.
        assert set(null_answer.__slots__ or ()) == {
            "status",
            "node_id",
            "target_series",
            "charges_budget",
            "detail",
        }

    @pytest.mark.parametrize("is_null", [True, False])
    def test_no_string_on_the_answer_names_the_bit(
        self, test_sidecar: NullSidecar, node_id: str, is_null: bool
    ) -> None:
        # The clause is *"never which returns is_null in any form"* — so the
        # spelling is swept from the whole record, not just from its field
        # names: the repr, the field names, the slot names, and every string
        # reachable from either answer.
        _written(test_sidecar, node_id, is_null=is_null)
        response = _endpoint(test_sidecar).post(_request(node_id))
        for public in (response, type(response)):
            assert not hasattr(public, "is_null")
            assert "is_null" not in repr(public)
        assert "is_null" not in repr(response)
        for name in getattr(response, "__slots__", ()):  # pragma: no branch
            assert "is_null" not in name

    @pytest.mark.parametrize("is_null", [True, False])
    def test_no_refusal_names_the_bit(
        self, test_sidecar: NullSidecar, node_id: str, is_null: bool
    ) -> None:
        # The refusals are where a leak is cheapest to commit and hardest to
        # notice: an error message is read by an operator, pasted into a
        # ticket and correlated with everything else they hold.  Each refusal
        # is provoked on both branches and its message swept for the bit.
        _written(test_sidecar, node_id, is_null=is_null)
        endpoint = _endpoint(test_sidecar, targets=None)
        with pytest.raises(TargetPayloadError) as caught:
            endpoint.post(_request(node_id))
        assert "is_null" not in str(caught.value)

    @pytest.mark.parametrize("is_null", [True, False])
    def test_the_missing_permutation_refuses_both_branches_alike(
        self, test_sidecar: NullSidecar, node_id: str, is_null: bool
    ) -> None:
        # The permute seam's absence refuses on *both* branches, and that
        # symmetry is the whole point rather than a convenience.  A route
        # holding ``targets`` but no ``permute`` can serve the real branch and
        # cannot serve the null one, so a refusal raised when the null branch
        # wanted it would make the difference between a 200 and an exception
        # *be* ``is_null`` — read by any caller who wrapped the call in a
        # ``try``.  The refusal is therefore named before the branch is
        # chosen, exactly as the series seam's is, and the message names the
        # missing mechanism and the node, never the branch that wanted it.
        _written(test_sidecar, node_id, is_null=is_null)
        endpoint = _endpoint(test_sidecar, permute=None)
        with pytest.raises(TargetPayloadError) as caught:
            endpoint.post(_request(node_id))
        assert node_id in str(caught.value)
        assert "permute" in str(caught.value)
        assert "is_null" not in str(caught.value)

    def test_the_two_supply_refusals_are_symmetric(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # The general property the test above is one instance of: for a node
        # on either branch, a route missing *either* seam answers that node
        # the same way.  Stated over both branches and both missing seams at
        # once, because the failure this guards against is precisely a route
        # whose answer depends on which branch asked.
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(node_id=null_node, is_null=True, perm_seed=4),
                NullAssignment(node_id=real_node, is_null=False, perm_seed=0),
            ]
        )
        for missing in ("targets", "permute"):
            endpoint = _endpoint(test_sidecar, **{missing: None})
            outcomes = []
            for node in (null_node, real_node):
                try:
                    outcomes.append(("returned", endpoint.post(_request(node)).status))
                except TargetPayloadError:
                    outcomes.append(("refused", None))
            assert outcomes[0] == outcomes[1], (
                f"a route missing its {missing} seam answered the two branches "
                f"differently: {outcomes} — which branch was refused is the bit"
            )

    def test_a_caller_cannot_read_the_bit_by_catching_the_refusal(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # The same defect as the test above, stated the way it actually costs
        # something: as a *reader* of the bit.  A caller who knows only that
        # "the null node is the one that raises" can classify every node it
        # asks about, and the preceding tests would all still pass — the
        # refusal is on the wrong branch, not the wrong message.
        #
        # So this test measures information rather than behaviour.  It asks
        # about a balanced set of nodes without being told which is which,
        # guesses "null" for each node the route refused, and asserts the
        # guesses are no better than a coin.  A route that refused only null
        # nodes scores 100% here; a route that refuses both branches scores
        # exactly the majority-class baseline, which is what it must score —
        # the exception then says nothing about the node that raised it.
        nodes = node_ids(12)
        test_sidecar.write(
            [
                NullAssignment(node_id=node, is_null=index % 2 == 0, perm_seed=3)
                for index, node in enumerate(nodes)
            ]
        )
        truth = ["null" if index % 2 == 0 else "real" for index in range(len(nodes))]
        endpoint = _endpoint(test_sidecar, permute=None)

        guesses = []
        for node in nodes:
            try:
                endpoint.post(_request(node))
                guesses.append("real")
            except TargetPayloadError:
                guesses.append("null")

        correct = sum(guess == answer for guess, answer in zip(guesses, truth))
        baseline = max(truth.count("null"), truth.count("real"))
        assert correct <= baseline, (
            f"the refusal classified {correct}/{len(nodes)} nodes where a "
            f"blind guess scores {baseline}/{len(nodes)} — a caller who "
            "catches this exception has read §7.2's bit"
        )

    def test_the_response_class_is_one_class(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # Two branches, one type — the same claim as the shape test above,
        # stated the way a caller would check it.
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(node_id=null_node, is_null=True, perm_seed=4),
                NullAssignment(node_id=real_node, is_null=False, perm_seed=0),
            ]
        )
        endpoint = _endpoint(test_sidecar)
        assert type(endpoint.post(_request(null_node))) is type(
            endpoint.post(_request(real_node))
        )


# -- The refusals ----------------------------------------------------------------


class TestAKnownNodeIsNeverAnsweredWithNothing:
    def test_a_route_with_no_series_seam_refuses_by_name(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # A deployment that holds no step-4 alignment composes a route that
        # refuses by name rather than serving half a world — the honest
        # degradation, and it is a refusal rather than a 404: the sidecar
        # *does* hold this node, and a 404 would deny it.
        _written(test_sidecar, node_id, is_null=False)
        endpoint = _endpoint(test_sidecar, targets=None)
        with pytest.raises(TargetPayloadError, match="no seam"):
            endpoint.post(_request(node_id))

    def test_a_seam_that_declines_a_request_refuses_by_name(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # A seam that answers ``None`` for one ask is a third way of having
        # no series, and it is named as such rather than read as an empty
        # one — the difference between "step 4 could not align this window"
        # and "step 4 aligned nothing".
        _written(test_sidecar, node_id, is_null=False)
        endpoint = _endpoint(test_sidecar, targets=lambda request: None)
        with pytest.raises(TargetPayloadError, match="answered no series"):
            endpoint.post(_request(node_id))

    def test_the_refusal_names_the_node_it_could_not_serve(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # A caller told *which* node the oracle could not serve can act on
        # it; a caller told "the oracle is broken" cannot.
        _written(test_sidecar, node_id, is_null=False)
        endpoint = _endpoint(test_sidecar, targets=None)
        with pytest.raises(TargetPayloadError) as caught:
            endpoint.post(_request(node_id))
        assert node_id in str(caught.value)

    def test_an_unknown_node_still_answers_404_with_no_payload(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # Feature 112's refusal is not reached by feature 113's supply check,
        # and the 404 it produces carries no payload: the route answers with
        # everything it knows, which is that the sidecar holds no such node.
        # Not even a series seam is consulted — the entry is read first, and
        # an unknown node never reaches the supply.
        _written(test_sidecar, str(uuid.uuid4()), is_null=False)
        called: list[Any] = []

        def _never(request: Any) -> dict:
            called.append(request)
            return {}

        response = _endpoint(test_sidecar, targets=_never).post(
            _request(node_id)
        )
        assert response.status == NOT_FOUND
        assert response.target_series is None
        assert response.charges_budget is None
        assert called == []

    def test_a_payload_on_a_404_is_refused(self) -> None:
        with pytest.raises(TargetPayloadError, match="carries no payload"):
            TargetResponse(
                status=NOT_FOUND,
                node_id=str(uuid.uuid4()),
                target_series=SERIES,
                detail="no such node",
            )

    def test_an_ok_without_a_payload_is_refused(self) -> None:
        # The other half of the same coherence rule, term by term so the
        # reader sees which term was missing.
        for missing in ("target_series", "charges_budget"):
            payload: dict[str, Any] = {
                "target_series": SERIES,
                "charges_budget": True,
            }
            payload[missing] = None
            with pytest.raises(TargetPayloadError, match=missing):
                TargetResponse(
                    status=OK, node_id=str(uuid.uuid4()), **payload
                )

    def test_a_series_of_the_wrong_shape_is_refused(self) -> None:
        # §7.2's payload is a panel keyed by rebalance date; a bare list of
        # numbers is a series for a different question, and it is refused by
        # name rather than iterated.
        for series in ([0.01, 0.02], None):
            with pytest.raises(TargetPayloadError, match="target_series"):
                TargetResponse(
                    status=OK,
                    node_id=str(uuid.uuid4()),
                    target_series=series,
                    charges_budget=True,
                )
        # The two nested cases are refused by the check that owns their
        # *level* rather than by the outer one — a row that is not a mapping,
        # and a symbol that is not a name.
        for series in ({DAYS[0]: 0.01}, {DAYS[0]: {1: 0.01}}):
            with pytest.raises(TargetPayloadError):
                TargetResponse(
                    status=OK,
                    node_id=str(uuid.uuid4()),
                    target_series=series,
                    charges_budget=True,
                )

    @pytest.mark.parametrize(
        "value", [float("nan"), float("inf"), float("-inf"), True, "0.01"]
    )
    def test_a_target_that_is_not_a_finite_number_is_refused(
        self, value: Any
    ) -> None:
        # A NaN or an infinity would reach the metrics dressed as a
        # measurement, and a bool that happens to equal a score is not a
        # score — the evaluator's own client refuses both, so the route must
        # not emit either.
        with pytest.raises(TargetPayloadError, match="BTCUSDT|number"):
            TargetResponse(
                status=OK,
                node_id=str(uuid.uuid4()),
                target_series={DAYS[0]: {"BTCUSDT": value}},
                charges_budget=True,
            )

    def test_a_dashed_string_is_refused_by_name_and_not_guessed_at(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The payload's dates accept exactly the pair the request's do — a
        # ``date`` or its ISO spelling.  Anything else is a series from a
        # different producer, refused at the constructor with a
        # :class:`TargetPayloadError` rather than the request's own error: a
        # caller reading a *request* refusal out of a *response* would look
        # for a malformed ask that does not exist.
        _written(test_sidecar, node_id, is_null=False)
        with pytest.raises(TargetPayloadError, match="ISO date"):
            _endpoint(
                test_sidecar,
                targets=lambda request: {
                    "January 5th": {"BTCUSDT": 0.01, "ETHUSDT": 0.02}
                },
            ).post(_request(node_id))

    def test_a_wire_spelled_date_is_captured_as_a_date(self) -> None:
        # §7.2 is a service boundary and ISO is the wire spelling, so an
        # answer keyed by ISO strings is the same answer: it is canonicalised
        # on capture, not refused.
        response = TargetResponse(
            status=OK,
            node_id=str(uuid.uuid4()),
            target_series={"2026-01-05": {"BTCUSDT": 0.01}},
            charges_budget=False,
        )
        assert response.target_series == {dt.date(2026, 1, 5): {"BTCUSDT": 0.01}}

    def test_one_bar_under_two_spellings_is_refused(self) -> None:
        # A wire producer that wrote both spellings produced a series with
        # two answers for one day; merging them would be guessing which.
        with pytest.raises(TargetPayloadError, match="twice"):
            TargetResponse(
                status=OK,
                node_id=str(uuid.uuid4()),
                target_series={
                    dt.date(2026, 1, 5): {"BTCUSDT": 0.01},
                    "2026-01-05": {"BTCUSDT": 0.02},
                },
                charges_budget=False,
            )

    def test_a_datetime_key_is_refused(self) -> None:
        # A target is day-granular, and truncating an instant would guess
        # which candle was meant.
        with pytest.raises(TargetPayloadError, match="datetime"):
            TargetResponse(
                status=OK,
                node_id=str(uuid.uuid4()),
                # The naive instant is the point of the test: a target is
                # day-granular and the refusal is about the *key type*, not
                # about a timezone the series never carried.
                target_series={
                    dt.datetime(2026, 1, 5, 9, 30): {"BTCUSDT": 0.01}  # noqa: DTZ001
                },
                charges_budget=False,
            )

    def test_a_hash_survives_the_payload(self) -> None:
        # The response is a value a caller may key a dict by — the
        # evaluator's own client collapses its series to tuples for the same
        # reason — so hashing must not raise on the mappings, and two equal
        # answers must hash alike.
        node = str(uuid.uuid4())
        first = TargetResponse(
            status=OK,
            node_id=node,
            target_series=SERIES,
            charges_budget=True,
        )
        second = TargetResponse(
            status=OK,
            node_id=node,
            target_series={day: dict(row) for day, row in SERIES.items()},
            charges_budget=True,
        )
        assert first == second
        assert hash(first) == hash(second)


# -- The seams -------------------------------------------------------------------


class TestTheSeamsAreCheckedAtConstruction:
    def test_a_seam_that_cannot_be_called_is_refused(
        self, test_sidecar: NullSidecar
    ) -> None:
        # The factory builds every registered component on every
        # ``create_app()`` call, so a wiring mistake must surface at
        # construction, where an operator sees it, rather than at the first
        # request, inside an evaluation.
        for seam in ("targets", "permute", "past_flip"):
            with pytest.raises(TypeError, match=seam):
                TargetEndpoint(test_sidecar, **{seam: "not callable"})

    def test_a_seam_may_be_omitted(self, test_sidecar: NullSidecar) -> None:
        # ``None`` is a supported state — a deployment that holds no step-4
        # series, no permutation, or no Type-D store composes a route that
        # answers what it can — so omitting one is not a wiring mistake.
        endpoint = TargetEndpoint(test_sidecar)
        assert endpoint.sidecar is test_sidecar

    def test_the_endpoint_holds_its_sidecar_and_nothing_else(
        self, test_sidecar: NullSidecar
    ) -> None:
        # No cache of the assignment map: the labels live in the sealed file,
        # and a memo would move the controlled read to construction and then
        # hold the plaintext for the process's lifetime.
        assert TargetEndpoint(test_sidecar).sidecar is test_sidecar


class TestTheTypeDSeamComposesWithoutReimplementingTheRule:
    def test_a_past_flip_answer_overrides_the_sidecars_bit(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §7.2 for Type-D campaigns: *"below flip_depth the real targets are
        # returned, at or beyond it the permuted ones"* — a fact of depths
        # that §7.1's sidecar does not hold (§7.3: *"Campaigns are
        # homogeneous in null type"*), so the entry's bit is whatever the
        # last writer left and reading it would answer the wrong regime.
        _written(test_sidecar, node_id, is_null=False, perm_seed=3)
        endpoint = _endpoint(
            test_sidecar, past_flip=lambda request: True
        )
        response = endpoint.post(_request(node_id))
        assert response.charges_budget is False
        assert response.target_series != SERIES

    def test_a_past_flip_answer_of_false_serves_the_real_series(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The other side of the flip: an entry whose stored bit says null,
        # resolved real because the request sits below the branch's flip.
        _written(test_sidecar, node_id, is_null=True, perm_seed=3)
        endpoint = _endpoint(
            test_sidecar, past_flip=lambda request: False
        )
        response = endpoint.post(_request(node_id))
        assert response.charges_budget is True
        assert response.target_series == SERIES

    def test_a_none_answer_falls_through_to_the_sidecar(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # ``None`` means *this campaign is not the Type-D regime*, which is
        # what lets the seam be composed unconditionally: an adapter over
        # feature 121's store answers only for the campaigns that have flips
        # and declines every other ask by saying so, rather than by raising
        # the store's refusal through a route that had a good answer.
        _written(test_sidecar, node_id, is_null=True, perm_seed=3)
        endpoint = _endpoint(
            test_sidecar, past_flip=lambda request: None
        )
        response = endpoint.post(_request(node_id))
        assert response.charges_budget is False
        assert response.target_series != SERIES

    def test_an_undecided_flip_is_refused_rather_than_guessed(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # A seam that answers something that merely looks true or false
        # leaves the branch undecided, and an undecided branch cannot be
        # served — the refusal names the answer and the node.
        _written(test_sidecar, node_id, is_null=False)
        for answer in (1, 0, "true", ""):
            endpoint = _endpoint(
                test_sidecar, past_flip=lambda request, a=answer: a
            )
            with pytest.raises(TargetPayloadError, match="past_flip"):
                endpoint.post(_request(node_id))

    def test_a_type_d_node_no_sidecar_holds_is_still_unknown(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The seam *overrides* the bit and never replaces the lookup: a route
        # whose Type-D known-ness came from a database and whose Type-R
        # known-ness came from the sealed file would report two different
        # worlds under one word.
        other = str(uuid.uuid4())
        _written(test_sidecar, other, is_null=False)
        endpoint = _endpoint(
            test_sidecar, past_flip=lambda request: True
        )
        assert endpoint.post(_request(node_id)).status == NOT_FOUND

    def test_a_type_d_node_still_draws_its_permutation_from_the_entry(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §7.1's schema is the single home of ``perm_seed`` and
        # ``block_days``, which is where feature 121's own docstring says a
        # caller composes its ``permute`` from — so the flip decides *which*
        # branch and the sidecar still decides *how*.
        recorder = _Recorder()
        _written(
            test_sidecar, node_id, is_null=False, perm_seed=42, block_days=2
        )
        _endpoint(
            test_sidecar, permute=recorder, past_flip=lambda request: True
        ).post(_request(node_id))
        assert recorder.calls == [(42, 2)]


# -- The ask the payload must answer ---------------------------------------------


class TestThePayloadAnswersTheAskItWasGiven:
    def test_a_series_covering_a_symbol_nobody_asked_for_is_refused(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §7.2's branches preserve the aligned support exactly, so an answer
        # naming a symbol the ask did not is a series that arrived by some
        # path other than this one — the substitution the evaluator's gate
        # refuses downstream, refused here so it never leaves the oracle.
        _written(test_sidecar, node_id, is_null=False)
        endpoint = _endpoint(
            test_sidecar,
            targets=lambda request: {
                day: {"BTCUSDT": 0.01, "SOLUSDT": 0.02} for day in DAYS
            },
        )
        with pytest.raises(TargetPayloadError, match="SOLUSDT"):
            endpoint.post(_request(node_id))

    def test_a_series_missing_a_symbol_the_ask_named_is_refused(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The other direction, and the more dangerous one: a symbol nobody
        # replied for is indistinguishable from a symbol nobody scored.
        _written(test_sidecar, node_id, is_null=False)
        endpoint = _endpoint(
            test_sidecar,
            targets=lambda request: {day: {"BTCUSDT": 0.01} for day in DAYS},
        )
        with pytest.raises(TargetPayloadError, match="ETHUSDT"):
            endpoint.post(_request(node_id))

    @pytest.mark.parametrize("is_null", [True, False])
    def test_the_support_check_runs_on_both_branches(
        self, test_sidecar: NullSidecar, node_id: str, is_null: bool
    ) -> None:
        # A check that ran only after the branch was chosen would have to be
        # *written* per branch, and the one place such a check leaks is where
        # it is written twice.  It runs before the branch is read, so the two
        # branches below are refused by the same line.
        _written(test_sidecar, node_id, is_null=is_null)
        endpoint = _endpoint(
            test_sidecar,
            targets=lambda request: {day: {"BTCUSDT": 0.01} for day in DAYS},
        )
        with pytest.raises(TargetPayloadError, match="ETHUSDT"):
            endpoint.post(_request(node_id))

    def test_the_values_are_never_compared_to_anything(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # An absurd series is served without comment, on both branches: the
        # check is on names and dates only.  A route that inspected values
        # would be the client-side null detector principle P2 forbids,
        # running inside the oracle.
        _written(test_sidecar, node_id, is_null=True, perm_seed=3)
        endpoint = _endpoint(
            test_sidecar,
            targets=lambda request: {day: {"BTCUSDT": 1e308, "ETHUSDT": -1e308} for day in DAYS},
        )
        assert endpoint.post(_request(node_id)).status == OK

    def test_a_date_outside_the_asks_span_is_refused(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # An answer whose dates fall outside the ``date_range`` the ask named
        # is an answer to a different ask — and refusing it costs no branch
        # information, because the check is containment: the series' own
        # endpoints are exactly what a permutation moves.
        _written(test_sidecar, node_id, is_null=False)
        beyond = dt.date(2026, 4, 1)
        endpoint = _endpoint(
            test_sidecar,
            targets=lambda request: {
                **{day: dict(row) for day, row in SERIES.items()},
                beyond: {"BTCUSDT": 0.01, "ETHUSDT": 0.02},
            },
        )
        with pytest.raises(TargetPayloadError, match="2026-04-01"):
            endpoint.post(_request(node_id))

    def test_a_series_inside_the_span_is_served_though_it_is_shorter(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # Containment, not equality: the real series may cover fewer days
        # than the span — a horizon the window cannot reach is absent, never
        # zeroed — and a route that demanded the full span would refuse
        # every short-horizon window.
        _written(test_sidecar, node_id, is_null=False)
        endpoint = _endpoint(
            test_sidecar,
            targets=lambda request: {DAYS[0]: {"BTCUSDT": 0.01, "ETHUSDT": 0.0}},
        )
        response = endpoint.post(_request(node_id))
        assert response.status == OK
        assert tuple(response.target_series) == (DAYS[0],)

    def test_the_span_check_accepts_iso_spellings_on_both_sides(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §7.2 is a service boundary and ISO is the wire spelling, so a
        # duck-typed ask that spelled its span as strings, against a series
        # keyed by dates, is compared on the same terms rather than by
        # accident of spelling.
        _written(test_sidecar, node_id, is_null=False)
        endpoint = _endpoint(test_sidecar)
        ask = _Ask(node_id, date_range=("2026-01-01", "2026-02-20"))
        assert endpoint.post(ask).status == OK  # type: ignore[arg-type]

    def test_a_span_that_cannot_be_read_defers_to_the_requests_contract(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # A duck-typed ask with an unreadable span is not this route's to
        # refuse: the term is the *request's* contract and its own validator
        # refuses it, so a route that refused it here would be a second
        # spelling of one rule.
        _written(test_sidecar, node_id, is_null=False)
        endpoint = _endpoint(test_sidecar)
        ask = _Ask(node_id, date_range=("January 5th", "2026-02-20"))
        assert endpoint.post(ask).status == OK  # type: ignore[arg-type]

    def test_a_request_naming_no_cross_section_defers(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The duck-typed ask the route reads on purpose — from the
        # module-alias seam — may state nothing to compare against, and a
        # caller is not refused for a field they never had.
        _written(test_sidecar, node_id, is_null=False)
        endpoint = _endpoint(test_sidecar)
        assert (
            endpoint.post(_Ask(node_id, symbols=None)).status  # type: ignore[arg-type]
            == OK
        )


class TestAPermutedSeriesStaysOnTheSameSupport:
    def test_a_permutation_that_changes_the_dates_is_refused(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The block permutation §7.2 names moves a series' day blocks and
        # never adds or drops one, so a served series carrying different
        # dates has been recomputed rather than rearranged — and its support
        # alone would mark the branch as plainly as an ``is_null`` column
        # would.
        _written(test_sidecar, node_id, is_null=True, perm_seed=3)
        endpoint = _endpoint(
            test_sidecar,
            permute=lambda series, *, seed, block_days: {
                day: dict(row)
                for day, row in list(series.items())[:-1]
            },
        )
        with pytest.raises(TargetPayloadError, match="day blocks and never"):
            endpoint.post(_request(node_id))

    def test_a_permutation_that_moves_a_date_is_refused(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # Same count, different days — the case a length check would miss.
        _written(test_sidecar, node_id, is_null=True, perm_seed=3)
        shifted = {
            day + dt.timedelta(days=365): dict(row)
            for day, row in SERIES.items()
        }
        endpoint = _endpoint(
            test_sidecar,
            permute=lambda series, *, seed, block_days: shifted,
        )
        with pytest.raises(TargetPayloadError, match="day blocks and never"):
            endpoint.post(_request(node_id))

    def test_an_identity_permutation_is_not_refused(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # Deliberate, and the one place this suite pins an *absence* of a
        # check: a series shorter than ``block_days`` has one block and
        # nothing to move, so a route that refused an identity permutation
        # would refuse exactly the one-block cases — and would refuse them
        # *only on the null branch*, which makes the refusal itself a branch
        # oracle.  The quality of a permutation is feature 116's to measure.
        _written(test_sidecar, node_id, is_null=True, perm_seed=3, block_days=20)
        endpoint = _endpoint(
            test_sidecar,
            permute=lambda series, *, seed, block_days: {
                day: dict(row) for day, row in series.items()
            },
        )
        response = endpoint.post(_request(node_id))
        assert response.status == OK
        assert response.target_series == SERIES

    def test_the_refusal_names_the_counts_and_the_node_and_nothing_else(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The message names the two counts, the node and the rule — never
        # *which* day moved, which is a property of the permutation and
        # therefore of the branch.
        _written(test_sidecar, node_id, is_null=True, perm_seed=3)
        endpoint = _endpoint(
            test_sidecar,
            permute=lambda series, *, seed, block_days: {
                day: dict(row) for day, row in list(series.items())[:-1]
            },
        )
        with pytest.raises(TargetPayloadError) as caught:
            endpoint.post(_request(node_id))
        message = str(caught.value)
        assert node_id in message
        assert f"{len(DAYS) - 1} dates" in message
        # The days themselves are the permutation's own output, so a message
        # that listed them would be publishing which rows the null branch
        # served.  The only date in it is a count, spelled as one.
        for day in DAYS:
            assert day.isoformat() not in message


class TestTheRouteErrorsStayDistinctFromThePayloadErrors:
    def test_a_malformed_body_is_refused_before_the_sidecar_is_opened(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # A request that cannot say what it is asking for spends no read of
        # the one file in the system worth controlling — so a sidecar that
        # was never written refuses nothing here, because it is never opened.
        with pytest.raises(TargetRouteError, match="node_id"):
            _endpoint(test_sidecar).post(_Ask("not-a-uuid"))  # type: ignore[arg-type]

    def test_the_two_refusals_are_different_classes(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The taxonomy is the point: a *body* that cannot say what it is
        # asking for, refused before the sidecar is opened, is not a
        # *deployment* that cannot serve what the body asked for, which is
        # only discoverable after the entry was read.  A caller that
        # conflated the two would go looking for a missing seam when their
        # request was malformed.
        _written(test_sidecar, node_id, is_null=False)
        with pytest.raises(TargetRouteError):
            _endpoint(test_sidecar).post(_Ask("nope"))  # type: ignore[arg-type]
        with pytest.raises(TargetPayloadError):
            _endpoint(test_sidecar, targets=None).post(_request(node_id))

    def test_a_payload_error_is_not_a_route_error(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The same statement as an assertion about the class hierarchy: an
        # ``except TargetRouteError`` around the route must not swallow a
        # payload refusal, or a caller retrying on a malformed body would
        # retry a deployment that cannot answer at all.
        _written(test_sidecar, node_id, is_null=False)
        endpoint = _endpoint(test_sidecar, targets=None)
        with pytest.raises(TargetPayloadError) as caught:
            endpoint.post(_request(node_id))
        assert not isinstance(caught.value, TargetRouteError)
