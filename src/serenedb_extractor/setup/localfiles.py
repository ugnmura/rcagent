"""Local files read by this process: opening, line splitting, and what the size means."""

import gzip
import os
import re
from collections.abc import Iterator
from typing import IO, Any, cast

from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.setup.paths import ResolvedSource
from serenedb_extractor.setup.sniff import human_bytes

HEAD_BYTES = 262_144  # how much of a file is read to recognise its format
LARGE_BYTES = 1_000_000_000
_NEWLINE = re.compile(r"\r\n|\r|\n")


def open_local(path: str, binary: bool = False) -> IO[Any]:
    """Open a local file for reading; `.gz` files are decompressed. Text is UTF-8, bad bytes replaced."""
    gz = path.lower().endswith(".gz")
    mode = "rb" if binary else "rt"
    kw: dict[str, Any] = {} if binary else {"encoding": "utf-8", "errors": "replace"}
    return cast(IO[Any], gzip.open(path, mode, **kw) if gz else open(path, mode, **kw))


def head_lines(path: str, max_bytes: int = HEAD_BYTES) -> list[str]:
    """The first complete lines of a local file, reading at most `max_bytes` of it."""
    with open_local(path, binary=True) as f:
        data = f.read(max_bytes)
    lines = data.decode("utf-8", errors="replace").splitlines()
    if len(data) >= max_bytes and len(lines) > 1:
        lines.pop()  # the last one was cut by the byte limit
    return lines


def host_lines(path: str) -> Iterator[str]:
    with open_local(path) as f:
        yield from f


def split_lines(text: str) -> list[str]:
    """Split like reading a file line by line: only \\n, \\r\\n and \\r end a line; no trailing empty line."""
    lines = _NEWLINE.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def require_file(rs: ResolvedSource, source: str) -> None:
    if not os.path.isfile(rs.db_path):
        raise UserFacingError(
            f"There is no file at {source} on this machine (and it is not under the mounted logs folder)."
        )


def under_mount(rs: ResolvedSource) -> bool:
    return rs.host_path is not None


def copy_needed(rs: ResolvedSource) -> bool:
    """True when this process must read the file and stream it in: raw text always (it is parsed
    here), a structured local file when it is outside the mounted folder and exists on this machine."""
    if rs.kind == "raw_text":
        return True
    return rs.kind in ("parquet", "json", "csv") and not rs.remote and rs.host_path is None and os.path.isfile(rs.db_path)


def large_input_notes(rs: ResolvedSource) -> list[str]:
    """Plain warnings for an input over 1 GB: the full copy (outside the mount) and the memory limits."""
    if rs.size_bytes is None or rs.size_bytes <= LARGE_BYTES:
        return []
    size = human_bytes(rs.size_bytes)
    notes = []
    if not under_mount(rs):
        notes.append(
            f"Warning: this file is {size} and outside the mounted folder, so this is a full copy that is read "
            "here and streamed in; mounting the folder would avoid it."
        )
    notes.append(
        f"Warning: this file is {size}. Large files are processed in memory, so very large or out-of-order "
        "files may be slow or fail."
    )
    return notes
