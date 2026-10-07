"""Feature 7 — the LLM author: one node in, one authored signal out.

additions_spec_llm_authoring.xml, "Authoring Foundation", feature 7: *System
authors a refined signal with
``signal_agent._llm_author.LLMSignalAuthor(session, *, history_store,
contract, anti_convergence, guidance, config, max_retries=1)``.  It is a
callable taking a discovery :class:`~discovery.NodeWorkspace`, and it creates
an :class:`AuthoredSignal` with ``code``, ``stated_mechanism``, ``proposal``
and ``record``.*

This module is the join the addition's first six features were built for.
Feature 5 (:mod:`signal_agent._authoring_prompt`) knows how to shape the C3
prompt from a workspace, a history and the committed clause; feature 6
(:mod:`signal_agent._authored`) knows how to read a model's answer into
``code``, ``stated_mechanism`` and ``proposal``; feature 2/3 of the providers
member state what the deployment authors with and hand back the provider a
role is served by; feature 4 of the signal-agent member's sibling laws
(:mod:`signal_agent._guidance`, :mod:`signal_agent._anti_convergence`,
:mod:`signal_agent._authoring`) are the gates a proposal must survive.  What
is missing is the *order* those pieces run in and the *retry* around the ones
a model can repair — and that is the whole of this object.  It owns no store,
no table and no schema; it is a callable a campaign driver hands to
:class:`discovery.NodeExpansion` in place of the stub agent, and every fact it
needs it is handed at construction.

The child, and how a role is read off it
----------------------------------------

The workspace is a *parent*: the refined signal becomes the parent's first
child, so the author derives the child the same way the tree does —
``uuid.uuid5(discovery.EXPANSION_NAMESPACE, str(parent node_id))`` for the id
and ``workspace.depth + 1`` for the depth.  It derives both itself, from the
same two rules :mod:`discovery.expansion` states, rather than reading them off
anything, because the id and the depth are what the record and the provider
routing are keyed by and a second caller-supplied pair could disagree with the
tree's own.  ``providers.role_for_depth(child_depth)`` then names the §14.1
role — the rotated frontier tier for a child at depth ≤ 1, the one cheap depth
model below — and ``session.provider_for(role, campaign_id=…, node_id=child_id)``
answers the ``(provider, pin)`` that serves it, the pin rotating for a root
exactly as feature 3 routes it.

Why the whole history is read, and never summarised
---------------------------------------------------

The prompt is built by feature 5 from ``history_store.history(campaign_id)``
— *every* prior node of the campaign, in the store's own order — and each
:class:`~signal_agent.PriorProposal` is paired with
``history_store.load(node_id).score``, so a prior proposal arrives beside the
figure it measured rather than as prose.  Nothing is sampled, truncated or
summarised: PRD §C3 and architecture §14.1 make the whole history the replay
object the agent reads, and feature 206's law is the guard over that
wholeness — this module only carries what the store gives it.  A node with no
recorded score is carried as ``None`` (the honest absence feature 5 renders),
never skipped, because the *set* is what the anti-convergence check compares
against.

The two refusals that happen before the call
--------------------------------------------

The prompt is screened twice before a single token is spent:
:meth:`~signal_agent.PromptGuidanceGate.require` on the named parts (feature
208 — an injected summarized-guidance section refuses the whole prompt), and
:meth:`~signal_agent.AntiConvergenceGate.require_in` on the rendered system
message (feature 210 — the committed clause must appear verbatim).  Both
raise their own gate's error and neither is retried: the agent has not been
called, so there is no answer to repair, and the defect is the caller's
assembly rather than the model's output.  Refusing *here* rather than after
the call is what keeps a malformed campaign from spending its first trial
charge on a prompt no gate would have admitted.

What is retried, and what is not
--------------------------------

Once the answer is in hand it is read by feature 6 (``parse_authored``) and,
if it parses, judged by feature 205's contract (:meth:`~signal_agent.
SignalContract.adopt`) and feature 210's anti-convergence gate
(:meth:`~signal_agent.AntiConvergenceGate.admit`, ``held`` = the *code* read
out of each prior proposal — feature 6's parse again, with a prior whose
document does not parse held at its recorded ``code_hash``; see
:meth:`_held_code`).  Three failures are *the model's to repair* and are retried
up to ``max_retries`` times: an unparseable answer, a source that does not
conform, and a structure the campaign already holds.  Each retry appends the
assistant's answer as a turn and a user turn naming the defect — the refusal's
code word, the adoption's own problem sentences, or the gate's code word — so
the model is told *what* to fix rather than that it answered wrong.  After the
last failed retry the whole authoring is refused as
:class:`AuthoringRefusedError`, whose ``authoring_refused`` code word opens the
sentence and whose body carries the last defect.

Two failures are **never** retried and propagate unchanged:
:class:`~providers.BudgetExhaustedError` (the campaign's budget for the pin is
gone — another call would be refused before it was sent, and the retry loop
must not spin against a wall) and :class:`~providers.ServedModelMismatchError`
(the vendor served a model the pin never named — the answer's provenance is
wrong, and re-asking would only ask the same vendor again for another wrong
answer).  Both are caught by *not* being caught: the loop catches exactly the
three model-repairable classes and nothing else.

The record, and what it costs
-----------------------------

Every call — a first attempt and each retry — is counted, and the
:class:`~providers.AuthoringRecord` this author hands back carries the usage
**summed over every call**, because a retry's spend is part of what the
authoring cost and a record holding only the last call's figure would
under-report the budget the pin just drew down.  The record also carries the
child's id and depth, the role, the pin, the sampling the config rolled, the
model that actually served the answer (feature 3's :func:`~providers.
require_served` has already checked it is the pinned one), and — for a root —
the declared frontier tier, which feature 4's recorder files against the
rotation.

A campaign's opening signal: ``author_root``
---------------------------------------------

additions_spec_campaign_driver.xml, "Roots" feature 1: a root has no parent to
derive a child id from, so :meth:`LLMSignalAuthor.author_root` takes the
caller's own ``root_id`` as the node being authored, fixes its depth at 0 and
its role at ``"root"``, and otherwise walks the *same* path ``__call__`` does
— the same history read, the same prompt build and pre-call gates (feature
208's guidance gate, feature 210's clause gate), the same parse/adopt/
anti-convergence retry loop (:meth:`_author`, unchanged and shared by both),
and the same two propagated refusals.  ``__call__`` itself is untouched: the
two callers build their own workspace-shaped value and their own prompt
inline, rather than share a third method, so ``__call__``'s own body and its
existing tests are exactly what they were before this method existed.

Stdlib only, plus this member's own submodules at module scope
(:mod:`signal_agent._authored` and :mod:`signal_agent._authoring_prompt`) and
``providers``/``discovery`` deferred to first use.  The deferral is the same
discipline the member's ``__init__`` and :mod:`signal_agent._authoring_prompt`
state: the factory's workspace scan imports every member one at a time with
that member's own ``src/`` on ``sys.path``, so a module-scope import of a
sibling *member* would make this file unimportable before its dependencies are
on the path.  ``providers`` and ``discovery`` are declared dependencies of
this member (feature 1) and reached only inside :meth:`LLMSignalAuthor.__call__`
and :meth:`LLMSignalAuthor.author_root` (``discovery`` only from the former,
since a root's id is given rather than derived).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any, Final

from ._authored import AUTHORED_OUTPUT_CODE, AuthoredOutputError, parse_authored
from ._authoring_prompt import build_authoring_prompt, to_request
from .errors import SignalAgentError

__all__ = ["AUTHORING_REFUSED_CODE", "AuthoredSignal", "AuthoringRefusedError", "LLMSignalAuthor"]

#: The token every refusal :class:`AuthoringRefusedError` opens with — the
#: greppable word an operator's campaign log carries, the discipline every
#: refusal in this member follows.  Spelled once so the raise site, the retry
#: message that quotes it and a grep all read the same string.
AUTHORING_REFUSED_CODE: Final[str] = "authoring_refused"

#: §14.1's rotated tier, by the name :func:`providers.role_for_depth` answers
#: it — the one role whose record carries the declared frontier tier, because
#: feature 196 files a *root*'s serving provider against that tier and a depth
#: or policy record has no rotation to record.  Spelled here rather than
#: imported so this module names the role it branches on once.
_ROOT_ROLE: Final[str] = "root"

#: The four fields an :class:`AuthoredSignal` carries — the spec's own list,
#: named once so the constructor, ``__eq__``, ``__slots__`` and ``__repr__``
#: cannot drift about what an authored signal *is*.
_AUTHORED_FIELDS: Final[tuple[str, ...]] = (
    "code",
    "stated_mechanism",
    "proposal",
    "record",
)


class AuthoringRefusedError(SignalAgentError):
    """A whole authoring was refused after its retries were spent.

    Raised by :meth:`LLMSignalAuthor.__call__` after the last retry failed —
    the model answered, was shown the defect and its answer was refused again
    — and by nothing else.  The message opens with
    :data:`AUTHORING_REFUSED_CODE` and then names the *last* defect: the
    refusal code word of the parse that could not read the answer
    (:data:`~signal_agent._authored.AUTHORED_OUTPUT_CODE`), the adoptor's own
    problem sentences, or the anti-convergence gate's code word.  A campaign
    driver reading it has the whole history of the round's failure in the
    message and a single class to catch.

    **It is a sibling of :class:`~signal_agent.AgentSourceError`, not a
    subclass of it.**  The subject is not one proposal the agent wrote — every
    proposal this authoring produced was individually refused and shown back —
    it is the *round*, which produced no admissible signal across its whole
    retry budget.  The repair is not another re-prompt (the budget is spent)
    but the driver's decision about the branch, and a caller that already
    catches :class:`~signal_agent.AgentSourceError` to retry must not catch
    this and loop forever on a node whose model cannot answer.

    It is likewise **not** raised for :class:`~providers.BudgetExhaustedError`
    or :class:`~providers.ServedModelMismatchError`: those propagate unchanged,
    because their repairs (stop spending, fix the pin) are different actions
    and re-wrapping them here would hide the store's or the vendor's own,
    sharper sentence behind this one.
    """


class AuthoredSignal:
    """One node's authored signal — the four things the pipeline reads away.

    What :meth:`LLMSignalAuthor.__call__` returns and what discovery's agent
    seam consumes: ``code`` (the source the contract adopted, the exact text
    §5.2's sandbox will execute), ``stated_mechanism`` (the rationale the
    node's column records, or ``None`` when the answer stated none),
    ``proposal`` (the model's *full raw answer*, the text the history
    persists) and ``record`` (the :class:`~providers.AuthoringRecord` the
    call left behind).

    **The three text fields come straight off the accepted answer's parse**,
    so they cannot disagree with one another or with the record: ``code`` is
    the body feature 6 extracted and feature 205 adopted, ``proposal`` is the
    whole answer that body came from, and ``record`` describes the very call
    that produced both.

    **It answers discovery's seam and nothing more.**  ``NodeExpansion`` reads
    ``.code`` (a non-blank string) and an optional ``.stated_mechanism`` (a
    string or ``None``) and ignores every other attribute, so a value with
    these four is exactly what the seam accepts — the driver that persists the
    proposal and files the record reads the second half.

    **Equality is over the parts, never by ``isinstance``** — the module
    loader imports every member twice, so an ``isinstance`` check against this
    class would be false for a value built from the other import of the same
    file.  The four parts are the whole truth about the value, and equality
    over them survives both imports.  The constructor refuses nothing: what it
    carries was already judged by the gates, and a value that exists is one
    those gates admitted.
    """

    __slots__ = _AUTHORED_FIELDS

    def __init__(
        self,
        *,
        code: str,
        stated_mechanism: str | None,
        proposal: str,
        record: Any,
    ) -> None:
        self.code = code
        self.stated_mechanism = stated_mechanism
        self.proposal = proposal
        self.record = record

    def __eq__(self, other: object) -> bool:
        """Equal when all four parts are equal — never by ``isinstance``."""
        if not all(hasattr(other, name) for name in _AUTHORED_FIELDS):
            return NotImplemented
        return (
            self.code == other.code
            and self.stated_mechanism == other.stated_mechanism
            and self.proposal == other.proposal
            and self.record == other.record
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"AuthoredSignal(code_chars={len(self.code)}, "
            f"stated_mechanism={'yes' if self.stated_mechanism else 'none'}, "
            f"proposal_chars={len(self.proposal)})"
        )


def _request_temperature(temperature: float | None) -> float:
    """The float every built :class:`providers.Request` carries for temperature.

    ``providers.Request.temperature`` has no optional form — it is always a
    number in ``[0, 2]`` — so a config that turns no temperature knob at all
    (``AuthoringConfig.temperature is None``, feature 5 of
    additions_spec_real_campaign_path.xml) is represented the same way
    :class:`~providers.Request` represents "a caller that turned no knob":
    its own default, ``0.0``.  Never ``float(None)``, which is the defect
    this guard exists to avoid.  A stated value is passed through unchanged,
    as a float.
    """
    return 0.0 if temperature is None else float(temperature)


def _require_max_retries(value: object) -> int:
    """Return ``value`` as a non-negative int, refusing anything else.

    A caller's wiring fact, not a proposal's: the retry count is the loan this
    author extends to a model, and a bool (``True`` is an ``int`` in Python)
    or a non-number names no number of retries.  The two refusals are the two
    standard errors they are: a wrong *type* is :class:`TypeError`, and a
    count below zero is :class:`ValueError` — neither is a member error,
    because no model was called and nothing of the authoring path failed.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"max_retries must be a non-negative int, got {value!r} "
            f"({type(value).__name__}). It is how many times a refused answer "
            f"is shown back to the model before the whole authoring is "
            f"refused, so it must be a count."
        )
    if value < 0:
        raise ValueError(
            f"max_retries must be non-negative, got {value}. Zero is the legal "
            f"way to state 'the first answer must be admissible'; a negative "
            f"count names no number of retries."
        )
    return value


