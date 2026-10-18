"""Metadata-only look at a source: reader SQL, columns, a few sample entries, sizes."""

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg

from serenedb_extractor.db import Database, quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.format import shorten
from serenedb_extractor.setup.paths import ResolvedSource, check_table_source, source_sql, sql_literal
from serenedb_extractor.setup.roles import is_nested

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


# Engine messages that mean the source itself could not be found, opened or decoded (as opposed to a query on
# its data failing): only these get the "check the path / access" advice.
_SOURCE_PROBLEM = re.compile(
    r"no files? found|no such file|does not exist|could not open|cannot open|failed to open|io error|http|"
    r"magic bytes|not a parquet|malformed json|invalid json|permission denied|access denied|forbidden|"
    r"unauthori[sz]ed|\b40[134]\b|timed? ?out connecting|could not resolve",
    re.IGNORECASE,
)


_WRONG_FORMAT = re.compile(r"magic bytes|not a parquet|malformed json|invalid json|could not sniff|csv error", re.IGNORECASE)


def _engine_detail(detail: str) -> str:
    """The engine's message without the echoed SQL (LINE n: ... and the caret line)."""
    text = re.split(r"\bLINE \d+:", detail, maxsplit=1)[0]
    return re.sub(r"\s+", " ", text).strip().rstrip(".")[:300]


class SourceUnreadable(UserFacingError):
    def __init__(self, source: str, detail: str, remote: bool) -> None:
        detail = _engine_detail(detail)
        if not _SOURCE_PROBLEM.search(detail):
            super().__init__(
                f"SereneDB could not finish reading {source}: {detail}. The source itself was found; the values "
                "it holds did not fit this request (for example a field role pointing at the wrong kind of column)."
            )
            return
        if re.search(r"adds column \"?(filename|file_row_number)", detail, re.IGNORECASE):
            super().__init__(
                f"{source} has its own column named filename or file_row_number, which SereneDB also adds to name each "
                "entry, so it can't be read in place. Rename that column in the file, or set up a copy of it "
                "(a file on this machine outside the logs folder is copied)."
            )
            return
        if _WRONG_FORMAT.search(detail):
            super().__init__(
                f"SereneDB could not read {source} in the format it was read as: {detail}. The file exists but holds "
                "another format: check its name or give format_hint (parquet, json, csv or raw_text)."
            )
            return
        hint = (
            " If the storage is private, SereneDB itself needs access to it (credentials configured "
            "on the SereneDB server); nothing is downloaded here."
            if remote
            else " Check the path as SereneDB sees it (and the logs folder mount, if one is configured)."
        )
        super().__init__(f"SereneDB could not read {source}: {detail}.{hint}")


@contextmanager
def readable(source: str, remote: bool = False) -> Iterator[None]:
    """Turn any error SereneDB reports into one plain-language line naming the source."""
    try:
        yield
    except psycopg.Error as exc:
        raise SourceUnreadable(source, str(exc), remote) from exc


@dataclass
class SourceInfo:
    resolved: ResolvedSource
    from_sql: str
    columns: list[tuple[str, str]]
    samples: list[dict[str, Any]]
    row_count: int | None = None
    num_files: int | None = None
    size_bytes: int | None = None
    row_groups: int | None = None
    big_columns: list[tuple[str, int]] | None = None


def table_ref(source: str) -> str:
    parts = source.strip().split(".")
    if not 1 <= len(parts) <= 2 or not all(_IDENT.match(p) for p in parts):
        raise UserFacingError(f"'{source}' is not a table name (use table or schema.table).")
    return ".".join(quote_ident(p) for p in parts)


def reader_sql(rs: ResolvedSource) -> str:
    """The FROM-clause reader for a source, with the position columns (spike section 5)."""
    if rs.kind == "table":
        return table_ref(rs.db_path)
    fn = {"parquet": "read_parquet", "csv": "read_csv"}.get(rs.kind, "read_json")
    return f"{fn}({source_sql(rs)}, filename=true, file_row_number=true)"


def relation_columns(db: Database, from_sql: str, source: str = "", remote: bool = False) -> list[tuple[str, str]]:
    """(name, type) of every column of a relation or reader, helper columns included."""
    slow = db.settings.max_timeout_s if remote else None
    what = f"reading the columns of {source or 'the source'}"
    with readable(source or from_sql, remote):
        names = db.read(f"SELECT * FROM {from_sql} LIMIT 0", {}, timeout_s=slow, what=what).columns
        types = {r[0]: r[1] for r in db.read(f"DESCRIBE SELECT * FROM {from_sql}", {}, timeout_s=slow, what=what).rows}
    return [(n, types.get(n, "VARCHAR" if n == "filename" else "")) for n in names]


