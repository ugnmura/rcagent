"""Turning what the user typed into something SereneDB can read, and where it is read from."""

import fnmatch
import os
import posixpath
import re
from dataclasses import dataclass
from typing import Literal

from serenedb_extractor.config import Settings
from serenedb_extractor.errors import UserFacingError

Kind = Literal["parquet", "json", "csv", "table", "raw_text"]
_REMOTE = re.compile(r"^(https?|s3|gs|gcs|az|abfss?|r2|hf)://", re.IGNORECASE)
_PARQUET_EXT = (".parquet", ".pq")
_JSON_EXT = (".json", ".jsonl", ".ndjson", ".json.gz", ".jsonl.gz", ".ndjson.gz")
_CSV_EXT = (".csv", ".tsv", ".csv.gz", ".tsv.gz")
_RAW_EXT = (".log", ".txt", ".out", ".err", ".log.gz", ".txt.gz", ".out.gz", ".err.gz")
LOG_EXTENSIONS = (".log", ".txt", ".out", ".err", ".parquet", ".pq", ".json", ".jsonl", ".ndjson", ".csv", ".tsv")
# Places that hold system files, keys and credentials, never logs this server reads (or writes): refused on this
# machine and inside SereneDB's container alike.
SYSTEM_DIRS = (
    "/etc", "/proc", "/sys", "/dev", "/root", "/private/etc", "/private/var/root", "/var/root", "~/Library/Keychains",
)
_SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "extractor")
_FORMAT_HINTS: dict[str, Kind] = {
    "parquet": "parquet",
    "json": "json",
    "jsonl": "json",
    "ndjson": "json",
    "csv": "csv",
    "tsv": "csv",
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
            "they are parsed here and copied in; remote sources must be Parquet, JSON or CSV. "
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
    if low.endswith(_CSV_EXT):
        return "csv"
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
            raise UserFacingError(f"Unknown format '{format}'. Use parquet, json, csv, table or raw_text.")
    remote = is_remote(src)
    if not remote and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", src) and not re.match(r"^[A-Za-z]:[\\/]", src):
        raise UserFacingError(
            f"{src} starts with a scheme ({src.split(':', 1)[0]}:) that is not a supported remote source; give a plain "
            "file path, or an http(s), s3, gs, az, r2 or hf URL."
        )
    looks_like_path = remote or "/" in src or src.startswith(".") or _kind_from_name(src) is not None
    kind = hint or _kind_from_name(src.split("?", 1)[0] if remote else src)
    if kind is None:
        kind = "raw_text" if remote else ("table" if not looks_like_path else "raw_text")
    if remote:
        if kind in ("raw_text", "table"):
            raise RemoteRawTextUnsupported(src)
        return ResolvedSource(kind, src, None, None, remote=True)
    if kind == "table":
        check_table_source(src)
        return ResolvedSource("table", src, None, None)
    path = normalise_path(src, settings)
    check_log_file_name(path, src)
    check_private_path(path, src)
    db_path, host_path = _translate(path, settings)
    if host_path is not None:
        check_private_path(db_path, src)  # where SereneDB reads it
    size: int | None = None
    local = host_path or db_path  # outside the mount the path is a file on this machine, if it exists
    if os.path.isfile(local):
        size = os.path.getsize(local)
    elif host_path is None and settings.source_dirs and not any(
        db_path == d or db_path.startswith(d + "/") for d in settings.source_dirs
    ):
        raise UserFacingError(
            f"{src} is not read: SereneDB reads files in place only from {', '.join(settings.source_dirs)} "
            "(SERENEDB_SOURCE_DIRS)."
        )
    elif host_path is None and _local_matches(db_path):
        raise UserFacingError(
            f"{src} names several files on this machine. SereneDB can't see this machine's files, and only a single "
            "local file is copied in, so set them up one at a time, or put them in the logs folder mount "
            "(LOGS_HOST_DIR and LOGS_CONTAINER_DIR) or anywhere SereneDB can read, where several files work as one log table."
        )
    return ResolvedSource(kind, db_path, host_path, size)


def _local_matches(path: str) -> bool:
    """Whether a path with wildcards ({a,b}, {000..009}, *, ?) names files that exist on this machine."""
    if not any(c in path for c in "*?{["):
        return False
    import glob

    return any(glob.glob(os.path.expanduser(p)) for p in expand_files(path))


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


# ---------------------------------------------------------------- what may be read (and written)


def check_table_source(name: str) -> None:
    """Refuse a table in a system schema (pg_catalog, information_schema, pg_*) or in the extractor schema: those
    hold the database's own users and settings, or this server's catalog and log tables, never a log to set up."""
    schema = name.strip().rpartition(".")[0].strip().strip('"').lower()
    if schema and (schema in _SYSTEM_SCHEMAS or schema.startswith("pg_")):
        raise UserFacingError(
            f"'{name.strip()}' is in the {schema} schema, which holds the database's own system tables or this "
            "server's catalog, not logs, so it can't be set up as a log table. Use a table in your own schema "
            "(for example public.my_logs)."
        )


def normalise_path(source: str, settings: Settings) -> str:
    """The path with `~`, `.` and `..` resolved. A path written under the logs folder (as this machine or as
    SereneDB sees it) must stay inside it, and a relative path may not climb above where it starts."""
    raw = os.path.expanduser(source.strip())
    norm = posixpath.normpath(raw)
    if norm == ".." or norm.startswith("../"):
        raise UserFacingError(
            f"{source.strip()} climbs out of the folder it starts from (..), so it is not read. Give the file's full path."
        )
    for folder in (settings.logs_host_dir, settings.logs_container_dir):
        if not folder:
            continue
        base = posixpath.normpath(os.path.expanduser(folder)).rstrip("/") or "/"
        inside = base == "/" or norm == base or norm.startswith(base + "/")
        if raw.startswith(base + "/") and not inside:
            raise UserFacingError(
                f"{source.strip()} uses .. to leave the mounted logs folder {folder}, so it is not read. Only files "
                "inside that folder are read through it."
            )
    return norm


def check_log_file_name(path: str, source: str) -> None:
    """Only log and data files are read: every file the path names must end in a recognised extension (a
    format_hint does not lift this; it only says how a recognised file is read)."""
    for f in expand_files(path):
        if _kind_from_name(posixpath.basename(f)) is None:
            raise UserFacingError(
                f"{source.strip()} is not read: only log and data files are, and its name does not end in one of "
                f"{', '.join(LOG_EXTENSIONS)} (optionally with .gz for text). Give a log file, or copy this one under "
                "a name with a fitting extension."
            )


def check_private_path(path: str, source: str, *, verb: str = "read") -> None:
    """Refuse hidden files and folders (~/.ssh, ~/.aws, ...) and system locations (/etc, /proc, ...). On this
    machine the path is also checked after following links, so a link can't lead there either."""
    candidates = [path]
    expanded = os.path.expanduser(path)
    folder, _, name = expanded.rpartition("/")
    if any(c in folder for c in "*?[{"):  # a wildcard folder could reach a hidden one through a link
        raise UserFacingError(
            f"{source.strip()} is not {verb}: wildcards are allowed only in the file name, not in the folders."
        )
    if not any(c in expanded for c in "*?[{") and os.path.lexists(expanded):
        candidates.append(os.path.realpath(expanded))
    elif folder and os.path.isdir(folder):
        candidates.append(os.path.realpath(folder) + "/" + name)  # the folder after following links
    for cand in candidates:
        for f in expand_files(cand):
            parts = [p for p in posixpath.normpath(f).split("/") if p not in ("", ".", "..")]
            # A part starting with a wildcard could match a hidden name (*ssh matches .ssh): treat it as hidden.
            hidden = next((p for p in parts if p.startswith(".")), None)
            if parts and parts[-1][:1] in ("*", "?", "["):
                # SereneDB's wildcards match hidden files too (*.csv matches .secret.csv), so a file name must
                # start with a plain character: part_*.parquet, not *.parquet.
                raise UserFacingError(
                    f"{source.strip()} is not {verb}: a file name may not start with a wildcard (it would also match "
                    "hidden files). Start it with a plain character, e.g. part_*.parquet or app*.log."
                )
            if hidden:
                raise UserFacingError(
                    f"{source.strip()} is not {verb}: it is in a hidden folder or is a hidden file ({hidden}). Hidden "
                    "folders such as ~/.ssh or ~/.aws hold keys and settings, not logs."
                )
            where = _system_dir(f)
            if where:
                raise UserFacingError(
                    f"{source.strip()} is not {verb}: it is in {where}, a system location that holds system files "
                    "or credentials, not logs."
                )


def _system_dir(path: str) -> str | None:
    """The system location a path (wildcards allowed) is or could be in, compared case-insensitively."""
    parts = [p for p in posixpath.normpath(path).lower().split("/") if p]
    if not posixpath.isabs(posixpath.normpath(path)):
        return None
    for d in SYSTEM_DIRS:
        dparts = [p for p in posixpath.normpath(os.path.expanduser(d)).lower().split("/") if p]
        if len(parts) >= len(dparts) and all(fnmatch.fnmatchcase(dp, pp) for dp, pp in zip(dparts, parts)):
            return d
    return None
