"""Feature 241: the configured legal theme set, and the refusal at assignment.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 241: *System
rejects a root theme outside the configured legal set when assigning a
research theme.*  Four things are asserted here, in the order the feature's
own sentence implies them — the *set* (the configured space, and what it
refuses to be configured with), the *question* (membership), the *refusal*
(the verb, on one theme and on a batch), and the *resolution* (which
deployment gets which space).

**The refusal is tested on the class, not on the message text.**  Like
feature 232's suite, this file pins ``IllegalThemeError`` rather than
substring-matching prose, so the message can be improved without breaking a
test that was only ever about *which* failure occurred.  The one exception is
:data:`~discovery.ILLEGAL_THEME`, which *is* asserted as text — the code is
part of the contract (app_spec.xml feature 212 names ``illegal_theme`` as the
message this refusal returns, and an operator greps a log for it), so it is
pinned as data rather than left to a message's opening words.

**The default is tested as PRD §9.3's list, not as a length.**  A test that
asserted "six themes" would pass against any six strings, so the default set
is asserted **element for element** against the PRD's numbered list — the one
thing that catches a transcription that dropped a theme or substituted one.
The rest of the default's behaviour (unset means it, blank does not) is the
resolver's, and it is pinned separately because those are different facts:
*what the space is* and *when the space is used*.

**Case and whitespace are insignificant; everything else is not.**  This is
the module's one normalisation decision and it cuts both ways, so it is
tested from both sides: the two spellings of one theme that *must* fold
together (casing, surrounding whitespace — because they are the same value),
and the near-misses that must *not* (an underscore, an inner space, a dot, a
trailing hyphen — because they are different strings that look like themes,
and silently repairing one would store a declaration nobody made).  A
normaliser that folded both, or neither, fails one of the two.
"""

from __future__ import annotations

import re

import pytest
from discovery import (
    DEFAULT_LEGAL_THEMES,
    DEFAULT_THEME_SET,
    ILLEGAL_THEME,
    LEGAL_THEMES_ENV,
    THEME_ROOT_COLUMN,
    DiscoveryError,
    IllegalThemeError,
    ThemeSet,
    assign_theme,
    legal_themes_from_env,
)

#: PRD §9.3's initial six theme roots, transcribed **from the PRD's own
#: numbering** rather than from :data:`DEFAULT_LEGAL_THEMES`.  Written out
#: here as the independent statement the constant is checked against: a test
#: that iterated the constant would agree with itself whatever the constant
#: said, which is precisely the failure this list exists to catch.
PRD_9_3_THEME_ROOTS = (
    # 1. Cross-sectional momentum and short-term reversal, small/mid-cap universe
    "cross-sectional-momentum",
    # 2. Order-flow imbalance and microstructure features from the free L2 feed
    "order-flow-imbalance",
    # 3. Borrow-rate and funding-state conditioning
    "borrow-rate-conditioning",
    # 4. Volatility-state and dispersion regimes
    "volatility-dispersion",
    # 5. Mechanical calendar and event effects
    "calendar-events",
    # 6. Cross-asset and cross-venue state divergence (state, not price)
    "cross-asset-divergence",
)

#: Spellings that are *one keystroke* from a legal theme and must be refused
#: rather than normalised into one.  Each is a different string, and the
#: point of the list is that a normaliser which "helpfully" repaired them
#: would store a theme the planner never declared — the same
#: refuse-don't-normalise line feature 232's ``_validated_campaign_type``
#: draws for ``"Type R"``.
NEAR_MISSES = (
    "order_flow_imbalance",
    "order flow imbalance",
    "order.flow.imbalance",
    "order-flow-imbalance-",
    "-order-flow-imbalance",
    "order--flow-imbalance",
    "2-order-flow-imbalance",
    "order-flow-imbalance "[:-1] + "!",
)


# -- The default space --------------------------------------------------------------


