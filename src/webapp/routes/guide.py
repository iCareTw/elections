from __future__ import annotations

import io
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from src.voter_guide.guide_crop import crop_photo_frac, render_page
from src.voter_guide.guide_repair import run_repair_job

router = APIRouter(prefix="/guide")
logger = logging.getLogger(__name__)


def _group_url(group_id: int, *, repair_job: int | None = None) -> str:
    url = f"/guide/group/{group_id}"
    if repair_job is not None:
        url += f"?repair_job={repair_job}"
    return url


@router.get("")
async def guide_home(request: Request):
    store = request.app.state.store
    return request.app.state.templates.TemplateResponse(request, "guide/index.html", {
        "tree": store.guide_tree(),
        "selected_election_id": None,
        "candidates": None,
        "selected_group_id": None,
    })


@router.get("/election/{election_id}")
async def guide_election(request: Request, election_id: str):
    store = request.app.state.store
    return request.app.state.templates.TemplateResponse(request, "guide/index.html", {
        "tree": store.guide_tree(),
        "selected_election_id": election_id,
        "candidates": store.guide_candidates_of(election_id),
        "selected_group_id": None,
    })


@router.get("/group/{group_id}")
async def guide_group(request: Request, group_id: int):
    store = request.app.state.store
    templates = request.app.state.templates

    loc = store.guide_group_locate(group_id)
    if loc is None:
        raise HTTPException(status_code=404, detail="group not found")
    view = store.guide_group_view(loc["election_id"], loc["ticket"])
    tree = store.guide_tree()
    candidates = store.guide_candidates_of(loc["election_id"])

    ctx = {
        "tree": tree,
        "selected_election_id": loc["election_id"],
        "candidates": candidates,
        "selected_group_id": group_id,
        "group": view["group"],
        "president": view["president"],
        "vice": view["vice"],
        "platform": view["platform"],
    }

    version_str = request.query_params.get("version")
    if version_str is not None:
        snap = store.guide_group_snapshot_view(group_id, int(version_str))
        pres_fields = [{**f, "id": None, "can_ai_repair": False}
                       for f in snap["fields"] if f["scope"] == "總統"]
        vice_fields = [{**f, "id": None, "can_ai_repair": False}
                       for f in snap["fields"] if f["scope"] == "副總統"]
        plat = next((f for f in snap["fields"] if f["scope"] == "政見"), None)
        ctx.update({
            "president": {"candidate": view["president"]["candidate"], "fields": pres_fields}
            if view["president"] else None,
            "vice": {"candidate": view["vice"]["candidate"], "fields": vice_fields}
            if view["vice"] else None,
            "platform": {**(plat or {}), "can_ai_repair": False},
            "has_uncommitted": False,
            "latest_version": view["latest_version"],
            "version_no": snap["version_no"],
            "min_version": snap["min_version"],
            "max_version": snap["max_version"],
            "readonly": True,
        })
        return templates.TemplateResponse(request, "guide/group.html", ctx)

    latest = view["latest_version"]
    ctx.update({
        "has_uncommitted": view["has_uncommitted"],
        "latest_version": latest,
        "version_no": latest,
        "min_version": 1 if latest >= 1 else 0,
        "max_version": latest,
        "readonly": False,
    })
    return templates.TemplateResponse(request, "guide/group.html", ctx)


@router.get("/candidate/{candidate_id}")
async def guide_candidate_redirect(request: Request, candidate_id: int):
    """相容舊連結:導到候選人所屬組視圖。"""
    gid = request.app.state.store.guide_candidate_group_id(candidate_id)
    if gid is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return RedirectResponse(_group_url(gid), status_code=303)


@router.get("/election/{election_id}/pdf")
async def serve_election_pdf(request: Request, election_id: str):
    store = request.app.state.store
    row = store.guide_election_row(election_id)
    if row is None or not row.get("source_pdf_path"):
        raise HTTPException(status_code=404, detail="no source PDF")
    pdf = Path(row["source_pdf_path"]).resolve()
    root: Path = request.app.state.root
    allowed = [(root / "_data").resolve(), (root / "_out").resolve()]
    if not any(_within(pdf, base) for base in allowed):
        raise HTTPException(status_code=403, detail="Path not allowed")
    if not pdf.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(pdf), media_type="application/pdf",
                        content_disposition_type="inline")


def _within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


@router.get("/crop")
async def serve_crop(request: Request, path: str):
    """Serve a crop/photo image file.  Rejects paths outside project _out/ directory."""
    root: Path = request.app.state.root
    out_dir = (root / "_out").resolve()
    resolved = Path(path).resolve()
    if not _within(resolved, out_dir):
        raise HTTPException(status_code=403, detail="Path not allowed")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(resolved))


# ---------------------------------------------------------------------------
# 文字欄動作(候選人層)— redirect 回組視圖
# ---------------------------------------------------------------------------

@router.post("/field/{field_id}/flag")
async def flag_field(request: Request, field_id: int,
                     note: str = Form(""), group_id: int = Form(...)):
    request.app.state.store.guide_flag_field(field_id, note)
    return RedirectResponse(_group_url(group_id), status_code=303)


@router.post("/field/{field_id}/unflag")
async def unflag_field(request: Request, field_id: int, group_id: int = Form(...)):
    request.app.state.store.guide_unflag_field(field_id)
    return RedirectResponse(_group_url(group_id), status_code=303)


