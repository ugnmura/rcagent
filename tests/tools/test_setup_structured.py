import psycopg
import pytest

from serenedb_extractor.catalog.store import CatalogStore
from serenedb_extractor.query.filters import Filters, MissingRole, build_where, diagnose_empty, parse_time_range
from serenedb_extractor.tools.describe import known_columns
from tests.conftest import call, container_parquet
from tests.fixtures.data import FX

pytestmark = pytest.mark.db


@pytest.fixture
def fx_path(db_url):
    return container_parquet(db_url, "fx", FX)


@pytest.fixture
async def fx_lt(mcp, fx_path):
    await call(mcp, "setup_log_table", name="fx", source=fx_path)
    return fx_path


async def test_inspect_has_no_side_effects(mcp, fx_path):
    out = await call(mcp, "inspect_source", source=fx_path)
    assert "level: level" in out and "read in place" in out
    assert "no log tables yet" in await call(mcp, "describe_logs")


async def test_inspect_maps_opentelemetry_names(mcp, db_url):
    path = container_parquet(
        db_url,
        "otel",
        "SELECT TIMESTAMPTZ '2026-03-01 00:00:00+00'::timestamptz_ns AS \"Timestamp\", 'error' AS \"SeverityText\", "
        "'payments' AS \"ServiceName\", 'abc' AS \"TraceId\", 'boom happened here' AS \"Body\", 'x' AS \"Other\"",
    )
    out = await call(mcp, "inspect_source", source=path)
    assert "timestamp: Timestamp" in out and "message: Body" in out and "level: SeverityText" in out
    assert "service: ServiceName" in out and "trace: TraceId" in out and "host: absent" in out


async def test_message_falls_back_to_widest_text_column(mcp, db_url):
    path = container_parquet(
        db_url, "wide", "SELECT now() AS ts, 'a' AS tag, 'a much longer free text column value' AS what"
    )
    assert "message: what" in await call(mcp, "inspect_source", source=path)


async def test_setup_and_describe(mcp, fx_path):
    await call(mcp, "setup_log_table", name="fx", source=fx_path)
    out = await call(mcp, "describe_logs", log_table="fx")
    assert "in place" in out and "host: absent" in out and "context scopes: trace, service, everything" in out
    assert "sampled — rare values may be missing" in out and "ERROR" in out
    assert "entries: 5,000" in out and "indexes: none" in out and "2026-03-01 00:00:00 to 2026-03-02" in out


async def test_setup_creates_view_not_copy(mcp, fx_path, database):
    out = await call(mcp, "setup_log_table", name="fx", source=fx_path)
    assert "nothing is copied" in out
    assert database.read("SELECT count(*) FROM extractor.lt_fx").scalar() == 5000
    kinds = database.read("SELECT table_type FROM information_schema.tables WHERE table_name = 'lt_fx'").rows
    assert kinds == [("VIEW",)]


async def test_correct_roles(mcp, fx_path):
    await call(mcp, "setup_log_table", name="fx", source=fx_path)
    assert "updated field roles: component" in await call(
        mcp, "setup_log_table", name="fx", source=fx_path, roles={"component": "service"}
    )
    assert "component: service" in await call(mcp, "describe_logs", log_table="fx")


async def test_rejects_unsafe_role_expression(mcp, fx_path):
    await call(mcp, "setup_log_table", name="fx", source=fx_path)
    for bad in ("level; DROP TABLE x", "nosuchcolumn", "level, message", "lower(level)", "level ->> 'a' || 'b'"):
        out = await call(mcp, "setup_log_table", name="fx", source=fx_path, roles={"level": bad})
        assert "not an allowed field" in out, bad
    assert "level: level" in await call(mcp, "describe_logs", log_table="fx")
    out = await call(mcp, "setup_log_table", name="fy", source=fx_path, roles={"level": "level; DROP TABLE x"})
    assert "not an allowed field" in out and "no log tables" not in out
    assert "fy" not in await call(mcp, "describe_logs")


