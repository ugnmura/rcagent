import re

import pytest

from rcagent.telemetry.registry import TelemetryStore
from rcagent.telemetry.trace_setup import numeric_status_scheme
from tests.conftest import call, container_parquet
from tests.telemetry import fixtures as fx

pytestmark = pytest.mark.db


@pytest.fixture
def cart_path(db_url):
    return container_parquet(db_url, "a3_tt_cart", fx.traces_sql("cart_fault"))


@pytest.fixture
def net_path(db_url):
    return container_parquet(db_url, "a3_tt_net", fx.traces_sql("network_delay"))


def _self_ms(database, relation, service, operation, before):
    side = "<" if before else ">="
    pivot_us = (fx.BASE_EPOCH + fx.PIVOT_S) * 1_000_000
    rows = database.read(
        f"SELECT DISTINCT self_time_us FROM {relation} WHERE service = %(s)s AND operation = %(o)s "
        f"AND start_us {side} {pivot_us}",
        {"s": service, "o": operation},
    ).rows
    return sorted(float(r[0]) / 1000 for r in rows)


def _line(out, text):
    for line in out.splitlines():
        if text in line:
            return line
    raise AssertionError(f"no line with {text!r} in:\n{out}")


# ------------------------------------------------------------------ setup


async def test_setup_copies_spans_with_self_time_and_reports(mcp, cart_path, database):
    out = await call(mcp, "setup_trace_table", name="shop_traces", source=cart_path)
    assert "extractor.tt_shop_traces" in out
    assert f"spans: {fx.SECONDS * 7:,}" in out
    assert "time range (UTC): 2026-03-01 10:00:00" in out
    assert "services (4): cart, checkout, frontend, payment" in out
    assert "/GetCart" in out and "payment.Charge" in out
    assert "orphan spans: 0" in out
    assert "setup took" in out
    assert "duration_unit: us  (from the column name 'duration_us')" in out
    [tt] = TelemetryStore(database).list_trace_tables()
    assert (tt.relation, tt.start, tt.duration, tt.duration_unit, tt.status) == (
        "extractor.tt_shop_traces", "start_us", "duration_us", "us", "status"
    )
    assert tt.row_count == fx.SECONDS * 7 and tt.orphan_spans == 0 and tt.setup_seconds is not None
    rel = tt.relation
    assert _self_ms(database, rel, "frontend", "/home", True) == [5.0]
    assert _self_ms(database, rel, "frontend", "/home", False) == [5.0]
    assert _self_ms(database, rel, "cart", "/GetCart", True) == [10.0]
    assert _self_ms(database, rel, "cart", "/GetCart", False) == [50.0]
    assert _self_ms(database, rel, "frontend", "cart.GetCart", True) == [1.0]
    assert _self_ms(database, rel, "frontend", "checkout.PlaceOrder", True) == [1.0]


OVERLAP_SQL = """
SELECT * FROM (VALUES
  ('x1', 'p',  NULL, 'api', 'root',  0,    100),
  ('x1', 'c1', 'p',  'db',  'q1',    10,   40),
  ('x1', 'c2', 'p',  'db',  'q2',    30,   40),
  ('x1', 'c3', 'p',  'db',  'q3',    90,   50),
  ('x1', 'o',  'gone', 'api', 'lost', 5,   20)
) v(trace_id, span_id, parent_span_id, service, operation, start, duration_ms)"""


async def test_overlapping_children_are_not_double_counted(mcp, db_url, database):
    path = container_parquet(db_url, "a3_tt_overlap", OVERLAP_SQL)
    out = await call(mcp, "setup_trace_table", name="ov", source=path, roles={"start_unit": "ms"})
    assert "orphan spans: 1" in out
    assert "start_unit: ms  (given by you)" in out
    rows = dict(database.read("SELECT span_id, self_time_us FROM extractor.tt_ov", {}).rows)
    # children cover [10,70) and [90,100) (c3 clipped at the parent's end): 70 ms of 100
    assert float(rows["p"]) == 30_000
    assert float(rows["o"]) == 20_000  # an orphan keeps its full duration


