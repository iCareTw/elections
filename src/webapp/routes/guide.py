from __future__ import annotations

import io
import logging
import threading
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from src.voter_guide.guide_crop import crop_photo_frac, render_page
from src.voter_guide.guide_repair import run_repair_job

router = APIRouter(prefix="/guide")
logger = logging.getLogger(__name__)


def _group_url(group_id: int) -> str:
    return f"/guide/group/{group_id}"


@router.get("")
async def guide_home(request: Request):
    store = request.app.state.store
    return request.app.state.templates.TemplateResponse(request, "guide/index.html", {
        "app_mode": "guide",
        "tree": store.guide_tree(),
        "selected_election_id": None,
        "candidates": None,
        "selected_group_id": None,
    })


@router.get("/election/{election_id}")
async def guide_election(request: Request, election_id: str):
    store = request.app.state.store
    candidates = store.guide_candidates_of(election_id)
    if candidates:
        return RedirectResponse(_group_url(candidates[0]["guide_group_id"]), status_code=303)
    return request.app.state.templates.TemplateResponse(request, "guide/index.html", {
        "app_mode": "guide",
        "tree": store.guide_tree(),
        "selected_election_id": election_id,
        "candidates": candidates,
        "selected_group_id": None,
    })


# ---------------------------------------------------------------------------
# 匯入公報 PDF(選現有檔 → 背景解析 + 載入)
# ---------------------------------------------------------------------------

def _list_pdfs(root: Path, imported: dict[str, str],
               jobs: dict[str, dict]) -> list[dict]:
    """列出 _data/voter_guide/ 下可匯入的公報 PDF(目前解析器支援總統)。新到舊排序。

    每列自帶最新狀態(已匯入 / 排隊中 / 解析中 / 上次失敗),讓清單本身就是現況。
    """
    base = root / "_data" / "voter_guide"
    out = []
    for pdf in sorted(base.glob("president/*.pdf"), reverse=True):
        rp = str(pdf.resolve())
        job = jobs.get(rp) or {}
        status = job.get("status") or ""
        total = job.get("total") or 0
        done = job.get("done") or 0
        finished = job.get("finished_at")
        out.append({
            "path": str(pdf.relative_to(root)), "name": pdf.stem,
            "type": "president",
            "imported": rp in imported,
            "election_id": imported.get(rp),
            "active": status in ("queued", "running"),
            "status": status,
            "message": job.get("message") or "",
            "pct": round(done / total * 100) if total else 0,
            # 失敗訊息附上日期:一眼看出是舊紀錄還是剛剛的結果
            "error": job.get("error") or "" if status == "failed" else "",
            "when": f"{finished.month}/{finished.day}" if finished else "",
        })
    return out


# --- 單一背景 worker:依序處理佇列中的匯入工作 ---------------------------------
_worker_lock = threading.Lock()
_worker_running = False


def _process_import_job(store, job: dict) -> None:
    job_id = job["id"]
    p = job["pdf_path"]

    def prog(msg, done, total):
        store.guide_update_import_progress(job_id, msg, done, total)
    try:
        from src.voter_guide.guide_import import import_pdf
        eid = import_pdf(store, p, progress=prog)
        store.guide_finish_import_job(job_id, status="done", message="完成",
                                      election_id=eid)
    except Exception as exc:  # noqa: BLE001 - 任何失敗都回報給前端
        logger.error("import failed: %s", exc, exc_info=True)
        store.guide_finish_import_job(job_id, status="failed", error=str(exc))


def _import_worker(store) -> None:
    global _worker_running
    while True:
        job = store.guide_claim_next_import_job()
        if job is None:
            with _worker_lock:
                job = store.guide_claim_next_import_job()  # 上鎖內再確認,避免漏接
                if job is None:
                    _worker_running = False
                    return
        _process_import_job(store, job)


def _ensure_import_worker(store) -> None:
    """確保佇列 worker 正在執行(單一實例)。"""
    global _worker_running
    with _worker_lock:
        if _worker_running:
            return
        _worker_running = True
    threading.Thread(target=_import_worker, args=(store,), daemon=True).start()


