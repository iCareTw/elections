from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from src.webapp.build_candidates import write_candidates_yaml
from src.webapp.store import Store

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/build")
async def build(request: Request):
    store: Store = request.app.state.store
    root: Path = request.app.state.root

    try:
        candidates = write_candidates_yaml(
            store,
            root / "candidates.yaml",
            root / "election_types.yaml",
        )
        logger.info("build candidates count=%d", len(candidates))
        return RedirectResponse(f"/?generated={len(candidates)}", status_code=303)
    except Exception as exc:
        logger.error("build failed: %s", exc, exc_info=True)
        return RedirectResponse("/?build_error=1", status_code=303)
