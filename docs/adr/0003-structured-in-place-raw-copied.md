# Structured log sources are read in place; raw text logs are copied once

Structured sources (Parquet, JSON) — including remote ones on HTTP/S3 at tens of billions of rows — are exposed through a view over SereneDB's file readers and never downloaded or copied. Raw text logs are parsed once into a real table: timestamp, level and component pulled out, multi-line entries (stack traces) joined, source file and line kept.

## Considered Options

- **Copy everything** — fast queries and full index support, but copying a 50B-row lake before asking a single question is unacceptable in time and storage.
- **Read raw text in place too** — one row per physical line splits stack traces from their errors, and parsing in the view makes it a generic view that SereneDB cannot fully index.

## Consequences

Local files reach the Dockerised SereneDB through a mounted folder; files outside it are streamed in by the MCP, which forces a copy even for structured sources (setup says so). Indexes, when built, are over the view for in-place sources and over the table for copied ones. Remote raw text is out of scope for the prototype, since copying it would mean downloading it or moving the parser into SQL.
