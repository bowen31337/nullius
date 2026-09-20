"""No wall clock in searched code — feature 139.

These tests pin :mod:`canary._allowlist` — the floor that refuses
``time``, the ``datetime`` clock constructors and the module-level
``random`` stream; the ceiling a deployment configures and cannot point
past the floor; and the screen that judges a submission's imports and
import-bound calls against both. The properties under test are the ones
the module docstring argues:

* the floor is the three entrances §12's row names, refused under every
  configuration — an allowlist that admits one is itself refused;
* the sanctioned spellings pass: a datetime built from arguments, a
  ``random.Random(seed)`` draw with the seed passed in;
* the screen is static and complete — one collective refusal names
  every offender with its line, and what cannot be read (non-string,
  blank, unparseable) is refused rather than waved through, because a
  screen that passed it would be the vacuous green the canary must
  never allow;
* an alias cannot launder the clock — ``from datetime import datetime
  as dt`` still resolves ``dt.now()`` to the refused term;
* the verdict is a value; the refusal is the feature.

The submissions below are real Python source, not mocks: the point of
the feature is that a searched module is refused *as submitted*, so
the passing cases use the deterministic spellings a signal plausibly
needs and the failing cases use the clock reaches the row names.
"""

from __future__ import annotations

import dataclasses

import pytest
from canary import (
    ALLOWED,
    CLOCK_CONSTRUCTORS,
    DEFAULT_IMPORT_ALLOWLIST,
    IMPORT_ALLOWLIST_ENV,
    REFUSED,
    WALL_CLOCK_MODULES,
    CanaryDeviceError,
    CanaryError,
    CanaryImageError,
    CanaryImportError,
    CanaryInferenceError,
    CanaryService,
    ImportAllowlist,
    SearchedImports,
    allowlist_from_env,
    classify_import,
    screen_imports,
)

# -- The floor: one term, one verdict ----------------------------------------


@pytest.mark.parametrize(
    "term",
    [
        "time",
        "time.time",
        "time.monotonic",
        "time.sleep",
        "datetime.now",
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.date.today",
        "random.random",
        "random.uniform",
        "random.choice",
        "random.seed",
        "random.SystemRandom",
    ],
    ids=[
        "time",
        "time-time",
        "time-monotonic",
        "time-sleep",
        "datetime-now",
        "datetime-datetime-now",
        "datetime-datetime-utcnow",
        "datetime-date-today",
        "random-random",
        "random-uniform",
        "random-choice",
        "random-seed",
        "random-systemrandom",
    ],
)
def test_the_floor_refuses_the_three_entrances(term: str) -> None:
    # §12's row names ``time``, ``datetime.now`` and ``random`` without
    # seed. Every spelling of the time module is the clock; ``utcnow``
    # and ``today`` are the same read under the datetime family's other
    # constructors; and the module-level random stream — including its
    # reseeder, and the SystemRandom that ignores seeds by construction —
    # is the unseeded one.
    assert classify_import(term) == REFUSED


@pytest.mark.parametrize(
    "term",
    [
        "math",
        "math.sqrt",
        "decimal",
        "fractions",
        "statistics",
        "itertools",
        "functools",
        "datetime",
        "datetime.datetime",
        "datetime.timedelta",
        "datetime.timezone",
        "random",
        "random.Random",
    ],
    ids=[
        "math",
        "math-sqrt",
        "decimal",
        "fractions",
        "statistics",
        "itertools",
        "functools",
        "datetime",
        "datetime-datetime",
        "datetime-timedelta",
        "datetime-timezone",
        "random",
        "random-Random",
    ],
)
def test_the_floor_passes_the_deterministic_spellings(term: str) -> None:
    # The datetime module stays importable — a datetime built from
    # explicit arguments is a value, not a clock read — and ``random``
    # stays importable because the seeded spelling needs the module.
    assert classify_import(term) == ALLOWED


