# HPC devel run: Part A again at extractor main 7fc3e37 

Same steps as job 5120494 (`hpc/2026-10-18-b51daa1/`), extractor at `7fc3e372cd9e485a1f72e74e04b01502f8e17c84` (contains `a0cc99e`), unchanged.
Job 5121922 on r23m0124 (devel), SereneDB 26.10.1, part_000 (1,000,000,000 entries, 41.0 GB). `A.jsonl` is table `tb`; `T.jsonl` is
table `textbench` (covered by the ownership rules), with `setup_log_table` and then the same A_index steps. Seconds are the wall time of one MCP `tools/call`.

## Table `tb`

| step | median s | runs | ok | notes |
|---|---|---|---|---|
| A1 setup_log_table | 1.896 | 1 | 1/1 | |
| A2 survey | 5.609 | 1 | 1/1 | block-sample survey |
| A3 search 60 s window, no index | 1.064 | 3 | 3/3 | runs 1.515 / 1.062 / 1.064; exact, 2,936,098 |
| A4 whole file, no index | 0.923 | 3 | 3/3 | runs 0.923 / 0.896 / 0.938; still a block-sample estimate ("An exact count would read ~26.1 GB (~4 min), so this is estimated from a sample"); no guard prompt |
| A5 count_logs by service, no index | 0.544 | 1 | 1/1 | block-sample estimate |
| A6 create_index dry_run | 0.460 | 1 | 1/1 | estimated ≈38.3 GB, ~6 min |
| A6 create_index (search) | 70.060 | 1 | 1/1 | built 37.5 GB, ~70 s |
| A7 whole file, with index | 3.044 | 3 | 3/3 | runs 3.553 / 3.044 / 2.568; exact through the index, 93,638,388 |
| A8 count_logs by service, with index | 0.957 | 1 | 1/1 | **index not used** (block-sample estimate) |
| A9 search 60 s window, with index | 1.768 | 3 | 3/3 | runs 2.326 / 1.743 / 1.768; **index not used**; exact, 2,936,098 |
| A10 drop_index | 0.007 | 1 | 1/1 | |

## Table `textbench` (ownership-covered), A_index steps

| step | median s | runs | ok | notes |
|---|---|---|---|---|
| T:setup setup_log_table | 0.809 | 1 | 1/1 | |
| T:A6 create_index dry_run | 0.503 | 1 | 1/1 | estimated ≈38.3 GB, ~7 min |
| T:A6 create_index (search) | 69.750 | 1 | 1/1 | built 37.5 GB, ~70 s |
| T:A7 whole file, with index | 1.917 | 3 | 3/3 | runs 2.427 / 1.731 / 1.917; **exact through the search index**, 93,638,388 |
| T:A8 count_logs by service, with index | 0.677 | 1 | 1/1 | **index not used** (block-sample estimate) |
| T:A9 search 60 s window, with index | 1.360 | 3 | 3/3 | runs 1.335 / 1.360 / 1.496; **index not used**; exact, 2,936,098 |
| T:A10 drop_index | 0.088 | 1 | 1/1 | |

Job: 3 min 34 s elapsed, MaxRSS 96,848,684 KB (batch step, includes SereneDB during two index builds), TotalCPU 45:14.

### First lines, A7-A9

- A7 (`tb`): `How this was measured: exact search through the search index extractor."tb_search_idx": every entry whose message has the words 'error' was found; period: all time; filters: message has the words 'error' (any case); no sampling; index used: extractor."tb_search_idx"; times in UTC.`
- A8 (`tb`): `How this was measured: count per log table: exact where marked exact, else estimated from a block sample (said per table); period: all time; filters: message contains 'error' (any case); block sample where marked; no index used; times in UTC.`
- A9 (`tb`): `How this was measured: exact search: every entry in scope was checked; period: 2025-09-23 00:10:00 to 2025-09-23 00:11:00 UTC; filters: message contains 'error' (any case); no sampling; no index used; times in UTC.`
- T:A7 (`textbench`): `How this was measured: exact search through the search index extractor."textbench_search_idx": every entry whose message has the words 'error' was found; period: all time; filters: message has the words 'error' (any case); no sampling; index used: extractor."textbench_search_idx"; times in UTC.`
- T:A8 (`textbench`): same as A8 (`no index used`).
- T:A9 (`textbench`): same as A9 (`no index used`).
