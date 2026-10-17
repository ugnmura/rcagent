"""Configuration from environment variables (spec section 4)."""

from collections.abc import Mapping
from dataclasses import dataclass

from serenedb_extractor.errors import UserFacingError


class ConfigError(UserFacingError):
    """A setting is missing or inconsistent; the message names the setting."""


@dataclass(frozen=True)
class Settings:
    reader_url: str
    writer_url: str
    single_role: bool
    logs_host_dir: str | None = None
    logs_container_dir: str | None = None
    default_timeout_s: float = 60.0
    max_timeout_s: float = 600.0
    sample_size: int = 100_000
    limit_cap: int = 10

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        reader = env.get("SERENEDB_READER_URL", "").strip()
        if not reader:
            raise ConfigError(
                "SERENEDB_READER_URL is not set: give the connection URL of a SereneDB role "
                "that can read your logs (for example postgresql://user@localhost:7890/postgres)."
            )
        writer = env.get("SERENEDB_WRITER_URL", "").strip()
        host_dir = env.get("LOGS_HOST_DIR", "").strip() or None
        container_dir = env.get("LOGS_CONTAINER_DIR", "").strip() or None
        if host_dir and not container_dir:
            raise ConfigError(
                "LOGS_HOST_DIR is set but LOGS_CONTAINER_DIR is not: set both (the folder on this "
                "machine and where SereneDB sees it) or neither."
            )
        if container_dir and not host_dir:
            raise ConfigError(
                "LOGS_CONTAINER_DIR is set but LOGS_HOST_DIR is not: set both (the folder on this "
                "machine and where SereneDB sees it) or neither."
            )
        return cls(
            reader_url=reader,
            writer_url=writer or reader,
            single_role=not writer,
            logs_host_dir=host_dir,
            logs_container_dir=container_dir,
        )
