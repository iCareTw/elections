from __future__ import annotations

import logging
from pathlib import Path

import io

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from src.voter_guide.guide_crop import crop_photo_frac, render_page
from src.voter_guide.guide_repair import run_repair_job

router = APIRouter(prefix="/guide")
logger = logging.getLogger(__name__)


@router.get("")
async def guide_home(request: Request):
    store = request.app.state.store
    templates = request.app.state.templates
    tree = store.guide_tree()
    return templates.TemplateResponse(request, "guide/index.html", {
        "tree": tree,
        "selected_election_id": None,
        "candidates": None,
        "selected_candidate_id": None,
    })


@router.get("/election/{election_id}")
async def guide_election(request: Request, election_id: str):
    store = request.app.state.store
    templates = request.app.state.templates
    tree = store.guide_tree()
    candidates = store.guide_candidates_of(election_id)
    return templates.TemplateResponse(request, "guide/index.html", {
        "tree": tree,
        "selected_election_id": election_id,
        "candidates": candidates,
        "selected_candidate_id": None,
    })


@router.get("/candidate/{candidate_id}")
async def guide_candidate(request: Request, candidate_id: int):
    store = request.app.state.store
    templates = request.app.state.templates

    view = store.guide_candidate_view(candidate_id)
    tree = store.guide_tree()
    candidates = store.guide_candidates_of(view["candidate"]["election_id"])

    # Derive candidate display name from fields
    name_val = next(
        (f["value"] for f in view["fields"] if f["field_name"] == "姓名"),
        "",
    )
    candidate = {**view["candidate"], "name": name_val}

    version_str = request.query_params.get("version")
    if version_str is not None:
        version_no = int(version_str)
        snap = store.guide_snapshot_view(candidate_id, version_no)
        # Normalize snapshot fields to share template shape with working-view fields
        snap_fields = [
            {**f, "id": None, "can_ai_repair": False}
            for f in snap["fields"]
        ]
        return templates.TemplateResponse(request, "guide/candidate.html", {
            "tree": tree,
            "selected_election_id": candidate["election_id"],
            "candidates": candidates,
            "selected_candidate_id": candidate_id,
            "candidate": candidate,
            "fields": snap_fields,
            "has_uncommitted": False,
            "latest_version": view["latest_version"],
            "version_no": snap["version_no"],
            "min_version": snap["min_version"],
            "max_version": snap["max_version"],
            "readonly": True,
        })

    latest = view["latest_version"]
    return templates.TemplateResponse(request, "guide/candidate.html", {
        "tree": tree,
        "selected_election_id": candidate["election_id"],
        "candidates": candidates,
        "selected_candidate_id": candidate_id,
        "candidate": candidate,
        "fields": view["fields"],
        "has_uncommitted": view["has_uncommitted"],
        "latest_version": latest,
        "version_no": latest,
        "min_version": 1 if latest >= 1 else 0,
        "max_version": latest,
        "readonly": False,
    })


