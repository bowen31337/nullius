"""Feature 265's law: the scorer process and the rate it lets out.

*System computes null pick rate inside a scorer process holding the
sidecar key, which returns the rate while labels stay in*
(app_spec.xml, "Objective Scoring & CVaR Aggregation") — docs §10.3's line
507: *"``null_pick_rate`` is computed by a scorer process holding the
sidecar key.  The number flows out; the labels do not."*  The tests here
hold :mod:`scoring._scorer` to the sentence's clauses, in order:

* **inside a scorer process holding the sidecar key** — the process is
  constructed over a sidecar-holding carrier duck-read by its one
  ``assignment(node_id)`` seam, a carrier without the seam is refused,
  and the process itself is the closed surface the barrier needs: no
  sidecar accessor, no ``__dict__`` to park a label in, a ``repr`` that
  names the class and nothing it holds
  (:func:`test_the_process_holds_the_sidecar_by_its_one_seam`,
  :func:`test_a_carrier_without_the_seam_is_refused`,
  :func:`test_the_process_exposes_no_label_surface`);
* **computes null pick rate** — prd §4.4's fraction of committed picks
  that are planted nulls, over the campaign's picks whole: exact dyadic
  rates on the fixture campaign and every subset, a multiset (two picks
  of one node are two picks), both spellings of a pick (the address text
  and the value exposing ``node_id``), and any text spelling of a UUID
  address joining the sidecar's canonical keys
  (:func:`test_the_rate_is_the_fraction_over_the_campaign`,
  :func:`test_every_subset_answers_its_own_dyadic_fraction`,
  :func:`test_two_picks_of_one_node_are_two_picks`,
  :func:`test_both_spellings_of_a_pick_join`,
  :func:`test_every_uuid_spelling_joins_the_canonical_keys`);
* **which returns the rate while labels stay in** — the answer is one
  bare ``float``, the held sidecar is asked exactly once per pick for
  exactly the handed picks and never for a branch, the ask is validated
  whole before the first label is touched, and the refusal of an
  unlabelled pick names that pick and no other node
  (:func:`test_the_answer_is_one_bare_float`,
  :func:`test_the_sidecar_is_asked_once_per_pick_in_canonical_form`,
  :func:`test_a_refused_ask_never_touches_a_label`,
  :func:`test_an_unlabelled_pick_is_refused_naming_only_that_pick`);
* **the refusals** — every malformed ask, each naming the repair:
  a mapping, a bare string, bytes, nothing iterable, an empty ask, a
  pick that is ``None``/a bool/blank/exposes no ``node_id``, an address
  that is not a UUID, an entry whose ``is_null`` is not a genuine bool,
  and the sidecar's own failure while being read — translated into this
  member's vocabulary with the original chained, so the caller's single
  ``except ScoringError`` catches the whole member
  (:func:`test_a_mapping_is_refused_its_keys_are_not_its_picks` through
  :func:`test_a_foreign_read_failure_is_translated_and_chained`);
* **the taxonomy** — :class:`~scoring.NullPickRateError` is a
  :class:`~scoring.ScoringError` and a *sibling* of 258's
  :class:`~scoring.NullPickPenaltyError`, never a child, because the
  rate and the charge on it have different repairs
  (:func:`test_the_refusal_sits_beside_the_penalty_siblings`);
* **the arrow to β₂** — the rate this process answers is the figure
  feature 258's term charges on, composed verbatim through the seam the
  dependency graph draws (265 → 258, never back)
  (:func:`test_the_rate_composes_into_the_beta_two_term`).

Exactness is the suite's own discipline, inherited from the conftest's
fixtures: the campaign is four picks (two null, two real), so every rate
below is ``k/4`` and the duplicates make ``k/8`` — all dyadic, every
``==`` asserting the law's arithmetic and nothing about float luck; the
suite is ``pytest.approx``-free on purpose.  What these tests
deliberately do not reach: composition (``test_scorer_component.py``),
the seat (``test_scorer_component.py``, beside the app-module pin), the
*real* sealed sidecar (``test_scorer_cross_member.py`` — this suite
drives the duck-typed seam with the stand-in, which is the honest way to
test what crosses it), and any persistence (the ``replay_score`` row is
feature 255's).
"""

from __future__ import annotations

import uuid

