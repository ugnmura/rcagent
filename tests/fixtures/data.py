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

# USERS: three phase files (written as users_a/b/c.parquet, read through one glob). Columns: ts, level, service, message.
#   A (03-01): one login-failure line each for three people, seen by separate narrow surveys
#              (service web / api / cli): alice WARN, bob ERROR, carol ERROR.
#   B (03-02): many users (WARN, web) and many admins (ERROR, api): the broader views that generalize A.
#   C (03-03): only `disk full on /dev/sda1` (ERROR, storage).
# Note: Drain would merge the three A lines into one template when surveyed together, so tests narrow by service.
USERS_A = """
SELECT TIMESTAMPTZ '2026-03-01 08:00:00+00' + i * INTERVAL '1 minute' AS ts,
  CASE WHEN i < 4 THEN 'WARN' ELSE 'ERROR' END AS level,
  CASE WHEN i < 4 THEN 'web' WHEN i < 7 THEN 'api' ELSE 'cli' END AS service,
  CASE WHEN i < 4 THEN 'login failed for user alice'
       WHEN i < 7 THEN 'login failed for admin bob'
       ELSE 'login failed for admin carol' END AS message
FROM range(10) t(i)
"""
USERS_B = """
SELECT TIMESTAMPTZ '2026-03-02 08:00:00+00' + i * INTERVAL '1 minute' AS ts,
  CASE WHEN i < 40 THEN 'WARN' ELSE 'ERROR' END AS level,
  CASE WHEN i < 40 THEN 'web' ELSE 'api' END AS service,
  CASE WHEN i < 40 THEN 'login failed for user user' || (i % 20)::VARCHAR
       ELSE 'login failed for admin adm' || (i % 10)::VARCHAR END AS message
FROM range(60) t(i)
"""
USERS_C = """
SELECT TIMESTAMPTZ '2026-03-03 08:00:00+00' + i * INTERVAL '1 minute' AS ts,
  'ERROR' AS level, 'storage' AS service, 'disk full on /dev/sda1' AS message
FROM range(5) t(i)
"""
USERS = {"a": USERS_A, "b": USERS_B, "c": USERS_C}