def test_the_default_set_is_prd_9_3s_initial_roots() -> None:
    # The transcription itself.  §9.3 lists the six research themes the
    # programme starts from, and this constant is this member's spelling of
    # them: same themes, same order, nothing added and nothing dropped.  An
    # *order-sensitive* comparison on purpose — the tuple is documentation as
    # well as data (see the constant's docstring), so a reordering is an edit
    # to what an operator reads and deserves to be seen.
    assert tuple(DEFAULT_LEGAL_THEMES) == PRD_9_3_THEME_ROOTS
    assert len(PRD_9_3_THEME_ROOTS) == 6


def test_the_default_set_carries_every_root_the_prd_names() -> None:
    # The same fact through the resolved value, which is what a planner
    # actually holds: every one of §9.3's themes is assignable with no
    # configuration at all — a deployment that declared nothing still has
    # PRD §9's space rather than an unconstrained one.
    for theme in PRD_9_3_THEME_ROOTS:
        assert DEFAULT_THEME_SET.assign(theme) == theme
        assert theme in DEFAULT_THEME_SET


def test_the_prd_set_is_the_default_theme_set() -> None:
    # ``DEFAULT_THEME_SET`` is built from ``DEFAULT_LEGAL_THEMES`` at import,
    # through the same validation a configured value passes through — so the
    # constant and the value cannot disagree, and a default that ever drifted
    # past the identifier grammar would fail this member's import rather than
    # first failing a planner.
    assert DEFAULT_THEME_SET.themes == tuple(sorted(PRD_9_3_THEME_ROOTS))


def test_a_default_set_is_sorted_and_the_constant_is_the_prds_order() -> None:
    # Two orders, two purposes, and the difference is deliberate: the constant
    # is the PRD's numbering (what a reader checks against) while the resolved
    # set is sorted (what a comparison is made against).  Pinned because the
    # temptation is to "simplify" one into the other.
    assert tuple(DEFAULT_LEGAL_THEMES) == PRD_9_3_THEME_ROOTS  # PRD order
    assert DEFAULT_THEME_SET.themes == tuple(
        sorted(PRD_9_3_THEME_ROOTS)
    )  # canonical order


def test_the_default_set_is_repr_able_and_iterable() -> None:
    # The value's small surface: ``in`` is the question, ``iter`` the space,
    # ``len`` its size.  Asserted together because a set that answered ``in``
    # but iterated nothing would be the shape a caller building a report off
    # it would trip over.
    assert len(DEFAULT_THEME_SET) == 6
    assert set(iter(DEFAULT_THEME_SET)) == set(PRD_9_3_THEME_ROOTS)
    assert "ThemeSet(themes=" in repr(DEFAULT_THEME_SET)


def test_the_column_the_refusal_is_about_is_feature_97s() -> None:
    # The refusal is *about* one column — the theme a root is planted in,
    # declared ``TEXT NOT NULL`` by 0118 — and the constant is spelled here so
    # a reader of the refusal learns which column the value belongs to.  The
    # literal is pinned as data because it is feature 97's spelling, not this
    # feature's choice.
    assert THEME_ROOT_COLUMN == "theme_root"


def test_the_error_code_is_the_specs_word() -> None:
    # app_spec.xml names ``illegal_theme`` as the message this refusal
    # returns, and feature 212 names it for the proposal-level twin.  Pinned
    # as data because the code is the greppable contract, not prose.
    assert ILLEGAL_THEME == "illegal_theme"


# -- The set as a value --------------------------------------------------------------


def test_a_configured_set_is_canonicalised_and_deduplicated() -> None:
    # Three spellings of one theme and one other: the set is canonical, so a
    # deployment that wrote ``Momentum`` beside ``momentum`` has one theme and
    # not two — the seam architecture §11.1 exposes ``theme_root`` through is
    # keyed on the family, and two spellings would be two families.
    configured = ThemeSet(("Momentum", "  momentum ", "CARRY"))
    assert configured.themes == ("carry", "momentum")
    assert len(configured) == 2


