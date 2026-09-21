"""The request a caller makes through the provider interface.

Feature 192 normalizes both directions of the seam: the answer is always a
:class:`providers.Completion`, and the ask is always a :class:`Request`.  A
provider therefore sees one shape of request whatever caller sent it, and a
caller sends one shape of request whatever provider serves it — the interface
is the single translation point, so neither side has to know about the other.

The request carries only what the interface needs to make and account for a
call, and nothing provider-specific:

* ``messages`` — the conversation: the ordered turn list the model completes.
  Each turn is a :class:`Message` with a ``role`` from a closed set and a
  ``content`` string.  A closed role set for the same reason the finish
  reasons and the boundary zones are closed: a caller that had to reconcile
  each provider's own role vocabulary ("assistant" vs "model", "system" vs
  "developer") would not be reading a normalized object.  The roles are the
  three the deployment's prompts use — ``system`` (the standing instructions),
  ``user`` (what is being asked), ``assistant`` (a prior model turn in a
  multi-turn exchange).

* ``model`` — the model the caller wants.  Distinct from the model a
  completion reports: a tiering or rotation layer may serve a different one,
  and the completion names the server while the request names the ask.

* ``temperature`` and ``max_tokens`` — the two knobs the deployment's prompts
  actually turn.  ``temperature`` is clamped to ``[0, 2]`` and ``max_tokens``
  to a positive int, so a caller cannot ask for a sampling setting the model
  cannot honour and have the lie reach it; the request refuses the setting at
  construction, where the caller can fix it.

The request is a frozen dataclass for the same reason the completion is: it
is the ask that was made, and an ask is not mutated in flight.  Equality is by
value, so a suite can assert ``Request(...) == recorded.request`` — which is
how the recording layer (feature 194) keys a fixture by "the prompt that was
asked": two requests that compare equal are the same prompt, whatever object
happened to carry it.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Message", "Request", "Role"]

#: The role of one turn in a conversation.  A closed set: the three the
#: deployment's prompts use.  ``system`` carries the standing instructions,
#: ``user`` what is being asked, and ``assistant`` a prior model turn in a
#: multi-turn exchange.  A provider that met a fourth role would be inventing
#: a turn type the rest of the system has no reader for.
Role = str

_SYSTEM = "system"
_USER = "user"
_ASSISTANT = "assistant"
_ROLES: frozenset[str] = frozenset({_SYSTEM, _USER, _ASSISTANT})

#: The sampling-temperature ceiling.  Above this a request is asking for a
#: sampling regime the models the deployment pins do not expose and a caller
#: would be tuning a knob that does nothing — refused at construction instead.
_MAX_TEMPERATURE = 2.0


def _require_role(role: object) -> str:
    """Return ``role`` as one of :data:`_ROLES`, refusing anything else.

    Guarded rather than written bare, so a non-string role is refused for the
    right reason (wrong type) and a string that is not a role for its own
    (a turn type the system has no reader for), and both leave as
    :class:`~providers.CompletionMalformedError` — the seam's error vocabulary
    is this interface's, never the standard library's ``TypeError`` or
    ``ValueError``.
    """
    if not isinstance(role, str):
        from ._errors import CompletionMalformedError

        raise CompletionMalformedError(
            f"a message's role must be a string, got {role!r} "
            f"({type(role).__name__}). A conversation turn has a role, and the "
            f"roles are a closed set ({_SYSTEM!r}, {_USER!r}, {_ASSISTANT!r}) "
            f"— a non-string role is not a turn the rest of the system can read."
        )
    if role not in _ROLES:
        from ._errors import CompletionMalformedError

        raise CompletionMalformedError(
            f"a message's role must be one of ({_SYSTEM!r}, {_USER!r}, "
            f"{_ASSISTANT!r}), got {role!r}. A conversation turn uses one of "
            f"the roles the deployment's prompts send; a fourth role is a turn "
            f"type the rest of the system has no reader for and is refused "
            f"here rather than forwarded to a provider that would invent one."
        )
    return role


@dataclass(frozen=True)
class Message:
    """One turn in a conversation: a role and what it said.

    The unit a :class:`Request` is built from.  ``role`` is one of the closed
    set of roles, validated on construction so a message that exists carries a
    turn the system can read; ``content`` is the text of the turn.  Frozen and
    value-equal, so messages compare by what they say rather than by identity
    — two equal messages are the same turn, which is what lets a request
    compare equal to a recorded one.
    """

    role: str
    content: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _require_role(self.role))
        if not isinstance(self.content, str):
            from ._errors import CompletionMalformedError

            raise CompletionMalformedError(
                f"a message's content must be a string, got {self.content!r} "
                f"({type(self.content).__name__}). A conversation turn says "
                f"something as text; a turn whose content is not text is not "
                f"the normalized object the interface carries."
            )


@dataclass(frozen=True)
class Request:
    """The one object every model call sends.

    The normalized ask of a caller: an ordered ``messages`` conversation, the
    ``model`` the caller wants, and the two sampling knobs the deployment's
    prompts turn (``temperature``, ``max_tokens``).  A provider receives this
    and nothing caller-specific; a caller sends this and nothing
    provider-specific.  The temperature and max_tokens are validated on entry,
    so a request that exists asks for a setting a pinned model can honour.

    Frozen by construction: it is the ask that was made, and a caller that
    needed to change it builds a new one.  Equality is by value, which is how
    the recording layer keys a fixture by the prompt that was asked — two
    requests that compare equal are the same prompt.
    """

    messages: tuple[Message, ...]
    model: str
    temperature: float = 0.0
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        if not isinstance(self.model, str) or not self.model:
            from ._errors import CompletionMalformedError

            raise CompletionMalformedError(
                f"a request's model must be a non-empty string, got "
                f"{self.model!r}. A request names the model to complete it, so "
                f"a blank or non-string model is a call that cannot be routed."
            )
        if not isinstance(self.temperature, (int, float)) or isinstance(
            self.temperature, bool
        ):
            from ._errors import CompletionMalformedError

            raise CompletionMalformedError(
                f"a request's temperature must be a number, got "
                f"{self.temperature!r} ({type(self.temperature).__name__}). "
                f"Temperature is a sampling knob a pinned model reads; a "
                f"non-number is not a setting it can honour."
            )
        if not (0 <= self.temperature <= _MAX_TEMPERATURE):
            from ._errors import CompletionMalformedError

            raise CompletionMalformedError(
                f"a request's temperature must be in [0, {_MAX_TEMPERATURE}], "
                f"got {self.temperature}. A temperature outside this range is "
                f"a sampling regime the models the deployment pins do not "
                f"expose, so it is refused at construction, where the caller "
                f"can fix it, rather than forwarded to a model that would "
                f"silently ignore it."
            )
        if not isinstance(self.max_tokens, int) or isinstance(self.max_tokens, bool):
            from ._errors import CompletionMalformedError

            raise CompletionMalformedError(
                f"a request's max_tokens must be an int, got {self.max_tokens!r} "
                f"({type(self.max_tokens).__name__}). The output ceiling is a "
                f"count a pinned model reads; a non-int is not one."
            )
        if self.max_tokens <= 0:
            from ._errors import CompletionMalformedError

            raise CompletionMalformedError(
                f"a request's max_tokens must be positive, got {self.max_tokens}. "
                f"A non-positive output ceiling is a call that cannot produce "
                f"an answer, so it is refused at construction rather than sent "
                f"to a model that would return nothing."
            )
