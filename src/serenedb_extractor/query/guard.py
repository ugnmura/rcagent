"""The read-only guard for run_sql: parse with sqlglot (postgres dialect) and accept exactly one
statement that is a query (SELECT, a set operation of selects, VALUES) or an EXPLAIN of one.
Anything that could modify data, change settings or kill sessions is rejected in plain language."""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from serenedb_extractor.errors import UserFacingError

BLOCKED_FUNCTIONS = {"pg_cancel_backend", "pg_terminate_backend", "set_config"}
REJECTED = "only read-only queries are allowed"

_QUERY_ROOTS = (exp.Select, exp.SetOperation, exp.Values)
_WRITE_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter, exp.TruncateTable,
    exp.Copy, exp.Set, exp.Command, exp.Pragma, exp.Use, exp.Into, exp.Lock, exp.Grant, exp.Comment,
    exp.Analyze, exp.Transaction, exp.Commit, exp.Rollback, exp.Attach, exp.Detach,
)


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


def _split_explain(sql: str, root: exp.Expr) -> str | None:
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
    inner = _split_explain(text, root)
    explain = inner is not None
    if inner is not None:
        root = _parse(inner)
        text = inner.rstrip(";").strip()
    if not isinstance(root, (*_QUERY_ROOTS, exp.Subquery)):
        raise SqlRejected("only SELECT queries, set operations and EXPLAIN of them can run")
    if isinstance(root, exp.Subquery) and not isinstance(root.unnest(), _QUERY_ROOTS):
        raise SqlRejected("only SELECT queries, set operations and EXPLAIN of them can run")
    for node in root.walk():
        if isinstance(node, _WRITE_NODES):
            raise SqlRejected("it changes data, settings or the database")
        if isinstance(node, exp.Select) and (node.args.get("locks") or node.args.get("into")):
            raise SqlRejected("it locks or writes rows")
        name = _function_name(node)
        if name in BLOCKED_FUNCTIONS:
            raise SqlRejected(f"{name}() is not allowed")
    return Checked(text, explain, root)
