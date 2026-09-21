"""Feature 213 — a root in structurally dead territory is refused with dead_territory.

app_spec.xml: *"System rejects any root opening in structurally dead territory
such as sub-30-minute liquidity-taking strategies."*
docs/alpha-engine-prd.md §9.4 supplies the list and why it is *configured*
rather than derived — *"Triangular arbitrage, cross-exchange latency
arbitrage, anything with a holding period under ~30 minutes taking liquidity.
Do not let the agent open roots there."*  The node table carries the value it
protects (docs/nullius-tech-architecture.md §9.1: ``theme_root TEXT NOT NULL``).

Each claim in that sentence is tested separately, because a law that satisfied
any three of them would be a different and worse feature:

* **any root opening** — the subject is the territory a branch opens in, not
  the text an agent wrote.  Feature 205's law judges the source; this one
  judges the mechanism, and the two refusals stay distinguishable;
* **in structurally dead territory** — *viability*, not membership.  The
  denylist is read from the committed artifact, and a list that cannot be read
  is refused rather than half-applied;
* **such as sub-30-minute liquidity-taking strategies** — the list is PRD §9.4's
  three, transcribed as slugs, and widening it is the human's decision;
* **is rejected** — the answer is a *value*, the shape every gate in this
  workspace takes, because a campaign driver diagnoses why a branch failed and
  a gate that raised would have taken that decision from the caller.

The refusals are asserted on the *returned value* rather than with
``pytest.raises``, because the law answers as a value.
:meth:`DeadTerritoryVerdict.require` is tested separately, as the one seam
where a refusal becomes an exception.

Two boundaries get their own groups, because both are places a plausible
implementation would be wrong:

* **exact membership, not prefix** — a root that is a near-miss spelling of a
  dead mechanism is a *different* mechanism, not a narrower one, and refusing
  it on a prefix would widen the denylist from inside a submission;
* **this is not §9.3** — feature 212's "outside the legal set" is a *membership*
  finding about a root the human never admitted; this law is a *viability*
  finding about a mechanism that cannot pay for itself however well the signal
  works.  The two questions are independent, so this gate carries nothing of
  feature 212's set, and a root that is *legal* (admitted) can still be *dead*.

A third boundary is the one asymmetry with feature 212, and it is
load-bearing: feature 212's builder fails **closed** on a drifted artifact
(refuses every proposal), while this law's builder fails **open** (admits every
proposal), because a down guardrail refuses fewer proposals than a system that
refuses them all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from signal_agent import (
    COMMITTED_DEAD_TERRITORY,
    DEAD_TERRITORY_CODE,
    DEAD_TERRITORY_POLICY_KIND,
    LIVE_TERRITORY_CODE,
    NOT_A_ROOT_CODE,
    DeadTerritory,
    DeadTerritoryError,
    DeadTerritoryGate,
    DeadTerritoryReason,
    DeadTerritorySetError,
    compile_dead_territory,
    dead_territory_gate,
    load_dead_territory,
)

#: A mechanism the committed denylist names as dead, taken from the artifact's
#: own vocabulary rather than written as a literal here: several claims below
#: are about *the document's own* list, and a constant that happened to name a
#: mechanism the document later dropped would make "the list refuses it" a
#: claim about this file instead.
DEAD_MECHANISM = "sub-30-minute-liquidity-taking"

#: A mechanism the committed denylist does not name — feature 212's legal
#: theme, deliberately, so the two laws are shown to be independent: a root can
#: be legal (admitted by feature 212) and yet live (cleared by feature 213).
LIVE_MECHANISM = "order-flow-imbalance"


# -- the configured dead-territory list --------------------------------------


def test_the_committed_list_is_the_document_the_feature_names() -> None:
    territory = load_dead_territory(COMMITTED_DEAD_TERRITORY)
    assert territory.kind == DEAD_TERRITORY_POLICY_KIND == (
        "signal-agent-dead-territory"
    )
    # PRD §9.4's initial list is three mechanisms; the number is asserted
    # because a fourth arriving unnoticed is a widened denylist, which is the
    # one edit PRD §9.4 says must be deliberate.
    assert len(territory) == 3


def test_the_committed_list_holds_prds_nine_four_three() -> None:
    # Each slug is the machine spelling of one of §9.4's three entries, and
    # each title is that section's own wording.  Asserted as a set of pairs
    # rather than by index so a reordering of the document is not a failure —
    # the order is asserted separately, where it is the claim.
    territory = load_dead_territory(COMMITTED_DEAD_TERRITORY)
    listed = {(slug, territory.title(slug)) for slug in territory}
    assert listed == {
        ("triangular-arbitrage", "Triangular arbitrage"),
        (
            "cross-exchange-latency-arbitrage",
            "Cross-exchange latency arbitrage",
        ),
        (
            "sub-30-minute-liquidity-taking",
            "Anything with a holding period under ~30 minutes taking liquidity",
        ),
    }


def test_the_dead_mechanisms_are_in_the_documents_own_order() -> None:
    # Document order, not sorted: the artifact is reviewed as it is written,
    # and a refusal that listed the mechanisms alphabetically would read
    # differently from the file an operator opens to widen it.
    territory = load_dead_territory(COMMITTED_DEAD_TERRITORY)
    assert territory.slugs() == (
        "triangular-arbitrage",
        "cross-exchange-latency-arbitrage",
        "sub-30-minute-liquidity-taking",
    )


def test_the_titles_are_the_prds_wording_not_this_members_prose() -> None:
    # The title is the half of the answer a human reads.  It is carried from
    # the document rather than described here, so the list and the PRD can be
    # diffed against each other by eye.
    territory = load_dead_territory(COMMITTED_DEAD_TERRITORY)
    assert territory.title(DEAD_MECHANISM) == (
        "Anything with a holding period under ~30 minutes taking liquidity"
    )
    assert territory.title(LIVE_MECHANISM) is None
    assert territory.title(None) is None


def test_a_list_that_cannot_be_read_is_refused_rather_than_half_applied(
    tmp_path: Path,
) -> None:
    # The compile-time half of "System rejects": the document that would widen
    # the denylist past what the deployment wrote is never applied.  Both
    # failure modes of *reading* are covered — a missing file and a malformed
    # one — because they are different accidents with the same repair.
    missing = tmp_path / "absent.json"
    with pytest.raises(DeadTerritorySetError) as unreadable:
        load_dead_territory(missing)
    assert "could not read" in str(unreadable.value)

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(DeadTerritorySetError) as unparsable:
        load_dead_territory(broken)
    assert "not valid JSON" in str(unparsable.value)


def test_a_document_that_does_not_say_what_it_is_cannot_be_read() -> None:
    # A stray JSON file carrying a 'mechanisms' key is not this configuration —
    # the discipline feature 212's committed legal set and feature 167's
    # committed allowlist take for their own markers.
    with pytest.raises(DeadTerritorySetError) as wrong_marker:
        compile_dead_territory({"policy": "something-else", "mechanisms": []})
    assert DEAD_TERRITORY_POLICY_KIND in str(wrong_marker.value)

    with pytest.raises(DeadTerritorySetError) as no_marker:
        compile_dead_territory({"mechanisms": [{"slug": "a", "title": "A"}]})
    assert "must be a non-empty string" in str(no_marker.value)


def test_a_list_naming_no_mechanisms_is_refused_not_compiled() -> None:
    # A dead-territory list that names nothing is not a strict denylist, it is
    # the absence of PRD §9.4's decision ("Do not let the agent open roots
    # there"), and a proposal screened against it would be admitted into
    # territory the human never cleared as live.  The builder's fail-open path
    # reaches an empty list only when the committed artifact cannot be read — a
    # deployment fault it reports, not a decision it makes — and it hand-builds
    # that list rather than asking the compiler.
    with pytest.raises(DeadTerritorySetError) as raised:
        compile_dead_territory(
            {"policy": DEAD_TERRITORY_POLICY_KIND, "mechanisms": []}
        )
    assert "names no mechanisms" in str(raised.value)
    assert "Do not let the agent open roots there" in str(raised.value)


def test_a_slug_that_is_not_a_slug_is_refused_at_compile_time() -> None:
    # The grammar is the document's, not the submission's: an entry written as
    # a title, a sentence or a padded spelling names no theme_root value a
    # proposal could carry, so the list would have a hole no submission fills.
    for bad in (
        "Triangular Arbitrage",
        "triangular arbitrage",
        "-triangular",
        "triangular-",
        "triangular--arbitrage",
        "triangular_arbitrage",
    ):
        with pytest.raises(DeadTerritorySetError) as raised:
            compile_dead_territory(
                {
                    "policy": DEAD_TERRITORY_POLICY_KIND,
                    "mechanisms": [{"slug": bad, "title": "Triangular arb"}],
                }
            )
        assert "must be a lowercase" in str(raised.value)


def test_one_mechanism_listed_twice_is_refused() -> None:
    # Two entries with one slug is one mechanism described twice, and the
    # applied list would carry whichever title came last — drift with extra
    # steps.
    with pytest.raises(DeadTerritorySetError) as raised:
        compile_dead_territory(
            {
                "policy": DEAD_TERRITORY_POLICY_KIND,
                "mechanisms": [
                    {"slug": "triangular-arbitrage", "title": "Triangular arb"},
                    {
                        "slug": "triangular-arbitrage",
                        "title": "Triangular arb, again",
                    },
                ],
            }
        )
    assert "appears twice" in str(raised.value)


def test_an_entry_that_is_not_an_entry_is_refused() -> None:
    for bad_mechanisms in ("not a list", {"slug": "a"}, 7):
        with pytest.raises(DeadTerritorySetError):
            compile_dead_territory(
                {"policy": DEAD_TERRITORY_POLICY_KIND, "mechanisms": bad_mechanisms}
            )


# -- the law: a dead mechanism is refused ------------------------------------


def test_a_dead_mechanism_is_refused_with_the_dead_territory_code(
    territory: DeadTerritoryGate,
) -> None:
    # The feature's own subject: a root in a mechanism §9.4 names as dead.  The
    # refusal opens with the code the feature names, carries the offending
    # spelling verbatim, and lists the whole denylist so the agent can re-open
    # inside a live mechanism.
    admission = territory.admit(DEAD_MECHANISM)
    assert admission.admitted is False
    assert admission.reason is DeadTerritoryReason.DEAD_TERRITORY
    assert admission.detail.startswith(DEAD_TERRITORY_CODE)
    assert repr(DEAD_MECHANISM) in admission.detail
    for mechanism in territory.dead():
        assert mechanism in admission.detail
    # The verdict carries nothing about the refused root — it is refused, so
    # there is no admitted value to read.
    assert admission.theme is None
    assert admission.title is None


def test_a_live_mechanism_is_admitted(territory: DeadTerritoryGate) -> None:
    # The feature's other subject: a root in a mechanism the list does not name.
    # It is admitted — the denylist refuses only what it names — and the
    # admission opens with the live-territory code, not the refusal's.
    admission = territory.admit(LIVE_MECHANISM)
    assert admission.admitted is True
    assert admission.reason is DeadTerritoryReason.LIVE
    assert admission.detail.startswith(LIVE_TERRITORY_CODE)
    assert admission.theme == LIVE_MECHANISM


def test_the_gate_is_independent_of_the_legal_set(territory: DeadTerritoryGate) -> None:
    # The two laws are two gates.  Feature 212's legal theme is, deliberately,
    # a *live* mechanism here: a root can be legal (admitted by feature 212)
    # and yet live (cleared by feature 213).  This gate carries nothing of
    # feature 212's set, so admitting the space is not the same as clearing the
    # mechanism, and refusing the mechanism is not the same as refusing the
    # space.
    assert territory.covers(LIVE_MECHANISM) is False
    assert territory.admit(LIVE_MECHANISM).admitted is True


def test_a_near_miss_of_a_dead_mechanism_is_live(territory: DeadTerritoryGate) -> None:
    # Exact membership, not prefix: a root that is a near-miss spelling of a
    # dead mechanism is a *different* mechanism, not a narrower one, and
    # refusing it on a prefix would widen the denylist from inside a
    # submission.  The same rule feature 212's allowlist holds for its slugs.
    # Each of these is one keystroke from a dead mechanism and none of them is
    # one, so each is live — a near-miss that the denylist refused would be a
    # denylist widened from inside a submission.
    for near_miss in (
        "sub-30-minute-liquidity-taking-v2",
        "sub-30-minute-liquidity",
        "sub-30min-liquidity-taking",
        "sub-30-minute-liquidity-taking ",  # trailing space
    ):
        assert territory.covers(near_miss) is False, near_miss
    # Sanity: the exact spelling is still dead, so the near-misses above are
    # near misses of something, not of nothing.
    assert territory.covers(DEAD_MECHANISM) is True


def test_the_read_side_answers_dead_without_a_verdict(territory: DeadTerritoryGate) -> None:
    # ``covers`` is the read side a deployment should be able to answer without
    # submitting a proposal to find out, and it is *inverted from* feature 212's
    # gate: ``True`` means the mechanism is dead, where feature 212's ``covers``
    # returns ``True`` when a root is legal.  The same word, opposite verdict —
    # the whole reason the two laws are two gates.
    assert territory.covers(DEAD_MECHANISM) is True
    assert territory.covers(LIVE_MECHANISM) is False
    assert territory.covers(None) is False
    assert territory.covers(7) is False


# -- the refusal is a value, not an exception --------------------------------


def test_require_raises_only_for_a_dead_mechanism(territory: DeadTerritoryGate) -> None:
    # ``require`` is the bridge for the caller on its last line before it opens
    # a node, and only there does the exception appear.  A live root returns
    # the slug; a dead one raises feature 213's own error class.
    assert territory.require(LIVE_MECHANISM) == LIVE_MECHANISM
    with pytest.raises(DeadTerritoryError) as raised:
        territory.require(DEAD_MECHANISM)
    assert isinstance(raised.value, DeadTerritoryError)
    assert str(raised.value).startswith(DEAD_TERRITORY_CODE)


def test_a_dead_refusal_is_not_an_illegal_theme_refusal() -> None:
    # The load-bearing distinction feature 212's law is built around: a dead
    # root that wore the illegal-theme class would read as "the human never
    # admitted this space" — the wrong repair and the wrong query.  The two
    # refusals are siblings under the source contract, each greppable on its
    # own class.
    from signal_agent import IllegalThemeError

    territory = dead_territory_gate()
    with pytest.raises(DeadTerritoryError) as raised:
        territory.require(DEAD_MECHANISM)
    assert not isinstance(raised.value, IllegalThemeError)


def test_a_not_a_root_value_is_refused_not_named_dead(territory: DeadTerritoryGate) -> None:
    # A value that is not a theme root — not a string, or a string with nothing
    # in it — is a bug in the *caller*, and an operator looking for a widened
    # denylist would be looking in the wrong place.  Its own reason and code,
    # the discipline feature 212's ``NOT_A_THEME`` and feature 205's
    # ``NOT_SOURCE`` already follow: a refusal that opened with another reason's
    # code would be quoting feature 213's headline while its own text says the
    # root was never a mechanism to judge.
    for bad in ("", "   ", None, 7, ["sub-30-minute-liquidity-taking"]):
        verdict = territory.admit(bad)  # type: ignore[arg-type]
        assert verdict.admitted is False
        assert verdict.reason is DeadTerritoryReason.NOT_A_ROOT
        assert verdict.detail.startswith(NOT_A_ROOT_CODE)
    # And it is a different verdict from the dead one — asserted on the code
    # that opens the sentence, so the two refusals stay distinguishable.
    assert territory.admit(DEAD_MECHANISM).reason is DeadTerritoryReason.DEAD_TERRITORY


# -- the law reached directly ------------------------------------------------


def test_dead_territory_gate_is_the_law_minus_the_composition() -> None:
    # The module-level convenience the member's own tests and any operator
    # script reach: the same call the builder makes, without the factory.
    territory = dead_territory_gate()
    assert isinstance(territory, DeadTerritoryGate)
    assert territory.dead() == load_dead_territory(COMMITTED_DEAD_TERRITORY).slugs()


def test_the_law_does_not_read_the_source_an_agent_wrote(territory: DeadTerritoryGate) -> None:
    # The subject is the *mechanism*, not the text: feature 205's law judges
    # the source and this one judges the territory, and a member that folded
    # the dead-territory check into adoption would have made one verb answer
    # two questions whose repairs differ.  `admit` takes a theme and nothing
    # else — asserted on the signature rather than by inspection, so a later
    # edit that grew a `source` parameter fails here.
    import inspect

    parameters = list(inspect.signature(DeadTerritoryGate.admit).parameters)
    assert parameters == ["self", "theme"]


# -- the neighbouring refusal this is not (feature 212) ----------------------


def test_a_legal_root_can_still_be_cleared(territory: DeadTerritoryGate) -> None:
    # Feature 212's "outside the legal set" is a *membership* finding about a
    # root the human never admitted; this law is a *viability* finding about a
    # mechanism that cannot pay for itself.  The two questions are independent,
    # so a root that is legal (admitted by feature 212) is not automatically
    # dead, and a root that is illegal (outside §9.3) is not automatically
    # cleared by this gate — feature 212 still refuses it.  This law carries
    # nothing of feature 212's set.
    # A legal theme that is also a live mechanism: admitted by both.
    assert territory.admit(LIVE_MECHANISM).admitted is True


def test_the_empty_denylist_admits_everything() -> None:
    # The fail-open path the builder reaches when the committed artifact cannot
    # be read: an empty denylist refuses nothing, so every proposal is
    # admitted.  This is the one asymmetry with feature 212, and it is
    # load-bearing — a down guardrail refuses fewer proposals than a system
    # that refuses them all, and the space (feature 212) still judges it.  The
    # compiler *refuses* an empty list; only the builder's fail-open path
    # reaches one, hand-built.
    empty = DeadTerritoryGate(
        DeadTerritory(kind=DEAD_TERRITORY_POLICY_KIND, mechanisms=())
    )
    assert len(empty.territory) == 0
    assert empty.admit(DEAD_MECHANISM).admitted is True
    assert empty.admit("anything-at-all").admitted is True


# -- the committed artifact is diffable against the PRD ----------------------


def test_the_committed_file_declares_itself_and_lists_only_entries() -> None:
    # The artifact ships beside the law that checks it, so a checkout cannot
    # hold one without the other.  It is read through the same law as any
    # change to it: the compile refuses a drift written to disk exactly as a
    # drift compiled in memory.
    document = json.loads(COMMITTED_DEAD_TERRITORY.read_text(encoding="utf-8"))
    assert document["policy"] == DEAD_TERRITORY_POLICY_KIND
    assert isinstance(document["mechanisms"], list)
    # Every entry is a slug/title pair, and the slugs are the machine spelling
    # the node table's theme_root column holds.
    for entry in document["mechanisms"]:
        assert {"slug", "title"} <= set(entry)
        assert entry["slug"].islower()
        assert " " not in entry["slug"]
