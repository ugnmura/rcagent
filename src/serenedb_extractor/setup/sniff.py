"""Metadata-only look at a source: reader SQL, columns, a few sample entries, sizes."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg

from serenedb_extractor.db import Database, quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.format import shorten
from serenedb_extractor.setup.paths import ResolvedSource, sql_literal

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


class SourceUnreadable(UserFacingError):
    def __init__(self, source: str, detail: str, remote: bool) -> None:
        detail = re.sub(r"\s+", " ", detail).strip()[:300]
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
    fn = "read_parquet" if rs.kind == "parquet" else "read_json"
    return f"{fn}({sql_literal(rs.db_path)}, filename=true, file_row_number=true)"


def relation_columns(db: Database, from_sql: str, source: str = "", remote: bool = False) -> list[tuple[str, str]]:
    """(name, type) of every column of a relation or reader, helper columns included."""
    with readable(source or from_sql, remote):
        names = db.read(f"SELECT * FROM {from_sql} LIMIT 0", {}).columns
        types = {r[0]: r[1] for r in db.read(f"DESCRIBE SELECT * FROM {from_sql}", {}).rows}
    return [(n, types.get(n, "VARCHAR" if n == "filename" else "")) for n in names]


def _short(v: Any) -> str:
    return shorten(str(v), 80)


def sniff(db: Database, rs: ResolvedSource, source: str) -> SourceInfo:
    from_sql = reader_sql(rs)
    if rs.kind == "table":
        schema, _, table = rs.db_path.rpartition(".")
        found = db.read(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %(t)s "
            "AND table_schema = COALESCE(NULLIF(%(s)s, ''), current_schema())",
            {"t": table, "s": schema},
        )
        if not found.rows or schema == "extractor":
            raise UserFacingError(f"There is no table named '{rs.db_path}' that can be used as a log source.")
    columns = relation_columns(db, from_sql, source, rs.remote)
    with readable(source, rs.remote):
        sample = db.read(f"SELECT * FROM {from_sql} LIMIT 5", {})
        info = SourceInfo(rs, from_sql, columns, sample.dicts(), size_bytes=rs.size_bytes)
        if rs.kind == "parquet":
            lit = sql_literal(rs.db_path)
            meta = db.read(
                "SELECT sum(num_rows)::bigint AS n, count(*) AS files, sum(file_size_bytes)::bigint AS size, "
                f"sum(num_row_groups)::bigint AS groups FROM parquet_file_metadata({lit})",
                {},
            ).dicts()[0]
            info.row_count, info.num_files, info.size_bytes, info.row_groups = (
                meta["n"],
                meta["files"],
                meta["size"],
                meta["groups"],
            )
            big = db.read(
                "SELECT path_in_schema AS c, sum(total_compressed_size)::bigint AS b "
                f"FROM parquet_metadata({lit}) GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
                {},
            )
            info.big_columns = [(r[0], int(r[1])) for r in big.rows]
        elif rs.kind == "table":
            info.row_count = db.read(f"SELECT count(*) FROM {from_sql}", {}).scalar()
    return info


def sample_values(info: SourceInfo) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in info.samples:
        for k, v in row.items():
            if v is not None:
                out.setdefault(k, []).append(_short(v))
    return out


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n} B"
