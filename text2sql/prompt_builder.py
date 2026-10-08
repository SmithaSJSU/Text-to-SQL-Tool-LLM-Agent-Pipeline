"""
Dynamic prompt engineering: turns a DatabaseSchema into a compact,
LLM-friendly schema description, then assembles a full system + user
prompt that:

  - injects the actual table/column/type/PK/FK structure of the target
    database (so the model can't hallucinate columns or joins)
  - explicitly enforces which relationships (FKs) must be used for joins
  - constrains the model to a single, read-only, dialect-appropriate
    SQL statement
  - asks for output in a fenced ```sql block only, no prose, so the
    response is trivial to parse and validate downstream
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .schema_introspector import DatabaseSchema

SYSTEM_PROMPT_TEMPLATE = """You are an expert SQL analyst. Your job is to translate a natural \
language question into a single, correct, read-only SQL query for a {dialect} database.

You MUST follow these rules strictly:
1. Use ONLY the tables and columns listed in the schema below. Never invent tables or columns.
2. Use the documented foreign key relationships for JOINs -- do not invent join conditions.
3. Generate exactly ONE SQL statement. Do not chain multiple statements with semicolons.
4. Only generate read-only queries (SELECT ... or WITH ... SELECT ...). Never generate \
INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, GRANT, or any other data/schema-mutating statement.
5. Never use SQL comments (--, /* */) in the output.
6. If the question cannot be answered using the given schema, respond with exactly: \
NO_VALID_QUERY -- followed by a brief reason.
7. Output ONLY a single fenced code block like:
```sql
SELECT ...
```
Do not include any explanation, prose, or additional text outside the code block.

### Database Schema
{schema_description}

### Additional Constraints
{constraints}
"""

USER_PROMPT_TEMPLATE = """Question: {question}

Write the SQL query that answers this question, following all rules above."""


def describe_schema(schema: DatabaseSchema) -> str:
    """Render the schema as a compact, structured text block for the prompt."""
    lines: List[str] = []
    for table_name, table in schema.tables.items():
        lines.append(f"Table: {table_name}")
        for col in table.columns:
            flags = []
            if col.primary_key:
                flags.append("PK")
            if not col.nullable:
                flags.append("NOT NULL")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"  - {col.name}: {col.type}{flag_str}")
        if table.foreign_keys:
            lines.append("  Foreign Keys:")
            for fk in table.foreign_keys:
                lines.append(
                    f"    - {table_name}.{fk.column} -> "
                    f"{fk.references_table}.{fk.references_column}"
                )
        lines.append("")  # blank line between tables
    return "\n".join(lines).strip()


@dataclass
class PromptBundle:
    system_prompt: str
    user_prompt: str


class PromptBuilder:
    """Builds schema-aware prompts for text-to-SQL generation."""

    def __init__(
        self,
        schema: DatabaseSchema,
        dialect: str = "SQLite",
        extra_constraints: Optional[List[str]] = None,
    ):
        self.schema = schema
        self.dialect = dialect
        self.extra_constraints = extra_constraints or []

    def build(self, question: str) -> PromptBundle:
        schema_description = describe_schema(self.schema)

        constraints = self.extra_constraints or ["(none)"]
        constraints_str = "\n".join(f"- {c}" for c in constraints)

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            dialect=self.dialect,
            schema_description=schema_description,
            constraints=constraints_str,
        )
        user_prompt = USER_PROMPT_TEMPLATE.format(question=question.strip())

        return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt)
