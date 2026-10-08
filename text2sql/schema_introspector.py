"""
Schema introspection layer.

Connects to a SQLAlchemy-supported database (SQLite by default, but the
same code path works for Postgres/MySQL/etc. by changing the connection
string) and produces a structured, serializable representation of the
schema: tables, columns, types, primary keys, and foreign key
relationships.

This structured schema is the single source of truth used by both:
  1. the prompt builder (to inject schema + constraints into the LLM prompt)
  2. the SQL validator (to check generated queries only reference real
     tables/columns and respect declared relationships)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    primary_key: bool = False


@dataclass
class ForeignKeyInfo:
    column: str
    references_table: str
    references_column: str


@dataclass
class TableInfo:
    name: str
    columns: List[ColumnInfo] = field(default_factory=list)
    foreign_keys: List[ForeignKeyInfo] = field(default_factory=list)

    @property
    def column_names(self) -> List[str]:
        return [c.name for c in self.columns]

    @property
    def primary_keys(self) -> List[str]:
        return [c.name for c in self.columns if c.primary_key]


@dataclass
class DatabaseSchema:
    tables: Dict[str, TableInfo] = field(default_factory=dict)

    def table_names(self) -> List[str]:
        return list(self.tables.keys())

    def has_table(self, name: str) -> bool:
        return name.lower() in {t.lower() for t in self.tables}

    def get_table(self, name: str) -> Optional[TableInfo]:
        for t_name, t in self.tables.items():
            if t_name.lower() == name.lower():
                return t
        return None

    def has_column(self, table: str, column: str) -> bool:
        t = self.get_table(table)
        if not t:
            return False
        return column.lower() in {c.lower() for c in t.column_names}

    def all_columns_flat(self) -> Dict[str, List[str]]:
        """table -> [columns], useful for validator lookups."""
        return {name: t.column_names for name, t in self.tables.items()}


class SchemaIntrospector:
    """Introspects a database and builds a DatabaseSchema."""

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.engine: Engine = create_engine(connection_string)

    def introspect(self, include_tables: Optional[List[str]] = None) -> DatabaseSchema:
        inspector = inspect(self.engine)
        schema = DatabaseSchema()

        table_names = inspector.get_table_names()
        if include_tables:
            wanted = {t.lower() for t in include_tables}
            table_names = [t for t in table_names if t.lower() in wanted]

        for table_name in table_names:
            pk_constraint = inspector.get_pk_constraint(table_name) or {}
            pk_cols = set(pk_constraint.get("constrained_columns") or [])

            columns = []
            for col in inspector.get_columns(table_name):
                columns.append(
                    ColumnInfo(
                        name=col["name"],
                        type=str(col["type"]),
                        nullable=col.get("nullable", True),
                        primary_key=col["name"] in pk_cols,
                    )
                )

            fks = []
            for fk in inspector.get_foreign_keys(table_name):
                referred_table = fk.get("referred_table")
                constrained = fk.get("constrained_columns") or []
                referred_cols = fk.get("referred_columns") or []
                for local_col, ref_col in zip(constrained, referred_cols):
                    fks.append(
                        ForeignKeyInfo(
                            column=local_col,
                            references_table=referred_table,
                            references_column=ref_col,
                        )
                    )

            schema.tables[table_name] = TableInfo(
                name=table_name, columns=columns, foreign_keys=fks
            )

        return schema


def load_schema(connection_string: str, include_tables: Optional[List[str]] = None) -> DatabaseSchema:
    """Convenience one-liner for the common case."""
    return SchemaIntrospector(connection_string).introspect(include_tables)
