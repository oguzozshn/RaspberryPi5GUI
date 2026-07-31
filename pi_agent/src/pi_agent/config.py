from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel

DEFAULT_CONFIG_PATH = Path("/etc/pi-agent/config.toml")


class AuthConfig(BaseModel):
    token: str


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8765


class StatsConfig(BaseModel):
    interval_seconds: float = 2.0


class AgentConfig(BaseModel):
    auth: AuthConfig
    server: ServerConfig = ServerConfig()
    stats: StatsConfig = StatsConfig()


def config_path() -> Path:
    """Resolve config location. PI_AGENT_CONFIG overrides the default,
    used for local development since /etc/pi-agent doesn't exist off-Pi."""
    override = os.environ.get("PI_AGENT_CONFIG")
    return Path(override) if override else DEFAULT_CONFIG_PATH


def load_config(path: Path | None = None) -> AgentConfig:
    path = path or config_path()
    with path.open("rb") as f:
        data = tomllib.load(f)
    return AgentConfig.model_validate(data)
