import pytest

from serenedb_extractor.catalog.store import CatalogStore
from tests.conftest import call, container_parquet, id_of, ids_in
from tests.fixtures.data import FX, USERS

pytestmark = pytest.mark.db

A, B, C = ("2026-03-01", "2026-03-02"), ("2026-03-02", "2026-03-03"), ("2026-03-03", "2026-03-04")


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, "fx", FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


@pytest.fixture
async def users_lt(mcp, db_url):
    for phase, sql in USERS.items():
        container_parquet(db_url, f"t11users_{phase}", sql)
    await call(mcp, "setup_log_table", name="users", source="/tmp/t11users_*.parquet")


async def survey_a(mcp):
    """Phase A seen one person at a time: alice, bob and carol become three templates."""
    return [
        await call(mcp, "survey", log_table="users", start=A[0], end=A[1], filters={"service": s})
        for s in ("web", "api", "cli")
    ]


async def survey_b(mcp):
    """Phase B, broader views: all users, then all admins."""
    return [
        await call(mcp, "survey", log_table="users", start=B[0], end=B[1], filters={"level": lv})
        for lv in ("WARN", "ERROR")
    ]


async def test_generalize_keeps_id(mcp, users_lt):
    a = (await survey_a(mcp))[0]
    b = (await survey_b(mcp))[0]
    assert id_of(a, "login failed for user alice") == id_of(b, "login failed for user <*>")


async def test_a_narrower_candidate_never_narrows_a_template(mcp, users_lt, database):
    """A broad template whose example is one narrow variant: surveying that variant alone again must not
    shrink the broad template back to it (BGL's CioStream "<*> <*> <*> <*>" vs "Link has been severed")."""
    from datetime import datetime

    from serenedb_extractor.catalog.models import CandidateTemplate
    from serenedb_extractor.templating.regex import compile_template

    def cand(text: str, example: str) -> CandidateTemplate:
        c = compile_template(text)
        return CandidateTemplate(text, c.regex, list(c.params), example, None, None, 1)

    store = CatalogStore(database)
    broad = store.upsert_survey_templates("users", [cand("socket closed: <*> <*>", "socket closed: link severed")], datetime(2026, 4, 1))
    broad_id = broad.items[0][0].template_id
    narrow = store.upsert_survey_templates("users", [cand("socket closed: link severed", "socket closed: link severed")], datetime(2026, 4, 2))
    saved, status = narrow.items[0]
    assert status == "new" and saved.template_id != broad_id
    assert store.resolve("users", broad_id).template.template == "socket closed: <*> <*>"
    # a typed placeholder is narrower than <*>: "<PATH>" never replaces "<*>" either
    wide = store.upsert_survey_templates("users", [cand("open failed: <*>", "open failed: /tmp/x")], datetime(2026, 4, 3))
    typed = store.upsert_survey_templates("users", [cand("open failed: <PATH>", "open failed: /tmp/x")], datetime(2026, 4, 4))
    assert typed.items[0][1] == "new"
    assert store.resolve("users", wide.items[0][0].template_id).template.template == "open failed: <*>"
    # and the broadest template covering a narrow one is found for ranking
    from serenedb_extractor.catalog.store import covering

    assert covering(saved, store.templates("users")).template_id == broad_id


async def test_merge_redirect_and_note(mcp, users_lt, database):
    _, bob, carol_out = await survey_a(mcp)
    bob_id, carol = id_of(bob, "login failed for admin bob"), id_of(carol_out, "login failed for admin carol")
    assert bob_id != carol
    merge_out = (await survey_b(mcp))[1]
    assert id_of(merge_out, "login failed for admin <*>") == bob_id  # oldest ID survives
    out = await call(mcp, "survey", log_table="users", exclude=[carol])
    assert f"{carol} was merged into {bob_id}" in out
    assert database.read("SELECT count(*) FROM extractor.templates WHERE template_id = %(i)s", {"i": carol}).scalar() == 0
    # a redirect never points at a deleted ID: every hop ends at a live template
    live = {t.template_id for t in CatalogStore(database).templates("users")}
    assert {r["new_id"] for r in database.read("SELECT new_id FROM extractor.template_redirects").dicts()} <= live