@pytest.mark.parametrize(
    "term",
    ["", ".sibling", "foo.", "a..b", "random.*", " time", "time ", "1time"],
    ids=[
        "empty",
        "relative",
        "trailing-dot",
        "empty-segment",
        "star",
        "leading-space",
        "trailing-space",
        "leading-digit",
    ],
)
def test_a_term_that_names_no_module_is_refused(term: str) -> None:
    # A relative import, a star import or a malformed spelling names no
    # module an allowlist can judge, and passing it would be reporting
    # clean over a term the screen never checked.
    with pytest.raises(CanaryImportError, match="must be a dotted Python name"):
        classify_import(term)


@pytest.mark.parametrize("term", [None, 12, b"time", ("time",)])
def test_a_non_string_term_is_refused(term: object) -> None:
    # The submission's imports are strings or they are broken; a term
    # that is not a string cannot even be named in a refusal that
    # intends to name it.
    with pytest.raises(CanaryImportError, match="must be a dotted Python name"):
        classify_import(term)


def test_the_floor_constants_state_the_row() -> None:
    # The vocabulary the row names, spelled once: the module refused
    # outright, the datetime constructors that read the clock, and (in
    # the module) the seeded spelling that is the sanctioned one. A test
    # on the constants keeps a refactor from quietly narrowing the row.
    assert WALL_CLOCK_MODULES == frozenset({"time"})
    assert CLOCK_CONSTRUCTORS == frozenset({"now", "utcnow", "today"})


# -- The ceiling: an allowlist that cannot lift the floor ---------------------


def test_the_default_allowlist_is_floor_clean_and_deterministic() -> None:
    # The default ceiling is the deterministic stdlib working set: it
    # covers the numeric and date modules a signal needs, does not
    # cover what a signal has no business importing, and contains no
    # term the floor refuses (it is built through the same validation
    # at import, so it cannot drift past the floor quietly).
    assert DEFAULT_IMPORT_ALLOWLIST.covers("math")
    assert DEFAULT_IMPORT_ALLOWLIST.covers("math.sqrt")
    assert DEFAULT_IMPORT_ALLOWLIST.covers("datetime.datetime")
    assert DEFAULT_IMPORT_ALLOWLIST.covers("random.Random")
    assert not DEFAULT_IMPORT_ALLOWLIST.covers("os")
    assert not DEFAULT_IMPORT_ALLOWLIST.covers("time")
    for term in DEFAULT_IMPORT_ALLOWLIST.terms:
        assert classify_import(term) == ALLOWED


def test_an_allowlist_admitting_the_clock_is_refused() -> None:
    # The allowlist is how the contract is enforced, not a way around
    # it: a configured ceiling that admits ``time`` is refused at
    # construction, naming the entry.
    with pytest.raises(CanaryImportError, match="admits terms the determinism"):
        ImportAllowlist(("math", "time"))


def test_an_allowlist_admitting_any_floor_term_is_refused() -> None:
    # The floor reaches below the module level too: admitting
    # ``random.random`` (the unseeded stream) or ``datetime.now`` (the
    # clock constructor) is the same lift and the same refusal.
    with pytest.raises(CanaryImportError, match="2 of 2 entries refused"):
        ImportAllowlist(("random.random", "datetime.datetime.now"))


def test_the_allowlist_refusal_is_collective() -> None:
    # One refusal names every offending entry — an operator widening
    # the ceiling reads the whole mistake in one message instead of
    # re-running to learn the rest.
    with pytest.raises(CanaryImportError) as refusal:
        ImportAllowlist(("time", "math", "random.uniform", "time.sleep"))
    message = str(refusal.value)
    assert "3 of 4 entries refused" in message
    assert "time:" in message
    assert "random.uniform:" in message
    assert "math" not in message.split("entries refused")[1]


