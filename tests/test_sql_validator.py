import pytest

from text2sql.sql_validator import SQLValidator


@pytest.fixture
def validator(schema):
    return SQLValidator(schema=schema, dialect="sqlite", max_row_limit=1000)


def wrap(sql: str) -> str:
    return f"```sql\n{sql}\n```"


# ---- Valid queries ----

def test_simple_select_is_valid(validator):
    r = validator.validate(wrap("SELECT first_name, last_name FROM customers"))
    assert r.is_valid
    assert "SELECT" in r.sql
    assert "LIMIT 1000" in r.sql


def test_join_using_real_fk_is_valid(validator):
    r = validator.validate(
        wrap(
            "SELECT c.first_name, o.order_date FROM customers c "
            "JOIN orders o ON c.customer_id = o.customer_id"
        )
    )
    assert r.is_valid


def test_cte_is_valid(validator):
    r = validator.validate(
        wrap("WITH recent AS (SELECT * FROM orders WHERE order_date > '2023-07-01') SELECT * FROM recent")
    )
    assert r.is_valid


def test_existing_limit_is_respected_not_duplicated(validator):
    r = validator.validate(wrap("SELECT * FROM products LIMIT 5"))
    assert r.is_valid
    assert r.sql.count("LIMIT") == 1
    assert "LIMIT 5" in r.sql


def test_group_by_alias_is_valid(validator):
    r = validator.validate(
        wrap("SELECT country, COUNT(*) AS total FROM customers GROUP BY country ORDER BY total DESC")
    )
    assert r.is_valid


def test_no_valid_query_signal_is_rejected(validator):
    r = validator.validate("NO_VALID_QUERY -- question unrelated to schema")
    assert not r.is_valid
    assert r.errors


# ---- Injection / malicious attempts ----

def test_stacked_statement_injection_is_rejected(validator):
    r = validator.validate(wrap("SELECT * FROM customers; DROP TABLE customers;"))
    assert not r.is_valid


def test_drop_table_is_rejected(validator):
    r = validator.validate(wrap("DROP TABLE customers"))
    assert not r.is_valid


def test_delete_is_rejected(validator):
    r = validator.validate(wrap("DELETE FROM customers WHERE customer_id = 1"))
    assert not r.is_valid


def test_update_is_rejected(validator):
    r = validator.validate(wrap("UPDATE customers SET email = 'hacked@evil.com'"))
    assert not r.is_valid


def test_insert_is_rejected(validator):
    r = validator.validate(wrap("INSERT INTO customers (first_name) VALUES ('x')"))
    assert not r.is_valid


def test_comment_based_injection_is_rejected(validator):
    r = validator.validate(wrap("SELECT * FROM customers WHERE 1=1 -- ' OR '1'='1"))
    assert not r.is_valid


def test_pragma_command_is_rejected(validator):
    r = validator.validate(wrap("PRAGMA table_info(customers)"))
    assert not r.is_valid


def test_attach_database_is_rejected(validator):
    r = validator.validate(wrap("ATTACH DATABASE '/etc/passwd' AS pwned"))
    assert not r.is_valid


# ---- Schema conformance (hallucination guardrails) ----

def test_unknown_table_is_rejected(validator):
    r = validator.validate(wrap("SELECT * FROM secret_admin_table"))
    assert not r.is_valid
    assert any("secret_admin_table" in e for e in r.errors)


def test_unknown_column_single_table_is_rejected(validator):
    r = validator.validate(wrap("SELECT ssn FROM customers"))
    assert not r.is_valid
    assert any("ssn" in e for e in r.errors)


def test_unknown_qualified_column_is_rejected(validator):
    r = validator.validate(wrap("SELECT c.ssn FROM customers c"))
    assert not r.is_valid
