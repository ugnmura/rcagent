"""Occurrence IDs: an entry's position in its log source, so it can be found again.

- in place (Parquet/JSON files): `<filename>#<file_row_number>`. For JSON, SereneDB's
  file_row_number is a byte offset into the file, not a row count: still unique and stable, which
  is all an ID needs.
- copied tables: `e:<entry_id>`.
- table sources: `pk:<value>` of the order role, when the table has one.
"""

import re
from typing import Any

from rcagent.catalog.models import LogTable
from rcagent.errors import UserFacingError
from rcagent.query.filters import role_sql


def kind(lt: LogTable) -> str | None:
    if lt.mode == "copied":
        return "entry"
    if lt.source_format in ("parquet", "json", "csv"):
        return "file"
    return "pk" if lt.roles.order is not None else None


def select_items(lt: LogTable) -> list[tuple[str, str]]:
    """(expression, alias) of every column `encode_occurrence` needs."""
    k = kind(lt)
    if k == "file":
        return [("filename", "occ_file"), ("file_row_number", "occ_row")]
    if k == "entry":
        return [("entry_id", "occ_row")]
    if k == "pk":
        return [(f"({role_sql(lt, 'order')})::varchar", "occ_pk")]
    return []


def select_sql(lt: LogTable) -> str:
    """Extra SELECT items (with a leading comma) that `encode_occurrence` needs, or ""."""
    return "".join(f", {e} AS {a}" for e, a in select_items(lt))


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


# A row number or entry id is a 64-bit integer: 18 digits always fit, more can't be a position.
MAX_DIGITS = 18


def _number(occ: str, num: str, expected: str) -> int:
    """The row number or entry id of an occurrence ID (ASCII digits only), refused plainly when it is
    longer than any entry's position can be."""
    if not re.fullmatch(r"[0-9]+", num):
        raise BadOccurrence(occ, expected)
    digits = num.lstrip("0") or "0"
    if len(digits) > MAX_DIGITS:
        shown = occ if len(occ) <= 60 else occ[:60] + "…"
        raise UserFacingError(
            f"No entry has the occurrence ID '{shown}': its number has {len(digits):,} digits, more than any "
            f"entry's position ({MAX_DIGITS} digits at most). Copy the ID from a search_logs or locate_occurrences result."
        )
    return int(digits)


def decode_occurrence(lt: LogTable, occ: str) -> tuple[str, dict[str, Any]]:
    """A WHERE body (with params) that finds the entry again."""
    text = occ.strip()
    k = kind(lt)
    if k == "file":
        name, sep, num = text.rpartition("#")
        if not sep or not name:
            raise BadOccurrence(occ, "<file>#<row>")
        row = _number(occ, num, "<file>#<row>")
        if "/" not in name and "\\" not in name:  # just the file's name: match it in any folder
            pattern = "%/" + name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            return (
                "filename LIKE %(occ_file)s ESCAPE '\\' AND file_row_number = %(occ_row)s",
                {"occ_file": pattern, "occ_row": row},
            )
        return "filename = %(occ_file)s AND file_row_number = %(occ_row)s", {"occ_file": name, "occ_row": row}
    if k == "entry":
        num = text.removeprefix("e:")
        if not text.startswith("e:"):
            raise BadOccurrence(occ, "e:<number>")
        return "entry_id = %(occ_row)s", {"occ_row": _number(occ, num, "e:<number>")}
    if k == "pk":
        if not text.startswith("pk:"):
            raise BadOccurrence(occ, "pk:<value>")
        return f"({role_sql(lt, 'order')})::varchar = %(occ_pk)s", {"occ_pk": text[3:]}
    raise UserFacingError("This log table has no column that identifies an entry, so it has no occurrence IDs.")