STATUS_SQL = """
SELECT * FROM (VALUES
  ('a', 's1', CAST(NULL AS VARCHAR), 'svc', 'op', 1772359200000, 5.0, 200),
  ('a', 's2', 's1', 'svc2', 'op2', 1772359200001, 1.0, 503),
  ('b', 's3', NULL, 'svc', 'op', 1772359201000, 5.0, 0),
  ('b', 's4', 's3', 'svc2', 'op2', 1772359201001, 1.0, 302),
  ('c', 's5', NULL, 'svc', 'op', 1772359202000, 5.0, CAST(NULL AS INTEGER))
) v(traceID, spanID, parentSpanID, serviceName, operationName, startTime, duration_ms, statusCode)"""


async def test_numeric_status_codes_are_mapped(mcp, db_url, database):
    path = container_parquet(db_url, "a3_tt_status", STATUS_SQL)
    out = await call(mcp, "setup_trace_table", name="st", source=path)
    assert "spans: 5" in out, out
    rows = dict(database.read("SELECT span_id, status FROM extractor.tt_st", {}).rows)
    assert rows == {"s1": "ok", "s2": "error", "s3": "ok", "s4": "ok", "s5": None}


async def test_opentelemetry_numeric_status_codes_are_mapped(mcp, db_url, database):
    otel = STATUS_SQL.replace(", 200)", ", 1)").replace(", 503)", ", 2)").replace(", 302)", ", 0)")
    path = container_parquet(db_url, "a3_tt_otel", otel)
    out = await call(mcp, "setup_trace_table", name="ot", source=path)
    assert "read as OpenTelemetry's" in out, out
    rows = dict(database.read("SELECT span_id, status FROM extractor.tt_ot", {}).rows)
    assert rows == {"s1": "ok", "s2": "error", "s3": "ok", "s4": "ok", "s5": None}


def test_numeric_status_scheme():
    assert numeric_status_scheme({0.0, 1.0, 2.0}) == "otel"
    assert numeric_status_scheme({0.0}) == "http"  # all gRPC OK: either way ok
    assert numeric_status_scheme({0.0, 200.0, 503.0}) == "http"
    assert numeric_status_scheme(set()) == "http"


async def test_duration_unit_is_required_without_a_suffix(mcp, db_url):
    path = container_parquet(
        db_url, "a3_tt_nounit", "SELECT 't' AS trace_id, 's' AS span_id, 'a' AS service, 'o' AS operation, "
        "to_timestamp(1772359200) AS start, 5 AS duration"
    )
    out = await call(mcp, "setup_trace_table", name="nu", source=path)
    assert "duration_unit" in out and "spans:" not in out
    out = await call(mcp, "setup_trace_table", name="nu", source=path, roles={"duration_unit": "ms"})
    assert "spans: 1" in out and "duration_unit: ms  (given by you)" in out


async def test_names_are_one_namespace(mcp, cart_path):
    await call(mcp, "setup_trace_table", name="shop_traces", source=cart_path)
    out = await call(mcp, "setup_trace_table", name="shop_traces", source=cart_path)
    assert "already used" in out


# ------------------------------------------------------------------ trace_changes


async def test_cart_fault_ranks_cart_self_time_first(mcp, cart_path):
    await call(mcp, "setup_trace_table", name="shop_traces", source=cart_path)
    out = await call(mcp, "trace_changes", prefix="shop_", pivot=fx.PIVOT_ISO)
    assert out.startswith("How this was measured:")
    section = out.split("operations by self-time change")[1].split("\n\n")[0]
    ops = [ln.strip() for ln in section.splitlines()[1:] if ln.startswith("  ")]
    assert ops[0].startswith("cart /GetCart"), section
    first = ops[0]
    assert "self p50 10.0 -> 50.0 ms" in first and "z +400.0" in first
    home = next(o for o in ops if o.startswith("frontend /home"))
    assert ops.index(home) > 0 and "z +0.0" in home
    assert re.search(r"slowest after: t\d+", first)
    assert "errors 0.0% -> 0.0%" in first
    assert "coverage" in out and "cart: logs no, metrics no, traces yes" in out
    assert "rose from zero" in out  # the group is always named, even if empty