import pytest
from conftest import (
    NULL_ONE,
    NULL_TWO,
    REAL_ONE,
    REAL_TWO,
    UNHELD,
    StandInAssignment,
    StandInPick,
    StandInSidecar,
)
from scoring import (
    BETA_TWO_DEFAULT,
    NullPickPenaltyError,
    NullPickRateError,
    NullPickScorer,
    ScoringError,
    null_pick_penalty,
    world_objective,
)


@pytest.fixture
def scorer(sidecar: StandInSidecar) -> NullPickScorer:
    """The process over the fixture campaign's stand-in sidecar."""
    return NullPickScorer(sidecar)


# -- inside a scorer process holding the sidecar key --------------------------


def test_the_process_holds_the_sidecar_by_its_one_seam(
    sidecar: StandInSidecar, committed_picks: list[StandInPick]
) -> None:
    """The duck-typed contract is the per-node assignment seam, and the
    process constructed over a carrier answering it computes through it.

    The stand-in carries no type relationship to the oracle's
    :class:`~nulloracle.NullSidecar` — that is the point of driving the
    seam with it: what crosses is the contract, and the cross-member
    suite pins that the real sealed sidecar satisfies the same one.
    """
    process = NullPickScorer(sidecar)
    assert process.null_pick_rate(committed_picks) == 0.5
    # The reads happened through the seam, in canonical form, one per pick.
    assert sidecar.reads == [NULL_ONE, REAL_ONE, NULL_TWO, REAL_TWO]


def test_a_carrier_without_the_seam_is_refused() -> None:
    """A sidecar-holding object that exposes no callable ``assignment``
    is refused at construction, naming the carrier and the seam it
    lacks — the wiring fault it is, not a label fact."""
    for carrier in (None, object(), {"assignment": "not callable"}, 7):
        with pytest.raises(NullPickRateError) as raised:
            NullPickScorer(carrier)  # type: ignore[arg-type]
        message = str(raised.value)
        assert "assignment(node_id)" in message
        assert "feature 265" in message


def test_the_process_exposes_no_label_surface(
    scorer: NullPickScorer, sidecar: StandInSidecar
) -> None:
    """The barrier is structural: no public attribute beside the verb, no
    ``__dict__`` for shadow state, and a ``repr`` that names the process
    and nothing it holds.

    ``labels stay in`` is not a promise this class asks the caller to
    believe — it is the absence of a surface the labels could leave
    through.  The sidecar stays reachable only as the private slot the
    verb reads.
    """
    public = [name for name in dir(scorer) if not name.startswith("_")]
    assert public == ["null_pick_rate", "resolve"]
    assert not hasattr(scorer, "__dict__")
    assert sidecar is not getattr(scorer, "sidecar", None)
    rendered = repr(scorer)
    assert "NullPickScorer" in rendered
    assert NULL_ONE not in rendered and "is_null" not in rendered


# -- computes null pick rate ---------------------------------------------------


def test_the_rate_is_the_fraction_over_the_campaign(
    scorer: NullPickScorer, committed_picks: list[StandInPick]
) -> None:
    """Two nulls over four committed picks: prd §4.4's fraction, exactly
    (0.5 is dyadic, so the law's one division is the only thing the
    ``==`` asserts)."""
    assert scorer.null_pick_rate(committed_picks) == 0.5


def test_every_subset_answers_its_own_dyadic_fraction(
    scorer: NullPickScorer, committed_picks: list[StandInPick]
) -> None:
    """k nulls over k+n picks: every subset's quotient is its own exact
    dyadic fraction, from the clean campaign (0.0 — a *measurement*) to
    the all-null one (1.0), and the empty collection is refused rather
    than answered 0.0 (its own test below: the two are different
    facts)."""
    by_address = [pick.node_id for pick in committed_picks]
    subsets = [
        ([REAL_ONE, REAL_TWO], 0.0),
        ([NULL_ONE], 1.0),
        ([NULL_ONE, REAL_ONE], 0.5),
        ([NULL_ONE, NULL_TWO, REAL_ONE, REAL_TWO], 0.5),
        (by_address, 0.5),  # the addresses spell the same campaign
        (list(reversed(by_address)), 0.5),  # order is not a fact of a set
    ]
    for picks, expected in subsets:
        assert scorer.null_pick_rate(picks) == expected
    # The third-sized subsets answer their thirds — two nulls of three and
    # one of three — and the ``==`` holds there too, because both sides
    # spell the same one division.
    assert scorer.null_pick_rate([NULL_ONE, NULL_TWO, REAL_ONE]) == 2 / 3
    assert scorer.null_pick_rate([NULL_ONE, REAL_ONE, REAL_TWO]) == 1 / 3


