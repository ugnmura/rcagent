# Templating is two steps: SQL masking in SereneDB, then Drain in the MCP

Surveys mask obvious variable values (numbers, UUIDs, IPs, hex, quoted strings, …) with `regexp_replace` and group in SereneDB, then run Drain (drain3) inside the Python MCP over the already-grouped masked strings to merge word-level variation (e.g. `user alice` / `user bob`). Each resulting template is compiled to a regex that SereneDB runs for every investigation.

## Considered Options

- **SQL only** — keeps everything in SereneDB but cannot detect word-valued parameters, since a single row gives no signal that a plain word varies; positional-variety SQL is possible but awkward and loses Drain's heuristics.
- **Drain only on raw sampled rows** — better templates but ships the whole sample to the MCP and does work SQL can do cheaply.

## Consequences

Grouping first collapses a ~100k-entry sample to a few thousand distinct strings, so little data leaves SereneDB. The template → regex compilation is the contract between the two steps and must round-trip.