async def test_clearing_a_role_marks_it_absent(mcp, fx_lt):
    out = await call(mcp, "setup_log_table", name="fx", source=fx_lt, roles={"trace": None})
    assert "updated field roles: trace" in out
    assert "context scopes: service, everything" in await call(mcp, "describe_logs", log_table="fx")


async def test_find_values(mcp, fx_lt):
    def fv(like):
        return call(mcp, "describe_logs", log_table="fx", find_values={"role_or_column": "service", "like": like})

    assert "payments" in await fv("pay") and "no values like 'billing' in service" in await fv("billing")


async def test_find_values_respects_time_range(mcp, fx_lt):
    out = await call(
        mcp,
        "describe_logs",
        log_table="fx",
        find_values={"role_or_column": "service", "like": "pay"},
        start="2030-01-01",
        end="2030-01-02",
    )
    assert "no values like 'pay' in service" in out and "data covers 2026-03-01" in out


async def test_time_range_outside_data(mcp, fx_lt):
    assert "data covers 2026-03-01" in await call(
        mcp, "describe_logs", log_table="fx", start="2030-01-01", end="2030-01-02"
    )


async def test_time_range_inside_data_and_zone(mcp, fx_lt):
    out = await call(
        mcp, "describe_logs", log_table="fx", start="2026-03-01T09:00:00", end="2026-03-01T10:00:00", timezone="Asia/Tokyo"
    )
    assert "Asia/Tokyo" in out and "ERROR" in out and "data covers" not in out


async def test_remote_raw_rejected(mcp):
    assert "raw text" in (await call(mcp, "inspect_source", source="https://example.com/app.log")).lower()
    assert "raw text" in (await call(mcp, "setup_log_table", name="x", source="s3://b/app.log")).lower()


async def test_local_raw_text_not_available_yet(mcp):
    out = await call(mcp, "setup_log_table", name="app", source="/logs/app.log")
    assert "raw text setup isn't available yet" in out


async def test_filter_on_absent_role(mcp, fx_lt):
    out = await call(mcp, "describe_logs", log_table="fx", find_values={"role_or_column": "host", "like": "x"})
    assert "no host" in out.lower()


async def test_unreadable_source_is_explained(mcp):
    out = await call(mcp, "inspect_source", source="https://example.invalid/none.parquet")
    assert out.startswith("SereneDB could not read") and "private" in out and "Traceback" not in out


async def test_json_source_and_json_path_role(mcp, db_url):
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute(  # type: ignore[call-overload]
            "COPY (SELECT TIMESTAMPTZ '2026-03-01 00:00:00+00' + i * INTERVAL '1 minute' AS ts, "
            "'INFO' AS level, 'hello ' || i::VARCHAR AS message, '{\"svc\":\"cart\"}'::JSON AS attrs "
            "FROM range(10) t(i)) TO '/tmp/js.json' (FORMAT JSON)"
        )
    await call(mcp, "setup_log_table", name="js", source="/tmp/js.json")
    out = await call(mcp, "setup_log_table", name="js", source="/tmp/js.json", roles={"service": "attrs ->> 'svc'"})
    assert "updated field roles: service" in out
    desc = await call(mcp, "describe_logs", log_table="js")
    assert "json" in desc and "service: attrs ->> 'svc'" in desc and "cart" in desc


async def test_existing_table_source(mcp, database):
    database.write("DROP TABLE IF EXISTS public.app_logs")
    database.write("CREATE TABLE public.app_logs (ts TIMESTAMPTZ, level VARCHAR, message VARCHAR)")
    database.write("INSERT INTO public.app_logs VALUES ('2026-03-01 00:00:00+00', 'WARN', 'disk almost full')")
    out = await call(mcp, "setup_log_table", name="tbl", source="public.app_logs")
    assert "existing table" in out
    desc = await call(mcp, "describe_logs", log_table="tbl")
    assert "WARN" in desc and "entries: 1" in desc
    database.write("DROP TABLE public.app_logs")


