from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from pi_agent.config import AgentConfig, load_config
from pi_agent.file_transfer import router as files_router
from pi_agent.logging_conf import setup_logging
from pi_agent.ws_router import router as ws_router

WEB_ROOT = Path(__file__).resolve().parent.parent.parent / "web"


def create_app(config: AgentConfig) -> FastAPI:
    app = FastAPI(title="pi-agent")
    app.state.config = config
    app.include_router(ws_router)
    app.include_router(files_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Mounted last and at the root: a mount swallows every unmatched path, so
    # /ws, /files and /healthz have to be registered before it. The phone UI is
    # static and unauthenticated by nature - it is only a login form until the
    # user supplies the token the WebSocket demands.
    if WEB_ROOT.is_dir():
        app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")

    return app


def run() -> None:
    setup_logging()
    config = load_config()
    app = create_app(config)
    uvicorn.run(app, host=config.server.host, port=config.server.port)


if __name__ == "__main__":
    run()
