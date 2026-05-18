from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.webapp.bulletin import bulletin_url
from src.webapp.routes.elections import _election_tree
from src.webapp.store import Store

router = APIRouter()
logger = logging.getLogger(__name__)

_COMPARE_FIELDS = ("year", "type", "region", "party", "elected")
_COMPARE_LABELS = {
    "year": "年份",
    "type": "選舉類別",
    "region": "區域",
    "party": "黨籍",
    "elected": "當選",
}


@router.get("/identity-checks")
async def identity_checks_index(request: Request):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates
    issues = store.list_identity_check_issues()
    return templates.TemplateResponse(request, "identity_checks.html", {
        "app_mode": "check",
        "election_tree": _election_tree(root, store),
        "selected_id": None,
        "issues": issues,
        "operations": store.list_identity_fix_operations(limit=20),
        "generated_count": request.query_params.get("generated"),
    })


@router.post("/identity-checks/scan")
async def scan_identity_checks(request: Request):
    store: Store = request.app.state.store
    count = store.refresh_identity_check_issues()
    logger.info("identity-check scan generated=%d", count)
    return RedirectResponse(f"/identity-checks?generated={count}", status_code=303)


@router.get("/identity-checks/{issue_id:int}")
async def identity_check_detail(request: Request, issue_id: int):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates
    detail = store.get_identity_check_detail(issue_id)
    if detail is None:
        return RedirectResponse("/identity-checks", status_code=303)
    _prepare_identity_check_detail(detail)
    return templates.TemplateResponse(request, "identity_check_detail.html", {
        "app_mode": "check",
        "election_tree": _election_tree(root, store),
        "selected_id": None,
        "detail": detail,
        "preview": None,
        "error": request.query_params.get("error", ""),
    })


@router.post("/identity-checks/{issue_id:int}/preview")
async def preview_identity_fix(
    request: Request,
    issue_id: int,
    action: str = Form(...),
    source_record_ids: list[str] = Form(default=[]),
    target_candidate_id: str = Form(default=""),
):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates
    detail = store.get_identity_check_detail(issue_id)
    if detail is None:
        return RedirectResponse("/identity-checks", status_code=303)
    _prepare_identity_check_detail(detail)
    if not source_record_ids:
        return RedirectResponse(f"/identity-checks/{issue_id}?error={quote('請至少選擇一筆 election')}", status_code=303)

    preview = store.preview_identity_fix(
        issue_id=issue_id,
        action=action,
        source_record_ids=source_record_ids,
        target_candidate_id=target_candidate_id or None,
    )
    if preview.get("error"):
        return RedirectResponse(f"/identity-checks/{issue_id}?error={quote(preview['error'])}", status_code=303)

    return templates.TemplateResponse(request, "identity_check_detail.html", {
        "app_mode": "check",
        "election_tree": _election_tree(root, store),
        "selected_id": None,
        "detail": detail,
        "preview": preview,
        "error": "",
    })


@router.post("/identity-checks/{issue_id:int}/apply")
async def apply_identity_fix(
    request: Request,
    issue_id: int,
    action: str = Form(...),
    source_record_ids: list[str] = Form(default=[]),
    target_candidate_id: str = Form(default=""),
):
    store: Store = request.app.state.store
    if not source_record_ids:
        return RedirectResponse(f"/identity-checks/{issue_id}?error={quote('請至少選擇一筆 election')}", status_code=303)
    try:
        operation_id = store.apply_identity_fix(
            issue_id=issue_id,
            action=action,
            source_record_ids=source_record_ids,
            target_candidate_id=target_candidate_id or None,
        )
    except ValueError as exc:
        return RedirectResponse(f"/identity-checks/{issue_id}?error={quote(str(exc))}", status_code=303)
    logger.info("identity-fix issue=%d operation=%d action=%s", issue_id, operation_id, action)
    return RedirectResponse(f"/identity-checks/{issue_id}", status_code=303)


@router.post("/identity-checks/{issue_id:int}/ignore")
async def ignore_identity_check(request: Request, issue_id: int):
    store: Store = request.app.state.store
    store.update_identity_check_status(issue_id, "ignored")
    return RedirectResponse("/identity-checks", status_code=303)


def _prepare_identity_check_detail(detail: dict) -> None:
    records = detail.get("records", [])
    value_classes: dict[tuple[str, str], str] = {}
    for field in _COMPARE_FIELDS:
        values = sorted({
            _display_compare_value(field, record.get(field))
            for record in records
            if _display_compare_value(field, record.get(field))
        })
        for index, value in enumerate(values):
            value_classes[(field, value)] = f"compare-token-{(index % 8) + 1}"

    for record in records:
        record["compare_fields"] = [
            {
                "key": field,
                "label": _COMPARE_LABELS[field],
                "value": _display_compare_value(field, record.get(field)),
                "class": value_classes.get((field, _display_compare_value(field, record.get(field))), ""),
            }
            for field in _COMPARE_FIELDS
        ]
        record["bulletin_url"] = bulletin_url(record, record.get("election_id") or "")


def _display_compare_value(field: str, value) -> str:
    if value is None or value == "":
        return ""
    if field == "elected":
        return "當選" if value in (1, True, "1", "true", "True", "*") else "未當選"
    return str(value)
