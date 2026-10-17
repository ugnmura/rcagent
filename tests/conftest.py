"""Shared test harness: database fixtures, in-memory MCP clients, output parsers."""

import os
import re
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import replace
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, GetPromptResult, ListPromptsResult, ListToolsResult
from mcp.shared.memory import create_connected_server_and_client_session
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from serenedb_extractor.config import Settings
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import Database
from serenedb_extractor.server import build_server

TEST_DB = os.environ.get("SERENEDB_TEST_DB", "extractor_test")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "db: needs a SereneDB at SERENEDB_TEST_URL")


@pytest.fixture(scope="session")
def db_url() -> str:
    """URL of the dedicated test database (`SERENEDB_TEST_DB`, default `extractor_test`) (created if missing); never `postgres`."""
    base = os.environ.get("SERENEDB_TEST_URL")
    if not base:
        pytest.skip("SERENEDB_TEST_URL not set")
    with psycopg.connect(base, autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone()
        if not exists:
            admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(TEST_DB)))
    return make_conninfo(base, dbname=TEST_DB)


def _reset_schema(url: str) -> None:
    assert str(conninfo_to_dict(url).get("dbname", "")).startswith("extractor_test"), (
        "tests may only reset schema extractor in a database named extractor_test*"
    )
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS extractor CASCADE")


def _settings(url: str, **over: Any) -> Settings:
    return replace(Settings.from_env({"SERENEDB_READER_URL": url, "SERENEDB_WRITER_URL": url}), **over)


@pytest.fixture
def database(db_url: str) -> Iterator[Database]:
    db = Database(_settings(db_url))
    try:
        yield db
    finally:
        db.close()


class Client:
    """In-memory MCP client over a FastMCP server.

    Each request opens a short-lived connected session inside the calling test's task: anyio
    cancel scopes cannot span pytest-asyncio's separate fixture setup/teardown tasks. Server
    state (the AppContext, the one-time notes) lives in the server, so it persists across calls.
    """

    def __init__(self, server: FastMCP, made: list[AppContext]) -> None:
        self.server = server
        self.made = made

    async def list_tools(self) -> ListToolsResult:
        async with create_connected_server_and_client_session(self.server) as session:
            return await session.list_tools()

    async def call_tool(self, name: str, args: dict[str, Any]) -> CallToolResult:
        async with create_connected_server_and_client_session(self.server) as session:
            return await session.call_tool(name, args)

    async def list_prompts(self) -> ListPromptsResult:
        async with create_connected_server_and_client_session(self.server) as session:
            return await session.list_prompts()

    async def get_prompt(self, name: str) -> GetPromptResult:
        async with create_connected_server_and_client_session(self.server) as session:
            return await session.get_prompt(name)

    def close(self) -> None:
        for ctx in self.made:
            ctx.db.close()


async def _client(factory: Callable[[], AppContext]) -> AsyncIterator[Client]:
    made: list[AppContext] = []

    def tracked() -> AppContext:
        ctx = factory()
        made.append(ctx)
        return ctx

    client = Client(build_server(tracked), made)
    try:
        yield client
    finally:
        client.close()


@pytest_asyncio.fixture
async def mcp(db_url: str) -> AsyncIterator[Client]:
    _reset_schema(db_url)
    settings = _settings(db_url)
    async for c in _client(lambda: AppContext.from_settings(settings)):
        yield c


@pytest_asyncio.fixture
async def mcp_single_role(db_url: str) -> AsyncIterator[Client]:
    _reset_schema(db_url)
    settings = Settings.from_env({"SERENEDB_READER_URL": db_url})
    async for c in _client(lambda: AppContext.from_settings(settings)):
        yield c


@pytest_asyncio.fixture
async def mcp_short_timeout(db_url: str) -> AsyncIterator[Client]:
    _reset_schema(db_url)
    settings = _settings(db_url, default_timeout_s=1.0)
    async for c in _client(lambda: AppContext.from_settings(settings)):
        yield c


@pytest_asyncio.fixture
async def mcp_no_db() -> AsyncIterator[Client]:
    def factory() -> AppContext:
        raise AssertionError("the database must not be touched")

    async for c in _client(factory):
        yield c


@pytest_asyncio.fixture
async def mcp_unreachable() -> AsyncIterator[Client]:
    settings = Settings.from_env({"SERENEDB_READER_URL": "postgresql://postgres@127.0.0.1:1/x?connect_timeout=2"})
    async for c in _client(lambda: AppContext.from_settings(settings)):
        yield c


async def call(client: Client, tool: str, **args: Any) -> str:
    """Call a tool by name and return its text result."""
    result = await client.call_tool(tool, args)
    return "\n".join(getattr(b, "text", "") for b in result.content)


def container_parquet(db_url: str, name: str, select_sql: str) -> str:
    """Write `select_sql` to a Parquet file inside the SereneDB container; return its path there."""
    path = f"/tmp/{name}.parquet"
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(f"COPY ({select_sql}) TO '{path.replace(chr(39), chr(39) * 2)}' (FORMAT PARQUET)")  # type: ignore[call-overload]
    return path


def ids_in(out: str) -> list[str]:
    """Template IDs (T<n>) in order of first appearance."""
    return list(dict.fromkeys(re.findall(r"\bT\d+\b", out)))


def id_of(out: str, template_text: str) -> str:
    """The template ID on the line that shows `template_text`."""
    for line in out.splitlines():
        if template_text in line:
            m = re.search(r"\bT\d+\b", line)
            if m:
                return m.group(0)
    raise AssertionError(f"no template ID next to {template_text!r} in:\n{out}")


def first_occurrence(out: str) -> str:
    """The first occurrence ID (`file#row`, `e:<n>` or `pk:<v>`) in the output."""
    m = re.search(r"(?:[^\s#]+#\d+|\be:\d+|\bpk:\S+)", out)
    assert m, f"no occurrence ID in:\n{out}"
    return m.group(0)


def token_of(out: str) -> str:
    """The `confirmed_cost=` value to pass back."""
    m = re.search(r"confirmed_cost=(\S+)", out)
    assert m, f"no confirmed_cost token in:\n{out}"
    return m.group(1).rstrip(".,)`'\"")
