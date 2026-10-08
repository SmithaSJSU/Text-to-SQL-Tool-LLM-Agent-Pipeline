def test_all_expected_tables_present(schema):
    expected = {"customers", "products", "orders", "order_items"}
    assert expected.issubset(set(schema.table_names()))


def test_customers_columns(schema):
    t = schema.get_table("customers")
    assert t is not None
    assert "customer_id" in t.column_names
    assert "email" in t.column_names
    assert "customer_id" in t.primary_keys


def test_foreign_keys_detected(schema):
    orders = schema.get_table("orders")
    fk_targets = {(fk.column, fk.references_table, fk.references_column) for fk in orders.foreign_keys}
    assert ("customer_id", "customers", "customer_id") in fk_targets

    order_items = schema.get_table("order_items")
    fk_targets_oi = {(fk.column, fk.references_table, fk.references_column) for fk in order_items.foreign_keys}
    assert ("order_id", "orders", "order_id") in fk_targets_oi
    assert ("product_id", "products", "product_id") in fk_targets_oi


def test_has_table_case_insensitive(schema):
    assert schema.has_table("Customers")
    assert not schema.has_table("nonexistent_table")


def test_has_column(schema):
    assert schema.has_column("customers", "email")
    assert not schema.has_column("customers", "ssn")
