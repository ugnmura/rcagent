import pytest

from serenedb_extractor.catalog import schema
from serenedb_extractor.config import ConfigError, Settings
from mcp.server.fastmcp import FastMCP

from serenedb_extractor.catalog.models import UnknownLogTable
from serenedb_extractor.server import ToolRunner
from tests.conftest import Client, call


@pytest.mark.db
async def test_describe_empty(mcp):
    out = await call(mcp, "describe_logs")
    assert out.startswith("How this was measured: ") and "no log tables yet" in out


@pytest.mark.db
async def test_bootstrap_idempotent(mcp, database):
    for _ in range(2):
        assert "no log tables yet" in await call(mcp, "describe_logs")
    schema.bootstrap(database)
    schema.bootstrap(database)
    assert "no log tables yet" in await call(mcp, "describe_logs")


@pytest.mark.db
async def test_single_role_note_once(mcp_single_role):
    first = await call(mcp_single_role, "describe_logs")
    second = await call(mcp_single_role, "describe_logs")
    assert "not enforcing read-only limits" in first and "not enforcing" not in second


@pytest.mark.db
async def test_single_role_note_rides_on_first_result_even_an_error(mcp_single_role):
    first = await call(mcp_single_role, "describe_logs", log_table="nope")
    second = await call(mcp_single_role, "describe_logs", log_table="nope")
    assert "nope" in first and "not enforcing read-only limits" in first
    assert "nope" in second and "not enforcing" not in second


@pytest.mark.db
async def test_two_roles_no_note(mcp):
    assert "not enforcing" not in await call(mcp, "describe_logs")


@pytest.mark.db
async def test_unknown_log_table_plain(mcp):
    out = await call(mcp, "describe_logs", log_table="nope")
    assert "nope" in out and "Traceback" not in out
    assert "\n" not in out.strip()
    assert not out.startswith("How this was measured")


def test_config_errors():
    with pytest.raises(ConfigError, match="SERENEDB_READER_URL"):
        Settings.from_env({})
    with pytest.raises(ConfigError, match="LOGS_CONTAINER_DIR"):
        Settings.from_env({"SERENEDB_READER_URL": "x", "LOGS_HOST_DIR": "/tmp"})
    with pytest.raises(ConfigError, match="LOGS_HOST_DIR"):
        Settings.from_env({"SERENEDB_READER_URL": "x", "LOGS_CONTAINER_DIR": "/logs"})


def test_settings_defaults():
    s = Settings.from_env({"SERENEDB_READER_URL": "x"})
    assert s.writer_url == "x" and s.single_role
    assert (s.default_timeout_s, s.max_timeout_s, s.sample_size) == (60.0, 600.0, 100_000)
    s2 = Settings.from_env({"SERENEDB_READER_URL": "x", "SERENEDB_WRITER_URL": "y"})
    assert s2.writer_url == "y" and not s2.single_role


async def test_annotations_registered(mcp_no_db):
    tools = {t.name: t for t in (await mcp_no_db.list_tools()).tools}
    assert tools["describe_logs"].annotations.readOnlyHint is True


EXPECTED_ANNOTATIONS = {
    **{
        n: (True, None)
        for n in (
            "inspect_source",
            "describe_logs",
            "locate_occurrences",
            "extract_params",
            "trend",
            "get_context",
            "search_logs",
            "run_sql",
        )
    },
    "setup_log_table": (None, True),
    "create_index": (None, True),
    "survey": (False, False),
    "rename_parameter": (False, False),
}


async def test_exactly_twelve_tools_with_expected_annotations(mcp_no_db):
    listed = (await mcp_no_db.list_tools()).tools
    assert sorted(t.name for t in listed) == sorted(EXPECTED_ANNOTATIONS)
    assert len(listed) == 12
    for t in listed:
        assert t.annotations is not None
        read_only, destructive = EXPECTED_ANNOTATIONS[t.name]
        if read_only is not None:
            assert t.annotations.readOnlyHint is read_only, t.name
        if destructive is not None:
            assert t.annotations.destructiveHint is destructive, t.name


async def test_unreachable_database_is_plain(mcp_unreachable):
    out = await call(mcp_unreachable, "describe_logs")
    assert "Traceback" not in out and "\n" not in out.strip()
    assert "SereneDB" in out


def _failing_client(exc: Exception) -> Client:
    server = FastMCP("test")
    runner = ToolRunner(lambda: None)  # type: ignore[arg-type, return-value]

    @server.tool()
    async def boom() -> str:
        def boom(ctx: object) -> str:
            raise exc

        return await runner.run_tool(boom)

    return Client(server, [])


async def test_unexpected_error_is_generic_and_logged(caplog):
    out = await call(_failing_client(ValueError("secret detail")), "boom")
    assert out == "Something went wrong while running boom; details were logged."
    assert "ValueError" not in out and "secret" not in out
    assert any("secret detail" in str(r.exc_info) for r in caplog.records)


async def test_user_facing_error_shown_verbatim():
    out = await call(_failing_client(UnknownLogTable("zzz")), "boom")
    assert "zzz" in out and "no log table" in out
