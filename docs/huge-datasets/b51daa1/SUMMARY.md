# HPC devel run: extractor b51daa1 on TextBench

Every number below is as measured; `seconds` is the wall time of one MCP `tools/call`, measured by `scripts/drive.py`.

## A. One file (part_000, 1,000,000,000 entries, 41.0 GB), job 5120494, node r23m0124

| step | median s | runs | ok | notes |
|---|---|---|---|---|
| A1 setup_log_table | 1.375 | 1 | 1/1 | view over S3 in place; 1,000,000,000 entries, 41.0 GB; message=Body, service=ServiceName |
| A2 survey | 1.725 | 1 | 1/1 | block sample: 5 row groups, 99,096 entries looked at; 235 templates |
| A3 search 60 s window, no index | 1.708 | 3 | 3/3 | runs 2.008 / 1.687 / 1.708; exact, 2,936,098 matches |
| A4 whole file, no index | 1.012 | 3 | 3/3 | runs 1.027 / 1.006 / 1.012; **not exact**: the tool chose a block sample (1 row group, 614,400 entries) → "≈100,000,000 (rough estimate … margin not estimable from 1 block)"; it said "An exact count would read ~26.1 GB (~4 min)". No TOO EXPENSIVE, so no confirmed_cost to follow; no timeout, so no psql fallback was run |
| A5 count_logs by service, no index | 0.647 | 1 | 1/1 | block-sample estimate, same 1 row group: ≈100,000,000; frontend 91.2 %, payment 7.3 %, email 1.1 % |
| A6 create_index dry_run | 0.466 | 1 | 1/1 | trial on 1,000,000 entries: estimated ≈38.3 GB, ~6 min |
| A6 create_index (search) | 70.709 | 1 | 1/1 | built: 37.5 GB on disk, ~71 s |
| A7 whole file, with index | 2.320 | 3 | 3/3 | runs 2.363 / 2.320 / 2.295; exact through the index: 93,638,388 matches (whole words) |
| A8 count_logs by service, with index | 0.670 | 1 | 1/1 | **index not used** ("no index used"): same block-sample estimate as A5 |
| A9 search 60 s window, with index | 1.730 | 3 | 3/3 | runs 1.705 / 1.746 / 1.730; index not used ("a scan of this scope fits the cost budget"); exact, 2,936,098 matches |
| A10 drop_index | 0.101 | 1 | 1/1 | |

Job: 2 min elapsed, MaxRSS 98,465,328 KB (batch step, includes SereneDB during the index build), TotalCPU 20:45.

Break-even as measured: whole-file "error" without an index answers in ~1.0 s but only as a 1-row-group estimate (≈100M);
with the index it is exact (93,638,388) in ~2.3 s after a 71 s, 37.5 GB build. An exact no-index whole-file number was not
produced by the tool (no guard prompt, no timeout); the tool's own prediction for it is ~26.1 GB read, ~4 min.

### A7-A9 first lines (request of 2026-10-18T15:32Z)

- A7: `How this was measured: exact search through the search index extractor."tb_search_idx": every entry whose message has the words was found; period: all time; filters: message has the words 'error' (any case); no sampling; index used: extractor."tb_search_idx"; times in UTC.`
- A8: `How this was measured: count per log table: exact where marked exact, else estimated from a block sample (said per table); period: all time; filters: message contains 'error' (any case); block sample where marked; no index used; times in UTC.` (**index not used**)
- A9: `How this was measured: exact search: every entry in scope was checked; period: 2025-09-23 00:10:00 to 2025-09-23 00:11:00 UTC; filters: message contains 'error' (any case); no sampling; no index used; times in UTC.` (**index not used**)

A7's search SQL (from its evidence, Q12.6): `SELECT count(*) FROM extractor."tb_search_idx" WHERE TRUE AND TRUE AND "Body" @@ ts_phrase('error')`

### A, exact no-index whole-file numbers (follow-up of 2026-10-18T16:18Z)

Fresh `setup_log_table` as `tb`, no index, one run each.

