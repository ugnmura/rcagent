"""Which columns an existing index covers (read from the catalog), and the estimates made this session.

Kept apart from setup/indexes.py so that query code can ask "does an index serve these columns" without
importing the setup package.
"""

from collections.abc import Collection
from typing import TYPE_CHECKING, Literal

from rcagent.catalog.models import FieldRoles, LogTable
from rcagent.catalog.store import CatalogStore

if TYPE_CHECKING:
    from rcagent.setup.indexes import IndexEstimate

IndexKind = Literal["filter", "search"]
KINDS: tuple[IndexKind, ...] = ("filter", "search")


def index_name_of(lt: LogTable, kind: IndexKind) -> str | None:
    return lt.filter_index_name if kind == "filter" else lt.search_index_name


def covering(store: CatalogStore, lt: LogTable, columns: Collection[str]) -> tuple[IndexKind, str, frozenset[str]] | None:
    """(kind, index name, covered columns) of the first existing index of `lt` that covers every column."""
    wanted = set(columns)
    covered = store.index_columns(lt.name)
    for kind in KINDS:
        name = index_name_of(lt, kind)
        cols = covered.get(kind)
        if name and cols is not None and wanted <= cols:
            return kind, name, cols
    return None


def all_covered(store: CatalogStore, lt: LogTable) -> frozenset[str]:
    out: frozenset[str] = frozenset()
    for cols in store.index_columns(lt.name).values():
        out |= cols
    return out


def _roles_key(roles: FieldRoles) -> tuple[object, ...]:
    return tuple(sorted(vars(roles).items()))


class EstimateCache:
    """Index estimates made in this server session, keyed by source, field roles and kind (so they are
    not reused after the roles change); forgotten for a source when its setup runs again."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, tuple[object, ...], str], "IndexEstimate"] = {}

    def get(self, source: str, roles: FieldRoles, kind: IndexKind) -> "IndexEstimate | None":
        return self._items.get((source.strip(), _roles_key(roles), kind))

    def put(self, source: str, roles: FieldRoles, kind: IndexKind, est: "IndexEstimate") -> None:
        self._items[(source.strip(), _roles_key(roles), kind)] = est

    def clear(self, source: str) -> None:
        for key in [k for k in self._items if k[0] == source.strip()]:
            del self._items[key]

    def hints(self, lt: LogTable) -> dict[str, str]:
        """Kind -> '≈X GB, ~N min to build' for the indexes of `lt` estimated earlier."""
        out: dict[str, str] = {}
        for kind in KINDS:
            est = self.get(lt.source, lt.roles, kind)
            if est is not None:
                out[kind] = est.hint()
        return out
