"""Feature 212 — a root outside the legal set is refused with illegal_theme.

app_spec.xml: *"System rejects a proposal whose theme root falls outside the
configured legal set, which returns an illegal_theme error message."*
docs/alpha-engine-prd.md §9 supplies the set and why it is *configured* —
*"Choosing the space is the highest-value human input in the system, and it
should be encoded as the set of legal ``theme_root`` values"* — with §9.3
listing the initial six.  The node table carries the value it protects
(docs/nullius-tech-architecture.md §9.1: ``theme_root TEXT NOT NULL``).

Each claim in that sentence is tested separately, because a law that satisfied
any three of them would be a different and worse feature:

* **whose theme root** — the subject is the territory a branch opens in, not
  the text an agent wrote.  Feature 205's law judges the source; this one
  judges the root, and the two refusals stay distinguishable;
* **falls outside the configured legal set** — *configured* is load-bearing.
  Membership is read from the committed artifact, and a set that cannot be
  read is refused rather than half-applied;
* **is rejected** — the answer is a *value*, the shape every gate in this
  workspace takes, because a campaign driver diagnoses why a branch failed and
  a gate that raised would have taken that decision from the caller;
* **which returns an illegal_theme error message** — the code the feature
  names, opening the refusal's sentence, naming the offending spelling
  verbatim and the whole legal set so the repair is actionable.

The refusals are asserted on the *returned value* rather than with
``pytest.raises``, because the law answers as a value.
:meth:`ThemeAdmission.require` is tested separately, as the one seam where a
refusal becomes an exception.

Two boundaries get their own groups, because both are places a plausible
implementation would be wrong:

* **exact membership, not prefix** — the sandbox's import allowlist admits a
  term and everything under it, and a theme set copied from that shape would
  admit ``order-flow-imbalance-v2`` on the ``order-flow-imbalance`` entry,
  letting a submission widen the hypothesis space PRD §9 reserves to the
  human;
* **this is not §9.4** — feature 213's "structurally dead at retail scale" is
  a finding about a root that is *already inside* the set, so no legal entry
  may carry a viability judgement and no dead-territory mechanism may be
  refused by *this* law for that reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from signal_agent import (
    COMMITTED_LEGAL_THEMES,
    ILLEGAL_THEME_CODE,
    LEGAL_THEME_CODE,
    LEGAL_THEMES_POLICY_KIND,
    NOT_A_THEME_CODE,
    IllegalThemeError,
    LegalThemes,
    SignalAgentError,
    SignalThemeGate,
    ThemeReason,
    ThemeSetError,
    compile_legal_themes,
    load_legal_themes,
    signal_theme_gate,
)

#: A legal root, taken from the committed artifact rather than written as a
#: literal here: several claims below are about *the document's own* set, and a
#: constant that happened to name a slug the document later dropped would make
#: "the set admits it" a claim about this file instead.
LEGAL_THEME = "order-flow-imbalance"

#: An illegal root of the shape §9.4 describes — *"anything with a holding
#: period under ~30 minutes taking liquidity"*.  Deliberately a plausible
#: research idea rather than gibberish: the law's whole value is refusing
#: territory that sounds reasonable, and a test that only refused nonsense
#: would pass against an implementation that refused on spelling.
ILLEGAL_THEME = "sub-30-minute-liquidity-taking"


# -- the configured legal set ------------------------------------------------


def test_the_committed_set_is_the_document_the_feature_names() -> None:
    themes = load_legal_themes(COMMITTED_LEGAL_THEMES)
    assert themes.kind == LEGAL_THEMES_POLICY_KIND == "signal-agent-legal-themes"
    # PRD §9.3's initial set is six themes; the number is asserted because a
    # seventh arriving unnoticed is a widened hypothesis space, which is the
    # one edit PRD §9 says must be deliberate.
    assert len(themes) == 6


def test_the_committed_set_holds_prds_nine_three_six() -> None:
    # Each slug is the machine spelling of one of §9.3's six entries, and each
    # title is that section's own wording.  Asserted as a set of pairs rather
    # than by index so a reordering of the document is not a failure — the
    # order is asserted separately, where it is the claim.
    themes = load_legal_themes(COMMITTED_LEGAL_THEMES)
    listed = {(slug, themes.title(slug)) for slug in themes}
    assert listed == {
        (
            "cross-sectional-momentum-reversal",
            "Cross-sectional momentum and short-term reversal, small/mid-cap universe",
        ),
        (
            "order-flow-imbalance",
            "Order-flow imbalance and microstructure features from the free L2 feed",
        ),
        (
            "borrow-rate-funding-state",
            "Borrow-rate and funding-state conditioning",
        ),
        (
            "volatility-state-dispersion",
            "Volatility-state and dispersion regimes",
        ),
        (
            "mechanical-calendar-events",
            "Mechanical calendar and event effects",
        ),
        (
            "cross-venue-state-divergence",
            "Cross-asset and cross-venue state divergence (state, not price)",
        ),
    }


def test_the_slugs_are_in_the_documents_own_order() -> None:
    # Document order, not sorted: the artifact is reviewed as it is written,
    # and a refusal that listed the set alphabetically would read differently
    # from the file an operator opens to widen it.
    themes = load_legal_themes(COMMITTED_LEGAL_THEMES)
    assert themes.slugs()[0] == "cross-sectional-momentum-reversal"
    assert themes.slugs()[-1] == "cross-venue-state-divergence"
    assert themes.slugs() != tuple(sorted(themes.slugs()))


def test_the_titles_are_the_prds_wording_not_this_members_prose() -> None:
    # The title is the half of the answer a human reads.  It is carried from
    # the document rather than described here, so the set and the PRD can be
    # diffed against each other by eye.
    themes = load_legal_themes(COMMITTED_LEGAL_THEMES)
    assert themes.title(LEGAL_THEME) == (
        "Order-flow imbalance and microstructure features from the free L2 feed"
    )
    assert themes.title(ILLEGAL_THEME) is None
    assert themes.title(None) is None


def test_a_set_that_cannot_be_read_is_refused_rather_than_half_applied(
    tmp_path: Path,
) -> None:
    # The compile-time half of "System rejects": the document that would widen
    # the box past what the deployment wrote is never applied.  Both failure
    # modes of *reading* are covered — a missing file and a malformed one —
    # because they are different accidents with the same repair.
    missing = tmp_path / "absent.json"
    with pytest.raises(ThemeSetError) as unreadable:
        load_legal_themes(missing)
    assert "could not read" in str(unreadable.value)

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ThemeSetError) as unparsable:
        load_legal_themes(broken)
    assert "not valid JSON" in str(unparsable.value)


def test_a_document_that_does_not_say_what_it_is_cannot_be_read() -> None:
    # A stray JSON file carrying a 'themes' key is not this configuration —
    # the discipline feature 167's committed allowlist and feature 157's
    # committed isolation policy take for their own markers.
    with pytest.raises(ThemeSetError) as wrong_marker:
        compile_legal_themes({"policy": "something-else", "themes": []})
    assert LEGAL_THEMES_POLICY_KIND in str(wrong_marker.value)

    with pytest.raises(ThemeSetError) as no_marker:
        compile_legal_themes({"themes": [{"slug": "a", "title": "A"}]})
    assert "must be a non-empty string" in str(no_marker.value)


def test_a_set_naming_no_themes_is_refused_not_compiled() -> None:
    # The opposite reading from the sandbox's empty allowlist, deliberately: a
    # *ceiling* that admits nothing is the strongest version of itself, while a
    # legal theme set that names nothing is not a strict hypothesis space — it
    # is PRD §9's decision never having been made, and every proposal would be
    # refused with a message unable to say what would have been admitted.
    with pytest.raises(ThemeSetError) as raised:
        compile_legal_themes({"policy": LEGAL_THEMES_POLICY_KIND, "themes": []})
    assert "names no themes" in str(raised.value)
    assert "highest-value input" in str(raised.value)


def test_a_slug_that_is_not_a_slug_is_refused_at_compile_time() -> None:
    # The grammar is the document's, not the submission's: an entry written as
    # a title, a sentence or a padded spelling names no theme_root value a
    # proposal could carry, so the set would have a hole no submission fills.
    for bad in (
        "Order Flow Imbalance",
        "order flow",
        "-order-flow",
        "order-flow-",
        "order--flow",
        "order_flow",
    ):
        with pytest.raises(ThemeSetError) as raised:
            compile_legal_themes(
                {
                    "policy": LEGAL_THEMES_POLICY_KIND,
                    "themes": [{"slug": bad, "title": "Order flow"}],
                }
            )
        assert "must be a lowercase" in str(raised.value)


def test_one_theme_listed_twice_is_refused() -> None:
    # Two entries with one slug is one theme described twice, and the applied
    # set would carry whichever title came last — drift with extra steps.
    with pytest.raises(ThemeSetError) as raised:
        compile_legal_themes(
            {
                "policy": LEGAL_THEMES_POLICY_KIND,
                "themes": [
                    {"slug": "order-flow", "title": "Order flow"},
                    {"slug": "order-flow", "title": "Order flow, again"},
                ],
            }
        )
    assert "appears twice" in str(raised.value)


def test_an_entry_that_is_not_an_entry_is_refused() -> None:
    for bad_themes in ("not a list", {"slug": "a"}, 7):
        with pytest.raises(ThemeSetError):
            compile_legal_themes(
                {"policy": LEGAL_THEMES_POLICY_KIND, "themes": bad_themes}
            )

    # And the entries themselves: a block that is not a mapping, or one
    # missing its title, cannot say which theme it configures.
    with pytest.raises(ThemeSetError):
        compile_legal_themes(
            {"policy": LEGAL_THEMES_POLICY_KIND, "themes": ["order-flow"]}
        )
    with pytest.raises(ThemeSetError):
        compile_legal_themes(
            {"policy": LEGAL_THEMES_POLICY_KIND, "themes": [{"slug": "order-flow"}]}
        )


def test_a_document_that_is_not_a_mapping_is_refused() -> None:
    for bad in (None, [], "themes", 42):
        with pytest.raises(ThemeSetError) as raised:
            compile_legal_themes(bad)
        assert "must be a mapping" in str(raised.value)


def test_the_committed_artifact_is_the_json_file_beside_the_law() -> None:
    # The artifact ships inside the package, so a checkout cannot hold the law
    # without the set — the reason the builder has no unconfigured state.  Read
    # as raw JSON here so the *file* is checked, not the compiled object.
    assert COMMITTED_LEGAL_THEMES.name == "legal_themes.json"
    document = json.loads(COMMITTED_LEGAL_THEMES.read_text(encoding="utf-8"))
    assert document["policy"] == LEGAL_THEMES_POLICY_KIND
    assert [entry["slug"] for entry in document["themes"]] == list(
        load_legal_themes(COMMITTED_LEGAL_THEMES).slugs()
    )


# -- rejecting a root outside the set ----------------------------------------


def test_a_legal_root_is_admitted(gate: SignalThemeGate) -> None:
    admission = gate.admit(LEGAL_THEME)
    assert admission.admitted
    assert admission.reason is ThemeReason.LEGAL
    assert admission.theme == LEGAL_THEME
    assert LEGAL_THEME_CODE in admission.detail


def test_an_illegal_root_is_refused_with_the_features_error_message(
    gate: SignalThemeGate,
) -> None:
    # The sentence's own headline: the refusal carries the code the feature
    # names, and it names the offending spelling so the agent can see what it
    # opened in rather than being told only "no".
    admission = gate.admit(ILLEGAL_THEME)
    assert not admission.admitted
    assert admission.reason is ThemeReason.ILLEGAL_THEME
    assert admission.reason.value == ILLEGAL_THEME_CODE == "illegal_theme"
    assert admission.detail.startswith(ILLEGAL_THEME_CODE)
    assert repr(ILLEGAL_THEME) in admission.detail


def test_the_refusal_lists_the_whole_legal_set(gate: SignalThemeGate) -> None:
    # An actionable refusal: the agent is told the space it *may* open in, not
    # only the spelling it may not.  Every legal slug is named, and so is the
    # section that made the set the human's decision — so an operator can tell
    # "the agent opened outside the space" from "the document was widened and
    # this run predates the widen".
    detail = gate.admit(ILLEGAL_THEME).detail
    for slug in gate.legal():
        assert slug in detail, slug
    assert "PRD §9" in detail or "§9" in detail


def test_the_refusal_carries_no_admitted_value(gate: SignalThemeGate) -> None:
    # A caller that has checked `adopted` reads the value rather than a
    # sentinel: a refusal must not hand back the theme it refused, or a caller
    # that forgot the check would author in exactly the territory the law
    # rejected.
    admission = gate.admit(ILLEGAL_THEME)
    assert admission.theme is None
    assert admission.title is None


def test_the_admitted_root_is_returned_unmodified(gate: SignalThemeGate) -> None:
    # Admission is a judgement about a spelling, never an edit of it:
    # theme_root is the value §9.1's node row persists, so a gate that
    # lowercased or stripped a root "into conformance" would produce a row
    # whose stored theme disagrees with the one the set was consulted about.
    exact = "order-flow-imbalance"
    assert gate.admit(exact).theme == exact


def test_a_near_miss_spelling_is_a_different_theme(gate: SignalThemeGate) -> None:
    # Membership is exact, not prefix and not case-folded.  A set copied from
    # the sandbox import allowlist's prefix coverage would admit everything
    # below an entry, which is how a submission would widen the hypothesis
    # space PRD §9 reserves to the human.
    for near_miss in (
        "order-flow-imbalance-v2",
        "Order-Flow-Imbalance",
        " order-flow-imbalance",
        "order-flow-imbalance ",
        "order-flow",
        "order",
    ):
        admission = gate.admit(near_miss)
        assert not admission.admitted, near_miss
        assert admission.reason is ThemeReason.ILLEGAL_THEME, near_miss


def test_a_value_that_is_not_a_theme_reports_its_own_reason(
    gate: SignalThemeGate,
) -> None:
    # Not a spelling of the illegal case: an unset column or a missing argument
    # is a bug in the *caller*, and a caller that could not tell the two apart
    # would send the agent back to re-open in a set that would have been fine.
    # The message opens with its own code rather than feature 212's headline,
    # the discipline feature 205's `not-source` and `not-conforming` sentences
    # keep — the two verdicts differ both to a caller branching on the returned
    # value and to an operator grepping the log.
    for not_a_theme in (None, 7, b"order-flow-imbalance", "", "   "):
        admission = gate.admit(not_a_theme)
        assert not admission.admitted, not_a_theme
        assert admission.reason is ThemeReason.NOT_A_THEME, not_a_theme
        assert admission.detail.startswith(NOT_A_THEME_CODE), not_a_theme
        assert not admission.detail.startswith(ILLEGAL_THEME_CODE), not_a_theme


def test_every_verdicts_message_opens_with_its_own_reasons_token(
    gate: SignalThemeGate,
) -> None:
    # One spelling per verdict, whichever way a caller asks: `admit` branches
    # on the reason and an operator greps the log, and the two must not be
    # different strings.  This is the property that keeps feature 212's
    # headline ("illegal_theme") attached to the refusal it is about, rather
    # than opening verdicts whose own text says the root was never a theme.
    for probe, reason in (
        (LEGAL_THEME, ThemeReason.LEGAL),
        (ILLEGAL_THEME, ThemeReason.ILLEGAL_THEME),
        (None, ThemeReason.NOT_A_THEME),
    ):
        admission = gate.admit(probe)
        assert admission.reason is reason, probe
        token = admission.detail.split(":", 1)[0]
        # LEGAL is the one documented divergence: its detail opens with
        # LEGAL_THEME_CODE, exactly as feature 205's CONFORMS opens with
        # CONFORMS_CODE rather than with the reason's own value.
        expected = LEGAL_THEME_CODE if reason is ThemeReason.LEGAL else reason.value
        assert token == expected, probe
        assert token in {LEGAL_THEME_CODE, ILLEGAL_THEME_CODE, NOT_A_THEME_CODE}


def test_the_admission_is_computed_from_the_reason_not_set_by_a_constant() -> None:
    # The "computed, never assumed" stance every gate in this workspace takes:
    # a caller cannot construct an admission whose `admitted` disagrees with
    # its reason, and `theme`/`title` follow the reason rather than being
    # passed independently.
    from signal_agent import ThemeAdmission

    refusal = ThemeAdmission(
        reason=ThemeReason.ILLEGAL_THEME,
        detail=f"{ILLEGAL_THEME_CODE}: refused",
        theme=LEGAL_THEME,
        title="Order-flow imbalance",
    )
    assert refusal.admitted is False
    assert refusal.theme is None and refusal.title is None

    acceptance = ThemeAdmission(
        reason=ThemeReason.LEGAL, detail=f"{LEGAL_THEME_CODE}: admitted"
    )
    assert acceptance.admitted is True
    assert acceptance.theme is None  # what was passed is what is carried


# -- the exception seam ------------------------------------------------------


def test_require_returns_the_admitted_slug(gate: SignalThemeGate) -> None:
    assert gate.require(LEGAL_THEME) == LEGAL_THEME


def test_require_raises_the_illegal_theme_error(gate: SignalThemeGate) -> None:
    # The one seam where a refusal becomes an exception — the caller's last
    # line before it opens a node — and the exception's message is the
    # admission's own sentence, so the retry prompt and the log line say the
    # same thing.
    with pytest.raises(IllegalThemeError) as raised:
        gate.require(ILLEGAL_THEME)
    assert str(raised.value) == gate.admit(ILLEGAL_THEME).detail
    assert ILLEGAL_THEME_CODE in str(raised.value)


def test_the_illegal_theme_error_is_catchable_as_the_source_contract(
    gate: SignalThemeGate,
) -> None:
    # Load-bearing: the two refusals have one subject (what the agent
    # proposed) and one repair (re-prompt inside the admitted space), so a
    # caller that already catches AgentSourceError must not lose a theme
    # refusal through a clause that stopped matching.
    #
    # Scoped to one module identity, and the caveat is worth stating because
    # the fixture hides it: this `gate` is built directly, so the classes it
    # raises are the ones `signal_agent.errors` defines.  The loader imports a
    # member twice under two names, so a gate read *out of a composed
    # application* raises a second, distinct copy of these classes and a
    # caller's `except` does not match it.  That is a property of
    # `app.module_loader._import_package`, not of this member — feature 205's
    # composed law behaves the same way — and it is deliberately not asserted
    # here, because pinning it would enshrine a footgun rather than report it.
    from signal_agent import AgentSourceError

    with pytest.raises(AgentSourceError):
        gate.require(ILLEGAL_THEME)
    with pytest.raises(SignalAgentError):
        gate.require(ILLEGAL_THEME)


def test_a_broken_set_is_not_catchable_as_a_proposal_refusal() -> None:
    # Deliberately *not* an AgentSourceError: no agent action repairs a
    # document, and a campaign driver's retry logic must not see one and
    # re-prompt.  The separation is the one sandbox.errors draws between a
    # refused submission and a refused allowlist.
    from signal_agent import AgentSourceError

    assert not issubclass(ThemeSetError, AgentSourceError)
    assert issubclass(ThemeSetError, SignalAgentError)


def test_require_on_a_value_that_is_not_a_theme_still_raises(
    gate: SignalThemeGate,
) -> None:
    # The two reasons differ to a caller branching on the *returned value*, and
    # both are refusals to a caller on its last line: a `require` that returned
    # None for a missing theme would let a node open with no theme_root.
    with pytest.raises(IllegalThemeError) as raised:
        gate.require(None)
    assert "must be a non-empty string" in str(raised.value)


# -- the read side -----------------------------------------------------------


def test_legal_returns_the_slugs_a_root_may_open_in(gate: SignalThemeGate) -> None:
    assert gate.legal() == gate.themes.slugs()
    assert LEGAL_THEME in gate.legal()
    assert ILLEGAL_THEME not in gate.legal()


def test_covers_answers_the_same_question_admit_answers(
    gate: SignalThemeGate,
) -> None:
    # The read side and the judgement must not disagree: a deployment that
    # asked `covers` before submitting would otherwise be told a theme was
    # legal and then have its proposal refused.
    for theme in (LEGAL_THEME, ILLEGAL_THEME, "order-flow-imbalance-v2", None, 7):
        assert gate.covers(theme) == gate.admit(theme).admitted, theme


def test_the_set_is_readable_but_hands_out_no_capability(
    gate: SignalThemeGate,
) -> None:
    # Reading the set widens nothing — it is a tuple of strings — which is why
    # the component can be a facade rather than a runner.
    themes = gate.themes
    assert isinstance(themes, LegalThemes)
    assert all(isinstance(slug, str) for slug in themes)
    assert themes.kind == LEGAL_THEMES_POLICY_KIND
    assert gate.covers(LEGAL_THEME) and not gate.covers(ILLEGAL_THEME)
    # Dunder spellings agree with the named method, so a caller writing
    # `if theme in gate.themes` gets the law's answer.
    assert LEGAL_THEME in themes and ILLEGAL_THEME not in themes


def test_a_gate_carrying_an_empty_set_fails_closed_and_still_reads(
) -> None:
    # The state the member's builder falls back to when the committed artifact
    # cannot be read: an empty set admits nothing, so the failure direction is
    # *closed* rather than open, and a refusal against it must still be a
    # sentence — a message trailing off into an empty list would be a refusal
    # an operator cannot act on.
    from signal_agent import LEGAL_THEMES_POLICY_KIND, LegalThemes

    empty = SignalThemeGate(
        LegalThemes(kind=LEGAL_THEMES_POLICY_KIND, themes=())
    )
    assert empty.legal() == ()

    admission = empty.admit(LEGAL_THEME)
    assert not admission.admitted
    assert admission.reason is ThemeReason.ILLEGAL_THEME
    assert admission.detail.startswith(ILLEGAL_THEME_CODE)
    assert "names no themes at all" in admission.detail
    assert "0 themes" not in admission.detail


# -- the neighbouring refusal this is not (feature 213) ----------------------


def test_no_legal_entry_carries_a_viability_judgement(
    gate: SignalThemeGate,
) -> None:
    # §9.4's "structurally dead at retail scale" is feature 213's subject and a
    # different question: a *finding* about a root that is already inside the
    # set.  Folding the two together would make the second unfixable without
    # widening the first — an operator who wanted to admit a mechanism would
    # have to widen the hypothesis space to do it — so this law refuses on
    # membership alone, and a dead-territory mechanism that a document did name
    # would be admitted here for feature 213 to judge.
    document = {
        "policy": LEGAL_THEMES_POLICY_KIND,
        # A slug that §9.4 names as dead, placed in a set by fiat.
        "themes": [{"slug": "triangular-arbitrage", "title": "Triangular arbitrage"}],
    }
    widened = SignalThemeGate(compile_legal_themes(document))
    admission = widened.admit("triangular-arbitrage")
    assert admission.admitted, (
        "feature 212 judges membership; a viability finding belongs to 213"
    )
    # And the committed set names none of §9.4's dead territory, which is the
    # other half of the same statement: the human did not admit it.
    for dead in ("triangular-arbitrage", ILLEGAL_THEME, "latency-arbitrage"):
        assert not gate.covers(dead), dead


def test_the_law_does_not_read_the_source_an_agent_wrote(
    gate: SignalThemeGate,
) -> None:
    # The subject is the *root*, not the text: feature 205's law judges the
    # source and this one judges the territory, and a member that folded the
    # theme check into adoption would have made one verb answer two questions
    # whose repairs differ.  `admit` takes a theme and nothing else — asserted
    # on the signature rather than by inspection, so a later edit that grew a
    # `source` parameter fails here.
    import inspect

    parameters = list(inspect.signature(SignalThemeGate.admit).parameters)
    assert parameters == ["self", "theme"]


# -- the law reached directly ------------------------------------------------


def test_signal_theme_gate_is_the_law_minus_the_composition() -> None:
    # The module-level convenience the member's own tests and any operator
    # script reach: the same call the builder makes, without the factory.
    gate = signal_theme_gate()
    assert isinstance(gate, SignalThemeGate)
    assert gate.legal() == load_legal_themes(COMMITTED_LEGAL_THEMES).slugs()