def test_two_picks_of_one_node_are_two_picks(scorer: NullPickScorer) -> None:
    """The figure is per pick, not per distinct node: two worlds
    committing to the same null are two false discoveries (2/4), not one
    deduplicated (1/3) — a multiset, counted as handed."""
    picks = [StandInPick(NULL_ONE), StandInPick(NULL_ONE), REAL_ONE, REAL_TWO]
    assert scorer.null_pick_rate(picks) == 0.5
    picks = [NULL_ONE, NULL_ONE, NULL_ONE, REAL_ONE, REAL_ONE, REAL_ONE,
             REAL_TWO, REAL_TWO]
    assert scorer.null_pick_rate(picks) == 3 / 8


def test_both_spellings_of_a_pick_join(
    scorer: NullPickScorer, sidecar: StandInSidecar
) -> None:
    """The address text and the value exposing ``node_id`` are the two
    spellings the objective's own pick seam accepts, and both are the
    same pick here — mixed freely in one ask, one read each, same rate."""
    picks = [NULL_TWO, StandInPick(NULL_ONE), StandInPick(REAL_ONE), REAL_TWO]
    assert scorer.null_pick_rate(picks) == 0.5
    assert sidecar.reads == [NULL_TWO, NULL_ONE, REAL_ONE, REAL_TWO]


def test_every_uuid_spelling_joins_the_canonical_keys(
    scorer: NullPickScorer, sidecar: StandInSidecar
) -> None:
    """Mixed case, braces and the ``urn:`` form all canonicalize to the
    sidecar's key spelling — the join is by the address, not by its
    typography, and the reads show the canonical form was asked."""
    upper = NULL_ONE.upper()
    braced = "{" + REAL_ONE + "}"
    urn = "urn:uuid:" + NULL_TWO
    assert scorer.null_pick_rate([upper, braced, urn, REAL_TWO]) == 0.5
    assert sidecar.reads == [NULL_ONE, REAL_ONE, NULL_TWO, REAL_TWO]


def test_the_same_ask_answers_the_same_rate(
    scorer: NullPickScorer, committed_picks: list[StandInPick]
) -> None:
    """Deterministic to the bit, ask over ask: one count, one division,
    no clock or store inside the verb — and a second process over the
    same labels agrees, because nothing about the first leaked into it."""
    first = scorer.null_pick_rate(committed_picks)
    second = scorer.null_pick_rate(committed_picks)
    assert first == second == 0.5
    twin = NullPickScorer(StandInSidecar({NULL_ONE: True, REAL_ONE: False,
                                          NULL_TWO: True, REAL_TWO: False}))
    assert twin.null_pick_rate([pick.node_id for pick in committed_picks]) == 0.5


# -- which returns the rate while labels stay in -------------------------------


def test_the_answer_is_one_bare_float(
    scorer: NullPickScorer, committed_picks: list[StandInPick]
) -> None:
    """The number flows out and nothing else does: the answer's type is
    ``float`` — not a carrier, not an int-count, not a value object a
    caller could introspect for the labels it aggregates.  §10.3's
    barrier enforced as a type, the only way a type can."""
    answer = scorer.null_pick_rate(committed_picks)
    assert type(answer) is float


def test_the_sidecar_is_asked_once_per_pick_in_canonical_form(
    scorer: NullPickScorer, sidecar: StandInSidecar, committed_picks: list[StandInPick]
) -> None:
    """One read per pick, canonical spelling, the handed picks only —
    never a branch walk, never a whole-file dump through this seam, and
    no second read for a repeated ask (the count pass and the label pass
    are one pass: the log has exactly the campaign in it)."""
    scorer.null_pick_rate(committed_picks)
    assert sidecar.reads == [NULL_ONE, REAL_ONE, NULL_TWO, REAL_TWO]