def test_a_set_may_be_empty_and_refuses_every_theme() -> None:
    # The strictest space, and a stance an operator can hold on purpose (a
    # research programme between spaces).  Never a vacuous one: every
    # assignment is refused by name rather than waved through, and the
    # refusal says the set is empty rather than listing nothing.
    empty = ThemeSet(())
    assert empty.themes == ()
    assert not empty.is_legal("momentum")
    with pytest.raises(IllegalThemeError) as raised:
        empty.assign("momentum")
    assert ILLEGAL_THEME in str(raised.value)
    assert "empty" in str(raised.value)


@pytest.mark.parametrize(
    "bad",
    [
        "Bad Theme",
        "order_flow_imbalance",
        "order flow imbalance",
        "Order.Flow",
        "-leading",
        "trailing-",
        "double--hyphen",
        "2-leading-digit",
        "",
        "   ",
        "momentum!",
        "mömëntum",
        42,
        None,
        ["momentum"],
    ],
)
def test_a_configured_term_that_is_not_a_theme_identifier_is_refused(bad) -> None:
    # The configuration's own face of the refusal: a legal set is how the
    # space is enforced, so a term it cannot judge leaves an assignment
    # unanswerable — refused at configuration, naming the variable, rather
    # than surfacing later as a theme that can be neither assigned nor
    # explained.  Parametrised over the shapes a hand-edited list produces:
    # a spaced phrase, an underscored spelling, a path-like dotted name, a
    # bad separator, a number, a blank and a non-string.
    with pytest.raises(IllegalThemeError) as raised:
        ThemeSet((bad,))
    message = str(raised.value)
    assert ILLEGAL_THEME in message
    assert LEGAL_THEMES_ENV in message  # names the variable to fix


def test_a_set_carrying_one_bad_term_is_refused_whole_and_names_the_rest() -> None:
    # Construction is all-or-nothing, and the refusal counts: ``1 of 3``
    # tells an operator the other two were fine, which a bare "the set is
    # invalid" would not.  The good terms are not silently kept — a set that
    # dropped the bad entry would be a space nobody configured.
    #
    # Each refused entry is asserted by its clause, the same necessity as the
    # batch refusal's: the entries are named one per line under a ``refused:``
    # heading, and the heading's own text names the variable rather than the
    # terms, so the count line and the entry lines are the honest structure.
    with pytest.raises(IllegalThemeError) as raised:
        ThemeSet(("momentum", "Bad Theme", "carry"))
    message = str(raised.value)
    assert "1 of 3" in message
    header, _, entries = message.partition("refused:")
    assert entries.strip().startswith("'Bad Theme'")
    assert "'momentum'" not in entries and "'carry'" not in entries
    assert "momentum" not in header  # the good terms are not named as refused


def test_a_single_string_is_not_a_set_of_themes() -> None:
    # ``ThemeSet("momentum")`` would iterate one theme character by character,
    # admitting ``m`` and refusing ``momentum`` — a set that admits nothing
    # anybody meant.  Refused by name rather than accepted as a sequence, the
    # same hazard :class:`canary.ImportAllowlist` refuses for its own terms.
    with pytest.raises(IllegalThemeError) as raised:
        ThemeSet("momentum")
    assert "character by character" in str(raised.value)
    assert not isinstance(ThemeSet(("momentum",)).themes, str)


def test_a_set_is_frozen() -> None:
    # A set resolved from a deployment's configuration cannot be widened by a
    # caller who kept a reference: the value records a human decision (which
    # spaces this deployment may explore), and a mutable one would let the
    # decision change in memory while the configuration said otherwise.
    from dataclasses import FrozenInstanceError

    configured = ThemeSet(("momentum",))
    with pytest.raises(FrozenInstanceError):
        configured.themes = ("anything",)  # type: ignore[misc]


# -- The question --------------------------------------------------------------------