def test_an_allowlist_entry_that_names_no_module_is_refused() -> None:
    # A ceiling entry that is not a dotted name could not say whether a
    # submission stayed inside it.
    with pytest.raises(CanaryImportError, match="must be a dotted Python name"):
        ImportAllowlist(("math", "numpy..linalg"))


def test_an_allowlist_is_a_sequence_not_a_string() -> None:
    # A single string iterates letter by letter — admitting nothing and
    # refusing nothing legibly — so it is refused as a shape, not parsed.
    with pytest.raises(CanaryImportError, match="sequence of dotted module"):
        ImportAllowlist("math, datetime")


def test_an_allowlist_sorts_and_deduplicates() -> None:
    # The value is frozen and ordered, so a verdict or a report filed
    # against it compares stably across submissions.
    allowlist = ImportAllowlist(("random", "math", "math", "datetime"))
    assert allowlist.terms == ("datetime", "math", "random")
    assert len(allowlist) == 3
    assert list(allowlist) == ["datetime", "math", "random"]


def test_an_empty_allowlist_is_the_strictest_ceiling() -> None:
    # Empty is a stance, not a gap: it covers nothing, so every import
    # is refused at the ceiling. It is never vacuously green — the one
    # reading the canary must never allow is a screen that passed what
    # it did not check, and an empty ceiling passes nothing.
    empty = ImportAllowlist(())
    assert len(empty) == 0
    assert not empty.covers("math")


def test_coverage_is_by_prefix() -> None:
    # An entry admits the term itself and everything under it — and
    # only that: a dotted entry does not silently admit its siblings.
    allowlist = ImportAllowlist(("datetime.datetime",))
    assert allowlist.covers("datetime.datetime")
    assert allowlist.covers("datetime.datetime.now")  # the floor still refuses it
    assert not allowlist.covers("datetime.timezone")
    assert "datetime.datetime" in allowlist
    assert "datetime" not in allowlist


