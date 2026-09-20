"""Keeping ``is_null`` out of the tree store — feature 110's refusal.

app_spec.xml, "Null Oracle & Planted Nulls", feature 110: *System keeps
is_null absent from the tree store entirely, which rejects any proposed node
column named is_null.*  It depends on feature 109, and the dependency is the
whole of the rule's content: the null bit already has the one home §7.1
allows it — the AES-GCM sidecar readable by exactly one service account — so
no writer ever *needs* the column, and the tree store is the one place it may
never appear.  docs/nullius-tech-architecture.md §7.1 states the rule as a
fact about the schema rather than a policy about its use:

    **There is no ``is_null`` column anywhere in the tree store.** Not
    hidden, not nulled out, not ``SELECT``-excluded. Absent. The only way to
    learn a node's status is to hold the sidecar key.

**A refusal, not a convention.**  §4.2 closes its own statement of the
barrier with *"Enforce it with a type-level barrier, not a code review"*, and
the same sentence governs the column: a convention — "we don't name a column
that" — is a code review, and a code review is exactly the enforcement §1
says the leak defeats, because *"a leak here silently voids every
calibration number the system has ever produced, and you would not
notice."*  This module is the check that *runs*: a proposal naming the
column cannot pass it, and a store carrying the column cannot read as
guarded.  The refusal is loud on purpose — a ``NOT NULL DEFAULT FALSE``
``is_null`` column is the most harmless-looking object in the schema, and
harmless-looking is the whole danger: every reader of the store, from the
discovery loop to the dashboard, becomes a reader of the labels the moment
it exists.

**Three spellings, one decision.**  The comparison is spelled once — a
column name is forbidden when it casefolds to :data:`FORBIDDEN_COLUMN` —
and everything else is a seam over the moments a column can appear:

* :func:`review_node_columns` — the *data* spelling.  A caller holding
  proposed column names as an iterable (a schema checklist, an ORM model's
  fields, a DataFrame a caller nearly wrote into the store) hands them over
  and gets the canonical tuple back, or the refusal.
* :func:`review_ddl` — the *migration* spelling, over
  :func:`node_columns_from_ddl`.  In this workspace a column proposal
  actually arrives as DDL: every column feature 98–101 ships is an ``ALTER
  TABLE ... ADD COLUMN`` statement a migration exposes as *data* through its
  ``statements("sqlite")`` — returned rather than executed, the convention's
  own words, *"so the DDL is inspectable"*.  This is the inspection.  The
  extractor reads the two shapes a node column can be proposed in — a
  ``CREATE TABLE`` column list and an ``ALTER TABLE``'s ``ADD`` clause —
  without executing anything, opening anything, or importing the file the
  statements came from.
* :meth:`TreeStoreGuard.audit` — the *standing* spelling.  *"Keeps absent"*
  is a maintained state, not a one-time claim: a column can arrive by a path
  that skipped both reviews (a hand-run ``ALTER``, a database restored from
  a store written by an older deployment), so the audit reads the live
  store's *declared* columns — what ``PRAGMA table_info`` answers, not what
  any query happens to select — and refuses when the forbidden one is among
  them.  A schema that hides the bit behind a view or a ``SELECT`` exclusion
  is not a schema this audit would bless, because it never asks the queries;
  it asks the table.

**Why the comparison is casefolded.**  SQLite column names are
case-insensitive: ``node.IS_NULL`` *is* ``node.is_null`` in every query, and
``PRAGMA table_info`` answers with the declared spelling, whichever it was.
A guard that matched only the lowercase spelling would refuse the name and
wave through the column — the exact shape of hole a convention leaves — so
``IS_NULL``, ``Is_Null`` and ``is_null`` are one offender, and the refusal
names the spelling it caught.

**The boundary is the ``node`` table.**  "Tree store" is the name this
member's own documentation uses for feature 97's ``node`` table — the store
every join here names ("the tree store's ``node.id``", "the tree store's
``node.flip_depth``") — and "node column" can only mean a column of it.  The
extractor therefore reads only the ``node`` table's statements and the audit
only the ``node`` table's columns; a column named ``is_null`` on any other
table is not this feature's to refuse — §4.2's barrier and the
scorer-package reachability rule (app_spec.xml feature 354) own the wider
sweep — and a guard that silently widened itself would refuse DDL no
sentence here empowers it to.  Deliberately exactly as wide as the feature's
own sentence.

**The audit reads, and never writes.**  A check must not mutate what it
checks: the audit opens the store read-only (SQLite's ``mode=ro``), so it
can neither create the table it audits — a guard whose audit built the
schema would bless a schema it just made — nor mend one it found broken.  A
database file that does not exist holds no ``node`` table, so absence holds
trivially there and the audit answers the empty column set — the same
true-but-thin answer :meth:`nulloracle.plan.CampaignPlanGate.review` gives
an absent sidecar, for the same reason: the file is the only place the
column could be, and there is no file.  A database that exists but will not
open raises :class:`~nulloracle.errors.KsGuardError` rather than answering,
because *"the barrier could not be checked"* must never read as *"the
barrier holds"*.

**The error vocabulary, and where each refusal lands.**  The barrier itself
is :class:`~nulloracle.errors.IsNullColumnError`, and every message begins
with :data:`NULL_COLUMN` (``is_null_column``) and names the offending
spelling — the same greppable-code discipline :data:`nulloracle.plan.
HETEROGENEOUS_WORLD` applies to the rejection the spec names.  Everything
else — an unreachable store, a scheme this store cannot speak, a column
proposal that is not a list of names, DDL that is not strings — is
:class:`~nulloracle.errors.KsGuardError`, the store-contract error the
fraction's, the flip depth's, the verdict's and the gate's stores already
raise, because those failures are about the *caller's document or the
deployment*, not about the one column the method forbids.

**Stdlib only, and import-cheap.**  ``re``, ``os``, ``sqlite3``,
``dataclasses`` and ``urllib.parse``; no third-party import at module scope,
so the factory's scan — which imports this package to fire its ``@register``
— pays nothing for this module, the discipline every store in the member
states.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, unquote, urlparse

from .errors import IsNullColumnError, KsGuardError

__all__ = [
    "DATABASE_URL_ENV",
    "FORBIDDEN_COLUMN",
    "NODE_TABLE",
    "NULL_COLUMN",
    "SchemaAudit",
    "TreeStoreGuard",
    "audit_tree_store",
    "node_columns_from_ddl",
    "review_ddl",
    "review_node_columns",
]

#: The error code every :class:`~nulloracle.errors.IsNullColumnError` message
#: begins with — the offender's own name, as a greppable prefix.
#:
#: Spelled once, as a constant, for the same reason
#: :data:`nulloracle.plan.HETEROGENEOUS_WORLD` is: the refusal is the one an
#: operator greps a log for, and two writers spelling it differently would
#: persist two codes for one failure.  A prefix rather than a substring so a
#: log line cannot carry it by accident — the message *begins* with the code,
#: and everything after the colon is the explanation.
NULL_COLUMN = "is_null_column"

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the guard's, the
#: verdict's, the fraction's, the flip depth's, the selection's, the
#: repository-level conftest's), restated here so this store states its own
#: contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The tree store's node table — feature 97's, the one table a "node column"
#: can be a column of.  The same spelling every module in this member that
#: joins the tree states, restated here so the guard and the stores it audits
#: cannot drift apart on what the tree store is called.
NODE_TABLE = "node"

#: The one column name the tree store may never carry — §7.1's own spelling.
#: The comparison against it is *casefolded* (see :func:`_is_forbidden`),
#: because SQLite column names are case-insensitive and ``IS_NULL`` is
#: ``is_null`` in every query; the constant itself stays lowercase because
#: that is the spelling the spec, the docs and the sidecar's schema all use.
FORBIDDEN_COLUMN = "is_null"

#: The keywords that begin a *table* constraint rather than a column
#: definition inside a ``CREATE TABLE`` body — an item starting with one of
#: these names a constraint, not a column, so the extractor skips it.  A
#: ``PRIMARY KEY (a, b)`` clause is not a column named ``primary``.
_TABLE_CONSTRAINT_KEYWORDS = frozenset(
    {"primary", "foreign", "unique", "check", "constraint"}
)

#: ``CREATE TABLE`` (with SQLite's optional ``IF NOT EXISTS``), the first of
#: the two shapes a node column can be proposed in.
_CREATE_TABLE_HEAD = re.compile(
    r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?", re.IGNORECASE
)

#: ``ALTER TABLE`` (with Postgres's optional ``IF EXISTS``), the head of the
#: second shape — the ``ALTER TABLE node ADD COLUMN x`` statements this
#: workspace's column migrations (features 98–101) are made of.
_ALTER_TABLE_HEAD = re.compile(
    r"\balter\s+table\s+(?:if\s+exists\s+)?", re.IGNORECASE
)

#: ``ADD`` or ``ADD COLUMN``, either dialect — the clause that proposes the
#: column.  Matched with :func:`re.finditer` so a statement carrying more
#: than one ``ADD`` (a dialect SQLite does not allow but a proposal may
#: still spell) has each of them read.
_ADD_COLUMN = re.compile(r"\badd(?:\s+column)?\s+", re.IGNORECASE)

#: A bare SQL identifier — the form every column and table name in this
#: workspace's DDL takes, matched here so the extractor can find where a
#: name *ends* as well as where it begins.
_BARE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


# -- The one decision ---------------------------------------------------------


def _is_forbidden(name: str) -> bool:
    """Whether ``name`` is the forbidden column, under SQLite's own rules.

    Casefolded, because SQLite column names are case-insensitive: a column
    declared ``IS_NULL`` answers to ``node.is_null`` in every query, so the
    spellings are one column and must be one refusal.  Stripped first,
    because a proposal that arrived as ``" is_null "`` names the same column
    and a guard defeated by whitespace would be a guard defeated by nothing
    at all.  This is the single comparison every spelling of the rule runs —
    the names review, the DDL review and the audit — which is what keeps the
    three one decision rather than three that could disagree.
    """
    return name.strip().casefold() == FORBIDDEN_COLUMN


def _is_node_table(name: str) -> bool:
    """Whether ``name`` names the tree store's table, under SQLite's rules.

    Casefolded for the same reason :func:`_is_forbidden` is, and compared on
    the last dotted segment so a schema-qualified ``main.node`` still names
    the table.  The extractor reads no other table, by the boundary the
    module docstring states: a column named ``is_null`` elsewhere is §4.2's
    and feature 354's to police, not the tree store guard's.
    """
    return name.strip().rsplit(".", 1)[-1].casefold() == NODE_TABLE


def _quoted(offenders: Iterable[str]) -> str:
    """The offending spellings, named for a refusal that names names.

    Deduplicated and sorted, because a proposal listing the same column
    twice is still one column and the refusal should say so — and the
    spellings are kept as declared (``IS_NULL`` stays uppercase) so an
    operator reading the message learns which spelling to drop.
    """
    return ", ".join(repr(name) for name in sorted(set(offenders)))


def _proposal_refusal(offenders: list[str], source: Optional[str]) -> str:
    """The message for a *proposal* the review refuses — before it lands."""
    origin = f" proposed by {source}" if source else ""
    return (
        f"{NULL_COLUMN}: a node column named {_quoted(offenders)}{origin} is "
        "refused rather than applied; §7.1 states the rule as 'There is no "
        "is_null column anywhere in the tree store' — not hidden, not nulled "
        "out, not SELECT-excluded — and the tree store is the one place the "
        "bit may never land: a node's null status lives in §7.1's sealed "
        "sidecar (feature 109) and nowhere else, so a tree carrying the bit "
        "in the clear would hand it to every reader of the store — the leak "
        "§1 says 'silently voids every calibration number the system has "
        "ever produced, and you would not notice'"
    )


def _presence_refusal(offenders: list[str]) -> str:
    """The message for a column the *audit* found — after it landed."""
    return (
        f"{NULL_COLUMN}: the tree store's {NODE_TABLE} table carries the "
        f"column {_quoted(offenders)}, and the audit refuses rather than "
        "reports; §7.1 states the rule as 'There is no is_null column "
        "anywhere in the tree store' — not hidden, not nulled out, not "
        "SELECT-excluded — so a present column is not a state to describe "
        "but a barrier already broken: the bit has a home in the clear where "
        "only the sealed sidecar may hold it (feature 109), every reader of "
        "this store is a reader of the labels, and §4.2's verdict on that is "
        "'violating this silently voids all calibration'.  Drop the column "
        "and replant the campaign; nothing measured against this store in "
        "the meantime is interpretable"
    )


def _validated_column_names(columns: Any) -> tuple[str, ...]:
    """Canonicalize a proposed column list, refusing what is not one.

    The same shape-check :func:`nulloracle.plan._sorted_node_ids` applies to
    a plan's halves: a bare string is not a list of names (a caller handing
    one name wraps it in a list, exactly as they would for any iterable-of-
    names seam), and a name that is not a non-empty string is a proposal no
    schema could apply.  Names are stripped rather than rejected for their
    whitespace, because ``" is_null "`` names the same column ``is_null``
    does and the refusal must land on the column, not on its padding.
    """
    if isinstance(columns, (str, bytes)) or not isinstance(columns, Iterable):
        raise KsGuardError(
            f"columns must be an iterable of column names, got "
            f"{type(columns).__name__} ({columns!r}); a column proposal names "
            "the columns the tree store's node table would carry, and a value "
            "that is not a collection of names is not a proposal the review "
            "could answer"
        )
    canonical: list[str] = []
    for value in columns:
        if isinstance(value, str) and value.strip():
            canonical.append(value.strip())
        else:
            raise KsGuardError(
                f"a column name must be a non-empty string, got {value!r} "
                f"({type(value).__name__}); a proposal carrying a name that "
                "is not a name cannot be reviewed, and guessing at it would "
                "be the code review §4.2 says the barrier must not be"
            )
    return tuple(canonical)


def _reject_forbidden(columns: Iterable[str], *, source: Optional[str]) -> None:
    """The one refusal, over any spelling's columns — the shared decision."""
    offenders = [name for name in columns if _is_forbidden(name)]
    if offenders:
        raise IsNullColumnError(_proposal_refusal(offenders, source))