def test_a_refused_ask_never_touches_a_label(
    scorer: NullPickScorer, sidecar: StandInSidecar
) -> None:
    """The ask is validated whole before the first label is read: a
    malformed pick anywhere in the collection refuses the whole ask with
    the sidecar untouched — no partial count, and no label read for an
    ask that could not be answered."""
    with pytest.raises(NullPickRateError):
        scorer.null_pick_rate([NULL_ONE, "not-a-uuid", REAL_ONE])
    with pytest.raises(NullPickRateError):
        scorer.null_pick_rate([NULL_ONE, None])  # type: ignore[list-item]
    assert sidecar.reads == []


def test_an_unlabelled_pick_is_refused_naming_only_that_pick(
    scorer: NullPickScorer, committed_picks: list[StandInPick]
) -> None:
    """A pick the sidecar holds no entry for is refused — never read as
    real, which would deflate the figure the term exists to charge — and
    the refusal names that pick and no other node: which nodes are null
    is the one fact this process keeps inside, so the message carries
    the caller's own fact (the address) and nothing about any branch."""
    with pytest.raises(NullPickRateError) as raised:
        scorer.null_pick_rate([*committed_picks, UNHELD])
    message = str(raised.value)
    assert UNHELD in message
    for held in (NULL_ONE, NULL_TWO, REAL_ONE, REAL_TWO):
        assert held not in message
    assert "not real" in message or "unknown" in message


# -- the refusals --------------------------------------------------------------


def test_a_mapping_is_refused_its_keys_are_not_its_picks(
    scorer: NullPickScorer
) -> None:
    """Iterating a mapping yields its keys, and keys are not picks — the
    ask is refused rather than silently rated, and the refusal says the
    mapping's shape without printing its contents into the log."""
    with pytest.raises(NullPickRateError) as raised:
        scorer.null_pick_rate({"w1": StandInPick(NULL_ONE), "w2": StandInPick(REAL_ONE)})
    message = str(raised.value)
    assert "mapping" in message
    assert "w1" not in message  # the shape names the repair, not the keys


def test_a_bare_string_is_one_pick_spelled_where_the_collection_belongs(
    scorer: NullPickScorer
) -> None:
    """A bare string (and bytes) is refused: iterating it would rate its
    characters — one pick, spelled where the collection belongs, is a
    wiring fault the message names."""
    for one_pick in (NULL_ONE, "", b"not-a-collection"):
        with pytest.raises(NullPickRateError) as raised:
            scorer.null_pick_rate(one_pick)  # type: ignore[arg-type]
        assert "collection" in str(raised.value)


def test_something_uniterable_is_refused(scorer: NullPickScorer) -> None:
    """An ask that is not a collection of picks at all is refused,
    naming what was carried — an int is the likeliest wrong handover
    (a count spelled where the picks belong)."""
    with pytest.raises(NullPickRateError) as raised:
        scorer.null_pick_rate(4)  # type: ignore[arg-type]
    assert "int" in str(raised.value)


def test_an_ask_with_no_picks_at_all_is_refused(scorer: NullPickScorer) -> None:
    """A rate over an empty denominator is undefined, not ``0.0`` — the
    clean campaign's honest zero is a measurement over picks that were
    committed, and this seam cannot invent it for a set it was not
    handed.  The refusal is the difference between *none were null* and
    *nothing was measured*."""
    with pytest.raises(NullPickRateError) as raised:
        scorer.null_pick_rate([])
    assert "empty denominator" in str(raised.value)


@pytest.mark.parametrize(
    "pick",
    [
        None,  # a miss is not a committed pick
        True,  # a bool is not an address
        "",  # blank text names no node
        "   ",  # neither does whitespace
        42,  # an int exposes no node_id
        StandInPick(""),  # the value spelling, blank
        uuid.UUID(int=0),  # a UUID object is not the address text
    ],
    ids=["none", "bool", "blank", "spaces", "int", "blank-value", "uuid-object"],
)
def test_a_pick_that_names_no_node_is_refused(
    scorer: NullPickScorer, pick: object
) -> None:
    """Each shape that names no node is refused, and the refusal names
    the miss's difference — a policy that emitted no pick is the −∞ the
    termination already scored, not a denominator member."""
    with pytest.raises(NullPickRateError) as raised:
        scorer.null_pick_rate([pick])  # type: ignore[list-item]
    message = str(raised.value)
    assert "committed picks" in message
    assert "miss" in message or "node_id" in message


