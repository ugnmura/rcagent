"""Time-zone resolution shared by query and setup."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from serenedb_extractor.errors import UserFacingError


def get_zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise UserFacingError(f"'{tz}' is not a time zone I know; use an IANA name like UTC or Europe/Paris.") from None