# -- The data spelling ---------------------------------------------------------


def review_node_columns(
    columns: Any, *, source: Optional[str] = None
) -> tuple[str, ...]:
    """Review proposed node-column names, refusing the forbidden one.

    Feature 110's sentence as one call over *data*: ``columns`` is the
    iterable of column names a caller proposes the ``node`` table carry, and
    the call either returns the names canonicalized — stripped, in the
    caller's order, so a reviewer can chain — or raises
    :class:`~nulloracle.errors.IsNullColumnError` naming the offender.
    Nothing is opened, nothing is executed: this is the review a migration
    author, a schema checklist or a store writer runs *before* the proposal
    is applied, which is the moment the feature's own word ("rejects any
    *proposed* node column") places the refusal at.

    ``source`` is optional provenance for the message — the migration's
    filename, the caller's name — so an operator reading the refusal learns
    where the proposal came from, not only what it named.  It changes no
    decision; the comparison is :func:`_is_forbidden` in every spelling.

    A proposal that is not a list of names is
    :class:`~nulloracle.errors.KsGuardError`, the store-contract error, not
    the barrier one: a caller catching ``IsNullColumnError`` is rejecting a
    *schema*, and a caller whose list was malformed should not be told a
    column was forbidden that the review never saw.
    """
    canonical = _validated_column_names(columns)
    _reject_forbidden(canonical, source=source)
    return canonical