| step | s | runs | ok | notes |
|---|---|---|---|---|
| Ax1 plain SQL, no extractor (psql): `SELECT count(*) FROM extractor.lt_tb WHERE "Body" ILIKE '%error%';` | 11.522 | 1 | 1/1 | **94,902,425** (substring); psql `\timing` 11,522.190 ms, wall 11.756 s; job 5121278 |
| Ax2 plain SQL, no extractor (psql): `... WHERE "Body" ~* '\merror\M';` | 0.056 | 1 | 0/1 | **error from SereneDB**: `invalid escape sequence: \m`; no count. Also: `statement_timeout` "is accepted for compatibility but is not enforced by serened"; job 5121278 |
| Ax3 extractor run_sql (query of Ax1, `timeout_s` 600) | 0.553 | 1 | 1/1 | guard: TOO EXPENSIVE, "reads up to ~37.7 GB, ~6 min"; offered confirmed_cost=37.7GB; job 5120974 |
| Ax3 extractor run_sql, confirmed | 15.380 | 1 | 1/1 | **94,902,425**; inner query Q3.4 took 14.96 s; job 5120974 |

Order and a script fault, as they happened: in job 5120974 the order was 1, 2, 3, but my script ran psql as `psql -f <path>`, a path the
container cannot see. psql exited before any query ("No such file or directory", 0.28 s). That run is kept in `raw/5120974/`.
Only Ax1 and Ax2 were rerun, feeding the SQL on stdin, in job 5121278. Ax3 was not repeated. So Ax3 ran before Ax1/Ax2, in a different job on the same node (r23m0124).

Break-even with these numbers (part_000, "error", no fuzzy):
- no index, exact substring: 11.5 s in plain SQL, 15.4 s through the extractor (after confirming 37.7 GB); 94,902,425 matches;
- with index: 2.3 s, exact whole-word 93,638,388 matches, after a 71 s build of 37.5 GB;
- index break-even ≈ 71 / (15.4 - 2.3) ≈ 5.4 whole-file searches through the extractor (≈ 7.7 against plain SQL's 11.5 s). This counts the build only, and the two match different things (substring vs whole word). A whole-word scan has no number because Ax2 failed.
- without the index, the extractor by default answers a whole-file search from a 1-row-group sample (A4, ~1.0 s, ≈100,000,000) and never offers to run it exactly.


## B. Ten files (part_{000..009}, 10,000,000,000 entries, 410.2 GB), table `textbench10`, job 5120975, node r23m0124

No index: one file's search index is 37.5 GB on disk and the build needed >64 GB RAM (A: MaxRSS 98 GB); ten files would not fit in 128 GB. Not tried.

| step | median s | runs | ok | notes |
|---|---|---|---|---|
| B1 | 2.400 | 1 | 1/1 | 10,000,000,000 entries, 10 files, 410.2 GB, 16,246 row groups |
| B2 | 0.567 | 1 | 1/1 | view over S3 in place; message=Body, service=ServiceName |
| B3 | 0.568 | 1 | 1/1 | **refused**: TOO EXPENSIVE, ~113.3 GB, ~19 min, more than the 600 s maximum, so no confirmed_cost was offered; nothing run |
| B4@00:10 | 2.872 | 3 | 3/3 | runs 3.115 / 2.872 / 2.831; exact, 2,936,098 matches |
| B4@02:30 | 3.047 | 3 | 3/3 | runs 4.094 / 3.047 / 2.949; exact, 2,960,892 matches |
| B4@04:50 | 3.485 | 3 | 3/3 | runs 3.857 / 3.386 / 3.485; exact, 2,795,044 matches |
| B5 | 4.389 | 3 | 3/3 | runs 4.601 / 4.389 / 4.165; exact, 15,211,837; frontend 13,785,160 (90.6 %), payment 1,206,121, email 189,420 |
| B6 | 0.589 | 1 | 1/1 | guard: TOO EXPENSIVE, ~5.3 GB, ~53 s; offered confirmed_cost=5.3GB |
| B6:confirmed | 31.761 | 1 | 1/1 | exact over all 10,000,000,000 entries, 62 (service, level) groups; frontend·error 1,063,483,297, payment·error 142,921,020, email·error 24,613,176 |

Job 5120975: 1 min 32 s elapsed, MaxRSS 13,858,536 KB, TotalCPU 10:09.

Superseded run: job 5120519 ran the same B steps with the table named `tb10`, before I had read the request to call it `textbench10`. It is
kept in `raw/5120519/`. Also, my driver at the time did not follow the guard there: B6 offered `confirmed_cost=5.3GB` and was not
confirmed, because the driver only looked for `TOO EXPENSIVE` at the start of the answer. That is fixed in `scripts/drive.py`, and 5120975 used the fix.
Its numbers matched 5120975 where both ran (B4 counts identical; B5 15,211,837 in both).
