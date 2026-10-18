"""The read-only guard for run_sql: parse with sqlglot (postgres dialect) and accept exactly one
statement that is a query (SELECT, a set operation of selects, VALUES) or an EXPLAIN of one.
Anything that could modify data, change settings or kill sessions is rejected in plain language."""

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope
from sqlglot.tokens import Token, TokenType

from rcagent.errors import UserFacingError

# Function ALLOWLIST (R56). Every word that is directly followed by "(" in the query text, as the
# SQL tokenizer sees it (so quoted names, schema qualifiers and different cases all count), must be
# one of these (lower case) or a bare SQL keyword that takes a parenthesis (SYNTAX_WORDS). Anything
# else is refused by name: functions that read files, sessions or settings, and every table function
# (read_*, glob, range, generate_series, current_setting, pg_*, ...) are simply not on the list. So are
# functions that build a huge value from a tiny input (repeat, lpad, rpad, and printf/format with a
# field width): one such call can run far past the timeout, which only stops a query between rows.
ALLOWED_FUNCTIONS = frozenset(
    """
    lower upper length char_length character_length octet_length substr substring left right trim ltrim rtrim btrim
    replace concat concat_ws position strpos contains starts_with ends_with prefix suffix reverse
    split_part string_split initcap ascii chr md5 hash translate overlay
    regexp_full_match regexp_matches regexp_extract regexp_extract_all regexp_replace regexp_split_to_array
    regexp_like regexp_match
    date_trunc date_part date_diff date_add date_sub datediff datepart extract epoch epoch_ms age now
    current_timestamp current_date current_time make_timestamp make_date make_time to_timestamp to_char
    strftime strptime time_bucket year month day hour minute second dayofweek dayofyear week quarter
    abs ceil ceiling floor round trunc sign sqrt cbrt power pow exp ln log log2 log10 mod div random
    greatest least coalesce nullif ifnull nvl if iif cast try_cast typeof timezone
    json_extract json_extract_string json_extract_path json_extract_path_text json_exists json_valid json_type
    json_array_length json_keys json_object json_array to_json
    count sum avg min max median mode stddev stddev_pop stddev_samp variance var_pop var_samp quantile quantile_cont
    quantile_disc percentile_cont percentile_disc approx_count_distinct approx_quantile any_value arbitrary first last
    list array_agg string_agg group_concat bool_and bool_or count_if sum_if arg_min arg_max min_by max_by histogram
    grouping row_number rank dense_rank percent_rank cume_dist ntile lag lead first_value last_value nth_value
    array_length cardinality array_to_string list_aggr list_contains list_distinct list_sort len array row
    varchar char text integer int bigint smallint tinyint double float real numeric decimal boolean
    timestamp timestamptz time timetz date interval bit
    """.split()
)
# String functions whose result can be much longer than their input; they may not be nested in one another.
MAX_GROWING_CALLS = 2
MAX_GROWING_OPS = 6
MAX_GROWING_LITERAL = 100
MAX_LITERAL = 1000
# Aggregates (and the calls that turn their lists into text) that collect a whole column into one value:
# one such value is as big as the table, so it may not feed another size-growing operation, nor run as a
# window function (OVER), where every row gets a value as big as all the rows before it.
COLLECTING_FUNCTIONS = frozenset(
    "string_agg group_concat array_agg list array histogram array_to_string list_aggr list_string_agg".split()
)
GROWING_FUNCTIONS = frozenset("replace regexp_replace overlay translate concat concat_ws".split()) | COLLECTING_FUNCTIONS
# Calls that build one value out of several: in a recursive CTE each round could double a value.
_RECURSIVE_BUILDERS = frozenset("json_array json_object to_json row".split())
# Words after which "(" or "[" opens a value of its own (a tuple, a list literal), not a call or an index.
_EXPR_START_WORDS = frozenset("select distinct then else when and or not all any some case".split())
# Keywords that may be followed by "(" without being a function call.
SYNTAX_WORDS = frozenset(
    """
    in not and or as on over from where select union intersect except all any some exists filter using by group
    order partition within values when then else case end join lateral distinct between like ilike is having
    limit offset with materialized similar escape rows window recursive cube rollup grouping
    """.split()
)
MAX_PAREN_DEPTH = 100
# Types whose casts look up catalog objects by name (leaking their existence and OIDs). Casts to
# plain `oid` are only numbers and stay allowed.
REG_TYPES = frozenset(
    "regclass regcollation regconfig regdictionary regnamespace regoper regoperator regproc regprocedure regrole regtype".split()
)
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


