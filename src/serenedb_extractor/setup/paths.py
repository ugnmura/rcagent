"""Turning what the user typed into something SereneDB can read, and where it is read from."""

import os
import posixpath
import re
from dataclasses import dataclass
from typing import Literal

from serenedb_extractor.config import Settings
from serenedb_extractor.errors import UserFacingError

Kind = Literal["parquet", "json", "table", "raw_text"]
_REMOTE = re.compile(r"^(https?|s3|gs|gcs|az|abfss?|r2|hf)://", re.IGNORECASE)
_PARQUET_EXT = (".parquet", ".pq")
_JSON_EXT = (".json", ".jsonl", ".ndjson", ".json.gz", ".jsonl.gz", ".ndjson.gz")
_RAW_EXT = (".log", ".txt", ".out", ".err", ".log.gz", ".txt.gz")
_FORMAT_HINTS: dict[str, Kind] = {
    "parquet": "parquet",
    "json": "json",
    "jsonl": "json",
    "ndjson": "json",
    "table": "table",
    "raw": "raw_text",
    "raw_text": "raw_text",
    "text": "raw_text",
    "log": "raw_text",
}


class RemoteRawTextUnsupported(UserFacingError):
    def __init__(self, source: str) -> None:
        super().__init__(
            f"{source} looks like a remote raw text log. Raw text logs must be local files because "
            "they are parsed here and copied in; remote sources must be Parquet or JSON. "
            "Download or mount the file locally, or point at a Parquet/JSON version of it."
        )


@dataclass(frozen=True)
class ResolvedSource:
    kind: Kind
    db_path: str  # what SereneDB reads: a URL, a path as SereneDB sees it, or a table name
    host_path: str | None  # the same file on this machine, when it is under the mount
    size_bytes: int | None
    remote: bool = False


def pct(sql: str) -> str:
    """Make text that goes into a parameterised query safe for psycopg: `%` becomes `%%`.

    Every query this package builds is sent with a params dict (possibly empty), so literals
    and role expressions interpolated into the SQL text must pass through here (or sql_literal).
    """
    return sql.replace("%", "%%")


def sql_literal(text: str) -> str:
    """A single-quoted SQL string literal, safe for `'` and `%`."""
    return pct("'" + text.replace("'", "''") + "'")


_RANGE = re.compile(r"\{(\d+)\.\.(\d+)\}")
_CHOICE = re.compile(r"\{([^{}]*,[^{}]*)\}")
MAX_FILES = 1000


def expand_files(source: str) -> list[str]:
    """The files a source names: `{000..009}` (a zero-padded number range) and `{a,b}` (alternatives)
    expand to several; anything else is one file. Lets a remote source span several objects, which
    can't be listed with a wildcard over HTTP."""
    out = [source]
    for _ in range(4):  # at most a few brace groups
        nxt: list[str] = []
        changed = False
        for item in out:
            if m := _RANGE.search(item):
                lo, hi = m.group(1), m.group(2)
                width = len(lo) if lo.startswith("0") or len(lo) == len(hi) else 0
                a, b = int(lo), int(hi)
                step = 1 if b >= a else -1
                nxt += [item[: m.start()] + str(i).zfill(width) + item[m.end() :] for i in range(a, b + step, step)]
                changed = True
            elif m := _CHOICE.search(item):
                nxt += [item[: m.start()] + c.strip() + item[m.end() :] for c in m.group(1).split(",")]
                changed = True
            else:
                nxt.append(item)
        out = nxt
        if len(out) > MAX_FILES:
            raise UserFacingError(f"{source} names {len(out):,} files; at most {MAX_FILES:,} can be read together.")
        if not changed:
            break
    return out


def source_sql(rs: "ResolvedSource") -> str:
    """The file argument for read_parquet/read_json/parquet_metadata: one path literal, or a list of them."""
    files = expand_files(rs.db_path)
    if len(files) == 1:
        return sql_literal(files[0])
    return "[" + ", ".join(sql_literal(f) for f in files) + "]"


def is_remote(source: str) -> bool:
    return bool(_REMOTE.match(source.strip()))


def _kind_from_name(name: str) -> Kind | None:
    low = name.lower()
    if low.endswith(_PARQUET_EXT):
        return "parquet"
    if low.endswith(_JSON_EXT):
        return "json"
    if low.endswith(_RAW_EXT):
        return "raw_text"
    return None


def resolve_source(source: str, settings: Settings, format: str | None = None) -> ResolvedSource:
    """Classify `source` and translate mounted paths. Raises for remote raw text."""
    src = source.strip()
    if not src:
        raise UserFacingError("Give a source: a Parquet/JSON file or URL, a raw log file, or a table name.")
    hint: Kind | None = None
    if format:
        hint = _FORMAT_HINTS.get(format.strip().lower())
        if hint is None:
            raise UserFacingError(f"Unknown format '{format}'. Use parquet, json, table or raw_text.")
    remote = is_remote(src)
    looks_like_path = remote or "/" in src or src.startswith(".") or _kind_from_name(src) is not None
    kind = hint or _kind_from_name(src.split("?", 1)[0] if remote else src)
    if kind is None:
        kind = "raw_text" if remote else ("table" if not looks_like_path else "raw_text")
    if remote:
        if kind in ("raw_text", "table"):
            raise RemoteRawTextUnsupported(src)
        return ResolvedSource(kind, src, None, None, remote=True)
    if kind == "table":
        return ResolvedSource("table", src, None, None)
    db_path, host_path = _translate(src, settings)
    size: int | None = None
    local = host_path or db_path  # outside the mount the path is a file on this machine, if it exists
    if os.path.isfile(local):
        size = os.path.getsize(local)
    return ResolvedSource(kind, db_path, host_path, size)


def _translate(path: str, settings: Settings) -> tuple[str, str | None]:
    """Map a path under LOGS_HOST_DIR to where SereneDB sees it; other paths are used as given."""
    host_dir, container_dir = settings.logs_host_dir, settings.logs_container_dir
    if host_dir and container_dir:
        host = posixpath.normpath(os.path.expanduser(path))
        base = posixpath.normpath(os.path.expanduser(host_dir))
        if host == base or host.startswith(base.rstrip("/") + "/"):
            rel = host[len(base) :].lstrip("/")
            return posixpath.join(container_dir, rel) if rel else container_dir, host
    return path, None