class LLMSignalAuthor:
    """Author one refined signal with a pinned model, gates included.

    Constructed with everything the call needs and nothing it must reach for:
    a providers :class:`~providers.AuthoringSession` (which provider a role is
    served by), the proposal-history store (the campaign's prior nodes), the
    signal contract (feature 205's adoption), the anti-convergence gate
    (feature 210's clause and structure screens), the prompt-guidance gate
    (feature 208) and the deployment's :class:`~providers.AuthoringConfig`
    (the sampling the request rolls and the record carries).  ``max_retries``
    is the only knob with a default, because one retry is §14.1's own stance:
    a model shown its defect once either answers or does not.

    Every collaborator is duck-typed and held as given, never constructed
    here — the author does no I/O at construction and reads no environment, so
    a suite can build one over a fake session and a fake store and drive the
    whole path with no network, no credential and no database, which is the
    constraint this addition states.  The object is a callable because that is
    the shape :class:`discovery.NodeExpansion(agent, database_url)` accepts.
    """

    def __init__(
        self,
        session: Any,
        *,
        history_store: Any,
        contract: Any,
        anti_convergence: Any,
        guidance: Any,
        config: Any,
        max_retries: int = 1,
    ) -> None:
        self._session = session
        self._history_store = history_store
        self._contract = contract
        self._anti_convergence = anti_convergence
        self._guidance = guidance
        self._config = config
        self._max_retries = _require_max_retries(max_retries)

    # -- The callable discovery's seam invokes -------------------------------

    def __call__(self, workspace: Any) -> AuthoredSignal:
        """Author the workspace's refined signal and answer an :class:`AuthoredSignal`.

        Reads the campaign's whole history, builds and screens the C3 prompt,
        calls the pinned model for the child's role, and judges the answer
        through feature 6's parse, feature 205's adoption and feature 210's
        anti-convergence check — retrying a model-repairable defect up to
        ``max_retries`` times and refusing the whole authoring beyond that.
        See the module docstring for what is retried and what is not.
        """
        import discovery
        import providers

        campaign_id = str(workspace.campaign_id)
        parent_id = str(workspace.node_id)
        child_id = str(uuid.uuid5(discovery.EXPANSION_NAMESPACE, parent_id))
        child_depth = workspace.depth + 1

        role = providers.role_for_depth(child_depth)
        provider, pin = self._session.provider_for(
            role, campaign_id=campaign_id, node_id=child_id
        )

        history = self._read_history(campaign_id)
        entries = self._pair_scores(history)
        held = self._held_code(history)

        parts = build_authoring_prompt(
            workspace, entries, clause=self._anti_convergence
        )
        # Feature 208 first, on the named parts — the gate reads the prompt's
        # structure, which is what feature 5 built.  It never raises on
        # admission; ``require`` is the one place it raises on a refusal.
        self._guidance.require(parts)
        request = to_request(
            parts,
            model=pin.model,
            temperature=_request_temperature(self._config.temperature),
            max_tokens=int(self._config.max_tokens),
        )
        # Feature 210's prompt half, on the rendered system message: the
        # committed clause must appear verbatim in what ships.  Both screens
        # run before the first call, so a refused prompt spends nothing.
        self._anti_convergence.require_in(request.messages[0].content)

        return self._author(
            providers,
            request=request,
            provider=provider,
            pin=pin,
            campaign_id=campaign_id,
            child_id=child_id,
            child_depth=child_depth,
            role=role,
            held=held,
        )

    # -- The callable a campaign driver plants a root with -------------------

    def author_root(
        self, campaign_id: str, theme_root: str, *, root_id: Any
    ) -> AuthoredSignal:
        """Author a campaign's opening signal — a root at depth 0.

        additions_spec_campaign_driver.xml, "Roots" feature 1: the root's own
        id is the caller's ``root_id`` rather than a derived child id (a root
        has no parent to derive it from), its depth is fixed at 0 and its
        role is fixed at :data:`_ROOT_ROLE` — unlike :meth:`__call__`, which
        reads the role off a *derived* child's depth, a root's role is never
        in question. ``session.provider_for("root", campaign_id=…,
        node_id=root_id)`` is what lets the root rotation (feature 3 of
        additions_spec_llm_authoring.xml) decide the model, the same call the
        rotation's own recorder later replays to check the serving provider
        against.

        The prompt, the history, the gates, the retry and the record are
        built the same way :meth:`__call__`'s are, over a workspace-shaped
        value built here instead of handed in, because build_authoring_prompt
        reads only ``campaign_id``, ``theme_root`` and ``depth`` off it
        (feature 5) and a root has no other workspace fact to contribute.
        The campaign's history is read the same way an expansion's is —
        whole, from ``history_store.history(campaign_id)`` — and is empty
        for a campaign's first root, which feature 5's own history renders
        as the honest "no prior proposals exist yet" rather than a refusal.
        """
        import providers

        campaign_id = str(campaign_id)
        root_id = str(root_id)
        role = _ROOT_ROLE
        child_depth = 0

        provider, pin = self._session.provider_for(
            role, campaign_id=campaign_id, node_id=root_id
        )

        history = self._read_history(campaign_id)
        entries = self._pair_scores(history)
        held = self._held_code(history)

        workspace = SimpleNamespace(
            campaign_id=campaign_id, theme_root=theme_root, depth=child_depth
        )
        parts = build_authoring_prompt(
            workspace, entries, clause=self._anti_convergence
        )
        # Feature 208 first, on the named parts — the gate reads the prompt's
        # structure, which is what feature 5 built.  It never raises on
        # admission; ``require`` is the one place it raises on a refusal.
        self._guidance.require(parts)
        request = to_request(
            parts,
            model=pin.model,
            temperature=_request_temperature(self._config.temperature),
            max_tokens=int(self._config.max_tokens),
        )
        # Feature 210's prompt half, on the rendered system message: the
        # committed clause must appear verbatim in what ships.  Both screens
        # run before the first call, so a refused prompt spends nothing.
        self._anti_convergence.require_in(request.messages[0].content)

        return self._author(
            providers,
            request=request,
            provider=provider,
            pin=pin,
            campaign_id=campaign_id,
            child_id=root_id,
            child_depth=child_depth,
            role=role,
            held=held,
        )

    # -- The history, whole and paired ---------------------------------------

    def _read_history(self, campaign_id: str) -> tuple[Any, ...]:
        """Every prior proposal of the campaign, in the store's own order.

        Carried whole — no sample, no truncation, no summary — because PRD §C3
        and architecture §14.1 make the complete history the replay object the
        agent reads and feature 206's law is the guard over that wholeness.
        This module adds no second opinion about what the history is.
        """
        return tuple(self._history_store.history(campaign_id))

    def _pair_scores(self, history: Iterable[Any]) -> tuple[tuple[Any, Any], ...]:
        """Each prior proposal beside the score the store recorded for it.

        ``history_store.load(node_id).score`` — the figure the node measured,
        or ``None`` when the node has no recorded pair yet, which feature 5
        renders as the honest absence rather than a zero.  The node is *not*
        dropped when its score is missing: the set of prior proposals is what
        the anti-convergence check compares against, and a headline that
        silently dropped the unscored would shrink the comparison set behind
        the agent's back.
        """
        pairs: list[tuple[Any, Any]] = []
        for prior in history:
            record = self._history_store.load(prior.node_id)
            pairs.append((prior, record.score if record is not None else None))
        return tuple(pairs)

    def _held_code(self, history: Iterable[Any]) -> tuple[tuple[str, str], ...]:
        """Each prior node beside the *code* its proposal document holds.

        The gate compares skeletons, and a skeleton is read from **source**;
        a prior ``proposal`` is a *document* — a ``Mechanism:`` line, prose
        and the ```` ```python ```` fence — because feature 6 pins
        ``proposal`` as the model's full raw answer and feature 207 persists
        that field verbatim.  Handing the gate the raw markdown would hand it
        nothing it can parse, and :func:`~signal_agent._anti_convergence.
        _held_digests` *skips* what it cannot read rather than refusing: the
        comparison set would arrive empty behind the author's back and every
        answer would be admitted as novel — §14.1's "a converged tree is not
        caught by anything", arriving as the gate's own silence.  What reaches
        the gate is therefore the same reading feature 6 gives an *answer*:
        ``parse_authored(prior.proposal).code``, the source the prior's own
        fence holds, which is what the campaign actually holds at that
        structure.

        A proposal that does not parse still contributes the ``code_hash`` the
        node's row recorded, when one is recorded: a 64-hex digest, which is
        the form the gate accepts, so a prior that cannot be re-read is held
        at the identity its own record names rather than dropped from the
        set.  With no code hash either, the prior contributes nothing — the
        gate has no opinion about an entry it cannot read, which is its own
        documented stance for an unparseable held entry, taken here so the
        set this author hands in is exactly the set it meant to compare
        against.
        """
        held: list[tuple[str, str]] = []
        for prior in history:
            try:
                held.append((prior.node_id, parse_authored(prior.proposal).code))
            except AuthoredOutputError:
                code_hash = prior.code_hash
                if isinstance(code_hash, str) and code_hash.strip():
                    held.append((prior.node_id, code_hash))
        return tuple(held)

    # -- The call loop --------------------------------------------------------

    def _author(
        self,
        providers: Any,
        *,
        request: Any,
        provider: Any,
        pin: Any,
        campaign_id: str,
        child_id: str,
        child_depth: int,
        role: str,
        held: tuple[tuple[str, str], ...],
    ) -> AuthoredSignal:
        """Call the model, judge the answer, retry a repairable defect.

        The loop the module docstring describes: each attempt sends the
        running conversation, applies :func:`providers.require_served` to the
        completion (which propagates a
        :class:`~providers.ServedModelMismatchError` unchanged), reads the
        answer, and either accepts it or appends the answer and a defect-naming
        user turn for the next attempt.  Usage is summed across *every* call,
        including the refused ones, because that is what the authoring cost.
        """
        messages = request.messages
        campaign_input = 0
        campaign_output = 0
        campaign_cache = 0
        served_model = ""
        last_defect: str | None = None
        parsed = None
        accepted = False

        for attempt in range(self._max_retries + 1):
            current = providers.Request(
                messages=messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
            completion = provider.complete(current)
            # Feature 3's own check: the completion's serving model must be the
            # pinned one.  A mismatch is the vendor's, not the model's, and it
            # leaves as ServedModelMismatchError — never retried.
            completion = providers.require_served(pin, completion)
            campaign_input += completion.usage.input_tokens
            campaign_output += completion.usage.output_tokens
            campaign_cache += completion.usage.cache_read_tokens
            served_model = completion.model
            answered = completion.content

            parsed, defect = self._judge(answered, held)
            if defect is None:
                accepted = True
                break

            last_defect = defect
            if attempt < self._max_retries:
                messages = messages + (
                    providers.Message(role="assistant", content=answered),
                    providers.Message(role="user", content=self._retry_message(defect)),
                )

        if not accepted:
            raise AuthoringRefusedError(
                f"{AUTHORING_REFUSED_CODE}: the authoring of node {child_id} "
                f"(depth {child_depth}, role {role!r}) was refused after "
                f"{self._max_retries + 1} attempt(s) — the model's answer was "
                f"shown the defect and refused again each time. The last defect "
                f"was: {last_defect}. The budget for the pin was spent on "
                f"answers no gate admitted, so this branch was authored by "
                f"nothing; hand the model a different prompt, raise "
                f"max_retries, or abandon the branch (feature 7)."
            )

        record = providers.AuthoringRecord(
            node_id=child_id,
            campaign_id=campaign_id,
            depth=child_depth,
            role=role,
            pin=pin,
            # A stated temperature still rolls all four of AgentSampling's
            # settings, unchanged.  A None temperature means no sampling knob
            # was turned at all, which the no-sampling extension gives
            # AgentSampling a way to say honestly: temperature and top_p null
            # (not sent), thinking "adaptive" (the 5.x family's reasoning is
            # not a flag the caller turns on or off), and effort carried when
            # the config named one.
            sampling=(
                providers.AgentSampling(temperature=float(self._config.temperature))
                if self._config.temperature is not None
                else providers.AgentSampling(
                    temperature=None,
                    top_p=None,
                    thinking="adaptive",
                    effort=self._config.effort,
                )
            ),
            usage=providers.Usage(
                input_tokens=campaign_input,
                output_tokens=campaign_output,
                cache_read_tokens=campaign_cache,
            ),
            served_model=served_model,
            tier=self._config.tier if role == _ROOT_ROLE else None,
        )
        return AuthoredSignal(
            code=parsed.code,
            stated_mechanism=parsed.stated_mechanism,
            proposal=parsed.proposal,
            record=record,
        )

    def _judge(self, answer: str, held: tuple[tuple[str, str], ...]) -> tuple[Any, str | None]:
        """Read one answer and judge it — ``(ParsedProposal, defect | None)``.

        The three model-repairable gates in order: feature 6's parse, feature
        205's adoption, feature 210's anti-convergence check.  Each failure
        answers the defect string the retry message quotes; an admission
        answers ``(parsed, None)``.  Only these three failures are caught — a
        store, budget or serving-model failure raised inside a gate would
        propagate, because none of them is the model's to repair.
        """
        try:
            parsed = parse_authored(answer)
        except AuthoredOutputError as exc:
            return None, f"{AUTHORED_OUTPUT_CODE}: {exc}"

        adoption = self._contract.adopt(parsed.code)
        if not adoption.adopted:
            problems = tuple(getattr(adoption, "problems", ()) or ())
            defect = (
                "; ".join(str(problem) for problem in problems)
                if problems
                else str(getattr(adoption, "detail", "") or adoption)
            )
            return parsed, defect

        verdict = self._anti_convergence.admit(parsed.code, held=held)
        if not verdict.admitted:
            code = getattr(getattr(verdict, "reason", None), "value", None) or "refused"
            return parsed, f"{code}: {getattr(verdict, 'detail', '')}"

        return parsed, None

    def _retry_message(self, defect: str) -> str:
        """The user turn that names the defect and asks for the repair.

        The format is restated so the model is not left to guess at the shape,
        and the defect is quoted verbatim so the repair is specific — the
        discipline feature 6's own refusal message is written for.
        """
        return (
            "Your previous answer (the assistant turn above) was refused. "
            f"The defect to repair: {defect}\n\n"
            "Reply with exactly one ```python fenced code block holding the "
            "complete corrected signal source and exactly one line starting "
            "'Mechanism:' stating the economic mechanism."
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"LLMSignalAuthor(max_retries={self._max_retries}, "
            f"role_ready={'yes' if self._session is not None else 'no'})"
        )
