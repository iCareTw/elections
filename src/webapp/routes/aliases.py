from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.webapp.routes.elections import _election_tree
from src.webapp.store import Store

router = APIRouter()


@router.get("/aliases")
async def aliases_index(request: Request):
    store: Store = request.app.state.store
    templates: Jinja2Templates = request.app.state.templates
    query = request.query_params.get("q", "").strip()
    return templates.TemplateResponse(request, "aliases.html", {
        "app_mode": "aliases",
        "election_tree": _election_tree(request.app.state.root, store),
        "selected_id": None,
        "query": query,
        "candidates": store.search_candidates_for_aliases(query),
        "error": request.query_params.get("error", ""),
    })


@router.post("/aliases/{candidate_id}/add")
async def add_alias(
    request: Request,
    candidate_id: str,
    alias_name: str = Form(...),
    q: str = Form(default=""),
):
    store: Store = request.app.state.store
    try:
        store.add_candidate_alias(candidate_id, alias_name)
    except ValueError as exc:
        params = urlencode({"q": q, "error": str(exc)})
        return RedirectResponse(f"/aliases?{params}", status_code=303)
    return RedirectResponse(f"/aliases?{urlencode({'q': q})}", status_code=303)


@router.post("/aliases/{candidate_id}/remove")
async def remove_alias(
    request: Request,
    candidate_id: str,
    alias_name: str = Form(...),
    q: str = Form(default=""),
):
    store: Store = request.app.state.store
    store.remove_candidate_alias(candidate_id, alias_name)
    return RedirectResponse(f"/aliases?{urlencode({'q': q})}", status_code=303)
