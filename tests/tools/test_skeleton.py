import pytest

from serenedb_extractor.catalog import schema
from serenedb_extractor.config import ConfigError, Settings
from tests.conftest import call


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
async def test_two_roles_no_note(mcp):
    assert "not enforcing" not in await call(mcp, "describe_logs")


@pytest.mark.db
async def test_unknown_log_table_plain(mcp):
    out = await call(mcp, "describe_logs", log_table="nope")
    assert "nope" in out and "Traceback" not in out
    assert "\n" not in out.strip()


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


async def test_unreachable_database_is_plain(mcp_unreachable):
    out = await call(mcp_unreachable, "describe_logs")
    assert "Traceback" not in out and "\n" not in out.strip()
    assert "SereneDB" in out
