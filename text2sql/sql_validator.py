"""
Validation and sanitization layer for LLM-generated SQL.

Design principle: never trust the LLM's output as executable SQL just
because it looks plausible. Every query is parsed into a real AST
(via sqlglot) and checked against an allow-list of behavior, rather
than trying to blacklist "bad" substrings (which is trivially bypassed).

Checks performed, in order:
  1. Extraction: pull SQL out of the model's response (fenced block or
     raw), reject if the model signaled it couldn't answer.
  2. Single statement: reject stacked/chained statements (a classic
     injection vector: "SELECT ...; DROP TABLE ...").
  3. Parseability: the query must parse into a valid AST for the
     target SQL dialect. Unparseable input is rejected outright --
     it's never passed to the database as a string.
  4. Statement type allow-list: only SELECT / WITH...SELECT is
     permitted. DML/DDL (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE,
     TRUNCATE, GRANT, ATTACH, PRAGMA, etc.) is rejected.
  5. Forbidden constructs: no comments, no semicolons mid-string, no
     multi-statement separators, no obvious injection patterns.
  6. Schema conformance: every table referenced must exist in the
     introspected schema; every column referenced (where resolvable)
     must belong to a table in the schema. This blocks hallucinated
     tables/columns AND blocks queries against tables the caller never
     exposed to the model.
  7. (Optional) row-limit enforcement for safety on ad hoc exploration.

The validator never executes SQL itself -- it only decides whether a
query is safe to hand to the execution layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

import sqlglot
from sqlglot import exp

from .schema_introspector import DatabaseSchema

ALLOWED_STATEMENT_TYPES = (exp.Select,)

# Statement/keyword types we explicitly refuse, even if sqlglot would
# happily parse them. Kept as an explicit deny-list on TOP of the
# allow-list above (belt and suspenders), for clear error messages.
FORBIDDEN_EXPRESSION_TYPES = {
    exp.Insert: "INSERT",
    exp.Update: "UPDATE",
    exp.Delete: "DELETE",
    exp.Drop: "DROP",
    exp.Alter: "ALTER",
    exp.Create: "CREATE",
    exp.TruncateTable: "TRUNCATE",
    exp.Grant: "GRANT",
    exp.Attach: "ATTACH",
    exp.Command: "raw/administrative command (e.g. PRAGMA)",
}

SUSPICIOUS_PATTERNS = [
    (re.compile(r";\s*\S"), "Multiple statements separated by ';' are not allowed."),
    (re.compile(r"--"), "SQL line comments ('--') are not allowed."),
    (re.compile(r"/\*"), "SQL block comments ('/* */') are not allowed."),
    (re.compile(r"\bxp_cmdshell\b", re.IGNORECASE), "Command execution procedures are not allowed."),
    (re.compile(r"\bINTO\s+OUTFILE\b", re.IGNORECASE), "File write operations are not allowed."),
    (re.compile(r"\bLOAD_FILE\s*\(", re.IGNORECASE), "File read operations are not allowed."),
]


@dataclass
class ValidationResult:
    is_valid: bool
    sql: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def raise_if_invalid(self):
        if not self.is_valid:
            raise SQLValidationError(self.errors)


class SQLValidationError(Exception):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def extract_sql_from_response(raw_response: str) -> Optional[str]:
    """
    Pulls SQL out of the model's raw text response.
    Expects a fenced ```sql ... ``` block per the prompt contract, but
    falls back to treating the whole response as SQL if no fence is found.
    Returns None if the model explicitly signaled it couldn't answer.
    """
    text = raw_response.strip()

    if text.upper().startswith("NO_VALID_QUERY"):
        return None

    fence_match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    return text if text else None


class SQLValidator:
    """Validates and sanitizes a candidate SQL string before execution."""

    def __init__(
        self,
        schema: DatabaseSchema,
        dialect: str = "sqlite",
        max_row_limit: Optional[int] = 1000,
        enforce_row_limit: bool = True,
    ):
        self.schema = schema
        self.dialect = dialect
        self.max_row_limit = max_row_limit
        self.enforce_row_limit = enforce_row_limit

    def validate(self, raw_llm_response: str) -> ValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        sql = extract_sql_from_response(raw_llm_response)
        if sql is None:
            return ValidationResult(
                is_valid=False,
                errors=["Model indicated the question cannot be answered from this schema."],
            )

        sql = sql.strip().rstrip(";").strip()
        if not sql:
            return ValidationResult(is_valid=False, errors=["Empty SQL after extraction."])

        # 1. Pattern-level checks (cheap, catches obvious injection attempts
        #    even before we invest in parsing).
        for pattern, message in SUSPICIOUS_PATTERNS:
            if pattern.search(sql):
                errors.append(message)

        # 2. Parse into AST. Anything unparseable is rejected outright --
        #    we never execute a string we can't structurally verify.
        try:
            statements = sqlglot.parse(sql, read=self.dialect)
        except Exception as e:  # sqlglot raises its own ParseError subclasses
            return ValidationResult(
                is_valid=False,
                errors=errors + [f"SQL failed to parse: {e}"],
            )

        statements = [s for s in statements if s is not None]

        # 3. Single statement only.
        if len(statements) != 1:
            errors.append(
                f"Expected exactly one SQL statement, found {len(statements)}."
            )

        if errors:
            return ValidationResult(is_valid=False, errors=errors)

        stmt = statements[0]

        # 4. Statement type allow-list / explicit deny-list.
        for bad_type, label in FORBIDDEN_EXPRESSION_TYPES.items():
            if isinstance(stmt, bad_type) or stmt.find(bad_type):
                errors.append(f"Statement type not allowed: {label}.")

        is_select_like = isinstance(stmt, exp.Select) or (
            isinstance(stmt, exp.With) and stmt.this and isinstance(stmt.this, exp.Select)
        )
        if not is_select_like and not errors:
            errors.append("Only SELECT (optionally with CTEs / WITH) statements are allowed.")

        if errors:
            return ValidationResult(is_valid=False, errors=errors, sql=sql)

        # 5. Schema conformance: every referenced table must exist.
        # CTE aliases (WITH x AS (...)) are not real tables and must be
        # excluded from this check -- they're valid to reference even
        # though they don't exist in the introspected schema.
        cte_names = {cte.alias.lower() for cte in stmt.find_all(exp.CTE) if cte.alias}
        referenced_tables = {
            t.name for t in stmt.find_all(exp.Table)
            if t.name and t.name.lower() not in cte_names
        }
        unknown_tables = [t for t in referenced_tables if not self.schema.has_table(t)]
        if unknown_tables:
            errors.append(
                f"Query references unknown table(s) not in schema: {', '.join(sorted(unknown_tables))}."
            )

        # 6. Best-effort column conformance: only checks unqualified /
        #    qualified simple columns we can confidently resolve; complex
        #    expressions (aliases, computed columns) are skipped rather
        #    than false-flagged.
        # Map table aliases (e.g. "c" in "customers c") back to their real
        # table name so qualified column checks (c.ssn) resolve correctly.
        alias_to_table = {}
        for t in stmt.find_all(exp.Table):
            if t.name and t.name.lower() not in cte_names:
                alias_to_table[t.name.lower()] = t.name
                if t.alias:
                    alias_to_table[t.alias.lower()] = t.name

        known_columns = set()
        for t in referenced_tables:
            table_info = self.schema.get_table(t)
            if table_info:
                known_columns.update(c.lower() for c in table_info.column_names)

        # Aliases defined in the SELECT list (e.g. `COUNT(*) AS total`) are
        # legitimate to reference unqualified in ORDER BY / GROUP BY / HAVING
        # and must not be flagged as unknown columns.
        select_aliases = set()
        select_expr = stmt.this if isinstance(stmt, exp.With) else stmt
        if isinstance(select_expr, exp.Select):
            for projection in select_expr.expressions:
                alias = projection.alias if hasattr(projection, "alias") else None
                if alias:
                    select_aliases.add(alias.lower())

        if not unknown_tables:
            for col in stmt.find_all(exp.Column):
                col_name = col.name
                if not col_name or col_name == "*":
                    continue
                if col_name.lower() in select_aliases:
                    continue
                if col.table:
                    if col.table.lower() in cte_names:
                        continue  # column belongs to a CTE, not a base table
                    resolved_table_name = alias_to_table.get(col.table.lower(), col.table)
                    tbl = self.schema.get_table(resolved_table_name)
                    if tbl and col_name.lower() not in {c.lower() for c in tbl.column_names}:
                        errors.append(
                            f"Column '{col.table}.{col_name}' does not exist in schema."
                        )
                    elif not tbl:
                        errors.append(
                            f"Column qualifier '{col.table}' does not resolve to a known table."
                        )
                else:
                    if not known_columns:
                        continue
                    if col_name.lower() not in known_columns:
                        if len(referenced_tables) == 1:
                            # Unambiguous: single table, column not found -> hard error.
                            errors.append(
                                f"Column '{col_name}' does not exist in table "
                                f"'{next(iter(referenced_tables))}'."
                            )
                        else:
                            # Ambiguous across a join -- can't be 100% sure it's
                            # not valid in some other referenced table's column
                            # set we haven't perfectly matched, so warn instead
                            # of hard-failing.
                            warnings.append(
                                f"Could not confidently resolve column '{col_name}' "
                                "against joined tables (may be an alias)."
                            )

        if errors:
            return ValidationResult(is_valid=False, errors=errors, sql=sql, warnings=warnings)

        # 7. Row-limit enforcement (defense in depth for ad hoc exploration --
        #    prevents accidentally pulling an entire large table).
        final_sql = sql
        if self.enforce_row_limit and self.max_row_limit:
            has_limit = stmt.find(exp.Limit) is not None
            if not has_limit:
                target_stmt = stmt.this if isinstance(stmt, exp.With) else stmt
                target_stmt.set("limit", exp.Limit(expression=exp.Literal.number(self.max_row_limit)))
                final_sql = stmt.sql(dialect=self.dialect)
                warnings.append(f"No LIMIT specified; capped at {self.max_row_limit} rows.")

        return ValidationResult(is_valid=True, sql=final_sql, errors=[], warnings=warnings)
