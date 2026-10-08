import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sample_db.create_sample_db import build_database
from text2sql.schema_introspector import load_schema


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("db")
    return build_database(db_dir / "test_ecommerce.db")


@pytest.fixture(scope="session")
def connection_string(db_path):
    return f"sqlite:///{db_path}"


@pytest.fixture(scope="session")
def schema(connection_string):
    return load_schema(connection_string)
