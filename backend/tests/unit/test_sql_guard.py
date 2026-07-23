"""A8 SQL guard — the eight injection cases the Phase 6 gate requires, plus
the legitimate-query cases that prove the guard is not simply refusing
everything. A guard with no false-negative test is indistinguishable from
`return False`.
"""

from __future__ import annotations

import pytest

from backend.services.sql_guard import SqlGuardError, validate

STAR_SCHEMA = {
    "dim_route", "dim_stop", "dim_station", "dim_date",
    "fact_ridership_monthly", "fact_modal_split_monthly", "dim_salik_tariff",
}


# =============================================================================
# The eight injection cases
# =============================================================================

INJECTIONS = [
    pytest.param(
        "SELECT * FROM dim_station; DROP TABLE dim_station;",
        id="1-stacked-statement",
    ),
    pytest.param(
        "DROP TABLE fact_ridership_monthly",
        id="2-bare-ddl",
    ),
    pytest.param(
        "DELETE FROM fact_ridership_monthly WHERE 1=1",
        id="3-bare-dml",
    ),
    pytest.param(
        "WITH gone AS (DELETE FROM dim_stop RETURNING *) SELECT * FROM gone",
        id="4-data-modifying-cte",
    ),
    pytest.param(
        "SELECT * FROM pg_catalog.pg_shadow",
        id="5-system-catalogue",
    ),
    pytest.param(
        "SELECT * FROM information_schema.tables",
        id="6-information-schema",
    ),
    pytest.param(
        "SELECT 1 --; DROP TABLE dim_route;\n",
        id="7-comment-smuggling",
    ),
    pytest.param(
        "SELECT pg_read_file('/etc/passwd')",
        id="8-file-read-function",
    ),
]


@pytest.mark.parametrize("sql", INJECTIONS)
def test_injection_is_blocked(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate(sql, allowed_tables=STAR_SCHEMA)


# =============================================================================
# Additional hostile input
# =============================================================================


def test_update_is_blocked() -> None:
    with pytest.raises(SqlGuardError):
        validate("UPDATE dim_station SET zone_id = 9", allowed_tables=STAR_SCHEMA)


def test_insert_is_blocked() -> None:
    with pytest.raises(SqlGuardError):
        validate("INSERT INTO dim_stop VALUES (1)", allowed_tables=STAR_SCHEMA)


def test_grant_is_blocked() -> None:
    with pytest.raises(SqlGuardError):
        validate("GRANT ALL ON dim_stop TO PUBLIC", allowed_tables=STAR_SCHEMA)


def test_unknown_table_is_blocked() -> None:
    """Tables outside the curated star schema are refused, so a hallucinated
    table name becomes a named gap rather than a confusing database error."""
    with pytest.raises(SqlGuardError, match="unknown table"):
        validate("SELECT * FROM secret_payroll", allowed_tables=STAR_SCHEMA)


def test_pg_prefixed_table_is_blocked() -> None:
    with pytest.raises(SqlGuardError):
        validate("SELECT * FROM pg_stat_activity", allowed_tables=None)


def test_empty_statement_is_blocked() -> None:
    with pytest.raises(SqlGuardError):
        validate("   ", allowed_tables=STAR_SCHEMA)


def test_query_with_no_tables_is_blocked() -> None:
    with pytest.raises(SqlGuardError, match="no tables"):
        validate("SELECT 1", allowed_tables=STAR_SCHEMA)


# =============================================================================
# Legitimate queries must pass — and be rewritten correctly
# =============================================================================


def test_simple_select_passes() -> None:
    result = validate(
        "SELECT station_name_en, zone_id FROM dim_station WHERE zone_id = 5",
        allowed_tables=STAR_SCHEMA,
    )
    assert "dim_station" in result.tables
    assert result.limit_applied is True
    assert "LIMIT 1000" in result.sql


def test_existing_limit_is_respected() -> None:
    result = validate(
        "SELECT * FROM dim_station LIMIT 10", allowed_tables=STAR_SCHEMA
    )
    assert result.limit_applied is False
    assert "LIMIT 10" in result.sql


def test_join_and_aggregate_passes() -> None:
    result = validate(
        """
        SELECT s.station_name_en, SUM(f.trips) AS total
        FROM fact_ridership_monthly f
        JOIN dim_station s ON s.station_id = f.station_id
        GROUP BY s.station_name_en
        ORDER BY total DESC
        """,
        allowed_tables=STAR_SCHEMA,
    )
    assert set(result.tables) == {"fact_ridership_monthly", "dim_station"}


def test_readonly_cte_passes() -> None:
    result = validate(
        """
        WITH monthly AS (
            SELECT station_id, SUM(trips) AS trips
            FROM fact_ridership_monthly GROUP BY station_id
        )
        SELECT * FROM monthly ORDER BY trips DESC
        """,
        allowed_tables=STAR_SCHEMA,
    )
    assert "fact_ridership_monthly" in result.tables


def test_markdown_fences_are_stripped() -> None:
    """LLMs habitually wrap SQL in code fences; that alone must not fail the query."""
    result = validate(
        "```sql\nSELECT zone_id FROM dim_station\n```", allowed_tables=STAR_SCHEMA
    )
    assert "dim_station" in result.tables


def test_trailing_semicolon_is_tolerated() -> None:
    result = validate("SELECT zone_id FROM dim_station;", allowed_tables=STAR_SCHEMA)
    assert "dim_station" in result.tables
