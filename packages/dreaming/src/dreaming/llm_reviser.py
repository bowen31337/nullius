"""Feature 9, the LLM policy reviser — the policy-development agent's acting half.

additions_spec_llm_authoring.xml, "Policy Development Author", feature 9:
*System creates a revised exploration policy module through a model with
``dreaming.llm_reviser.LLMReviser(session, *, config)``, a callable matching
dreaming's :data:`~dreaming.reviser.Reviser`
``(incumbent_source, revision_index, seed) -> source``.*

Feature 271 built the revision sweep — :func:`dreaming.reviser.revise_policy`
runs ``M`` revisions of an incumbent policy, one per index ``1..M``, and takes
the transform as a pluggable ``reviser``.  Its default is
:func:`~dreaming.reviser.default_reviser`, a seeded *magnitude* perturbation of
the incumbent's numeric literals: structure-preserving, admissible by
construction, and deliberately blind to *why* a policy should change.  This
module is the other half of that seam.  It swaps the blind jitter for a
**model-driven rewrite**: the incumbent source, the revision index and the seed
go to the policy pin of the deployment's authoring configuration, and the
model's answer — one ```` ```python ```` block holding the whole revised module
— comes back as the next candidate.  The sweep's contract does not move: an
:class:`LLMReviser` *is* a :data:`~dreaming.reviser.Reviser`, so
``revise_policy(incumbent, count, reviser=LLMReviser(...))`` runs unchanged.

Why this lives in dreaming, and where the boundary is
-----------------------------------------------------

Feature 271's own docstring names a pluggable reviser as the way "a deployment
substitutes its own ``(incumbent_source, revision_index, seed) -> source``
policy-development strategy without moving the contract".  This module is that
substitution, made real by the authoring addition: the *strategy* — which model,
at what dice, under what budget — is the deployment's, stated in the authoring
configuration (features 2 and 3) and answered by the authoring session.  So this
module owns the *new* things and nothing else:

* the **request** it builds (the incumbent in full, the revision index, the
  seed, the config's temperature and ``max_tokens``) and the **format** it asks
  for (exactly one ```` ```python ```` block);
* the **reading** of the model's answer back into a revised source, and the
  refusals that reading makes;
* the **record** every call leaves behind, appended to
  :attr:`LLMReviser.records` as a :class:`providers.AuthoringRecord` with role
  ``policy``.

It owns none of the session's routing, the pin's resolution, the budget's
arithmetic or the record's store.  Those are features 2, 3 and 4, reached
through the session object it is handed and through the ``config`` it is handed
beside it — the *one* thing this module reads off ``config`` is the two knobs
the request carries (``temperature`` and ``max_tokens``); every other question
about pins is the session's.

The node id is a revision, not a tree node
------------------------------------------

The policy role's ids are not discovery-tree nodes.  §14.1 draws three call
sites — the rotated frontier tier that authors roots, the depth tier below it,
and *"the policy reviser"* — and only the first two are nodes of the search
tree.  This module's call site is a **revision of one module**, so its ``node_id``
is ``f"revision-{revision_index}"`` and its ``campaign_id`` is the literal
``"policy-development"`` — the campaign the revision belongs to, stated once in
:data:`POLICY_CAMPAIGN_ID`.  Both are exactly what the feature's own sentence
names, and both are *non-blank strings* rather than UUIDs — which is precisely
why :class:`providers.AuthoringRecord` guards its ids as non-blank text and not
as UUIDs (feature 2's own docstring says so): a guard that demanded a UUID would
refuse the records this reviser appends.

The answer, and its two refusals
--------------------------------

The model is asked for exactly one ```` ```python ```` block holding the whole
revised module.  The reading of the answer is deliberately narrow, and it is
this module's own rather than a shared parser, because a policy revision is a
*different subject* than a signal proposal:

* **zero or several python blocks**, or a python block whose body is blank, is
  :class:`ReviserOutputError` — the answer did not carry exactly one complete
  block of source, so there is no single revised module to answer with.  Several
  blocks are the same ambiguity the signal parser refuses: both can be valid
  modules, and picking one would spend the revision on this module's guess;
* **an answer identical to the incumbent** is :class:`ReviserOutputError` too,
  and it **names the revision index**.  A revision that is not a revision — the
  model handed the incumbent back unchanged — would make ``revise_policy``'s
  distinctness check collapse two candidates onto one source, and the loop's
  argmax would be selecting between fewer revisions than it asked for.  The
  refusal names *which* revision produced the echo so the caller can re-ask that
  one.

Both refusals open with :data:`REVISER_OUTPUT_CODE` (``reviser_output``), the
greppable token the feature's sentence names, and :class:`ReviserOutputError`
is defined **in this module** — the feature's own requirement, and the workspace
convention of a typed error living beside the code that raises it.  It subclasses
:class:`~dreaming.errors.DreamingError` so a caller's single ``except`` catches
every failure of the dreaming path, exactly as every other refusal in this member
does.

The tag is wrap-agnostic
--------------------------

A prompt and a fake fixture cannot both be assumed to agree on whether the fence
is ``python`` or ``py``, whether the answer arrives with prose around it, or
whether it is wrapped in markdown emphasis.  The scanner here is line-based like
:func:`signal_agent._authored.parse_authored` — CommonMark's own fence rules, a
closing fence carrying no info string, leading whitespace tolerated — with one
deliberate widening: the info string is accepted when it is ``python`` **or**
``py`` (case-folded), because the instruction the *model* is given names
``python`` while a recorded fixture may carry either and the two spellings name
one format.  Nothing else about the reading is tolerant: the block's body is the
revised source, dedented by the opening fence's own indentation and read with
``\\r\\n`` as ``\\n``, exactly as feature 271's ``ast``-based checks downstream
expect.

The record, and what it costs
------------------------------

Every call appends one :class:`providers.AuthoringRecord` to
:attr:`LLMReviser.records`: the ``node_id`` it served (``revision-{index}``), the
``campaign_id`` (``policy-development``), a ``depth`` of :data:`POLICY_REVISION_DEPTH`
(zero — a revision is not a tree node and has no depth; the record's depth field
is a tree fact and zero is the honest absence of one for a non-node, the same
zero the role's own docstring lets stand), the ``role`` ``"policy"``, the ``pin``
the session answered, the ``sampling`` the call rolled (an
:class:`providers.AgentSampling` built with the config's temperature and the
revision's seed), the ``usage`` the completion reported, and the ``served_model``
the completion named.  ``tier`` is ``None`` — a policy record carries no frontier
tier, exactly as feature 2's record docstring states.  The mapping to a record
is this module's, and so is the decision **not** to file it: feature 4's
``record_authoring`` writes a record to a store and demands a ``node`` row for
its node id, which a revision id has none of; so this module *appends* the record
where the loop can read it and leaves the persistence to the caller that owns a
store, exactly as feature 271 leaves admission to feature 230 rather than
pre-refusing.

What this module deliberately does not do
------------------------------------------

It makes no model call of its own construction — the session it is handed
resolves the provider, so a deployment resolver that reads a credential reads it
at the session's first ``provider_for``, which is the composition-time credential
read both features 2 and 3 refuse to perform eagerly.  It reads no environment,
opens no database, resolves no path and imports nothing that could: the whole of
its I/O is the one ``provider.complete(request)`` call, and the provider is the
caller's.  It never evaluates a policy, scores a world, reads the cousin
nulloracle member or any ``is_null`` value — it sees the incumbent's *source*
and the model's *answer*, and neither carries a null status (design principle 2).

One import-time caution: :mod:`providers` is a declared dependency of this
member, but the composed application's scan imports each member to fire its
``@register``, and a module-scope ``import providers`` would make this file's
importability depend on the scan having already put the providers member's
``src/`` on ``sys.path``.  So the provider vocabulary this module reads at *call*
time — :class:`~providers.AuthoringRecord`, :class:`~providers.AgentSampling`,
:func:`~providers.require_served` — is reached through one deferred
:func:`_providers` helper, the discipline :func:`signal_agent._authoring_prompt.
to_request` states for its own sibling-member import.  The session and config
objects are the caller's and are never imported here.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from .errors import DreamingError

__all__ = [
    "POLICY_CAMPAIGN_ID",
    "POLICY_REVISION_DEPTH",
    "REVISER_OUTPUT_CODE",
    "LLMReviser",
    "ReviserOutputError",
]

#: The campaign every policy revision belongs to — the feature's own literal.
#: A revision is not a tree node (see the module docstring), so the campaign it
#: is filed under is stated once here rather than derived from a workspace.
POLICY_CAMPAIGN_ID: Final[str] = "policy-development"

#: The depth a policy revision's record carries.  A revision has no place in the
#: discovery tree, and the record's depth field is a tree fact; zero is the
#: honest absence of one — the root depth — rather than a fabricated level.  It
#: is not read off the incumbent or the index, because neither is a depth.
POLICY_REVISION_DEPTH: Final[int] = 0

#: The greppable code word every refusal this module raises opens with — the
#: token the feature's sentence names (``reviser_output``), spelled once so the
#: raise sites and an operator's grep read the same string.
REVISER_OUTPUT_CODE: Final[str] = "reviser_output"

#: Markdown's fence marker, spelled once.  A fence line is a line whose stripped
#: form starts with this; what follows (stripped) is the fence's *info string*.
_FENCE_MARKER: Final[str] = "```"

#: The info strings that make a fenced block count as the answer's revised
#: module, case-folded.  Two spellings, one format: the instruction the model is
#: given names ``python``, while a recorded fixture may carry ``py``, and the two
#: name the same thing.  A third spelling (``python3``) is not admitted — it
#: names a language the format never asked for, and quietly admitting it would
#: make this reader the one that guessed.
_PYTHON_INFOS: Final[frozenset[str]] = frozenset({"python", "py"})

#: The fence's uniform-indentation reading and the line-ending reading are the
#: same two the signal parser applies (feature 6); restated here rather than
#: imported, because this module's subject is a *policy revision* and importing
#: the signal member's parser would be a cross-member dependency the sibling
#: rule forbids.

#: The system instruction this reviser sends.  It names the two facts the model
#: must honour: the answer is exactly one ```` ```python ```` block holding the
#: *whole* module, and nothing else fenced as python.  Kept as one string so the
#: ask and the reading (which refuses zero, several and blank) are one contract
#: in the same place.
_SYSTEM_INSTRUCTION: Final[str] = (
    "You revise an exploration-policy Python module. You are given the "
    "incumbent module in full, the revision index of this sweep, and the seed "
    "that fixes any randomness. Answer with exactly one ```python fenced code "
    "block holding the whole revised module, and nothing else fenced as "
    "python. The module must be complete and importable on its own. Do not "
    "answer with the incumbent unchanged."
)

#: The label the user message carries the incumbent source under, so the source
#: is a clearly delimited region of the request rather than prose the model has
#: to guess the boundaries of.
_INCUMBENT_HEADER: Final[str] = "incumbent module:"

#: The denomination of the request's user message — the index and the seed, in
#: the order the feature's sentence lists them ("the revision_index and the
#: seed"), each on its own line so a model reads two facts and not one string.
_DENOMINATION: Final[str] = "revision index: {index}\nseed: {seed}"


class ReviserOutputError(DreamingError):
    """A model's answer is not the one revised module the reviser asked for.

    Raised by :meth:`LLMReviser.__call__` — and only the reading half of it —
    for the two shapes the feature's sentence refuses: an answer that does not
    carry exactly one complete ```` ```python ```` block (zero blocks, several
    blocks, a blank body, or a fence that never closes), and an answer identical
    to the incumbent.  The message opens with :data:`REVISER_OUTPUT_CODE` and
    then names *which* shape it holds — and, for the echo, the ``revision_index``
    that produced it — because the caller that catches it re-asks that one
    revision, and a message that named no revision would leave it to re-run the
    whole sweep.

    **It subclasses :class:`~dreaming.errors.DreamingError`**, so a caller that
    already catches the dreaming path's one base — the campaign loop, an operator
    script — catches this beside a thin pool and a capped sweep without importing
    a second type.  It is a **sibling** of :class:`~dreaming.errors.RevisionError`
    rather than a subclass: that class is feature 271's verdict on a *production*
    (an incumbent whose constants cannot fund ``M`` distinct candidates, a custom
    reviser that returned unparseable text), judged after the reviser ran; this
    one fires *inside* a reviser, before any candidate exists, and its subject is
    the model's answer shape.  The repairs differ — re-ask the model, which is
    why this class's message quotes the format back — so a caller counting
    malformed answers must not have to separate them from short sweeps by reading
    message text.
    """


def _providers():
    """The providers member, imported at call time rather than at module scope.

    One deferred import, for the reason the module docstring states: the
    composed application's workspace scan imports this file (to fire the
    dreaming member's ``@register``) with only that member's own ``src/``
    necessarily on ``sys.path``, so a module-scope ``import providers`` would
    make this file's importability depend on scan order.  The names read from
    it are the three the record and the served check need and no more.
    """
    import providers

    return providers


def _normalised_lines(text: str) -> list[str]:
    """The answer's lines, ``\\r\\n`` spellings read as ``\\n``.

    The wire's line ending is not part of the source the model wrote, so the
    same answer arriving over CRLF and over LF must read as one source — or the
    ``code_hash`` feature 274 persists would hash the transport rather than the
    revision.  This is a reading only; the returned source is rebuilt from these
    lines.
    """
    return text.replace("\r\n", "\n").split("\n")


def _leading_whitespace(line: str) -> str:
    """A line's leading blanks — the indentation a fence or body line wears."""
    stripped = line.lstrip(" \t")
    return line[: len(line) - len(stripped)]


def _fence_info(line: str) -> str | None:
    """A line's fence info string, or ``None`` when the line is not a fence.

    Leading whitespace is tolerated (models indent fences inside lists), the
    marker's remainder is stripped, and a plain prose line answers ``None``.
    An empty string is a *closing* fence; a non-empty one is an opening fence's
    language tag.
    """
    stripped = line.strip()
    if not stripped.startswith(_FENCE_MARKER):
        return None
    return stripped[len(_FENCE_MARKER):].strip()


def _dedent_body(body_lines: list[str], fence_indent: int) -> str:
    """The body with the opening fence's own indentation taken off it.

    A block fenced inside a list arrives with the list's indentation on every
    line, and the surviving prefix would reach feature 230's admission gate as
    Python indentation — an ``IndentationError`` wearing a conformance defect it
    is not.  The repair takes the *smallest* of the indentation every body line
    shares and the opening fence's own, so it never cuts past a line the model
    wrote at column zero; a body with no common indentation is carried byte for
    byte.  Blank lines are whitespace-only and are not counted.
    """
    indents = [
        len(_leading_whitespace(line)) for line in body_lines if line.strip()
    ]
    removed = min(min(indents), fence_indent) if indents else 0
    return "\n".join(
        line[len(_leading_whitespace(line)[:removed]):] for line in body_lines
    )


def _python_block_bodies(lines: list[str]) -> list[str]:
    """Every python-fenced block in an answer's lines, as its dedented body.

    One pass over the answer's lines, keeping to CommonMark's fence rules rather
    than inventing reader-specific ones:

    * a fence **opens** at a fence line with any info string, and the block is a
      python block when that info string is one of :data:`_PYTHON_INFOS`
      (case-folded);
    * a fence **closes** at the next line whose info string is empty — a
      ```` ```json ```` line inside an open block is *content*, not a boundary;
    * a python fence left **unclosed** is refused as an unterminated block (the
      ``max_tokens`` cut): the answer stopped mid-module, and the remainder is
      the piece that fit, not the revision.  An unclosed fence of another
      language is skipped — its content was never going to become the module;
    * the body is the lines between the fences, dedented by the opening fence's
      own indentation; nothing is stripped from the ends, because the revised
      source is what the model wrote and this reader refuses to be the answer's
      first transformer.
    """
    bodies: list[str] = []
    index = 0
    while index < len(lines):
        info = _fence_info(lines[index])
        if info is None:
            index += 1
            continue
        fence_indent = len(_leading_whitespace(lines[index]))
        start = index + 1
        index = start
        while index < len(lines) and _fence_info(lines[index]) != "":
            index += 1
        if index == len(lines):
            if info.casefold() in _PYTHON_INFOS:
                raise ReviserOutputError(
                    f"{REVISER_OUTPUT_CODE}: the answer's "
                    f"{_FENCE_MARKER}{info} fenced block is unterminated — it "
                    f"opens but never closes. An answer cut off mid-fence "
                    f"(max_tokens, or a dropped line) leaves the piece that fit, "
                    f"not the whole revised module, and adopting the truncated "
                    f"tail would hand the sweep a module the model never "
                    f"finished writing (feature 9)."
                )
            index += 1
            continue
        if info.casefold() in _PYTHON_INFOS:
            bodies.append(_dedent_body(lines[start:index], fence_indent))
        # Step past the closing fence so a fence line never does double duty as
        # the opener of the block it just closed.
        index += 1
    return bodies


def _revised_source(text: Any, incumbent_source: str, revision_index: int) -> str:
    """Read one model answer as the revised module, or refuse it by name.

    The reading half of :meth:`LLMReviser.__call__`, split out so it is a pure
    function of the answer and the incumbent: zero python blocks is refused, a
    blank block body is refused, several python blocks are refused, and an
    answer whose single block is byte-identical to the incumbent is refused
    **naming the revision index** — because a model that echoed the incumbent
    produced no revision, and returning it would collapse ``revise_policy``'s
    distinctness check onto one source.  Each refusal opens with
    :data:`REVISER_OUTPUT_CODE`.
    """
    if not isinstance(text, str):
        raise ReviserOutputError(
            f"{REVISER_OUTPUT_CODE}: a reviser's answer must be text, got "
            f"{type(text).__name__}; the answer is the one artefact this "
            f"reviser reads — the single fenced block that becomes the revised "
            f"module — and neither the block nor the source in it can be "
            f"scanned out of a value that is not text (feature 9)."
        )
    blocks = _python_block_bodies(_normalised_lines(text))
    if not blocks:
        raise ReviserOutputError(
            f"{REVISER_OUTPUT_CODE}: the answer carries no "
            f"{_FENCE_MARKER}python fenced block. The reviser asks for exactly "
            f"one holding the whole revised module, so an answer without one "
            f"proposes no module at all, and nothing is recovered from the "
            f"prose around the gap — a reader that adopted text it was not "
            f"handed would be authoring, not reading (feature 9)."
        )
    if len(blocks) > 1:
        raise ReviserOutputError(
            f"{REVISER_OUTPUT_CODE}: the answer carries {len(blocks)} "
            f"{_FENCE_MARKER}python fenced blocks where the reviser asks for "
            f"exactly one. Which block is the revised module would be this "
            f"reader's guess, and both can be importable modules no downstream "
            f"gate could tell apart — so the count is named and refused rather "
            f"than spent on the guess (feature 9)."
        )
    code = blocks[0]
    if not code.strip():
        raise ReviserOutputError(
            f"{REVISER_OUTPUT_CODE}: the answer's {_FENCE_MARKER}python fenced "
            f"block has a blank body. A fence with nothing in it carries no "
            f"module for the sweep to replay and no source for the admission "
            f"gate to read, and the refusal names the answer's shape rather "
            f"than letting a blank reach the gate as a source defect it is not "
            f"(feature 9)."
        )
    if code == incumbent_source:
        raise ReviserOutputError(
            f"{REVISER_OUTPUT_CODE}: revision {revision_index} answered with the "
            f"incumbent module unchanged. A revision that is not a revision "
            f"produces no new candidate — revise_policy deduplicates by "
            f"code_hash, so an echoed incumbent collapses onto the source it "
            f"copied, and the loop's argmax would select between fewer "
            f"revisions than it asked for. The revision index is named so the "
            f"caller can re-ask this one (feature 9)."
        )
    return code


class LLMReviser:
    """A model-driven :data:`~dreaming.reviser.Reviser` — feature 9's callable.

    Built over a :class:`providers.AuthoringSession` and the
    :class:`providers.AuthoringConfig` that session binds, and *is* a
    ``(incumbent_source, revision_index, seed) -> source`` callable, so it drops
    straight into :func:`dreaming.reviser.revise_policy`'s ``reviser`` parameter
    without the sweep knowing a model is behind it::

        reviser = LLMReviser(session, config=config)
        candidates = revise_policy(incumbent_source, count, reviser=reviser)

    Each call takes the policy pin from the session
    (:meth:`~providers.AuthoringSession.provider_for` with role ``"policy"``,
    campaign :data:`POLICY_CAMPAIGN_ID` and node ``f"revision-{revision_index}"``),
    builds the request (the incumbent source in full, the revision index, the
    seed, the config's ``temperature`` and ``max_tokens``), completes it,
    applies :func:`providers.require_served` so a vendor quietly serving another
    model is caught before the answer is trusted, reads the single
    ```` ```python ```` block out of the answer, appends an
    :class:`providers.AuthoringRecord` with role ``policy`` to :attr:`records`,
    and answers the block's body.

    **It holds the session, not a provider.**  The session resolves and budgets
    each pin once (feature 3), so a sweep that runs ``M`` revisions against one
    policy pin draws on *one* running budget rather than one per revision — which
    is the whole reason this class takes a session and not a provider: a reviser
    that resolved its own provider per call would hand each revision a fresh,
    unspent budget and the ceiling would bound an answer rather than a campaign.

    **``records`` is append-only and never culled.**  Every call appends its
    :class:`providers.AuthoringRecord`, including a call that later refuses the
    answer — the spend happened, and the record is the account of it.  A caller
    reads :attr:`records` to see what the sweep cost; the caller that owns a
    store is the one that files them (feature 4), because a policy revision's
    ids name no ``node`` row for ``record_authoring`` to write against.
    """

    __slots__ = ("_config", "_session", "records")

    def __init__(self, session: object, *, config: object) -> None:
        # Held, not copied: ``config`` is frozen and value-equal (feature 2), and
        # ``session`` is the object that owns the providers and their budgets, so
        # a caller keeping a reference cannot change what this reviser routes.
        self._session = session
        self._config = config
        #: Every authoring record this reviser has appended, in call order.
        self.records: list[Any] = []

    # -- The callable the sweep takes ---------------------------------------

    def __call__(self, incumbent_source: str, revision_index: int, seed: Any) -> str:
        """Revise the incumbent once, through the policy pin — feature 9's call.

        The signature feature 271's :data:`~dreaming.reviser.Reviser` requires,
        and nothing about it moves: the incumbent source in, the revised source
        out.  The body is the module docstring's account — take the pin, build
        the request, complete it, check what served, read the block, record the
        spend — and every refusal it can raise is
        :class:`ReviserOutputError` for a bad *answer*, or the providers member's
        own errors (an unserved model, an exhausted budget, a malformed request)
        for a bad *call*, which propagate unchanged because they name the
        variable or the ceiling an operator acts on.
        """
        node_id = f"revision-{revision_index}"
        provider, pin = self._session.provider_for(
            "policy",
            campaign_id=POLICY_CAMPAIGN_ID,
            node_id=node_id,
        )
        request = self._build_request(incumbent_source, revision_index, seed, pin)
        completion = provider.complete(request)
        providers = _providers()
        completion = providers.require_served(pin, completion)
        # The record is appended once the call has been *served* — the spend
        # happened — and before the answer is read, so a call whose answer this
        # module refuses (zero blocks, several, a blank body, an echoed
        # incumbent) still leaves its account behind.  A require_served refusal
        # above is the one exception: the answer's provenance is not the pin's,
        # so there is no trusted serving model to record.
        self.records.append(
            self._record(pin, completion, revision_index, node_id, seed)
        )
        return _revised_source(completion.content, incumbent_source, revision_index)

    # -- The request ---------------------------------------------------------

    def _build_request(
        self, incumbent_source: Any, revision_index: int, seed: Any, pin: object
    ) -> Any:
        """The :class:`providers.Request` one revision sends.

        The incumbent source in **full** — nothing summarised, sampled or
        truncated, the same restraint feature 206 states for the history the
        signal author reads — under :data:`_INCUMBENT_HEADER`, and the index and
        the seed in the user message.  The two knobs come from ``config``: the
        ``temperature`` the deployment rolls and the ``max_tokens`` ceiling
        every authoring request carries (feature 2's two keys).  The model is the
        pin's, so the request names the model the session routed to.
        """
        providers = _providers()
        messages = (
            providers.Message(role="system", content=_SYSTEM_INSTRUCTION),
            providers.Message(
                role="user",
                content=(
                    f"{_DENOMINATION.format(index=revision_index, seed=seed)}\n"
                    f"{_INCUMBENT_HEADER}\n{incumbent_source}"
                ),
            ),
        )
        return providers.Request(
            messages=messages,
            model=self._pin_model(pin),
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )

    # -- The record ----------------------------------------------------------

    def _record(
        self,
        pin: object,
        completion: Any,
        revision_index: int,
        node_id: str,
        seed: Any,
    ) -> Any:
        """The :class:`providers.AuthoringRecord` one revision leaves behind.

        The three tree fields are the revision's own — ``node_id`` is
        ``revision-{index}``, ``campaign_id`` is :data:`POLICY_CAMPAIGN_ID`, and
        ``depth`` is :data:`POLICY_REVISION_DEPTH` — the ``role`` is ``"policy"``,
        the ``pin`` is the one the session answered, the ``sampling`` is an
        :class:`providers.AgentSampling` built with the config's temperature and
        this revision's seed (a draw that *is* reproducible, so ``seed`` is
        recorded and never ``None``), the ``usage`` is the completion's, and the
        ``served_model`` is the model the completion named.  ``tier`` is left at
        the record's default ``None`` — a policy record carries no frontier tier.
        """
        providers = _providers()
        sampling = providers.AgentSampling(
            temperature=self._config.temperature,
            seed=self._seed_for_record(seed),
        )
        return providers.AuthoringRecord(
            node_id=node_id,
            campaign_id=POLICY_CAMPAIGN_ID,
            depth=POLICY_REVISION_DEPTH,
            role="policy",
            pin=pin,
            sampling=sampling,
            usage=completion.usage,
            served_model=completion.model,
        )

    # -- Small readings ------------------------------------------------------

    @staticmethod
    def _pin_model(pin: object) -> str:
        """The model name a request names — read off the pin duck-typed.

        A :class:`providers.ModelPin` carries a ``model`` attribute; reading it
        by name rather than importing the class keeps this file's importability
        free of the scan-order dependency the module docstring describes, and
        the class is the session's own value, so the duck-read is exact.
        """
        model = getattr(pin, "model", None)
        if not isinstance(model, str) or not model:
            raise ReviserOutputError(
                f"{REVISER_OUTPUT_CODE}: the policy pin answered by the "
                f"authoring session carries no model name (got {model!r}), so "
                f"the reviser cannot name the model to complete the request. "
                f"The pin is the session's value and a request names the model "
                f"the session routed to (feature 9)."
            )
        return model

    @staticmethod
    def _seed_for_record(seed: Any) -> int:
        """The revision's seed as the non-negative int a sampling record holds.

        :class:`providers.AgentSampling`'s ``seed`` is a non-negative int in
        ``[0, 2**63 - 1]``; feature 271's seed is *text or an integer* (its own
        :func:`~dreaming.reviser._validated_seed` admits both, because an
        ``f``-string renders both to the same draw material).  The two must
        agree for the record to be writable, so an integer seed is passed
        through and any other value is folded to a stable non-negative integer
        by the same sha256 the default reviser uses — reproducible across
        processes, so a replay of the sweep records the same dice.  ``seed=0``
        is a seed, not an absence; the fold is used only when the value is not
        already a storable int.
        """
        if isinstance(seed, int) and not isinstance(seed, bool) and seed >= 0:
            return seed
        material = f"{seed}".encode()
        return int(hashlib.sha256(material).hexdigest()[:15], 16)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"LLMReviser(campaign_id={POLICY_CAMPAIGN_ID!r}, "
            f"records={len(self.records)})"
        )
