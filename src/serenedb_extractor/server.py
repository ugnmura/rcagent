"""MCP server: tool registration, uniform error handling, stdio entry point."""

import logging
import os
import sys
import threading
from collections.abc import Callable
from typing import Any

import anyio.to_thread
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from serenedb_extractor import evidence
from serenedb_extractor import format as fmt
from serenedb_extractor.config import ConfigError, Settings
from serenedb_extractor.context import AppContext
from serenedb_extractor.instructions import SERVER_INSTRUCTIONS
from serenedb_extractor.prompts import register_prompts
from serenedb_extractor.query import stats
from serenedb_extractor.tools import aggregate, catalog_tools, describe, evidence_tools, lookup, setup_tools
from serenedb_extractor.tools import context as context_tool
from serenedb_extractor.tools import investigate
from serenedb_extractor.tools import sql as sql_tool
from serenedb_extractor.tools import survey as survey_tool
from serenedb_extractor.tools import trend as trend_tool

SINGLE_ROLE_NOTE = (
    "Note: only a reader URL was configured, so SereneDB is not enforcing read-only limits "
    "on this connection. Set SERENEDB_WRITER_URL and use a SELECT-only role for the reader to enforce them."
)


# Tools whose result is not a measurement (it shows earlier evidence, or changes only names).
NO_EVIDENCE = frozenset({"show_evidence", "rename_parameter"})


def _per_call(fn: Callable[..., str], kw: dict[str, Any]) -> str:
    """One tool call, with scope statistics remembered for its duration (query/stats.py)."""
    with stats.per_call():
        return fn(**kw)


class ToolRunner:
    """Owns the lazily built AppContext and the one-time note; every tool goes through it."""

    def __init__(self, ctx_factory: Callable[[], AppContext]) -> None:
        self._factory = ctx_factory
        self._lock = threading.Lock()
        self._ctx: AppContext | None = None
        self._noted = False

    def ctx(self) -> AppContext:
        with self._lock:
            if self._ctx is None:
                self._ctx = self._factory()
            return self._ctx

    async def call_tool(self, name: str, fn: Callable[..., str], /, **kw: Any) -> str:
        """Run a blocking tool body off the event loop; any failure becomes one plain line.

        The process's first result, success or error, also carries the single-role note.
        """
        try:
            out = await anyio.to_thread.run_sync(lambda: _per_call(fn, kw))
        except Exception as exc:
            out = fmt.plain_error(exc, name)
        with self._lock:
            if self._ctx is not None and self._ctx.settings.single_role and not self._noted:
                self._noted = True
                out += "\n" + SINGLE_ROLE_NOTE
        return out

    async def run_tool(self, fn: Callable[..., str], /, **kw: Any) -> str:
        """Register tools with this: it injects the AppContext (`fn(ctx, **kw)`) and routes through call_tool.

        The queries the call runs are recorded with its result in the evidence log, and the result ends
        with an evidence footer (the Q<n> handle and the queries), so every number can be checked."""
        name = fn.__name__

        def body(**k: Any) -> str:
            ctx = self.ctx()
            with evidence.collecting() as queries:
                try:
                    out = fn(ctx, **k)
                except Exception as exc:
                    # A failure after queries ran (e.g. a timeout) keeps its evidence too: which query ran
                    # how long is what tells why it failed.
                    if name in NO_EVIDENCE or not queries:
                        raise
                    out = fmt.plain_error(exc, name)
            if name in NO_EVIDENCE:
                return out
            rec = ctx.evidence.record(name, k, queries, out)
            return out + "\n" + evidence.footer(rec)

        return await self.call_tool(name, body, **kw)


