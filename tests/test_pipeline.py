"""
End-to-end pipeline tests using a stubbed-out LLM client so the full
question -> prompt -> (fake) LLM -> validate -> execute flow can be
tested deterministically, without hitting a real API.
"""

import pytest

from text2sql.pipeline import TextToSQLPipeline


class FakeLLMClient:
    """Drop-in replacement for LLMClient that returns canned responses."""

    def __init__(self, canned_response: str):
        self.canned_response = canned_response
        self.last_system_prompt = None
        self.last_user_prompt = None

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        return self.canned_response


def make_pipeline(connection_string, canned_response, monkeypatch):
    # Avoid constructing a real LLMClient (which would require an API key)
    # by patching TextToSQLPipeline.__init__'s LLM construction step.
    from text2sql import pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module,
        "LLMClient",
        lambda config=None: FakeLLMClient(canned_response),
    )
    return TextToSQLPipeline(connection_string=connection_string)


def test_pipeline_executes_valid_generated_query(connection_string, monkeypatch):
    canned = "```sql\nSELECT country, COUNT(*) AS n FROM customers GROUP BY country\n```"
    pipeline = make_pipeline(connection_string, canned, monkeypatch)

    result = pipeline.ask("How many customers per country?")

    assert result.is_valid
    assert result.rows is not None
    assert result.row_count == len(result.rows)
    assert all("country" in row and "n" in row for row in result.rows)


def test_pipeline_rejects_and_does_not_execute_malicious_generation(connection_string, monkeypatch):
    canned = "```sql\nSELECT * FROM customers; DROP TABLE customers;\n```"
    pipeline = make_pipeline(connection_string, canned, monkeypatch)

    result = pipeline.ask("Delete everyone")

    assert not result.is_valid
    assert result.rows is None
    assert result.errors

    # Confirm the table really is still there afterwards.
    from sqlalchemy import create_engine, inspect

    engine = create_engine(connection_string)
    assert "customers" in inspect(engine).get_table_names()


def test_pipeline_no_execute_mode_returns_sql_only(connection_string, monkeypatch):
    canned = "```sql\nSELECT product_name FROM products WHERE category = 'Furniture'\n```"
    pipeline = make_pipeline(connection_string, canned, monkeypatch)

    result = pipeline.ask("Which products are furniture?", execute=False)

    assert result.is_valid
    assert result.sql is not None
    assert result.rows is None


def test_pipeline_passes_schema_into_prompt(connection_string, monkeypatch):
    canned = "```sql\nSELECT 1\n```"
    pipeline = make_pipeline(connection_string, canned, monkeypatch)
    pipeline.ask("anything", execute=False)

    fake_client = pipeline.llm_client
    assert "customers" in fake_client.last_system_prompt
    assert "orders" in fake_client.last_system_prompt
    assert "How many" not in fake_client.last_system_prompt  # sanity: not leaking unrelated text