# -- The migration spelling ------------------------------------------------------


def _strip_comments(statement: str) -> str:
    """Drop ``--`` line comments, the comment form this workspace's DDL uses.

    Both the member's own schemas and the migrations' ``statements()`` carry
    their per-column commentary as SQL line comments, so the extractor reads
    past them; block comments are not handled because no DDL in this
    workspace uses them, and a parser that quietly accepted a comment form
    it did not understand would be a hole wearing a feature.
    """
    return "\n".join(line.partition("--")[0] for line in statement.splitlines())


def _leading_identifier(text: str) -> "tuple[str, str] | None":
    """The identifier at the head of ``text``, with the remainder after it.

    Handles the three quotings SQL allows an identifier — double quotes,
    backticks and brackets — by returning what they delimit, and a bare
    identifier by matching it whole.  Returns the remainder so the caller
    knows where the name *ends* (a table name must be followed by ``(`` or
    an ``ADD`` clause, and a column name by its type or nothing).  ``None``
    when no identifier starts the text, which is the extractor's answer to
    a fragment it does not recognise: skip it, having matched nothing.
    """
    text = text.lstrip()
    if not text:
        return None
    first = text[0]
    if first in ('"', "`"):
        end = text.find(first, 1)
        if end == -1:
            return None
        return text[1:end], text[end + 1 :]
    if first == "[":
        end = text.find("]", 1)
        if end == -1:
            return None
        return text[1:end], text[end + 1 :]
    match = _BARE_IDENTIFIER.match(text)
    if match is None:
        return None
    return match.group(0), text[match.end():]


