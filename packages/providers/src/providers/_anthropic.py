"""The Anthropic Messages backend — a live provider behind the one seam.

The provider interface of feature 192 is a contract with no transport: a
caller hands it a :class:`~providers.Request` and gets a
:class:`~providers.Completion`, and the recorded backend of feature 193
answers from fixtures precisely so the deployment could run before any
model was reachable.  This module is one of the two live backends the
live-providers addition introduces: :class:`AnthropicProvider` completes a
request by translating it into one Anthropic Messages-API call and
translating the answer back, so a caller written against the seam — the
signal agent, the hypothesis author — reaches Claude without learning a
single wire fact.  Which URL, which headers, which body fields, which stop
codes are all decided here, once, rather than re-decided (and re-forgotten)
by every caller.

The transport is feature 1's door and nothing else.  :meth:`_complete`
posts its one JSON request through :func:`providers._live_http.post_json`
with ``allowed_hosts`` pinned to :data:`ANTHROPIC_ALLOWED_HOSTS` — the one
host an Anthropic credential may ever travel to, fixed regardless of the
``base_url`` a deployment hands in — so the host guard, the retry policy,
the failure vocabulary and the secret scrubbing are the door's, inherited
by every live call this backend makes rather than re-implemented beside
them.  ``transport=None`` means the door's ``urllib.request`` default; a
test injects a callable of the door's :data:`~providers._live_http.Transport`
shape and no test of this backend opens a socket.

**The translation, request half.**  System messages become the top-level
``system`` field, joined — the Messages API carries the standing
instructions outside the conversation, and a deployment whose prompts hold
two system turns is a deployment whose standing instructions are one text.
The remaining turns are sent as ``messages`` in the order they were given,
roles verbatim.  The prefix is cacheable at exactly the two breakpoints
that cover everything stable in a call: the system text, and the message
just before the final one — every turn of the conversation except the last
is prefix, and the last turn is what changes between calls, so caching
through the turn before it caches all of the stable part.  Each of the two
carries ``cache_control {type: "ephemeral"}``, and nothing else does: a
call with no system text spends one breakpoint, a single-message call
spends one or none, and no call this backend sends ever spends more than
two.

**Temperature above 1.0 is refused, never clamped.**  The interface's
:class:`~providers.Request` admits temperatures up to 2.0 — the widest
range the deployment's pinned models expose — but the Messages API's own
ceiling is 1.  A request above it raises
:class:`ProviderRequestError` (code word
:data:`UNSUPPORTED_TEMPERATURE_CODE`) *before any call*: clamping it would
silently answer a different sampling regime than the caller asked for, and
an answer that looks fine while being sampled at a temperature nobody
requested is exactly the quiet wrong a research system must not produce.
The refusal happens in :meth:`_complete` ahead of the door, so nothing is
sent at all — the same "refuse before the transport" discipline
:mod:`providers._budget` applies to spend and the door itself applies to
hosts.

**The translation, answer half.**  The text blocks of the answer's
``content`` are joined in order into ``Completion.content`` — a non-text
block (a thinking block, a tool call) is not text and does not join.  The
response's ``model`` field is copied *verbatim* into
``Completion.model``: a completion names the model that served it, dated
snapshot suffix and all, and whether that model is the one the pin asked
for is feature 4's ``require_served`` question, not this backend's — the
backend reports, the registry checks.  ``stop_reason`` maps onto the
interface's closed set — ``end_turn`` and ``stop_sequence`` to ``stop``,
``max_tokens`` to ``length`` — and any other reason raises
:class:`~providers.CompletionMalformedError` naming it, because a stop
code the interface has no vocabulary for is a provider inventing a reason
the rest of the system cannot read.  Usage counts every input token the
call read: ``input_tokens`` is the response's ``input_tokens`` *plus*
``cache_creation_input_tokens`` *plus* ``cache_read_input_tokens`` — the
prompt, the prefix newly written into the cache and the prefix read back
from it are all input the call consumed, and a total that dropped any of
the three would under-report what the call spent — while
``cache_write_tokens`` and ``cache_read_tokens`` each carry their cache
figure separately too (a write and a read bill at different rates
downstream) and ``output_tokens`` passes through.

**The key never renders.**  ``repr(provider)`` shows the credential as
``***`` and never its value — the same rendering discipline the door
applies to secret headers, applied here to the object that holds one: a
provider printed into a log line, a traceback or a bug report arrives
masked, while the bytes on the wire of course carry the real key, because
scrubbing is a property of rendering, never of sending.

Construction validates its configuration with :class:`ValueError` — a
blank or non-string key, model or base URL, or a non-callable transport,
never got well-formed enough to be a provider-contract question, the same
split :mod:`providers._budget` takes for its own ceilings.

**The per-model sampling table (added 2026-10-06, additions_spec_real_campaign_path.xml feature 5).**
The paragraph above was true the day this backend was written and stopped
being true the day an operator pointed it at a real deployment: the
Messages API answered ``claude-opus-5-5`` and ``claude-sonnet-5-5`` with
HTTP 400, ``"`temperature` is deprecated for this model"``, to a body
that unconditionally carried ``temperature`` — the ceiling refusal above
protects the *range*, but these two models reject the *field*, at any
value, default included.  :func:`_sampling_mode` is the table that
decides, by exact model name, whether a body may carry
``temperature``/``top_p``/``top_k`` at all:

* ``claude-opus-5-5``, ``claude-opus-5``, ``claude-sonnet-5-5``,
  ``claude-sonnet-5`` and the Fable family (any model starting
  ``claude-fable-``, matched by prefix rather than enumerated, so a later
  Fable snapshot this table is never updated for still gets the
  generation's treatment instead of silently falling through) carry none
  of the three — this is :data:`NO_SAMPLING_MODE`.  In its place they take
  ``output_config.effort`` when the caller names one (:data:`EFFORT_LEVELS`:
  ``low``, ``medium``, ``high``, ``xhigh``, ``max``) — effort is the
  control these models actually expose, and the body omits
  ``output_config`` entirely when no effort was named, rather than send an
  empty object the vendor would have to interpret.
* ``claude-haiku-4-5`` (and, by the same generation, any older model this
  table does not yet need to name) is :data:`TEMPERATURE_MODE`: it keeps
  the behaviour above verbatim — ``temperature`` travels, the 1.0 ceiling
  is enforced, effort is never sent to a model with no slot for it.
* A model this table has no entry for is treated as :data:`NO_SAMPLING_MODE`
  — the safe default, since sending a field a model rejects is an HTTP 400
  discovered mid-campaign, while withholding one a model would have
  accepted is at worst a knob the call did not turn — and the decision is
  logged once through this module's own logger, so an operator reading a
  campaign's log sees exactly which model fell through to the default and
  can add it to the table once its behaviour is verified.

The table is consulted exactly once per request, inside :func:`_request_body`
— never twice, so an unknown model's fallback is not logged twice for one
call — and the temperature-ceiling refusal above only fires for a model
this table says accepts temperature at all: a no-sampling model's request
never reaches that check, because the field it would guard never ships.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Final

from ._completion import Completion, Usage
from ._errors import CompletionMalformedError, ProviderError, UnknownModelError
from ._live_http import Transport, post_json
from ._provider import Provider
from ._request import Request

__all__ = [
    "ANTHROPIC_ALLOWED_HOSTS",
    "ANTHROPIC_API_HOST",
    "ANTHROPIC_VERSION",
    "DEFAULT_BASE_URL",
    "EFFORT_LEVELS",
    "MESSAGES_PATH",
    "NO_SAMPLING_MODE",
    "TEMPERATURE_MODE",
    "UNSUPPORTED_TEMPERATURE_CODE",
    "AnthropicProvider",
    "ProviderRequestError",
    "sent_sampling",
]

#: This module's own logger — the one line :func:`_sampling_mode` emits for
#: a model the table does not name, so an operator reading a campaign's log
#: sees exactly which model fell through to the safe default.
_logger = logging.getLogger(__name__)

#: The one host an Anthropic credential may travel to.  Spelled as a name
#: because it appears twice — as the default base URL's host and as the sole
#: member of the allowlist — and the two are one fact, not two strings that
#: happen to agree.
ANTHROPIC_API_HOST: Final[str] = "api.anthropic.com"

#: The hosts :meth:`AnthropicProvider._complete` declares to feature 1's
#: door.  Always the one vendor host, whatever ``base_url`` was handed in:
#: the allowlist is the deployment's statement of where keys may travel, and
#: a base URL pointing anywhere else meets the door's refusal here —
#: :class:`~providers._live_http.ProviderHostRefusedError`, before anything
#: is sent — rather than a quiet call to a place nobody declared.
ANTHROPIC_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({ANTHROPIC_API_HOST})

#: The Messages-API version this backend speaks, pinned rather than
#: defaulted: a vendor header that drifted between calls is a backend whose
#: answers changed shape under a deployment that changed nothing.
ANTHROPIC_VERSION: Final[str] = "2023-06-01"

#: Where the Messages API lives when the caller says nowhere else.
DEFAULT_BASE_URL: Final[str] = f"https://{ANTHROPIC_API_HOST}"

#: The Messages-API endpoint's own path, appended to the base URL.
MESSAGES_PATH: Final[str] = "/v1/messages"

#: The greppable word that opens every :class:`ProviderRequestError`
#: message: ``unsupported_temperature``.  An operator greps one token for
#: *a live call was refused because the ask itself cannot be sent as made*
#: and lands on this backend's one such refusal — on the precedent
#: :data:`providers._budget.BUDGET_EXHAUSTED_CODE` sets for its own word.
UNSUPPORTED_TEMPERATURE_CODE: Final[str] = "unsupported_temperature"

#: The role whose turns leave the conversation for the top-level system
#: field.  The interface's own closed role set spells it; this backend
#: repeats it as a name because it is the one role it treats differently,
#: and a reader deserves to see which without counting.
_SYSTEM_ROLE: Final[str] = "system"

#: The Messages API's own sampling-temperature ceiling.  The interface
#: admits up to 2.0 because other pinned vendors expose that wide a knob;
#: this vendor does not, and the gap is closed by refusing, never by
#: clamping (see the module docstring for why clamping is the quiet wrong).
_MAX_TEMPERATURE: Final[float] = 1.0

#: The response ``stop_reason`` spellings this backend knows, mapped onto
#: the interface's closed finish-reason set.  Two vendor spellings for one
#: normalized reason — a natural end is a natural end whether the model
#: chose it or a stop sequence did — and every other spelling is a reason
#: the interface has no vocabulary for, refused by name rather than
#: guessed-at.
_STOP_REASONS: Final[Mapping[str, str]] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
}

#: A request to a model in this mode carries ``temperature`` (and would carry
#: ``top_p``/``top_k`` if a caller ever turned those knobs), exactly as the
#: rest of this module describes.
TEMPERATURE_MODE: Final[str] = "temperature"

#: A request to a model in this mode carries none of ``temperature``,
#: ``top_p`` or ``top_k`` — the vendor rejects the field outright — and
#: carries ``output_config.effort`` instead, when a caller named one.  Also
#: the safe default for a model :func:`_sampling_mode` does not recognise.
NO_SAMPLING_MODE: Final[str] = "no_sampling"

#: The per-model sampling table, verified 2026-10-06 against the live
#: Messages API (additions_spec_real_campaign_path.xml feature 5): these four
#: exact model names answered HTTP 400, ``"`temperature` is deprecated for
#: this model"``, to a request carrying it.  See the module docstring's
#: "per-model sampling table" section for the reasoning; this set and
#: :data:`_FABLE_PREFIX` together are :data:`NO_SAMPLING_MODE`'s table.
_NO_SAMPLING_MODELS: Final[frozenset[str]] = frozenset(
    {
        "claude-opus-5-5",
        "claude-opus-5",
        "claude-sonnet-5-5",
        "claude-sonnet-5",
    }
)

#: The Fable family's name prefix.  Matched rather than enumerated: the
#: family shares the 5.x generation's sampling restriction, and a prefix
#: survives a later Fable snapshot this table was never updated for, where
#: an enumerated set would silently fall through to the default instead
#: (which happens to agree here, but a reader should not have to know that).
_FABLE_PREFIX: Final[str] = "claude-fable-"

#: The one model verified, as of the same date, to still accept
#: ``temperature`` — "claude-haiku-4-5 and older keep temperature" in the
#: feature's own words.  A deployment pinning a genuinely older model this
#: table has not yet verified gets :data:`NO_SAMPLING_MODE`'s safe default,
#: logged once, rather than an assumption that it behaves like this one.
_TEMPERATURE_MODELS: Final[frozenset[str]] = frozenset({"claude-haiku-4-5"})

#: ``output_config.effort``'s closed set — the control a no-sampling model
#: exposes in place of temperature.  Shared with :mod:`providers._authoring`,
#: which validates an authoring config's own ``effort`` key against this same
#: set, so the two cannot drift into accepting different spellings of "the
#: same five levels".
EFFORT_LEVELS: Final[frozenset[str]] = frozenset(
    {"low", "medium", "high", "xhigh", "max"}
)


def _sampling_mode(model: str) -> str:
    """Whether ``model`` accepts ``temperature``, or needs ``effort`` instead.

    The one place this backend decides, by exact model name (and the Fable
    family's prefix), which of the two wire shapes a request takes — see the
    module docstring's "per-model sampling table" section for why the table
    exists and what each entry means.  An unrecognised model answers
    :data:`NO_SAMPLING_MODE`, the safe default, and this function is the one
    call site that logs the fallback — called exactly once per request, so
    one call never logs the decision twice.
    """
    if model in _NO_SAMPLING_MODELS or model.startswith(_FABLE_PREFIX):
        return NO_SAMPLING_MODE
    if model in _TEMPERATURE_MODELS:
        return TEMPERATURE_MODE
    _logger.warning(
        "providers._anthropic: model %r has no entry in the per-model "
        "sampling table; treating it as %s (no temperature, top_p or "
        "top_k sent) rather than risk the vendor's HTTP 400. Add it to "
        "_NO_SAMPLING_MODELS or _TEMPERATURE_MODELS once its behaviour is "
        "verified.",
        model,
        NO_SAMPLING_MODE,
    )
    return NO_SAMPLING_MODE


def sent_sampling(
    model: str, *, temperature: float | None = None, effort: str | None = None
) -> dict[str, object]:
    """The sampling settings a request to ``model`` would actually carry.

    The one place a caller — today, a test; once a later feature widens
    :mod:`providers._sampling` and :mod:`providers._pin_store` to hold it, an
    authoring record too — can ask *what would this backend actually put on
    the wire* without building a full :class:`~providers.Request` and a
    transport to inspect.  Mirrors :func:`_request_body`'s own decision
    exactly, because both read :func:`_sampling_mode`:

    * :data:`TEMPERATURE_MODE` answers ``{"temperature": temperature}`` when
      ``temperature`` is not ``None``, and ``{}`` when it is — the same
      "nothing to send" state :func:`_request_body` reaches for a request
      whose knob nobody turned.
    * :data:`NO_SAMPLING_MODE` answers ``{"effort": effort}`` when ``effort``
      is not ``None``, and ``{}`` otherwise — never ``temperature``, whatever
      value a caller handed in, because this mode's whole point is that the
      vendor never receives that field.

    This is the honest half of feature 5's "never a temperature the vendor
    did not apply": a caller recording what one call rolled reads this
    function's answer, not the config's raw ``temperature``/``effort``
    fields, so a no-sampling model's record can never claim a temperature
    that never reached the wire.
    """
    if _sampling_mode(model) == TEMPERATURE_MODE:
        return {} if temperature is None else {"temperature": temperature}
    return {} if effort is None else {"effort": effort}


class ProviderRequestError(ProviderError):
    """A live call was refused because the request itself cannot be sent as asked.

    The live backends' word for the refusal that is the *ask's* own: the
    call was never placed, because something about the request cannot
    travel to the vendor as the caller stated it.  This module's one raise
    site — and this addition's only one — is the Messages API's temperature
    ceiling, so the class and :data:`UNSUPPORTED_TEMPERATURE_CODE` are one
    pair, the way every error class in this member's transport family
    carries exactly one code word of its own.

    A :class:`~providers.ProviderError` directly, on the convention this
    package states for every new error class: the caller catching the
    interface's base is catching "the provider contract could not be
    completed", and a request that cannot be sent as asked is exactly that
    — while the repair it names (fix the ask, don't retry the call) is
    carried by the code word, not by a second inheritance tree.

    Distinct from :class:`~providers.CompletionMalformedError` because
    nothing was answered: there is no completion to call malformed, and a
    caller that caught the two together would be conflating "my request
    was impossible" with "the model answered wrong" — two different
    repairs, as the module's taxonomy docstrings each insist.
    """

    def __init__(self, message: str) -> None:
        # The code word is prefixed at the type rather than at each raise
        # site, so the token and the class are one edit and cannot drift
        # apart — the discipline every code word in this member follows.
        super().__init__(f"{UNSUPPORTED_TEMPERATURE_CODE}: {message}")

    @property
    def code(self) -> str:
        """The refusal's greppable code — :data:`UNSUPPORTED_TEMPERATURE_CODE`."""
        return UNSUPPORTED_TEMPERATURE_CODE


def _require_text(value: object, field: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else.

    Shared by every constructor argument this backend refuses at
    construction, because they fail the same way and owe the caller the
    same explanation: a key, a model or a base URL is a string a live call
    is built from, and a blank or non-string one is a provider that was
    never well-formed enough to place a call — :class:`ValueError`, never
    a :class:`~providers.ProviderError`, on the same split
    :func:`providers._budget.BudgetedProvider` takes for its ceilings.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"AnthropicProvider.{field} must be a non-empty string, got "
            f"{value!r} ({type(value).__name__}). A live backend is built "
            f"from its {field}; a blank or non-string one is a provider "
            f"that cannot place the call it exists to place, refused here "
            f"at construction rather than mid-request."
        )
    return value


def _text_block(text: str, *, cacheable: bool = False) -> dict[str, Any]:
    """One Messages-API text block, optionally a prompt-cache breakpoint.

    ``cache_control`` rides a content block or nowhere — the wire format
    has no string-level spelling of it — so every text this backend sends
    is a one-block list and the breakpoint is a property of the block.
    """
    block: dict[str, Any] = {"type": "text", "text": text}
    if cacheable:
        block["cache_control"] = {"type": "ephemeral"}
    return block


def _request_body(request: Request, *, effort: str | None = None) -> dict[str, Any]:
    """Translate one admitted request into one Messages-API body.

    System turns join into the top-level ``system`` field (absent when
    there are none — an empty system field is a statement the vendor would
    read, and this backend has nothing to say then); every other turn is
    forwarded in order with its role verbatim.  The two cache breakpoints
    — the system text and the message before the final one — are decided
    here and nowhere else, which is what keeps every body this backend
    sends at two breakpoints or fewer.

    The sampling fields are decided last, by :func:`_sampling_mode` on
    ``request.model``: a :data:`TEMPERATURE_MODE` model gets ``temperature``
    — refused above :data:`_MAX_TEMPERATURE`, as before — and a
    :data:`NO_SAMPLING_MODE` model gets neither temperature nor the ceiling
    refusal (there is nothing to refuse a field that never ships), carrying
    ``output_config.effort`` instead when ``effort`` is not ``None``, and no
    ``output_config`` at all when it is — an empty object is a statement the
    vendor would have to interpret, and this backend has nothing to say then.
    """
    system_texts = [
        message.content for message in request.messages if message.role == _SYSTEM_ROLE
    ]
    conversation = [
        message for message in request.messages if message.role != _SYSTEM_ROLE
    ]
    body: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens,
    }
    if system_texts:
        body["system"] = [_text_block("\n".join(system_texts), cacheable=True)]
    body["messages"] = [
        {
            "role": message.role,
            "content": [
                _text_block(message.content, cacheable=index == len(conversation) - 2)
            ],
        }
        for index, message in enumerate(conversation)
    ]
    if _sampling_mode(request.model) == TEMPERATURE_MODE:
        if request.temperature > _MAX_TEMPERATURE:
            raise ProviderRequestError(
                f"temperature {request.temperature} is above the Messages "
                f"API's ceiling of {_MAX_TEMPERATURE}, and this provider "
                f"refuses the request rather than clamping it. A clamped "
                f"temperature would answer a sampling regime the caller did "
                f"not ask for — an answer that looks fine while being "
                f"sampled at a temperature nobody requested. Send a "
                f"temperature of at most {_MAX_TEMPERATURE} or bind a "
                f"provider whose model exposes the range you need."
            )
        body["temperature"] = request.temperature
    elif effort is not None:
        body["output_config"] = {"effort": effort}
    return body


def _join_text_blocks(blocks: object) -> str:
    """Join the answer's text blocks into the completion's content, in order.

    Only ``text`` blocks join — a thinking block or a tool call is a real
    answer block that is not text, and this backend's contract is one
    content string, not a block list with a shape the interface never
    promised.  Anything that is not a list of blocks, or a ``text`` block
    whose text is not a string, is an answer that did not carry the
    contract's shape and leaves as
    :class:`~providers.CompletionMalformedError`, never as an
    ``AttributeError`` some downstream reader would meet instead.
    """
    if not isinstance(blocks, list):
        raise CompletionMalformedError(
            f"a Messages answer's content must be a list of blocks, got "
            f"{blocks!r} ({type(blocks).__name__}). The Messages API answers "
            f"with content blocks, and this backend joins them into the one "
            f"content string the interface promises — an answer whose "
            f"content is not a block list is not a shape this backend can "
            f"read."
        )
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            raise CompletionMalformedError(
                f"a Messages answer's content block must be an object, got "
                f"{block!r} ({type(block).__name__}). A block carries a type "
                f"and its text; anything else is not a block the Messages "
                f"API defines."
            )
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if not isinstance(text, str):
            raise CompletionMalformedError(
                f"a Messages answer's text block must carry its text as a "
                f"string, got {text!r} ({type(text).__name__}). This backend "
                f"joins text blocks into one content string; a text block "
                f"without string text is a join with nothing honest to join."
            )
        parts.append(text)
    return "".join(parts)


def _finish_reason(stop_reason: object) -> str:
    """Map the vendor's ``stop_reason`` onto the interface's closed set.

    ``end_turn`` and ``stop_sequence`` are the two vendor spellings of a
    natural end; ``max_tokens`` is the output ceiling having been hit.
    Every other reason — including an absent one — is a stop code the
    interface has no vocabulary for, and is refused *naming it*, so the
    operator reading the refusal sees the vendor's own word rather than a
    paraphrase that dropped it.
    """
    if isinstance(stop_reason, str) and stop_reason in _STOP_REASONS:
        return _STOP_REASONS[stop_reason]
    raise CompletionMalformedError(
        f"a Messages answer's stop_reason must be one of "
        f"{sorted(_STOP_REASONS)!r}, got {stop_reason!r}. The interface's "
        f"finish reasons are a closed set — a natural end maps to 'stop' "
        f"and the output ceiling to 'length' — and a stop code outside "
        f"that mapping is the vendor inventing a reason the rest of the "
        f"system has no reader for."
    )


def _counter(usage: Mapping[str, Any], name: str) -> int:
    """Read one usage counter, an absent one reading as zero.

    Zero rather than a refusal for an absent counter because the interface
    itself reads absence that way — :class:`~providers.Usage` defaults its
    cache figure to zero "because a provider that does not report it has
    not earned the caller a negative number" — and the cache counters are
    genuinely absent from a cold call.  A counter that is present but is
    not a non-negative int is a malformed answer, not an absent figure, and
    is refused as one.
    """
    value = usage.get(name, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CompletionMalformedError(
            f"a Messages answer's usage.{name} must be a non-negative int, "
            f"got {value!r} ({type(value).__name__}). Usage is the token "
            f"accounting the completion carries; a counter that is not a "
            f"count is an answer this backend cannot account for."
        )
    return value


def _usage(usage: object) -> Usage:
    """Translate the answer's usage into the interface's record.

    ``input_tokens`` sums every input counter the Messages API reports —
    the plain input, the prefix newly written into the prompt cache and
    the prefix read back from it — because all three are input tokens the
    call consumed, and a total that dropped any of them would under-report
    the call's spend to every cost total downstream.  The cache counters
    also each travel on their own field: a cache write and a cache read
    bill at different rates, and :attr:`Usage.cache_write_tokens` and
    :attr:`Usage.cache_read_tokens` are where the deployment reads those
    rates from.
    """
    if not isinstance(usage, dict):
        raise CompletionMalformedError(
            f"a Messages answer's usage must be an object, got "
            f"{usage!r} ({type(usage).__name__}). The completion carries "
            f"its token accounting as a normalized record; an answer whose "
            f"usage is not an object of counters is not a shape this "
            f"backend can read."
        )
    input_tokens = _counter(usage, "input_tokens")
    cache_creation = _counter(usage, "cache_creation_input_tokens")
    cache_read = _counter(usage, "cache_read_input_tokens")
    return Usage(
        input_tokens=input_tokens + cache_creation + cache_read,
        output_tokens=_counter(usage, "output_tokens"),
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_creation,
    )


def _completion(answer: Mapping[str, Any]) -> Completion:
    """Translate one decoded Messages answer into the interface's completion.

    The response's ``model`` is copied verbatim — dated snapshot suffix and
    all — because a completion names the model that *served* it, and
    whether that model is the one the pin asked for is feature 4's
    ``require_served`` question, asked by the registry that knows the pin,
    not by the backend that only watched the answer arrive.
    """
    model = answer.get("model")
    if not isinstance(model, str) or not model:
        raise CompletionMalformedError(
            f"a Messages answer's model must be a non-empty string, got "
            f"{model!r}. A completion names the model that served it — the "
            f"one fact provenance downstream pins — and an answer that "
            f"does not name one cannot be accounted for."
        )
    return Completion(
        content=_join_text_blocks(answer.get("content")),
        model=model,
        usage=_usage(answer.get("usage")),
        finish_reason=_finish_reason(answer.get("stop_reason")),
    )


class AnthropicProvider(Provider):
    """A :class:`~providers.Provider` whose transport is the Messages API.

    Constructed for exactly one model — :meth:`check_model` refuses any
    other name with :class:`~providers.UnknownModelError`, because a pin
    naming a model this backend was not built for is a configuration error
    to fix before the call, not a call to send — and for exactly one
    credential, which reaches the wire in the ``x-api-key`` header and
    never reaches a repr, a message or a log line.  ``base_url`` and
    ``transport`` exist for the deployment and the suite respectively: the
    door's host guard still allows only
    :data:`ANTHROPIC_API_HOST` (a loopback base URL is the door's one
    plaintext exception), and an injected transport is how every test of
    this backend answers from a script without opening a socket.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        effort: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._api_key = _require_text(api_key, "api_key")
        self._model = _require_text(model, "model")
        self._base_url = _require_text(base_url, "base_url")
        if effort is not None and effort not in EFFORT_LEVELS:
            raise ValueError(
                f"AnthropicProvider.effort must be one of "
                f"{sorted(EFFORT_LEVELS)!r} or None, got {effort!r} "
                f"({type(effort).__name__}). effort is the control a "
                f"no-sampling model exposes in place of temperature, and a "
                f"value outside the vendor's closed set is not a level any "
                f"model honours."
            )
        self._effort = effort
        if transport is not None and not callable(transport):
            raise ValueError(
                f"AnthropicProvider.transport must be a callable of the "
                f"door's Transport shape or None, got {transport!r} "
                f"({type(transport).__name__}). The transport is the one "
                f"seam this backend's tests drive; something that is not "
                f"a callable is not a seam, it is a crash deferred to the "
                f"first call."
            )
        self._transport = transport

    def __repr__(self) -> str:
        # The credential renders as '***' — never its value — on the same
        # discipline the door applies to secret headers: rendering is where
        # a key leaks, and a provider printed into a log, a traceback or a
        # bug report must arrive masked.  Everything else a reader of a
        # repr wants (which model, which base URL) stays.
        return (
            f"{type(self).__name__}(api_key='***', model={self._model!r}, "
            f"base_url={self._base_url!r})"
        )

    def check_model(self, model: str) -> str:
        """Refuse any model other than the one this backend was built for.

        A live backend is constructed for one model — the pin's model — and
        a request naming another is a configuration the caller can fix, not
        a runtime failure to be discovered mid-request: the interface's own
        reason for :meth:`~providers.Provider.check_model`, and the reason
        this backend pins the set to the single name it holds rather than
        leaving the permissive default.  The message names the asked model
        and the served one, never the key.
        """
        if model != self._model:
            raise UnknownModelError(
                f"this AnthropicProvider serves {self._model!r} only, and "
                f"{model!r} is not it. A live backend is built for one "
                f"model, so a request naming another is a configuration "
                f"error to fix before the call — not a call to send."
            )
        return model

    def _complete(self, request: Request) -> Completion:
        # The temperature ceiling (for a model that accepts temperature at
        # all) is checked inside _request_body, before the door is reached,
        # so a refused temperature sends nothing — no socket, no body
        # serialization, no key on any wire.  Never clamped: see the module
        # docstring for the quiet wrong a clamped temperature would answer.
        answer = post_json(
            f"{self._base_url.rstrip('/')}{MESSAGES_PATH}",
            self._headers(),
            _request_body(request, effort=self._effort),
            allowed_hosts=ANTHROPIC_ALLOWED_HOSTS,
            transport=self._transport,
        )
        return _completion(answer)

    def _headers(self) -> dict[str, str]:
        """The headers one Messages call carries: the credential, the pinned
        version, the body's type.

        The key travels here — to the transport, verbatim — because the
        vendor cannot authenticate a masked call; where it must not travel
        is every rendering, which is the door's scrubbing and this class's
        own ``__repr__``, not this dict.
        """
        return {
            "content-type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
