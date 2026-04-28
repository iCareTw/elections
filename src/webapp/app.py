from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from src.webapp.logging_setup import setup_logging
from src.webapp.routes import build, elections, review
from src.webapp.store import Store

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(root: Path = ROOT) -> FastAPI:
    setup_logging(root / "logs")

    app = FastAPI(title="Identity Workbench")
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-in-prod"),
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    store = Store()
    store.init_schema()

    app.state.store = store
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.root = root

    app.include_router(elections.router)
    app.include_router(review.router)
    app.include_router(build.router)

    return app


def main() -> None:
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=23088)


if __name__ == "__main__":
    main()
