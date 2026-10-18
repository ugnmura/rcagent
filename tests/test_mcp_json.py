"""The project .mcp.json starts the server with settings the server accepts, using only local defaults."""

import json
import re
from pathlib import Path

from serenedb_extractor.config import Settings

MCP_JSON = Path(__file__).resolve().parents[1] / ".mcp.json"
EXPANSION = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")  # Claude Code's ${VAR} / ${VAR:-default}


def _server() -> dict:
    return json.loads(MCP_JSON.read_text())["mcpServers"]["serenedb-extractor"]


def _expand(value: str, env: dict[str, str]) -> str:
    return EXPANSION.sub(lambda m: env.get(m[1]) or (m[2] or ""), value)


def test_command_runs_the_project_entry_point() -> None:
    server = _server()
    assert [server["command"], *server["args"]] == ["uv", "run", "--directory", ".", "serenedb-extractor"]


def test_every_env_value_is_an_overridable_variable_of_the_same_name() -> None:
    for name, value in _server()["env"].items():
        m = EXPANSION.fullmatch(value)
        assert m and m[1] == name, f"{name}: {value!r}"


def test_defaults_match_the_readme_quick_start() -> None:
    env = {k: _expand(v, {}) for k, v in _server()["env"].items()}
    settings = Settings.from_env(env)
    assert settings.reader_url == "postgresql://postgres@localhost:7890/postgres"
    assert settings.single_role and settings.allow_sql
    assert (settings.logs_host_dir, settings.logs_container_dir) == ("~/logs", "/logs")


def test_no_password_in_the_defaults() -> None:
    for value in _server()["env"].values():
        assert not re.search(r"://[^/@]*:[^/@]*@", value), value


def test_environment_overrides_the_defaults() -> None:
    env = {k: _expand(v, {"SERENEDB_READER_URL": "postgresql://r@db:1/x", "SERENEDB_WRITER_URL": "postgresql://w@db:1/x"})
           for k, v in _server()["env"].items()}
    settings = Settings.from_env(env)
    assert (settings.reader_url, settings.writer_url, settings.single_role) == (
        "postgresql://r@db:1/x", "postgresql://w@db:1/x", False)
