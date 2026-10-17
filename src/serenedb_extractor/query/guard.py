"""The read-only guard for run_sql: parse with sqlglot (postgres dialect) and accept exactly one
statement that is a query (SELECT, a set operation of selects, VALUES) or an EXPLAIN of one.
Anything that could modify data, change settings or kill sessions is rejected in plain language."""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from serenedb_extractor.errors import UserFacingError

BLOCKED_FUNCTIONS = {"pg_cancel_backend", "pg_terminate_backend", "set_config"}
# Deny-by-name rule for every function call (lower case, any schema qualifier ignored): an exact
# name below, or a name starting/ending with one of the affixes. A function that sqlglot does not
# know (Anonymous) is allowed unless it matches; known ones are matched by their SQL name.
DENIED_NAMES = BLOCKED_FUNCTIONS | {"glob", "nextval", "setval", "currval"}
DENIED_PREFIXES = (
    "pg_", "lo_", "dblink", "read_", "parquet_", "sniff_", "copy", "query_to_", "txid_", "load", "install",
)
DENIED_SUFFIXES = ("_to_xml",)
ALLOWED_SCHEMA = "extractor"
REJECTED = "only read-only queries are allowed"

_QUERY_ROOTS = (exp.Select, exp.SetOperation, exp.Values)
# Nodes that can only appear inside a query when it writes or changes state (a data-modifying CTE,
# SELECT INTO ...); statement-level ones never reach the walk because the root must be a query.
_WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter, exp.Copy, exp.Set, exp.Command, exp.Into)


class SqlRejected(UserFacingError):
    def __init__(self, why: str) -> None:
        super().__init__(f"Not run: {REJECTED} ({why}). Nothing was changed.")


@dataclass(frozen=True)
class Checked:
    sql: str  # the query, without a trailing semicolon (for an EXPLAIN: the explained query)
    explain: bool  # the statement was an EXPLAIN of `sql`
    tree: exp.Expr  # the parsed query (for EXPLAIN: the explained query)


def _function_name(node: exp.Expr) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower() if isinstance(node, exp.Func) else ""


def _source_name(node: exp.Expr | None) -> str:
    if node is None:
        return "a function"
    return (_function_name(node) or str(node.name) or "a function").lower()


def _denied(name: str) -> bool:
    return name in DENIED_NAMES or name.startswith(DENIED_PREFIXES) or name.endswith(DENIED_SUFFIXES)


def _check_relation(t: exp.Table, ctes: set[str]) -> None:
    if not isinstance(t.this, exp.Identifier):  # read_text('..'), generate_series(..), ROWS FROM ...
        what = t.this.name if t.this is not None and t.this.name else (t.this.sql_name() if isinstance(t.this, exp.Func) else "a table function")
        raise SqlRejected(f"{what.lower()}() is a table function; only tables in the {ALLOWED_SCHEMA} schema can be read")
    name = t.name
    schema = t.args.get("db")
    if schema is None:
        if name.lower() in ctes:
            return
        raise SqlRejected(f"table {name} is not in the {ALLOWED_SCHEMA} schema; write {ALLOWED_SCHEMA}.{name}")
    sname = str(schema.name)
    if t.args.get("catalog") is not None or (sname if schema.quoted else sname.lower()) != ALLOWED_SCHEMA:
        raise SqlRejected(f"{t.sql(dialect='postgres')} is outside the {ALLOWED_SCHEMA} schema; only {ALLOWED_SCHEMA} tables can be read")


def _parse(sql: str) -> exp.Expr:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError:
        raise SqlRejected("it could not be read as a single SQL query") from None
    if not statements:
        raise SqlRejected("there is no statement")
    if len(statements) > 1:
        raise SqlRejected("more than one statement")
    return statements[0]


def _split_explain(root: exp.Expr) -> str | None:
    """The explained query's text when `root` is a plain EXPLAIN, else None."""
    if not (isinstance(root, exp.Command) and str(root.this).upper() == "EXPLAIN"):
        return None
    rest = str(root.expression.name if isinstance(root.expression, exp.Literal) else root.expression or "").strip()
    if not rest:
        raise SqlRejected("EXPLAIN needs a query")
    if rest.upper().startswith(("ANALYZE", "(")):
        raise SqlRejected("EXPLAIN options are not supported")
    return rest


def check_read_only(sql: str) -> Checked:
    text = sql.strip().rstrip(";").strip()
    root = _parse(text)
    inner = _split_explain(root)
    explain = inner is not None
    if inner is not None:
        root = _parse(inner)
        text = inner.rstrip(";").strip()
    if not isinstance(root, (*_QUERY_ROOTS, exp.Subquery)):
        raise SqlRejected("only SELECT queries, set operations and EXPLAIN of them can run")
    if isinstance(root, exp.Subquery) and not isinstance(root.unnest(), _QUERY_ROOTS):
        raise SqlRejected("only SELECT queries, set operations and EXPLAIN of them can run")
    ctes = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    for node in root.walk():
        if isinstance(node, exp.Table):
            _check_relation(node, ctes)
        # A function used as a row source (FROM f(), JOIN f(), LATERAL f(), unnest(..)) is refused whatever
        # its name. A LATERAL subquery is allowed: its tables are checked like any other.
        if isinstance(node, exp.Lateral) and not isinstance(node.this, (exp.Subquery, exp.Select)):
            raise SqlRejected(_source_name(node.this) + "() is a table function; only tables in the extractor schema can be read")
        if isinstance(node, (exp.From, exp.Join)) and isinstance(node.this, exp.Func):
            raise SqlRejected(_source_name(node.this) + "() is a table function; only tables in the extractor schema can be read")
        if isinstance(node, exp.Unnest):
            raise SqlRejected("unnest() is a table function; only tables in the extractor schema can be read")
        if isinstance(node, _WRITE_NODES):
            raise SqlRejected("it changes data, settings or the database")
        if isinstance(node, exp.Select) and (node.args.get("locks") or node.args.get("into")):
            raise SqlRejected("it locks or writes rows")
        name = _function_name(node)
        if name and _denied(name):
            raise SqlRejected(f"{name}() is not allowed")
    return Checked(text, explain, root)