def _leading_qualified_name(text: str) -> "tuple[str, str] | None":
    """The dotted identifier chain at the head of ``text`` (``schema.table``).

    A table may arrive qualified by the schema it lives in — ``main.node``,
    ``tree.node`` — so the reader collects the whole chain and hands it to
    :func:`_is_node_table`, which compares the chain's *last* segment.  The
    chain is identifiers joined by single dots and nothing else; a second
    identifier not preceded by a dot ends the name the way one does in
    :func:`_leading_identifier`, and the remainder is returned so the caller
    knows where the name ended (a table name is followed by ``(`` or an
    ``ADD`` clause).  Used for *table* names only — a column name is never
    dotted, so the body readers keep the single-identifier form.
    """
    parsed = _leading_identifier(text)
    if parsed is None:
        return None
    name, rest = parsed
    while rest.lstrip().startswith("."):
        parsed_next = _leading_identifier(rest.lstrip()[1:])
        if parsed_next is None:
            break
        segment, rest = parsed_next
        name = f"{name}.{segment}"
    return name, rest


def _balanced_body(text: str) -> Optional[str]:
    """The inside of the parenthesis ``text`` starts with, nesting-aware.

    A ``CREATE TABLE`` body's own column defaults carry parentheses — the
    node table's UUID default nests four deep — so the body runs to the
    *matching* close, not the first one.  ``None`` when the parentheses
    never balance, which is DDL the extractor declines to guess at.
    """
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[1:index]
    return None


