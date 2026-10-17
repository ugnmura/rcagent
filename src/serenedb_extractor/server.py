"""MCP server: tool registration, uniform error handling, stdio entry point."""

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
from serenedb_extractor.tools import describe

SINGLE_ROLE_NOTE = (
    "Note: only a reader URL was configured, so SereneDB is not enforcing read-only limits "
    "on this connection. Set SERENEDB_WRITER_URL and use a SELECT-only role for the reader to enforce them."
)


async def call_tool(fn: Callable[..., str], **kw: Any) -> str:
    """Run a blocking tool body off the event loop; any failure becomes one plain line."""
    try:
        return await anyio.to_thread.run_sync(lambda: fn(**kw))
    except Exception as exc:
        return fmt.plain_error(exc)


def build_server(ctx_factory: Callable[[], AppContext]) -> FastMCP:
    mcp = FastMCP("serenedb-extractor")
    lock = threading.Lock()
    state: dict[str, Any] = {"ctx": None, "noted": False}

    def get_ctx() -> AppContext:
        with lock:
            if state["ctx"] is None:
                state["ctx"] = ctx_factory()
            return state["ctx"]  # type: ignore[no-any-return]

    async def run(fn: Callable[..., str], **kw: Any) -> str:
        """Call `fn(ctx, **kw)`; the first successful result also carries the single-role note."""
        out = await call_tool(lambda **k: fn(get_ctx(), **k), **kw)
        with lock:
            ctx = state["ctx"]
            if ctx is not None and ctx.settings.single_role and not state["noted"] and out.startswith(fmt.PREFIX):
                state["noted"] = True
                out += "\n" + SINGLE_ROLE_NOTE
        return out

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def describe_logs(log_table: str | None = None) -> str:
        """Describe the log tables that are set up (or one of them): source, size and fields."""
        return await run(describe.describe_logs, log_table=log_table)

    return mcp


def main() -> None:
    try:
        settings = Settings.from_env(os.environ)
    except ConfigError as exc:
        print(f"serenedb-extractor: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    build_server(lambda: AppContext.from_settings(settings)).run(transport="stdio")


if __name__ == "__main__":
    main()
