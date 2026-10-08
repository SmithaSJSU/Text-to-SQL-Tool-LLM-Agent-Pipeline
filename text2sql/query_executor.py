"""
Executes an already-validated, read-only SQL query and returns rows.

This layer intentionally does no validation of its own -- it trusts
that anything reaching it has already passed SQLValidator. It exists
as a separate module so the execution boundary (the only place that
actually touches the live database) is small, auditable, and easy to
swap for a read-only DB role / connection pool in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@dataclass
class QueryResult:
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int


class QueryExecutor:
    def __init__(self, connection_string: str):
        self.engine: Engine = create_engine(connection_string)

    def execute(self, sql: str) -> QueryResult:
        with self.engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return QueryResult(columns=columns, rows=rows, row_count=len(rows))
