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

    source_records = store.list_source_records(election_id)
    if not source_records:
        return RedirectResponse(f"/elections/{election_id}", status_code=303)

    decisions = {
        decision["source_record_id"]: decision
        for decision in store.list_review_decisions(election_id)
    }
    total_count = len(source_records)
    resolved_count = len(decisions)
    progress_pct = int(resolved_count / total_count * 100) if total_count else 0

    pending_records = [r for r in source_records if r["source_record_id"] not in decisions]
    display_records = pending_records if pending_records else source_records
    i = max(0, min(i, len(display_records) - 1))
    current_record = display_records[i]
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
        "incoming_birthday": payload.get("birthday"),
        "i": i,
        "pending_count": len(pending_records),
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

    birthday_override_raw = str(form.get("birthday_override", "")).strip()
    birthday_override = int(birthday_override_raw) if birthday_override_raw.isdigit() else None

    if mode == "use_match":
        mode = "manual"

    if birthday_override is not None and mode == "manual" and candidate_id:
        with store.connect() as conn:
            store._setup_conn(conn)
            conn.execute(
                "UPDATE candidates SET birthday = %s WHERE id = %s",
                (birthday_override, candidate_id),
            )

    if source_record_id and mode and candidate_id:
        store.upsert_review_decision(
            source_record_id=source_record_id,
            election_id=election_id,
            candidate_id=candidate_id,
            mode=mode,
        )

    next_i = max(0, min(i, total_count - 2))

    return RedirectResponse(f"/review/{election_id}?i={next_i}", status_code=303)


@router.post("/elections/{election_id:path}/commit")
async def commit(request: Request, election_id: str):
    store: Store = request.app.state.store

    source_records = store.list_source_records(election_id)
    decisions = {
        decision["source_record_id"]: {
            "mode": decision["mode"],
            "candidate_id": decision["candidate_id"],
        }
        for decision in store.list_review_decisions(election_id)
    }

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

    return RedirectResponse(f"/elections/{election_id}", status_code=303)