async def test_redirects_stay_one_hop(mcp, users_lt, database):
    a, b, c = await survey_a(mcp)
    alice, bob, carol = id_of(a, "alice"), id_of(b, "admin bob"), id_of(c, "admin carol")
    await survey_b(mcp)  # carol -> bob
    store = CatalogStore(database)
    assert store.resolve("users", carol).template.template_id == bob
    # a broader template now swallows bob too (it matches every A example): everything points at the lowest ID
    from datetime import datetime

    from serenedb_extractor.catalog.models import CandidateTemplate
    from serenedb_extractor.templating.regex import compile_template

    compiled = compile_template("login failed for <*> <*>")
    cand = CandidateTemplate("login failed for <*> <*>", compiled.regex, list(compiled.params), "login failed for user zed", None, None, 1)
    store.upsert_survey_templates("users", [cand], datetime(2026, 4, 1))
    assert store.resolve("users", carol).template.template_id == alice
    assert store.resolve("users", bob).template.template_id == alice
    hops = {r["old_id"]: r["new_id"] for r in database.read("SELECT old_id, new_id FROM extractor.template_redirects").dicts()}
    assert hops == {carol: alice, bob: alice}


async def test_ids_never_reused(mcp, users_lt):
    await survey_a(mcp)
    await survey_b(mcp)
    c = await call(mcp, "survey", log_table="users", start=C[0], end=C[1])
    assert id_of(c, "disk full on <PATH>") == "T4"


async def test_first_seen_is_the_earliest(mcp, users_lt, database):
    a = (await survey_a(mcp))[0]
    await survey_b(mcp)
    tid = id_of(a, "login failed for user alice")
    first = database.read("SELECT first_seen FROM extractor.templates WHERE template_id = %(i)s", {"i": tid}).scalar()
    assert first.date().isoformat() == "2026-03-01"


async def test_exclude_surfaces_rare(mcp, fx_lt):
    first = await call(mcp, "survey", log_table="fx", sample_size=500)
    noisy = [i for i in ids_in(first) if i != id_of(first, "disk full on <PATH>")] if "disk full" in first else ids_in(first)
    assert "disk full on <PATH>" in await call(mcp, "survey", log_table="fx", exclude=noisy, sample_size=500)


async def test_exclude_hides_templates_and_says_so(mcp, fx_lt):
    first = await call(mcp, "survey", log_table="fx")
    timeout = id_of(first, "timeout after <NUM>ms calling payments")
    out = await call(mcp, "survey", log_table="fx", exclude=[timeout])
    assert "timeout after" not in out and f"excluding templates {timeout}" in out
    assert "isn't available yet" not in out
    assert "login failed for user <*>" in out


async def test_rename(mcp, fx_lt):
    tid = id_of(await call(mcp, "survey", log_table="fx"), "login failed for user <*>")
    assert "username" in await call(mcp, "rename_parameter", log_table="fx", template=tid, old_name="user", new_name="username")
    assert "invalid" in (await call(mcp, "rename_parameter", log_table="fx", template=tid, old_name="username", new_name="Bad Name")).lower()


async def test_rename_is_permanent_and_unique(mcp, fx_lt, database):
    first = await call(mcp, "survey", log_table="fx")
    tid = id_of(first, "login failed for user <*>")
    await call(mcp, "rename_parameter", log_table="fx", template=tid, old_name="user", new_name="username")
    await call(mcp, "survey", log_table="fx")  # a later survey leaves the name alone
    names = [p.name for t in CatalogStore(database).templates("fx") if t.template_id == tid for p in t.params]
    assert names == ["username"]
    assert "no parameter" in (await call(mcp, "rename_parameter", log_table="fx", template=tid, old_name="user", new_name="x")).lower()
    timeout = id_of(first, "timeout after <NUM>ms calling payments")
    assert "invalid" in (await call(mcp, "rename_parameter", log_table="fx", template=tid, old_name="username", new_name="1abc")).lower()
    assert timeout != tid


async def test_rename_survives_generalization(mcp, users_lt, database):
    from datetime import datetime

    from serenedb_extractor.catalog.models import CandidateTemplate
    from serenedb_extractor.templating.regex import compile_template

    store = CatalogStore(database)
    await survey_a(mcp)
    await survey_b(mcp)
    tid = id_of(await call(mcp, "survey", log_table="users", filters={"service": "web"}), "login failed for user <*>")
    await call(mcp, "rename_parameter", log_table="users", template=tid, old_name="user", new_name="person")
    broader = compile_template("login failed for <*> <*>")  # position 1 keeps its kind: the name carries over
    cand = CandidateTemplate("login failed for <*> <*>", broader.regex, list(broader.params), "login failed for user zed", None, None, 1)
    store.upsert_survey_templates("users", [cand], datetime(2026, 4, 1))
    assert store.resolve("users", tid).template.params[0].name == "person"


