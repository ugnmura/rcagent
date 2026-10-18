"""Synthetic telemetry with a known answer, in the shape of docs/contracts/telemetry-case-v1.md.

One system, 20 minutes at 1 s, pivot at minute 10, five services:
frontend -> cart, frontend -> checkout -> payment, plus email (no traces).

Scenario `cart_fault` (default): cart's cpu steps up at the pivot and its server spans slow down
(10 ms -> 50 ms self time); frontend's total latency rises with it but frontend's self time does not;
cart logs a new OutOfMemoryError template; email's `error` metric rises from zero (a distractor that
must not be ranked by z).

Scenario `network_delay`: no cart fault; the network between checkout and payment adds 100 ms after the
pivot. payment's own spans do not change; checkout's client span to payment grows by 100 ms, which only
the edge's network time (client span minus server span) attributes correctly.

Each function returns a SELECT for tests.conftest.container_parquet.
"""

BASE_EPOCH = 1772359200  # 2026-03-01 10:00:00 UTC
SECONDS = 1200
PIVOT_S = 600
PIVOT_ISO = "2026-03-01T10:10:00Z"
START_ISO = "2026-03-01T10:00:00Z"
SERVICES = ("frontend", "cart", "checkout", "payment", "email")
TRACED = ("frontend", "cart", "checkout", "payment")

_T = f"(SELECT range AS i FROM range({SECONDS}))"


def metrics_sql(scenario: str = "cart_fault", epoch_unit: str | None = None) -> str:
    """Long-format metrics. epoch_unit None gives a TIMESTAMPTZ `ts`; 's'/'ms'/'us'/'ns' an integer epoch."""
    cart = scenario == "cart_fault"
    ts = {
        None: f"to_timestamp({BASE_EPOCH} + i)",
        "s": f"CAST({BASE_EPOCH} + i AS BIGINT)",
        "ms": f"CAST(({BASE_EPOCH} + i) * 1000 AS BIGINT)",
        "us": f"CAST(({BASE_EPOCH} + i) * 1000000 AS BIGINT)",
        "ns": f"CAST(({BASE_EPOCH} + i) * 1000000000 AS BIGINT)",
    }[epoch_unit]
    services = ", ".join(f"({k}, '{s}')" for k, s in enumerate(SERVICES))
    return f"""
SELECT {ts} AS ts, service, metric,
  CAST(CASE metric
    WHEN 'cpu' THEN 0.2 + 0.01 * ((i * 7 + k * 3) % 5)
                    + CASE WHEN {str(cart).upper()} AND service = 'cart' AND i >= {PIVOT_S} THEN 0.6 ELSE 0 END
    WHEN 'mem' THEN 100.0 + ((i * 3 + k) % 7)
    WHEN 'error' THEN CASE WHEN service = 'email' AND i >= {PIVOT_S} THEN 2.0 ELSE 0.0 END
    ELSE 10.0 + (i % 4) + CASE WHEN {str(cart).upper()} AND service = 'frontend' AND i >= {PIVOT_S} THEN 5 ELSE 0 END
  END AS DOUBLE) AS value
FROM {_T} t,
  (SELECT * FROM (VALUES {services}) v(k, service)) s,
  (SELECT * FROM (VALUES ('cpu'), ('mem'), ('error'), ('latency')) v(metric)) m
ORDER BY ts, service, metric"""


def wide_metrics_sql() -> str:
    """The same cpu values in wide form (one column per series): setup must refuse it with a hint."""
    cols = ", ".join(f"0.2 + 0.01 * ((i * 7 + {k} * 3) % 5) AS {s}_cpu" for k, s in enumerate(SERVICES))
    return f"SELECT to_timestamp({BASE_EPOCH} + i) AS time, {cols} FROM {_T} t"


def traces_sql(scenario: str = "cart_fault") -> str:
    """One trace per second, seven spans: a frontend /home server span; frontend client spans to cart and
    checkout with their server spans; checkout's client span to payment and payment's server span.
    Durations in microseconds; client span = callee server span + network time."""
    cart = str(scenario == "cart_fault").upper()
    net = str(scenario == "network_delay").upper()
    return f"""
WITH d AS (
  SELECT i,
    CASE WHEN {cart} AND i >= {PIVOT_S} THEN 50000 ELSE 10000 END AS cart_us,
    CASE WHEN {net} AND i >= {PIVOT_S} THEN 101000 ELSE 1000 END AS net_cp_us,
    6000 AS pay_us
  FROM {_T} t
), d2 AS (
  SELECT *, pay_us + net_cp_us AS pay_client_us, cart_us + 1000 AS cart_client_us FROM d
), d3 AS (
  SELECT *, 8000 + pay_client_us AS chk_us FROM d2
), d4 AS (
  SELECT *, chk_us + 1000 AS chk_client_us FROM d3
), d5 AS (
  SELECT *, 5000 + cart_client_us + chk_client_us AS home_us, 2000 + cart_client_us AS chk_client_start FROM d4
), spans AS (
  SELECT i, 'a' AS k, NULL AS parent, 'frontend' AS service, '/home' AS operation, 0 AS off_us, home_us AS dur FROM d5
  UNION ALL SELECT i, 'b', 'a', 'frontend', 'cart.GetCart', 1000, cart_client_us FROM d5
  UNION ALL SELECT i, 'c', 'b', 'cart', '/GetCart', 1500, cart_us FROM d5
  UNION ALL SELECT i, 'd', 'a', 'frontend', 'checkout.PlaceOrder', chk_client_start, chk_client_us FROM d5
  UNION ALL SELECT i, 'e', 'd', 'checkout', '/PlaceOrder', chk_client_start + 500, chk_us FROM d5
  UNION ALL SELECT i, 'f', 'e', 'checkout', 'payment.Charge', chk_client_start + 1500, pay_client_us FROM d5
  UNION ALL SELECT i, 'g', 'f', 'payment', '/Charge', chk_client_start + 2000, pay_us FROM d5
)
SELECT 't' || i AS trace_id, 's' || i || k AS span_id,
  CASE WHEN parent IS NULL THEN NULL ELSE 's' || i || parent END AS parent_span_id,
  service, operation,
  to_timestamp({BASE_EPOCH} + i + off_us / 1000000.0) AS start,
  CAST(dur AS BIGINT) AS duration_us,
  'ok' AS status
FROM spans ORDER BY start"""


def logs_sql(scenario: str = "cart_fault") -> str:
    cart = str(scenario == "cart_fault").upper()
    return f"""
SELECT to_timestamp({BASE_EPOCH} + i) AS ts, service, level, message FROM (
  SELECT i, 'frontend' AS service, 'INFO' AS level, 'GET /home 200 in ' || (10 + i % 7) || ' ms' AS message FROM {_T} t
  UNION ALL SELECT i, 'cart', 'INFO', 'Processing GetCart request id=' || i FROM {_T} t
  UNION ALL SELECT i, 'cart', 'ERROR', 'java.lang.OutOfMemoryError: Java heap space id=' || i
    FROM {_T} t WHERE {cart} AND i >= {PIVOT_S} AND i % 5 = 0
  UNION ALL SELECT i, 'checkout', 'INFO', 'PlaceOrder ok order=' || i FROM {_T} t
) x ORDER BY ts"""
