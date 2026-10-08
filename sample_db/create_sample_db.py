"""
Creates a small sample e-commerce SQLite database with realistic
relationships (PK/FK constraints) so the text-to-SQL pipeline has
something meaningful to introspect and query against.

Run:
    python sample_db/create_sample_db.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "ecommerce.db"

SCHEMA_SQL = """
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    signup_date   TEXT NOT NULL,
    country       TEXT NOT NULL
);

CREATE TABLE products (
    product_id    INTEGER PRIMARY KEY,
    product_name  TEXT NOT NULL,
    category      TEXT NOT NULL,
    unit_price    REAL NOT NULL,
    stock_qty     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL,
    order_date    TEXT NOT NULL,
    status        TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL,
    product_id    INTEGER NOT NULL,
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
"""

CUSTOMERS = [
    (1, "Ava", "Thompson", "ava.t@example.com", "2023-01-15", "USA"),
    (2, "Liam", "Garcia", "liam.g@example.com", "2023-02-20", "Mexico"),
    (3, "Noah", "Kim", "noah.k@example.com", "2023-03-05", "South Korea"),
    (4, "Mia", "Rossi", "mia.r@example.com", "2023-04-11", "Italy"),
    (5, "Zoe", "Dubois", "zoe.d@example.com", "2023-05-30", "France"),
]

PRODUCTS = [
    (1, "Wireless Mouse", "Electronics", 24.99, 150),
    (2, "Mechanical Keyboard", "Electronics", 89.99, 80),
    (3, "Standing Desk", "Furniture", 349.00, 20),
    (4, "Office Chair", "Furniture", 199.50, 35),
    (5, "USB-C Hub", "Electronics", 39.99, 200),
    (6, "Desk Lamp", "Furniture", 29.99, 100),
]

ORDERS = [
    (1, 1, "2023-06-01", "completed"),
    (2, 1, "2023-07-15", "completed"),
    (3, 2, "2023-06-20", "cancelled"),
    (4, 3, "2023-08-02", "completed"),
    (5, 4, "2023-08-10", "pending"),
    (6, 5, "2023-09-01", "completed"),
]

ORDER_ITEMS = [
    (1, 1, 1, 2, 24.99),
    (2, 1, 2, 1, 89.99),
    (3, 2, 5, 3, 39.99),
    (4, 3, 3, 1, 349.00),
    (5, 4, 4, 2, 199.50),
    (6, 5, 6, 4, 29.99),
    (7, 6, 2, 1, 89.99),
    (8, 6, 1, 1, 24.99),
]


def build_database(db_path: Path = DB_PATH) -> Path:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.executescript(SCHEMA_SQL)
        cur.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)", CUSTOMERS
        )
        cur.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?)", PRODUCTS
        )
        cur.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?)", ORDERS
        )
        cur.executemany(
            "INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", ORDER_ITEMS
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


if __name__ == "__main__":
    path = build_database()
    print(f"Sample database created at: {path}")
