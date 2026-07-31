from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pi_agent.config import AgentConfig, AuthConfig, ServerConfig, StatsConfig
from pi_agent.main import create_app

TOKEN = "test-token-123"


@pytest.fixture
def client() -> TestClient:
    config = AgentConfig(
        auth=AuthConfig(token=TOKEN),
        server=ServerConfig(),
        # keep the push loop out of the way of request/response assertions
        stats=StatsConfig(interval_seconds=60.0),
    )
    return TestClient(create_app(config))


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}