@router.post("/field/{field_id}/value")
async def set_field_value(request: Request, field_id: int,
                          value: str = Form(...), group_id: int = Form(...)):
    request.app.state.store.guide_set_field_value(field_id, value)
    return RedirectResponse(_group_url(group_id), status_code=303)


@router.post("/field/{field_id}/repair")
async def repair_field(request: Request, field_id: int, background_tasks: BackgroundTasks,
                       group_id: int = Form(...), note: str = Form("")):
    store = request.app.state.store
    ref = store.guide_field_ref(field_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="field not found")
    if not ref["source_crop_path"]:
        raise HTTPException(status_code=400, detail="此欄無來源切圖,無法 AI 修復")
    job_id = store.guide_create_repair_job(ref["guide_candidate_id"], ref["field_name"], note or None)
    background_tasks.add_task(run_repair_job, store, job_id)
    return JSONResponse({"job_id": job_id})


# ---------------------------------------------------------------------------
# 政見動作(組層級)
# ---------------------------------------------------------------------------

@router.post("/group/{group_id}/platform/flag")
async def flag_platform(request: Request, group_id: int, note: str = Form("")):
    request.app.state.store.guide_flag_platform(group_id, note)
    return RedirectResponse(_group_url(group_id), status_code=303)


@router.post("/group/{group_id}/platform/unflag")
async def unflag_platform(request: Request, group_id: int):
    request.app.state.store.guide_unflag_platform(group_id)
    return RedirectResponse(_group_url(group_id), status_code=303)


@router.post("/group/{group_id}/platform/value")
async def set_platform_value(request: Request, group_id: int, value: str = Form(...)):
    request.app.state.store.guide_set_platform_value(group_id, value)
    return RedirectResponse(_group_url(group_id), status_code=303)


@router.post("/group/{group_id}/platform/repair")
async def repair_platform(request: Request, group_id: int, background_tasks: BackgroundTasks,
                          note: str = Form("")):
    store = request.app.state.store
    ref = store.guide_platform_ref(group_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="platform not found")
    if not ref["source_crop_path"]:
        raise HTTPException(status_code=400, detail="政見無來源切圖,無法 AI 修復")
    job_id = store.guide_create_platform_repair_job(group_id, note or None)
    background_tasks.add_task(run_repair_job, store, job_id)
    return JSONResponse({"job_id": job_id})


@router.get("/repair/{job_id}/status")
async def repair_status(request: Request, job_id: int):
    job = request.app.state.store.guide_get_repair_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JSONResponse({
        "status": job["status"], "target": job["target"],
        "result_value": job["result_value"], "error": job["error"],
    })


# ---------------------------------------------------------------------------
# 照片動作 + 手動圈選補正(候選人層)
# ---------------------------------------------------------------------------

@router.post("/candidate/{candidate_id}/photo/flag")
async def flag_photo(request: Request, candidate_id: int,
                     note: str = Form(""), group_id: int = Form(...)):
    request.app.state.store.guide_flag_photo(candidate_id, note)
    return RedirectResponse(_group_url(group_id), status_code=303)


@router.post("/candidate/{candidate_id}/photo/unflag")
async def unflag_photo(request: Request, candidate_id: int, group_id: int = Form(...)):
    request.app.state.store.guide_unflag_photo(candidate_id)
    return RedirectResponse(_group_url(group_id), status_code=303)


@router.get("/candidate/{candidate_id}/crop")
async def crop_page(request: Request, candidate_id: int):
    ref = request.app.state.store.guide_candidate_pdf_ref(candidate_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    has_source = ref["source_page"] is not None and bool(ref["source_pdf_path"])
    return request.app.state.templates.TemplateResponse(
        request, "guide/crop.html",
        {"candidate_id": candidate_id, "has_source": has_source})


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
async def crop_submit(request: Request, candidate_id: int,
                      x0: float = Form(...), y0: float = Form(...),
                      x1: float = Form(...), y1: float = Form(...)):
    store = request.app.state.store
    ref = store.guide_candidate_pdf_ref(candidate_id)
    if ref is None or ref["source_page"] is None or not ref["source_pdf_path"]:
        raise HTTPException(status_code=400, detail="無來源 PDF/頁碼,無法圈選補照片")
    root = Path(request.app.state.root)
    out_dir = (root / "_out").resolve()
    # 就地覆蓋該候選人現有的照片檔(語意檔名);無現存照片才另存
    stored = ref.get("photo_path")
    dest = None
    if stored:
        p = Path(stored)
        cand = (p if p.is_absolute() else root / p).resolve()
        if _within(cand, out_dir):
            dest = cand
    if dest is None:
        dest = root / "_out" / "parsed" / "manual_photos" / f"cand_{candidate_id}.png"
    crop_photo_frac(ref["source_pdf_path"], ref["source_page"], (x0, y0, x1, y1), dest)
    store.guide_set_photo_path(candidate_id, str(dest))
    gid = store.guide_candidate_group_id(candidate_id)
    return RedirectResponse(_group_url(gid), status_code=303)


# ---------------------------------------------------------------------------
# Commit / 捨棄(組層級)
# ---------------------------------------------------------------------------

@router.post("/group/{group_id}/commit")
async def commit_group(request: Request, group_id: int, note: str = Form("")):
    request.app.state.store.guide_group_commit(group_id, note or None)
    return RedirectResponse(_group_url(group_id), status_code=303)


@router.post("/group/{group_id}/discard")
async def discard_group(request: Request, group_id: int):
    request.app.state.store.guide_group_discard(group_id)
    return RedirectResponse(_group_url(group_id), status_code=303)