async def test_rerun_with_other_source_refused(mcp, fx_lt, db_url):
    other = container_parquet(db_url, "fx2", FX)
    out = await call(mcp, "setup_log_table", name="fx", source=other)
    assert "already exists" in out


async def test_unknown_log_table(mcp):
    assert "no log table named 'nope'" in await call(mcp, "describe_logs", log_table="nope")


async def test_diagnose_empty_names_the_filter(mcp, fx_lt, database):
    store = CatalogStore(database)
    lt = store.get_log_table("fx")
    cols = known_columns(database, lt)
    tr = parse_time_range(None, None)
    lines = diagnose_empty(database, lt, tr, Filters(level="error"), cols)
    assert lines[0].startswith("level='error' matched nothing (seen: ERROR, WARN")
    lines = diagnose_empty(database, lt, tr, Filters(level="WARN", service="payments"), cols)
    assert any("no entry matches all of them together" in x for x in lines)
    assert diagnose_empty(database, lt, parse_time_range("2030-01-01", None), Filters(), cols)[0].startswith(
        "No entries from"
    )


async def test_build_where_filters_and_time(mcp, fx_lt, database):
    store = CatalogStore(database)
    lt = store.get_log_table("fx")
    cols = known_columns(database, lt)
    tr = parse_time_range("2026-03-01", "2026-03-02")
    sql, params = build_where(lt, tr, Filters(level="ERROR", service=["payments", "checkout"]), cols)
    n = database.read(f"SELECT count(*) FROM {lt.relation} WHERE {sql}", params).scalar()
    assert 0 < n < 3030
    with pytest.raises(MissingRole):
        build_where(lt, tr, Filters(host="h"), cols)
    sql, params = build_where(lt, tr, Filters(columns={"trace_id": "t-1; DROP TABLE x"}), cols)
    assert "DROP" not in sql
    assert database.read(f"SELECT count(*) FROM {lt.relation} WHERE {sql}", params).scalar() == 0


async def test_nanosecond_timestamp_column_time_range(mcp, db_url):
    path = container_parquet(
        db_url,
        "otel_ns",
        "SELECT (TIMESTAMPTZ '2026-03-01 00:00:00+00' + i * INTERVAL '1 minute')::timestamptz_ns AS \"Timestamp\", "
        "'error' AS \"SeverityText\", 'payments' AS \"ServiceName\", 'boom ' || i::VARCHAR AS \"Body\" FROM range(60) t(i)",
    )
    await call(mcp, "setup_log_table", name="otel", source=path)
    out = await call(mcp, "describe_logs", log_table="otel", start="2026-03-01T00:10:00", end="2026-03-01T00:20:00")
    assert "entries in 2026-03-01 00:10:00 to 2026-03-01 00:20:00 UTC: 10" in out
    assert "error (10)" in out and "2026-03-01 00:00:00 to 2026-03-01 00:59:00" in out


async def test_percent_and_quote_in_path(mcp, db_url):
    path = container_parquet(db_url, "we'ird%s%d", FX)
    out = await call(mcp, "inspect_source", source=path)
    assert "level: level" in out
    assert "entries: 5,000" in await call(mcp, "setup_log_table", name="odd", source=path)
    desc = await call(mcp, "describe_logs", log_table="odd")
    assert "time range: 2026-03-01 00:00:00 to" in desc and "from Parquet statistics" in desc and "ERROR" in desc
    out = await call(mcp, "describe_logs", log_table="odd", start="2026-03-01", end="2026-03-02")
    assert "ERROR" in out
    out = await call(mcp, "describe_logs", log_table="odd", find_values={"role_or_column": "service", "like": "100%"})
    assert "no values like '100%' in service" in out