async def test_network_delay_shows_on_the_edge_not_on_payment(mcp, net_path):
    await call(mcp, "setup_trace_table", name="shop_traces", source=net_path)
    out = await call(mcp, "trace_changes", table="shop_traces", pivot=fx.PIVOT_ISO)
    edges = out.split("edges (caller -> callee")[1]
    edge = _line(edges, "checkout -> payment")
    net = re.search(r"network time p50 ([\d.]+) -> ([\d.]+) ms, z \+([\d.]+)", edge)
    assert net, edge
    assert (float(net.group(1)), float(net.group(2))) == (1.0, 101.0) and float(net.group(3)) > 100
    assert "call latency p50 6.0 -> 6.0 ms, z +0.0" in edge
    pay = _line(out.split("edges (caller")[0], "payment /Charge")
    assert "self p50 6.0 -> 6.0 ms" in pay and "z +0.0" in pay
    first_edge = [ln for ln in edges.splitlines()[1:] if ln.startswith("  ")][0]
    assert "checkout -> payment" in first_edge


async def test_null_status_is_unknown_not_zero(mcp, db_url):
    sql = fx.traces_sql("cart_fault").replace("'ok' AS status", "CAST(NULL AS VARCHAR) AS status")
    path = container_parquet(db_url, "a3_tt_nostatus", sql)
    await call(mcp, "setup_trace_table", name="ns_traces", source=path)
    out = await call(mcp, "trace_changes", table="ns_traces", pivot=fx.PIVOT_ISO)
    line = _line(out, "cart /GetCart")
    assert "errors unknown" in line and "0.0%" not in line


async def test_sort_and_filters(mcp, cart_path):
    await call(mcp, "setup_trace_table", name="shop_traces", source=cart_path)
    out = await call(mcp, "trace_changes", table="shop_traces", pivot=fx.PIVOT_ISO, services=["checkout"], sort="volume", top=1)
    section = out.split("operations by volume change")[1].split("\n\n")[0]
    ops = [ln for ln in section.splitlines() if ln.startswith("  ")]
    assert len(ops) == 1 and ops[0].strip().startswith("checkout ")
    assert "cart /GetCart" not in out
    bad = await call(mcp, "trace_changes", table="shop_traces", pivot=fx.PIVOT_ISO, sort="median")
    assert "sort" in bad and "self_time" in bad


async def test_prefix_and_table_handling(mcp, cart_path):
    await call(mcp, "setup_trace_table", name="shop_traces", source=cart_path)
    both = await call(mcp, "trace_changes", prefix="shop_", table="shop_traces", pivot=fx.PIVOT_ISO)
    assert "either" in both
    neither = await call(mcp, "trace_changes", pivot=fx.PIVOT_ISO)
    assert "prefix" in neither and "table" in neither
    other = await call(mcp, "trace_changes", prefix="zz_", pivot=fx.PIVOT_ISO)
    assert "zz_" in other and "operations by" not in other
    nope = await call(mcp, "trace_changes", table="nope", pivot=fx.PIVOT_ISO)
    assert "no trace table named 'nope'" in nope


# ------------------------------------------------------------------ get_trace


async def test_get_trace_prints_the_tree(mcp, cart_path):
    await call(mcp, "setup_trace_table", name="shop_traces", source=cart_path)
    out = await call(mcp, "get_trace", table="shop_traces", trace_id="t700")
    lines = [ln for ln in out.splitlines() if "ms" in ln and ("frontend" in ln or "cart" in ln or "checkout" in ln or "payment" in ln)]
    assert lines[0].startswith("frontend /home")
    assert "self 5.0 ms" in lines[0] and "start +0.0 ms" in lines[0]
    get_cart = _line(out, "cart /GetCart")
    assert get_cart.startswith("    cart /GetCart") and "duration 50.0 ms" in get_cart and "start +1.5 ms" in get_cart
    charge = _line(out, "payment /Charge")
    assert charge.startswith("        payment /Charge") and "status ok" in charge
    missing = await call(mcp, "get_trace", table="shop_traces", trace_id="nope")
    assert "no spans" in missing