COMPLEX = "the query is too complex or couldn't be read"


def _matching_parens(tokens: list[Token]) -> dict[int, int]:
    """Index of each "(" -> index of its ")" (unbalanced ones are left out; the parser refuses them)."""
    out: dict[int, int] = {}
    stack: list[int] = []
    for i, tok in enumerate(tokens):
        if tok.token_type == TokenType.L_PAREN:
            stack.append(i)
        elif tok.token_type == TokenType.R_PAREN and stack:
            out[stack.pop()] = i
    return out


def _is_string(tok: Token) -> bool:
    return "STRING" in tok.token_type.name


def _starts_value(prev: Token | None) -> bool:
    """Whether a "(" or "[" right after `prev` opens a value (a tuple, a list literal) rather than a call or an index."""
    if prev is None:
        return True
    if _is_string(prev):
        return False
    text = prev.text.lower()
    if re.fullmatch(r"[a-z_][a-z0-9_$ ]*", text):
        return text in _EXPR_START_WORDS
    return prev.token_type not in (TokenType.R_PAREN, TokenType.R_BRACKET)


def _has_top_level_comma(tokens: list[Token], start: int, stop: int) -> bool:
    depth = 0
    for tok in tokens[start + 1 : stop]:
        if tok.token_type in (TokenType.L_PAREN, TokenType.L_BRACKET, TokenType.L_BRACE):
            depth += 1
        elif tok.token_type in (TokenType.R_PAREN, TokenType.R_BRACKET, TokenType.R_BRACE):
            depth -= 1
        elif tok.token_type == TokenType.COMMA and depth == 0:
            return True
    return False


RECURSIVE_GROWTH = (
    "a recursive query (WITH RECURSIVE) may not build text or values ({what}): each round could double a "
    "value until it fills the server's memory"
)


