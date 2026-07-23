"""Four-layer SQL safety for the Text-to-SQL agent (A8).

Layers one and two are here. Layers three and four are infrastructure:

    1. sqlglot AST parsing — reject anything that is not a single SELECT   (this module)
    2. keyword denylist and statement-shape checks                        (this module)
    3. execution under a read-only Postgres role                          (scripts/init_db.sql)
    4. 5s statement timeout and a forced LIMIT                            (both)

Layers three and four are defence in depth: they assume layers one and two will
eventually be defeated. A guard that trusts its own parser is not a guard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from backend.services.logging import get_logger

log = get_logger(__name__)

DEFAULT_ROW_LIMIT = 1000

# Statement types that must never reach the database, regardless of how the
# query is spelled. Checked against the parsed AST, not the raw string, so
# comment tricks and whitespace games do not help.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Merge,
)

# Belt-and-braces textual denylist. The AST check above is authoritative; this
# catches dialect constructs sqlglot may parse into something unexpected.
_DENY_PATTERN = re.compile(
    r"\b("
    r"drop|delete|update|insert|alter|truncate|grant|revoke|create|merge|"
    r"copy|vacuum|analyze|reindex|cluster|comment|call|do|execute|prepare|"
    r"pg_read_file|pg_ls_dir|pg_sleep|dblink|lo_import|lo_export|"
    r"set_config|current_setting|pg_terminate_backend"
    r")\b",
    re.IGNORECASE,
)

# System catalogues leak schema and role information; the star schema is the
# only surface A8 is allowed to see.
_BLOCKED_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}


class SqlGuardError(Exception):
    """Raised when generated SQL fails validation. Never surfaced to the user
    verbatim — A8 converts it into a named gap for the Grader (A12)."""


@dataclass(slots=True)
class GuardResult:
    sql: str
    """The validated, rewritten statement — this is what executes."""

    tables: list[str]
    limit_applied: bool
    original_sql: str


def _strip_fences(sql: str) -> str:
    """Remove markdown fences and trailing semicolons an LLM tends to add."""
    text = sql.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    return text.strip().rstrip(";").strip()


def validate(
    sql: str,
    *,
    allowed_tables: set[str] | None = None,
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> GuardResult:
    """Validate and rewrite generated SQL, or raise `SqlGuardError`.

    Returns a statement guaranteed to be a single SELECT with a bounded row
    count, touching only permitted tables.
    """
    original = sql
    text = _strip_fences(sql)

    if not text:
        raise SqlGuardError("empty statement")

    # --- layer 2a: multiple statements ------------------------------------
    try:
        statements = sqlglot.parse(text, read="postgres")
    except Exception as exc:
        raise SqlGuardError(f"unparseable SQL: {type(exc).__name__}: {exc}") from exc

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SqlGuardError(f"expected exactly one statement, found {len(statements)}")

    tree = statements[0]

    # --- layer 1: must be a SELECT ----------------------------------------
    # A CTE-led query parses to Select with a `with` arg, which is fine.
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        raise SqlGuardError(f"only SELECT is permitted, got {type(tree).__name__.upper()}")

    for node_type in _FORBIDDEN_NODES:
        if list(tree.find_all(node_type)):
            raise SqlGuardError(f"forbidden statement type: {node_type.__name__.upper()}")

    # A data-modifying CTE (WITH x AS (DELETE ...)) is the classic bypass.
    # CTE names are also collected: they are query-local aliases, not real
    # tables, so checking them against the table allowlist would reject
    # perfectly legitimate queries.
    cte_aliases: set[str] = set()
    for cte in tree.find_all(exp.CTE):
        inner = cte.this
        if not isinstance(inner, (exp.Select, exp.Union, exp.Subquery)):
            raise SqlGuardError("CTEs must contain only SELECT statements")
        if alias := cte.alias_or_name:
            cte_aliases.add(alias.lower())

    # --- layer 2b: textual denylist ---------------------------------------
    # Applied to the rendered AST, which has comments stripped — so
    # `SELECT 1 --; DROP TABLE x` cannot smuggle anything past.
    rendered = tree.sql(dialect="postgres")
    if match := _DENY_PATTERN.search(rendered):
        raise SqlGuardError(f"forbidden keyword: {match.group(1).upper()}")

    # --- layer 2c: table allowlist ----------------------------------------
    tables: list[str] = []
    for table in tree.find_all(exp.Table):
        schema = (table.db or "").lower()
        name = (table.name or "").lower()
        if schema in _BLOCKED_SCHEMAS:
            raise SqlGuardError(f"access to system schema {schema!r} is not permitted")
        if name.startswith("pg_"):
            raise SqlGuardError(f"access to system table {name!r} is not permitted")
        if name and name not in cte_aliases:
            tables.append(name)

    if allowed_tables is not None:
        unknown = {t for t in tables if t not in allowed_tables}
        if unknown:
            raise SqlGuardError(
                f"unknown table(s): {', '.join(sorted(unknown))}. "
                f"Only the curated star schema is queryable."
            )

    if not tables:
        raise SqlGuardError("query references no tables")

    # --- layer 4: force a row limit ---------------------------------------
    limit_applied = False
    if isinstance(tree, exp.Select) and tree.args.get("limit") is None:
        tree = tree.limit(row_limit)
        limit_applied = True
    elif isinstance(tree, exp.Union):
        tree = exp.Subquery(this=tree).select("*").limit(row_limit)
        limit_applied = True

    final_sql = tree.sql(dialect="postgres", pretty=True)

    log.info(
        "sql_guard.validated",
        tables=sorted(set(tables)),
        limit_applied=limit_applied,
    )
    return GuardResult(
        sql=final_sql,
        tables=sorted(set(tables)),
        limit_applied=limit_applied,
        original_sql=original,
    )


def is_safe(sql: str, *, allowed_tables: set[str] | None = None) -> bool:
    """Boolean convenience wrapper for tests and quick checks."""
    try:
        validate(sql, allowed_tables=allowed_tables)
        return True
    except SqlGuardError:
        return False
