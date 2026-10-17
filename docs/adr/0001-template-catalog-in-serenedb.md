# Template catalog lives in SereneDB, holds facts only, with stable IDs

Templates discovered by surveys are persisted per log table in the MCP's own `extractor` schema in SereneDB, so the catalog builds up across sessions instead of being rediscovered each time. It holds only what surveys observed (template, regex, example, first/last seen, last estimate) plus parameter names — never judgments such as "noise", because whether a template matters depends on the question being asked. Template IDs are assigned (`T1`, `T2`, …), not derived from the template text, so that when a later survey generalizes a template it is updated in place and keeps its ID; only when two templates merge does the absorbed ID get a single-hop redirect.

## Considered Options

- **In-memory per session** — simplest, but nothing accumulates and every session starts cold.
- **Stateless, ID = hash of template text** — no storage, but every generalization changes the ID and breaks references.
- **Per application, shared across log tables** — rejected for now; catalogs are not merged across log tables.

## Consequences

The MCP needs a writer role limited to the `extractor` schema, separate from the reader role used for queries. Catalog writes after a survey happen without approval.
