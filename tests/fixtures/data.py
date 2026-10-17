"""Deterministic SELECT generators for test log data (written to Parquet inside SereneDB)."""

# FX: 5,000 entries over 2026-03-01..02, in time order, with the groups interleaved.
# Row position p = (i * 7) % 5000 is a bijection, so group sizes are exact:
#   p < 3000          timeout after <NUM>ms calling payments  (payments, ERROR)
#   3000 <= p < 4500  login failed for user <*>               (auth, WARN, 50 users)
#   4500 <= p < 4530  disk full on <PATH>                     (checkout, ERROR)
#   otherwise         INFO noise                              (web)
FX = """
SELECT
  TIMESTAMPTZ '2026-03-01 00:00:00+00' + i * INTERVAL '34 seconds' AS ts,
  CASE WHEN p < 3000 THEN 'ERROR' WHEN p < 4500 THEN 'WARN' WHEN p < 4530 THEN 'ERROR' ELSE 'INFO' END AS level,
  CASE WHEN p < 3000 THEN 'payments' WHEN p < 4500 THEN 'auth' WHEN p < 4530 THEN 'checkout' ELSE 'web' END AS service,
  CASE WHEN p < 3000 THEN 'gateway' WHEN p < 4500 THEN 'login' WHEN p < 4530 THEN 'storage' ELSE 'http' END AS component,
  't-' || (i % 100)::VARCHAR AS trace_id,
  CASE WHEN p < 3000 THEN 'timeout after ' || (100 + p % 900)::VARCHAR || 'ms calling payments'
       WHEN p < 4500 THEN 'login failed for user user' || (p % 50)::VARCHAR
       WHEN p < 4530 THEN 'disk full on /dev/sd' || chr(97 + (p % 4)::INTEGER)
       ELSE 'GET /health ok in ' || (p % 20)::VARCHAR || 'ms' END AS message
FROM (SELECT i, (i * 7) % 5000 AS p FROM range(5000) t(i))
ORDER BY ts
"""