def _split_top_level(body: str) -> "list[str]":
    """Split a ``CREATE TABLE`` body on its top-level commas, nesting-aware.

    The same defaults that make :func:`_balanced_body` nesting-aware put
    commas *inside* the body (``substr('89ab', abs(random()) % 4 + 1, 1)``),
    so a plain ``split(",")`` would tear a column definition in half and
    name its tail a column.  Only commas at depth zero separate columns.
    """
    items: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(body):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(body[start:index])
            start = index + 1
    items.append(body[start:])
    return items


def _create_table_columns(fragment: str) -> "list[str]":
    """The node-table column names a ``CREATE TABLE`` fragment proposes.

    ``CREATE TABLE [IF NOT EXISTS] <table> (<body>)``: the body is split on
    its top-level commas and each item's leading identifier read, with the
    table-constraint keywords skipped — ``PRIMARY KEY (a, b)`` is not a
    column named ``primary``.  Empty when the fragment is not a ``CREATE
    TABLE``, does not name the node table, or carries no body the extractor
    can balance — the extractor matches what it recognises and proposes
    nothing of its own.
    """
    head = _CREATE_TABLE_HEAD.search(fragment)
    if head is None:
        return []
    parsed = _leading_qualified_name(fragment[head.end():])
    if parsed is None:
        return []
    table, remainder = parsed
    if not _is_node_table(table):
        return []
    after = remainder.lstrip()
    if not after.startswith("("):
        return []
    body = _balanced_body(after)
    if body is None:
        return []
    names: list[str] = []
    for item in _split_top_level(body):
        parsed_item = _leading_identifier(item)
        if parsed_item is None:
            continue
        name, _rest = parsed_item
        if name.casefold() in _TABLE_CONSTRAINT_KEYWORDS:
            continue
        names.append(name)
    return names


def _alter_table_columns(fragment: str) -> "list[str]":
    """The node-table column names an ``ALTER TABLE`` fragment proposes.

    ``ALTER TABLE <table> ADD [COLUMN] <name>`` — the shape every column
    migration in this workspace (features 98–101) is made of.  Every ``ADD``
    clause in the fragment is read, so a statement carrying several is
    reviewed whole, and a clause that adds a constraint rather than a column
    (``ADD CONSTRAINT``) is skipped by the same keyword set the ``CREATE``
    reader uses.  Empty when the fragment is not an ``ALTER TABLE`` over the
    node table — a ``RENAME`` or ``DROP`` proposes no column, and a
    ``DROP COLUMN is_null`` *removes* the offender rather than proposing it,
    so it is not a refusal this guard makes.
    """
    head = _ALTER_TABLE_HEAD.search(fragment)
    if head is None:
        return []
    parsed = _leading_qualified_name(fragment[head.end():])
    if parsed is None:
        return []
    table, rest = parsed
    if not _is_node_table(table):
        return []
    names: list[str] = []
    for match in _ADD_COLUMN.finditer(rest):
        parsed_name = _leading_identifier(rest[match.end():])
        if parsed_name is None:
            continue
        name, _rest = parsed_name
        if name.casefold() in _TABLE_CONSTRAINT_KEYWORDS:
            continue
        names.append(name)
    return names


