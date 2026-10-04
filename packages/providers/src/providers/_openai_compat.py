"""The OpenAI-compatible backend: one provider, four vendors.

The live-providers addition needs a live backend for every model family the
deployment pins, and three of the four families it serves — OpenAI, DeepSeek
and Google's Gemini — speak dialects of *one* wire protocol: the
chat-completions shape OpenAI defined and everyone else cloned, right down to
the field names.  The fourth family, self-hosted weights behind a vLLM (or any
other OpenAI-compatible server), speaks it on purpose: compatibility with the
OpenAI client is the reason those servers exist.  So the addition has **one**
backend for all four, :class:`OpenAICompatProvider`, and the vendor name an
operator pins decides only the four facts that genuinely differ per vendor —
none of which is the protocol.

This backend owns no transport of its own.  Its :meth:`_complete
<OpenAICompatProvider._complete>` posts one JSON request through feature 1's
door (:func:`providers._live_http.post_json`), so everything a deployment must
hold true of a live call is held true of this one by the door and not
re-decided here: the host guard that refuses a destination nobody declared
before anything is sent, the retry policy for the transient statuses, the
two-word failure vocabulary (:class:`~providers._live_http.ProviderTransportError`
for the network, :class:`~providers._live_http.ProviderHTTPError` for the
vendor) and the secret scrubbing that renders a credential as ``***`` in every
message, repr and log line.  What this module adds on top is exactly the
vendor table and the two translations at either end of the call.

**The vendor table.**  ``openai``, ``deepseek``, ``google`` and ``self-hosted``
— the provider spellings the pin store already uses — each carry a default
base URL, an allowed host, a length-cap key and a cache-figure spelling:

* **openai** — base ``https://api.openai.com/v1``, host ``api.openai.com``,
  and the length cap sent as ``max_completion_tokens``, the spelling OpenAI's
  current API reads (the older ``max_tokens`` is deprecated there while the
  clones still require it, which is the one place the dialects have actually
  drifted).
* **deepseek** — base ``https://api.deepseek.com``, host
  ``api.deepseek.com``, cap ``max_tokens``, and its cache figure reported at
  the top level of ``usage`` as ``prompt_cache_hit_tokens`` rather than
  nested in ``prompt_tokens_details``.
* **google** — Gemini's OpenAI-compatible endpoint, base
  ``https://generativelanguage.googleapis.com/v1beta/openai``, host
  ``generativelanguage.googleapis.com``, cap ``max_tokens``.
* **self-hosted** — no default, because there is nothing to default *to*: the
  weights live wherever the deployment runs them.  ``base_url`` is required,
  and the allowed host is that URL's own host — the operator naming the box
  *is* the declaration the host guard exists to enforce.  Its ``api_key`` may
  be empty, in which case no ``Authorization`` header is sent at all, because
  a lab box behind no auth is a real deployment, not a misconfiguration.

Any other vendor is refused at construction with
:class:`~providers.ProviderNotConfiguredError` — the configuration error the
caller fixes, not a runtime failure discovered mid-request — and the message
names the four it serves.  A hosted vendor's allowlist is pinned to the
vendor's own host and never follows an overriding ``base_url``: the parameter
may re-spell the vendor's own destination (a path prefix, a trailing slash)
but a URL on any other host is the door's refusal, raised before anything is
sent.

**The request translation** is deliberately almost nothing.  The messages go
out verbatim — each turn's role and content as the interface normalized them,
``system`` turns included in ``messages`` rather than lifted to a top-level
field, because the chat-completions protocol has no such field and the
OpenAI-compatible family has no system story to translate (the contrast with
the Anthropic backend, whose protocol *does* and whose backend therefore
joins, is feature 2's to draw).  The temperature and the model name go out as
the request carries them, and the one genuine translation is the length cap's
key: ``max_completion_tokens`` for openai, ``max_tokens`` for the rest.

**The answer translation** is three copies and one refusal.  The response's
``model`` field is copied verbatim into :attr:`Completion.model
<providers.Completion.model>` — *not* checked against the model the provider
was built for, because a vendor that silently serves a different model is
feature 4's finding to catch (its ``require_served``), and a backend that
"helpfully" normalized the serving model away would destroy the evidence.
``finish_reason`` is already the interface's own closed vocabulary — ``stop``
and ``length`` are the two spellings both sides share — so the mapping is the
identity and any third code (``content_filter``, ``tool_calls``, …) is
refused as :class:`~providers.CompletionMalformedError` naming it: a model
stopping for a reason the deployment has no vocabulary for is a fact to read,
not to fold onto ``stop``.  A ``null`` (or absent, or non-text) message
content is refused the same way, naming what the message carried instead of
text.  Usage is copied figure for figure — ``prompt_tokens`` in,
``completion_tokens`` out — with the cache-read count read from the vendor's
own spelling and ``0`` when the response reports none.

Like everything in this member the module is stdlib-only, and testability is
the ``transport`` parameter: a test injects the door's transport callable and
no test of this backend opens a socket.  ``repr(provider)`` shows the vendor,
the model and the base URL — the deployment, in other words — and renders the
credential as ``***``, because a repr is one of the three places a key must
never reach.  Batches are out of scope for the whole addition: this backend
answers one request at a time and keeps the base class's
:class:`~providers.NotImplementedBatchError`.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from ._completion import Completion, Usage
from ._errors import (
    CompletionMalformedError,
    ProviderNotConfiguredError,
    UnknownModelError,
)
from ._live_http import Transport, post_json
from ._provider import Provider
from ._request import Request

__all__ = ["OpenAICompatProvider"]

#: The path every vendor's endpoint hangs off its base URL.  One constant
#: because it is the one part of the URL the four vendors genuinely share —
#: the protocol's own name — while the base URL itself is per-vendor below.
_CHAT_COMPLETIONS_PATH: Final[str] = "chat/completions"

#: The length-cap key OpenAI's current API reads.  Deprecated in the older
#: ``max_tokens`` spelling on OpenAI's own endpoint, and *un*readable there in
#: the newest models — while every clone still requires the old spelling — so
#: the split is a per-vendor fact of the wire, not a style choice.
_MAX_COMPLETION_TOKENS_KEY: Final[str] = "max_completion_tokens"

#: The length-cap key the other three vendors read: DeepSeek's, Google's
#: OpenAI-compatible layer's and every self-hosted server's spelling.
_MAX_TOKENS_KEY: Final[str] = "max_tokens"

#: Where openai, google and the self-hosted servers report the cached-input
#: figure: nested one level down, inside ``usage.prompt_tokens_details``.
_PROMPT_TOKENS_DETAILS_KEY: Final[str] = "prompt_tokens_details"
_CACHED_TOKENS_KEY: Final[str] = "cached_tokens"

#: Where deepseek reports it instead: at the top level of ``usage``, under
#: its own name.  Same figure, different shelf — the one usage field the
#: dialects do not agree on.
_PROMPT_CACHE_HIT_TOKENS_KEY: Final[str] = "prompt_cache_hit_tokens"

#: The usage figures every one of the four vendors reports under the same
#: names, mapped onto :class:`~providers.Usage` figure for figure.
_PROMPT_TOKENS_KEY: Final[str] = "prompt_tokens"
_COMPLETION_TOKENS_KEY: Final[str] = "completion_tokens"

#: The two finish reasons the chat-completions family and the interface share
#: spellings for, so the "mapping" between them is the identity.  A closed
#: set for the same reason :class:`~providers.Completion` closes its own: a
#: third code is a provider inventing a reason the rest of the system has no
#: vocabulary for.
_FINISH_REASONS: Final[frozenset[str]] = frozenset({"stop", "length"})

#: How a credential is rendered wherever this module draws one — the same
#: three stars feature 1's scrubbing uses, so every rendered text in the live
#: path shows a key the same way.
_REDACTED: Final[str] = "***"

#: The self-hosted vendor's spelling, called out as a name because two of the
#: construction guards below branch on it and a bare string literal at each
#: would leave the reader to notice they are the same fact.
_SELF_HOSTED: Final[str] = "self-hosted"


@dataclass(frozen=True)
class _VendorWire:
    """One vendor's four wire differences from its three siblings.

    The whole of what varies per vendor, and nothing else: where the request
    goes by default, which host the door may send it to, which key the length
    cap is sent under, and which shelf of ``usage`` the cached-input figure
    is read from.  Frozen because a vendor's wire facts are not configuration
    a caller tunes — they are facts of the protocol each vendor shipped.
    """

    default_base_url: str | None
    allowed_host: str | None
    length_cap_key: str
    cache_hit_key: str


#: The vendor table.  ``self-hosted`` carries ``None`` for both the default
#: base URL (there is nothing to default to — the deployment names the box)
#: and the allowed host (the base URL's own host, read per provider at
#: construction).  A frozen mapping, so neither the table nor a vendor's entry
#: can be mutated after import by anything in the process.
_VENDORS: Final[Mapping[str, _VendorWire]] = MappingProxyType(
    {
        "openai": _VendorWire(
            default_base_url="https://api.openai.com/v1",
            allowed_host="api.openai.com",
            length_cap_key=_MAX_COMPLETION_TOKENS_KEY,
            cache_hit_key=_CACHED_TOKENS_KEY,
        ),
        "deepseek": _VendorWire(
            default_base_url="https://api.deepseek.com",
            allowed_host="api.deepseek.com",
            length_cap_key=_MAX_TOKENS_KEY,
            cache_hit_key=_PROMPT_CACHE_HIT_TOKENS_KEY,
        ),
        "google": _VendorWire(
            default_base_url=(
                "https://generativelanguage.googleapis.com/v1beta/openai"
            ),
            allowed_host="generativelanguage.googleapis.com",
            length_cap_key=_MAX_TOKENS_KEY,
            cache_hit_key=_CACHED_TOKENS_KEY,
        ),
        _SELF_HOSTED: _VendorWire(
            default_base_url=None,
            allowed_host=None,
            length_cap_key=_MAX_TOKENS_KEY,
            cache_hit_key=_CACHED_TOKENS_KEY,
        ),
    }
)


def _vendor_names() -> str:
    """The four vendors as a readable list, for a refusal's message.

    Built from the table rather than spelled again so the sentence and the
    truth cannot drift apart: a vendor added to the table is named by the
    next refusal without a second edit.
    """
    names = [repr(name) for name in _VENDORS]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _non_negative_int(value: object) -> bool:
    """Whether ``value`` is an int a :class:`~providers.Usage` figure may be.

    ``bool`` is excluded on purpose — it is an ``int`` to Python but not a
    token count to anyone else — and negatives with it, because a count below
    zero is a vendor arithmetic bug this backend refuses rather than forwards.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class OpenAICompatProvider(Provider):
    """A live :class:`~providers.Provider` for the chat-completions family.

    Built for one vendor and one model — ``OpenAICompatProvider("openai",
    key, model="gpt-5-mini")`` — and answers every call to that model by
    posting one JSON request through feature 1's door to the vendor's
    ``{base}/chat/completions`` endpoint and translating the answer into a
    :class:`~providers.Completion`.  The vendor's wire facts (default base
    URL, allowed host, length-cap key, cache-figure spelling) come from the
    table above; everything else — the host guard, the retries, the failure
    vocabulary, the scrubbing — is the door's and is inherited, not restated.

    ``base_url`` overrides a hosted vendor's default destination and may
    re-spell it (a path prefix, a trailing slash) but may **not** rehost it:
    the allowed host stays the vendor's own, so a base URL on any other host
    is the door's refusal, raised before anything is sent.  For ``self-hosted``
    the parameter is required — there is no default to fall back on — and the
    allowed host is the URL's own host, because the operator naming the box
    is the declaration the guard exists to enforce.  A self-hosted key may be
    empty, and then no ``Authorization`` header is sent at all.

    ``transport`` defaults to the door's ``urllib.request`` transport; a test
    injects the door's transport callable and opens no socket.
    """

    def __init__(
        self,
        vendor: str,
        api_key: str,
        *,
        model: str,
        base_url: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        if not isinstance(vendor, str):
            raise ProviderNotConfiguredError(
                f"a vendor must be one of {_vendor_names()}, got a "
                f"{type(vendor).__name__}. The vendor names the wire dialect "
                "a call speaks, and the four the OpenAI-compatible backend "
                "serves are a closed set read from the pin."
            )
        wire = _VENDORS.get(vendor)
        if wire is None:
            raise ProviderNotConfiguredError(
                f"vendor {vendor!r} is not one the OpenAI-compatible backend "
                f"serves; the vendors are {_vendor_names()}. A pin's provider "
                "spelling must be one a live backend exists for, and an "
                "OpenAI-compatible clone nobody has taught the table is a "
                "configuration to fix here, not a call to attempt."
            )
        if not isinstance(api_key, str):
            # The type is named and the value is not rendered: a key of the
            # wrong type is still shaped like a credential, and a refusal is
            # one of the places a credential must never reach.
            raise ProviderNotConfiguredError(
                f"vendor {vendor!r} was built with an api_key that is a "
                f"{type(api_key).__name__} rather than a string. The key "
                "travels in a header, and a header value is text; the "
                "refusal names the type so the caller can see the mistake "
                "without the value ever being rendered."
            )
        if not api_key and vendor != _SELF_HOSTED:
            raise ProviderNotConfiguredError(
                f"vendor {vendor!r} is a hosted API and cannot be called "
                "without a credential; the key may be empty only for "
                f"{_SELF_HOSTED!r}, where the box itself decides whether to "
                "ask for one. An empty key sent to a hosted vendor would be "
                "a refusal the vendor answers after the request left, which "
                "is a worse place to learn it than construction."
            )
        if not isinstance(model, str) or not model:
            raise ProviderNotConfiguredError(
                f"model must be a non-empty string naming the one model this "
                f"provider serves, got {model!r}. The backend is built for a "
                "pinned model at a time and serves no other, so a blank name "
                "is a provider that could answer no call at all."
            )
        if base_url is not None and not isinstance(base_url, str):
            raise ProviderNotConfiguredError(
                f"base_url must be a string naming the endpoint's base, got a "
                f"{type(base_url).__name__}. A base URL is joined to the "
                "chat-completions path, and anything but text cannot be."
            )
        base = wire.default_base_url if base_url is None else base_url
        if base is None:
            raise ProviderNotConfiguredError(
                f"vendor {_SELF_HOSTED!r} has no default base URL — the "
                "weights live wherever the deployment runs them — so the "
                "provider cannot be built without base_url naming where. "
                "Every hosted vendor has a default; self-hosting is the one "
                "spelling whose destination only the operator knows."
            )
        host = urllib.parse.urlsplit(base).hostname
        if not host:
            raise ProviderNotConfiguredError(
                f"base_url {base!r} names no host, and a URL with no host is "
                "not a destination a model call can be sent to. The door "
                "would refuse it before anything was sent; construction "
                "refuses it first, where the caller can fix it."
            )
        self._vendor = vendor
        self._api_key = api_key
        self._model = model
        self._wire = wire
        # A trailing slash is tolerated rather than rejected so an operator's
        # base URL may be copied either way out of a vendor's docs; the join
        # below then never produces a double slash in the path.
        self._base_url = base.rstrip("/")
        # A hosted vendor's allowlist is the vendor's own host, never the
        # URL's — the parameter may re-spell the destination but not rehost
        # it.  Self-hosted is the exception that proves the rule: the URL's
        # own host *is* the declaration, because there is no vendor default
        # for it to agree with.
        self._allowed_host = host if wire.allowed_host is None else wire.allowed_host
        self._transport = transport

    def __repr__(self) -> str:
        # The deployment, not the credential: a repr is one of the three
        # places a key must never reach (the other two are exception messages
        # and log lines), and the vendor, model and base URL are the three
        # facts an operator reading a repr is looking for.
        return (
            f"{type(self).__name__}(vendor={self._vendor!r}, "
            f"model={self._model!r}, base_url={self._base_url!r}, "
            f"api_key={_REDACTED!r})"
        )

    def check_model(self, model: str) -> str:
        """Refuse any model other than the one the provider was built for.

        The backend is built for one pinned model at a time and serves no
        other, so every other name — a sibling model, a newer revision, the
        same name in different case — is refused with
        :class:`~providers.UnknownModelError` *before* a request is sent:
        which model a pin names is a configuration decision, and the place to
        learn it is wrong is at the caller, not in a vendor's error body after
        the request left the machine.
        """
        if model != self._model:
            raise UnknownModelError(
                f"this provider serves exactly one model, {self._model!r} "
                f"(vendor {self._vendor!r}), and was asked for {model!r}. "
                "The OpenAI-compatible backend is built for one pinned model "
                "at a time, so a different name is a configuration the caller "
                "fixes here, before anything is sent — not a failure the "
                "vendor reports after one."
            )
        return model

    def _complete(self, request: Request) -> Completion:
        """Post one chat-completions request through the door and translate.

        The base class has already validated the request and the model (this
        provider's :meth:`check_model` refused anything but its own), so all
        that is left is the backend's whole job: build the body the family
        reads, hand it to feature 1's door with the vendor's allowed host,
        and translate the answered object into the interface's completion.
        """
        answer = post_json(
            f"{self._base_url}/{_CHAT_COMPLETIONS_PATH}",
            self._headers(),
            self._request_body(request),
            allowed_hosts=(self._allowed_host,),
            transport=self._transport,
        )
        return self._completion_from(answer)

    # -- the request half of the translation ---------------------------------

    def _headers(self) -> dict[str, str]:
        """The headers one call carries: the JSON content type, and the key.

        The credential travels as a bearer token under ``authorization``, the
        spelling the whole family reads (Google's OpenAI-compatible layer
        included — its native ``x-goog-api-key`` belongs to the Gemini
        protocol this backend does not speak).  A self-hosted provider built
        with an empty key sends no ``authorization`` header at all: a lab box
        behind no auth is a real deployment, and an empty bearer token would
        be a credential-shaped lie.  The door receives the real value and
        scrubs it from every rendering; see :mod:`providers._live_http`.
        """
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return headers

    def _request_body(self, request: Request) -> dict[str, Any]:
        """The body the chat-completions family reads, from a Request.

        Deliberately almost a copy: the messages go out verbatim with their
        roles (``system`` turns included in ``messages`` — this protocol has
        no top-level system field to lift them to), the temperature and the
        model name as the request carries them, and the one genuine
        translation is the length cap's *key* — ``max_completion_tokens``
        for openai, ``max_tokens`` for the rest — because that is the one
        place the dialects have actually drifted.
        """
        return {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
            self._wire.length_cap_key: request.max_tokens,
        }

    # -- the answer half of the translation -----------------------------------

    def _completion_from(self, answer: dict[str, Any]) -> Completion:
        """Turn the vendor's answered object into the interface's completion.

        Three copies and one refusal.  The content is copied from
        ``choices[0].message.content`` and must be text — a ``null`` content
        is the family's own way of saying the model said nothing (a refused
        content filter, a tool call instead of an answer) and is refused
        *naming* that, never answered as an empty string, because "the model
        said nothing" and "the model said ''" are different facts.  The
        finish reason is the identity mapping over the two spellings both
        sides share; a third code is refused naming it.  The model field is
        copied **verbatim and unchecked** — the serving model, not the asked
        one — because a vendor silently serving another model is feature 4's
        finding (``require_served``) and this backend normalizing it away
        would destroy the evidence.
        """
        choices = answer.get("choices")
        if not isinstance(choices, list) or not choices:
            raise CompletionMalformedError(
                f"a chat-completions answer carries its answer in a non-empty "
                f"choices list, and this answer's choices is {choices!r}. "
                "The one shape every vendor of this family answers is "
                "choices[0]; an answer without it is not a shape a reader "
                "can meet later as an IndexError."
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise CompletionMalformedError(
                f"choices[0] must be an object carrying the answer's message, "
                f"got {first!r} ({type(first).__name__}). The family answers "
                "one object per choice, and anything else is not a choice a "
                "reader can read a message out of."
            )
        finish_reason = first.get("finish_reason")
        if finish_reason not in _FINISH_REASONS:
            raise CompletionMalformedError(
                f"choices[0].finish_reason {finish_reason!r} is not one of "
                "('stop', 'length'). The family and the interface "
                "share these two spellings, so the mapping between them is "
                "the identity; a third code — content_filter, tool_calls — "
                "is a model stopping for a reason the deployment has no "
                "vocabulary for, and it is refused naming it rather than "
                "folded onto a reason it does not carry."
            )
        message = first.get("message")
        if not isinstance(message, dict):
            raise CompletionMalformedError(
                f"choices[0].message must be an object carrying the answer's "
                f"text, got {message!r} ({type(message).__name__}). The "
                "answer's content is read out of this one field, and an "
                "answer whose message is not an object has no field to read."
            )
        content = message.get("content")
        if not isinstance(content, str):
            if "content" not in message:
                complaint = "carries no content at all"
            elif content is None:
                complaint = "carries null instead of the text"
            else:
                complaint = (
                    f"carries a {type(content).__name__} instead of the text"
                )
            raise CompletionMalformedError(
                f"choices[0].message {complaint}. The family answers a "
                "model's text in message.content, and a null content is its "
                "own way of saying the model said nothing — a refused content "
                "filter, a tool call instead of an answer. That is a fact to "
                "refuse naming, not to answer as an empty string, because a "
                "caller cannot tell a model that said nothing from one that "
                "said ''."
            )
        usage = self._usage_from(answer)
        return self.completion(
            content=content,
            model=answer.get("model"),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            finish_reason=finish_reason,
        )

    def _usage_from(self, answer: dict[str, Any]) -> Usage:
        """Read the usage object as the interface's token accounting.

        The two billed figures are copied from the names every vendor of the
        family reports — ``prompt_tokens`` and ``completion_tokens`` — and a
        usage object that does not carry both as non-negative ints is refused
        naming which figure it broke, rather than invented as zero: a token
        count the vendor never reported is the number the budget (feature 7)
        and the cache-rate measurement (feature 200) account with, and a
        silent zero would understate both.  The cache-read count is the
        vendor's own spelling and may honestly be absent — see
        :meth:`_cache_read_tokens`.
        """
        usage = answer.get("usage")
        if not isinstance(usage, dict):
            raise CompletionMalformedError(
                f"a chat-completions answer carries its token accounting in a "
                f"usage object, and this answer's usage is {usage!r} "
                f"({type(usage).__name__}). The billed figures a completion "
                "reports are read from this one field, and an answer without "
                "the field has no figures to report."
            )
        figures: dict[str, int] = {}
        for key in (_PROMPT_TOKENS_KEY, _COMPLETION_TOKENS_KEY):
            value = usage.get(key)
            if not _non_negative_int(value):
                raise CompletionMalformedError(
                    f"usage.{key} must be a non-negative int, got {value!r} "
                    f"({type(value).__name__}). The token accounting a "
                    "completion carries is what the budget and the cost model "
                    "account with, and a figure that is not a count is "
                    "refused here rather than coerced into one."
                )
            figures[key] = value
        return Usage(
            input_tokens=figures[_PROMPT_TOKENS_KEY],
            output_tokens=figures[_COMPLETION_TOKENS_KEY],
            cache_read_tokens=self._cache_read_tokens(usage),
        )

    def _cache_read_tokens(self, usage: dict[str, Any]) -> int:
        """Read the cached-input figure from the vendor's own shelf of usage.

        openai, google and the self-hosted servers nest it —
        ``usage.prompt_tokens_details.cached_tokens`` — while deepseek shelves
        it at the top level as ``usage.prompt_cache_hit_tokens``.  The table
        names which shelf this vendor's figure is on, and the figure is
        optional in both spellings: a response that reports none — the
        details object absent, empty, or null-carrying — counts zero, because
        a provider that did not report a cache hit has not earned the caller
        a number, and the absence of a figure is not a figure.
        """
        if self._wire.cache_hit_key == _PROMPT_CACHE_HIT_TOKENS_KEY:
            reported = usage.get(_PROMPT_CACHE_HIT_TOKENS_KEY)
        else:
            details = usage.get(_PROMPT_TOKENS_DETAILS_KEY)
            reported = (
                details.get(_CACHED_TOKENS_KEY)
                if isinstance(details, dict)
                else None
            )
        return reported if _non_negative_int(reported) else 0
