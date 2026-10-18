"""Time-zone resolution shared by query and setup."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from serenedb_extractor.errors import UserFacingError

_UTC_NAMES = {"UTC", "ETC/UTC", "GMT", "ETC/GMT", "UCT", "ETC/UCT", "UNIVERSAL", "ETC/UNIVERSAL", "ZULU", "ETC/ZULU"}


def get_zone(tz: str) -> ZoneInfo:
    if tz.strip().upper() in ("UTC", "Z", "GMT", "ETC/UTC"):
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz.strip())
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise UserFacingError(f"'{tz}' is not a time zone I know; use an IANA name like UTC or Europe/Paris.") from None


def is_utc(tz: str) -> bool:
    """True for the names of UTC itself (not for zones that merely sit at offset 0 part of the year)."""
    return tz.strip().upper() in _UTC_NAMES


def is_zone_name(tz: str) -> bool:
    try:
        get_zone(tz)
    except UserFacingError:
        return False
    return True


def offset_text(local: datetime) -> str:
    """The UTC offset of an aware time as ISO 8601 text, e.g. -07:00."""
    off = local.strftime("%z")
    return f"{off[:3]}:{off[3:5]}"
