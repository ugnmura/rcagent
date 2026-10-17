"""TREND (#15): 28 days, 2026-03-01..03-28, in time order. Per day d, slot k is a 10-minute step:
  k < 10 (d < 14) or k < 20 (d >= 14)  queue overflow on shard <NUM>      T_RISE: doubles from 03-15
  k 20..24                            heartbeat ok from node <NUM>       T_DAILY: 5 every day
  k 30..32 on d = 19 (03-20)          certificate expired for gateway <NUM>  T_ONCE: 3 entries, one day
  k 40..69                            GET /health ok in <NUM>ms          noise
Every slot holds 20 entries one second apart (j), so the file spans ~14 row groups of 2,048.
Columns: ts, level, service, component, message. Counts: T_RISE 2,800 then 5,600; T_DAILY 100 a day;
T_ONCE 60. About 28,000 entries."""

T_RISE_TEXT = "queue overflow on shard <NUM>"
T_DAILY_TEXT = "heartbeat ok from node <NUM>"
T_ONCE_TEXT = "certificate expired for gateway <NUM>"

TREND = """
SELECT ts, level, service, component, message FROM (
  SELECT
    TIMESTAMPTZ '2026-03-01 00:00:00+00' + d * INTERVAL '1 day' + k * INTERVAL '10 minutes' + j * INTERVAL '1 second' AS ts,
    CASE WHEN k < 20 THEN 'ERROR' WHEN k < 30 THEN 'INFO' WHEN k < 40 THEN 'WARN' ELSE 'INFO' END AS level,
    CASE WHEN k < 20 THEN 'queue' WHEN k < 30 THEN 'ops' WHEN k < 40 THEN 'edge' ELSE 'web' END AS service,
    CASE WHEN k < 20 AND k % 2 = 0 THEN 'broker' WHEN k < 20 THEN 'scheduler' WHEN k < 30 THEN 'heartbeat'
         WHEN k < 40 THEN 'tls' ELSE 'http' END AS component,
    CASE WHEN k < 20 THEN 'queue overflow on shard ' || (k % 7)::VARCHAR
         WHEN k < 30 THEN 'heartbeat ok from node ' || (k % 3)::VARCHAR
         WHEN k < 40 THEN 'certificate expired for gateway ' || (k % 3)::VARCHAR
         ELSE 'GET /health ok in ' || (k % 20)::VARCHAR || 'ms' END AS message,
    CASE WHEN k < 10 THEN 1 WHEN k < 20 THEN CASE WHEN d >= 14 THEN 1 ELSE 0 END
         WHEN k BETWEEN 20 AND 24 THEN 1
         WHEN k BETWEEN 30 AND 32 THEN CASE WHEN d = 19 THEN 1 ELSE 0 END
         WHEN k >= 40 THEN 1 ELSE 0 END AS keep
  FROM range(28) a(d), range(70) b(k), range(20) c(j)
) WHERE keep = 1 ORDER BY ts
"""
