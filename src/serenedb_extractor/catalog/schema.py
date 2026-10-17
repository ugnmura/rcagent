"""The `extractor` schema (spec section 5). Bootstrapping is idempotent."""

from serenedb_extractor.catalog.models import ROLE_FIELDS
from serenedb_extractor.db import Database

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

DDL = [
    "CREATE SCHEMA IF NOT EXISTS extractor",
    LOG_TABLES_DDL,
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
]


def bootstrap(db: Database) -> None:
    for statement in DDL:
        db.write(statement)
