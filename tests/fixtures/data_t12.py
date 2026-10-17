"""Test data for the cost-aware survey (#12)."""

# FX_BIG: 30,720 entries (15 row groups of 2,048 when written with ROW_GROUP_SIZE 2048), in time
# order, groups interleaved like FX. p = (i * 7) % 30720 is a bijection, so group sizes are exact:
#   p < 18432          timeout after <NUM>ms calling payments  (payments, ERROR)  18,432
#   18432 <= p < 27648 login failed for user <*>               (auth, WARN)        9,216
#   27648 <= p < 27840 disk full on <PATH>                     (checkout, ERROR)     192
#   otherwise          INFO noise                              (web)
FX_BIG_ROWS = 30_720
FX_BIG = """
SELECT
  TIMESTAMPTZ '2026-03-01 00:00:00+00' + i * INTERVAL '5 seconds' AS ts,
  CASE WHEN p < 18432 THEN 'ERROR' WHEN p < 27648 THEN 'WARN' WHEN p < 27840 THEN 'ERROR' ELSE 'INFO' END AS level,
  CASE WHEN p < 18432 THEN 'payments' WHEN p < 27648 THEN 'auth' WHEN p < 27840 THEN 'checkout' ELSE 'web' END AS service,
  CASE WHEN p < 18432 THEN 'gateway' WHEN p < 27648 THEN 'login' WHEN p < 27840 THEN 'storage' ELSE 'http' END AS component,
  CASE WHEN p < 18432 THEN 'timeout after ' || (100 + p % 900)::VARCHAR || 'ms calling payments'
       WHEN p < 27648 THEN 'login failed for user user' || (p % 50)::VARCHAR
       WHEN p < 27840 THEN 'disk full on /dev/sd' || chr(97 + (p % 4)::INTEGER)
       ELSE 'GET /health ok in ' || (p % 20)::VARCHAR || 'ms' END AS message
FROM (SELECT i, (i * 7) % 30720 AS p FROM range(30720) t(i))
ORDER BY ts
"""
