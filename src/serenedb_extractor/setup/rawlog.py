"""Raw text logs: line formats and multi-line entries."""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.timezones import get_zone

_ISO_TS = (
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_LEVELS = "TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|SEVERE|CRITICAL|FATAL"


@dataclass(frozen=True)
class LineFormat:
    name: str
    regex: re.Pattern[str]
    describes: str
    time_fields: tuple[str, ...]  # named groups joined (with a space) into the timestamp text
    ts_format: str | None = None  # strptime format; None means ISO 8601
    host_field: str | None = None
    ignore: tuple[str, ...] = ()  # groups already carried by another field


LINE_FORMATS: dict[str, LineFormat] = {
    "bgl": LineFormat(
        "bgl",
        re.compile(
            r"^(?P<label>\S+) (?P<timestamp>\d+) (?P<date>\d{4}\.\d{2}\.\d{2}) (?P<node>\S+) "
            r"(?P<time>\d{4}-\d{2}-\d{2}-\d{2}\.\d{2}\.\d{2}(?:\.\d+)?) (?P<noderepeat>\S+) "
            r"(?P<type>\S+) (?P<component>\S+) (?P<level>\S+) (?P<content>.*)$"
        ),
        "<Label> <Timestamp> <Date> <Node> <Time> <NodeRepeat> <Type> <Component> <Level> <Content>",
        ("time",),
        "%Y-%m-%d-%H.%M.%S.%f",
        host_field="node",
        ignore=("date",),
    ),
    "openstack": LineFormat(
        "openstack",
        re.compile(
            r"^(?P<logrecord>\S+) (?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}(?:\.\d+)?) "
            r"(?P<pid>\d+) (?P<level>[A-Z]+) (?P<component>\S+) \[(?P<addr>[^\]]*)\] (?P<content>.*)$"
        ),
        "<Logrecord> <Date> <Time> <Pid> <Level> <Component> [<ADDR>] <Content>",
        ("date", "time"),
    ),
    "generic": LineFormat(
        "generic",
        re.compile(
            rf"^\[?(?P<ts>{_ISO_TS})\]?[ \t]*(?:\[?(?P<level>{_LEVELS})\]?\b)?[ \t]*"
            r"(?:\[(?P<component>[^\]]*)\][ \t]*)?(?P<content>.*)$"
        ),
        "<timestamp> <LEVEL> [<component>] <message>",
        ("ts",),
    ),
}
_DETECT_ORDER = ("bgl", "openstack", "generic")  # most specific first; ties go to the earlier one


@dataclass(frozen=True)
class RawEntry:
    line_start: int  # 1-based
    line_end: int
    ts: datetime | None  # aware, UTC
    level: str | None
    component: str | None
    host: str | None
    message: str
    attrs: dict[str, str]


def line_format_named(name: str) -> LineFormat:
    fmt = LINE_FORMATS.get(name.strip().lower())
    if fmt is None:
        raise UserFacingError(f"Unknown line format '{name}'. Use one of: {', '.join(LINE_FORMATS)}.")
    return fmt


def detect_line_format(lines: Iterable[str], sample: int = 200) -> str:
    """The format that matches the most of the first non-empty lines (generic when none does)."""
    counts = dict.fromkeys(_DETECT_ORDER, 0)
    seen = 0
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        seen += 1
        for name in _DETECT_ORDER:
            if LINE_FORMATS[name].regex.match(line):
                counts[name] += 1
        if seen >= sample:
            break
    best = max(_DETECT_ORDER, key=lambda n: counts[n])
    return best if counts[best] > 0 else "generic"


def parse_ts(text: str, ts_format: str | None, zone: ZoneInfo) -> datetime | None:
    """A UTC instant; zoneless text is read in `zone`. None when the text is not a time."""
    try:
        if ts_format:
            dt = datetime.strptime(text, ts_format)
        else:
            t = text.strip().replace(",", ".")
            dt = datetime.fromisoformat(t[:-1] + "+00:00" if t[-1:] in "Zz" else t)
    except ValueError:
        return None
    return (dt.replace(tzinfo=zone) if dt.tzinfo is None else dt).astimezone(UTC)


def parse_entries(lines: Iterable[str], line_format: str, tz: str) -> Iterator[RawEntry]:
    """Group physical lines into entries: a line that does not match the format continues the
    previous entry; lines before the first match form one entry without a timestamp."""
    fmt = line_format_named(line_format)
    zone = get_zone(tz)
    consumed = {*fmt.time_fields, *fmt.ignore, "level", "component", "content"}
    if fmt.host_field:
        consumed.add(fmt.host_field)
    head: dict[str, str | None] | None = None
    start = end = 0
    parts: list[str] = []
    blanks: list[str] = []

    def finish() -> RawEntry | None:
        if head is None:
            return None
        attrs = {k: v for k, v in head.items() if k not in consumed and v is not None}
        ts_text = " ".join(str(head[f]) for f in fmt.time_fields if head.get(f))
        return RawEntry(
            start,
            end,
            parse_ts(ts_text, fmt.ts_format, zone) if ts_text else None,
            head.get("level") or None,
            head.get("component") or None,
            (head.get(fmt.host_field) or None) if fmt.host_field else None,
            "\n".join(parts),
            attrs,
        )

    for n, raw in enumerate(lines, 1):
        line = raw.rstrip("\r\n").replace("\x00", "")
        m = fmt.regex.match(line)
        if m:
            done = finish()
            if done is not None:
                yield done
            head = m.groupdict()
            start = end = n
            parts = [head["content"] or ""]
            blanks = []
        elif not line.strip():
            if head is not None:
                blanks.append(line)
        else:
            if head is None:  # text before the first timestamped line
                head, start = {}, n
                parts = []
            parts += blanks
            parts.append(line)
            blanks = []
            end = n
    done = finish()
    if done is not None:
        yield done
