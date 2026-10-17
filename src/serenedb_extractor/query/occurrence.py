"""Occurrence IDs: an entry's position in its log source, so it can be found again.

- in place (Parquet/JSON files): `<filename>#<file_row_number>`. For JSON, SereneDB's
  file_row_number is a byte offset into the file, not a row count: still unique and stable, which
  is all an ID needs.
- copied tables: `e:<entry_id>`.
- table sources: `pk:<value>` of the order role, when the table has one.
"""

from typing import Any

from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query.filters import role_sql


def kind(lt: LogTable) -> str | None:
    if lt.mode == "copied":
        return "entry"
    if lt.source_format in ("parquet", "json"):
        return "file"
    return "pk" if lt.roles.order is not None else None


def select_sql(lt: LogTable) -> str:
    """Extra SELECT items (with a leading comma) that `encode_occurrence` needs, or ""."""
    k = kind(lt)
    if k == "file":
        return ", filename AS occ_file, file_row_number AS occ_row"
    if k == "entry":
        return ", entry_id AS occ_row"
    if k == "pk":
        return f", ({role_sql(lt, 'order')})::varchar AS occ_pk"
    return ""


def encode_occurrence(lt: LogTable, row: dict[str, Any]) -> str:
    k = kind(lt)
    if k == "file":
        return f"{row['occ_file']}#{row['occ_row']}"
    if k == "entry":
        return f"e:{row['occ_row']}"
    if k == "pk":
        return f"pk:{row['occ_pk']}"
    return ""


class BadOccurrence(UserFacingError):
    def __init__(self, occ: str, expected: str) -> None:
        super().__init__(f"'{occ}' is not an occurrence ID of this log table; they look like {expected}.")


def decode_occurrence(lt: LogTable, occ: str) -> tuple[str, dict[str, Any]]:
    """A WHERE body (with params) that finds the entry again."""
    text = occ.strip()
    k = kind(lt)
    if k == "file":
        name, sep, num = text.rpartition("#")
        if not sep or not name or not num.isdigit():
            raise BadOccurrence(occ, "<file>#<row>")
        return "filename = %(occ_file)s AND file_row_number = %(occ_row)s", {"occ_file": name, "occ_row": int(num)}
    if k == "entry":
        num = text.removeprefix("e:")
        if not text.startswith("e:") or not num.isdigit():
            raise BadOccurrence(occ, "e:<number>")
        return "entry_id = %(occ_row)s", {"occ_row": int(num)}
    if k == "pk":
        if not text.startswith("pk:"):
            raise BadOccurrence(occ, "pk:<value>")
        return f"({role_sql(lt, 'order')})::varchar = %(occ_pk)s", {"occ_pk": text[3:]}
    raise UserFacingError("This log table has no column that identifies an entry, so it has no occurrence IDs.")
