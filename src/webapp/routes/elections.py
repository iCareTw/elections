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


def _election_tree(root: Path, store: Store) -> dict:
    raw = discover_elections(root)
    db_elections = {e["election_id"]: e for e in store.list_elections()}
    
    tree = {"name": "root", "children": {}, "pending_commit_count": 0}

    for e in raw:
        eid = e["election_id"]
        merged = {**e, **db_elections.get(eid, {})}
        merged.setdefault("status", "todo")
        pending_commit = merged["status"] != "done"
        
        parts = eid.split("/")
        current = tree
        path_acc = ""
        for i, part in enumerate(parts):
            if pending_commit:
                current["pending_commit_count"] += 1
            path_acc = f"{path_acc}/{part}" if path_acc else part
            if i == len(parts) - 1:
                # Leaf node (election)
                current["children"][part] = {
                    "kind": "election",
                    "data": merged
                }
            else:
                # Directory node
                if part not in current["children"]:
                    current["children"][part] = {
                        "kind": "dir",
                        "name": part,
                        "path": path_acc,
                        "children": {},
                        "pending_commit_count": 0,
                    }
                current = current["children"][part]

    return tree


@router.get("/")
async def home(request: Request):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates

    generated = request.query_params.get("generated")
    election_tree = _election_tree(root, store)

    return templates.TemplateResponse(request, "elections.html", {
        "election_tree": election_tree,
        "selected_id": None,
        "election": None,
        "generated": int(generated) if generated else None,
    })


@router.get("/elections/{election_id:path}")
async def election_detail(request: Request, election_id: str):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates

    election_tree = _election_tree(root, store)
    
    # Flatten to find the selected election
    raw = discover_elections(root)
    db_elections = {e["election_id"]: e for e in store.list_elections()}
    flat = {}
    for e in raw:
        eid = e["election_id"]
        merged = {**e, **db_elections.get(eid, {})}
        merged.setdefault("status", "todo")
        flat[eid] = merged

    election = flat.get(election_id)
    if election is None:
        return RedirectResponse("/")
    if election["status"] in ("review", "ready"):
        return RedirectResponse(f"/review/{election_id}", status_code=303)

    resolutions = store.list_resolutions(election_id) if election.get("status") == "done" else []
    _MODE_LABELS = {"auto": "自動匹配", "new": "自動建立", "manual_new": "新建人物", "manual": "人工合併"}
    for r in resolutions:
        r["mode_label"] = _MODE_LABELS.get(r["mode"], r["mode"])

    return templates.TemplateResponse(request, "elections.html", {
        "election_tree": election_tree,
        "selected_id": election_id,
        "election": election,
        "resolutions": resolutions,
    })


@router.post("/elections/{election_id:path}/load")
async def load_election(request: Request, election_id: str):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates

    raw_elections = {e["election_id"]: e for e in discover_elections(root)}
    raw_election = raw_elections.get(election_id)
    if raw_election is None:
        return RedirectResponse("/", status_code=303)

    records = load_election_records(raw_election)
    invalid_records = [
        r for r in records
        if not r.get("name") or not r.get("birthday") or not r.get("party")
    ]
    if invalid_records:
        election_tree = _election_tree(root, store)
        return templates.TemplateResponse(
            request,
            "elections.html",
            {
                "election_tree": election_tree,
                "selected_id": election_id,
                "election": {**raw_election, "status": "invalid_data", "invalid_records": invalid_records},
            },
            status_code=422,
        )

    store.upsert_election(raw_election)

    existing_decisions = {
        decision["source_record_id"]: decision
        for decision in store.list_review_decisions(election_id)
    }
    total = 0
    auto_new = 0

    for record in records:
        if record["source_record_id"] in existing_decisions:
            existing_mode = existing_decisions[record["source_record_id"]]["mode"]
            original_kind = existing_mode if existing_mode in ("auto", "new") else "manual"
            store.insert_source_record(
                source_record_id=record["source_record_id"],
                election_id=election_id,
                payload=record,
                original_kind=original_kind,
            )
            total += 1
            continue

        result = classify_record(record, store)
        store.insert_source_record(
            source_record_id=record["source_record_id"],
            election_id=election_id,
            payload=record,
            original_kind=result["kind"],
        )
        if result["kind"] in ("auto", "new"):
            store.upsert_review_decision(
                source_record_id=record["source_record_id"],
                election_id=election_id,
                candidate_id=result["candidate_id"],
                mode=result["kind"],
            )
            auto_new += 1
        total += 1

    decision_count = len(store.list_review_decisions(election_id))
    pending_count = total - decision_count
    logger.info("load election=%s total=%d auto_new=%d pending=%d",
                election_id, total, auto_new, pending_count)

    if pending_count == 0:
        source_records = store.list_source_records(election_id)
        decisions = {
            d["source_record_id"]: {"mode": d["mode"], "candidate_id": d["candidate_id"]}
            for d in store.list_review_decisions(election_id)
        }
        source_records_map = {r["source_record_id"]: r["payload"] for r in source_records}
        auto_c, manual_c = store.commit_election(
            election_id=election_id,
            decisions=decisions,
            source_records_map=source_records_map,
        )
        logger.info("auto-commit election=%s auto=%d manual=%d", election_id, auto_c, manual_c)
        return RedirectResponse(f"/elections/{election_id}", status_code=303)

    return RedirectResponse(f"/review/{election_id}", status_code=303)
