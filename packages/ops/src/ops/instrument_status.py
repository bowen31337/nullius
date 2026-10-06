"""Feature 342's endpoint: GET /metrics/instrument-status, the three
binary lamps.

app_spec.xml, "Observability & Dashboards", feature 342: *System exposes
GET /metrics/instrument-status which returns canary, KS guard and ingest
lag as three binary lamps.*  The spec's API summary spells the route's one
line under the Observability domain — ``GET /metrics/instrument-status —
Return canary, KS guard and ingest lag status`` — directly beneath feature
341's top-line figure; the category's foundation is 341 (*"every later
feature in the category declares ``depends_on="341"``"*), and this is the
first surface to hang from the route 341 established.

**The route exists because the rail above the figure is what makes the
figure readable at all.**  docs/design.md §5.4 draws this surface before
any numeral in the system is drawn::

    canary     ok        replay is deterministic
    ks guard   ok        nulls indistinguishable
    ingest     1.2s      feed lag

and states the reason in one line — *"Three binary lamps at the top of the
left rail, because everything below them is worthless if any is out."*  The
consequence follows immediately: *"Any failure turns the rail ``--void`` and
stamps every numeral rendered during the affected window with the void
treatment, retroactively.  Bad data does not quietly age into good data."*
So this route is not a convenience panel: it is the seam that decides
whether the figures beside it may be believed, and the answer it gives is
**three bits** — canary, KS guard, ingest — each *binary* by the sentence's
own word, never a graded score, never a colour, never a count of anomalies.
The spec's own success criterion reads it back the same way: *"The operator
… sees instrument status as three binary lamps."*

**Each lamp is the owning member's own verdict, delegated — never
re-derived here.**  The member's law is that the observability member owns
no figure: it reads each through the member that holds it (feature 341's
route established the door, feature 343's the second).  This route holds
that law three times over, and the three cases are genuinely different
shapes:

* **canary** — §12's determinism halt, *and* feature 1's own run history,
  read together.  A halt is feature 143's monotone break
  (:class:`~canary.CanaryHaltStore`, :meth:`~canary.CanaryHaltStore.halted`)
  and wins over everything: halted is ``False``, full stop, no campaign, no
  number, no threshold, the deployment's own fact.  Short of a halt, the
  lamp is not a standing *"replay is deterministic"* bit — it is a claim
  about a **specific, recent** replay, so it answers ``True`` only when
  feature 1's own history (:meth:`~canary.CanaryRunStore.newest`) names a
  run that both passed (``within_tolerance``) and is still recent
  (:data:`CANARY_MAX_AGE_HOURS`).  Anything else — no run ever recorded, or
  the newest one older than that window — is *no reading*, ``None``: a
  canary that has not run tonight has not told anyone replay is
  deterministic tonight, and a lamp that read that silence as green would
  be exactly the *"bad data quietly aging into good data"* §5.4 draws this
  surface to prevent.
* **ks guard** — §7.4's detectability reading.  Feature 123's
  :class:`~nulloracle.KsGuard` persists the two-sample p-value against its
  campaign and reads it back through :meth:`~nulloracle.KsGuard.load`,
  refusing a half (the campaign column and the provenance row are one
  reading's content).  The comparison that turns that number into a
  *verdict* is spelled once in the workspace, as
  :data:`nulloracle.VOID_THRESHOLD`, and this route compares against **that
  constant**, read through the nulloracle member — the level is not
  restated here, and no second spelling of ``0.05`` exists in this module.
  The boundary is §7.4's own strict ``<``: a p-value exactly at the
  threshold is *not* below it, so it is not detectable, the nulls are still
  indistinguishable, and the lamp stays lit.
* **ingest lag** — §16's WS staleness, docs §5.4's *"feed lag"*.  This is
  the one lamp whose figure is a *reading* rather than a *state*, and the
  one read from this member's own storage rather than a sibling's: feature
  350's ``ops_live_metrics`` row ``feed_staleness_s`` is the durable record
  of a silence some process measured — the risk member's own quantity
  (feature 328's *"Data feed staleness > threshold"* row) handed over
  already measured, which is precisely the barrier feature 350's spec
  states and the reason it reserved this route as the reader: *"a
  subsequent expose/render feature can read the current value."*  The
  ingest member's own durable state is a **sequence watermark** (feature
  29's :meth:`~nullius_ingest.SequenceStore.current`), a count of messages
  rather than an instant, so it cannot answer *how long has the socket been
  quiet*; and nothing in this workspace persists a ``last_message_at``, so
  a route that tried to measure the silence itself would be inventing the
  half of the watchdog feature 328 refuses to guess at.  So this route asks
  the recorded reading, and carries it with the instant it was labelled
  with.

**The KS lamp reports on the campaign the top-line figure is attributed
to, and it says which.**  A guard reading is a fact *about a campaign*
(feature 123 keys its journal by ``campaign_id``, and its own read takes
the id), while this route takes no arguments — a GET over the deployment's
instruments has no body and no campaign to state.  So the campaign is
resolved the way this member's neighbouring route already resolves it: the
**newest row of the scoring member's own trend read**
(:meth:`~scoring.FdrDeployStore.history`, ordered ``computed_at`` then
``campaign_id``), the same last row feature 341 top-lines and the same
attribution docs' hero plate renders (*"campaign 24"* beside the figure).
The lamp therefore reports the guard finding for the campaign the numeral
beside it belongs to — and, because a top-line figure an operator cannot
attribute is a figure nobody can audit, the answer carries the campaign id
and the p-value it judged, so the lamp's bit is always reconstructible from
the answer.

**Three absences, held apart from one another and from a broken read.**
The family's stance (feature 267's discoverable state, restated at 341's
and 343's routes) is that an absent figure is *answered as an absence*
while a broken one is *refused*.  Each lamp has its own honest absence, and
none of them is ever answered with a lit lamp:

* **the canary lamp is absent for "no reading"** — either the canary has
  never run (:meth:`~canary.CanaryRunStore.newest` answers ``None``) or the
  newest run is older than :data:`CANARY_MAX_AGE_HOURS`.  Both are the same
  honest silence: nobody can say tonight's replay is deterministic when
  nobody replayed it tonight.  This is **not** the halt store's own
  absence — a halt table with no rows *is* "not halted" (a real
  measurement of that table's content), and the two reads are combined
  rather than conflated: a halt (however stale the run history) still
  answers ``False``, because a halt wins over everything, as it does today;
  the "no reading" state is reached only when there is *no halt* and the
  run history has nothing recent enough to stand behind a lit lamp either.
  A store that cannot be opened or read — the halt store or the run store —
  is refused (translated, below), never answered green and never answered
  with the absence.
* **the KS lamp is absent when there is no finding to report** — either the
  trend names no campaign (no campaign has been closed out, so there is no
  guard reading to judge) or the guard has not run for the campaign the
  trend names (:meth:`~nulloracle.KsGuard.load` answers ``None``, feature
  123's own honest answer for *"a campaign the orchestrator has created and
  no job has read yet"*).  An unguarded campaign is **not** a passing one:
  ``ks_pvalue`` is ``NULL`` until the guard fills it, and a lamp that read
  green off a NULL would be certifying the one state §7.4 exists to catch.
* **the ingest lamp is absent for either half of the watchdog** — no
  recorded ``feed_staleness_s`` row (nothing has measured the feed, so
  there is no silence to judge) or no configured band (**§13.3 says
  "threshold" and names no number**, so the band is configuration a
  deployment supplies; a reading with no band is *half a watchdog* and this
  route answers it as an absence rather than judging against nothing).  The
  two halves stay distinguishable on the answer — a reading with no band
  still carries ``ingest_lag_seconds`` and ``ingest_read_at``, and a band
  with no reading still carries ``threshold_seconds`` — because an operator
  whose watchdog is half-wired needs to see which half is missing.  And the
  no-band half is *named*: a recorded silence with no band carries
  :attr:`ingest_threshold_env`, the environment variable the deployment
  would set (:data:`FEED_STALENESS_THRESHOLD_ENV`'s own spelling, read off
  the module's one constant — never restated), so a render never has to
  re-derive which knob is missing from the fields beside the lamp.  A
  reading with no band is *unconfigured*; no reading at all is *no
  reading* — the two states the J04 journey step 3 holds apart, answered
  apart here so no surface downstream can collapse them.

**The KS and ingest lamps read no clock; the canary lamp reads exactly
one, for "the instant of the read" the feature sentence itself names.**
The guard's persisted number and the recorded silence are readings *of a
store*, taken whole — nothing here stamps an instant of its own for either,
or compares two clocks, or re-derives a figure the risk or nulloracle
member owns; the ingest lamp's provenance is the row's own instant
(``ingest_read_at``), rendered exactly as feature 350 stored it.  The
canary lamp is different in exactly the way its own clause is different:
*"ran within CANARY_MAX_AGE_HOURS of the read"* is a comparison between
feature 1's stamped ``ran_at`` and **now**, and a route that refused to ask
the one clock that comparison needs could not answer it at all.  So
:func:`datetime.datetime.now` is called exactly once, inline at the
comparison, and nothing else — the result is never stored on the response
(the figure the response carries is the run's own ``ran_at``, not the
instant it was judged against, the same "carry the provenance, not the
verdict's scratch work" discipline the KS lamp's stored p-value already
keeps), so two calls to :meth:`~InstrumentStatusEndpoint.get` a second
apart may answer differently for the same stored run — which is the
feature's own point: the lamp is a claim about *freshness*, and a stale
claim must eventually go dark on its own, without a fresh write from
anyone.

**A read that fails is refused, translated, and never answered around.**
Each lamp's sibling failure is translated into this member's vocabulary
(:class:`~ops.errors.InstrumentStatusError`, the original chained): a
caller that wrote ``except InstrumentStatusError`` must not be taken down
by :class:`~canary.CanaryError`, by :class:`~nulloracle.KsGuardError` or by
:class:`~scoring.FdrDeployError` — errors from modules this route's caller
never imported — the member-seam law features 341 and 343 state for their
own single sibling, applied once per lamp.  And nothing is ever caught
*into* a lamp: every fallback this route could add is a lamp state nobody
read — a green canary for a database that would not open, a lit KS lamp for
a campaign whose guard row is half-written — which is exactly the *"bad data
quietly aging into good data"* §5.4 draws this surface to prevent.

**The response validates what it holds, and re-derives its own bits.**  The
readings arrive from stores that validated them, but the response is
constructible by hand (tests, a later adapter over a recorded rail), and a
frozen value that validated nothing would lend this route's guarantees to a
rail nobody stood behind.  So construction narrows every field — genuine
bools with ``int`` look-alikes refused (``True`` is ``1`` in Python, and a
truthy look-alike where a lamp belongs is the one substitution that turns a
dark rail green), a p-value a probability in ``[0, 1]``, a lag a finite
non-negative real, a band a strictly positive finite real, a campaign a
non-empty name — **and then checks each carried bit against its own
numbers**: the KS lamp must equal ``ks_pvalue >= VOID_THRESHOLD`` and the
ingest lamp must equal ``lag <= threshold``.  The canary lamp carries no
number the freshness verdict could be re-derived from at construction time
(the verdict is a comparison against *now*, which the response never reads
— see above), so its own check is narrower and asks only what the response
*can* answer without a clock: a lit canary lamp must carry the run instant
it is a verdict on (:attr:`~InstrumentStatusResponse.canary_last_run_at`),
because a ``True`` with no run behind it is a verdict nothing stands
behind, the same standing the KS lamp's own p-value pairing holds.  A rail
whose bits disagreed with the readings beside them would report an
instrument status the operator's own numbers contradict, and §5.4's whole
purpose is that the rail can be trusted *instead of* the numbers.

Stdlib-only, like the rest of the member: :mod:`dataclasses` for the
response, :mod:`datetime` for the canary lamp's freshness comparison,
:mod:`math` for the figures, :mod:`os` for the environment,
:mod:`collections.abc` for the mapping check, :mod:`typing` for
``Optional`` — and the cross-member imports (:mod:`canary`, :mod:`nulloracle`
and, through :func:`~ops.fdr_route.require_scoring`, the scoring member's
trend read), each declared in the member's pyproject and deferred past both
module scope *and* builder time (:class:`_DeferredInstrumentReadings`
below) so the factory's scan stays import-order-safe and composition never
depends on a sibling's presence on ``sys.path``.
"""

