"""BIG: 40,000 entries in 20 row groups of 2,000 (written with ROW_GROUP_SIZE 2000) so block sampling applies.
Every 4th entry (10,000 in all) is `timeout after <NUM>ms calling payments`, the rest `GET /health ok in <n>ms`."""

BIG = """
SELECT TIMESTAMPTZ '2026-03-01 00:00:00+00' + i * INTERVAL '3 seconds' AS ts,
  CASE WHEN i % 4 = 0 THEN 'ERROR' ELSE 'INFO' END AS level,
  CASE WHEN i % 4 = 0 THEN 'payments' ELSE 'web' END AS service,
  CASE WHEN i % 4 = 0 THEN 'timeout after ' || (100 + i % 900)::VARCHAR || 'ms calling payments'
       ELSE 'GET /health ok in ' || (i % 20)::VARCHAR || 'ms' END AS message
FROM range(40000) t(i)
ORDER BY ts
"""