def test_a_pick_whose_node_id_is_not_text_is_refused(scorer: NullPickScorer) -> None:
    """The value spelling must expose a ``node_id`` that is text — a
    UUID object or a number in the field is a wiring fault the seam
    refuses rather than stringifies, because ``str()`` of a carrier is
    not an address anyone keyed by."""

    class NumericNodeId:
        node_id = 7

    with pytest.raises(NullPickRateError):
        scorer.null_pick_rate([NumericNodeId()])


def test_an_address_that_is_not_a_uuid_is_refused(scorer: NullPickScorer) -> None:
    """An id that cannot join the sidecar's UUID keys cannot join the
    tree store's ``node.id`` either — refused, never skipped, because a
    rate silently computed over fewer picks than were handed would be a
    fraction of a denominator nobody chose."""
    for address in ("not-a-uuid", "campaign-01/momentum-branch/d+1", "NULL_ONE"):
        with pytest.raises(NullPickRateError) as raised:
            scorer.null_pick_rate([address])
        assert "not a UUID" in str(raised.value)
        assert address in str(raised.value)


def test_an_entry_whose_bit_is_not_a_genuine_bool_is_refused() -> None:
    """``bool("false")`` is ``True``: a coerced bit counts the wrong
    world, so the seam demands the genuine article — the same refusal
    the oracle's assignment layer makes at the write and its target
    route makes at the read."""

    class Loose:
        def __init__(self, bit: object) -> None:
            self.is_null = bit

        def assignment(self, node_id: str) -> Loose:
            return self

    process = NullPickScorer(Loose("false"))
    with pytest.raises(NullPickRateError) as raised:
        process.null_pick_rate([NULL_ONE])
    assert "is_null" in str(raised.value)


def test_a_foreign_read_failure_is_translated_and_chained() -> None:
    """The sidecar's own failure while being read — whatever it raised —
    is one fact for the caller (the label could not be read), translated
    into this member's vocabulary with the original chained: the
    caller's single ``except ScoringError`` keeps working, and the
    operator keeps the oracle's own error underneath."""

    class Broken:
        def assignment(self, node_id: str) -> StandInAssignment:
            raise PermissionError("sidecar.enc: 0o644 admits a second account")

    process = NullPickScorer(Broken())
    with pytest.raises(NullPickRateError) as raised:
        process.null_pick_rate([NULL_ONE])
    assert isinstance(raised.value, ScoringError)
    assert isinstance(raised.value.__cause__, PermissionError)
    assert "could not be read" in str(raised.value)


# -- the taxonomy ----------------------------------------------------------------


def test_the_refusal_sits_beside_the_penalty_siblings() -> None:
    """``NullPickRateError`` is a ``ScoringError`` and a sibling of 258's
    ``NullPickPenaltyError`` — never a child of it or of any other
    β-term's — because the rate and the charge on it have different
    repairs: a computation that never ran against a mis-set coefficient.
    One ``except ScoringError`` catches the member whole; no narrower
    except conflates the two."""
    assert issubclass(NullPickRateError, ScoringError)
    assert not issubclass(NullPickRateError, NullPickPenaltyError)
    assert not issubclass(NullPickPenaltyError, NullPickRateError)
    for raised in (NullPickRateError("rate"), NullPickPenaltyError("charge")):
        assert isinstance(raised, ScoringError)


# -- the arrow to beta-two --------------------------------------------------------


def test_the_rate_composes_into_the_beta_two_term(
    scorer: NullPickScorer,
    committed_picks: list[StandInPick],
    pick: StandInPick,
    panel: dict,
) -> None:
    """The dependency arrow runs one way: the process answers the rate,
    β₂ charges on it — the number crossing the seam is a ``float``, and
    the term's charge is the coefficient times exactly that number.  The
    composition is the whole integration the graph draws (265 → 258):
    the scorer never imports the term, the term never derives the rate."""
    score = world_objective("financial-campaign-01", pick, panel)
    rate = scorer.null_pick_rate(committed_picks)
    moved = null_pick_penalty(score, null_pick_rate=rate)
    assert moved.score == score.score - BETA_TWO_DEFAULT * rate
    assert moved.score == score.score - 0.25  # 0.5 · 0.5, both dyadic
    with pytest.raises(NullPickPenaltyError):
        # The boundary holds the other way too: the term refuses a figure
        # outside the fraction's own bounds, and never reaches for the
        # sidecar to compute one itself.
        null_pick_penalty(score, null_pick_rate=2.0)