from __future__ import annotations

import datetime as dt
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

from .errors import InstrumentStatusError, LiveMetricError
from .fdr_route import require_scoring
from .live_metrics import DATABASE_URL_ENV, LIVE_METRICS, LiveMetricsStore

__all__ = [
    "CANARY_MAX_AGE_HOURS",
    "FEED_STALENESS_METRIC",
    "FEED_STALENESS_THRESHOLD_ENV",
    "INSTRUMENT_STATUS_ROUTE",
    "LAMP_NAMES",
    "OPS_INSTRUMENT_STATUS_COMPONENT_NAME",
    "InstrumentStatusEndpoint",
    "InstrumentStatusResponse",
    "require_canary",
    "require_nulloracle",
]

#: How recent the newest canary run must be for its *pass* to still count
#: as "replay is deterministic" right now.  The feature's own number: a
#: lamp that only ever answered the newest run's verdict, however old,
#: would eventually be reporting on a replay from weeks ago as if it were
#: tonight's — exactly the *"bad data quietly aging into good data"* §5.4
#: draws this whole surface to prevent.  Fixed here rather than read from
#: the environment, unlike :data:`FEED_STALENESS_THRESHOLD_ENV`: §13.3
#: names no ingest band because that one is a deployment's own tolerance,
#: while this window is the feature sentence's own literal (36), so a
#: second place to configure it would only be a second place it could
#: drift from the number the sentence states.
CANARY_MAX_AGE_HOURS = 36

# The store's own name, selected out of the member's published vocabulary
# rather than re-typed beside it: ``LIVE_METRICS`` is the store's contract
# (the closed set its value layer validates a name against), so taking the
# name from it means this route cannot drift to a spelling the store refuses.
FEED_STALENESS_METRIC = next(
    name for name in LIVE_METRICS if name == "feed_staleness_s"
)

#: The environment variable naming the band the ingest lamp judges its
#: recorded silence against.  §13.3 says *"threshold"* and names no number —
#: *"Data feed staleness > threshold | Halt new orders, hold positions"* — so
#: the band is configuration the deployment supplies, the same way feature
#: 328's guard takes ``threshold_seconds`` from its caller rather than
#: defaulting one.  Member-first and subject-second, the spelling every
#: configuration variable in this workspace takes (``NULLIUS_UNIVERSE_TOP_N``,
#: ``NULLIUS_LEGAL_THEMES``, ``NULLIUS_COST_MODEL_PATH``), so an operator
#: reading a deployment's environment can tell whose knob it is.
#:
#: **Deliberately without a default.**  A band this module invented would be
#: this route deciding, on the operator's behalf, how much silence is too
#: much — a number no document states and no member owns.  Unset, the ingest
#: lamp is *absent* (see the module docstring): half a watchdog is an
#: absence, never a lit lamp.
FEED_STALENESS_THRESHOLD_ENV = "NULLIUS_FEED_STALENESS_THRESHOLD_S"

#: The route this endpoint serves — app_spec.xml's API summary row for the
#: Observability domain, spelled once: ``GET /metrics/instrument-status —
#: Return canary, KS guard and ingest lag status`` (the feature sentence's
#: own words: *returns canary, KS guard and ingest lag as three binary
#: lamps*).  Carried on the class (:attr:`InstrumentStatusEndpoint.route`)
#: so a composed deployment can state its routes from the components it
#: holds rather than from a string that lives somewhere else.
INSTRUMENT_STATUS_ROUTE = "/metrics/instrument-status"