async def test_rename_follows_a_redirect(mcp, users_lt):
    _, bob, carol_out = await survey_a(mcp)
    carol = id_of(carol_out, "login failed for admin carol")
    await survey_b(mcp)
    out = await call(mcp, "rename_parameter", log_table="users", template=carol, old_name="admin", new_name="operator")
    assert "operator" in out and f"{carol} was merged into" in out


async def test_unknown_id(mcp, fx_lt):
    assert "T99" in await call(mcp, "survey", log_table="fx", exclude=["T99"])
    assert "T99" in await call(mcp, "rename_parameter", log_table="fx", template="T99", old_name="a", new_name="b")


async def test_unknown_id_names_the_closest(mcp, fx_lt):
    tid = id_of(await call(mcp, "survey", log_table="fx"), "disk full on <PATH>")
    out = await call(mcp, "survey", log_table="fx", exclude=["disk full on /dev/sda1"])
    assert "no template" in out and tid in out


async def test_rename_parameter_is_not_read_only(mcp):
    tool = next(t for t in (await mcp.list_tools()).tools if t.name == "rename_parameter")
    assert tool.annotations is not None and tool.annotations.readOnlyHint is False and tool.annotations.destructiveHint is False


# --- R34: merges survive partial failure and concurrency -------------------------------------------------


def _cand(text, example):
    from serenedb_extractor.catalog.models import CandidateTemplate
    from serenedb_extractor.templating.regex import compile_template

    c = compile_template(text)
    return CandidateTemplate(text, c.regex, list(c.params), example, None, None, 1)


_WHEN = __import__("datetime").datetime(2026, 4, 1)


def _seed(store):
    """T_user (alice), T_bob, T_carol: carol is merged into bob, so a redirect already exists."""
    user = store.upsert_survey_templates("fx", [_cand("login failed for user alice", "login failed for user alice")], _WHEN)
    bob = store.upsert_survey_templates("fx", [_cand("login failed for admin bob", "login failed for admin bob")], _WHEN)
    carol = store.upsert_survey_templates("fx", [_cand("login failed for admin carol", "login failed for admin carol")], _WHEN)
    ids = [r.items[0][0].template_id for r in (user, bob, carol)]
    store.upsert_survey_templates("fx", [_cand("login failed for admin <*>", "login failed for admin dave")], _WHEN)
    return ids


def _clear(database):
    for table in ("templates", "template_redirects"):
        database.write(f"DELETE FROM extractor.{table} WHERE log_table = 'fx'", {})


BROAD = _cand("login failed for <*> <*>", "login failed for user zed")


async def test_merge_converges_after_a_failure_at_every_write(mcp, fx_lt, database):  # R34
    store = CatalogStore(database)
    real_write = database.write
    step = 1
    while True:
        _clear(database)
        ids = _seed(store)
        calls = {"n": 0}

        def flaky(*a, **kw):
            calls["n"] += 1
            if calls["n"] == step:
                raise RuntimeError("injected")
            return real_write(*a, **kw)

        database.write = flaky  # type: ignore[method-assign]
        try:
            store.upsert_survey_templates("fx", [BROAD], _WHEN)
            failed = False
        except RuntimeError:
            failed = True
        finally:
            database.write = real_write  # type: ignore[method-assign]
        for tid in ids:  # (a) every ID ever issued still resolves
            store.resolve("fx", tid)
        store.upsert_survey_templates("fx", [BROAD], _WHEN)  # (b) a retry converges to the clean state
        live = [t.template_id for t in store.templates("fx")]
        assert live == [ids[0]], (step, live)
        for tid in ids:
            assert store.resolve("fx", tid).template.template_id == ids[0]
        hops = {r["old_id"]: r["new_id"] for r in database.read("SELECT old_id, new_id FROM extractor.template_redirects").dicts()}
        assert hops == {ids[1]: ids[0], ids[2]: ids[0]}, (step, hops)
        if not failed:
            break
        step += 1
    assert step >= 4  # the merge really issues several writes


async def test_concurrent_generalizations_lose_nothing(mcp, fx_lt, database):  # R34
    from concurrent.futures import ThreadPoolExecutor

    store = CatalogStore(database)
    _clear(database)
    ids = [
        store.upsert_survey_templates("fx", [_cand(f"{w} failed here", f"{w} failed here")], _WHEN).items[0][0].template_id
        for w in ("alpha", "beta", "gamma", "delta")
    ]
    wide = [_cand("<*> failed here", "omega failed here"), _cand("<*> failed <*>", "omega failed there")]
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda c: store.upsert_survey_templates("fx", [c], _WHEN), wide))
    for tid in ids:
        store.resolve("fx", tid)
    live = [t.template_id for t in store.templates("fx")]
    assert live == [ids[0]]
