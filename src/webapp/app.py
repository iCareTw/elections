from __future__ import annotations

import os
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from src.webapp.bulletin import bulletin_url_from_record
from src.webapp.logging_setup import setup_logging
from src.webapp.routes import build, elections, review
from src.webapp.store import Store

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    store = Store()
    store.open()
    app.state.store = store
    yield
    # Shutdown
    app.state.store.close()


def create_app(root: Path = ROOT) -> FastAPI:
    setup_logging(root / "logs")

    app = FastAPI(title="Identity Workbench", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-in-prod"),
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.globals["bulletin_url_from_record"] = bulletin_url_from_record
    app.state.templates = templates
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