def _check_tokens(text: str) -> None:
    """Checks on the raw tokens, which see what the server will see: TABLE in any form, unicode-escaped
    names, runaway nesting, and every function name against the allowlist."""
    try:
        tokens = Dialect.get_or_raise("postgres").tokenize(text)
    except Exception:
        raise SqlRejected(COMPLEX) from None
    if any(tok.token_type == TokenType.SEMICOLON for tok in tokens):
        raise SqlRejected("run_sql runs one statement at a time; send each query on its own")
    closing = _matching_parens(tokens)
    # In a recursive CTE every round can double a value (s || s): no value building at all there.
    recursive = any(tok.token_type == TokenType.RECURSIVE for tok in tokens)
    depth = 0
    # Paren depths at which a size-growing string function's arguments are open: one inside another (replace of a
    # replace ...) can multiply a value's size in a single row, which the time-based cost check can't see.
    growing_open: list[int] = []
    growing_calls = 0
    growing_ops = 0  # growing calls plus || concatenations
    collecting: list[str] = []  # whole-column aggregates used
    literal_run = 0  # adjacent string literals ('a' 'b') are one text: their lengths add up
    for i, tok in enumerate(tokens):
        word = tok.text.lower() if not _is_string(tok) else ""
        prev = tokens[i - 1] if i > 0 else None
        if word.lstrip("_") in REG_TYPES:  # _regclass is the array type of regclass
            raise SqlRejected(f"casts to {word.lstrip('_')} look up catalog objects and are not allowed in run_sql")
        if tok.token_type == TokenType.TABLE:
            raise SqlRejected("TABLE is not allowed in run_sql; use SELECT * FROM extractor.<table>")
        if tok.token_type == TokenType.L_PAREN:
            depth += 1
            if depth > MAX_PAREN_DEPTH:
                raise SqlRejected(COMPLEX)
            stop = closing.get(i)
            if (
                recursive
                and stop is not None
                and _starts_value(prev)
                and tokens[i + 1].token_type not in (TokenType.SELECT, TokenType.WITH, TokenType.VALUES)
                and _has_top_level_comma(tokens, i, stop)
            ):
                raise SqlRejected(RECURSIVE_GROWTH.format(what="a tuple of values"))
        elif tok.token_type == TokenType.R_PAREN:
            if growing_open and growing_open[-1] == depth:
                growing_open.pop()
            depth -= 1
        if recursive and tok.token_type == TokenType.L_BRACE:
            raise SqlRejected(RECURSIVE_GROWTH.format(what="a struct literal"))
        if recursive and tok.token_type == TokenType.L_BRACKET and _starts_value(prev):
            raise SqlRejected(RECURSIVE_GROWTH.format(what="a list literal"))
        if _is_string(tok):
            literal_run = literal_run + len(tok.text) if prev is not None and _is_string(prev) else len(tok.text)
            limit = MAX_GROWING_LITERAL if growing_open else MAX_LITERAL
            if literal_run > limit:
                raise SqlRejected(
                    f"a text longer than {limit} characters"
                    + (" inside a replace/concat-style function" if growing_open else "")
                    + " is not allowed in run_sql (it can build huge values)"
                )
        if tok.token_type == TokenType.DPIPE:  # || concatenates: it grows values too
            if recursive:
                raise SqlRejected(RECURSIVE_GROWTH.format(what="||"))
            growing_ops += 1
            if growing_ops > MAX_GROWING_OPS:
                raise SqlRejected(f"at most {MAX_GROWING_OPS} || concatenations and replace/concat-style calls per query")
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is not None and nxt.token_type == TokenType.AMP and word == "u":
            raise SqlRejected("unicode-escaped names (U&...) are not allowed in run_sql")
        if nxt is None or nxt.token_type != TokenType.L_PAREN or not re.fullmatch(r"[a-z_][a-z0-9_$ ]*", word):
            continue
        quoted_or_plain = tok.token_type in (TokenType.VAR, TokenType.IDENTIFIER)
        if recursive and (word in GROWING_FUNCTIONS or word in _RECURSIVE_BUILDERS):
            raise SqlRejected(RECURSIVE_GROWTH.format(what=f"{word}()"))
        if word in COLLECTING_FUNCTIONS:
            collecting.append(word)
            _refuse_window(tokens, closing, i + 1, word)
        if word in GROWING_FUNCTIONS:
            if growing_open:
                raise SqlRejected(
                    f"{word}() inside another replace/concat-style function or string aggregate can build huge "
                    "values; nest at most one of them"
                )
            growing_calls += 1
            growing_ops += 1
            if growing_calls > MAX_GROWING_CALLS or growing_ops > MAX_GROWING_OPS:  # chained through subqueries or CTEs they multiply as well
                raise SqlRejected(
                    f"at most {MAX_GROWING_CALLS} replace/concat-style functions per query (they can build huge values)"
                )
            growing_open.append(depth + 1)  # its "(" comes next

        if word in ALLOWED_FUNCTIONS:
            continue
        if not quoted_or_plain and word.split()[0] in SYNTAX_WORDS:
            continue
        if word == "group" and tok.token_type == TokenType.VAR and prev is not None and prev.text.lower() == "within":
            continue  # percentile_cont(0.95) WITHIN GROUP (ORDER BY x)
        raise SqlRejected(f"function {word} isn't allowed in run_sql")
    if collecting and growing_ops > 1:
        raise SqlRejected(
            f"{collecting[0]}() gathers a whole column into one value, so it can't be combined with another "
            "replace/concat-style function, string aggregate or || in the same query (together they build huge values)"
        )


