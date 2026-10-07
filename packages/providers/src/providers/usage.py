"""Feature 5 of additions_spec_llm_usage_tracking.xml: the usage-reporting CLI.

*System reports spend from* ``python -m providers.usage [--campaign ID]
[--by campaign|pin|role|node]`` *and displays one JSON line per group plus a
total line.* Feature 3 (:mod:`providers._usage_store`) gave every provider
call a stored row, priced and attributed to a campaign, node, role and pin;
nothing before this module could answer "how much has this campaign spent?"
from the command line without opening the sqlite file by hand. This is that
answer, following the same house CLI shape ``orchestrator.dream`` and
``orchestrator.closeout`` already use: ``main(argv=None, *, env=None,
emit=print) -> int``, exit 0/1/2, one JSON line per row, one stderr line per
refusal opening with a greppable code word, never a traceback.

Why the grouping is done here, not in :class:`~providers._usage_store.UsageStore`
--------------------------------------------------------------------------------

:meth:`~providers._usage_store.UsageStore.totals` sums over the *whole*
store; it carries no ``campaign_id`` filter, because feature 3 had no reason
to want one. This command's ``--campaign`` narrows the report to one
campaign's rows while still grouping by any of the four attribution columns
(including ``campaign_id`` itself, trivially: one group, the campaign
named). Rather than widen feature 3's store with a filter it does not
otherwise need, this module reads every row once with
:meth:`~providers._usage_store.UsageStore.rows`, narrows it to the requested
campaign in Python, and groups the narrowed set itself — the same sum/count
bucketing :meth:`UsageStore.totals` does, scoped to whatever ``--campaign``
and ``--by`` were asked for.

Why ``--campaign latest`` needs no second read
------------------------------------------------

:meth:`~providers._usage_store.UsageStore.rows` answers oldest row first
(insertion order). The most recently recorded row's ``campaign_id`` is, by
construction, the most recently active campaign — so "latest" is resolved
from the same single read this command already made, as the last element's
attribution, rather than a second query naming "the newest campaign" as a
concept the store would otherwise have no reason to carry.

Why an empty result still prints a total line
------------------------------------------------

A store with no rows, or a ``--campaign`` naming one with none, is not a
refusal — it is a true report: nothing has been spent. The total line still
prints, with every count at zero and ``est_cost_usd`` ``None`` (never a
guessed zero that would look like a free campaign's real figure), so a
caller scripting against this command's output always gets exactly one
total line, whether or not any group line preceded it.

How a group line and the total line are told apart
------------------------------------------------------

Every group line carries the ``--by`` column's own name (``campaign_id``,
``pin``, ``role`` or ``node_id``) beside its figures; the total line never
does, because it is not keyed to one value of that column. The total line
is the one line this module adds ``price_table_version`` to — the feature's
own word for the total line's one extra field — which doubles as a cheap
key for a reader to pick the total out of a stream of JSON lines without
otherwise distinguishing the two shapes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from ._prices import PRICE_TABLE_VERSION
from ._usage_store import UsageRow, UsageStore, UsageStoreError

__all__ = [
    "DATABASE_URL_ENV",
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "LATEST_CAMPAIGN",
    "USAGE_CODE",
    "main",
]

#: The greppable word this module's own refusals open with.
USAGE_CODE = "usage"

#: The environment variable naming the relational store -- the one spelling
#: every store and CLI in this workspace already uses.
DATABASE_URL_ENV = "DATABASE_URL"

#: The one ``--campaign`` value that is not a literal campaign id: it asks
#: this command to resolve the most recently recorded campaign itself.
LATEST_CAMPAIGN = "latest"

#: Nothing to read: a fresh store, or a campaign filter matching no row.
EXIT_OK = 0
#: A collaborator refused -- a malformed ``DATABASE_URL`` this store cannot
#: open or read (an unsupported scheme, a locked file).
EXIT_REFUSED = 1
#: Missing configuration: no ``DATABASE_URL``.
EXIT_CONFIG = 2

#: ``--by``'s four spellings, mapped to the column of
#: :class:`~providers._usage_store.UsageRow` each one groups by.
_BY_COLUMNS: dict[str, str] = {
    "campaign": "campaign_id",
    "pin": "pin",
    "role": "role",
    "node": "node_id",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m providers.usage",
        description=(
            "Report locally recorded LLM spend (feature 3's "
            "provider_call_usage table): one JSON line per group, plus a "
            "total line."
        ),
    )
    parser.add_argument(
        "--campaign",
        default=None,
        metavar="ID",
        help=(
            "only report this campaign's rows; 'latest' selects the most "
            "recently recorded campaign. Default: every campaign."
        ),
    )
    parser.add_argument(
        "--by",
        choices=tuple(_BY_COLUMNS),
        default="campaign",
        help="the column to group rows by (default: campaign)",
    )
    return parser


def _empty_bucket() -> dict[str, Any]:
    return {
        "calls": 0,
        "input_tokens": 0,
        "cache_write_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 0,
        "_priced_total": Decimal(0),
        "_priced_calls": 0,
        "unpriced_calls": 0,
    }


def _accumulate(bucket: dict[str, Any], row: UsageRow) -> None:
    bucket["calls"] += 1
    bucket["input_tokens"] += row.input_tokens
    bucket["cache_write_tokens"] += row.cache_write_tokens
    bucket["cache_read_tokens"] += row.cache_read_tokens
    bucket["output_tokens"] += row.output_tokens
    if row.est_cost_usd is None:
        bucket["unpriced_calls"] += 1
    else:
        bucket["_priced_calls"] += 1
        bucket["_priced_total"] += row.est_cost_usd


def _bucket_payload(bucket: dict[str, Any]) -> dict[str, Any]:
    priced_total: Decimal = bucket["_priced_total"]
    est_cost = priced_total if bucket["_priced_calls"] else None
    return {
        "calls": bucket["calls"],
        "input_tokens": bucket["input_tokens"],
        "cache_write_tokens": bucket["cache_write_tokens"],
        "cache_read_tokens": bucket["cache_read_tokens"],
        "output_tokens": bucket["output_tokens"],
        "est_cost_usd": None if est_cost is None else str(est_cost),
        "unpriced_calls": bucket["unpriced_calls"],
    }


def _group_lines(rows: Sequence[UsageRow], column: str) -> list[dict[str, Any]]:
    """One payload per distinct value of ``column``, in first-seen order.

    First-seen rather than sorted, on :meth:`UsageStore.totals`' own
    precedent: the grouped column may hold ``None`` (an unattributed
    ``node_id``), which no total order compares against a string.
    """
    order: list[Any] = []
    buckets: dict[Any, dict[str, Any]] = {}
    for row in rows:
        key = getattr(row, column)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = _empty_bucket()
            buckets[key] = bucket
            order.append(key)
        _accumulate(bucket, row)
    lines: list[dict[str, Any]] = []
    for key in order:
        payload: dict[str, Any] = {column: key}
        payload.update(_bucket_payload(buckets[key]))
        lines.append(payload)
    return lines


def _total_line(rows: Sequence[UsageRow]) -> dict[str, Any]:
    bucket = _empty_bucket()
    for row in rows:
        _accumulate(bucket, row)
    payload = _bucket_payload(bucket)
    payload["price_table_version"] = PRICE_TABLE_VERSION
    return payload


def _select_rows(
    all_rows: tuple[UsageRow, ...], requested_campaign: str | None
) -> tuple[UsageRow, ...]:
    """Every row of ``all_rows`` belonging to the requested campaign.

    ``requested_campaign=None`` (no ``--campaign``) answers every row
    unchanged. :data:`LATEST_CAMPAIGN` resolves to the campaign named by
    ``all_rows``' own last element -- the most recently recorded row -- or
    to no campaign at all when the store holds nothing, which then narrows
    to no rows below, the same empty result an unknown literal id produces.
    """
    if requested_campaign is None:
        return all_rows
    if requested_campaign == LATEST_CAMPAIGN:
        target = all_rows[-1].campaign_id if all_rows else None
    else:
        target = requested_campaign
    return tuple(row for row in all_rows if row.campaign_id == target)


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m providers.usage [--campaign ID] [--by campaign|pin|role|node]``.

    ``env`` and ``emit`` are this command's seams, taken exactly as the
    other operator CLIs in this workspace take them: ``env`` is where
    ``DATABASE_URL`` is read from (the process environment when ``None``),
    and ``emit`` is what each JSON line is printed with, one call per line
    -- every group line first (in :meth:`UsageStore.rows`' own first-seen
    order), then the total line last.
    """
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    source = os.environ if env is None else env

    database_url = source.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        print(
            f"{USAGE_CODE}: {DATABASE_URL_ENV} must name the database "
            "usage rows are read from",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    store = UsageStore(database_url)
    try:
        all_rows = store.rows()
    except UsageStoreError as exc:
        print(f"{USAGE_CODE}: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    rows = _select_rows(all_rows, arguments.campaign)

    if rows:
        column = _BY_COLUMNS[arguments.by]
        for line in _group_lines(rows, column):
            emit(json.dumps(line))
    emit(json.dumps(_total_line(rows)))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