@router.get("/crop")
async def serve_crop(request: Request, path: str):
    """Serve a crop/photo image file.  Rejects paths outside project _out/ directory."""
    root: Path = request.app.state.root
    out_dir = (root / "_out").resolve()
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(out_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path not allowed")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(resolved))


# ---------------------------------------------------------------------------
# POST actions — field level
# ---------------------------------------------------------------------------

@router.post("/field/{field_id}/flag")
async def flag_field(
    request: Request,
    field_id: int,
    note: str = Form(""),
    candidate_id: int = Form(...),
):
    request.app.state.store.guide_flag_field(field_id, note)
    return RedirectResponse(f"/guide/candidate/{candidate_id}", status_code=303)


@router.post("/field/{field_id}/unflag")
async def unflag_field(
    request: Request,
    field_id: int,
    candidate_id: int = Form(...),
):
    request.app.state.store.guide_unflag_field(field_id)
    return RedirectResponse(f"/guide/candidate/{candidate_id}", status_code=303)


@router.post("/field/{field_id}/value")
async def set_field_value(
    request: Request,
    field_id: int,
    value: str = Form(...),
    candidate_id: int = Form(...),
):
    request.app.state.store.guide_set_field_value(field_id, value)
    return RedirectResponse(f"/guide/candidate/{candidate_id}", status_code=303)


@router.post("/field/{field_id}/repair")
async def repair_field(
    request: Request,
    field_id: int,
    background_tasks: BackgroundTasks,
    candidate_id: int = Form(...),
    note: str = Form(""),
):
    store = request.app.state.store
    ref = store.guide_field_ref(field_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="field not found")
    if not ref["source_crop_path"]:
        raise HTTPException(status_code=400, detail="此欄無來源切圖,無法 AI 修復")
    job_id = store.guide_create_repair_job(
        ref["guide_candidate_id"], ref["field_name"], note or None)
    background_tasks.add_task(run_repair_job, store, job_id)
    return RedirectResponse(
        f"/guide/candidate/{candidate_id}?repair_job={job_id}", status_code=303)


@router.get("/repair/{job_id}/status")
async def repair_status(request: Request, job_id: int):
    job = request.app.state.store.guide_get_repair_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JSONResponse({
        "status": job["status"],
        "target": job["target"],
        "result_value": job["result_value"],
        "error": job["error"],
    })


# --- 照片手動圈選補正 (Phase 7) ---

@router.get("/candidate/{candidate_id}/crop")
async def crop_page(request: Request, candidate_id: int):
    ref = request.app.state.store.guide_candidate_pdf_ref(candidate_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    has_source = ref["source_page"] is not None and bool(ref["source_pdf_path"])
    return request.app.state.templates.TemplateResponse(
        request,
        "guide/crop.html",
        {"candidate_id": candidate_id, "has_source": has_source},
    )


@router.get("/candidate/{candidate_id}/page-image")
async def crop_page_image(request: Request, candidate_id: int):
    ref = request.app.state.store.guide_candidate_pdf_ref(candidate_id)
    if ref is None or ref["source_page"] is None or not ref["source_pdf_path"]:
        raise HTTPException(status_code=404, detail="no source page")
    img = render_page(ref["source_pdf_path"], ref["source_page"])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.post("/candidate/{candidate_id}/crop")
async def crop_submit(
    request: Request,
    candidate_id: int,
    x0: float = Form(...),
    y0: float = Form(...),
    x1: float = Form(...),
    y1: float = Form(...),
):
    store = request.app.state.store
    ref = store.guide_candidate_pdf_ref(candidate_id)
    if ref is None or ref["source_page"] is None or not ref["source_pdf_path"]:
        raise HTTPException(status_code=400, detail="無來源 PDF/頁碼,無法圈選補照片")
    root = Path(request.app.state.root)
    dest = root / "_out" / "parsed" / "manual_photos" / f"cand_{candidate_id}.png"
    crop_photo_frac(ref["source_pdf_path"], ref["source_page"], (x0, y0, x1, y1), dest)
    store.guide_set_photo_path(candidate_id, str(dest))
    return RedirectResponse(f"/guide/candidate/{candidate_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST actions — photo level
# ---------------------------------------------------------------------------

@router.post("/candidate/{candidate_id}/photo/flag")
async def flag_photo(
    request: Request,
    candidate_id: int,
    note: str = Form(""),
):
    request.app.state.store.guide_flag_photo(candidate_id, note)
    return RedirectResponse(f"/guide/candidate/{candidate_id}", status_code=303)


@router.post("/candidate/{candidate_id}/photo/unflag")
async def unflag_photo(request: Request, candidate_id: int):
    request.app.state.store.guide_unflag_photo(candidate_id)
    return RedirectResponse(f"/guide/candidate/{candidate_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST actions — commit / discard
# ---------------------------------------------------------------------------

@router.post("/candidate/{candidate_id}/commit")
async def commit_candidate(
    request: Request,
    candidate_id: int,
    note: str = Form(""),
):
    request.app.state.store.guide_commit(candidate_id, note or None)
    return RedirectResponse(f"/guide/candidate/{candidate_id}", status_code=303)


@router.post("/candidate/{candidate_id}/discard")
async def discard_candidate(request: Request, candidate_id: int):
    request.app.state.store.guide_discard(candidate_id)
    return RedirectResponse(f"/guide/candidate/{candidate_id}", status_code=303)