def node_columns_from_ddl(statements: Any) -> tuple[str, ...]:
    """The node-column names proposed by DDL statements, extracted as data.

    The reader half of the migration spelling.  ``statements`` is an
    iterable of DDL strings — a migration's ``statements("sqlite")``, or a
    single string of several statements — and the return is every column
    name the statements would give the ``node`` table, in the order the DDL
    proposes them, with comments read past and nothing executed.  The two
    shapes read are the only two a column can be proposed in: a ``CREATE
    TABLE`` over the node table, and an ``ALTER TABLE`` over it carrying an
    ``ADD`` clause.  Statements about other tables are skipped by name (see
    :func:`_is_node_table`), so a caller may hand the extractor a whole
    migration's DDL and be answered for the tree store alone.

    The extractor is deliberately *small*: it recognises the DDL this
    workspace writes, no dialect beyond it, and proposes nothing of its own
    when it meets something it does not recognise.  That is the honest
    failure — a statement the extractor cannot read returns no column for
    it, and the proposal it carried goes to the data spelling or to the
    audit, never silently blessed.
    """
    if isinstance(statements, str):
        fragments: Iterable[str] = (statements,)
    elif isinstance(statements, bytes) or not isinstance(statements, Iterable):
        raise KsGuardError(
            f"statements must be an iterable of DDL strings, got "
            f"{type(statements).__name__} ({statements!r}); a column proposal "
            "in DDL arrives as the statements a migration would run, and a "
            "value that is not a collection of statements is not a proposal "
            "the extractor could read"
        )
    else:
        fragments = statements
    columns: list[str] = []
    for statement in fragments:
        if not isinstance(statement, str):
            raise KsGuardError(
                f"a DDL statement must be a string, got {statement!r} "
                f"({type(statement).__name__}); the extractor reads proposals "
                "as data and never executes them, so a non-text statement is "
                "a proposal it could not even read"
            )
        # Comments are stripped per statement and the semicolons split
        # afterwards, so a comment cannot smuggle a separator past the
        # reader and a single string of many statements takes the same path
        # as a migration's tuple of one statement each.
        for fragment in _strip_comments(statement).split(";"):
            columns.extend(_create_table_columns(fragment))
            columns.extend(_alter_table_columns(fragment))
    return tuple(columns)


def review_ddl(statements: Any, *, source: Optional[str] = None) -> tuple[str, ...]:
    """Review the node columns DDL proposes, refusing the forbidden one.

    The migration spelling of the review: ``statements`` is what a migration
    exposes as data (its ``statements("sqlite")``, the convention this
    workspace's migrations state — returned rather than executed *"so the
    DDL is inspectable"*, and this is the inspection), the return is the
    node-table columns the DDL proposes, and a proposal naming the forbidden
    column raises :class:`~nulloracle.errors.IsNullColumnError` before any
    of it is applied.  Nothing is opened and nothing is executed — the
    review is over the *text*, which is what makes it runnable in CI over
    every migration the repository ships.

    ``source`` is optional provenance for the message (a migration's
    filename), so an operator reading a refusal from a CI log learns which
    proposal to fix rather than only what it named.

    The review answers for the ``node`` table's statements alone — the
    module's stated boundary — so a caller auditing a whole migration file
    gets the tree store's decision and nothing else.  See
    :func:`node_columns_from_ddl` for what is read and what is skipped.
    """
    columns = node_columns_from_ddl(statements)
    _reject_forbidden(columns, source=source)
    return columns


# -- The audit as a value -------------------------------------------------------