def _refuse_window(tokens: list[Token], closing: dict[int, int], open_at: int, word: str) -> None:
    """A whole-column aggregate run as a window function (its call, any FILTER (...), then OVER)."""
    stop = closing.get(open_at)
    j = stop + 1 if stop is not None else len(tokens)
    while (
        j + 1 < len(tokens)
        and tokens[j].text.lower() == "filter"
        and tokens[j + 1].token_type == TokenType.L_PAREN
        and (j + 1) in closing
    ):
        j = closing[j + 1] + 1
    if j < len(tokens) and tokens[j].token_type == TokenType.OVER:
        raise SqlRejected(
            f"{word}() as a window function (OVER) builds, for every row, a value as large as all the rows "
            "before it; use it as a plain aggregate with GROUP BY"
        )


def _cte_references(root: exp.Expr) -> set[int]:
    """ids of unqualified Table nodes that resolve to a CTE visible in their own scope."""
    ok: set[int] = set()
    for scope in traverse_scope(root):
        for t in scope.tables:
            if t.args.get("db") is None and isinstance(scope.sources.get(t.name), Scope):
                ok.add(id(t))
    return ok


def _check_relation(t: exp.Table, cte_refs: set[int]) -> None:
    if not isinstance(t.this, exp.Identifier):  # read_text('..'), generate_series(..), ROWS FROM ...
        what = t.this.name if t.this is not None and t.this.name else (t.this.sql_name() if isinstance(t.this, exp.Func) else "a table function")
        raise SqlRejected(f"{what.lower()}() is a table function; only tables in the {ALLOWED_SCHEMA} schema can be read")
    name = t.name
    schema = t.args.get("db")
    if schema is None:
        if id(t) in cte_refs:
            return
        raise SqlRejected(f"table {name} is not in the {ALLOWED_SCHEMA} schema; write {ALLOWED_SCHEMA}.{name}")
    sname = str(schema.name)
    if t.args.get("catalog") is not None or (sname if schema.quoted else sname.lower()) != ALLOWED_SCHEMA:
        raise SqlRejected(f"{t.sql(dialect='postgres')} is outside the {ALLOWED_SCHEMA} schema; only {ALLOWED_SCHEMA} tables can be read")


def _parse(sql: str) -> exp.Expr:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except RecursionError:
        raise SqlRejected(COMPLEX) from None
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
    try:
        return _check(sql)
    except RecursionError:
        raise SqlRejected(COMPLEX) from None


def _check(sql: str) -> Checked:
    text = sql.strip().rstrip(";").strip()
    _check_tokens(text)
    root = _parse(text)
    inner = _split_explain(root)
    explain = inner is not None
    if inner is not None:
        _check_tokens(inner)  # the tokenizer saw EXPLAIN's query as one string: check the query itself too
        root = _parse(inner)
        text = inner.rstrip(";").strip()
    if not isinstance(root, (*_QUERY_ROOTS, exp.Subquery)):
        raise SqlRejected("only SELECT queries, set operations and EXPLAIN of them can run")
    if isinstance(root, exp.Subquery) and not isinstance(root.unnest(), _QUERY_ROOTS):
        raise SqlRejected("only SELECT queries, set operations and EXPLAIN of them can run")
    try:
        cte_refs = _cte_references(root)
    except Exception:
        raise SqlRejected(COMPLEX) from None
    if any(isinstance(node, _WRITE_NODES) for node in root.walk()):  # say what is wrong before naming tables
        raise SqlRejected("it changes data, settings or the database")
    for node in root.walk():
        if isinstance(node, exp.Table):
            _check_relation(node, cte_refs)
        if isinstance(node, exp.Column) and node.name.lower() == "table":
            raise SqlRejected("TABLE is not allowed in run_sql; use SELECT * FROM extractor.<table>")
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
    return Checked(text, explain, root)
