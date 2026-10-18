# Index timings on the base corpus: with and without a search index

On the base corpus, every text search and count without an index is an **exact scan that takes 0.05–0.85 s**,
with a median of at most 0.27 s per query. Building the search index takes **2.6 s for BGL** (4,747,963 entries,
120.0 MB) and **0.2 s for OpenStack** (207,636 entries, 12.3 MB). Once it exists:

- **Fuzzy search** works, and goes through the index: 0.17 s for a misspelled "parity eror", 121,358 matches.
- **Plain searches** still scan, on purpose. Their result says why: "The search index wasn't needed: a scan of
  this scope fits the cost budget, so the entries were searched directly (exact substring match)".

At this size the index buys fuzzy matching, not speed. Setup itself says "none needed — … small enough to search
without an index". The billion-row case, where the index is what makes a whole-file search fast, is in
[HUGE_DATASETS.md](HUGE_DATASETS.md).

## What ran

| | |
|---|---|
| Extractor | `main` at `cb4dfa2`, the server's own MCP tools over stdio |
| Data | the base corpus loaded with `scripts/load_base_corpus.py` (Parquet read in place) |
| SereneDB | 26.09.2 arm64 (`sha256:f9681a19f7f1…`), Docker on an Apple M1 (8 CPUs, 16 GB), 2026-10-18 |
| Calls | [`index-timings/calls.json`](index-timings/calls.json), run by [`index-timings/driver.py`](index-timings/driver.py); every call with its full result is in [`index-timings/calls.jsonl`](index-timings/calls.jsonl) |
| Order | every query 5 times without an index; then `create_index` (`dry_run` first) on both tables; the same queries 5 times again; then `drop_index` |

## Building the index

| Step | BGL | OpenStack |
|---|---|---|
| `create_index(kind="search", dry_run=true)`: trial build on a sample, estimate | 0.47 s: ≈103.4 MB, ~2 s (trial on 1,000,000 entries) | 0.33 s: ≈12.2 MB, under a second |
| `create_index(kind="search")`: build time over every entry | **2.64 s**, 120.0 MB | **0.20 s**, 12.3 MB |
| `drop_index` | 0.02 s | 0.03 s |

The dry-run estimates were close to the real builds: 14% under on size for BGL, and under a second off on time.

## Queries: medians of 5 runs

| Query | Matches | No index | After `create_index` | How the second column ran |
|---|---|---|---|---|
| `search_logs` "parity error", BGL, all time | 121,357 | **0.27 s** | 0.31 s | scan: "the search index wasn't needed" |
| `search_logs` "error", BGL, 2005-06-11 00:00–24:00 UTC | 31 | **0.06 s** | 0.06 s | scan: "the search index wasn't needed" |
| `count_logs` "error" by component, BGL, all time | — | **0.12 s** | 0.13 s | scan (`count_logs` doesn't use the search index) |
| `search_logs` "error", OpenStack, all time | 8 | **0.10 s** | 0.11 s | scan: "the search index wasn't needed" |
| `search_logs` "parity eror" with `fuzzy=true`, BGL | 121,358 | refused: "fuzzy search needs a search index" | **0.17 s** (1 run) | "exact search through the search index extractor."bgl_search_idx"" |

The plain searches give identical counts with and without the index. The first no-index run of "parity error" was
the cold start (0.85 s); the other four were 0.22–0.28 s. The 11 June window is given in UTC. The BGL log's own
time zone is America/Los_Angeles, so this window misses most of the 11 June storm, which falls on 12 June in UTC.

## When the index is used

- **Fuzzy search:** always through the index; there is no other way to run it.
- **Plain search:** through the index when a scan of the scope would not fit the time budget. On the base corpus
  that never happens. On the billion-row TextBench file it does: a whole-file search goes through the index and is
  exact, while without the index the tool answers from a stated block sample
  (see [HUGE_DATASETS.md](HUGE_DATASETS.md)).
- **Ownership-covered tables (`bgl`, `openstack`):** since `a0cc99e`, only the fields a search actually uses need to
  be in the index. At `b51daa1` the derived `team` role kept these two tables off the index entirely, and fuzzy
  search was refused.
