#!/usr/bin/env python3
"""Static, database-independent contract checks for experiment/schema.sql.

This is a DDL contract lint only. It does not parse or execute PostgreSQL SQL,
and it does not prove constraint or trigger behavior. Run ``make schema-test``
against a real PostgreSQL/TimescaleDB instance for runtime verification.
"""

from __future__ import annotations

import re
from pathlib import Path

EXPECTED_TABLES = ("experiment_run", "experiment_result", "remediation_action")
EXPECTED_POLICIES = {"hpa_tuned", "forecast_hybrid"}
EXPECTED_STATUSES = {"proposed", "approved", "rejected", "applied", "failed"}
EXPECTED_DURATION_CHECKS = {
    "experiment_run": {"slo_p95_ms", "horizon_s"},
    "experiment_result": {
        "slo_breach_duration_s",
        "pod_minutes",
        "mttd_s",
    },
}
EXPECTED_IMMUTABLE_FIELDS = {
    "action_id",
    "proposed_at",
    "service",
    "action_type",
    "params",
    "evidence",
    "run_id",
}
EXPECTED_TRANSITIONS = {
    ("proposed", "approved"),
    ("proposed", "rejected"),
    ("approved", "applied"),
    ("approved", "failed"),
}

TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
TRIGGER_RE = re.compile(
    r"CREATE\s+TRIGGER\s+remediation_audit_guard_trg\s+"
    r"BEFORE\s+UPDATE\s+OR\s+DELETE\s+ON\s+remediation_action\s+"
    r"FOR\s+EACH\s+ROW\s+EXECUTE\s+FUNCTION\s+remediation_audit_guard\s*\(\s*\)\s*;",
    re.IGNORECASE,
)
FUNCTION_RE = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+remediation_audit_guard\s*\(\s*\)\s+"
    r"RETURNS\s+trigger\s+AS\s+\$\$(.*?)\$\$\s+LANGUAGE\s+plpgsql\s*;",
    re.IGNORECASE | re.DOTALL,
)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_line_comments(sql: str) -> str:
    """Remove SQL line comments without touching quoted text or dollar bodies."""
    result: list[str] = []
    index = 0
    quote: str | None = None
    dollar_tag: str | None = None

    while index < len(sql):
        char = sql[index]

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                result.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                result.append(char)
                index += 1
            continue

        if quote is not None:
            result.append(char)
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    result.append(sql[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if char in ("'", '"'):
            quote = char
            result.append(char)
            index += 1
            continue

        if char == "$":
            tag_match = re.match(
                r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql[index:]
            )
            if tag_match:
                dollar_tag = tag_match.group(0)
                result.append(dollar_tag)
                index += len(dollar_tag)
                continue

        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            if newline == -1:
                break
            result.append("\n")
            index = newline + 1
            continue

        result.append(char)
        index += 1

    return "".join(result)


def split_top_level(body: str) -> list[str]:
    """Split a table body on top-level commas, ignoring quotes and parentheses."""
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    index = 0

    while index < len(body):
        char = body[index]
        if quote is not None:
            if char == quote:
                if index + 1 < len(body) and body[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(body[start:index])
            start = index + 1
        index += 1

    parts.append(body[start:])
    return [normalize_whitespace(part) for part in parts if part.strip()]


def extract_tables(sql: str) -> dict[str, str]:
    tables: dict[str, str] = {}
    for match in TABLE_RE.finditer(sql):
        name = match.group(1).lower()
        assert name not in tables, f"duplicate CREATE TABLE for {name}"
        tables[name] = match.group(2)
    return tables


def extract_columns(table_name: str, body: str) -> dict[str, str]:
    columns: dict[str, str] = {}
    for definition in split_top_level(body):
        match = re.match(r"([A-Za-z_]\w*)\b", definition)
        assert match, f"{table_name}: cannot parse column definition: {definition!r}"
        name = match.group(1).lower()
        assert name not in columns, f"{table_name}: duplicate column {name}"
        columns[name] = definition
    return columns


def parse_check_enum(
    table_name: str, column_name: str, definition: str
) -> set[str]:
    pattern = (
        rf"CHECK\s*\(\s*{re.escape(column_name)}"
        rf"\s+IN\s*\(([^)]*)\)\s*\)"
    )
    match = re.search(pattern, definition, re.IGNORECASE)
    assert match, f"{table_name}.{column_name}: missing IN (...) CHECK"

    values = re.findall(r"'([^']*)'", match.group(1))
    assert len(values) == len(set(values)), (
        f"{table_name}.{column_name}: duplicate values in CHECK list"
    )
    return {value.lower() for value in values}


def check_schema(sql: str) -> None:
    executable_sql = normalize_whitespace(strip_line_comments(sql))

    tables = extract_tables(executable_sql)
    for table_name in EXPECTED_TABLES:
        assert table_name in tables, f"missing table declaration: {table_name}"

    columns = {
        table_name: extract_columns(table_name, body)
        for table_name, body in tables.items()
    }
    run_columns = columns["experiment_run"]
    result_columns = columns["experiment_result"]
    remediation_columns = columns["remediation_action"]

    assert "run_id" in result_columns, "experiment_result.run_id is missing"
    assert re.fullmatch(
        r"run_id\s+BIGINT\s+PRIMARY\s+KEY\s+REFERENCES\s+experiment_run"
        r"\s*\(\s*run_id\s*\)\s+ON\s+DELETE\s+CASCADE",
        result_columns["run_id"],
        re.IGNORECASE,
    ), "experiment_result.run_id must be PK/FK to experiment_run with ON DELETE CASCADE"

    assert "policy" in run_columns, "experiment_run.policy is missing"
    policies = parse_check_enum("experiment_run", "policy", run_columns["policy"])
    assert policies == EXPECTED_POLICIES, (
        f"experiment_run.policy CHECK set is {sorted(policies)}, "
        f"expected {sorted(EXPECTED_POLICIES)}"
    )

    for table_name, fields in EXPECTED_DURATION_CHECKS.items():
        for field in fields:
            assert field in columns[table_name], (
                f"{table_name}.{field} is missing"
            )
            check_pattern = (
                rf"CHECK\s*\(\s*{re.escape(field)}\s*>=\s*0\s*\)"
            )
            assert re.search(
                check_pattern, columns[table_name][field], re.IGNORECASE
            ), f"{table_name}.{field}: missing non-negative CHECK"

    assert "status" in remediation_columns, "remediation_action.status is missing"
    status_definition = remediation_columns["status"]
    assert re.search(
        r"\bDEFAULT\s+'proposed'(?:\s|$)", status_definition, re.IGNORECASE
    ), "remediation_action.status must default to 'proposed'"
    statuses = parse_check_enum(
        "remediation_action", "status", status_definition
    )
    assert statuses == EXPECTED_STATUSES, (
        f"remediation_action.status CHECK set is {sorted(statuses)}, "
        f"expected {sorted(EXPECTED_STATUSES)}"
    )

    assert TRIGGER_RE.search(executable_sql), (
        "remediation_audit_guard_trg must be declared "
        "BEFORE UPDATE OR DELETE ON remediation_action"
    )

    function_match = FUNCTION_RE.search(executable_sql)
    assert function_match, "remediation_audit_guard() trigger function is missing"
    # Strip PL/pgSQL comments too; otherwise commented-out guards could pass.
    function_body = normalize_whitespace(strip_line_comments(function_match.group(1)))

    assert re.search(
        r"IF\s+TG_OP\s*=\s*'DELETE'\s+THEN\s+RAISE\s+EXCEPTION"
        r"\s+'[^']*DELETE blocked[^']*'",
        function_body,
        re.IGNORECASE,
    ), "trigger function is missing the DELETE guard"

    immutable_fields = re.findall(
        r"NEW\.(\w+)\s+IS\s+DISTINCT\s+FROM\s+OLD\.\1",
        function_body,
        re.IGNORECASE,
    )
    assert len(immutable_fields) == len(set(immutable_fields)), (
        "trigger function has duplicate immutable-field checks"
    )
    assert {field.lower() for field in immutable_fields} == EXPECTED_IMMUTABLE_FIELDS, (
        "trigger function immutable-field set is "
        f"{sorted(field.lower() for field in immutable_fields)}, "
        f"expected {sorted(EXPECTED_IMMUTABLE_FIELDS)}"
    )
    assert re.search(
        r"RAISE\s+EXCEPTION\s+'[^']*immutable field rewrite blocked[^']*'",
        function_body,
        re.IGNORECASE,
    ), "trigger function is missing the immutable-field exception"

    transition_match = re.search(
        r"NOT\s+IN\s*\((.*?)\)\s+THEN",
        function_body,
        re.IGNORECASE | re.DOTALL,
    )
    assert transition_match, "trigger function is missing the status transition guard"
    transitions = re.findall(
        r"\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)",
        transition_match.group(1),
    )
    transition_set = {(old.lower(), new.lower()) for old, new in transitions}
    assert len(transitions) == len(transition_set), (
        "trigger function has duplicate status transitions"
    )
    assert transition_set == EXPECTED_TRANSITIONS, (
        f"trigger function transition set is {sorted(transition_set)}, "
        f"expected {sorted(EXPECTED_TRANSITIONS)}"
    )


def main() -> None:
    schema_path = Path(__file__).resolve().with_name("schema.sql")
    schema_sql = schema_path.read_text(encoding="utf-8")
    check_schema(schema_sql)
    print(
        "schema_offline_test OK: static schema contract check passed "
        "(PostgreSQL syntax, constraint enforcement, and trigger runtime "
        "behavior are NOT verified)."
    )


if __name__ == "__main__":
    main()
