"""
Top-level orchestration: natural language question -> validated SQL
(-> optionally executed rows).

    Question
       │
       ▼
  SchemaIntrospector  ──►  DatabaseSchema
       │
       ▼
  PromptBuilder  (schema-aware prompt + constraints)
       │
       ▼
  LLMClient  (LangChain call to Anthropic/OpenAI)
       │
       ▼
  SQLValidator  (parse, allow-list, schema-conformance, sanitize)
       │
       ├── invalid ──► PipelineResult(is_valid=False, errors=[...])
       │
       ▼
  QueryExecutor  (optional)
       │
       ▼
  PipelineResult(is_valid=True, sql=..., rows=...)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient, LLMConfig
from .prompt_builder import PromptBuilder
from .query_executor import QueryExecutor, QueryResult
from .schema_introspector import DatabaseSchema, load_schema
from .sql_validator import SQLValidator, ValidationResult


@dataclass
class PipelineResult:
    question: str
    is_valid: bool
    sql: Optional[str] = None
    raw_llm_response: Optional[str] = None
    errors: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
    rows: Optional[List[Dict[str, Any]]] = None
    row_count: Optional[int] = None


class TextToSQLPipeline:
    def __init__(
        self,
        connection_string: str,
        llm_config: Optional[LLMConfig] = None,
        dialect: str = "sqlite",
        include_tables: Optional[List[str]] = None,
        max_row_limit: Optional[int] = 1000,
        extra_constraints: Optional[List[str]] = None,
    ):
        self.connection_string = connection_string
        self.dialect = dialect

        self.schema: DatabaseSchema = load_schema(connection_string, include_tables)
        self.prompt_builder = PromptBuilder(
            schema=self.schema,
            dialect=dialect,
            extra_constraints=extra_constraints,
        )
        self.validator = SQLValidator(
            schema=self.schema,
            dialect=dialect.lower(),
            max_row_limit=max_row_limit,
        )
        self.llm_client = LLMClient(llm_config)
        self.executor = QueryExecutor(connection_string)

    def refresh_schema(self, include_tables: Optional[List[str]] = None) -> None:
        """Re-introspect the DB, e.g. after a migration."""
        self.schema = load_schema(self.connection_string, include_tables)
        self.prompt_builder.schema = self.schema
        self.validator.schema = self.schema

    def ask(self, question: str, execute: bool = True) -> PipelineResult:
        prompt = self.prompt_builder.build(question)
        raw_response = self.llm_client.generate(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
        )

        validation: ValidationResult = self.validator.validate(raw_response)

        if not validation.is_valid:
            return PipelineResult(
                question=question,
                is_valid=False,
                raw_llm_response=raw_response,
                errors=validation.errors,
                warnings=validation.warnings,
            )

        if not execute:
            return PipelineResult(
                question=question,
                is_valid=True,
                sql=validation.sql,
                raw_llm_response=raw_response,
                warnings=validation.warnings,
            )

        query_result: QueryResult = self.executor.execute(validation.sql)
        return PipelineResult(
            question=question,
            is_valid=True,
            sql=validation.sql,
            raw_llm_response=raw_response,
            warnings=validation.warnings,
            rows=query_result.rows,
            row_count=query_result.row_count,
        )