#: The component name this route registers under — member-first and
#: route-second, the spelling every route-shaped component in this workspace
#: takes (feature 341's ``ops-fdr-deploy`` and feature 343's
#: ``ops-regime-coverage`` beside it), so a composed application's ``order``
#: sorts this member's routes *beside* — never inside — another member's, and
#: this route lands as a peer of the top-line route rather than a new prefix
#: family.  The seat was reserved when feature 341 landed:
#: :data:`~ops.OPS_COMPONENT_NAME`'s own note names *"342's lamps"* among the
#: sibling routes that *"land as its peers under the same prefix"*.
#: *Defined* here, beside the module whose component it names, and imported
#: by the member's ``__init__`` where the ``@register`` lives — the placement
#: feature 343's route name already takes.  Read by name through the
#: composed application.
OPS_INSTRUMENT_STATUS_COMPONENT_NAME = "ops-instrument-status"

#: The three lamps' names, in the order docs/design.md §5.4 draws them —
#: canary, then the KS guard, then ingest.  Spelled once so the response's
#: :attr:`~InstrumentStatusResponse.lamps` mapping, the tests that pin the
#: rail's contents and any later render cannot drift apart on the label of a
#: lamp; the *attributes* on the response are these same three words, so the
#: mapping is a view of those fields rather than a second vocabulary.
LAMP_NAMES = ("canary", "ks_guard", "ingest")


def require_canary() -> Any:
    """Import and return the :mod:`canary` member, or raise loudly.

    Called from inside the endpoint's read paths — never at module scope, and
    never at builder time — for the reason
    :func:`~ops.fdr_route.require_scoring` gives for its own cross-member
    import: the factory's workspace scan imports this package to fire its
    ``@register``, and the scan puts one member's ``src/`` on ``sys.path`` at
    a time, so a module-scope ``import canary`` would make this component's
    presence in the composed application depend on scan order.  A deployment
    that genuinely needs the rail and cannot reach the canary member is told
    which wheel is missing rather than shown a bare :class:`ImportError`.

    The dependency itself is the "never grow a second reader" door feature
    341's route opened for the scoring member: §12's halt is feature 143's
    store, its monotone bit is the store's own read, and this route asks for
    the lamp through that one spelling rather than re-deriving *has a
    determinism break been recorded* from the halt table's rows.  The same
    door now also reaches feature 1's own run history
    (:class:`~canary.CanaryRunStore`), because the canary lamp needs the
    one sibling fact the halt store cannot answer — *did the canary run
    recently, and did it pass* — and that history lives in the same member.
    """
    try:
        import canary
    except ModuleNotFoundError as exc:  # pragma: no cover - declared dependency
        raise ModuleNotFoundError(
            "the ops member serves the instrument-status route by reading "
            "the canary member's own halt store (feature 143's monotone bit, "
            "the state docs §5.4 draws as its first lamp) rather than "
            "re-spelling the halt table's read, and that member is not "
            "importable in this environment; run `uv sync --all-packages` in "
            "the workspace root (or put packages/canary/src on sys.path) so "
            "the lamp this route reports can be reached"
        ) from exc
    return canary


def require_nulloracle() -> Any:
    """Import and return the :mod:`nulloracle` member, or raise loudly.

    The mirror of :func:`require_canary`, for the sibling that owns the
    second lamp's figure: §7.4's guard journal is feature 123's
    (:class:`~nulloracle.KsGuard`), the level its p-value is judged against
    is feature 124's (:data:`nulloracle.VOID_THRESHOLD`), and this route asks
    for both through that member rather than restating either — a second
    spelling of ``0.05`` here would be a second place §7.4's boundary could
    drift from the one feature 124 voids campaigns on.  Deferred past module
    scope and past builder time for the same scan-order reason as the door
    above.
    """
    try:
        import nulloracle
    except ModuleNotFoundError as exc:  # pragma: no cover - declared dependency
        raise ModuleNotFoundError(
            "the ops member serves the instrument-status route by reading "
            "the nulloracle member's own KS-guard journal (feature 123's "
            "persisted p-value) and comparing it against that member's own "
            "VOID_THRESHOLD (feature 124's level) rather than re-spelling "
            "§7.4's comparison, and that member is not importable in this "
            "environment; run `uv sync --all-packages` in the workspace root "
            "(or put packages/nulloracle/src on sys.path) so the lamp this "
            "route reports can be reached"
        ) from exc
    return nulloracle


# -- The lamp values -----------------------------------------------------------


def _require_lamp(value: Any, lamp: str) -> bool:
    """Return ``value`` as a genuine bool, or refuse it by name.

    ``int`` look-alikes are refused *before* the bool check would admit them,
    deliberately and for the reason every member of this workspace refuses
    ``1`` where a flag belongs: ``True`` is ``1`` in Python, so a
    ``canary=1`` would pass a naive check and a rail built from a count of
    breaks rather than from the store's bit would render green exactly as
    often as it counted a break.  A lamp is one bit — lit or out — and
    nothing else is a lamp.
    """
    if not isinstance(value, bool):
        raise InstrumentStatusError(
            f"the {lamp} lamp on a GET {INSTRUMENT_STATUS_ROUTE} answer must "
            f"be a bool — the sentence asks for *three binary lamps* and a "
            f"lamp is one bit — got {value!r} ({type(value).__name__}). A "
            f"truthy look-alike where a lamp belongs is the one substitution "
            f"that would turn a dark rail green, which is the state docs "
            f"§5.4 draws this surface to prevent (feature 342, §5.4)"
        )
    return value


def _optional_lamp(value: Any, lamp: str) -> Optional[bool]:
    """Return ``value`` as a lamp: a genuine bool, or ``None`` for absent.

    ``None`` is not a third lamp state — it is the *absence of a reading* (no
    campaign has been closed out, the guard has not run, no silence has been
    recorded, no band is configured), and the family's stance is that such a
    state is answered as an absence rather than as a verdict.  What is
    refused is everything that is neither: a string ``"ok"``, a count, a
    ``nan`` — each of which would be a lamp state no store answered.
    """
    if value is None:
        return None
    return _require_lamp(value, lamp)


