"""I2 (final review): the catalog matches template regexes with RE2, the engine SereneDB uses, never
Python `re` (they disagree on syntax such as POSIX classes, so a merge or a suggestion could differ
from what the SQL counts)."""

from rcagent.catalog.models import Template
from rcagent.catalog.store import CatalogStore

POSIX = "^[[:alpha:]]+ failed$"  # RE2: letters then " failed"; Python re: a nested set (FutureWarning)


def _t(tid: str, regex: str, template: str = "x") -> Template:
    return Template("lt", tid, template, regex, [], "", None, None, None, None)


def test_full_match_uses_re2_semantics():
    from rcagent.catalog.store import full_match

    assert full_match(POSIX, "login failed")
    assert not full_match(POSIX, "login 3 failed")


def test_closest_matches_with_re2(monkeypatch):
    store = CatalogStore(db=None)  # type: ignore[arg-type]
    monkeypatch.setattr(store, "templates", lambda log_table: [_t("T1", POSIX)])
    assert store._closest("lt", "login failed") == ["T1"]