async def test_percent_and_quote_in_json_path_role(mcp, db_url):
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute(  # type: ignore[call-overload]
            "COPY (SELECT TIMESTAMPTZ '2026-03-01 00:00:00+00' + i * INTERVAL '1 minute' AS ts, "
            "'INFO' AS level, 'hello ' || i::VARCHAR AS message, '{\"a\'\'b%c\":\"cart\"}'::JSON AS attrs "
            "FROM range(5) t(i)) TO '/tmp/pct.json' (FORMAT JSON)"
        )
    await call(mcp, "setup_log_table", name="pct", source="/tmp/pct.json")
    role = "attrs ->> 'a''b%c'"
    out = await call(mcp, "setup_log_table", name="pct", source="/tmp/pct.json", roles={"service": role})
    assert "updated field roles: service" in out
    desc = await call(mcp, "describe_logs", log_table="pct", start="2026-03-01", end="2026-03-02")
    assert "service: attrs ->> 'a''b%c'" in desc and "cart (5)" in desc
    out = await call(mcp, "describe_logs", log_table="pct", find_values={"role_or_column": "service", "like": "car"})
    assert "cart (5)" in out


async def test_message_role_given_when_it_cannot_be_guessed(mcp, db_url):
    path = container_parquet(db_url, "nomsg", "SELECT now() AS ts, 5 AS num, 7 AS other")
    assert "message" in (await call(mcp, "setup_log_table", name="nm", source=path)).lower()
    assert "no log table named 'nm'" in await call(mcp, "describe_logs", log_table="nm")
    out = await call(mcp, "setup_log_table", name="nm", source=path, roles={"message": "num"})
    assert "message: num" in out
    assert "message: num" in await call(mcp, "describe_logs", log_table="nm")


async def test_bad_name_is_plain(mcp, fx_path):
    out = await call(mcp, "setup_log_table", name="Bad Name", source=fx_path)
    assert "not a usable name" in out and "went wrong" not in out


async def test_sereneDB_error_is_plain_and_next_call_works(mcp, fx_path):
    for tool_args in (("inspect_source", {}), ("setup_log_table", {"name": "gone"})):
        out = await call(mcp, tool_args[0], source="/tmp/does-not-exist-123.parquet", **tool_args[1])
        assert out.startswith("SereneDB could not read") and "Could not reach" not in out and "went wrong" not in out
        assert "level: level" in await call(mcp, "inspect_source", source=fx_path)


async def test_time_range_label_says_how_it_was_found(mcp, fx_lt, db_url):
    assert "(from Parquet statistics)" in await call(mcp, "describe_logs", log_table="fx")
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute(  # type: ignore[call-overload]
            "COPY (SELECT TIMESTAMPTZ '2026-03-01 00:00:00+00' + i * INTERVAL '1 minute' AS ts, 'hi' AS message "
            "FROM range(5) t(i)) TO '/tmp/lbl.json' (FORMAT JSON)"
        )
    await call(mcp, "setup_log_table", name="lbl", source="/tmp/lbl.json")
    out = await call(mcp, "describe_logs", log_table="lbl")
    assert "(from a scan of the timestamp column)" in out and "(from Parquet statistics)" not in out


async def test_rerun_updates_time_zone(mcp, fx_lt):
    out = await call(mcp, "setup_log_table", name="fx", source=fx_lt, timezone="Asia/Tokyo")
    assert "updated time zone: Asia/Tokyo" in out and "updated field roles" not in out
    out = await call(mcp, "setup_log_table", name="fx", source=fx_lt)
    assert "nothing changed" in out
    out = await call(mcp, "setup_log_table", name="fx", source=fx_lt, timezone="Nowhere/Land")
    assert "time zone" in out and "Nowhere/Land" in out


async def test_user_text_says_entries_not_rows(mcp, fx_path):
    for out in (
        await call(mcp, "inspect_source", source=fx_path),
        await call(mcp, "setup_log_table", name="fx", source=fx_path),
        await call(mcp, "describe_logs", log_table="fx"),
    ):
        assert "rows" not in out.replace("row groups", "") and "catalog entry" not in out
