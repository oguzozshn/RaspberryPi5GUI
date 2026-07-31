from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from pi_agent.config import AgentConfig, load_config
from pi_agent.file_transfer import router as files_router
from pi_agent.logging_conf import setup_logging
from pi_agent.ws_router import router as ws_router


def create_app(config: AgentConfig) -> FastAPI:
    app = FastAPI(title="pi-agent")
    app.state.config = config
    app.include_router(ws_router)
    app.include_router(files_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def run() -> None:
    setup_logging()
    config = load_config()
    app = create_app(config)
    uvicorn.run(app, host=config.server.host, port=config.server.port)


if __name__ == "__main__":
    run()
