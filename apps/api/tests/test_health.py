import os

import pytest
from fastapi.testclient import TestClient
from pydantic import PostgresDsn

from agent_hq.config import Settings
from agent_hq.main import create_app


def test_live_returns_ok() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_returns_503_when_database_unreachable() -> None:
    settings = Settings(
        environment="test",
        database_url=PostgresDsn("postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"),
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "fail"}


@pytest.mark.skipif(
    "AGENT_HQ_DATABASE_URL" not in os.environ, reason="requires a running PostgreSQL"
)
def test_ready_returns_ok_with_database() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok"}


def test_docs_disabled_in_production() -> None:
    with TestClient(create_app(Settings(environment="production"))) as client:
        assert client.get("/docs").status_code == 404
