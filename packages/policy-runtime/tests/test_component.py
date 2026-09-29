"""Feature 217, the component — how the observed accessor composes into the
running system.

app_spec.xml, "Exploration Policy Runtime", feature 217: the observed accessor
is exposed through a ``@register`` component named ``policy-runtime``, read back
with ``create_app().get("policy-runtime")``.  These tests pin the composition:

* **the component is registered under its name and composed by the factory** —
  the ``@register`` seam the factory discovers, so ``create_app()`` carries a
  ``policy-runtime`` component among the components it composes;
* **the component takes no arguments and resolves the tree itself** — the
  factory's builder protocol is ``builder() -> value``; the builder resolves the
  tree from the deployment's artifact store, returning ``None`` for a
  deployment that names no store rather than raising (the degrade-don't-break
  stance every store-bound builder in this workspace takes, because the factory
  builds every registered component on every ``create_app()`` and a builder
  that raised would take composition down for every unrelated feature);
* **the composed application answers the component's name** —
  ``app.get("policy-runtime")`` is ``None`` over a deployment that names no
  campaign, never an exception.
"""

from __future__ import annotations

import pytest

from policy_runtime import (
    CAMPAIGN_TREE_COMPONENT,
    CampaignTree,
    build_campaign_tree,
    build_campaign_tree_component,
    policy_question,
)


def test_builder_takes_no_arguments() -> None:
    # The factory's builder protocol is ``builder() -> value`` — the component
    # is registered under a name and the factory calls it with no arguments, so
    # a builder that took an argument would not be a component the factory could
    # compose.  Calling it with no arguments resolves the tree the deployment's
    # store holds.
    result = build_campaign_tree()
    assert result is None or isinstance(result, CampaignTree)


def test_builder_degrades_to_none_without_a_campaign() -> None:
    # The factory builds every component on every ``create_app()`` over a bare
    # app, so a component that raised on an absent store would break every app —
    # it degrades to ``None`` instead.  This environment names no campaign, so
    # the builder resolves ``None`` — a discoverable state, not an error.
    assert build_campaign_tree() is None


def test_builder_is_the_registered_component() -> None:
    # The second spelling of the builder is the same function object the
    # ``@register`` decorator registered — so the component the factory composed
    # under ``policy-runtime`` and the builder a script calls are one, and
    # registering the alias would have put two components of one name in the
    # registry (the later import silently winning), the hazard
    # ``app.module_loader`` documents.
    assert build_campaign_tree_component is build_campaign_tree


def test_component_is_registered_under_its_name() -> None:
    # The component is registered under its name — the ``@register`` seam the
    # factory discovers — so ``create_app()`` composes a ``policy-runtime``
    # component among the components it carries.
    from app.module_loader import create_app

    app = create_app()
    assert CAMPAIGN_TREE_COMPONENT in app.components


def test_component_degrades_to_none_without_a_store() -> None:
    # The composed application answers ``None`` for the component when the
    # deployment names no store — so a policy reading it over a bare app reads
    # nothing, and composition never raises on an absent deployment.  This
    # environment names no campaign, so the component resolves ``None``.
    from app.module_loader import create_app

    assert create_app().get(CAMPAIGN_TREE_COMPONENT) is None


def test_component_tree_answers_the_observed_accessor() -> None:
    # The whole composition: the component resolves a tree, and the observed
    # accessor answers over it — so a policy handed the component's tree and
    # a question over it reads the honest observed mapping, prefix-only.  A tree
    # is built directly here (not through the store) to pin that a question over
    # the resolved tree answers the observed accessor — the property the replay
    # scorer depends on when it fronts a policy over the composed tree.
    tree = CampaignTree.freeze(
        {
            "n0": (None, 0, {"depth": 0}),
            "n1": (
                "n0",
                1,
                {"parent_id": "n0", "depth": 1, "r2_insample": 0.20},
            ),
        }
    )
    question = policy_question(tree)
    question.reveal("n1")
    assert set(question.observed()) == {"n1"}
    assert question.observed()["n1"].r2_insample == 0.20
