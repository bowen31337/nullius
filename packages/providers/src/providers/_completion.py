"""The normalized completion object — feature 192's one answer.

Every model call in the deployment passes through the one provider interface
(:class:`providers.Provider`) and returns *this* object and nothing else.
That is the whole of the feature: the caller never sees a provider SDK's
response type, a transport's payload, or a model-specific shape — it sees a
:class:`Completion`, and every provider, whatever it runs underneath, returns
one.  A caller written against the interface is therefore portable across
providers and across tiers without a rewrite, because the answer it reads is
the same object in every case.

What the completion carries is exactly what the rest of the system needs from
a model answer, and no more — the interface is deliberately thin, because a
normalized object that smuggled every provider-specific field behind a
generic name would be a second, divergent copy of each provider's contract
(the same reason ``infra.security.provider_boundary`` models a request as
opaque: the payload shape belongs to the caller, not to the seam):

* ``content`` — the answer text.  The one field every caller reads; the
  message body the model produced.

* ``model`` — the model that produced it.  Persisted downstream (feature 196
  records the serving provider, feature 203 the ``agent_model_id`` triple),
  so a completion names its own author rather than leaving the caller to
  remember which model it asked.  It is the model that *served* the answer,
  which a tiering or rotation layer may change from what the caller asked
  for — so it is reported, not assumed.

* ``usage`` — the token accounting (input, output, and a cache-read count),
  carried as a small immutable record so cost and fill accounting downstream
  can read it without re-parsing a provider payload.  ``cache_read`` defaults
  to zero because not every provider reports it and a missing figure is not
  the same as a negative one.

* ``finish_reason`` — why the model stopped: ``stop`` for a natural end, or
  ``length`` when the output ceiling was hit.  A closed set, for the same
  reason the zones in ``provider_boundary`` are one: a third value is a
  provider inventing a reason the rest of the system has no vocabulary for,
  and a caller that had to special-case each provider's stop codes would not
  be reading a normalized object at all.

The object is a frozen dataclass: a completion is an answer that was given,
and an answer is not something a caller mutates.  Equality is by value, so a
suite can assert ``Completion(...) == provider.complete(request)`` rather than
reaching into fields — the same testability the tree's other records
(``snapshot``'s manifest, ``bootstrap``'s world) get from being value types.

Validating in ``__post_init__`` rather than at the call site is deliberate:
the enforcement that a completion is well-formed lives in the object, so a
completion constructed anywhere — by a provider, by a fixture, by a test —
carries its own guard, and :func:`providers.require_completion` only has to
check "is this a Completion at all", not re-verify each field.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Completion", "FinishReason", "Usage"]

#: The reasons a completion may have ended.  A closed set: a model that stops
#: for some third reason is normalized onto one of these by the provider that
#: serves it, so a downstream caller never meets a stop code it does not know.
#: ``stop`` is a natural end; ``length`` is the output ceiling having been hit.
FinishReason = str

_STOP = "stop"
_LENGTH = "length"
_FINISH_REASONS: frozenset[str] = frozenset({_STOP, _LENGTH})


@dataclass(frozen=True)
class Usage:
    """The token accounting a completion carries.

    The three figures the deployment's cost and fill accounting read, and no
    more.  ``input_tokens`` and ``output_tokens`` are the billed quantities;
    ``cache_read_tokens`` is what a provider reports when a prompt hit its
    cached-context prefix, and defaults to zero because a provider that does
    not report it has not earned the caller a negative number — the absence
    of a figure is not a figure.  All three are non-negative: a token count
    below zero is a malformed provider, and the object refuses it at
    construction rather than letting the lie travel into a cost total.
    """

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
            ("cache_read_tokens", self.cache_read_tokens),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(
                    f"Usage.{name} must be a non-negative int, got {value!r}"
                )

    @property
    def total_tokens(self) -> int:
        """The billed token total for this completion — input plus output.

        Cache-read tokens are not billed on top of the input they are a part
        of, so they are not added here: the total is what a cost model charges
        for, not a naive sum of every counter the provider happened to report.
        """
        return self.input_tokens + self.output_tokens


def _require_finish_reason(reason: object) -> str:
    """Return ``reason`` as one of :data:`_FINISH_REASONS`, refusing anything else.

    The membership test is guarded rather than written bare, because a reason
    that is not a string is refused for a different reason than one that is
    merely unknown, and only one of them is about the contract.  A ``str``
    that is not a finish reason is a provider inventing a stop code the rest
    of the system has no vocabulary for; a non-string is a wrong type.  Both
    must leave as :class:`~providers.CompletionMalformedError`, so the caller
    that catches a malformed completion gets the same answer whichever it met
    — the seam's error vocabulary is this interface's, never the standard
    library's.
    """
    if not isinstance(reason, str):
        from ._errors import CompletionMalformedError

        raise CompletionMalformedError(
            f"a completion's finish_reason must be a string, got {reason!r} "
            f"({type(reason).__name__}). A completion says why the model "
            f"stopped, and the reasons are a closed set "
            f"({_STOP!r}, {_LENGTH!r}) — a non-string stop code is not a "
            f"reason the rest of the system can read."
        )
    if reason not in _FINISH_REASONS:
        from ._errors import CompletionMalformedError

        raise CompletionMalformedError(
            f"a completion's finish_reason must be one of "
            f"({_STOP!r}, {_LENGTH!r}), got {reason!r}. A model that stops "
            f"for some other reason is normalized onto one of these by the "
            f"provider that served it; a third stop code is a provider "
            f"inventing a reason the rest of the system has no vocabulary for."
        )
    return reason


@dataclass(frozen=True)
class Completion:
    """The one object every model call returns.

    The normalized answer of a model, whatever provider served it.  A caller
    reads these four fields and nothing provider-specific: ``content`` (the
    answer text), ``model`` (the model that produced it — the serving model,
    which a tiering layer may have changed from what was asked), ``usage``
    (the token accounting), and ``finish_reason`` (why the model stopped).

    Frozen by construction: a completion is an answer that was given, and a
    caller that needed to change it builds a new one.  The finish_reason and
    usage are validated on entry, so a completion that exists is a valid one
    — the guard lives in the object, not in every reader of it.
    """

    content: str
    model: str
    usage: Usage
    finish_reason: str = _STOP

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            from ._errors import CompletionMalformedError

            raise CompletionMalformedError(
                f"a completion's content must be a string, got {self.content!r} "
                f"({type(self.content).__name__}). A completion is the model's "
                f"answer as text; an answer that is not text is not the "
                f"normalized object feature 192 promises every caller."
            )
        if not isinstance(self.model, str) or not self.model:
            from ._errors import CompletionMalformedError

            raise CompletionMalformedError(
                f"a completion's model must be a non-empty string, got "
                f"{self.model!r}. A completion names the model that served it, "
                f"so a blank or non-string model is a completion that cannot "
                f"be accounted for downstream."
            )
        if not isinstance(self.usage, Usage):
            from ._errors import CompletionMalformedError

            raise CompletionMalformedError(
                f"a completion's usage must be a Usage record, got "
                f"{self.usage!r} ({type(self.usage).__name__}). A completion "
                f"carries its token accounting as a normalized record so cost "
                f"and fill accounting downstream never have to re-parse a "
                f"provider payload; anything else is not that record."
            )
        # finish_reason is validated last so a completion fails on the field a
        # reader is most likely to touch — content — first, then the shape
        # around it.  Assigning the validated value back keeps the stored
        # reason canonical (the closed-set member, not whatever alias a
        # provider passed).
        object.__setattr__(
            self, "finish_reason", _require_finish_reason(self.finish_reason)
        )
