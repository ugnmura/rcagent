from dataclasses import dataclass, fields
from datetime import datetime
from typing import Literal

from serenedb_extractor.errors import UserFacingError


@dataclass(frozen=True)
class Param:
    pos: int
    name: str
    kind: str


@dataclass(frozen=True)
class FieldRoles:
    """SQL expressions over a log table's relation; None means the role is absent."""

    message: str
    timestamp: str | None = None
    level: str | None = None
    service: str | None = None
    host: str | None = None
    component: str | None = None
    trace: str | None = None
    order: str | None = None

    def present(self) -> dict[str, str]:
        """The roles that have an expression, by role name."""
        return {k: v for k, v in vars(self).items() if v is not None}


ROLE_FIELDS = tuple(f.name for f in fields(FieldRoles))


@dataclass(frozen=True)
class LogTable:
    name: str
    source: str
    source_format: str
    mode: str
    relation: str
    roles: FieldRoles
    filter_index_name: str | None
    search_index_name: str | None
    row_count: int | None
    timezone: str
    created_at: datetime
    roles_updated_at: datetime


@dataclass(frozen=True)
class Template:
    log_table: str
    template_id: str
    template: str
    regex: str
    params: list[Param]
    example: str
    first_seen: datetime | None
    last_seen: datetime | None
    last_estimate: int | None
    last_estimate_at: datetime | None


@dataclass(frozen=True)
class CandidateTemplate:
    template: str
    regex: str
    params: list[Param]
    example: str
    first_seen: datetime | None
    last_seen: datetime | None
    estimate: int | None


@dataclass(frozen=True)
class UpsertResult:
    items: list[tuple[Template, Literal["new", "generalized", "known"]]]
    merged: dict[str, str]


@dataclass(frozen=True)
class Resolved:
    template: Template
    redirected_from: str | None


class UnknownLogTable(UserFacingError):
    def __init__(self, name: str, known: list[str] | None = None) -> None:
        self.name = name
        self.known = known or []
        hint = f" Known log tables: {', '.join(self.known)}." if self.known else " There are no log tables yet."
        super().__init__(f"There is no log table named '{name}'.{hint}")


class UnknownTemplate(UserFacingError):
    def __init__(self, template_id: str, closest: list[str] | None = None) -> None:
        self.template_id = template_id
        self.closest = closest or []
        hint = f" Closest known IDs: {', '.join(self.closest)}." if self.closest else ""
        super().__init__(f"There is no template '{template_id}' in this log table.{hint}")
