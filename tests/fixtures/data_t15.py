"""TREND (#15): 2026-03-01..03-28 in time order, plus a few noise entries just after midnight on 03-29
(so the data provably continues past 03-28). Per day d, slot k is a 10-minute step:
  k < 10 (d < 14) or k < 20 (d >= 14)  queue overflow on shard <NUM>      T_RISE: doubles from 03-15
  k 20..24                            heartbeat ok from node <NUM>       T_DAILY: 5 slots every day
  k 30..32 on d = 19 (03-20)          certificate expired for gateway <NUM>  T_ONCE: 3 slots, one day
  k 40..143                           GET /health ok in <NUM>ms          noise, one entry per slot
Each template slot holds 200 entries one second apart (j), so the file is ~115,000 entries (~57 row
groups of 2,048): more than the default sample size, so estimating is natural.
Columns: ts, level, service, component, message.
Counts: T_RISE 28,000 then 56,000; T_DAILY 1,000 a day; T_ONCE 600."""

T_RISE_TEXT = "queue overflow on shard <NUM>"
T_DAILY_TEXT = "heartbeat ok from node <NUM>"
T_ONCE_TEXT = "certificate expired for gateway <NUM>"
T_TICK_TEXT = "tick from node <NUM>"

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
    CASE WHEN d = 28 THEN CASE WHEN k BETWEEN 40 AND 49 AND j = 0 THEN 1 ELSE 0 END
         WHEN k < 10 THEN 1 WHEN k < 20 THEN CASE WHEN d >= 14 THEN 1 ELSE 0 END
         WHEN k BETWEEN 20 AND 24 THEN 1
         WHEN k BETWEEN 30 AND 32 THEN CASE WHEN d = 19 THEN 1 ELSE 0 END
         WHEN k >= 40 THEN CASE WHEN j = 0 THEN 1 ELSE 0 END
         ELSE 0 END AS keep
  FROM range(29) a(d), range(144) b(k), range(200) c(j)
) WHERE keep = 1 ORDER BY ts
"""

# TICKS (#15, clock changes): one entry every 30 minutes, UTC, around the 2026 Europe/Paris clock changes
# (spring forward 03-29 02:00 -> 03:00; fall back 10-25 03:00 -> 02:00).
TICKS = """
SELECT ts, 'tick from node ' || (i % 3)::VARCHAR AS message FROM (
  SELECT TIMESTAMPTZ '2026-03-26 00:00:00+00' + i * INTERVAL '30 minutes' AS ts, i FROM range(240) t(i)
  UNION ALL
  SELECT TIMESTAMPTZ '2026-10-23 00:00:00+00' + i * INTERVAL '30 minutes' AS ts, i FROM range(240) t(i)
) ORDER BY ts
"""
