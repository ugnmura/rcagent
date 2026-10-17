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
from serenedb_extractor.tools import describe, setup_tools
from serenedb_extractor.tools import survey as survey_tool

SINGLE_ROLE_NOTE = (
    "Note: only a reader URL was configured, so SereneDB is not enforcing read-only limits "
    "on this connection. Set SERENEDB_WRITER_URL and use a SELECT-only role for the reader to enforce them."
)


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
            out = await anyio.to_thread.run_sync(lambda: fn(**kw))
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
        """Set up a log table over a source, read in place, with confirmed field roles. Re-running with roles or timezone corrects only those. timezone (IANA name, default UTC) is how timestamps without a zone are read."""
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

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def describe_logs(
        log_table: str | None = None,
        find_values: dict[str, str] | None = None,
        start: str | None = None,
        end: str | None = None,
        timezone: str = "UTC",
    ) -> str:
        """Describe the log tables: source, field roles, time range, context scopes and top values; find_values={"role_or_column","like"} looks up values containing a word."""
        return await runner.run_tool(
            describe.describe_logs,
            log_table=log_table,
            find_values=find_values,
            start=start,
            end=end,
            timezone=timezone,
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
        timezone: str = "UTC",
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


def build_server(ctx_factory: Callable[[], AppContext]) -> FastMCP:
    mcp = FastMCP("serenedb-extractor")
    register_tools(mcp, ToolRunner(ctx_factory))
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
