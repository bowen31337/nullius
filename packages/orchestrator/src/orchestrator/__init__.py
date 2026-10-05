"""The orchestrator member: live node evaluation and the campaign driver.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 1,
creates this workspace member (``packages/orchestrator``, import name
``orchestrator``); docs/nullius-tech-architecture.md §3 draws its edges —
the discovery orchestrator calls the frozen evaluator, the null oracle
and the trial ledger, persists through the tree and artifact stores, and
drives the signal agent and the policy runtime.  Spec A of the campaign
driver (this spec) supplies what a live run was missing: the evaluator's
``TreeNodeWriter`` and ``ArtifactWriter`` implementations, a caller of
``evaluator.debit_trial``, a null-aware oracle for nodes below a
campaign's root, configuration loading, and the one-call ``evaluate_node``
that assembles them.  Spec B (``additions_spec_campaign_driver.xml``)
builds the loop itself on top.

*This module at feature 1 holds a docstring and an empty ``__all__``, and
registers no component yet.*  That is a real state of the member, not a
placeholder: the workspace scan imports this package on every
``create_app()``, so an ``__init__`` that exists and registers nothing is
how a member joins the composed application before its first component
lands — composition must not depend on what a member will one day
contribute.  The component this spec eventually adds ("live-evaluator",
feature 8) will be registered here, in this ``__init__`` and in no
submodule, because the loader re-executes a package's ``__init__`` on
every composition but does not re-execute an already-cached submodule —
a ``@register`` that lived in one would fire on the first ``create_app()``
of a process and silently drop out of every later one.

The member's standing rule, fixed by the spec's addition summary: the
evaluator, nulloracle, ledger, artifacts and discovery members are the
read-only trust zone Z0, *called and never changed*.  The pyproject
declares those dependencies — plus signal-agent, providers and
policy-runtime — as workspace sources, and no third-party package: this
member is wiring, and wiring carries no weight of its own.
"""

from __future__ import annotations

__all__ = []
