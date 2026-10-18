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

from serenedb_extractor import format as fmt
from serenedb_extractor.config import ConfigError, Settings
from serenedb_extractor.context import AppContext
from serenedb_extractor.instructions import SERVER_INSTRUCTIONS
from serenedb_extractor.prompts import register_prompts
from serenedb_extractor.query import stats
from serenedb_extractor.tools import catalog_tools, describe, lookup, setup_tools
from serenedb_extractor.tools import context as context_tool
from serenedb_extractor.tools import investigate
from serenedb_extractor.tools import sql as sql_tool
from serenedb_extractor.tools import survey as survey_tool
from serenedb_extractor.tools import trend as trend_tool

SINGLE_ROLE_NOTE = (
    "Note: only a reader URL was configured, so SereneDB is not enforcing read-only limits "
    "on this connection. Set SERENEDB_WRITER_URL and use a SELECT-only role for the reader to enforce them."
)


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
        """Register tools with this: it injects the AppContext (`fn(ctx, **kw)`) and routes through call_tool."""
        return await self.call_tool(fn.__name__, lambda **k: fn(self.ctx(), **k), **kw)


def register_tools(mcp: FastMCP, runner: ToolRunner) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def inspect_source(source: str, format_hint: str | None = None, line_format: str | None = None) -> str:
        """Look at a log source (Parquet/JSON file or URL, or a table) without changing anything: columns, sample entries and proposed field roles."""
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
        """Set up a log table over a source, read in place, with confirmed field roles; build_filter_index / build_search_index build an index right away (default: none; the result shows size and time estimates for big sources). Re-running with roles or timezone corrects only those. timezone (IANA name) is how timestamps without a zone are read: default the line format's own zone where it has one (bgl: America/Los_Angeles), else UTC."""
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
        """Build a filter index (kind="filter": exact value lists, nearly free filters) or a search index (kind="search": faster text search and fuzzy search) on a log table. dry_run=True only estimates size and build time from a trial build on a sample and builds nothing. Only build when the user asks for it."""
        return await runner.run_tool(setup_tools.create_index, log_table=log_table, kind=kind, dry_run=dry_run)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def describe_logs(
        log_table: str | None = None,
        find_values: dict[str, str] | None = None,
        start: str | None = None,
        end: str | None = None,
        timezone: str | None = None,
        confirmed_cost: str | None = None,
    ) -> str:
        """Describe the log tables: source, field roles, time zone, time range, context scopes and top values; find_values={"role_or_column","like"} looks up values containing a word. If a lookup answers TOO EXPENSIVE and the user agrees, repeat it with the confirmed_cost it gives."""
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
        """Find log entries by filters (e.g. {"level": "ERROR", "service": "payments"}) and/or text the message contains (any case), newest or oldest first. Each entry shows its time, fields, message and an occurrence ID. The cost is checked first: a too-expensive search may be estimated from a sample (said so), or answer TOO EXPENSIVE with a confirmed_cost to repeat it with once the user agrees. fuzzy needs a search index."""
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
        """Show the entries shortly before and after one occurrence (an ID from search_logs or locate results), marked with →, each tagged with its template. Default scope is the narrowest available (same trace, else same service and host); scope='everything' or a list of trace/service/host overrides it. window_minutes (default 5) is the window either side; before/after limit the entries shown (nearest first). Long entries are shortened."""
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
        """First look at a log table: the most common message templates with estimated counts, shares, top services/components and an example each. Saves templates to the catalog (new ones are flagged NEW; IDs are stable). filters={"level": "ERROR"} narrow it first; start/end bound the period."""
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

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def rename_parameter(log_table: str, template: str, old_name: str, new_name: str) -> str:
        """Give a template parameter a better name, permanently (later surveys keep it). template is a T<n> ID from survey; new_name is lower-case letters, digits and underscores, unique within the template."""
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
        """Escape hatch: run ONE read-only SQL statement (SELECT, WITH, set operations or EXPLAIN) when no other tool fits. Anything that could change data is refused. Results are cut to limit rows (default 50); the plan is cost-checked first and a too-expensive query answers TOO EXPENSIVE with a confirmed_cost to repeat it with once the user agrees. Log tables are views named like extractor.lt_<name>."""
        return await runner.run_tool(
            sql_tool.run_sql, sql=sql, limit=limit, timeout_s=timeout_s, confirmed_cost=confirmed_cost
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
        """Exact counts of the entries matching templates (T<n> IDs from survey), grouped by any role, column or time bucket (group_by=["service", "time:1h"]; buckets are time:<n>m|h|d), with example occurrence IDs per group. Needs at least one template: run survey first. The cost is checked first: a too-expensive count may be estimated from a sample (said so), or answer TOO EXPENSIVE with a confirmed_cost to repeat it with once the user agrees."""
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
        """For one template (T<n> ID from survey): each parameter's top values with counts (10 per parameter, raisable with limit) and, for numeric parameters, min, p50, p95 and max. by="service" (a role or column) breaks it down per value. The cost is checked first: a too-expensive extraction may be estimated from a sample (said so), or answer TOO EXPENSIVE with a confirmed_cost to repeat it with once the user agrees."""
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
        """Compare templates (T<n> IDs; default the catalog's top_n by size) over a period (start and end are required) with the preceding period of equal length: count per hour or day (bucket), change, on how many buckets each was present and which components were affected. Estimated by default (says so); exact=True counts every entry through the cost check, which may fall back to an estimate or answer TOO EXPENSIVE with a confirmed_cost to repeat it with. Where the data does not cover the preceding period the comparison is marked limited and nothing is called new."""
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
