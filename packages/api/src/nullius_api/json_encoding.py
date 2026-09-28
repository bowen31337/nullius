"""The one JSON spelling every response body passes through.

The transport's own law — additions_spec_journeys.xml feature 4, *"returns
a JSON body for every response"* — needs a codec before it needs a route:
the endpoints this member serves answer in the members' value vocabulary
(frozen dataclasses, ``datetime`` stamps, ``UUID`` identities,
``Decimal`` figures, tuples), and none of that is JSON until something
spells it.  This module is that something, and it is the only such
something in the member: the handler writes every body — successes and
refusals alike — through :func:`dumps`, so a figure, a stamp or an
identity can never reach the wire in two spellings that could disagree.

The rules are the workspace's own, restated as encodings:

* **A dataclass answers as an object keyed by its field names** — the
  spelling the members already give their values in docstrings and
  ``__init__`` signatures (``FdrDeployResponse.history``,
  ``InstrumentStatusResponse.canary``), so a body a caller parses says
  what the member's own documentation says.  Nested values encode
  recursively; a frozen dataclass and a plain one spell identically,
  because the scan's synthetic module copies must encode exactly as the
  directly-imported classes do.
* **Dates and datetimes answer as ISO 8601** (``datetime.isoformat``),
  the one textual instant spelling the workspace already carries on its
  records.
* **A ``UUID`` answers as its canonical hyphenated text** — the identity
  spelling every member's rows hold.
* **A ``Decimal`` answers as its exact text, never a float.**  ``float``
  of ``Decimal("0.1")`` is a different number than ``0.1``; a figure
  that crossed that bridge would be a number nobody measured, which is
  the one direction the whole spec refuses (the same reasoning
  :class:`~ops.fdr_route.FdrDeployResponse` gives for answering ``None``
  rather than ``0.0`` over an empty trend).
* **``None`` answers ``null``, tuples answer arrays**, mappings answer
  objects.  An empty store therefore answers ``null`` fields and empty
  collections straight through — the honest-absence law, at the codec.

And the refusals are as deliberate as the encodings.  A value the codec
cannot spell — a ``set`` (no order to promise), ``bytes`` (no honest
JSON text), a filesystem path, an arbitrary object — is refused by name
(:class:`JsonEncodingError` naming the type) rather than stringified,
because ``str()`` of the wrong thing is exactly how a filesystem path or
a memory repr would reach a body the spec promises carries neither.  A
non-finite float is refused for the same reason ``NaN`` is not JSON: it
is not a figure anyone measured.  Nothing here silently coerces.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

__all__ = ["JsonEncodingError", "dumps"]


class JsonEncodingError(TypeError):
    """A value the transport cannot spell as JSON, refused by name.

    Raised by :func:`dumps` for a value outside the supported vocabulary
    — an arbitrary object, a ``set``, ``bytes``, a filesystem path, a
    non-finite float, a non-text mapping key.  Subclasses
    :class:`TypeError` so an ordinary ``except TypeError`` at a call
    site keeps catching it, the same subclassing law the spec's refusal
    features state for the members' own error classes.

    The server answers this as a refusal about *itself* (an internal
    error, no detail on the wire), never as a body: the message is for
    the operator's log, and it names the offending type so the repair —
    encode a value the vocabulary spells — is one glance away.
    """


#: The scalar types that spell themselves through their own text form.
#: Kept as a tuple for ``isinstance``; membership order irrelevant.
_TEXT_SCALARS = (dt.datetime, dt.date, dt.time, uuid.UUID, Decimal)


def dumps(value: Any) -> str:
    """Spell ``value`` as one JSON text — the member's only body encoder.

    Every response body the server writes passes through here
    (successes and refusals alike), which is what makes *"a JSON body
    for every response"* a fact about the transport rather than a habit
    of each route.  Raises :class:`JsonEncodingError` for a value the
    vocabulary above does not spell; the caller that cannot answer a
    refusal body answers the internal-error envelope instead.
    """
    return json.dumps(_encode(value), allow_nan=False)


def _encode(value: Any) -> Any:
    """Reduce ``value`` to JSON-native structures, or refuse by name."""
    # The natives pass straight through.  bool is checked before int is
    # ever consulted (bool is an int subclass; JSON spells them
    # differently), and floats are refused when non-finite rather than
    # emitted as NaN/Infinity — tokens Python's json accepts and no JSON
    # parser on the other end of the wire is promised to.
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise JsonEncodingError(
                f"a float must be finite to be spelled as JSON; got "
                f"{value!r}. NaN and the infinities are not figures "
                "anyone measured, and a body carrying them would be "
                "answering a number no store stated"
            )
        return value

    # Dataclasses — duck-checked on ``__dataclass_fields__`` rather than
    # isinstance-guarded, for the reason every member seam gives: the
    # factory's scan imports members under synthetic module names, so a
    # *composed* endpoint's response is structurally a dataclass but
    # never an instance of any class this module could name.  The
    # contract is the fields, and the fields are what is read.
    fields = getattr(value, "__dataclass_fields__", None)
    if fields is not None:
        return {
            field.name: _encode(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }

    if isinstance(value, _TEXT_SCALARS):
        # isoformat() for dates and datetimes, str() for UUID (the
        # canonical hyphenated form) and Decimal (the exact text — see
        # the module docstring for why never float).
        return value.isoformat() if isinstance(value, (dt.date,)) else str(value)

    if isinstance(value, Mapping):
        # Keys must already be text.  Coercing a non-text key would be a
        # second spelling of the key the member chose; the responses
        # this member serves key by campaign id and stratum name, and a
        # key that is not text is refused rather than re-spelled.
        encoded: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise JsonEncodingError(
                    f"a JSON object key must be text; got a key of type "
                    f"{type(key).__name__} ({key!r}). The members key "
                    "their mappings by campaign id and stratum name, so a "
                    "non-text key is a value the transport refuses to "
                    "re-spell rather than silently coercing"
                )
            encoded[key] = _encode(item)
        return encoded

    if isinstance(value, (list, tuple)):
        # Tuples answer arrays — the members' history rows and count
        # pairs are tuples, and an array is the JSON spelling of an
        # ordered sequence.
        return [_encode(item) for item in value]

    # Everything else is refused by name.  This is the load-bearing
    # refusal: bytes, sets (no order to promise), filesystem paths,
    # callables and arbitrary objects all land here, and the message
    # names the type so an operator reading the log sees the one repair
    # (spell the value in the vocabulary above) rather than a repr that
    # might itself carry a path.
    raise JsonEncodingError(
        f"cannot spell values of type {type(value).__name__} as JSON. "
        "The transport spells dataclasses (as objects keyed by field "
        "name), dates and datetimes (ISO 8601), UUIDs and Decimals "
        "(their exact text), mappings with text keys, tuples and lists "
        "(as arrays), and the JSON natives; anything else — a set, "
        "bytes, a filesystem path, an arbitrary object — is refused "
        "rather than stringified, so no body ever carries a repr "
        "nobody chose to answer with"
    )
