"""The two committed theme sets agree: one hypothesis space, not two.

PRD §9.3 v2 (owner-approved 2026-10-13) lists nine guided theme roots. Two
members each carry a committed copy of that list, for two different callers:
:mod:`discovery` plants a campaign's roots in them
(``discovery.DEFAULT_LEGAL_THEMES``, read by
``orchestrator._campaign._themes_for`` through
:func:`discovery.legal_themes_from_env` whenever ``NULLIUS_LEGAL_THEMES`` is
unset — the default an operator who configured nothing still gets), and
:mod:`signal_agent` refuses a proposal whose theme root falls outside them
(``signal_agent.committed_legal_themes().slugs()``, feature 212). A campaign
planted in a root the authoring agent then refuses every proposal against
would spend a workspace, a node id and an authoring call discovering a
mismatch that this file catches at collection time instead — the two
committed documents are checked against each other, not merely each against
the PRD by eye.

Order matters and is asserted, not just membership: a planner that cycles
``discovery.DEFAULT_LEGAL_THEMES`` by index (``orchestrator._campaign``'s
``_themes_for``) and an authoring prompt that lists
``signal_agent``'s slugs in its own document order would silently disagree
about "theme root #3" if the two committed lists were a reordering of one
another, which plain set equality would miss.

Every committed theme having a brief is asserted here too, rather than left
to signal-agent's own suite: v2's whole reason for being is that each root
carries a mechanism, inputs, a pre-stated expected sign and its risks
(docs/hypothesis-space/themes-v2.md) — a slug the campaign can plant a root
in but the authoring prompt renders nothing for would be v1's silence with a
v2 slug attached, and this is the seam where the two facts (discovery's
default, signal-agent's briefs) are in scope together.
"""

from __future__ import annotations

import discovery
import signal_agent


def test_discovery_default_matches_signal_agents_committed_set() -> None:
    # Same nine slugs, same order — the order a planner cycles through
    # (orchestrator._campaign._themes_for) and the order an authoring
    # prompt lists are the same document's, not two that happen to agree.
    committed = signal_agent.committed_legal_themes()
    assert discovery.DEFAULT_LEGAL_THEMES == committed.slugs()
    assert len(discovery.DEFAULT_LEGAL_THEMES) == 9


def test_every_committed_theme_has_a_brief() -> None:
    # v2's reason for being: a slug with no brief is v1's silence wearing a
    # v2 spelling — the authoring prompt has nothing to render for it.
    committed = signal_agent.committed_legal_themes()
    for slug in committed.slugs():
        brief = committed.brief(slug)
        assert brief is not None, slug
        assert set(brief) == {"mechanism", "inputs", "expected_sign", "notes"}
        for key, value in brief.items():
            assert isinstance(value, str) and value.strip(), (slug, key)


def test_an_unconfigured_deployment_plants_roots_the_agent_may_open_in() -> None:
    # The end-to-end fact the other two assertions exist to guarantee: a
    # deployment that configured NULLIUS_LEGAL_THEMES with nothing (the
    # posture `./run.sh campaign` runs under by default) plants every root in
    # a theme the signal agent's own gate admits.
    legal = discovery.legal_themes_from_env({})
    assert legal is discovery.DEFAULT_THEME_SET
    gate = signal_agent.signal_theme_gate()
    for theme in legal.themes:
        admission = gate.admit(theme)
        assert admission.admitted, (theme, admission.detail)