@router.get("/import")
async def import_page(request: Request):
    store = request.app.state.store
    from src.voter_guide.vision import endpoint_available, BASE_URL
    return request.app.state.templates.TemplateResponse(request, "guide/import.html", {
        "app_mode": "guide",
        "tree": store.guide_tree(),
        "selected_election_id": None,
        "candidates": None,
        "selected_group_id": None,
        "pdfs": _list_pdfs(Path(request.app.state.root),
                           store.guide_imported_pdf_map(),
                           store.guide_latest_import_by_path()),
        "model_ok": endpoint_available(),
        "model_url": BASE_URL,
    })


@router.get("/import/model-status")
async def import_model_status(request: Request):
    """前端可重新檢查本機視覺模型是否已啟動。"""
    from src.voter_guide.vision import endpoint_available, BASE_URL
    return JSONResponse({"ok": endpoint_available(), "url": BASE_URL})


@router.get("/import/pdf")
async def import_pdf_view(request: Request, path: str):
    """直接檢視待匯入的本地公報 PDF(限 _data/voter_guide 目錄內)。"""
    root = Path(request.app.state.root)
    base = (root / "_data" / "voter_guide").resolve()
    p = Path(path)
    p = (p if p.is_absolute() else root / p).resolve()
    if not _within(p, base) or not p.is_file():
        raise HTTPException(status_code=404, detail="PDF 不在允許的公報目錄")
    return FileResponse(str(p), media_type="application/pdf",
                        content_disposition_type="inline")


@router.get("/import/jobs")
async def import_jobs(request: Request):
    """各公報最新狀態(供匯入頁輪詢更新清單各列),欄位與初次渲染一致。"""
    store = request.app.state.store
    rows = _list_pdfs(Path(request.app.state.root),
                      store.guide_imported_pdf_map(),
                      store.guide_latest_import_by_path())
    return JSONResponse({"rows": rows})


@router.post("/import")
async def import_start(request: Request, pdf: str = Form(...)):
    root = Path(request.app.state.root)
    base = (root / "_data" / "voter_guide").resolve()
    p = Path(pdf)
    p = (p if p.is_absolute() else root / p).resolve()
    if not _within(p, base) or not p.is_file():
        raise HTTPException(status_code=400, detail="PDF 不在允許的公報目錄")

    store = request.app.state.store
    rp = str(p.resolve())
    if rp in store.guide_imported_pdf_paths():
        raise HTTPException(status_code=409, detail="這份公報已匯入過")
    if rp in store.guide_active_import_paths():
        raise HTTPException(status_code=409, detail="這份公報已在佇列中")
    from src.voter_guide.vision import endpoint_available, BASE_URL
    if not endpoint_available():
        raise HTTPException(status_code=503,
                            detail=f"本機視覺模型未啟動({BASE_URL})。請先啟動模型再匯入。")
    job_id = store.guide_create_import_job(str(p), p.stem)
    _ensure_import_worker(store)
    return JSONResponse({"job_id": job_id})


@router.get("/import/status/{job_id}")
async def import_status(request: Request, job_id: int):
    job = request.app.state.store.guide_get_import_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JSONResponse({
        "status": job["status"], "message": job["message"],
        "done": job["done"], "total": job["total"],
        "election_id": job["election_id"], "error": job["error"],
    })


@router.get("/import/active")
async def import_active(request: Request):
    """全站側欄常駐指示用:目前是否有進行中的匯入。"""
    job = request.app.state.store.guide_active_import_job()
    if job is None:
        return JSONResponse({"active": False})
    return JSONResponse({
        "active": True, "job_id": job["id"], "message": job["message"],
        "done": job["done"], "total": job["total"],
        "pdf_name": job["pdf_name"], "queued_count": job.get("queued_count", 0),
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
        "app_mode": "guide",
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
# 手動圈選補正照片(候選人層)
# ---------------------------------------------------------------------------

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
    ident = store.guide_candidate_identity(candidate_id)
    if ref is None or ident is None or ref["source_page"] is None or not ref["source_pdf_path"]:
        raise HTTPException(status_code=400, detail="無來源 PDF/頁碼,無法圈選補照片")
    root = Path(request.app.state.root)
    # 存到解析器不會碰的獨立目錄,並以穩定鍵(選舉+號次+角色)登記 → 重載/重解析都保留
    dest = (root / "_out" / "guide_manual" / ident["election_id"]
            / f"ticket{ident['ticket']}_{ident['role']}.png").resolve()
    crop_photo_frac(ref["source_pdf_path"], ref["source_page"], (x0, y0, x1, y1), dest)
    store.guide_upsert_manual_photo(ident["election_id"], ident["ticket"], ident["role"], str(dest))
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
