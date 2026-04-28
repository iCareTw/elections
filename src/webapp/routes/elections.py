from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.webapp.discovery import discover_elections, load_election_records
from src.webapp.matching import classify_record
from src.webapp.store import Store

router = APIRouter()
logger = logging.getLogger(__name__)


def _election_tree(root: Path, store: Store) -> list[tuple[str, list[dict]]]:
    raw = discover_elections(root)
    for e in raw:
        store.upsert_election(e)

    db_elections = {e["election_id"]: e for e in store.list_elections()}
    groups: dict[str, list[dict]] = {}
    for e in raw:
        eid = e["election_id"]
        group = eid.split("/")[0]
        merged = {**e, **db_elections.get(eid, {})}
        merged.setdefault("status", "todo")
        groups.setdefault(group, []).append(merged)

    return list(groups.items())


@router.get("/")
async def home(request: Request):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates

    generated = request.query_params.get("generated")
    election_groups = _election_tree(root, store)

    return templates.TemplateResponse(request, "elections.html", {
        "election_groups": election_groups,
        "selected_id": None,
        "election": None,
        "generated": int(generated) if generated else None,
    })


@router.get("/elections/{election_id:path}")
async def election_detail(request: Request, election_id: str):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates

    election_groups = _election_tree(root, store)
    flat = {e["election_id"]: e for _, es in election_groups for e in es}
    election = flat.get(election_id)
    if election is None:
        return RedirectResponse("/")

    return templates.TemplateResponse(request, "elections.html", {
        "election_groups": election_groups,
        "selected_id": election_id,
        "election": election,
    })


@router.post("/elections/{election_id:path}/load")
async def load_election(request: Request, election_id: str):
    store: Store = request.app.state.store
    root: Path = request.app.state.root

    raw_elections = {e["election_id"]: e for e in discover_elections(root)}
    raw_election = raw_elections.get(election_id)
    if raw_election is None:
        return RedirectResponse("/", status_code=303)

    store.upsert_election(raw_election)

    session = request.session
    pending_key = f"pending_{election_id}"
    decisions: dict[str, dict] = {}
    total = 0

    for record in load_election_records(raw_election):
        store.insert_source_record(
            source_record_id=record["source_record_id"],
            election_id=election_id,
            payload=record,
        )
        result = classify_record(record, store)
        if result["kind"] in ("auto", "new"):
            decisions[record["source_record_id"]] = {
                "mode": result["kind"],
                "candidate_id": result["candidate_id"],
            }
        total += 1

    session[pending_key] = decisions
    logger.info("load election=%s total=%d auto_new=%d manual=%d",
                election_id, total, len(decisions), total - len(decisions))

    return RedirectResponse(f"/review/{election_id}", status_code=303)