@dataclass(frozen=True)
class SchemaAudit:
    """What the tree store's ``node`` table actually declares.

    The standing audit's read half, as a value: ``columns`` is what
    ``PRAGMA table_info`` answered — the table's *declared* columns, in
    declaration order, in the spellings the schema carries — and the two
    properties answer §7.1's question over them.  Frozen and validated in
    ``__post_init__`` rather than only where built, because the value is a
    record of a read and a record that could carry a non-name would misstate
    the schema it claims to describe — the same discipline
    :class:`~nulloracle.ksguard.KsGuardRecord` states for a stored reading.

    :meth:`require` is the refusal, so the read and the decision are two
    spellings of one fact: a caller may hold the audit (read the columns,
    log them) and only the caller about to *rely* on the barrier need call
    ``require()`` — the same seam
    :meth:`nulloracle.preservation.PreservationReport.require` states for a
    null series about to be served.
    """

    #: The node table's declared column names, in declaration order, as the
    #: schema spells them.  Empty means the store holds no ``node`` table —
    #: a table SQLite created always declares at least one column, so the
    #: empty answer is the no-table answer and not a table with no columns.
    columns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in self.columns:
            if not isinstance(name, str) or not name.strip():
                raise KsGuardError(
                    f"a declared column name must be a non-empty string, got "
                    f"{name!r} ({type(name).__name__}); an audit is a record "
                    "of what the store declares, and a record carrying a name "
                    "that is not a name describes no schema this member "
                    "could have read"
                )

    @property
    def forbidden_columns(self) -> tuple[str, ...]:
        """The declared columns that are the forbidden one, by SQLite's rules.

        Usually empty; when it is not, the barrier is already broken, and
        the spellings are as declared so :meth:`require` can name the one to
        drop.
        """
        return tuple(name for name in self.columns if _is_forbidden(name))

    @property
    def holds(self) -> bool:
        """Whether §7.1's rule holds over this table: no forbidden column."""
        return not self.forbidden_columns

    def require(self) -> "SchemaAudit":
        """Return this audit, or refuse it by name — the standing audit's seam.

        The refusal is :class:`~nulloracle.errors.IsNullColumnError`, the
        barrier's own error rather than the store's, because a caller
        catching it is not investigating a broken connection: it is learning
        the one column the method forbids is present, which §4.2 says
        *"silently voids all calibration"* — and the audit will not be the
        thing that stays silent about it.  Present is not reported; it is
        refused, because §7.1's rule is *"absent"*, and a report would leave
        the reader to notice.
        """
        offenders = list(self.forbidden_columns)
        if offenders:
            raise IsNullColumnError(_presence_refusal(offenders))
        return self

    def to_payload(self) -> "dict[str, Any]":
        """The audit as a plain mapping, for a log line or an operator's report.

        The field names are the audit's own, the same discipline the
        member's other records state: a rendered mapping and a structured
        log record name the same things the same way, and ``holds`` rides
        along so a log reader never has to re-derive it from the list.
        """
        return {
            "table": NODE_TABLE,
            "columns": list(self.columns),
            "holds": self.holds,
        }


# -- The store ------------------------------------------------------------------