@pytest.mark.parametrize("spelling", ["momentum", "Momentum", "MOMENTUM", "  momentum  "])
def test_case_and_whitespace_are_insignificant(spelling: str) -> None:
    # The two places a *spelling of the same value* differs, and both fold:
    # they are not a different theme, they are the same theme typed
    # differently, and a family key that split on them would be two families.
    configured = ThemeSet(("momentum",))
    assert configured.is_legal(spelling)
    assert spelling in configured
    assert configured.assign(spelling) == "momentum"


@pytest.mark.parametrize("near_miss", NEAR_MISSES)
def test_a_near_miss_is_not_the_theme(near_miss: str) -> None:
    # The other side of the normalisation, and the one that matters more: an
    # underscore, an inner space, a dot, a doubled or dangling hyphen and a
    # trailing bang are each one keystroke from a legal theme and are each a
    # *different string*.  Refused rather than repaired — a silent repair
    # would store a theme the planner never declared, and the row's
    # ``theme_root`` is what every later grouping reads.
    configured = ThemeSet(("order-flow-imbalance",))
    assert not configured.is_legal(near_miss)
    assert near_miss not in configured
    with pytest.raises(IllegalThemeError):
        configured.assign(near_miss)


@pytest.mark.parametrize("not_a_theme", [None, 42, 3.5, True, ["momentum"], {"a": 1}])
def test_a_value_that_is_not_a_string_is_never_legal(not_a_theme) -> None:
    # ``is_legal`` answers a bool about anything: a caller branching on it
    # must not get an exception for a value that is merely not a theme.  The
    # refusal lives in ``assign``, where the caller asked for an assignment.
    assert DEFAULT_THEME_SET.is_legal(not_a_theme) is False
    assert not_a_theme not in DEFAULT_THEME_SET


def test_membership_is_exact_and_the_set_is_not_a_prefix_match() -> None:
    # ``momentum`` is not in the PRD set (the theme is
    # ``cross-sectional-momentum``) and neither is a prefix of one.  Pinned
    # because the tempting implementation — a startswith/`in` string search —
    # would admit both, and the space would quietly be wider than configured.
    assert "momentum" not in DEFAULT_THEME_SET
    assert "cross" not in DEFAULT_THEME_SET
    assert "cross-sectional" not in DEFAULT_THEME_SET
    assert "cross-sectional-momentum" in DEFAULT_THEME_SET


# -- The refusal ---------------------------------------------------------------------


def test_an_assignable_theme_comes_back_canonical() -> None:
    # The verb's happy path: the theme in, its canonical form out — the value
    # the caller banks and the row carries.
    assert DEFAULT_THEME_SET.assign(" ORDER-FLOW-IMBALANCE ") == "order-flow-imbalance"


def test_a_theme_outside_the_set_is_refused_before_anything_is_planted() -> None:
    # Feature 241's own sentence.  The theme is well formed — ``momentum`` is
    # a theme identifier, just not one this deployment configured — so this is
    # the refusal's *other* face from the configuration's, and the message
    # must therefore name the configured set and the repair rather than
    # complain about the spelling.
    with pytest.raises(IllegalThemeError) as raised:
        DEFAULT_THEME_SET.assign("momentum")
    message = str(raised.value)
    assert message.startswith(ILLEGAL_THEME)
    assert "momentum" in message
    assert "cross-sectional-momentum" in message  # names the space
    assert LEGAL_THEMES_ENV in message  # and how to widen it


def test_a_refusal_is_a_property_of_the_configured_set_not_of_the_theme_alone() -> None:
    # The same string, two deployments, two answers — which is the whole
    # reason the check is against *configuration* rather than a hard-coded
    # list.  PRD §9: the space is the human's highest-value input, so a
    # deployment that declared ``momentum`` as its space assigns it, and the
    # unconfigured one does not.
    assert DEFAULT_THEME_SET.assign("cross-sectional-momentum")
    with pytest.raises(IllegalThemeError):
        DEFAULT_THEME_SET.assign("momentum")
    narrow = ThemeSet(("momentum",))
    assert narrow.assign("momentum") == "momentum"
    with pytest.raises(IllegalThemeError):
        narrow.assign("cross-sectional-momentum")


