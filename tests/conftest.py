import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def configure_env():
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    db_path = Path("/tmp/toolgateway_test.db")
    if db_path.exists():
        db_path.unlink()

    os.environ["TOOLGATEWAY_DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["TOOLGATEWAY_ADMIN_KEY"] = "test-admin-key"
    os.environ["TOOLGATEWAY_SERVICE_KEY"] = "test-service-key"


@pytest.fixture()
def client(configure_env):
    from app.main import app

    with TestClient(app) as c:
        yield c
