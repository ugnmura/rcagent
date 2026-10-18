"""The `extractor` schema (spec section 5). Bootstrapping is idempotent."""

from rcagent.catalog.models import ROLE_FIELDS
from rcagent.db import Database
from rcagent.evidence import EVIDENCE_DDL
from rcagent.ownership import CHANGES_DDL, OWNERSHIP_DDL, seed, upgrade

_ROLE_COLUMNS = ",\n        ".join(
    f"role_{f} VARCHAR NOT NULL" if f == "message" else f"role_{f} VARCHAR" for f in ROLE_FIELDS
)

LOG_TABLES_DDL = f"""CREATE TABLE IF NOT EXISTS extractor.log_tables (
        name               VARCHAR PRIMARY KEY,
        source             VARCHAR NOT NULL,
        source_format      VARCHAR NOT NULL,
        mode               VARCHAR NOT NULL,
        relation           VARCHAR NOT NULL,
        {_ROLE_COLUMNS},
        filter_index_name  VARCHAR,
        search_index_name  VARCHAR,
        row_count          BIGINT,
        next_template_no   INTEGER NOT NULL DEFAULT 1,
        timezone           VARCHAR NOT NULL DEFAULT 'UTC',
        created_at         TIMESTAMP NOT NULL,
        roles_updated_at   TIMESTAMP NOT NULL
    )"""

# Metric and trace tables have their own registries; log_tables is never touched for them (ADR-0004).
METRIC_TABLES_DDL = """CREATE TABLE IF NOT EXISTS extractor.metric_tables (
        name                 VARCHAR PRIMARY KEY,
        source               VARCHAR NOT NULL,
        source_format        VARCHAR NOT NULL,
        relation             VARCHAR NOT NULL,
        role_timestamp       VARCHAR NOT NULL,
        role_timestamp_unit  VARCHAR,
        role_service         VARCHAR,
        role_metric          VARCHAR NOT NULL,
        role_value           VARCHAR NOT NULL,
        row_count            BIGINT,
        timezone             VARCHAR NOT NULL DEFAULT 'UTC',
        created_at           TIMESTAMP NOT NULL
    )"""

TRACE_TABLES_DDL = """CREATE TABLE IF NOT EXISTS extractor.trace_tables (
        name                 VARCHAR PRIMARY KEY,
        source               VARCHAR NOT NULL,
        source_format        VARCHAR NOT NULL,
        relation             VARCHAR NOT NULL,
        role_trace_id        VARCHAR NOT NULL,
        role_span_id         VARCHAR NOT NULL,
        role_parent_span_id  VARCHAR,
        role_service         VARCHAR NOT NULL,
        role_operation       VARCHAR NOT NULL,
        role_start           VARCHAR NOT NULL,
        role_start_unit      VARCHAR,
        role_duration        VARCHAR NOT NULL,
        role_duration_unit   VARCHAR NOT NULL,
        role_status          VARCHAR,
        row_count            BIGINT,
        orphan_spans         BIGINT,
        setup_seconds        DOUBLE,
        timezone             VARCHAR NOT NULL DEFAULT 'UTC',
        created_at           TIMESTAMP NOT NULL
    )"""

DDL = [
    "CREATE SCHEMA IF NOT EXISTS extractor",
    LOG_TABLES_DDL,
    METRIC_TABLES_DDL,
    TRACE_TABLES_DDL,
    """CREATE TABLE IF NOT EXISTS extractor.log_index_columns (
        log_table          VARCHAR NOT NULL,
        kind               VARCHAR NOT NULL,
        columns            VARCHAR NOT NULL,
        PRIMARY KEY (log_table, kind)
    )""",
    """CREATE TABLE IF NOT EXISTS extractor.templates (
        log_table          VARCHAR NOT NULL,
        template_id        VARCHAR NOT NULL,
        template           VARCHAR NOT NULL,
        regex              VARCHAR NOT NULL,
        params             JSON NOT NULL,
        example            VARCHAR NOT NULL,
        first_seen         TIMESTAMP,
        last_seen          TIMESTAMP,
        last_estimate      BIGINT,
        last_estimate_at   TIMESTAMP,
        updated_at         TIMESTAMP NOT NULL,
        PRIMARY KEY (log_table, template_id)
    )""",
    """CREATE TABLE IF NOT EXISTS extractor.template_redirects (
        log_table          VARCHAR NOT NULL,
        old_id             VARCHAR NOT NULL,
        new_id             VARCHAR NOT NULL,
        merged_at          TIMESTAMP NOT NULL,
        PRIMARY KEY (log_table, old_id)
    )""",
    EVIDENCE_DDL,
    OWNERSHIP_DDL,
    CHANGES_DDL,
]


def bootstrap(db: Database) -> None:
    for statement in DDL:
        db.write(statement)
    upgrade(db)
    seed(db)