def register_tools(mcp: FastMCP, runner: ToolRunner) -> None:
    # Descriptions follow one shape so the agent can choose: what it does, when to use it, inputs, returns.
    # Shared input conventions (log_table, start/end, filters, timezone, confirmed_cost) are explained once
    # in the server instructions.

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def describe_logs(
        log_table: str | None = None,
        find_values: dict[str, str] | None = None,
        start: str | None = None,
        end: str | None = None,
        timezone: str | None = None,
        confirmed_cost: str | None = None,
    ) -> str:
        """Orientation: which log tables exist and what is in them. START HERE in every conversation.
        Use when: you need the table name, its time range (to pick a period), the fields it has (level, component, team, host, service, trace), how a value is spelled, or which context scopes exist.
        Inputs: log_table (omit for all); find_values={"<role or column>": "<word>"} lists the actual values containing a word (e.g. {"level": "err"}) — do this before filtering on a value you have not seen.
        Returns: per table — source, field roles, entry count, time zone, time range, context scopes, sampled top values of level/component/team; or the matching values with counts."""
        return await runner.run_tool(
            describe.describe_logs,
            log_table=log_table,
            find_values=find_values,
            start=start,
            end=end,
            timezone=timezone,
            confirmed_cost=confirmed_cost,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def count_logs(
        log_tables: list[str] | None = None,
        group_by: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        filters: dict[str, Any] | None = None,
        text: str | None = None,
        limit: int | None = None,
        timezone: str | None = None,
        confirmed_cost: str | None = None,
    ) -> str:
        """Exact counts of log entries, grouped — the aggregation for "how many / which team / which component / per day".
        Use when: a team lead or manager needs counts by team, component, level or time; you need whole-corpus numbers across several log tables (omit log_tables = all of them, each counted separately and reported together); or you want to count how often a word appears (text) per component or per day. Needs no templates, so it can come before survey.
        Inputs: group_by up to 3 of: team, component, level, host, service, trace, any column, or a time bucket time:<n>m|h|d (e.g. time:1d, time:7d for weeks); filters e.g. {"level": ["FATAL","ERROR"], "team": "Node OS"}; text = words the message must contain (any case); limit = groups shown per table (default 25).
        Returns: per table the matching total and each group's count and share, largest first (by time for time buckets), "showing N of M groups" when cut, and a combined line per group value shared by several tables. Exact unless it says it is an estimate."""
        return await runner.run_tool(
            aggregate.count_logs,
            log_tables=log_tables,
            group_by=group_by,
            start=start,
            end=end,
            filters=filters,
            text=text,
            limit=limit,
            timezone=timezone,
            confirmed_cost=confirmed_cost,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def survey(
        log_table: str,
        start: str | None = None,
        end: str | None = None,
        filters: dict[str, Any] | None = None,
        exclude: list[str] | None = None,
        sample_size: int | None = None,
        limit: int | None = None,
        timezone: str | None = None,
        confirmed_cost: str | None = None,
    ) -> str:
        """Groups the messages of a period into recurring templates ("data TLB error interrupt", "timeout after <NUM> ms") with counts — the first step for "what keeps happening" and "what kinds of errors are there".
        Use when: you need to know WHICH problems occur before counting or tracing them; every template-based tool (locate_occurrences, extract_params, trend) needs the T<n> IDs this returns.
        Inputs: filters e.g. {"level": "FATAL"} or {"team": "Cloud API"}; exclude = template IDs to hide so rarer ones surface; limit = templates shown (default 30). Small scopes are read completely (exact); big ones are sampled (estimates).
        Returns: templates ranked by count with share, top components, an example message each, NEW for templates first seen now. Template IDs are stable across calls."""
        return await runner.run_tool(
            survey_tool.survey,
            log_table=log_table,
            start=start,
            end=end,
            filters=filters,
            exclude=exclude,
            sample_size=sample_size,
            limit=limit,
            timezone=timezone,
            confirmed_cost=confirmed_cost,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def search_logs(
        log_table: str,
        start: str | None = None,
        end: str | None = None,
        filters: dict[str, Any] | None = None,
        text: str | None = None,
        fuzzy: bool = False,
        order: str = "newest",
        limit: int | None = None,
        timezone: str | None = None,
        confirmed_cost: str | None = None,
    ) -> str:
        """Full-text search: the actual log entries matching words and/or field filters in a time window — the engineer's evidence.
        Use when: you need to quote real error messages, find the entries behind a count, or look for a word or phrase (e.g. "timeout", "parity error") in a period. Not for counting how often something happens — use count_logs or locate_occurrences for that; a page of examples says nothing about frequency.
        Inputs: text = words the message contains, any case, as a phrase; fuzzy=True also matches near-misses (needs a search index); filters e.g. {"level": "ERROR", "component": "nova.compute.manager"}; order newest|oldest; limit = entries shown (default 50).
        Returns: the total number of matching entries, then up to limit entries with time, fields (incl. team), message, template tag and an occurrence ID (e:<n>) to pass to get_context; says when the list is cut."""
        return await runner.run_tool(
            lookup.search_logs,
            log_table=log_table,
            start=start,
            end=end,
            filters=filters,
            text=text,
            fuzzy=fuzzy,
            order=order,
            limit=limit,
            timezone=timezone,
            confirmed_cost=confirmed_cost,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_context(
        log_table: str,
        occurrence: str,
        scope: str | list[str] | None = None,
        window_minutes: float = 5.0,
        before: int = 10,
        after: int = 10,
        filters: dict[str, Any] | None = None,
        timezone: str | None = None,
        confirmed_cost: str | None = None,
    ) -> str:
        """What happened just before and after one entry — the nearby events an engineer needs to explain a failure.
        Use when: you have an occurrence ID (e:<n> from search_logs or locate_occurrences) and want the lead-up and aftermath on the same request, node or service.
        Inputs: scope = which neighbours count: default the narrowest available (same trace/request, else same service and host); "everything" or a list of trace/service/host/component widens it; window_minutes either side (default 5); before/after = entries shown each side (default 10).
        Returns: the entries in time order with the occurrence marked →, each with its time offset, fields and template tag; long messages shortened."""
        return await runner.run_tool(
            context_tool.get_context,
            log_table=log_table,
            occurrence=occurrence,
            scope=scope,
            window_minutes=window_minutes,
            before=before,
            after=after,
            filters=filters,
            timezone=timezone,
            confirmed_cost=confirmed_cost,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def locate_occurrences(
        log_table: str,
        templates: list[str],
        start: str | None = None,
        end: str | None = None,
        filters: dict[str, Any] | None = None,
        group_by: list[str] | None = None,
        examples_per_group: int = 3,
        limit: int | None = None,
        timezone: str | None = None,
        confirmed_cost: str | None = None,
    ) -> str:
        """Exact counts of chosen templates, broken down by where and when — "on which nodes / teams / days does this error happen".
        Use when: survey found the problems that matter and you need their exact counts per team, component, host or time bucket, plus example entries to open with get_context.
        Inputs: templates = T<n> IDs from survey (required); group_by e.g. ["team"], ["host"], ["component", "time:1d"]; examples_per_group (default 3); limit = groups per template (default 20).
        Returns: per template its total and per-group counts, largest first (by time for buckets), with example occurrence IDs; says when groups are cut."""
        return await runner.run_tool(
            investigate.locate_occurrences,
            log_table=log_table,
            templates=templates,
            start=start,
            end=end,
            filters=filters,
            group_by=group_by,
            examples_per_group=examples_per_group,
            limit=limit,
            timezone=timezone,
            confirmed_cost=confirmed_cost,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def trend(
        log_table: str,
        start: str | None = None,
        end: str | None = None,
        templates: list[str] | None = None,
        bucket: str = "day",
        exact: bool = False,
        filters: dict[str, Any] | None = None,
        top_n: int | None = None,
        timezone: str | None = None,
        confirmed_cost: str | None = None,
    ) -> str:
        """Is a problem rising, falling, new or persistent? Compares templates over a period with the preceding period of equal length.
        Use when: a team lead or manager asks what recurs, what got worse, or what to prioritise; run after survey.
        Inputs: start and end (required); templates = T<n> IDs (default: the catalog's largest top_n); bucket hour|day; exact=True counts every entry (default estimates).
        Returns: per template the count per bucket, change against the preceding period, on how many buckets it was present (persistence), and the components and teams affected. Marks the comparison limited when the data does not cover the earlier period — then nothing may be called new."""
        return await runner.run_tool(
            trend_tool.trend,
            log_table=log_table,
            templates=templates,
            start=start,
            end=end,
            bucket=bucket,
            exact=exact,
            filters=filters,
            top_n=top_n,
            timezone=timezone,
            confirmed_cost=confirmed_cost,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def extract_params(
        log_table: str,
        template: str,
        start: str | None = None,
        end: str | None = None,
        filters: dict[str, Any] | None = None,
        by: str | None = None,
        limit: int | None = None,
        timezone: str | None = None,
        confirmed_cost: str | None = None,
    ) -> str:
        """The varying values inside one template — which node, which status code, how long the timeouts were.
        Use when: a template's placeholders (<NUM>, <IP>, <HEX>) hide the detail you need, e.g. the distribution of latencies or which addresses fail.
        Inputs: template = one T<n> ID; by = a role or column to break it down per value (e.g. "team"); limit = values per parameter (default 10).
        Returns: per parameter the top values with counts and, for numbers, min, p50, p95 and max."""
        return await runner.run_tool(
            investigate.extract_params,
            log_table=log_table,
            template=template,
            start=start,
            end=end,
            filters=filters,
            by=by,
            limit=limit,
            timezone=timezone,
            confirmed_cost=confirmed_cost,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def show_evidence(ids: list[str] | None = None, include_result: bool = True) -> str:
        """The executed queries and results behind earlier answers, for checking — every other tool's result ends with an evidence handle [Q<n>].
        Use when: the user asks how a number was obtained or to see the queries, or when you write the "Evidence" section of an answer.
        Inputs: ids = Q<n> handles (omit to list the recent ones); include_result=False shows only the queries.
        Returns: per handle the tool and arguments, every query that ran with its time and row count, and the result it produced."""
        return await runner.run_tool(evidence_tools.show_evidence, ids=ids, include_result=include_result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def inspect_source(source: str, format_hint: str | None = None, line_format: str | None = None) -> str:
        """Look at a log source before setting it up; changes nothing.
        Use when: the user points at a new file, URL or table and you need its columns, size and proposed field roles.
        Inputs: source = a Parquet/JSON file or URL (several remote files as part_{000..009}.parquet), a raw .log file, or a table name; format_hint parquet|json|table|raw; line_format for raw logs (bgl, openstack, generic).
        Returns: columns, sample entries, size and row count from metadata, proposed field roles with the reason for each, and index size estimates."""
        return await runner.run_tool(
            setup_tools.inspect_source, source=source, format_hint=format_hint, line_format=line_format
        )

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def setup_log_table(
        name: str,
        source: str,
        roles: dict[str, str | None] | None = None,
        line_format: str | None = None,
        timezone: str | None = None,
        build_filter_index: bool = False,
        build_search_index: bool = False,
    ) -> str:
        """Register a log source as a log table so the other tools can query it. Parquet/JSON (local or remote URL) is read in place — nothing is downloaded; raw text logs are parsed and copied.
        Use when: the user wants new logs analysed. Re-running on an existing name only corrects roles or the time zone.
        Inputs: name (lowercase); source as for inspect_source (several remote files: part_{000..009}.parquet); roles = {"timestamp": col, "message": col, "level": col, "component": col, "service": col, "host": col, "trace": col} to confirm or correct the proposal; timezone (IANA) for timestamps without a zone: default the line format's own zone where it has one (bgl: America/Los_Angeles), else UTC; build_filter_index / build_search_index only when the user asks.
        Returns: the field roles, entry count, files, size, how long setup took and index estimates. Teams come from the ownership table automatically when it covers the table."""
        return await runner.run_tool(
            setup_tools.setup_log_table,
            name=name,
            source=source,
            roles=roles,
            line_format=line_format,
            timezone=timezone,
            build_filter_index=build_filter_index,
            build_search_index=build_search_index,
        )

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def create_index(log_table: str, kind: str, dry_run: bool = False) -> str:
        """Build an index so repeated questions on a big log table answer faster. Only when the user asks for one.
        Use when: the user wants faster filters (kind="filter": exact value lists, nearly free filters) or faster/fuzzy text search (kind="search"), or asks what an index would cost (dry_run=True: a trial build on a sample, nothing kept).
        Returns: the index's size on disk and build time (measured, or estimated for dry_run)."""
        return await runner.run_tool(setup_tools.create_index, log_table=log_table, kind=kind, dry_run=dry_run)

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def drop_index(log_table: str, kind: str) -> str:
        """Remove an index built with create_index, e.g. when an investigation is over, to free its disk space.
        Inputs: kind = "filter" or "search".
        Returns: what was dropped (nothing changes when the log table has no such index)."""
        return await runner.run_tool(setup_tools.drop_index, log_table=log_table, kind=kind)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def rename_parameter(log_table: str, template: str, old_name: str, new_name: str) -> str:
        """Give a template's parameter a clearer name, permanently (later surveys keep it).
        Inputs: template = T<n>; old_name as shown by extract_params; new_name lowercase letters, digits, underscores.
        Returns: the template with its parameter names."""
        return await runner.run_tool(
            catalog_tools.rename_parameter,
            log_table=log_table,
            template=template,
            old_name=old_name,
            new_name=new_name,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def run_sql(
        sql: str, limit: int | None = None, timeout_s: float | None = None, confirmed_cost: str | None = None
    ) -> str:
        """Last resort: one read-only SQL statement (SELECT, WITH, EXPLAIN) when no other tool can answer, e.g. a latency percentile over a column of the OpenStack table. Prefer the tools above: they check cost, label estimates and diagnose empty results.
        Inputs: sql (log tables are views extractor.lt_<name>; ownership rules are in extractor.ownership); limit = rows shown (default 50).
        Returns: the rows, cut to limit (says so); a too-expensive plan answers TOO EXPENSIVE with a confirmed_cost."""
        return await runner.run_tool(
            sql_tool.run_sql, sql=sql, limit=limit, timeout_s=timeout_s, confirmed_cost=confirmed_cost
        )


def build_server(ctx_factory: Callable[[], AppContext]) -> FastMCP:
    mcp = FastMCP("serenedb-extractor", instructions=SERVER_INSTRUCTIONS)
    runner = ToolRunner(ctx_factory)
    register_tools(mcp, runner)
    register_prompts(mcp)
    return mcp


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    try:
        settings = Settings.from_env(os.environ)
    except ConfigError as exc:
        print(f"serenedb-extractor: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    build_server(lambda: AppContext.from_settings(settings)).run(transport="stdio")


if __name__ == "__main__":
    main()
