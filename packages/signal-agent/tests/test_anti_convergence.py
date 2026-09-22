"""Feature 210 — the explicit anti-convergence clause, applied.

app_spec.xml: *"Agent applies an explicit anti-convergence clause, so a tree
never collapses into 400 parameter tweaks of one indicator."*
docs/alpha-engine-prd.md §C3 supplies the clause — the discovery agent adapts
the paper's Listing 1 exploration prompt *"nearly verbatim, keeping in
particular: ... The explicit anti-convergence clause.  Without it, a discovery
tree collapses into 400 parameter tweaks of one indicator."* —
docs/nullius-tech-architecture.md §14.1 supplies why nothing else catches the
failure: *"A bad proposal is caught by the evaluator at a cost of one trial
charge.  A converged tree is not caught by anything.  At roots, a weak model's
failure mode is proposing the 400th variant of one indicator — every node
scores plausibly, the budget is fully consumed, and nothing in the pipeline
detects it."*

Each claim in the feature's sentence is tested separately, because a law that
satisfied any one of them without the others would be a different and worse
feature:

* **explicit** — the clause is a committed artifact with a compiler that
  refuses what it cannot read, not a sentence in a prompt template.  *Explicit*
  is a fact about a file in this repository;
* **applies** — the clause is *used*, not merely held.  Two screens, tested in
  their own groups: the campaign's authoring prompt must carry the clause
  verbatim, and each proposal's structure must not be one the campaign already
  holds;
* **a tree never collapses** — the applied half is per *campaign*, because PRD
  §9 makes the campaign the unit of search, and an empty comparison set refuses
  nothing;
* **into 400 parameter tweaks of one indicator** — the comparison is on the
  proposal's structure *with every numeric literal erased*.  This is the axis
  no other law in this member sees, and the group that tests it is the
  feature's centre of gravity.

Three boundaries get their own groups, because each is a place a plausible
implementation would be wrong:

* **the skeleton is the structure, not the text** — formatting, comments,
  docstrings and keyword-argument order are spelling; a new term, another
  accessor or a different transformation are structure.  Both directions are
  tested, because a gate that merged too much would refuse genuinely novel
  proposals and a gate that merged too little would admit the 400th variant;
* **``bool`` is not a parameter** — ``True``/``False`` select a branch rather
  than scale one, and Python's ``bool`` being an ``int`` subclass is exactly
  the trap that would erase them by accident;
* **the skeleton is not a score** — the digest is a key compared for equality,
  never a magnitude compared for distance.  Asserted on the type, because an
  orderable derived value is the first step toward a priced one.

The refusals are asserted on the *returned value* rather than with
``pytest.raises``, because the law answers as a value: ``admit`` returns an
:class:`AntiConvergenceVerdict` and only ``require`` raises.  That split is
tested explicitly, as the one seam where a refusal becomes an exception.

The last group is the one asymmetry with feature 213, and it is load-bearing:
feature 213's builder falls back to an empty denylist, which fails **open** —
it admits every proposal.  Feature 210's *applied* half fails the same way for
the same reason, but its *clause* half fails **closed**, because the screen is
a substring test and the empty string is a substring of every string: a gate
whose own clause is unreadable would otherwise certify every prompt.  Both
polarities are asserted, on the same gate, because reading either one as the
other is the mistake the module docstring names.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from signal_agent import (
    ANTI_CONVERGENCE_POLICY_KIND,
    CLAUSE_ABSENT_CODE,
    COMMITTED_ANTI_CONVERGENCE,
    NOT_A_PROPOSAL_CODE,
    NOVEL_CODE,
    PARAMETER_TWEAK_CODE,
    AntiConvergenceClause,
    AntiConvergenceClauseError,
    AntiConvergenceError,
    AntiConvergenceGate,
    AntiConvergenceReason,
    anti_convergence_gate,
    committed_anti_convergence,
    compile_anti_convergence,
    load_anti_convergence,
    proposal_skeleton,
    skeleton_digest,
)

#: The feature's headline case, spelled in the smallest source that shows it:
#: one indicator, one accessor, one lookback.  ``HELD`` is what the campaign
#: already holds; ``TWEAK`` is the 400th variant §14.1 describes.  They differ
#: in exactly one character — the literal — which is the point.
HELD = "def signal(ctx, seed):\n    return ctx.close.rolling_mean(20)\n"
TWEAK = "def signal(ctx, seed):\n    return ctx.close.rolling_mean(60)\n"

#: A proposal that is *not* a tweak: the same indicator with another term.  The
#: tree changed rather than a leaf, so this must be admitted even though it
#: shares every identifier with ``HELD``.
NOVEL = (
    "def signal(ctx, seed):\n"
    "    return ctx.close.rolling_mean(20) - ctx.volume.rolling_mean(20)\n"
)


# -- the committed clause: *explicit* is a fact about a file ------------------


def test_the_committed_clause_is_the_document_the_feature_names() -> None:
    clause = load_anti_convergence(COMMITTED_ANTI_CONVERGENCE)
    assert clause.kind == ANTI_CONVERGENCE_POLICY_KIND == (
        "signal-agent-anti-convergence"
    )
    assert clause.slug == "anti-convergence"


def test_the_committed_clause_is_named_and_titled() -> None:
    # The read side a log line and a dashboard both want.  The title is the
    # document's own wording rather than a second description written in code,
    # which is why it is asserted as a phrase rather than by equality with a
    # literal this file would have to keep in sync with the artifact.
    clause = committed_anti_convergence()
    assert clause.title().strip()
    assert "anti-convergence" in clause.title().lower()
    assert len(clause) == len(clause.text()) > 0


def test_the_committed_clause_says_what_the_feature_says() -> None:
    # PRD §C3 keeps this clause in the agent's *defining* prompt, and §14.1
    # names the failure it prevents.  Both are quoted into the artifact's own
    # comment block, and the clause itself must carry the constraint rather
    # than only its rationale: what the agent is forbidden to do is stated as a
    # negative ("do not propose another variant ..."), which is the form that
    # cannot become guidance.
    text = committed_anti_convergence().text()
    assert "400 parameter tweaks" in text
    assert "do not propose" in text.lower()
    # And it names the repair, because a refusal with no repair is a wall: the
    # clause tells the agent what an admissible proposal looks like instead.
    assert "structural change" in text.lower()


def test_the_committed_clause_carries_no_history_derived_direction() -> None:
    # Feature 208's refusal, held from this side.  The clause is the one piece
    # of prose this member compiles, and it must stay on the right side of PRD
    # §C3 / §14.1's anti-guidance line: a *negative constraint* carrying no
    # direction distilled from campaign history.  A clause that named a
    # mechanism, an indicator or a lookback to search would be guidance wearing
    # a prohibition's clothes, and this asserts it names none.
    lowered = committed_anti_convergence().text().lower()
    for direction in (
        "momentum",
        "reversal",
        "order-flow",
        "roll",
        "lookback of",
        "prefer",
        "try ",
    ):
        assert direction not in lowered, direction


def test_the_committed_clause_survives_a_round_trip_through_the_compiler() -> None:
    # Reading the file and compiling the parsed document must agree, because a
    # caller that recompiled a drift in memory would otherwise get a different
    # clause from the one on disk.
    on_disk = load_anti_convergence(COMMITTED_ANTI_CONVERGENCE)
    in_memory = compile_anti_convergence(
        json.loads(Path(COMMITTED_ANTI_CONVERGENCE).read_text(encoding="utf-8"))
    )
    assert on_disk.text() == in_memory.text()
    assert on_disk.title() == in_memory.title()
    assert on_disk.slug == in_memory.slug


# -- the compiler refuses what it cannot read --------------------------------


def _document(**overrides: object) -> dict:
    """A minimal valid document, with ``overrides`` applied over its clause."""
    clause: dict = {
        "slug": "anti-convergence",
        "title": "The explicit anti-convergence clause",
        "text": "Do not propose another variant of a mechanism this tree holds.",
    }
    for key, value in overrides.items():
        if key == "clause":
            clause = value  # type: ignore[assignment]
        else:
            clause[key] = value
    return {"policy": ANTI_CONVERGENCE_POLICY_KIND, "clause": clause}


def test_a_minimal_document_compiles() -> None:
    clause = compile_anti_convergence(_document())
    assert clause.slug == "anti-convergence"
    assert clause.text().startswith("Do not propose")


@pytest.mark.parametrize(
    "document",
    [
        pytest.param([], id="not-a-mapping"),
        pytest.param("policy", id="a-string"),
        pytest.param(None, id="none"),
    ],
)
def test_a_document_that_is_not_a_mapping_is_refused(document: object) -> None:
    # A compiler that guessed at the meaning of a stray list or string would be
    # writing policy rather than reading it.
    with pytest.raises(AntiConvergenceClauseError):
        compile_anti_convergence(document)


@pytest.mark.parametrize(
    "document",
    [
        pytest.param({"clause": {}}, id="no-marker"),
        pytest.param({"policy": "", "clause": {}}, id="empty-marker"),
        pytest.param({"policy": 7, "clause": {}}, id="non-string-marker"),
        pytest.param(
            {"policy": "signal-agent-legal-themes", "clause": {}},
            id="another-features-marker",
        ),
    ],
)
def test_a_document_that_does_not_declare_itself_is_refused(document: dict) -> None:
    # A stray JSON file carrying a ``clause`` key is not this configuration —
    # and the last case is the load-bearing one, because this member ships
    # three committed artifacts and a copy-paste between two of them is exactly
    # how one would end up read as another.
    # Two sentences for four cases, and both name what is missing: an *absent*
    # or blank marker is reported as the 'policy' field, and a marker that is
    # present but *wrong* is reported as the declaration it should have made.
    with pytest.raises(AntiConvergenceClauseError, match="policy|declare itself"):
        compile_anti_convergence(document)


def test_another_features_marker_is_refused_by_name() -> None:
    # The same case asserted on the message rather than the class, because the
    # refusal's *value* here is naming which document was picked up: an
    # operator reading "signal-agent-legal-themes" in a clause refusal knows
    # immediately which file was copied.
    with pytest.raises(AntiConvergenceClauseError) as caught:
        compile_anti_convergence({"policy": "signal-agent-legal-themes", "clause": {}})
    assert "signal-agent-legal-themes" in str(caught.value)
    assert ANTI_CONVERGENCE_POLICY_KIND in str(caught.value)


@pytest.mark.parametrize(
    "clause",
    [
        pytest.param([], id="clause-is-a-list"),
        pytest.param("text", id="clause-is-a-string"),
        pytest.param(None, id="clause-is-none"),
        pytest.param({"slug": "anti-convergence", "title": "t"}, id="no-text"),
        pytest.param(
            {"slug": "anti-convergence", "title": "t", "text": ""},
            id="blank-text",
        ),
        pytest.param(
            {"slug": "anti-convergence", "title": "t", "text": "   "},
            id="whitespace-text",
        ),
    ],
)
def test_a_clause_whose_text_names_nothing_is_refused(clause: object) -> None:
    # The one refusal this document has that features 212's and 213's sets
    # share only by analogy: a clause with blank text is refused, because a
    # prompt screened against it would be screened against nothing — and the
    # *screen* is what makes that dangerous here rather than merely useless.
    with pytest.raises(AntiConvergenceClauseError):
        compile_anti_convergence(_document(clause=clause))


@pytest.mark.parametrize(
    "slug",
    [
        pytest.param("Anti-Convergence", id="uppercase"),
        pytest.param("anti_convergence", id="underscore"),
        pytest.param("-anti", id="leading-hyphen"),
        pytest.param("anti-", id="trailing-hyphen"),
        pytest.param("anti--convergence", id="double-hyphen"),
        pytest.param("anticonvergence1", id="ok"),
    ],
)
def test_a_slug_outside_the_shared_grammar_is_refused(slug: str) -> None:
    # The grammar is feature 212's, reached through ``_themes`` rather than
    # respelled, so the member's committed artifacts cannot drift apart on what
    # a slug is.  ``anticonvergence1`` is in the parametrisation as the control:
    # it is *unusual* but legal, and a grammar tightened here rather than
    # shared would refuse it.
    if slug == "anticonvergence1":
        assert compile_anti_convergence(_document(slug=slug)).slug == slug
        return
    with pytest.raises(AntiConvergenceClauseError, match="slug"):
        compile_anti_convergence(_document(slug=slug))


@pytest.mark.parametrize(
    "field",
    ["title", "slug"],
)
def test_a_clause_missing_a_required_field_is_refused(field: str) -> None:
    document = _document()
    del document["clause"][field]
    with pytest.raises(AntiConvergenceClauseError, match=field):
        compile_anti_convergence(document)


def test_an_unreadable_file_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(AntiConvergenceClauseError, match="could not read"):
        load_anti_convergence(tmp_path / "does-not-exist.json")


def test_a_file_that_is_not_json_is_refused_by_name(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(AntiConvergenceClauseError, match="not valid JSON"):
        load_anti_convergence(path)


def test_a_drifted_file_is_refused_exactly_as_a_drifted_document_is(
    tmp_path: Path,
) -> None:
    # The committed artifact is not privileged: a drift written to disk is
    # refused by the same law as one compiled in memory, so there is no path
    # by which a file reaches a gate without passing the compiler.
    path = tmp_path / "drifted.json"
    path.write_text(json.dumps(_document(text="   ")), encoding="utf-8")
    with pytest.raises(AntiConvergenceClauseError):
        load_anti_convergence(path)


# -- the clause half: the prompt must carry it -------------------------------


def test_a_prompt_carrying_the_clause_verbatim_is_certified(
    clause_gate: AntiConvergenceGate,
) -> None:
    prompt = "You are a discovery agent.\n\n" + clause_gate.text() + "\n\nBegin."
    assert clause_gate.carries(prompt) is True
    assert clause_gate.require_in(prompt) == prompt


def test_a_prompt_that_paraphrases_the_clause_is_refused(
    clause_gate: AntiConvergenceGate,
) -> None:
    # The screen is a substring test on the clause verbatim, and this is why:
    # a deployment that *rewords* the clause has a different clause and should
    # commit that one; a deployment that paraphrases has a prompt that does not
    # carry the clause it claims to.  A similarity score here would accept this
    # prompt, and PRD §C3's "nearly verbatim" would become an honour system.
    prompt = clause_gate.text()[:-40] + "Try to be original."
    assert clause_gate.carries(prompt) is False
    with pytest.raises(AntiConvergenceClauseError):
        clause_gate.require_in(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(None, id="none"),
        pytest.param(7, id="an-int"),
        pytest.param(b"bytes", id="bytes"),
        pytest.param("", id="empty"),
        pytest.param("   \n  ", id="whitespace"),
        pytest.param("a prompt that says nothing about convergence", id="unrelated"),
    ],
)
def test_a_prompt_that_cannot_carry_the_clause_is_refused(
    clause_gate: AntiConvergenceGate, prompt: object
) -> None:
    # One refusal for all of these, because the repair is one repair: put the
    # committed clause in the prompt.  A non-string is a caller's bug and an
    # absent clause is an author's, and both are answered by the same file.
    assert clause_gate.carries(prompt) is False
    with pytest.raises(AntiConvergenceClauseError):
        clause_gate.require_in(prompt)


def test_the_prompt_refusal_opens_with_the_clause_absent_code(
    clause_gate: AntiConvergenceGate,
) -> None:
    # A deployment fault must not read as a research finding: the two halve
    # refusals of this feature open with different codes, so an operator
    # grepping a campaign log for a converged tree does not find a template.
    with pytest.raises(AntiConvergenceClauseError) as caught:
        clause_gate.require_in("nothing")
    assert str(caught.value).startswith(CLAUSE_ABSENT_CODE)
    assert "§14.1" in str(caught.value)


def test_require_in_returns_the_prompt_unmodified(
    clause_gate: AntiConvergenceGate,
) -> None:
    # This law checks the prompt; it does not author it.  A gate that inserted
    # the clause would be writing the campaign's prompt, and the deployment
    # would have no way to review what its agent was actually told.
    prompt = clause_gate.text() + "\n\nSuffix the campaign added."
    assert clause_gate.require_in(prompt) == prompt


def test_the_clause_error_is_not_a_source_error() -> None:
    # Deployment-level, like feature 212's ThemeSetError and feature 213's
    # DeadTerritorySetError: no agent action repairs a drifted document, and a
    # prompt that dropped the clause is fixed by editing the prompt rather than
    # by re-prompting the model.  A campaign driver's retry logic turns on
    # exactly this distinction.
    from signal_agent import AgentSourceError, SignalAgentError

    assert issubclass(AntiConvergenceClauseError, SignalAgentError)
    assert not issubclass(AntiConvergenceClauseError, AgentSourceError)


def test_the_proposal_error_is_a_source_error() -> None:
    # Proposal-level, and deliberately under the source contract: the subject
    # is what the agent proposed, the repair is the same re-prompt features
    # 212's and 213's refusals ask for, and a caller that already writes
    # ``except AgentSourceError`` must not lose *this* refusal — the one that
    # fires most often in practice.
    from signal_agent import AgentSourceError

    assert issubclass(AntiConvergenceError, AgentSourceError)


def test_the_clause_error_is_a_sibling_of_the_other_two_set_errors() -> None:
    # Three committed artifacts, three configuration errors, none a subclass of
    # another: an operator reading the refusal must know which file drifted.
    from signal_agent import DeadTerritorySetError, ThemeSetError

    for other in (ThemeSetError, DeadTerritorySetError):
        assert not issubclass(AntiConvergenceClauseError, other)
        assert not issubclass(other, AntiConvergenceClauseError)


# -- the skeleton: the structure, with the numbers erased --------------------


def test_two_lookbacks_of_one_indicator_share_a_skeleton() -> None:
    # The feature's headline, at the level the comparison actually runs on.
    assert proposal_skeleton(HELD) == proposal_skeleton(TWEAK)
    assert skeleton_digest(HELD) == skeleton_digest(TWEAK)


def test_the_erasure_covers_floats_and_complex_too() -> None:
    # ``int`` is the shape §14.1's lookbacks take, but a threshold, a scaling
    # constant or a multiplier is a float and a signal-period expression can be
    # complex.  An eraser that handled only ``int`` would miss the majority of
    # the parameters a quant model actually tweaks.
    assert proposal_skeleton("x = 1") == proposal_skeleton("x = 1.5")
    assert proposal_skeleton("x = 1") == proposal_skeleton("x = 2j")
    assert proposal_skeleton("x = 10 ** 9") == proposal_skeleton("x = 10 ** 3")


def test_the_erasure_reaches_nested_and_negative_literals() -> None:
    # A literal buried in a call argument, a subscript, a default or a unary
    # minus is still a literal.  ``-20`` parses as ``UnaryOp(USub, Constant)``,
    # so an eraser that only looked at ``Constant`` nodes would leave the sign
    # behind — harmless here, but the case is asserted because it is the one a
    # hand-rolled walk gets wrong.
    assert proposal_skeleton("f(g(1), h[2])") == proposal_skeleton("f(g(9), h[7])")
    assert proposal_skeleton("x = -1") == proposal_skeleton("x = -9")
    assert proposal_skeleton("def f(n=1): pass") == proposal_skeleton(
        "def f(n=99): pass"
    )


def test_a_boolean_is_not_erased() -> None:
    # ``bool`` is an ``int`` subclass in Python, so the naive walk erases it by
    # accident — and that would be wrong: a flag selects a *branch* rather than
    # scaling one, so flipping it is a structural edit.  Erasing it would make
    # ``x if flag else y`` and ``y if flag else x`` one structure, a false merge
    # on the side that refuses, which is worse than a false split.
    assert proposal_skeleton("x = True") != proposal_skeleton("x = False")
    assert proposal_skeleton("f(flag=True)") != proposal_skeleton("f(flag=False)")


def test_a_docstring_is_not_structure() -> None:
    # Two agents describing one mechanism in different words must not be two
    # structures.  The rewrite removes docstrings rather than inspecting them,
    # which also keeps the screen from reading prose — feature 208's concern.
    described = (
        "def signal(ctx, seed):\n"
        '    """A twenty-day close rolling mean."""\n'
        "    return ctx.close.rolling_mean(20)\n"
    )
    assert proposal_skeleton(described) == proposal_skeleton(HELD)


def test_formatting_comments_and_quote_style_are_not_structure() -> None:
    # The normalisation through ``ast.unparse`` is what makes two spellings of
    # one mechanism compare equal — and a proposal a model reformats between
    # attempts is the common case, not the exotic one.  The reformatting here
    # is deliberately confined to *spelling*: the line breaks, the comment and
    # the docstring all move, and the expression tree does not.
    verbose = (
        "def signal(ctx, seed):\n"
        "    # a comment the agent added on the second attempt\n"
        '    """And a docstring it added too."""\n'
        "    return ctx.close.rolling_mean(\n"
        "        20,\n"
        "    )\n"
    )
    assert proposal_skeleton(verbose) == proposal_skeleton(HELD)


def test_hoisting_a_literal_into_a_named_binding_is_structure() -> None:
    # The boundary of the erasure, stated as a test because it is a *decision*
    # rather than an accident.  ``window = 20`` followed by
    # ``rolling_mean(window)`` parses to a different tree from
    # ``rolling_mean(20)``: the hoist adds a statement and a name binding, and
    # the law does not see through it.  That is the right side to err on — the
    # gate refuses *less* than a more aggressive normalisation would, and a
    # false split costs one admitted proposal while a false merge refuses a
    # genuinely novel one, which is §14.1's badge of honour.  What it does mean
    # is that a model that hoists its constants between attempts is not caught
    # by this screen at that step; feature 211's stated-mechanism check and the
    # budget still are.
    hoisted = (
        "def signal(ctx, seed):\n"
        "    window = 20\n"
        "    return ctx.close.rolling_mean(window)\n"
    )
    assert proposal_skeleton(hoisted) != proposal_skeleton(HELD)
    # But the hoisted form is *itself* a structure, so two hoisted variants with
    # different constants are caught against each other — which is what stops
    # the hoist from being an escape hatch.
    other = (
        "def signal(ctx, seed):\n"
        "    window = 60\n"
        "    return ctx.close.rolling_mean(window)\n"
    )
    assert proposal_skeleton(hoisted) == proposal_skeleton(other)


def test_named_keyword_order_is_not_structure() -> None:
    assert proposal_skeleton("f(a=1, b=2)") == proposal_skeleton("f(b=2, a=1)")


def test_a_keyword_unpacking_pins_its_position() -> None:
    # The one case the sort deliberately does not touch: where ``**kw`` sits
    # relative to the named keywords decides which of them may be overridden,
    # so reordering there would be editing the proposal rather than normalising
    # its spelling.
    assert proposal_skeleton("f(a=1, **kw)") != proposal_skeleton("f(**kw, a=1)")


def test_a_new_term_is_structure() -> None:
    # The other direction, and the one a too-eager screen fails: this proposal
    # shares every identifier with ``HELD`` and adds a term, so the tree changed
    # rather than a leaf.  A gate built on a token multiset or on a similarity
    # score would refuse it, and §14.1 gives depth the job of making exactly
    # this kind of targeted change.
    assert proposal_skeleton(NOVEL) != proposal_skeleton(HELD)
    assert skeleton_digest(NOVEL) != skeleton_digest(HELD)


def test_a_different_transformation_is_structure() -> None:
    assert proposal_skeleton(HELD) != proposal_skeleton(
        "def signal(ctx, seed):\n    return ctx.close.ewm_mean(20)\n"
    )


def test_a_different_accessor_is_structure() -> None:
    assert proposal_skeleton(HELD) != proposal_skeleton(
        "def signal(ctx, seed):\n    return ctx.volume.rolling_mean(20)\n"
    )


def test_the_digest_is_a_key_not_a_magnitude() -> None:
    # Compared for equality by every caller, never for distance.  The type is
    # the claim: a numeric digest is orderable, and an orderable derived value
    # is the first step toward a scored one — which would make this law a
    # novelty *metric* rather than a gate.
    digest = skeleton_digest(HELD)
    assert isinstance(digest, str)
    assert digest == digest.lower()
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    assert skeleton_digest(HELD) == skeleton_digest(HELD)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(None, id="none"),
        pytest.param(7, id="an-int"),
        pytest.param(b"def signal(ctx, seed): pass", id="bytes"),
        pytest.param("", id="empty"),
        pytest.param("   \n ", id="whitespace"),
    ],
)
def test_a_skeleton_needs_source_text(source: object) -> None:
    with pytest.raises(AntiConvergenceError):
        proposal_skeleton(source)


def test_a_source_that_does_not_parse_raises_rather_than_returning_a_sentinel() -> None:
    # The alternative — a sentinel skeleton — would make every unparseable
    # proposal compare equal to every other one *and to itself*, which is the
    # collapse this gate exists to detect arriving as its own answer.  Feature
    # 205's adopt runs first; a syntax error here is a caller that skipped it.
    with pytest.raises(AntiConvergenceError, match="does not parse"):
        proposal_skeleton("def signal(ctx, seed)\n    return 1\n")


# -- the applied half: a tweak is refused before the node opens --------------


def test_a_tweak_of_a_held_proposal_is_refused(
    clause_gate: AntiConvergenceGate,
) -> None:
    verdict = clause_gate.admit(TWEAK, held=[("n1", HELD)])
    assert verdict.admitted is False
    assert verdict.reason is AntiConvergenceReason.PARAMETER_TWEAK
    assert verdict.digest == skeleton_digest(HELD)
    assert verdict.duplicates == (("n1", skeleton_digest(HELD)),)


def test_a_novel_proposal_is_admitted(clause_gate: AntiConvergenceGate) -> None:
    verdict = clause_gate.admit(NOVEL, held=[("n1", HELD)])
    assert verdict.admitted is True
    assert verdict.reason is AntiConvergenceReason.NOVEL
    assert verdict.duplicates == ()
    assert verdict.digest == skeleton_digest(NOVEL)


def test_the_first_proposal_of_a_campaign_is_admitted(
    clause_gate: AntiConvergenceGate,
) -> None:
    # An empty comparison set refuses nothing, and that is the correct answer —
    # not the empty-document mistake features 212 and 213 refuse.  A campaign
    # that has proposed nothing has converged on nothing; the empty case here
    # is *history*, not a missing decision.
    for held in ((), [], ()):
        verdict = clause_gate.admit(NOVEL, held=held)
        assert verdict.admitted is True


def test_the_comparison_set_is_per_campaign(clause_gate: AntiConvergenceGate) -> None:
    # PRD §9 makes the campaign the unit of search: two campaigns exploring one
    # structure from different angles are two campaigns, not one collapse.  The
    # same source refused against one campaign's history is admitted against
    # another's, and nothing about the gate changed between the two calls.
    assert clause_gate.admit(TWEAK, held=[("n1", HELD)]).admitted is False
    assert clause_gate.admit(TWEAK, held=[("other", NOVEL)]).admitted is True


def test_the_verdict_names_every_duplicate_it_found(
    clause_gate: AntiConvergenceGate,
) -> None:
    # The retrying agent needs to see *which* of its own nodes it is
    # duplicating and *how many times*: "not novel" is not a repair, and "you
    # have proposed this structure nine times" is.
    held = [("n1", HELD), ("n2", NOVEL), ("n3", TWEAK), ("n4", HELD)]
    verdict = clause_gate.admit(TWEAK, held=held)
    assert verdict.admitted is False
    assert [node for node, _ in verdict.duplicates] == ["n1", "n3", "n4"]
    # Only the duplicates, in the caller's order — the novel node between them
    # is not reported, because reporting it would name a node that is not why
    # the proposal was refused.
    assert "n2" not in verdict.detail
    assert "n1" in verdict.detail and "n4" in verdict.detail
    assert "3 time(s)" in verdict.detail


def test_a_long_collapse_summarises_rather_than_quoting_every_id(
    clause_gate: AntiConvergenceGate,
) -> None:
    # §14.1's failure mode is exactly the case where the list is long — four
    # hundred variants — and a sentence quoting four hundred ids is one nobody
    # reads.  The bound is the law's; this asserts the sentence summarises
    # rather than truncating silently.
    held = [(f"n{i}", HELD) for i in range(20)]
    verdict = clause_gate.admit(TWEAK, held=held)
    assert len(verdict.duplicates) == 20
    assert "20 time(s)" in verdict.detail
    assert "more)" in verdict.detail


def test_the_refusal_opens_with_the_parameter_tweak_code(
    clause_gate: AntiConvergenceGate,
) -> None:
    verdict = clause_gate.admit(TWEAK, held=[("n1", HELD)])
    assert verdict.detail.startswith(PARAMETER_TWEAK_CODE)
    assert PARAMETER_TWEAK_CODE == "parameter_tweak"


def test_the_refusal_quotes_section_fourteen_one(
    clause_gate: AntiConvergenceGate,
) -> None:
    # The refusal names why nothing else catches this, because an operator
    # reading it has to know the screen is not redundant with feature 205's:
    # *"A converged tree is not caught by anything."*
    detail = clause_gate.admit(TWEAK, held=[("n1", HELD)]).detail
    assert "§14.1" in detail
    assert "converged tree is not caught by anything" in detail
    assert "400th variant of one indicator" in detail


def test_the_admission_opens_with_the_novel_code(
    clause_gate: AntiConvergenceGate,
) -> None:
    # The admitted case's own token, because an admission is not a code an
    # operator greps a campaign for — the asymmetry feature 212's LEGAL_THEME_CODE
    # states for its own gate.
    verdict = clause_gate.admit(NOVEL, held=[("n1", HELD)])
    assert verdict.detail.startswith(NOVEL_CODE)
    assert NOVEL_CODE == "novel_structure"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(None, id="none"),
        pytest.param(7, id="an-int"),
        pytest.param([], id="a-list"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param("def signal(ctx, seed)\n    return 1\n", id="unparseable"),
    ],
)
def test_a_submission_that_is_not_a_proposal_is_refused_with_its_own_reason(
    clause_gate: AntiConvergenceGate, source: object
) -> None:
    # Its own reason, not the headline's: the repair is different in kind.  An
    # empty or unparseable submission is a bug at the call site (or a caller
    # that skipped feature 205's adopt), and an operator looking for a converged
    # tree would be looking in the wrong place.
    verdict = clause_gate.admit(source, held=[("n1", HELD)])
    assert verdict.admitted is False
    assert verdict.reason is AntiConvergenceReason.NOT_A_PROPOSAL
    assert verdict.detail.startswith(NOT_A_PROPOSAL_CODE)
    assert verdict.digest is None


def test_a_refusal_is_never_admitted_by_a_broken_comparison_set(
    clause_gate: AntiConvergenceGate,
) -> None:
    # The comparison set is the caller's own history, and a node the caller
    # cannot parse is one this law has no opinion about.  Refusing the *new*
    # proposal because an *old* one was unparseable would be this gate
    # reporting a defect in the tree as a property of the submission.
    held = [("broken", "def signal(ctx, seed)\n    return 1\n"), ("junk", 7)]
    verdict = clause_gate.admit(NOVEL, held=held)
    assert verdict.admitted is True


def test_the_comparison_set_accepts_digests_as_well_as_sources(
    clause_gate: AntiConvergenceGate,
) -> None:
    # Three shapes, all legitimate for a caller that already holds part of the
    # answer: (node_id, source), (node_id, digest) — what a previous verdict
    # carried, so screening a batch does not re-parse the whole history per
    # proposal — and a bare string, for a caller screening before anything is
    # persisted.
    by_source = clause_gate.admit(TWEAK, held=[("n1", HELD)])
    by_digest = clause_gate.admit(TWEAK, held=[("n1", skeleton_digest(HELD))])
    assert by_source.detail == by_digest.detail
    assert by_digest.duplicates == (("n1", skeleton_digest(HELD)),)


def test_a_bare_string_in_the_comparison_set_gets_a_positional_id(
    clause_gate: AntiConvergenceGate,
) -> None:
    verdict = clause_gate.admit(TWEAK, held=[HELD])
    assert verdict.admitted is False
    # Spelled ``held-<n>`` rather than a UUID, because it is *not* a node id
    # and must not be mistaken for one in a log line.
    assert verdict.duplicates == (("held-0", skeleton_digest(HELD)),)


def test_the_applied_verdict_carries_the_digest_so_a_caller_can_chain(
    clause_gate: AntiConvergenceGate,
) -> None:
    # A caller screening several proposals in one pass hands each admitted
    # verdict's pair back in, and does not re-parse its history per proposal.
    first = clause_gate.admit(HELD, held=[])
    assert first.admitted is True
    held = [("n1", first.digest)]
    assert clause_gate.admit(TWEAK, held=held).admitted is False


# -- covers: the read side of the applied law --------------------------------


def test_covers_is_the_predicate_admit_runs(
    clause_gate: AntiConvergenceGate,
) -> None:
    # The same question without a verdict object, so a dashboard and a gate
    # cannot drift apart on their answer.  ``True`` means *refused* — feature
    # 213's denylist polarity, and the inverse of feature 212's allowlist: the
    # same word, opposite verdict.
    held = [("n1", HELD)]
    assert clause_gate.covers(TWEAK, held) is True
    assert clause_gate.covers(TWEAK, held) == (
        not clause_gate.admit(TWEAK, held=held).admitted
    )
    assert clause_gate.covers(NOVEL, held) is False


def test_covers_answers_false_rather_than_raising_on_a_non_proposal(
    clause_gate: AntiConvergenceGate,
) -> None:
    # This is the *asking* verb: a caller branching on the answer gets a
    # boolean, and the caller that wants the parse failure named calls ``admit``
    # or ``proposal_skeleton``.
    for source in (None, 7, "", "def signal(ctx, seed)\n    return 1\n"):
        assert clause_gate.covers(source, [("n1", HELD)]) is False


# -- require: the one seam where a refusal becomes an exception --------------


def test_require_returns_the_digest_for_a_novel_proposal(
    clause_gate: AntiConvergenceGate,
) -> None:
    assert clause_gate.require(NOVEL, [("n1", HELD)]) == skeleton_digest(NOVEL)


def test_require_raises_the_proposal_error_for_a_tweak(
    clause_gate: AntiConvergenceGate,
) -> None:
    with pytest.raises(AntiConvergenceError) as caught:
        clause_gate.require(TWEAK, [("n1", HELD)])
    assert str(caught.value).startswith(PARAMETER_TWEAK_CODE)


def test_require_raises_with_the_same_sentence_the_verdict_carries(
    clause_gate: AntiConvergenceGate,
) -> None:
    # The retry prompt and the log line must say the same thing — a caller that
    # branched on the verdict and one that let it raise must not record two
    # different reasons.
    detail = clause_gate.admit(TWEAK, held=[("n1", HELD)]).detail
    with pytest.raises(AntiConvergenceError) as caught:
        clause_gate.require(TWEAK, [("n1", HELD)])
    assert str(caught.value) == detail


def test_the_verdict_constructor_refuses_nothing(
    clause_gate: AntiConvergenceGate,
) -> None:
    # A caller holding a refusal is the caller that most needs one, and it
    # cannot be told about an object it was never allowed to build.  The
    # refusals live at ``require``.
    from signal_agent import AntiConvergenceVerdict

    verdict = AntiConvergenceVerdict(
        reason=AntiConvergenceReason.PARAMETER_TWEAK, detail="d"
    )
    assert verdict.admitted is False
    with pytest.raises(AntiConvergenceError):
        verdict.require()


def test_admitted_is_computed_from_the_reason_not_set_by_a_constant() -> None:
    # The "computed, never assumed" stance every gate in this member takes: a
    # verdict built with NOVEL is admitted and one built with either refusal is
    # not, whatever a caller passed for the other fields.
    from signal_agent import AntiConvergenceVerdict

    for reason, expected in (
        (AntiConvergenceReason.NOVEL, True),
        (AntiConvergenceReason.PARAMETER_TWEAK, False),
        (AntiConvergenceReason.NOT_A_PROPOSAL, False),
    ):
        verdict = AntiConvergenceVerdict(reason=reason, detail="d", digest="0" * 64)
        assert verdict.admitted is expected


def test_the_verdict_reason_values_are_their_own_codes() -> None:
    # A StrEnum whose value is the token its detail opens with, so the reason
    # is greppable in a campaign log without a lookup table.  NOVEL is the one
    # place the two differ, the same asymmetry feature 212's ThemeReason.LEGAL
    # has against LEGAL_THEME_CODE.
    assert AntiConvergenceReason.PARAMETER_TWEAK.value == PARAMETER_TWEAK_CODE
    assert AntiConvergenceReason.NOT_A_PROPOSAL.value == NOT_A_PROPOSAL_CODE
    assert AntiConvergenceReason.NOVEL.value == "novel" != NOVEL_CODE


# -- the clause half fails closed, the applied half fails open ---------------


def test_a_gate_whose_clause_is_unreadable_certifies_no_prompt() -> None:
    # The load-bearing asymmetry with feature 213, asserted from the side that
    # matters.  Feature 213's builder falls back to an empty denylist, which
    # *admits* every proposal — fail open.  Feature 210's applied half does the
    # same.  But its clause half cannot: the screen is a substring test and the
    # empty string is a substring of every string, so a naive implementation
    # would certify **every prompt** — a silent green tick on a prompt nobody
    # checked, which is §14.1's "not caught by anything" arriving as this
    # member's own answer.
    empty = AntiConvergenceGate(
        AntiConvergenceClause(
            kind=ANTI_CONVERGENCE_POLICY_KIND,
            slug="anti-convergence",
            title="unreadable",
            text="",
        )
    )
    for prompt in ("", "anything", "the committed clause, even", None, 7):
        assert empty.carries(prompt) is False
    with pytest.raises(AntiConvergenceClauseError):
        empty.require_in("anything")
    # And the applied half of the *same* gate still fails open, because that
    # half's empty case is a campaign with no history rather than a deployment
    # with no document.  The two polarities live in one object on purpose.
    assert empty.admit(NOVEL, held=[]).admitted is True


def test_the_builder_hands_out_a_gate_whose_clause_is_the_committed_one() -> None:
    # The composed path: the builder compiles the artifact, so a caller holding
    # the component has the deployment's clause rather than a stand-in.
    gate = anti_convergence_gate()
    assert gate.text() == committed_anti_convergence().text()
    assert gate.carries("prefix " + gate.text() + " suffix") is True


def test_the_gate_reads_its_clause_rather_than_re_deriving_it() -> None:
    # ``clause`` is exposed so a CI check recompiling the committed artifact
    # and an operator asking what the agent was asked to write under read the
    # same object the screen runs on.  Reading it refuses nothing: the clause
    # holds no capability, which is why the component is a facade.
    gate = anti_convergence_gate()
    assert gate.clause.text() == gate.text()
    assert gate.clause.kind == ANTI_CONVERGENCE_POLICY_KIND
