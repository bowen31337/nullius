"""Feature 6's suite: a model's answer read as source, rationale and text.

app_spec.xml, "Signal Agent Author", feature 6: *System parses a model's
answer with ``signal_agent._authored.parse_authored(text)``, and it creates a
``ParsedProposal(code, stated_mechanism, proposal)``, where ``proposal`` is
the full raw text.*

The sentence is three extractions and one refusal rule, and this file takes
them separately because they fail separately — a suite that tested "the
parse" would let the block rule hold while the raw-text fidelity quietly
didn't:

* **the code** — the body of the answer's *single* ```` ```python ```` block,
  byte for byte.  The fence rules are CommonMark's, pinned here as decisions
  (indentation tolerated, case-folded info string, no info string closes,
  unclosed runs to the end) rather than left for a reader to infer; the
  near-miss spellings are pinned as *not* python blocks, because a parser
  that guessed at ``py``/``python3`` would admit blocks the prompt never
  asked for.
* **the refusals** — zero blocks, several blocks, a blank body, and the
  not-text case beneath all three.  Each message opens with the
  ``authored_output`` code word, because feature 7's retry loop quotes that
  word back to the model and an operator greps for the same token in a
  campaign log.
* **the stated mechanism** — the first line starting ``Mechanism:``, its
  remainder stripped, or ``None``.  The ``None``-versus-empty-string split is
  pinned with the argument that owns it: a *missing* line is the honest
  unstated state 0117's nullable column records, and a *blank* one is
  feature 211's refusal to make at persist — neither is the parser's.
* **the proposal** — the full raw answer, untransformed.  Pinned as an
  ``is`` claim, not merely an equality: the next round reads this text in
  full (§14.1), so "the parser kept the very object it was handed" is the
  guarantee, and a copy that happened to compare equal would still be a
  place for a transformation to hide.

**The fixtures are module-scope text, on purpose.**  The conftest states the
member's rule — proposals are *text*, and several assertions are about the
text itself (it is returned unmodified; the code body is byte-identical), so
a fixture that rebuilt them per test would make "the same answer" a claim
about two constructions rather than about one string.  Nothing here opens a
connection, reads a variable or touches a store: the parse is a pure function
over the strings below, which is the module's own design claim tested by
being true.

**The last two tests pin the module's two standing prohibitions.**  The
error's place in the vocabulary — under the member's base, beside
feature 205's source contract, never inside it — and the import discipline
the sentence states outright (*"the module imports nothing outside the
standard library and the signal_agent package"*), pinned from the parsed
source rather than from a greppable name, so that adding a forbidden import
fails a test rather than a review.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from signal_agent import AgentSourceError, SignalAgentError, _authored

#: The signal body every well-formed fixture answer carries.  Realistic on
#: purpose: the parse's fidelity claims ("byte for byte", "nothing stripped")
#: are only meaningful about text that looks like what the sandbox executes,
#: and a fixture body of ``x = 1`` would let a parser that mangled the shape
#: of real source pass the same assertions.
_CODE = (
    "def signal(ctx, seed):\n"
    "    window = ctx.close[-42:]\n"
    "    return (window - window.mean()) / window.std()"
)

#: The one-line rationale the format asks for — feature 5's own shape, one
#: line starting ``Mechanism:``, so the extraction claims are about the line
#: the prompt actually requests rather than about a paragraph.
_MECHANISM = (
    "short-horizon mean reversion: an oversold 42-bar window reverts "
    "faster than the book prices in"
)

#: The canonical well-formed answer: prose, one fenced block, one mechanism
#: line — the three parts in the order a model naturally writes them.
_ANSWER = (
    "Here is the signal, against the theme root given.\n"
    "\n"
    "```python\n"
    f"{_CODE}\n"
    "```\n"
    "\n"
    f"Mechanism: {_MECHANISM}\n"
)


# ── The code: one block, read verbatim ───────────────────────────────────────


def test_a_well_formed_answer_parses_into_its_three_readings() -> None:
    """Prose, one block, one mechanism line — each part read where it stands.

    The happy path is three fidelity claims at once, asserted separately so
    a failure names the half that broke: the code is the body between the
    fences (no leading blank from the line after the opener, no trailing
    blank from the line before the closer), the mechanism is the prefix's
    remainder with its leading space stripped, and the proposal is the whole
    answer including the prose and the fences the other two were cut from.
    """
    parsed = _authored.parse_authored(_ANSWER)
    assert parsed.code == _CODE
    assert parsed.stated_mechanism == _MECHANISM
    assert parsed.proposal == _ANSWER


def test_the_proposal_is_the_very_object_handed_in() -> None:
    """``is``, not merely ``==`` — the parser is not the answer's transformer.

    §14.1's read-everything rule makes the persisted proposal the thing the
    next round reads in full, so the parse's guarantee is stronger than
    equality: it hands on the same string it was given, and a copy — even one
    that compared equal — would be a place for a silent strip or re-render to
    hide between the provider's completion and the history's row.
    """
    parsed = _authored.parse_authored(_ANSWER)
    assert parsed.proposal is _ANSWER


def test_the_block_body_is_carried_byte_for_byte() -> None:
    """Nothing is stripped from the body's ends — the hash covers these bytes.

    A model that opens its fence with a blank line, indents its source,
    leaves a blank line inside and closes cold still wrote exactly that
    body, and ``code_hash`` downstream (§9.1) is a hash of what the model
    wrote.  A parser that trimmed the ends "to be tidy" would make the
    identity a property of the parser rather than of the answer — two
    spellings of one proposal would hash apart for no reason the model
    caused.
    """
    answer = (
        "```python\n"
        "\n"
        "def signal(ctx, seed):\n"
        "\n"
        "    return ctx.close\n"
        "```"
    )
    parsed = _authored.parse_authored(answer)
    assert parsed.code == (
        "\ndef signal(ctx, seed):\n\n    return ctx.close"
    )


def test_a_fence_may_be_indented_and_surrounded_by_space() -> None:
    """Fence matching strips the line — models indent fences inside lists.

    The opener may carry indentation and trailing space after its info
    string, and the closer may be indented to match; both are the shapes
    real answers arrive in, and a scanner that required the marker at column
    zero would refuse a perfectly clear block.
    """
    answer = f"   ```python \n{_CODE}\n   ```"
    parsed = _authored.parse_authored(answer)
    assert parsed.code == _CODE


def test_the_info_string_is_python_case_folded() -> None:
    """```` ```Python ```` opens a python block — the word, not its case.

    Models write the language name with a capital now and then; the info
    string is compared case-folded because the *word* is the fact and its
    case is not.  Everything else about the spelling stays exact — the
    near-miss test below pins that.
    """
    answer = f"```Python\n{_CODE}\n```"
    parsed = _authored.parse_authored(answer)
    assert parsed.code == _CODE


@pytest.mark.parametrize("info", ["py", "python3", "python  # the signal"])
def test_a_near_miss_info_string_is_not_a_python_block(info: str) -> None:
    """``py``, ``python3`` and annotated fences are not what the format asked.

    The authoring format names ```` ```python ```` (feature 5); a parser that
    recognised near-miss spellings would admit blocks the prompt never
    requested while refusing to say which spelling it accepted — the same
    silent guess the several-blocks refusal exists to prevent, one character
    wide.
    """
    answer = f"```{info}\n{_CODE}\n```"
    with pytest.raises(_authored.AuthoredOutputError, match=r"^authored_output"):
        _authored.parse_authored(answer)


def test_a_bare_fence_is_not_a_python_block() -> None:
    """An unlabelled fence holding code is prose-shaped, and refused as zero.

    The info string is what makes a fence the answer's *source*; a bare
    block is a quotation, and adopting it would be the parser choosing code
    the model fenced for another purpose.
    """
    answer = f"```\n{_CODE}\n```"
    with pytest.raises(_authored.AuthoredOutputError, match=r"^authored_output"):
        _authored.parse_authored(answer)


def test_the_content_of_other_fences_is_not_scanned_for_blocks() -> None:
    """A ```` ```json ```` block neither counts nor hides the real one.

    The scanner skips a non-python fence's content whole, so an answer may
    carry documentation blocks beside its source and the source is still the
    one python block — the count is over *python* fences, not over fences.
    """
    answer = (
        '```json\n{"metric": "ir_marginal", "window": 42}\n```\n'
        f"\n```python\n{_CODE}\n```"
    )
    parsed = _authored.parse_authored(answer)
    assert parsed.code == _CODE


def test_a_python_line_inside_an_open_block_is_content_not_a_boundary() -> None:
    """CommonMark's rule: only a bare fence closes, so this is one block.

    A second ```` ```python ```` line inside an open block does not close it
    and does not open another — the block runs to the bare fence, and the
    inner marker is body.  Pinning this keeps the scanner line-based
    Markdown rather than a home-grown nest of counters, and keeps an answer
    whose source quotes a fence line out of the several-blocks refusal it
    would otherwise meet.
    """
    answer = "```python\nfirst\n```python\nsecond\n```"
    parsed = _authored.parse_authored(answer)
    assert parsed.code == "first\n```python\nsecond"


def test_an_unclosed_fence_runs_to_the_end_of_the_text() -> None:
    """No closing fence: the body is the remainder — one block, not zero.

    CommonMark again: an unclosed fence runs to the end of its container.
    The block still counts as the one it visibly meant to be, so a truncated
    answer is judged on the source it did carry (the contract's refusal to
    make, if prose followed) rather than refused here as a shape it never
    chose.
    """
    answer = f"Intro prose.\n```python\n{_CODE}"
    parsed = _authored.parse_authored(answer)
    assert parsed.code == _CODE


# ── The refusals: one shape, four depths, one code word ─────────────────────


def test_no_block_at_all_is_refused() -> None:
    """Prose and a mechanism line, but no source — the answer proposes nothing.

    The mechanism half never rescues the code half: the two are judged
    separately by design (the statement is feature 211's subject at persist
    time), and an answer without a block is refused with the code word the
    retry loop quotes back to the model.
    """
    answer = f"Some thoughts.\n\nMechanism: {_MECHANISM}\n"
    with pytest.raises(_authored.AuthoredOutputError) as raised:
        _authored.parse_authored(answer)
    assert str(raised.value).startswith("authored_output: ")
    assert "no ```python fenced block" in str(raised.value)


def test_several_blocks_are_refused_and_the_count_is_named() -> None:
    """Two blocks is an ambiguity, and the ambiguity is named, not resolved.

    Both bodies here are plausible sources; picking one would be this
    parser's guess spent as a trial charge (§14.1), so the refusal names the
    count — the model's retry message then says *what shape to answer in*,
    which no silent pick could have told it.
    """
    answer = (
        f"```python\n{_CODE}\n```\n"
        "\nBetween the two:\n\n"
        f"```python\ndef signal(ctx, seed):\n    return ctx.open\n```\n"
        f"\nMechanism: {_MECHANISM}\n"
    )
    with pytest.raises(_authored.AuthoredOutputError) as raised:
        _authored.parse_authored(answer)
    message = str(raised.value)
    assert message.startswith("authored_output: ")
    assert "carries 2 ```python fenced blocks" in message


@pytest.mark.parametrize("body", ["", " ", "\t\n   \n"])
def test_a_blank_body_is_refused(body: str) -> None:
    """The fence is there and carries nothing — no source was proposed.

    Whitespace-only counts as blank: nothing adoptable exists between the
    fences, and the refusal names the answer's shape rather than letting a
    blank reach the conformance gates wearing a source defect it is not —
    the agent contract requires non-blank code, and this is where that
    guarantee is established for the LLM path.
    """
    answer = f"```python\n{body}\n```"
    with pytest.raises(_authored.AuthoredOutputError) as raised:
        _authored.parse_authored(answer)
    message = str(raised.value)
    assert message.startswith("authored_output: ")
    assert "blank body" in message


@pytest.mark.parametrize("not_text", [None, 42, b"```python\npass\n```", ["answer"]])
def test_a_value_that_is_not_text_is_refused(not_text: object) -> None:
    """No answer to read — including bytes, the easy wrong shape to hand in.

    A caller that passes an encoded completion or a structured value holds
    something other than the provider's content, and the refusal names the
    type it got so the fix is at the call site rather than in the model.
    """
    with pytest.raises(_authored.AuthoredOutputError) as raised:
        _authored.parse_authored(not_text)  # type: ignore[arg-type]
    message = str(raised.value)
    assert message.startswith("authored_output: ")
    assert type(not_text).__name__ in message


def test_the_code_word_is_the_one_the_spec_names() -> None:
    """``authored_output``, spelled once, opening every refusal this raises.

    The constant exists so the raise sites, the retry message that quotes
    them (feature 7) and an operator's grep read the same string; this pins
    the token itself, because a code word that drifted would strand every
    log line already written against it.
    """
    assert _authored.AUTHORED_OUTPUT_CODE == "authored_output"
    assert _authored.AuthoredOutputError.__module__ == "signal_agent._authored"


# ── The stated mechanism: first line, remainder, stripped ────────────────────


def test_the_mechanism_is_the_first_line_s_remainder_stripped() -> None:
    """Whitespace around the rationale goes; nothing else is touched.

    ``Mechanism:`` followed by several spaces, and a rationale with trailing
    spaces before the newline, still answer the rationale alone.  Stripping
    is whitespace-only by design — folding case or punctuation is
    ``canonical_mechanism``'s comparison, and a parser that "fixed" spelling
    would be editing the agent's words on their way into history.
    """
    answer = (
        "```python\n"
        f"{_CODE}\n"
        "```\n"
        "\n"
        f"Mechanism:   {_MECHANISM}   \n"
    )
    parsed = _authored.parse_authored(answer)
    assert parsed.stated_mechanism == _MECHANISM


def test_the_first_mechanism_line_wins_and_the_rest_are_ignored() -> None:
    """A second line is the model's own redundancy, not a refusal.

    The format asked for one line; the first one is the statement, and the
    parse refuses to turn a repeated line into a retry the model cannot
    locate.
    """
    answer = (
        f"```python\n{_CODE}\n```\n\n"
        "Mechanism: first claim\nMechanism: second claim\n"
    )
    parsed = _authored.parse_authored(answer)
    assert parsed.stated_mechanism == "first claim"


def test_a_missing_mechanism_line_answers_none() -> None:
    """No line, no statement — the honest unstated state, not a refusal.

    0117's nullable column exists to record an agent that stated no
    mechanism rather than fabricate a rationale no one wrote, and discovery's
    agent contract carries ``.stated_mechanism`` as optional; the parse
    reports the absence and lets the statement law decide what may be
    recorded.
    """
    answer = f"```python\n{_CODE}\n```"
    parsed = _authored.parse_authored(answer)
    assert parsed.stated_mechanism is None


def test_a_mechanism_line_that_says_nothing_answers_empty_string() -> None:
    """``Mechanism:`` alone is ``""``, not ``None`` — the split is 211's.

    A line that exists but states nothing is a *stated blank*, which is
    feature 211's refusal to make when the statement is persisted; reporting
    it as ``None`` here would conflate an agent that said nothing with one
    that said nothing *after deciding to say something*.
    """
    answer = f"```python\n{_CODE}\n```\n\nMechanism:   \n"
    parsed = _authored.parse_authored(answer)
    assert parsed.stated_mechanism == ""


@pytest.mark.parametrize(
    "line",
    ["  Mechanism: indented", "mechanism: lower case", "The Mechanism: mid-sentence"],
)
def test_only_a_line_that_starts_with_the_prefix_counts(line: str) -> None:
    """The prefix is exact: column zero, capital ``M``, one colon.

    The format names the spelling (feature 5) and a parser that recognised
    indented or lower-case variants would be accepting lines the prompt
    never asked for, on the model's behalf — the near-miss rule from the
    fence's info string, applied to the mechanism's marker.
    """
    answer = f"```python\n{_CODE}\n```\n\n{line}\n"
    parsed = _authored.parse_authored(answer)
    assert parsed.stated_mechanism is None


def test_a_mechanism_line_inside_the_fence_is_still_the_statement() -> None:
    """The scan reads raw lines in order — it does not track fences.

    Taking the model at its word about where it stated its rationale cuts
    both ways, and this is the other edge: a mechanism stated inside the
    code fence is *read*, because a structure-aware scan that skipped it
    would silently turn a stated mechanism into an unstated one — the wrong
    direction for a column whose whole nullability argument is honesty about
    what was said.
    """
    answer = (
        "```python\n"
        f"{_CODE}\n"
        "Mechanism: stated inside the fence\n"
        "```\n"
    )
    parsed = _authored.parse_authored(answer)
    assert parsed.stated_mechanism == "stated inside the fence"


# ── The value: parts, hash, and a repr that keeps prose out of logs ─────────


def test_the_constructor_refuses_nothing_and_keeps_the_sentence_s_order() -> None:
    """``ParsedProposal(code, stated_mechanism, proposal)`` — and it builds.

    Construction is not judgment (:class:`~signal_agent.PriorProposal`'s own
    rule): the parse's refusals stay in :func:`~signal_agent._authored.
    parse_authored`, and the positional order is the feature sentence's own,
    so a caller writing the value by hand writes it the way the spec spells
    it.
    """
    value = _authored.ParsedProposal(_CODE, None, _ANSWER)
    assert value.code == _CODE
    assert value.stated_mechanism is None
    assert value.proposal == _ANSWER


def test_equality_is_over_the_parts_and_survives_the_double_import() -> None:
    """Duck-read by name — the loader imports this member twice.

    ``isinstance`` would be false for a value built from the other import of
    this same file, so equality reads the three fields off whatever it was
    handed (a :class:`types.SimpleNamespace` with the same parts *is* equal,
    which is the pin); equal values hash equal; anything without the parts
    is simply not equal, no exception.
    """
    first = _authored.parse_authored(_ANSWER)
    second = _authored.parse_authored(_ANSWER)
    assert first == second
    assert hash(first) == hash(second)
    assert first == SimpleNamespace(
        code=_CODE, stated_mechanism=_MECHANISM, proposal=_ANSWER
    )

    other = _authored.parse_authored(
        f"```python\n{_CODE}\n```\n\nMechanism: a different claim\n"
    )
    assert first != other
    assert first != _ANSWER


def test_the_repr_carries_lengths_not_text() -> None:
    """A model's prose stays out of log lines — the shape is the repr.

    The value holds a whole answer and its rationale; a repr that printed
    either would put prose into terminals and logs, and quoting a proposal
    anywhere but its own artifact is the truncation feature 206 refuses, in
    miniature.  The lengths say everything a log needs.
    """
    value = _authored.parse_authored(_ANSWER)
    rendered = repr(value)
    assert f"code_chars={len(_CODE)}" in rendered
    assert f"proposal_chars={len(_ANSWER)}" in rendered
    assert "window.std()" not in rendered
    assert "reversion" not in rendered
    assert "Here is the signal" not in rendered


# ── The two standing prohibitions ───────────────────────────────────────────


def test_where_the_refusal_sits_in_the_member_s_vocabulary() -> None:
    """Under the base, beside the source contract — never inside it.

    A caller's single ``except SignalAgentError`` still catches every
    failure of the authoring path, so subclassing the base is owed.  The
    sibling pin is the load-bearing half: feature 205's handler is about
    *source that failed the declared contract*, and this refusal fires
    before any source exists to judge — zero blocks means no code at all.
    Folding it in would make "how often did the model answer in the wrong
    shape?" unanswerable without reading message text.
    """
    assert issubclass(_authored.AuthoredOutputError, SignalAgentError)
    assert not issubclass(_authored.AuthoredOutputError, AgentSourceError)
    assert not issubclass(AgentSourceError, _authored.AuthoredOutputError)


def test_the_module_imports_nothing_outside_stdlib_and_this_package() -> None:
    """The spec's own sentence, pinned from the parsed source.

    Read with :mod:`ast` rather than grepped, because the claim is about what
    the interpreter executes: every absolute import's root must be standard
    library (``__future__`` included — it is a compiler directive, not a
    package), and every relative import stays inside ``signal_agent`` by
    construction of Python's own semantics.  No ``providers``, no
    ``discovery``, no null sidecar — the parser is model-agnostic and
    testable as a pure function over text, and this is what keeps it that
    way when nobody is looking.
    """
    source = Path(_authored.__file__).read_text(encoding="utf-8")
    absolute_roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            absolute_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            absolute_roots.add((node.module or "").split(".")[0])
    assert absolute_roots <= set(sys.stdlib_module_names) | {"__future__"}, (
        f"imports outside the standard library and this package: "
        f"{sorted(absolute_roots - set(sys.stdlib_module_names))}"
    )
