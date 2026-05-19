from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.webapp.discovery import discover_elections, load_election_records
from src.webapp.matching import classify_record_cached
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


@router.get("/elections/{election_id:path}/reset-confirm")
async def reset_election_confirm(request: Request, election_id: str):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates
    next_url = request.query_params.get("next") or f"/elections/{election_id}"
    return templates.TemplateResponse(request, "reset_election_confirm.html", {
        "app_mode": "identity",
        "election_tree": _election_tree(root, store),
        "selected_id": election_id,
        "election_id": election_id,
        "next_url": next_url,
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
    _REQUIRED_FIELDS = (("name", "姓名"), ("birthday", "生日"), ("party", "政黨"))
    invalid_records = []
    for r in records:
        missing = [label for key, label in _REQUIRED_FIELDS if not r.get(key)]
        if missing:
            invalid_records.append({**r, "missing_fields": "、".join(missing)})
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
        d["source_record_id"]: d
        for d in store.list_review_decisions(election_id)
    }

    to_classify = [r for r in records if r["source_record_id"] not in existing_decisions]
    already_decided = [r for r in records if r["source_record_id"] in existing_decisions]

    # Batch-fetch candidates needed for classification (2 queries instead of N*2)
    names = {r["name"] for r in to_classify}
    candidates_by_name = store.list_candidates_by_names(names)
    all_candidates = store.list_candidates_with_elections() if names else []

    source_records_batch: list[dict] = []
    decisions_batch: list[dict] = []
    auto_new = 0

    for record in already_decided:
        existing_mode = existing_decisions[record["source_record_id"]]["mode"]
        original_kind = existing_mode if existing_mode in ("auto", "new") else "manual"
        source_records_batch.append({
            "source_record_id": record["source_record_id"],
            "election_id": election_id,
            "payload": record,
            "original_kind": original_kind,
        })

    for record in to_classify:
        result = classify_record_cached(record, candidates_by_name, all_candidates)
        source_records_batch.append({
            "source_record_id": record["source_record_id"],
            "election_id": election_id,
            "payload": record,
            "original_kind": result["kind"],
        })
        if result["kind"] in ("auto", "new"):
            decisions_batch.append({
                "source_record_id": record["source_record_id"],
                "election_id": election_id,
                "candidate_id": result["candidate_id"],
                "mode": result["kind"],
            })
            auto_new += 1

    store.batch_upsert_source_records(source_records_batch)
    store.batch_upsert_review_decisions(decisions_batch)
    total = len(records)

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


@router.post("/elections/{election_id:path}/reset")
async def reset_election(request: Request, election_id: str):
    store: Store = request.app.state.store
    form = await request.form()
    next_url = str(form.get("next") or f"/elections/{election_id}")
    stats = store.reset_election_data(election_id)
    store.refresh_identity_check_issues()
    logger.info("reset election=%s stats=%s", election_id, stats)
    return RedirectResponse(next_url, status_code=303)