def _optional_name(value: Any, what: str) -> Optional[str]:
    """Return ``value`` as a non-empty name, or ``None``, or refuse it."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InstrumentStatusError(
            f"{what} on a GET {INSTRUMENT_STATUS_ROUTE} answer must be a "
            f"non-empty name — got {value!r} ({type(value).__name__}). The "
            f"answer attributes the KS-guard lamp to the campaign it judged "
            f"and labels the ingest reading with the instant it was taken, so "
            f"an empty name is a figure nobody can order (feature 342, §5.4)"
        )
    return value.strip()


def _optional_pvalue(value: Any) -> Optional[float]:
    """Return ``value`` as a probability in ``[0, 1]``, or ``None``, or refuse.

    A p-value is a probability: feature 123's test answers one, feature 124's
    verdict refuses a stored number outside the range (*"a number outside
    that range is not a p-value any test produced"*), and the response is
    constructible by hand, so the same bound is held here on the way in.
    ``bool`` is refused before the number check, the family's law; a
    non-finite value is refused because ``nan`` compares false against
    everything, so a ``nan`` p-value would silently answer *not detectable* —
    the one direction a detectability lamp must never fail in.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InstrumentStatusError(
            f"the KS-guard lamp's p-value on a GET {INSTRUMENT_STATUS_ROUTE} "
            f"answer must be a real number — got {value!r} "
            f"({type(value).__name__}). The lamp reports §7.4's detectability "
            f"reading, and a reading that is not a number is not one any test "
            f"produced (feature 342, prd §7.4)"
        )
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise InstrumentStatusError(
            f"the KS-guard lamp's p-value on a GET {INSTRUMENT_STATUS_ROUTE} "
            f"answer must be a finite probability in [0, 1] — got {value!r}. A "
            f"p-value outside that range could not have come from any test, "
            f"and this lamp's whole point is to certify the number §7.4 judged "
            f"(feature 342, prd §7.4)"
        )
    return number


def _optional_seconds(value: Any, what: str) -> Optional[float]:
    """Return ``value`` as a finite non-negative duration, or ``None``.

    A silence is a duration and a duration has one direction: feature 328's
    measurement refuses a negative age rather than taking its magnitude
    (*"the two ends of the measurement disagree about what time it is"*), and
    the same refusal holds here — a negative lag on the rail would be a
    reading that could not have been taken from a feed at all.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InstrumentStatusError(
            f"{what} on a GET {INSTRUMENT_STATUS_ROUTE} answer must be a real "
            f"number of seconds — got {value!r} ({type(value).__name__}) "
            f"(feature 342, prd §13.3)"
        )
    number = float(value)
    if not math.isfinite(number):
        raise InstrumentStatusError(
            f"{what} on a GET {INSTRUMENT_STATUS_ROUTE} answer must be finite "
            f"— got {value!r}; a silence that is not a number cannot be inside "
            f"or outside a band (feature 342, prd §13.3)"
        )
    if number < 0:
        raise InstrumentStatusError(
            f"{what} on a GET {INSTRUMENT_STATUS_ROUTE} answer must be at "
            f"least 0 — got {value!r}. A negative silence is not a silence: it "
            f"is two readings that disagree about what time it is, the state "
            f"feature 328 refuses to measure rather than clamp (feature 342, "
            f"prd §13.3)"
        )
    return number


def _require_threshold(value: Any) -> float:
    """Return ``value`` as a strictly positive band, or refuse it by name.

    §13.3 says *threshold* and names no number, so the band is configuration
    — but a band of zero or less is not configuration, it is a watchdog that
    judges every silence past it: every lag other than exactly zero exceeds a
    non-positive band, so a deployment that configured one has wired a dark
    lamp rather than a tolerance.  The refusal is stated here, in the value
    layer, and not only at composition, because the band decides whether an
    operator may believe the figures beside this rail — and it is stated with
    feature 328's own argument for its identical refusal, reached
    independently because this module imports no band from that member.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InstrumentStatusError(
            f"{FEED_STALENESS_THRESHOLD_ENV} must be a real number of seconds "
            f"— got {value!r} ({type(value).__name__}). The ingest lamp judges "
            f"a recorded silence against §13.3's configured threshold, and a "
            f"band that is not a number is not a band (feature 342, prd §13.3)"
        )
    number = float(value)
    if not math.isfinite(number):
        raise InstrumentStatusError(
            f"{FEED_STALENESS_THRESHOLD_ENV} must be finite — got {value!r}; a "
            f"band that is not a number cannot be exceeded, so a feed judged "
            f"against it would be judged against nothing (feature 342, "
            f"prd §13.3)"
        )
    if number <= 0:
        raise InstrumentStatusError(
            f"{FEED_STALENESS_THRESHOLD_ENV} must be greater than zero — got "
            f"{value!r}; every silence other than exactly zero exceeds a "
            f"non-positive band, so a threshold of {value!r} would render the "
            f"ingest lamp dark forever rather than judging the feed "
            f"(feature 342, prd §13.3)"
        )
    return number


def _the_threshold(raw: Any) -> Optional[float]:
    """Read the configured band out of an environment value.

    Unset, empty and whitespace-only all count as unset — the semantics every
    member store's ``resolve`` takes for ``DATABASE_URL``, applied to a
    numeric knob — and an unset band is *not* an error: it is a deployment
    that has not wired half its watchdog, which the lamp answers as an
    absence (see the module docstring).  A value that *is* present but is not
    a usable band is refused by name by :func:`_require_threshold`, because a
    deployment that set this knob believes it has a band and must hear that
    it has not.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise InstrumentStatusError(
            f"{FEED_STALENESS_THRESHOLD_ENV} is set to {raw!r}, which is not a "
            f"number of seconds; the ingest lamp judges a recorded silence "
            f"against §13.3's configured threshold, and a deployment that set "
            f"this knob believes it has a band — leaving it unparsed would "
            f"leave that belief unexamined (feature 342, prd §13.3)"
        ) from exc
    return _require_threshold(number)


def _the_void_threshold() -> float:
    """§7.4's level, read through the nulloracle member that spells it.

    Feature 124's module docstring states the argument for the placement:
    *"the level that separates 'calibrated' from 'void' lives here … a reader
    tuning the tolerance finds it spelled once, beside the comparison that
    uses it."*  This route is that reader: it takes the number from the
    member rather than restating ``0.05``, so the rail's threshold and the
    level the verdict voids on cannot drift apart.

    Read on demand rather than captured at import, for the reason the
    member's doors are deferred at all — the nulloracle member is not
    promised to be importable at module scope — and it is the *only*
    cross-member read the response's constructor makes, at the moment a
    hand-built rail asks it to check its own bit.
    """
    return float(require_nulloracle().VOID_THRESHOLD)


# -- The response --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstrumentStatusResponse:
    """The answer to one GET /metrics/instrument-status: three binary lamps.

    docs/design.md §5.4's rail as a value — ``canary``, ``ks_guard``,
    ``ingest`` — each one bit, each *absent* (``None``) rather than lit when
    the store it would be read from holds nothing to judge, and each carrying
    the provenance that makes its bit reconstructible: the run instant behind
    the canary lamp, the campaign and p-value behind the KS lamp, the
    recorded silence and the configured band behind the ingest lamp.  All
    three lamps share one honest-absence law: *no reading* is never folded
    into a lit or a dark lamp.  The canary lamp's own absence is **not** "a
    database with no halt row" (that is a real measurement — *not halted* —
    and it answers the bit ``False`` would otherwise contradict); it is *no
    run recent enough to stand behind a claim of "replay is deterministic
    right now"* — no run ever recorded, or the newest one older than
    :data:`CANARY_MAX_AGE_HOURS`.  The ingest lamp's absence keeps its two
    reasons apart on the answer itself: no recorded reading is *no reading*,
    while a recorded reading with no configured band carries
    :attr:`ingest_threshold_env` naming the knob the deployment would set —
    *unconfigured*, never to be mistaken for a feed nobody measured.

    **The bits are checked against their own numbers, where a number is
    carried to check against.**  ``ks_guard`` must equal
    ``ks_pvalue >= VOID_THRESHOLD`` and ``ingest`` must equal
    ``ingest_lag_seconds <= threshold_seconds`` — both re-derived at
    construction, the discipline every value in this workspace applies to its
    own terms (feature 328's :class:`~risk.FeedStaleness`, feature 124's
    :class:`~nulloracle.Verdict`).  ``canary`` carries no such number — its
    verdict is a comparison against *now*, which this frozen value never
    reads (see :meth:`InstrumentStatusEndpoint.get`) — so its own check is
    narrower: a lit canary lamp must carry the run instant it is a verdict
    on (:attr:`canary_last_run_at`), the one thing construction *can* confirm
    without a clock.  A rail whose lamp disagreed with the reading beside it
    would render an instrument state the operator's own numbers contradict,
    and §5.4's whole purpose is that the rail can be trusted *instead of*
    the numbers.

    Frozen, because the response is the route's testimony about the
    deployment's instruments at the moment it was read: re-reading answers a
    fresh value (the halt is written by a nightly runner, the guard by a
    campaign job, the silence by whichever process measured last), and
    nothing here is a knob to adjust.
    """

    #: §12's determinism lamp — ``False`` out (feature 143's halt is on
    #: record; a halt wins over everything, so this is answered whatever
    #: feature 1's run history says), ``True`` lit (*replay is
    #: deterministic*: not halted, and the newest recorded run
    #: (:attr:`canary_last_run_at`) both passed and is within
    #: :data:`CANARY_MAX_AGE_HOURS` of the read), or ``None`` — *no
    #: reading* — when neither holds: no run ever recorded, or the newest
    #: one too old to stand behind a claim about *right now*.  Unlike
    #: ``ks_guard`` and ``ingest``, the halt half of this bit is a
    #: standing fact (it does not go stale), while the pass half does —
    #: which is exactly why a passing run many days old must still read
    #: as *no reading* rather than as a lit lamp telling the operator
    #: something nobody checked tonight.
    canary: Optional[bool] = None

    #: The instant of the newest recorded canary run
    #: (:meth:`~canary.CanaryRunStore.newest`, ISO 8601), or ``None`` when
    #: the canary has never run.  Carried independently of the ``canary``
    #: bit and of any halt — it is feature 1's own history, not this
    #: lamp's verdict, so it is present whenever a run is on record even
    #: when that run is too old to light the lamp, or when a halt (from
    #: any run, on any night) has already forced the lamp dark.  A lit
    #: lamp always carries this field: see the lamp's own cross-check in
    #: :meth:`InstrumentStatusResponse.__post_init__`.
    canary_last_run_at: Optional[str] = None

    #: §7.4's detectability lamp — ``True`` lit (*nulls indistinguishable*),
    #: ``False`` out (the guard's p-value fell strictly below the level), or
    #: ``None`` when there is no finding to report (no closed campaign, or the
    #: guard has not run for the one the trend names).  Never ``True`` for an
    #: unguarded campaign: ``ks_pvalue`` is ``NULL`` until the guard fills it,
    #: and an unmeasured campaign is not a passing one.
    ks_guard: Optional[bool] = None

    #: §13.3's feed lamp — ``True`` lit (*the recorded silence is inside the
    #: band*), ``False`` out (strictly greater than the band), or ``None``
    #: when half the watchdog is missing: no recorded reading, or no
    #: configured band.  The two halves stay distinguishable — a reading with
    #: no band still carries :attr:`ingest_lag_seconds` and
    #: :attr:`ingest_read_at` *and* names the missing knob through
    #: :attr:`ingest_threshold_env`, and a band with no reading still carries
    #: :attr:`threshold_seconds` — because an operator whose watchdog is
    #: half-wired needs to see which half.
    ingest: Optional[bool] = None

    #: The campaign the KS lamp reports on — the newest row of the scoring
    #: member's own trend read, the same campaign this member's neighbouring
    #: route top-lines and docs' hero plate names.  ``None`` exactly when the
    #: trend names no campaign (the KS lamp is then absent), and present even
    #: when the guard has not run (the campaign is known; the finding is not)
    #: — the distinction between *no campaign* and *no finding* that an
    #: operator chasing a dark lamp needs first.
    campaign: Optional[str] = None

    #: The p-value the KS lamp judged — feature 123's persisted number, read
    #: back through the member's own store, which refuses a half.  Present
    #: exactly when the lamp is: a lamp with no number would be a verdict
    #: nothing stands behind.
    ks_pvalue: Optional[float] = None

    #: The recorded silence the ingest lamp judged, in seconds — feature 350's
    #: newest ``feed_staleness_s`` row, the risk member's quantity handed over
    #: already measured.  Present whenever a row exists, whether or not a band
    #: is configured.
    ingest_lag_seconds: Optional[float] = None

    #: The instant the recorded silence was labelled with — the row's own
    #: ``logged_at``, rendered exactly as the store holds it (ISO 8601 UTC).
    #: Carried rather than recomputed, because the route reads no clock: the
    #: age *of the reading* is the one thing that tells an operator whether a
    #: lit lamp is a live report or a stale one.
    ingest_read_at: Optional[str] = None

    #: The configured band the recorded silence is judged against (§13.3's
    #: threshold), or ``None`` when the deployment configured none.  Present
    #: whenever it was configured — including when no reading exists, because
    #: *the knob is set and nothing has been measured* is exactly the half a
    #: half-wired watchdog shows.
    threshold_seconds: Optional[float] = None

    #: The band knob a recorded silence with no band names as missing —
    #: :data:`FEED_STALENESS_THRESHOLD_ENV`'s own spelling, or ``None``.
    #: This is the one absence on the rail whose repair is a *setting*
    #: rather than a measurement, and the answer names the setting so the
    #: operator is sent to the environment and not to the feed: a reading
    #: with no threshold is *unconfigured*, while no reading at all is *no
    #: reading*, and the two states must never render as one.  **Derived at
    #: construction** from the halves it names — present exactly when
    #: :attr:`ingest_lag_seconds` is present and :attr:`threshold_seconds`
    #: is absent, the same re-derivation discipline that checks each
    #: carried bit against the number beside it — so a hand-built rail and
    #: the route's own answer cannot disagree about which knob is missing.
    ingest_threshold_env: str | None = None

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so normalisation writes
        # through object.__setattr__ — the same discipline feature 341's
        # response and feature 343's ledger follow.
        canary_bit = _optional_lamp(self.canary, "canary")
        canary_last_run_at = _optional_name(
            self.canary_last_run_at, "the canary lamp's last run instant"
        )
        ks_guard = _optional_lamp(self.ks_guard, "ks_guard")
        ingest = _optional_lamp(self.ingest, "ingest")
        campaign = _optional_name(self.campaign, "the KS lamp's campaign")
        pvalue = _optional_pvalue(self.ks_pvalue)
        lag = _optional_seconds(self.ingest_lag_seconds, "the ingest lamp's lag")
        read_at = _optional_name(self.ingest_read_at, "the ingest reading's instant")
        threshold = (
            None
            if self.threshold_seconds is None
            else _require_threshold(self.threshold_seconds)
        )

        if canary_bit is True and canary_last_run_at is None:
            raise InstrumentStatusError(
                f"a GET {INSTRUMENT_STATUS_ROUTE} answer reports the canary "
                f"lamp as True with no last-run instant; the lamp is the "
                f"verdict on a specific, recent canary run (feature 1's "
                f"newest recorded row), so a lit lamp with no run behind it "
                f"is a verdict nothing stands behind (feature 342, prd §12)"
            )
        if (ks_guard is None) != (pvalue is None):
            raise InstrumentStatusError(
                f"a GET {INSTRUMENT_STATUS_ROUTE} answer reports the KS-guard "
                f"lamp as {ks_guard!r} beside a p-value of {pvalue!r}; the "
                f"lamp *is* the verdict on that number — feature 123's "
                f"persisted p-value compared against feature 124's level — so "
                f"a lamp without its number is a verdict nothing stands "
                f"behind, and a number without its lamp is a finding nobody "
                f"rendered (feature 342, prd §7.4)"
            )
        if ks_guard is not None and campaign is None:
            raise InstrumentStatusError(
                f"a GET {INSTRUMENT_STATUS_ROUTE} answer reports the KS-guard "
                f"lamp as {ks_guard!r} and names no campaign; §7.4's guard "
                f"reading is a fact about a campaign (feature 123 keys its "
                f"journal by campaign id), so a lamp with no campaign is an "
                f"instrument status nobody can attribute — the unauditable "
                f"numeral docs §5.4 exists to rule out (feature 342, §7.4)"
            )
        if (lag is None) != (read_at is None):
            raise InstrumentStatusError(
                f"a GET {INSTRUMENT_STATUS_ROUTE} answer carries a recorded "
                f"silence of {lag!r}s beside the instant {read_at!r}; the "
                f"reading and its label are one row (feature 350's ``(metric, "
                f"logged_at)`` key), so an age without its instant could not "
                f"be ordered against anything (feature 342, prd §13.3)"
            )
        if ingest is not None and (lag is None or threshold is None):
            raise InstrumentStatusError(
                f"a GET {INSTRUMENT_STATUS_ROUTE} answer reports the ingest "
                f"lamp as {ingest!r} with lag={lag!r} and band={threshold!r}; "
                f"the lamp is a judgement of a measured silence against a "
                f"configured band, so a lit-or-dark lamp needs both halves — "
                f"half a watchdog is an absence, never a verdict (feature 342, "
                f"prd §13.3)"
            )

        if pvalue is not None:
            # The comparison is §7.4's own, against the level the *member*
            # spells — never a number restated here.  Strictly below is
            # detectable, so the lamp is dark; at or above it the nulls are
            # indistinguishable and the lamp is lit, the margin feature 124's
            # docstring argues for ("the boundary errs toward keeping a
            # campaign in").
            expected = pvalue >= _the_void_threshold()
            if ks_guard != expected:
                raise InstrumentStatusError(
                    f"the KS-guard lamp on a GET {INSTRUMENT_STATUS_ROUTE} "
                    f"answer states {ks_guard!r} beside a p-value of "
                    f"{pvalue!r}; §7.4 voids a campaign whose p-value falls "
                    f"strictly below the level, so this reading is "
                    f"{'indistinguishable' if expected else 'detectable'} and "
                    f"the lamp must say so. A rail whose bit disagreed with "
                    f"its own number would report an instrument status the "
                    f"evidence contradicts (feature 342, prd §7.4)"
                )
        if ingest is not None and lag is not None and threshold is not None:
            # §13.3's own boundary, strictly greater is out — the convention
            # feature 328's judgement states ("a feed silent for exactly the
            # band is inside it") and feature 329's and 314's boundaries
            # share.  Equality is inside: a feed silent for exactly the band
            # is not this lamp's business.
            expected = lag <= threshold
            if ingest != expected:
                raise InstrumentStatusError(
                    f"the ingest lamp on a GET {INSTRUMENT_STATUS_ROUTE} "
                    f"answer states {ingest!r} beside a recorded silence of "
                    f"{lag!r}s and a band of {threshold!r}s; §13.3's row is "
                    f"*staleness > threshold*, so a silence of exactly the "
                    f"band is inside it — this reading is "
                    f"{'inside' if expected else 'outside'} and the lamp must "
                    f"say so (feature 342, prd §13.3)"
                )

        object.__setattr__(self, "canary", canary_bit)
        object.__setattr__(self, "canary_last_run_at", canary_last_run_at)
        object.__setattr__(self, "ks_guard", ks_guard)
        object.__setattr__(self, "ingest", ingest)
        object.__setattr__(self, "campaign", campaign)
        object.__setattr__(self, "ks_pvalue", pvalue)
        object.__setattr__(self, "ingest_lag_seconds", lag)
        object.__setattr__(self, "ingest_read_at", read_at)
        object.__setattr__(self, "threshold_seconds", threshold)
        # The knob the no-band absence names, derived from the halves it
        # names rather than carried, so no caller — route or hand-built —
        # can state a missing setting the readings do not show missing.
        # Reading present and band absent is *unconfigured*; anything else
        # names no knob, because *no reading* and *judged* are not
        # configuration states (J04 step 3's distinction).
        object.__setattr__(
            self,
            "ingest_threshold_env",
            (
                FEED_STALENESS_THRESHOLD_ENV
                if (lag is not None and threshold is None)
                else None
            ),
        )

    # -- The rail, read back ------------------------------------------------

    @property
    def lamps(self) -> dict[str, Optional[bool]]:
        """The rail as docs §5.4 draws it — ``{lamp: bit or None}``.

        A fresh dict per call, so a caller cannot mutate this value's answer,
        and a view *over* the three fields rather than a second copy of them:
        the bits are the attributes', and a value that stored both would be
        two records of one rail.  ``None`` is the absence of a reading, and it
        is carried through as ``None`` — never folded into ``False``, because
        *nobody measured* and *the instrument is out* are different states and
        §5.4's rail treats them differently.
        """
        return {name: getattr(self, name) for name in LAMP_NAMES}

    @property
    def absent(self) -> tuple[str, ...]:
        """The lamps this answer reports no reading for, in rail order.

        The absence state, named so an operator chasing a dark rail can see
        which lamps were *lit*, which were *out* and which were never read —
        the three states a boolean-only rail collapses.
        """
        return tuple(name for name, bit in self.lamps.items() if bit is None)

    @property
    def failing(self) -> tuple[str, ...]:
        """The lamps that are *lit out* — read, and out — in rail order.

        Deliberately not the same tuple as :attr:`absent`: an absent lamp is
        not a failing one, and a caller that treated the two alike would
        report an unmeasured instrument as a broken one — the same conflation
        feature 341's empty trend and feature 343's empty ledger refuse on
        their own surfaces.
        """
        return tuple(name for name, bit in self.lamps.items() if bit is False)

    def __bool__(self) -> bool:
        """Whether the whole rail is lit — three readings, all inside.

        ``True`` only when every lamp is *present and lit*: an absent lamp is
        not a lit one, so a deployment with an unmeasured instrument answers
        falsy here, and a caller that needs *may I believe the numerals beside
        this rail?* gets the conservative answer §5.4's *"everything below
        them is worthless if any is out"* implies.  A caller that wants the
        finer three-way reading asks :attr:`absent` and :attr:`failing`.
        """
        return all(bit is True for bit in self.lamps.values())


# -- The deferred readings -----------------------------------------------------


class _DeferredInstrumentReadings:
    """The five readings a composed route takes, resolved at first read.

    :meth:`InstrumentStatusEndpoint.from_env` reads ``DATABASE_URL`` eagerly
    — whether a route composes at all is a fact about the deployment, and the
    builder must decide it at composition — but it cannot *construct* the
    sibling stores there, for the scan-order reason :func:`require_canary`
    exists: the factory's workspace scan puts one member's ``src/`` on
    ``sys.path`` at a time and has already taken the canary, nulloracle and
    scoring members' off again by the time builders fire, so a build-time
    ``canary.CanaryHaltStore(...)`` would import those members exactly where
    those imports are not promised to work — and a component whose builder
    raises takes the whole composition down with it.

    So the endpoint holds this carrier, which keeps the URL it was resolved
    from (that is the composition fact — the one database this route, the
    composed sibling stores and every figure beside the rail point at, pinned
    by tests without reading anything) and constructs each real store on the
    read that needs it, where the caller is precisely one who reached for
    that lamp and therefore runs somewhere the declared dependency is
    importable.

    Five reads, one per fact the route needs — the shape the lamps demand
    rather than a convenience surface:

    * :meth:`canary_halted` — the canary member's own monotone bit;
    * :meth:`canary_last_run` — feature 1's own newest recorded run, as the
      ``(ran_at, within_tolerance)`` pair the store labels it with;
    * :meth:`campaign` — the newest campaign of the scoring member's own
      trend read, which is also how this member's neighbouring route
      attributes its top-line figure;
    * :meth:`ks_pvalue` — the nulloracle member's persisted p-value for that
      campaign, read back through its own ``load`` (which refuses a half
      rather than answering one);
    * :meth:`feed_reading` — this member's own newest recorded
      ``feed_staleness_s`` row, as the ``(logged_at, seconds)`` pair the
      store labels it with.

    Duck-shaped exactly as the endpoint's check demands — those five names
    and nothing else — because that is the whole contract; nothing here
    re-spells a store behaviour, it only moves each store's construction
    from a moment the import cannot happen to the first moment it must.
    """

    __slots__ = ("_url", "_halt", "_run", "_fdr", "_guard", "_live")

    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._halt: Any = None
        self._run: Any = None
        self._fdr: Any = None
        self._guard: Any = None
        self._live: Any = None

    @property
    def database_url(self) -> str:
        """The URL ``DATABASE_URL`` named at composition — carried, not
        re-read, so the route cannot drift to a later environment."""
        return self._url

    def canary_halted(self) -> bool:
        """§12's halt state, through the canary member's own store.

        One bit for the deployment: the halt takes no campaign argument
        (feature 143's ``halt`` is the deployment's, and its ``halted`` read
        is monotone once set), so this read takes none either.  A store that
        cannot be opened or read raises the canary member's own error, which
        the route translates — never answered with a lit lamp.
        """
        if self._halt is None:
            canary = require_canary()
            self._halt = canary.CanaryHaltStore(self._url)
        return self._halt.halted()

    def canary_last_run(self) -> Optional[tuple[dt.datetime, bool]]:
        """Feature 1's newest recorded run, as ``(ran_at, within_tolerance)``.

        Read through :meth:`canary.CanaryRunStore.newest`, the member's own
        history read, which reconstructs the row through its own validation
        (so a row edited outside that package cannot reach this route as a
        plausible-looking run).  ``ran_at`` is handed through as the
        timezone-aware :class:`datetime.datetime` the store already parsed
        it into — a stdlib type, not the member's own :class:`~canary.CanaryRun`,
        so nothing of the canary member's own class crosses this seam, the
        same "plain data" shape :meth:`feed_reading` hands back for its row.

        ``None`` when the canary has never run — a discoverable state, not
        an error, the same stance an empty trend takes for :meth:`campaign`.
        A store that cannot be opened or read raises the canary member's own
        error, translated at the route and never answered around.
        """
        if self._run is None:
            canary = require_canary()
            self._run = canary.CanaryRunStore(self._url)
        record = self._run.newest()
        if record is None:
            return None
        return (record.ran_at, bool(record.within_tolerance))

    def campaign(self) -> Optional[str]:
        """The newest campaign of the scoring member's own trend read.

        ``history()`` is feature 267's own read, ordered ``computed_at ASC,
        campaign_id ASC`` — the order prd §12's M3 exit reads *"improves"*
        across — so *newest* is its **last row**, taken here rather than
        restated as an ``ORDER BY`` (the same inheritance feature 341's route
        performs for the top-line figure, and the reason the two surfaces can
        never attribute their readings to different campaigns).

        ``None`` for an empty trend: a deployment that has closed no campaign
        out has no campaign for a guard reading to belong to, which is a
        discoverable state and not an error — feature 267's own stance for the
        same empty list.
        """
        if self._fdr is None:
            scoring = require_scoring()
            self._fdr = scoring.FdrDeployStore(self._url)
        history = self._fdr.history()
        if not history:
            return None
        newest = history[-1]
        # The row is feature 267's ``(campaign_id, fdr_deploy, computed_at)``
        # triple, the campaign already in the canonical UUID text the store's
        # own key spelling produces — which is the join feature 123's guard
        # store takes, so no second normalisation happens here.  Nothing here
        # re-derives the figure.
        return str(newest[0])

    def ks_pvalue(self, campaign: str) -> Optional[float]:
        """Feature 123's persisted p-value for ``campaign``, or ``None``.

        Read through :meth:`nulloracle.KsGuard.load`, the member's own read,
        which answers ``None`` for a campaign no job has guarded and *refuses*
        a half (a campaign column without its provenance row, or the reverse)
        — so this method can never hand the route a number the guard did not
        record.  ``None`` therefore means *the guard has not run*, never *the
        read failed*: a read that failed raises through the member's own error
        and is translated at the route.
        """
        if self._guard is None:
            nulloracle = require_nulloracle()
            self._guard = nulloracle.KsGuard(self._url)
        record = self._guard.load(campaign)
        if record is None:
            return None
        return float(record.pvalue)

    def feed_reading(self) -> Optional[tuple[str, float]]:
        """The newest recorded ``feed_staleness_s`` row, or ``None``.

        Feature 350's own ``series`` read — ordered ``logged_at ASC`` by the
        store itself, so *newest* is again the last row, inherited rather than
        restated — over the closed metric name the store validates
        (:data:`~ops.live_metrics.LIVE_METRICS`).  The pair is the store's own
        ``(logged_at, value)`` shape, plain data crossing no member seam:
        this method re-derives neither the figure nor its label, it takes the
        row.

        ``None`` when the store holds no reading of that metric — nothing has
        measured the feed, which is an absence the lamp answers as an absence
        rather than as a zero-second silence.
        """
        if self._live is None:
            self._live = LiveMetricsStore(self._url)
        series = self._live.series(FEED_STALENESS_METRIC)
        if not series:
            return None
        logged_at, seconds = series[-1]
        return (str(logged_at), float(seconds))


class InstrumentStatusEndpoint:
    """Serves GET /metrics/instrument-status over the deployment's stores.

    The rail's three facts are each the owning member's own read — the canary
    member's halt bit and run history, the nulloracle member's guard journal,
    the scoring member's trend for the campaign attribution, this member's own
    recorded live reading for the silence — reached through those members
    rather than re-implemented here; see the module docstring for the law and
    :func:`require_canary` / :func:`require_nulloracle` for the doors.
    Constructed with the readings it takes; :meth:`get` is the route.

    The endpoint holds no state of its own — no cache of a previous rail, no
    memo of a lamp — because the answer must be the instruments' state at the
    moment it is asked for: the nightly runner writes a halt, a campaign job
    writes a guard reading, the order path records a live metric, and a cached
    rail would make the operator's view a fact about when the surface happened
    to start rather than about what the system is doing now.  The canary
    lamp carries this furthest: even an unchanged run history answers
    differently from one call to the next once the newest run ages past
    :data:`CANARY_MAX_AGE_HOURS`, because the comparison is against *now*.

    The carrier is duck-checked, never ``isinstance``-guarded, for the reason
    every seam in this workspace gives: the factory's scan imports members
    under synthetic names, so a *composed* carrier is structurally this
    module's and never the same class object a direct import yields.  The
    contract is the five reads the three lamps need, and each is named in the
    refusal when it is missing — because the repair differs by lamp (*wire the
    halt store* is not *wire the trend read*), and a caller that was told only
    "the carrier is wrong" would not know which lamp went dark.
    """

    #: The route this endpoint serves — :data:`INSTRUMENT_STATUS_ROUTE`,
    #: pinned as a class attribute so ``InstrumentStatusEndpoint.route``
    #: states the contract without an instance.
    route = INSTRUMENT_STATUS_ROUTE

    def __init__(self, readings: Any, *, threshold_seconds: Any = None) -> None:
        for read in (
            "canary_halted",
            "canary_last_run",
            "campaign",
            "ks_pvalue",
            "feed_reading",
        ):
            if not callable(getattr(readings, read, None)):
                raise TypeError(
                    "InstrumentStatusEndpoint speaks an instrument-reading "
                    f"carrier (something with {read}()); got "
                    f"{type(readings).__name__}. The route returns canary, KS "
                    "guard and ingest lag as three binary lamps (feature 342, "
                    "docs §5.4), and each lamp is the owning member's own read "
                    "— a carrier that cannot answer one of the five facts "
                    "would leave that lamp unreadable."
                )
        self._readings = readings
        self._threshold = (
            None
            if threshold_seconds is None
            else _require_threshold(threshold_seconds)
        )

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["InstrumentStatusEndpoint"]:
        """The endpoint over the stores ``DATABASE_URL`` names, or ``None``
        when it names none.

        The URL is resolved eagerly — whether a route composes at all is a
        fact about the deployment, read from
        :data:`~ops.live_metrics.DATABASE_URL_ENV` with the same unset
        semantics every member store's resolution takes (absent, empty and
        whitespace-only all count as unset) — and the band the ingest lamp
        judges against is resolved eagerly beside it, from
        :data:`FEED_STALENESS_THRESHOLD_ENV`, because *is this watchdog
        wired?* is likewise a composition fact; but the *stores* are deferred
        to the first read (:class:`_DeferredInstrumentReadings`), because a
        builder runs at composition and the factory's scan has already taken
        the sibling members' ``src/`` off ``sys.path`` by then.

        No ``DATABASE_URL`` composes no endpoint — an unconfigured store is a
        discoverable state, not an error (the stance every builder in this
        member takes), and it is deliberately *not* the absent-lamp answer: no
        route at all says there is nowhere any reading could have been
        persisted, while a composed route with an absent lamp says which
        specific instrument was never read.

        A band that is *present and unusable* — not a number, not finite, not
        positive — is refused here rather than treated as unset, because a
        deployment that set the knob believes its watchdog is wired; the
        refusal is this member's own error and names the variable, so an
        operator learns which knob to fix.  A band that is absent leaves the
        ingest lamp absent (see the module docstring).
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "")
        if not isinstance(raw, str) or not raw.strip():
            return None
        return cls(
            _DeferredInstrumentReadings(raw.strip()),
            threshold_seconds=_the_threshold(source.get(FEED_STALENESS_THRESHOLD_ENV)),
        )

    @property
    def readings(self) -> Any:
        """The carrier this endpoint reads — the five instrument reads, held
        duck-typed across the member seams.  For an endpoint built by
        :meth:`from_env` this is the deferred carrier
        (:class:`_DeferredInstrumentReadings`) until the first read: it
        carries the resolved ``database_url`` from composition and constructs
        each member's store only where reading that lamp actually happens."""
        return self._readings

    @property
    def threshold_seconds(self) -> Optional[float]:
        """The band the ingest lamp judges the recorded silence against, or
        ``None`` when the deployment configured none — the *half a watchdog*
        state, answered as an absent lamp."""
        return self._threshold

    # -- The route ----------------------------------------------------------

    def get(self) -> InstrumentStatusResponse:
        """Answer one GET /metrics/instrument-status: three binary lamps.

        The whole of feature 342 at its seam.  The route takes no arguments: a
        GET over the deployment's instruments has no body and no campaign to
        state, and the sentence asks for the three lamps — canary, KS guard
        and ingest lag — not for one instrument's detail, so a filtered ask (a
        single lamp, another campaign) is the store's own read, and not this
        route's.

        Each lamp is read through the member that owns it, in the order docs
        §5.4 draws them, and each read is *translated* into this member's
        vocabulary at its own seam so a caller that catches
        :class:`~ops.errors.InstrumentStatusError` is not taken down by a
        sibling's error class.  A lamp nobody has measured is answered as
        ``None`` — never lit, and never folded into *out* — while a read that
        **fails** is refused rather than answered around, because every
        fallback this route could add is a lamp state nobody read (*"bad data
        does not quietly age into good data"*, docs §5.4).

        The canary lamp is read in two parts, both through the canary
        member: the halt (:meth:`~_DeferredInstrumentReadings.canary_halted`)
        and the newest run
        (:meth:`~_DeferredInstrumentReadings.canary_last_run`).  A halt wins
        over everything — ``False``, regardless of what the run history
        says — exactly as it does today; short of a halt, the lamp is
        ``True`` only when a run is on record, it passed, and it is within
        :data:`CANARY_MAX_AGE_HOURS` of **this** read (the one clock read
        this route makes, inline, never stored); anything else is ``None``.
        ``canary_last_run_at`` carries the newest run's own instant whenever
        one is on record, independent of the bit, so an operator reading a
        halted or absent lamp can still see when the canary last spoke.

        The ingest lamp is the one lamp that may be absent for two different
        reasons, and the answer keeps them apart: no recorded reading (the
        store's series is empty) and no configured band (the deployment wired
        half a watchdog) leave different fields present — a reading with no
        band still carries
        :attr:`~InstrumentStatusResponse.ingest_lag_seconds` and its instant,
        and a band with no reading still carries
        :attr:`~InstrumentStatusResponse.threshold_seconds`, so the operator
        can see which half is missing.
        """
        canary = require_canary()
        nulloracle = require_nulloracle()
        scoring = require_scoring()

        try:
            halted = self._readings.canary_halted()
        except canary.CanaryError as exc:
            raise InstrumentStatusError(
                f"could not answer GET {INSTRUMENT_STATUS_ROUTE}: the canary "
                f"member's halt store refused the read: {exc!r}. §12's "
                f"determinism halt is the rail's first lamp — *\"everything "
                f"below them is worthless if any is out\"* (docs §5.4) — so a "
                f"halt state that cannot be asked is surfaced rather than "
                f"answered around with a lit lamp; the repair is the store's "
                f"(the original refusal is chained), never a default "
                f"(feature 342, docs §5.4)"
            ) from exc

        try:
            last_run = self._readings.canary_last_run()
        except canary.CanaryError as exc:
            raise InstrumentStatusError(
                f"could not answer GET {INSTRUMENT_STATUS_ROUTE}: the canary "
                f"member's run history refused the read: {exc!r}. The canary "
                f"lamp's *no reading* state is only honest when the run "
                f"history was actually asked and found empty or stale — a "
                f"history that cannot be asked is surfaced rather than "
                f"answered around with no reading or a lit lamp; the repair "
                f"is the store's (the original refusal is chained), never a "
                f"default (feature 342, prd §12)"
            ) from exc

        canary_last_run_at: Optional[str] = None
        canary_lit: Optional[bool] = None
        if last_run is not None:
            ran_at, within_tolerance = last_run
            canary_last_run_at = ran_at.isoformat()
            fresh = (dt.datetime.now(dt.UTC) - ran_at) <= dt.timedelta(
                hours=CANARY_MAX_AGE_HOURS
            )
            if within_tolerance and fresh:
                canary_lit = True
        if halted:
            # A halt wins over everything, as today — whatever the run
            # history says, however fresh.
            canary_lit = False

        campaign: Optional[str] = None
        pvalue: Optional[float] = None
        try:
            campaign = self._readings.campaign()
        except scoring.FdrDeployError as exc:
            raise InstrumentStatusError(
                f"could not answer GET {INSTRUMENT_STATUS_ROUTE}: the scoring "
                f"member's FDR_deploy trend refused the read that attributes "
                f"the KS-guard lamp to a campaign: {exc!r}. The lamp reports "
                f"the guard finding for the campaign the top-line figure "
                f"belongs to (the newest row of feature 267's own read), so a "
                f"trend that cannot be asked leaves this lamp unattributable — "
                f"refused rather than answered by picking some other campaign; "
                f"the original refusal is chained (feature 342, prd §7.4)"
            ) from exc
        if campaign is not None:
            try:
                pvalue = self._readings.ks_pvalue(campaign)
            except nulloracle.KsGuardError as exc:
                raise InstrumentStatusError(
                    f"could not answer GET {INSTRUMENT_STATUS_ROUTE}: the "
                    f"nulloracle member's KS-guard journal refused the read "
                    f"for campaign {campaign!r}: {exc!r}. §7.4's guard reading "
                    f"is the rail's second lamp, and a *half*-written reading "
                    f"— a campaign column without its provenance or the "
                    f"reverse — is exactly the state feature 123's own read "
                    f"refuses rather than answering, so it is surfaced here "
                    f"too; the repair is the store's (the original refusal is "
                    f"chained), never a default (feature 342, prd §7.4)"
                ) from exc

        reading: Optional[tuple[str, float]] = None
        try:
            reading = self._readings.feed_reading()
        except LiveMetricError as exc:
            raise InstrumentStatusError(
                f"could not answer GET {INSTRUMENT_STATUS_ROUTE}: this "
                f"member's own live-metrics store refused the read of the "
                f"{FEED_STALENESS_METRIC!r} series: {exc!r}. The recorded "
                f"silence is the rail's third lamp (docs §5.4's *feed lag*), "
                f"and a store that cannot be asked is surfaced rather than "
                f"answered around — an unreadable feed reading answered green "
                f"is precisely the *\"bad data quietly aging into good data\"* "
                f"§5.4 draws this surface to prevent; the original refusal is "
                f"chained (feature 342, prd §13.3)"
            ) from exc

        read_at: Optional[str] = None
        lag: Optional[float] = None
        if reading is not None:
            read_at, lag = reading

        threshold = self._threshold
        ingest: Optional[bool]
        if lag is None or threshold is None:
            # Half a watchdog — or none at all.  The lamp is an absence, and
            # whichever half *is* present is carried so the operator can see
            # which one is missing (see the response's own docstring).
            ingest = None
        else:
            # §13.3's own boundary: strictly greater is out, so a silence of
            # exactly the band is inside it.
            ingest = lag <= threshold

        return InstrumentStatusResponse(
            canary=canary_lit,
            canary_last_run_at=canary_last_run_at,
            ks_guard=(
                None if pvalue is None else pvalue >= float(nulloracle.VOID_THRESHOLD)
            ),
            ingest=ingest,
            campaign=campaign,
            ks_pvalue=pvalue,
            ingest_lag_seconds=lag,
            ingest_read_at=read_at,
            threshold_seconds=threshold,
        )