class TreeStoreGuard:
    """The standing audit over the tree store: does ``node`` still hold no bit?

    Constructed with the database URL it reads; :meth:`columns` answers the
    ``node`` table's declared columns, and :meth:`audit` answers
    :class:`SchemaAudit` — refusing, through the record's own
    :meth:`SchemaAudit.require`, when the forbidden column is among them.
    The class resolves its path lazily, so constructing one performs no I/O
    — composition-time work must not touch the disk, the contract every
    store in this workspace states.

    The guard opens the store **read-only** and creates nothing: a check
    must not mutate what it checks, and a guard whose audit created the
    ``node`` table would be blessing a schema it just made.  A database
    file that does not exist holds no node table, so absence holds trivially
    and the audit answers the empty column set — the same true-but-thin
    answer the planning gate gives an absent sidecar.  A database that
    exists but will not open raises :class:`~nulloracle.errors.KsGuardError`
    rather than answering, because an uncheckable barrier must never read
    as a held one.

    The guard holds no labels and reads no rows: the audit is over the
    schema, not the data, and ``PRAGMA table_info`` is the whole of its
    contact with the store.  There is no field here that could leak a label
    partition, deliberately — see the module docstring and §4.2.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise KsGuardError(f"{DATABASE_URL_ENV} must be a non-empty database URL")
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # guard is composition-time work and must not touch the disk.
        self._path: Optional[Path] = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: "Mapping[str, str] | None" = None
    ) -> "TreeStoreGuard | None":
        """The guard ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no guard component — a discoverable state, not an exception — while
        the deployment that must audit its tree store's schema is the caller
        that must not find itself in it.  **This method never raises**, the
        stance every store in this member states: the factory builds every
        registered component on every
        :func:`~app.module_loader.create_app` call, so a builder that raised
        would take composition down for every unrelated feature.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this guard reads from."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this guard, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    # -- The read ------------------------------------------------------------

    def columns(self) -> tuple[str, ...]:
        """The ``node`` table's declared column names, read read-only.

        ``PRAGMA table_info`` is the whole of the read: the audit asks what
        the table *declares* — not what any query happens to select, which
        is the distinction §7.1 draws between absent and ``SELECT``-excluded
        — and SQLite answers it without touching a row.  The connection is
        opened with ``mode=ro``, so a guard whose path pointed at a store
        that did not exist would fail to open rather than create it, and
        the *file-absent* case is answered before that: a database that does
        not exist holds no node table, so the empty tuple is the true
        answer, the same answer a store with no ``node`` table yet gives.

        Raises :class:`~nulloracle.errors.KsGuardError` when the store
        exists but will not open or answer — a barrier that could not be
        checked must never read as one that holds.
        """
        path = self.path
        if not path.exists():
            return ()
        try:
            with closing(self._read_only_connect(path)) as connection:
                rows = connection.execute(
                    f"PRAGMA table_info({NODE_TABLE})"
                ).fetchall()
        except sqlite3.Error as exc:
            raise KsGuardError(
                f"the tree store at {path} could not be audited: {exc}; the "
                "standing audit reads the store's declared schema and "
                "refuses to answer when it cannot, because a barrier that "
                "could not be checked must never read as one that holds"
            ) from exc
        return tuple(str(row[1]) for row in rows)

    @staticmethod
    def _read_only_connect(path: Path) -> sqlite3.Connection:
        """Open the store read-only — the audit never mutates what it audits.

        SQLite's URI ``mode=ro`` refuses to create the file and refuses to
        write an existing one, which is the property the audit stands on: a
        guard that could create the ``node`` table would be blessing a
        schema it just made.  The path is percent-quoted so a directory
        name carrying URI-significant characters cannot redirect the open.
        """
        return sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)

    # -- Feature 110: the standing audit --------------------------------------

    def audit(self) -> SchemaAudit:
        """Audit the tree store's schema for §7.1's rule, refusing a break.

        The standing spelling of feature 110's decision: the declared
        columns are read (:meth:`columns`), the read becomes a
        :class:`SchemaAudit`, and the record's own
        :meth:`SchemaAudit.require` either returns it — the barrier holds —
        or raises :class:`~nulloracle.errors.IsNullColumnError` with the
        ``is_null_column`` message naming the spelling to drop.  The audit
        is over the *schema* and never the rows: §7.1's rule is about what
        the table declares, and the labels — if the barrier holds — are the
        sidecar's alone.

        Idempotent by construction: the audit writes nothing, so running it
        hourly, nightly or before every campaign changes no store and can
        be repeated freely.
        """
        return SchemaAudit(columns=self.columns()).require()


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract
    — the same spelling the fraction's, the flip depth's, the selection's
    and the gate's stores state.  A non-SQLite scheme is refused loudly, and
    a pathless (in-memory) URL is refused too: an in-memory database would
    die with the connection that opened it, and an audit of a store that
    vanishes is a verdict nothing could replay.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise KsGuardError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            "database would die with the connection that opened it, and a "
            "tree store audited against one would be a barrier nothing could "
            "re-check"
        )
    return Path(path)


def audit_tree_store(
    *,
    database_url: Optional[str] = None,
    env: "Mapping[str, str] | None" = None,
) -> SchemaAudit:
    """Audit the tree store's schema — the module-level spelling.

    Feature 110's standing half as one call: the store is resolved from
    ``database_url``, else from ``DATABASE_URL``, and the audit answers for
    the tree store it names.  A deployment that names neither is refused
    *by name* rather than silently answering, because an audit that quietly
    skipped itself would leave the store looking guarded while nothing
    looked at it — which is the exact failure mode the refusal exists to
    rule out.

    An :class:`~nulloracle.errors.IsNullColumnError` from the audit is left
    to propagate unwrapped — it is the feature's own refusal, and the caller
    catching it is the operator learning the barrier is broken — while the
    store's own failures arrive as :class:`~nulloracle.errors.KsGuardError`,
    exactly as :meth:`TreeStoreGuard.audit` states.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise KsGuardError(
            f"audit_tree_store audits the tree store's schema for the "
            f"forbidden column and nothing names a store: {DATABASE_URL_ENV} "
            "is unset (and no database_url was supplied), so §7.1's rule "
            "could not be checked. An audit that quietly skipped itself "
            "would leave the store looking guarded while nothing looked at "
            "it — the exact failure this feature exists to rule out"
        )
    return TreeStoreGuard(url).audit()
