from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.normalize import generate_id
from src.webapp.matching import classify_record
from src.webapp.store import Store
from src.webapp.routes.elections import _election_tree

router = APIRouter()
logger = logging.getLogger(__name__)

_FIELD_LABELS = {
    "name": "姓名", "birthday": "生日", "party": "政黨",
    "type": "選舉", "region": "地區", "elected": "當選",
    "year": "年份", "session": "屆次", "ticket": "號次",
}


@router.get("/review/{election_id:path}")
async def review_page(request: Request, election_id: str, i: int = 0):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates

    pending_key = f"pending_{election_id}"
    decisions: dict = request.session.get(pending_key, {})

    source_records = store.list_source_records(election_id)
    if not source_records:
        return RedirectResponse(f"/elections/{election_id}", status_code=303)

    total_count = len(source_records)
    resolved_count = sum(1 for r in source_records if r["source_record_id"] in decisions)
    progress_pct = int(resolved_count / total_count * 100) if total_count else 0

    i = max(0, min(i, total_count - 1))
    current_record = source_records[i]
    payload = current_record["payload"]

    result = classify_record(payload, store)
    matches = result.get("matches", [])

    record_fields = [
        (_FIELD_LABELS.get(k, k), payload[k])
        for k in ("name", "birthday", "year", "type", "region", "party", "elected")
        if k in payload
    ]

    election_tree = _election_tree(root, store)
    
    # Flatten to find the selected election
    from src.webapp.discovery import discover_elections
    raw = discover_elections(root)
    db_elections = {e["election_id"]: e for e in store.list_elections()}
    flat = {}
    for e in raw:
        eid = e["election_id"]
        merged = {**e, **db_elections.get(eid, {})}
        merged.setdefault("status", "todo")
        flat[eid] = merged

    election = flat.get(election_id, {"election_id": election_id, "label": election_id, "type": "", "year": ""})

    return templates.TemplateResponse(request, "review.html", {
        "election_tree": election_tree,
        "selected_id": election_id,
        "election": election,
        "current_record": current_record,
        "record_fields": record_fields,
        "matches": matches,
        "i": i,
        "total_count": total_count,
        "resolved_count": resolved_count,
        "progress_pct": progress_pct,
    })


@router.post("/review/{election_id:path}/resolve")
async def resolve(request: Request, election_id: str):
    form = await request.form()
    mode = str(form.get("mode", ""))
    source_record_id = str(form.get("source_record_id", ""))
    candidate_id = str(form.get("candidate_id", "")) or None
    i = int(str(form.get("i", 0)))
    total_count = int(str(form.get("total_count", 1)))

    store: Store = request.app.state.store

    if mode == "new":
        record = store.get_source_record(source_record_id)
        if record:
            candidate_id = generate_id(record["name"], record.get("birthday"))

    if mode == "use_match":
        mode = "manual"

    if source_record_id and mode and candidate_id:
        pending_key = f"pending_{election_id}"
        decisions = request.session.get(pending_key, {})
        decisions[source_record_id] = {"mode": mode, "candidate_id": candidate_id}
        request.session[pending_key] = decisions

    next_i = min(i + 1, total_count - 1)

    return RedirectResponse(f"/review/{election_id}?i={next_i}", status_code=303)


@router.post("/elections/{election_id:path}/commit")
async def commit(request: Request, election_id: str):
    store: Store = request.app.state.store

    pending_key = f"pending_{election_id}"
    decisions: dict = request.session.get(pending_key, {})
    source_records = store.list_source_records(election_id)

    if len(decisions) < len(source_records):
        return RedirectResponse(f"/review/{election_id}", status_code=303)

    source_records_map = {r["source_record_id"]: r["payload"] for r in source_records}
    auto, manual = store.commit_election(
        election_id=election_id,
        decisions=decisions,
        source_records_map=source_records_map,
    )

    logger.info("commit election=%s auto=%d manual=%d total=%d",
                election_id, auto, manual, auto + manual)

    request.session.pop(pending_key, None)
    return RedirectResponse(f"/elections/{election_id}", status_code=303)
