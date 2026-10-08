from text2sql.prompt_builder import PromptBuilder, describe_schema


def test_schema_description_includes_tables_and_fks(schema):
    desc = describe_schema(schema)
    assert "Table: customers" in desc
    assert "Table: orders" in desc
    assert "orders.customer_id -> customers.customer_id" in desc


def test_prompt_bundle_contains_question_and_rules(schema):
    builder = PromptBuilder(schema=schema, dialect="SQLite")
    bundle = builder.build("How many customers are there?")

    assert "read-only" in bundle.system_prompt
    assert "single SQL statement" in bundle.system_prompt or "ONE SQL statement" in bundle.system_prompt
    assert "customers" in bundle.system_prompt
    assert "How many customers are there?" in bundle.user_prompt


def test_extra_constraints_are_injected(schema):
    builder = PromptBuilder(
        schema=schema,
        extra_constraints=["Always filter out cancelled orders unless explicitly asked."],
    )
    bundle = builder.build("List all orders")
    assert "cancelled orders" in bundle.system_prompt