def test_the_refusal_names_the_column_the_theme_belongs_to() -> None:
    # An operator reading the refusal learns *which* value was wrong and
    # *where* it would have landed — the discipline the nulloracle
    # refusals state for their own fields.
    with pytest.raises(IllegalThemeError) as raised:
        DEFAULT_THEME_SET.assign("not-a-real-space")
    assert "not-a-real-space" in str(raised.value)
    with pytest.raises(IllegalThemeError) as spelled:
        DEFAULT_THEME_SET.assign("Not A Real Space")
    assert THEME_ROOT_COLUMN in str(spelled.value)


def test_every_refusal_begins_with_the_specs_code() -> None:
    # The grep contract: app_spec.xml names ``illegal_theme`` as this
    # refusal's message, every face of the refusal carries it, and a log
    # search for it finds all of them.  Asserted across all four faces —
    # assignment, batch assignment, configuration and a non-string variable —
    # because a code that only some of them carried would be a code an
    # operator could not rely on.
    faces = [
        lambda: DEFAULT_THEME_SET.assign("momentum"),
        lambda: DEFAULT_THEME_SET.assign("not a theme"),
        lambda: DEFAULT_THEME_SET.assign_all(["momentum"]),
        lambda: ThemeSet(("Bad Theme",)),
        lambda: ThemeSet("momentum"),
        lambda: legal_themes_from_env({LEGAL_THEMES_ENV: ["momentum"]}),
        lambda: legal_themes_from_env({LEGAL_THEMES_ENV: "Bad Theme"}),
        lambda: assign_theme("momentum", legal="not a ThemeSet"),
    ]
    for face in faces:
        with pytest.raises(IllegalThemeError) as raised:
            face()
        assert str(raised.value).startswith(ILLEGAL_THEME), face


def test_an_illegal_theme_is_a_discovery_error() -> None:
    # One ``except`` for the caller: the member's base class catches this
    # refusal alongside every other failure of the orchestrator's path, which
    # is the reason the base exists.  And it is not a
    # ``CampaignPlanningError`` — the repair differs (widen the space, or
    # pick a configured theme) from a malformed ask's (re-send a corrected
    # one) — so the two classes are asserted distinct rather than merely both
    # caught.
    from discovery import CampaignPlanningError

    assert issubclass(IllegalThemeError, DiscoveryError)
    assert not issubclass(IllegalThemeError, CampaignPlanningError)
    assert not issubclass(CampaignPlanningError, IllegalThemeError)


# -- The batch -----------------------------------------------------------------------


def test_a_batch_comes_back_canonical_in_the_callers_order() -> None:
    # A grid plan assigns several roots at once (architecture §11.1's
    # ``plan.theme_roots``), and the returned tuple is the caller's order,
    # canonicalised — the planner's own arrangement is not this helper's to
    # change.
    assert DEFAULT_THEME_SET.assign_all(
        ["Volatility-Dispersion", "calendar-events"]
    ) == ("volatility-dispersion", "calendar-events")


def test_a_batch_keeps_duplicates() -> None:
    # How many *distinct* themes a campaign's grid must span is feature 234's
    # law, checked at planning time so the campaign is never created.  A batch
    # helper that quietly deduplicated would be pre-empting a decision this
    # feature was not asked to make, and would hide a plan that fails it.
    assert DEFAULT_THEME_SET.assign_all(
        ["calendar-events", "calendar-events"]
    ) == ("calendar-events", "calendar-events")


def test_a_batch_refuses_collectively_naming_every_offender() -> None:
    # One refusal per batch, not one per root: a planner that learned one
    # illegal theme per attempt would be replanned to learn the rest, and
    # each attempt is a planning call.  The count and both offenders are in
    # the message — the ``screen_imports`` stance applied to this screen.
    #
    # The offenders are matched by their *clause* rather than by substring,
    # and that is necessary rather than fussy: each offender's own refusal
    # names the whole configured space, so a legal theme's name appears in
    # the message too, and only the clause distinguishes "this theme was
    # refused" from "this theme is in the set".
    with pytest.raises(IllegalThemeError) as raised:
        DEFAULT_THEME_SET.assign_all(["calendar-events", "nope", "also-not-a-space"])
    message = str(raised.value)
    assert "2 of 3" in message
    offenders = re.findall(r"the research theme '([^']+)' is outside", message)
    assert sorted(offenders) == ["also-not-a-space", "nope"]
    assert "calendar-events" not in offenders  # the legal root is not refused


