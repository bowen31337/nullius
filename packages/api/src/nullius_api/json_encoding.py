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
* **The answer a dataclass spells carries its *derived reads* beside
  its fields.**  The members state a response's derived figures as
  ``@property`` reads over the fields — ``FdrDeployResponse.fdr_deploy``/
  ``campaign_id``/``computed_at``, ``RegimeCoverageResponse.counts``,
  ``KEffectiveResponse.total`` — precisely so a derived read cannot
  drift from the fields it is drawn from.  A body carrying the fields
  alone would drop the very reads the member's own docstring promises a
  caller (the argument
  :class:`~ledger.keffective_route.KEffectiveResponse` gives for its
  ``total``), so the reads are spelled after the fields, in definition
  order, under their own names.  This applies to the one value the
  server was *handed* — the endpoint's answer, or the transport's own
  envelope — and not to the member values nested inside it, which keep
  exactly the shape their members define (the same "the existing keys
  stay" law the route's own callers rely on; ``KEffectiveResponse.view``
  is why the distinction is load-bearing: a member's own ``by_epoch`` is
  keyed by the un-named epoch, a ``None`` no JSON object can hold).
  A read that shadows a field name never occurs and is refused by the
  field winning, and **a read the vocabulary below cannot spell is left
  out rather than allowed to cost the body**: the fields are the
  member's stated answer and the derived reads are additions to it, so
  an addition must never turn a working answer into an internal error.
  Nothing is coerced to rescue one (see the refusal rules below), so an
  omission here is a *narrower* answer, never a wrong one.
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
* **A mapping key is text, or one of the scalars that spell themselves
  as text.**  A JSON object's keys are strings, so the members' key
  vocabulary has to reach the wire as text: the ones that already name
  a canonical spelling do so through the rule above and nothing new —
  §7.2's target series is keyed by ``{rebalance date: {symbol: return}}``,
  and a calendar date spells itself exactly as an ISO date *value* does,
  because it is the same date under the same rule.  Anything else (an
  ``int`` key, a tuple, ``None``) is refused by name rather than
  coerced, and two keys that would spell one text are refused rather
  than silently collapsed — the same "one bar, one answer" rule
  :func:`nulloracle.target.TargetResponse` states over the same series.

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
    of each route.  The value handed in is the *answer* the server is
    about to write — an endpoint's response dataclass, the error
    envelope, or a plain collection one of those reads produced — so it
    is the one position in which a dataclass's derived reads
    (:func:`_derived_reads`) are spelled beside its fields.

    Raises :class:`JsonEncodingError` for a value the vocabulary above
    does not spell; the caller that cannot answer a refusal body answers
    the internal-error envelope instead.
    """
    return json.dumps(_encode(value, response=True), allow_nan=False)


def _encode_key(key: Any) -> str:
    """Spell one mapping key as the text a JSON object key must be.

    A ``str`` is already the answer.  The scalars the value vocabulary
    spells through their own text form (:data:`_TEXT_SCALARS` — a
    ``date``, a ``datetime``, ``time``, ``UUID`` or ``Decimal``) spell
    their *keys* the same way they spell their values, because a JSON
    object's keys are strings and the alternative would be a second
    spelling of one date: ``{date(2026, 1, 5): …}`` must reach the wire
    as ``{"2026-01-05": …}``, which is exactly what that date answers as
    a value and exactly what
    :func:`nulloracle.target.TargetRequest` accepts back.

    Everything else is refused by name.  ``str()`` of an ``int``, a
    tuple, ``None`` or an arbitrary object is a re-spelling nobody chose
    — and for a path or an object it is the repr leak this module exists
    to close, one mapping key away from a body.
    """
    if isinstance(key, str):
        return key
    if isinstance(key, _TEXT_SCALARS):
        return key.isoformat() if isinstance(key, dt.date) else str(key)
    raise JsonEncodingError(
        f"a JSON object key must be text (or a value that spells one "
        f"canonically — a date, datetime, time, UUID or Decimal); got a "
        f"key of type {type(key).__name__}. The members key their mappings "
        "by campaign id, stratum name and §7.2's rebalance dates, so a key "
        "outside that vocabulary is refused rather than re-spelled"
    )


def _derived_reads(cls: type) -> list[str]:
    """The ``@property`` reads a value class exposes, in definition order.

    The members state a *response*'s derived figures as properties over
    its fields precisely so a derived read cannot drift from what it is
    drawn from (:class:`~ops.fdr_route.FdrDeployResponse`'s
    ``fdr_deploy``, :class:`~ops.regime_coverage.RegimeCoverageResponse`'s
    ``counts``), and those reads are the member's own stated answer to a
    caller — the same standing the field names have, which is why the
    response's reads are spelled and a nested member *value* keeps its
    fields alone (``KEffectiveResponse.view`` is the member's own
    ``KEffective``, whose ``by_epoch`` is keyed by the un-named epoch —
    a ``None`` no JSON object can hold).

    Walked over the MRO so a subclass's own reads are found beside an
    inherited one, derived class first, and deduplicated by name: one
    read spells one key, the first definition winning.
    """
    names: dict[str, None] = {}
    for klass in getattr(cls, "__mro__", (cls,)):
        for name, member in vars(klass).items():
            if isinstance(member, property):
                names.setdefault(name, None)
    return list(names)


def _encode(value: Any, *, response: bool = False) -> Any:
    """Reduce ``value`` to JSON-native structures, or refuse by name.

    ``response`` marks the one value the transport was *handed*: an
    endpoint's answer.  That value carries its derived reads
    (:func:`_derived_reads`) beside its fields; everything nested inside
    it spells its fields alone, so a member's own value keeps the shape
    its members define.
    """
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
        encoded: dict[str, Any] = {
            field.name: _encode(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
        # The answer's derived reads beside its fields — and only the
        # answer's.  A response states its derived figures as properties
        # over the fields so they cannot drift from what they are drawn
        # from, and those reads are part of what the member's own
        # docstring promises a caller: a body carrying the fields alone
        # answers the trend but drops the top-line figure the trend exists
        # to explain (feature 341's ``fdr_deploy``, feature 343's
        # ``counts``, feature 94's ``total``).  The values *nested* inside
        # it are the members' own value classes, and they keep the shape
        # their members define — the law the constraint that the existing
        # keys stay states.
        for name in _derived_reads(type(value)) if response else ():
            if name in encoded:
                # A property cannot shadow a dataclass field the value
                # actually holds: the field is the member's own declaration
                # and wins, so the body never carries two entries for one
                # name (JSON's last-key-wins would silently pick one).
                continue
            try:
                derived = _encode(getattr(value, name))
            except Exception:  # noqa: BLE001, S112 - a failing read is left out
                # The fields are the member's stated answer; the derived
                # reads are additions to it.  An addition the vocabulary
                # cannot spell (a ``Path`` read off a dataclass, say) is
                # *left out* rather than allowed to turn a working answer
                # into the internal error — the same "the existing keys
                # stay" law the route's own callers depend on.  Nothing is
                # coerced to rescue it, so the omission is a narrower body,
                # never a wrong one.
                #
                # The catch is deliberately every exception rather than
                # :class:`JsonEncodingError` alone, because a property is
                # arbitrary code: ``PreRegistrationResponse.open`` forwards
                # to a record's own read, and a record that does not carry
                # one raises ``AttributeError`` from *inside* the read the
                # codec never wrote.  Reading a field cannot do this — the
                # field names come from the class — so letting a derived
                # read's failure escape would turn an answer the member
                # stated in full into a 500, which is precisely the
                # "existing keys stay" promise this loop exists to hold.
                continue
            encoded[name] = derived
        return encoded

    if isinstance(value, _TEXT_SCALARS):
        # isoformat() for dates and datetimes, str() for UUID (the
        # canonical hyphenated form) and Decimal (the exact text — see
        # the module docstring for why never float).
        return value.isoformat() if isinstance(value, (dt.date,)) else str(value)

    if isinstance(value, Mapping):
        # Keys are spelled by the same rules the values are, so the
        # members' key vocabulary reaches the wire unchanged: text stays
        # itself, and a scalar that already names a canonical text form
        # (§7.2's target series is keyed by calendar date) is spelled
        # exactly as that same date is spelled as a value.  Coercing
        # anything else — ``str(1)``, ``str(("a", "b"))``, ``str(None)``
        # — would be a second spelling of a key the member chose, and
        # ``str()`` of a path or an object is precisely how a repr nobody
        # chose would reach a body.
        encoded: dict[str, Any] = {}
        for key, item in value.items():
            text = _encode_key(key)
            if text in encoded:
                # Two keys spelling one text would silently collapse into
                # one entry — the last writer winning a bar that the
                # member stated twice.  Refused, for the same reason
                # :class:`nulloracle.target.TargetResponse` refuses a
                # series carrying one day under two spellings: one bar,
                # one answer.
                raise JsonEncodingError(
                    f"a mapping carries two keys that spell the same JSON "
                    f"object key {text!r}; one entry would silently shadow "
                    "the other and the reader would see one where the "
                    "member stated two"
                )
            encoded[text] = _encode(item)
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