def _short(v: Any) -> str:
    return shorten(str(v), 80)


def sample_columns(columns: list[tuple[str, str]], remote: bool = False) -> str:
    """What to select for the sample entries: every column, nested ones (maps, structs, lists) as JSON text so
    their fields show and can be proposed as roles. A remote source leaves nested columns out when there are
    plain ones: they are the bulk of a remote file."""
    nested = [c for c, t in columns if is_nested(t) and t.strip().upper() != "JSON"]
    if not nested:
        return "*"
    if remote:
        plain = [c for c, _ in columns if c not in nested]
        return ", ".join(quote_ident(c) for c in plain) if plain else "*"
    return ", ".join(
        f"to_json({quote_ident(c)})::VARCHAR AS {quote_ident(c)}" if c in nested else quote_ident(c) for c, _ in columns
    )


def sniff(db: Database, rs: ResolvedSource, source: str, for_setup: bool = False) -> SourceInfo:
    """Columns, 5 sample entries and the size of a source, reading no data beyond the sample. A remote
    source's reads may take up to the maximum query time (setup is a one-off), and setup skips the
    per-column sizes that only inspect_source shows."""
    from_sql = reader_sql(rs)
    slow = db.settings.max_timeout_s if rs.remote else None
    if rs.kind == "table":
        schema, _, table = rs.db_path.rpartition(".")
        found = db.read(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = %(t)s "
            "AND table_schema = COALESCE(NULLIF(%(s)s, ''), current_schema())",
            {"t": table, "s": schema},
        )
        if not found.rows:
            raise UserFacingError(
                f"There is no database table named '{rs.db_path}' to use as a log source. If it is a log table set up "
                "here, describe_logs shows it; for a file, give its path with the extension (.parquet, .json, .csv, .log)."
            )
        actual = str(found.rows[0][0])
        check_table_source(f"{actual}.{table}")
        # Name the schema it was found in, so the view can't resolve the bare name to a system table instead.
        from_sql = f"{quote_ident(actual)}.{quote_ident(table)}"
    columns = relation_columns(db, from_sql, source, rs.remote)
    with readable(source, rs.remote):
        sample = db.read(
            f"SELECT {sample_columns(columns, rs.remote)} FROM {from_sql} LIMIT 5", {}, timeout_s=slow,
            what=f"reading 5 sample entries of {source}",
        )
        info = SourceInfo(rs, from_sql, columns, sample.dicts(), size_bytes=rs.size_bytes)
        if rs.kind == "parquet":
            lit = source_sql(rs)
            meta = db.read(
                "SELECT sum(num_rows)::bigint AS n, count(*) AS files, sum(file_size_bytes)::bigint AS size, "
                f"sum(num_row_groups)::bigint AS groups FROM parquet_file_metadata({lit})",
                {},
                timeout_s=slow,
                what=f"reading the Parquet metadata of {source}",
            ).dicts()[0]
            info.row_count, info.num_files, info.size_bytes, info.row_groups = (
                meta["n"],
                meta["files"],
                meta["size"],
                meta["groups"],
            )
            if not for_setup:
                big = db.read(
                    "SELECT path_in_schema AS c, sum(total_compressed_size)::bigint AS b "
                    f"FROM parquet_metadata({lit}) GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
                    {},
                    timeout_s=slow,
                    what=f"reading the column sizes of {source}",
                )
                info.big_columns = [(r[0], int(r[1])) for r in big.rows]
        elif rs.kind == "table":
            info.row_count = db.read(f"SELECT count(*) FROM {from_sql}", {}).scalar()
    return info


def sample_text(v: Any) -> str:
    """A sample value for role proposal: shortened, except JSON objects, whose fields are read (up to a limit)."""
    text = json.dumps(v, default=str) if isinstance(v, dict) else str(v)
    return text[:4000] if text.startswith("{") else _short(text)


def sample_values(info: SourceInfo) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in info.samples:
        for k, v in row.items():
            if v is not None:
                out.setdefault(k, []).append(sample_text(v))
    return out


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n} B"