def test_a_batch_is_all_or_nothing() -> None:
    # The refusal is raised before any theme is returned, so a caller cannot
    # act on a half-validated batch — the reveal-set discipline feature 217's
    # ``reveal_many`` states for its own batch, applied to a grid's roots.
    good = ["calendar-events", "volatility-dispersion"]
    with pytest.raises(IllegalThemeError):
        DEFAULT_THEME_SET.assign_all([*good, "nope"])
    # No partial value escapes: the call raised, and the same batch without
    # the offender is the one that answers.
    assert DEFAULT_THEME_SET.assign_all(good) == tuple(good)


def test_an_empty_batch_is_an_empty_assignment() -> None:
    # Not a refusal: *which* themes a campaign spans, and how many, is the
    # planning path's law (feature 234), and this helper validates the themes
    # it is handed rather than the composition of the grid.
    assert DEFAULT_THEME_SET.assign_all([]) == ()
    assert DEFAULT_THEME_SET.assign_all(iter(["calendar-events"])) == ("calendar-events",)


def test_a_bare_string_is_not_a_batch_of_themes() -> None:
    # The silent-pass this guard exists for, and it is worth stating exactly
    # because it is *not* caught by the refusal below it: a single-letter
    # theme is a legal theme identifier, so a space of ``{"a", "b", "c"}``
    # read ``"abc"`` as three legal assignments and **reported success** — one
    # mistyped theme silently becoming a three-theme grid, which is the exact
    # shape feature 234's distinctness law is meant to be checked against.
    # Refused by name, the same hazard ``ThemeSet`` refuses for its own terms.
    narrow = ThemeSet(("a", "b", "c"))
    with pytest.raises(IllegalThemeError) as raised:
        narrow.assign_all("abc")
    message = str(raised.value)
    assert message.startswith(ILLEGAL_THEME)
    assert "character by character" in message
    # The same string as three *explicit* themes is a legitimate batch — the
    # guard is about the container, not about short theme names.
    assert narrow.assign_all(["a", "b", "c"]) == ("a", "b", "c")


@pytest.mark.parametrize(
    "not_a_batch",
    [
        None,
        42,
        3.5,
        {"calendar-events": 1},  # a mapping: iterable, hands over its keys
        {"calendar-events", "volatility-dispersion"},  # unordered, hash-seeded
        frozenset({"calendar-events"}),
        b"calendar-events",
    ],
)
def test_a_batch_that_is_not_an_ordered_sequence_is_refused(not_a_batch) -> None:
    # Two hazards in one guard.  ``None`` and a number would raise a bare
    # ``TypeError`` out of this feature's own verb — the caller learns a
    # Python exception name rather than which value was wrong.  A *mapping*
    # or an unordered *set* is worse than that: both iterate, so both would
    # be silently read as a batch of themes (a mapping's keys, a set's
    # hash-seeded order) and could report success for assignments nobody
    # made.  Refused by name, like every other face of this check.
    with pytest.raises(IllegalThemeError) as raised:
        DEFAULT_THEME_SET.assign_all(not_a_batch)
    message = str(raised.value)
    assert message.startswith(ILLEGAL_THEME)
    assert "ordered sequence" in message


# -- The resolution ------------------------------------------------------------------


