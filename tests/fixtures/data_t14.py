"""Fixture CTX for get_context (#14).

Trace t-1: a WARN `pool exhausted` (payments) 2 s before `connection refused` (checkout, ERROR);
`other-service` INFO lines (trace t-2) between and around them; one ERROR whose message is a
10,000+ character stack trace (trace t-3, 30 minutes later).
"""

CTX = """
SELECT ts::TIMESTAMPTZ AS ts, level, service, host, trace_id, message FROM (VALUES
  ('2026-03-01 10:00:00+00', 'WARN',  'payments',      'h1', 't-1', 'pool exhausted, 0/50 connections available'),
  ('2026-03-01 10:00:01+00', 'INFO',  'other-service', 'h2', 't-2', 'heartbeat ok from other-service'),
  ('2026-03-01 10:00:02+00', 'ERROR', 'checkout',      'h1', 't-1', 'connection refused to 10.0.7.21:5432'),
  ('2026-03-01 10:00:03+00', 'INFO',  'other-service', 'h2', 't-2', 'heartbeat ok from other-service'),
  ('2026-03-01 10:00:04+00', 'ERROR', 'checkout',      'h1', 't-4', 'connection refused to 10.0.7.22:5432'),
  ('2026-03-01 10:30:00+00', 'ERROR', 'payments',      'h1', 't-3',
     'java.lang.IllegalStateException: boom' || repeat(' at com.example.Foo.bar(Foo.java:42)', 300))
) AS v(ts, level, service, host, trace_id, message)
ORDER BY ts
"""