def test_an_allowlist_is_frozen() -> None:
    allowlist = ImportAllowlist(("math",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        allowlist.terms = ("time",)  # type: ignore[misc]


# -- The environment spelling ------------------------------------------------


def test_an_unset_variable_is_the_default_allowlist() -> None:
    # A deployment that declared nothing still has a ceiling, exactly as
    # a deployment that declared no device still runs on the CPU — the
    # default is the deterministic working set, not a refusal.
    assert allowlist_from_env({}) == DEFAULT_IMPORT_ALLOWLIST


def test_a_declared_allowlist_is_parsed() -> None:
    resolved = allowlist_from_env({IMPORT_ALLOWLIST_ENV: " os , numpy \n"})
    assert resolved.terms == ("numpy", "os")


def test_a_blank_declaration_is_the_strictest_ceiling() -> None:
    # Set and blank is the strictest stance — nothing allowed — which is
    # a configuration the deployment chose, kept distinct from unset.
    resolved = allowlist_from_env({IMPORT_ALLOWLIST_ENV: " , "})
    assert len(resolved) == 0


def test_a_declared_floor_term_is_refused_naming_the_variable() -> None:
    # Configuring the contract away is the one reading this resolution
    # exists to prevent, and the refusal names the variable so the
    # operator knows which declaration to fix.
    with pytest.raises(CanaryImportError, match=IMPORT_ALLOWLIST_ENV):
        allowlist_from_env({IMPORT_ALLOWLIST_ENV: "math, time"})


def test_a_non_string_declaration_is_refused() -> None:
    with pytest.raises(CanaryImportError, match="comma-separated string"):
        allowlist_from_env({IMPORT_ALLOWLIST_ENV: 12})


def test_the_process_environment_is_the_default_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(IMPORT_ALLOWLIST_ENV, "decimal, fractions")
    assert allowlist_from_env().terms == ("decimal", "fractions")


# -- The screen: the feature's three refusals ---------------------------------


def test_the_time_module_is_refused_at_the_import() -> None:
    with pytest.raises(CanaryImportError) as refusal:
        screen_imports("import time\n")
    assert "line 1" in str(refusal.value)
    assert "wall clock" in str(refusal.value)


@pytest.mark.parametrize(
    "source",
    [
        "from time import time\n",
        "from time import monotonic\n",
        "import time as clock\n",
        "from time import sleep as wait\n",
    ],
    ids=["from-time-time", "from-time-monotonic", "aliased", "aliased-from"],
)
def test_every_spelling_of_the_time_module_is_refused(source: str) -> None:
    # The module is the clock; a renamed binding of it is the same
    # import wearing a different local name.
    with pytest.raises(CanaryImportError, match="wall clock"):
        screen_imports(source)


@pytest.mark.parametrize(
    "source",
    [
        "import datetime\n\n\ndef f() -> int:\n    return datetime.datetime.now().year\n",
        "from datetime import datetime\n\n\ndef f() -> int:\n    return datetime.now().year\n",
        "from datetime import datetime as dt\n\n\ndef f() -> int:\n    return dt.now().year\n",
        "import datetime as dtm\n\n\ndef f() -> int:\n    return dtm.datetime.utcnow().year\n",
        "from datetime import date\n\n\ndef f() -> int:\n    return date.today().year\n",
    ],
    ids=[
        "module-datetime-now",
        "class-now",
        "aliased-class-now",
        "aliased-module-utcnow",
        "date-today",
    ],
)
def test_the_datetime_clock_constructors_are_refused(source: str) -> None:
    # now, utcnow and today — the constructors that read the clock —
    # reached through every binding the imports created. The alias cases
    # are the load-bearing ones: an alias cannot launder the clock.
    with pytest.raises(CanaryImportError) as refusal:
        screen_imports(source)
    message = str(refusal.value)
    assert "wall clock" in message
    assert "line 5" in message


@pytest.mark.parametrize(
    "source",
    [
        "import random\n\n\ndef f() -> float:\n    return random.random()\n",
        "import random\n\n\ndef f() -> float:\n    return random.uniform(0.0, 1.0)\n",
        "import random\n\n\ndef f() -> float:\n    return random.gauss(0.0, 1.0)\n",
        "import random\n\n\ndef f() -> object:\n    return random.SystemRandom()\n",
        "from random import choice\n\n\ndef f(x: list) -> object:\n    return choice(x)\n",
    ],
    ids=[
        "random-random",
        "random-uniform",
        "random-gauss",
        "systemrandom",
        "from-choice",
    ],
)
def test_the_unseeded_random_stream_is_refused(source: str) -> None:
    # The module-level stream is the unseeded one: no seed the search
    # recorded ever reached it, so two runs of one seeded signal draw
    # different values — the divergence the canary exists to catch.
    with pytest.raises(CanaryImportError) as refusal:
        screen_imports(source)
    assert "module-level random stream" in str(refusal.value)


def test_reseeding_the_global_stream_is_still_the_global_stream() -> None:
    # ``random.seed(...)`` does not turn the module-level stream into
    # the seeded spelling — it mutates the one stream no frozen seed
    # owns. §12's sanctioned spelling passes the seed in and constructs
    # ``random.Random(seed)``.
    source = (
        "import random\n"
        "\n"
        "\n"
        "def f() -> float:\n"
        "    random.seed(7)\n"
        "    return random.random()\n"
    )
    with pytest.raises(CanaryImportError, match="module-level random stream"):
        screen_imports(source)


# -- The screen: the sanctioned spellings pass --------------------------------


def test_the_seeded_random_spelling_passes() -> None:
    # §12's own next row: "Seeded RNG | seed passed into signal();
    # stored on the node". The construction is recorded as a cleared
    # call, and the draw on the seeded instance is not the screen's to
    # judge — the seed reached the value.
    source = (
        "import random\n"
        "\n"
        "\n"
        "def signal(seed: int) -> float:\n"
        "    rng = random.Random(seed)\n"
        "    return rng.uniform(0.0, 1.0)\n"
    )
    verdict = screen_imports(source)
    assert verdict.imports == ((1, "random"),)
    assert verdict.calls == ((5, "random.Random"),)


def test_a_datetime_built_from_arguments_passes() -> None:
    source = (
        "from datetime import datetime\n"
        "\n"
        "\n"
        "def stamp(day: int) -> object:\n"
        "    return datetime(2026, 1, day)\n"
    )
    verdict = screen_imports(source)
    assert verdict.imports == ((1, "datetime.datetime"),)
    assert verdict.calls == ((5, "datetime.datetime"),)


def test_plain_numerics_pass_without_a_call_record() -> None:
    # Only the governed families (datetime, random) are resolved below
    # the module level; a math call is the ceiling's business at import
    # time only, so the clean verdict records the import and nothing
    # else.
    source = "import math\n\n\ndef f(x: float) -> float:\n    return math.sqrt(x)\n"
    verdict = screen_imports(source)
    assert verdict.imports == ((1, "math"),)
    assert verdict.calls == ()


def test_import_free_code_screens_clean() -> None:
    # Zero imports is clean, not vacuous: the screen checked the whole
    # tree and the code reaches for nothing. The verdict stays truthy —
    # a completed check is not a failure — which is why the value
    # defines no ``__len__``.
    verdict = screen_imports("def f(x: int) -> int:\n    return x * 2\n")
    assert verdict.imports == ()
    assert verdict.calls == ()
    assert verdict.terms == ()
    assert verdict.modules == ()
    assert bool(verdict) is True


# -- The screen: the ceiling --------------------------------------------------


def test_an_import_outside_the_allowlist_is_refused() -> None:
    # The other half of the mechanism: searched code imports only what
    # the deployment admitted, and a module the allowlist never named
    # is one the determinism contract was never checked against.
    with pytest.raises(CanaryImportError, match="outside the import allowlist"):
        screen_imports("import os\n")


def test_a_wider_ceiling_admits_more_deterministic_modules() -> None:
    # The ceiling is the deployment's choice: the same submission that
    # the default refuses is clean under an allowlist that admits it.
    assert screen_imports("import os\n", ImportAllowlist(("os",))).imports == (
        (1, "os"),
    )


def test_a_narrower_ceiling_refuses_a_floor_clean_import() -> None:
    # The floor is a floor, not an approver: ``math`` is deterministic
    # and still refused when the ceiling does not admit it.
    with pytest.raises(CanaryImportError, match="outside the import allowlist"):
        screen_imports("import math\n", ImportAllowlist(("decimal",)))


def test_a_dotted_ceiling_entry_admits_only_its_own_branch() -> None:
    allowlist = ImportAllowlist(("datetime.datetime",))
    assert screen_imports(
        "from datetime import datetime\n", allowlist
    ).imports == ((1, "datetime.datetime"),)
    with pytest.raises(CanaryImportError, match="outside the import allowlist"):
        screen_imports("from datetime import timezone\n", allowlist)


def test_the_ceiling_cannot_be_lifted_past_the_floor_by_a_wider_entry() -> None:
    # The two checks compose: an allowlist that admits the datetime
    # branch still cannot make the clock constructor pass, because the
    # floor applies per submission regardless of the ceiling.
    allowlist = ImportAllowlist(("datetime",))
    source = "from datetime import datetime\n\n\ndef f() -> int:\n    return datetime.now().year\n"
    with pytest.raises(CanaryImportError, match="wall clock"):
        screen_imports(source, allowlist)


def test_the_allowlist_screen_method_is_the_module_level_screen() -> None:
    # One provenance, two spellings: the composed value's method and
    # the module function are the same check.
    allowlist = ImportAllowlist(("math", "random"))
    source = "import math\nimport random\n\n\ndef f(seed: int) -> float:\n    return random.Random(seed).uniform(0.0, 1.0)\n"
    assert allowlist.screen(source) == screen_imports(source, allowlist)


def test_a_loose_ceiling_is_refused_as_a_shape() -> None:
    # The ceiling is a validated value: a loose sequence handed to the
    # screen is refused rather than re-validated mid-refusal, because a
    # ceiling the floor never checked is the lift the floor exists to
    # prevent.
    with pytest.raises(CanaryImportError, match="must be an ImportAllowlist"):
        screen_imports("import math\n", ["math"])  # type: ignore[arg-type]


# -- The screen: completeness and the vacuity guards --------------------------


def test_the_refusal_names_every_offender_in_one_error() -> None:
    # A screen that reported only the first would be resubmitted to
    # learn the rest; the author of searched code reads the whole
    # refusal in one message.
    source = (
        "import math\n"
        "import time\n"
        "import random\n"
        "\n"
        "\n"
        "def f() -> float:\n"
        "    random.seed(3)\n"
        "    return random.random()\n"
    )
    with pytest.raises(CanaryImportError) as refusal:
        screen_imports(source)
    message = str(refusal.value)
    # The import (line 2), the reseed of the global stream (line 7) and
    # the draw from it (line 8) are all named — the reseed is a call
    # too, and it is refused for the same reason as the draw.
    assert "3 of 5 imports and calls refused" in message
    assert "line 2" in message
    assert "line 7" in message
    assert "line 8" in message


@pytest.mark.parametrize(
    "source", [None, 12, b"import time"], ids=["none", "int", "bytes"]
)
def test_non_string_source_is_refused(source: object) -> None:
    # The screen cannot admit what it cannot read.
    with pytest.raises(CanaryImportError, match="non-empty string"):
        screen_imports(source)


@pytest.mark.parametrize("source", ["", "   \n\t"], ids=["empty", "blank"])
def test_blank_source_is_refused(source: str) -> None:
    with pytest.raises(CanaryImportError, match="blank source"):
        screen_imports(source)


def test_unparseable_source_is_refused() -> None:
    # A submission that does not parse is refused rather than waved
    # through — passing it would be the vacuous green the nightly
    # canary must never allow, and the refusal names where parsing
    # broke so the author can fix it.
    with pytest.raises(CanaryImportError, match="does not parse") as refusal:
        screen_imports("def (:\n")
    assert "line 1" in str(refusal.value)


def test_a_relative_import_is_refused() -> None:
    # Searched code is one submitted module, not a package with
    # siblings the search froze — a relative import reaches into
    # modules no allowlist ever judged.
    with pytest.raises(CanaryImportError, match="must be a dotted Python name"):
        screen_imports("from . import sibling\n")


def test_a_star_import_is_refused() -> None:
    # A star import binds everything at once — the one term no
    # allowlist can judge.
    with pytest.raises(CanaryImportError, match="must be a dotted Python name"):
        screen_imports("from random import *\n")


# -- The verdict value --------------------------------------------------------


def test_the_verdict_records_lines_terms_and_roots() -> None:
    source = (
        "import random\n"
        "import math\n"
        "from datetime import datetime\n"
        "\n"
        "\n"
        "def f(seed: int, day: int) -> tuple:\n"
        "    return math.sqrt(2.0), datetime(2026, 1, day), random.Random(seed)\n"
    )
    verdict = screen_imports(source)
    assert verdict.imports == (
        (1, "random"),
        (2, "math"),
        (3, "datetime.datetime"),
    )
    assert verdict.terms == ("random", "math", "datetime.datetime")
    assert verdict.modules == ("datetime", "math", "random")


def test_the_verdict_is_frozen() -> None:
    verdict = screen_imports("import math\n")
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.imports = ((1, "time"),)  # type: ignore[misc]


@pytest.mark.parametrize(
    "imports",
    [((0, "math"),), ((1, ""),), ((1, "math", "extra"),)],
    ids=["zero-line", "blank-term", "not-a-pair"],
)
def test_a_verdict_cannot_be_built_from_malformed_entries(
    imports: tuple[tuple, ...],
) -> None:
    # A verdict is a statement about code a screen actually read; an
    # entry that cannot say where and what was checked cannot be filed
    # against a submission.
    with pytest.raises(CanaryImportError, match=r"\(line, term\) pairs"):
        SearchedImports(imports, ())


# -- The taxonomy -------------------------------------------------------------


def test_the_import_refusal_is_its_own_contract_class() -> None:
    # A caller halting dreaming needs to know *which* line of §12
    # broke, because the repair differs — and the repair for searched
    # code that reads the clock is to fix the submission, not to
    # re-pin an image, remove a GPU or materialize an inference.
    assert issubclass(CanaryImportError, CanaryError)
    assert CanaryImportError is not CanaryImageError
    assert CanaryImportError is not CanaryDeviceError
    assert CanaryImportError is not CanaryInferenceError


def test_a_single_except_catch_still_catches_it() -> None:
    with pytest.raises(CanaryError):
        screen_imports("import time\n")


# -- The service seam ---------------------------------------------------------


def test_the_service_resolves_the_default_allowlist_lazily() -> None:
    # Composition never depends on the allowlist configuration: the
    # service constructs bare and resolves the ceiling on first use.
    service = CanaryService()
    assert service.allowlist == DEFAULT_IMPORT_ALLOWLIST


def test_the_service_caches_the_resolved_allowlist() -> None:
    # A deployment that re-read its allowlist mid-run could screen two
    # submissions under two different ceilings and never know which
    # one spoke.
    service = CanaryService()
    assert service.allowlist is service.allowlist


def test_the_service_reads_the_environment_it_was_given() -> None:
    # The mapping seam: a test or an operator hands the service an
    # environment and both spellings of the resolution read it.
    service = CanaryService(env={IMPORT_ALLOWLIST_ENV: "numpy, polars"})
    assert service.allowlist.terms == ("numpy", "polars")


def test_the_service_refuses_a_floor_term_in_its_environment() -> None:
    service = CanaryService(env={IMPORT_ALLOWLIST_ENV: "time"})
    with pytest.raises(CanaryImportError, match=IMPORT_ALLOWLIST_ENV):
        _ = service.allowlist


def test_the_service_screens_through_the_resolved_ceiling() -> None:
    service = CanaryService(env={IMPORT_ALLOWLIST_ENV: "numpy"})
    verdict = service.allowlist.screen("import numpy\n")
    assert verdict.imports == ((1, "numpy"),)
    with pytest.raises(CanaryImportError, match="outside the import allowlist"):
        service.allowlist.screen("import math\n")


def test_the_composed_service_carries_the_allowlist_property() -> None:
    # The factory's scan composes the canary on every create_app(),
    # over environments with no allowlist declared — so the property
    # must exist without resolving anything, and resolve to the
    # default when it does. Asserted on the class first (the property,
    # not a resolution), then behaviourally — comparing terms, not the
    # value, because the loader imports this member under a synthetic
    # name and isinstance/== cannot hold across the two copies (the
    # registration-contract tests document the same trap).
    from app.module_loader import create_app

    component = create_app().get("canary")
    assert isinstance(vars(type(component)).get("allowlist"), property)
    assert component.allowlist.terms == DEFAULT_IMPORT_ALLOWLIST.terms


def test_the_allowlist_property_does_not_break_composition() -> None:
    # The load-bearing property for the factory: a deployment whose
    # allowlist variable is unset (or whose environment is bare)
    # composes, and the refusal — when the variable names a floor term
    # — lands at first use, not at construction.
    from app.module_loader import create_app

    app = create_app()
    assert app.get("canary") is not None