def test_an_unset_variable_is_the_prd_default() -> None:
    # "Nothing configured" must not read as "anything is legal": that would
    # turn a missing environment variable into an off switch for feature
    # 241's whole sentence.  A deployment that declared nothing still has
    # PRD §9's space — the same stance :func:`canary.allowlist_from_env`
    # takes for §12's import ceiling.
    assert legal_themes_from_env({}) is DEFAULT_THEME_SET
    assert legal_themes_from_env({LEGAL_THEMES_ENV: None}) is DEFAULT_THEME_SET


def test_a_blank_variable_is_the_strictest_space() -> None:
    # Set and blank is a *stance*, not a gap: an operator between research
    # spaces can say "nothing is legal" on purpose, and every assignment is
    # then refused by name.  Deliberately different from unset — the two
    # would be one state if blank were treated as absent.
    for blank in ("", "   ", ",", " , , "):
        resolved = legal_themes_from_env({LEGAL_THEMES_ENV: blank})
        assert resolved.themes == ()
        assert resolved is not DEFAULT_THEME_SET
        with pytest.raises(IllegalThemeError):
            resolved.assign("calendar-events")


def test_a_configured_variable_is_the_space() -> None:
    # The deployment's own space, comma-separated, canonicalised — casing and
    # surrounding whitespace insignificant, duplicates collapsed, and a theme
    # the PRD default carries refused when the deployment narrowed the space
    # away from it.
    resolved = legal_themes_from_env(
        {LEGAL_THEMES_ENV: "Momentum, carry ,MOMENTUM"}
    )
    assert resolved.themes == ("carry", "momentum")
    assert resolved.assign("Momentum") == "momentum"
    with pytest.raises(IllegalThemeError):
        resolved.assign("calendar-events")


def test_a_configured_term_that_is_not_a_theme_identifier_names_the_variable() -> None:
    # The configuration's refusal, through the resolver: it re-raises with the
    # variable's name in front, because an operator who set a bad list needs
    # to know *which* variable to edit — the ``allowlist_from_env`` remedy.
    with pytest.raises(IllegalThemeError) as raised:
        legal_themes_from_env({LEGAL_THEMES_ENV: "momentum,Bad Theme"})
    message = str(raised.value)
    assert message.startswith(ILLEGAL_THEME)
    assert LEGAL_THEMES_ENV in message
    assert "Bad Theme" in message


@pytest.mark.parametrize("not_a_string", [["momentum"], ("momentum",), 42, {"a": 1}])
def test_a_variable_that_is_not_a_string_is_refused(not_a_string) -> None:
    # A mapping a caller assembled by hand, or one loaded from a config format
    # that produced a list where a comma-separated string was meant.  Refused
    # naming what arrived rather than iterated into something surprising.
    with pytest.raises(IllegalThemeError) as raised:
        legal_themes_from_env({LEGAL_THEMES_ENV: not_a_string})
    assert "comma-separated string" in str(raised.value)


def test_the_resolver_reads_the_process_environment_by_default(monkeypatch) -> None:
    # The ``env=None`` seam: with no mapping handed in, the process
    # environment is read — which is how a deployment's configuration is
    # actually reached.  Pinned with monkeypatch so the process is put back.
    monkeypatch.setenv(LEGAL_THEMES_ENV, "process-space")
    assert legal_themes_from_env().themes == ("process-space",)
    monkeypatch.delenv(LEGAL_THEMES_ENV)
    assert legal_themes_from_env() is DEFAULT_THEME_SET


def test_resolving_reads_nothing_at_import_time() -> None:
    # The default is built at import through the resolver's own validation,
    # and the *variable* is read only when a caller asks.  Asserted by
    # behaviour rather than by inspection: an import-time read would have
    # baked whatever the test process's environment held into the module.
    assert DEFAULT_THEME_SET.themes == tuple(sorted(PRD_9_3_THEME_ROOTS))


# -- The module-level verb -----------------------------------------------------------


def test_assign_theme_uses_the_default_when_nothing_is_given() -> None:
    # The verb without a set, over a process that configured nothing: the
    # default space applies, so the module-level spelling and a composed
    # process reach the same configuration.
    assert assign_theme("Calendar-Events") == "calendar-events"
    with pytest.raises(IllegalThemeError):
        assign_theme("momentum")


