"""additions_spec_guided_themes.xml, feature 3 — the node's theme brief and
the shared construction rules render into the authoring prompt.

PRD §9.3 v2's whole point: a prompt that names only a theme's slug leaves the
agent to guess a mechanism, and three pre-registered M2 pivots failed on that
set (docs/hypothesis-space/themes-v2.md).  v2 commits a brief — mechanism,
inputs, expected sign, notes — for each of its nine guided roots, and five
shared construction rules; this suite pins that the rendered system message
carries a node's own brief and the shared rules, that an unbriefed theme root
renders ``theme_brief`` as ``None`` rather than a refusal, and that every
other task key is unchanged.

No module-level state, so the suite is order- and worker-independent under
pytest-xdist.
"""

from __future__ import annotations

from types import SimpleNamespace

from signal_agent import committed_legal_themes
from signal_agent._authoring_prompt import build_authoring_prompt, to_request

#: The committed legal set, read once for this module's own fixtures — the
#: same artifact :func:`signal_agent._authoring_prompt._theme_brief_part`
#: reads, so a slug added or removed there is picked up here without this
#: suite hard-coding a count or a spelling of its own.
_THEMES = committed_legal_themes()


def _workspace(theme_root: str) -> SimpleNamespace:
    return SimpleNamespace(
        campaign_id="8f14e45f-cea3-4f93-8d2e-000000000003",
        theme_root=theme_root,
        depth=1,
    )


def _system(parts) -> str:
    return to_request(parts, model="test-model", temperature=0.0, max_tokens=512).messages[0].content


# -- every one of the nine committed slugs carries its own brief -------------


def test_nine_committed_slugs_are_the_fixture_this_suite_sweeps() -> None:
    # A sanity check on the fixture itself, not a restatement of
    # test_themes.py's own law: if the committed set ever shrinks below ten,
    # this suite's "for each of the slugs" sweep below should say so rather
    # than silently sweep fewer.
    assert len(_THEMES.slugs()) == 10


def test_each_committed_slugs_mechanism_and_expected_sign_render_in_the_system_message() -> None:
    for slug in _THEMES.slugs():
        brief = _THEMES.brief(slug)
        assert brief is not None, slug
        parts = build_authoring_prompt(_workspace(slug), (), clause="clause text")
        assert parts.task["theme_brief"]["mechanism"] == brief["mechanism"]
        assert parts.task["theme_brief"]["expected_sign"] == brief["expected_sign"]
        assert parts.task["theme_brief"]["inputs"] == brief["inputs"]
        assert parts.task["theme_brief"]["notes"] == brief["notes"]

        system = _system(parts)
        assert brief["mechanism"] in system, slug
        assert brief["expected_sign"] in system, slug


def test_each_committed_slugs_system_message_carries_the_five_shared_rules() -> None:
    rules = _THEMES.construction_rules()
    assert len(rules) == 5
    for slug in _THEMES.slugs():
        parts = build_authoring_prompt(_workspace(slug), (), clause="clause text")
        assert list(parts.task["theme_brief"]["construction_rules"]) == list(rules)

        system = _system(parts)
        for rule in rules:
            assert rule in system, (slug, rule)


def test_each_committed_slugs_brief_states_expected_sign_is_pre_registered() -> None:
    for slug in _THEMES.slugs():
        parts = build_authoring_prompt(_workspace(slug), (), clause="clause text")
        statement = parts.task["theme_brief"]["pre_registration"]
        assert "pre-registered" in statement
        assert "different hypothesis" in statement
        assert statement in _system(parts)


# -- the tenth root, multi-theme-composite, names its five components --------


def test_multi_theme_composite_brief_names_its_five_components_and_is_equal_weight() -> None:
    # The owner-approved tenth root (2026-10-13, the v2 RESULT file): a
    # workspace opened in it must see which five v2 roots it composites and
    # that the weighting is equal, not fitted — the two facts a child
    # refining this root needs before it may touch windows or smoothing.
    parts = build_authoring_prompt(
        _workspace("multi-theme-composite"), (), clause="clause text"
    )
    brief = parts.task["theme_brief"]
    assert brief is not None

    system = _system(parts)
    for component in (
        "attention-volume",
        "funding-crowding",
        "low-volatility",
        "oi-price-divergence",
        "intermediate-momentum",
    ):
        assert component in brief["mechanism"], component
        assert component in system, component
    assert "equal" in brief["mechanism"].lower()
    assert "equal" in system.lower()


# -- an unknown slug: theme_brief is null, never a refusal --------------------


def test_an_unknown_theme_root_renders_theme_brief_null_and_the_prompt_builds() -> None:
    for unknown in ("not-a-real-theme", "momentum", "cross-sectional-momentum"):
        assert _THEMES.brief(unknown) is None, unknown
        parts = build_authoring_prompt(_workspace(unknown), (), clause="clause text")
        assert parts.task["theme_brief"] is None

        system = _system(parts)
        assert '"theme_brief": null' in system


# -- every other task key is unchanged against a pinned rendering ------------


def test_the_other_task_keys_are_unchanged_against_a_pinned_rendering() -> None:
    workspace = _workspace("low-volatility")
    parts = build_authoring_prompt(workspace, (), clause="clause text")

    assert set(parts.task) == {
        "campaign_id",
        "theme_root",
        "depth",
        "contract",
        "answer_format",
        "cost_awareness",
        "theme_brief",
    }
    assert parts.task["campaign_id"] == workspace.campaign_id
    assert parts.task["theme_root"] == "low-volatility"
    assert parts.task["depth"] == 1
    assert parts.task["answer_format"]["mechanism_line"].startswith(
        "Exactly one line starting 'Mechanism:'"
    )
    assert parts.task["cost_awareness"]["cadence"] == "unmeasured"
    assert parts.task["cost_awareness"]["per_rebalance_cost_bps"] == "unmeasured"


def test_an_unbriefed_theme_roots_other_task_keys_are_unaffected() -> None:
    workspace = _workspace("not-a-real-theme")
    parts = build_authoring_prompt(workspace, (), clause="clause text")

    assert set(parts.task) == {
        "campaign_id",
        "theme_root",
        "depth",
        "contract",
        "answer_format",
        "cost_awareness",
        "theme_brief",
    }
    assert parts.task["theme_brief"] is None
    assert parts.task["campaign_id"] == workspace.campaign_id
    assert parts.task["theme_root"] == "not-a-real-theme"
