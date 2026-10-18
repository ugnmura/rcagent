# Index timings on the base corpus: with and without a search index

On the base corpus, every text search and count without an index is an **exact scan that takes 0.05–0.37 s**.
Building the search index takes **3.0 s for BGL** (4,747,963 entries, 119.7 MB) and **0.3 s for OpenStack**
(207,636 entries, 12.3 MB). At this size an index doesn't pay off: the scans are already fast and exact, and
setup itself says "none needed — … small enough to search without an index". The billion-row case, where the
index matters, is in [HUGE_DATASETS.md](HUGE_DATASETS.md).

At `b51daa1` the searches below **did not use the index after it was built**. See
[What the second run shows](#what-the-second-run-shows).

## What ran

| | |
|---|---|
| Extractor | `main` at `b51daa1`, the server's own MCP tools over stdio |
| Data | the base corpus loaded with `scripts/load_base_corpus.py` (Parquet read in place) |
| SereneDB | 26.09.2 arm64 (`sha256:f9681a19f7f1…`), Docker on an Apple M1 (8 CPUs, 16 GB), 2026-10-18 |
| Calls | [`index-timings/calls.json`](index-timings/calls.json), run by [`index-timings/driver.py`](index-timings/driver.py); every call with its full result is in [`index-timings/calls.jsonl`](index-timings/calls.jsonl) |
| Order | every query 5 times without an index; then `create_index` (`dry_run` first) on both tables; the same queries 5 times again; then `drop_index` |

## Building the index

| Step | BGL | OpenStack |
|---|---|---|
| `create_index(kind="search", dry_run=true)`: trial build on a sample, estimate | 0.46 s: ≈103.4 MB, ~2 s (trial on 1,000,000 entries) | 0.38 s: ≈12.2 MB, under a second |
| `create_index(kind="search")`: build time over every entry | **2.96 s**, 119.7 MB | **0.30 s**, 12.3 MB |
| `drop_index` | 0.03 s | 0.02 s |

The dry-run estimates were close to the real builds: 14% under on size for BGL, and about a second under on time.

## Queries: medians of 5 runs

| Query | Matches | No index | After `create_index` |
|---|---|---|---|
| `search_logs` "parity error", BGL, all time | 121,357 | **0.22 s** | 0.26 s |
| `search_logs` "error", BGL, 11 June 2005 | 152,255 | **0.05 s** | 0.06 s |
| `count_logs` "error" by component, BGL, all time | — | **0.11 s** | 0.13 s |
| `search_logs` "error", OpenStack, all time | 8 | **0.07 s** | 0.08 s |
| `search_logs` "parity eror" with `fuzzy=true`, BGL | — | refused: "fuzzy search needs a search index" | refused: "Fuzzy search can't use the search index for this question" |

Every result in both columns starts "How this was measured: exact search: every entry in scope was checked …
no sampling; **no index used**". The matching counts are identical with and without the index.

## What the second run shows

- **The index wasn't used.** After `create_index`, `search_logs` still scanned with `ILIKE`, and fuzzy search
  was refused. The cause is in `_index_path` (`src/serenedb_extractor/tools/lookup.py`):
  - The index is used only when every role of the log table is a plain column in the index.
  - On tables the [team ownership](../README.md#team-ownership) rules cover (`bgl%`, `openstack%`,
    `textbench%`), the `team` role is derived: it is a `CASE` expression over the component, not a column.
  - So the index is never taken on those tables. The build result still says "search_logs uses it", which is
    wrong for them.
- **The TextBench run used the index.** It ran at `6cad141`, before teams existed, on a table named `tb` that no
  ownership rule covers. Its whole-file search reported "exact search through the search index".
- **The size of the cost:** on the base corpus none. The second column is the same scan, and 0.05–0.37 s is
  already well inside the time budget. On a covered billion-row table it would mean no fast whole-file
  search, and no fuzzy search.