def test_assign_theme_reads_the_mapping_it_is_handed() -> None:
    # The ``env`` seam, so a test or a script can resolve a deployment's space
    # without touching the process — and the space then *applies*, which is
    # the assertion that matters (a resolution the verb ignored would be
    # configuration that does nothing).
    assert assign_theme("momentum", env={LEGAL_THEMES_ENV: "momentum"}) == "momentum"
    with pytest.raises(IllegalThemeError):
        assign_theme("calendar-events", env={LEGAL_THEMES_ENV: "momentum"})


def test_assign_theme_honours_an_explicit_set_over_the_environment(monkeypatch) -> None:
    # ``legal`` wins over the variable — the same precedence
    # :func:`discovery.create_campaign` gives its ``database_url`` argument
    # over ``DATABASE_URL``, so a caller that holds the set it means does not
    # have to clear the environment to use it.
    monkeypatch.setenv(LEGAL_THEMES_ENV, "process-space")
    assert assign_theme("explicit", legal=ThemeSet(("explicit",))) == "explicit"


@pytest.mark.parametrize(
    "loose", ["momentum", ["momentum"], ("momentum",), 42, {"momentum"}]
)
def test_assign_theme_refuses_a_legal_set_that_is_not_one(loose) -> None:
    # A loose sequence where the validated value was meant: refused rather
    # than re-validated mid-assignment, the stance
    # :func:`canary.screen_imports` takes toward a ceiling that is not an
    # ``ImportAllowlist``.  Every one of these would otherwise surface as a
    # bare ``AttributeError`` from ``.assign`` — a Python exception name
    # rather than a refusal naming the value, which is not something a
    # planner can act on.
    with pytest.raises(IllegalThemeError) as raised:
        assign_theme("momentum", legal=loose)
    message = str(raised.value)
    assert message.startswith(ILLEGAL_THEME)
    assert "must be a ThemeSet" in message


def test_assign_theme_treats_none_as_resolve_it_not_as_a_refusal(monkeypatch) -> None:
    # ``legal=None`` is the documented spelling for "resolve the deployment's
    # space", and it must stay distinct from "a legal set that is not one".
    # Pinned explicitly because a guard written as a bare truthiness check
    # would fold the two together and refuse the *normal* call — the failure
    # mode of the fix that makes the parametrised case above pass.
    monkeypatch.setenv(LEGAL_THEMES_ENV, "momentum")
    assert assign_theme("momentum", legal=None) == "momentum"
    assert assign_theme("momentum", env={LEGAL_THEMES_ENV: "momentum"}) == "momentum"


def test_assign_theme_never_falls_back_to_an_unconstrained_space() -> None:
    # The sharpest reading of the feature's sentence: a deployment whose
    # configuration resolves to *nothing legal* refuses every assignment.
    # A module-level verb that fell back to the PRD default when the
    # configured space came back empty would be an off switch for the check,
    # and this is the case that would find it.
    env = {LEGAL_THEMES_ENV: "   "}
    for theme in PRD_9_3_THEME_ROOTS:
        with pytest.raises(IllegalThemeError):
            assign_theme(theme, env=env)


def test_the_member_exports_the_features_whole_vocabulary() -> None:
    # The member's public surface, asserted as a set so the feature cannot be
    # half-exported: a caller reaching for the verb, the value or the
    # resolver finds all three, and the error class is reachable without
    # importing ``discovery.errors`` directly (the nulloracle seam's
    # discipline about where a refusal is looked up).
    import discovery as member

    for name in (
        "DEFAULT_LEGAL_THEMES",
        "DEFAULT_THEME_SET",
        "ILLEGAL_THEME",
        "LEGAL_THEMES_ENV",
        "THEME_ROOT_COLUMN",
        "ThemeSet",
        "assign_theme",
        "legal_themes_from_env",
        "IllegalThemeError",
    ):
        assert name in member.__all__, name
        assert hasattr(member, name), name
