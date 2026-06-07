from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.webapp.bulletin import bulletin_url
from src.webapp.routes.elections import _election_tree
from src.webapp.store import Store

router = APIRouter()
logger = logging.getLogger(__name__)

_ISSUE_STATUS_ORDER = {
    "open": 0,
    "stale": 1,
    "resolved": 2,
    "ignored": 3,
}

_ISSUE_TYPE_FILTERS = (
    ("same_year_multiple", "同年多筆參選"),
    ("regional_jump", "跨地參選"),
    ("rank_downgrade", "參選較低位階"),
)
_ALL_ISSUE_TYPES = [key for key, _ in _ISSUE_TYPE_FILTERS]

_ELTYPE_FILTERS = (
    ("president", "President"),
    ("legislator", "Legislator"),
    ("mna", "MNA"),
    ("mayor", "Mayor"),
    ("council", "Council"),
    ("other", "Other"),
)
_ALL_ELTYPES = [key for key, _ in _ELTYPE_FILTERS]

_ELTYPE_KNOWN_TYPES: dict[str, set[str]] = {
    "president": {"國家元首_總統", "國家元首_副總統"},
    "legislator": {"立法委員"},
    "mna": {"國大代表"},
    "mayor": {"縣市首長"},
    "council": {"縣市議員"},
}
_ELTYPE_ALL_KNOWN = {t for types in _ELTYPE_KNOWN_TYPES.values() for t in types}


def _election_type_category(t: str) -> str:
    for category, types in _ELTYPE_KNOWN_TYPES.items():
        if t in types:
            return category
    return "other"

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
    if request.query_params.get("filtered") == "1":
        selected_types = [t for t in request.query_params.getlist("type") if t in _ALL_ISSUE_TYPES]
        selected_eltypes = [t for t in request.query_params.getlist("eltype") if t in _ALL_ELTYPES]
        request.session["check_filter"] = {"type": selected_types, "eltype": selected_eltypes}
    elif saved := request.session.get("check_filter"):
        params = urlencode(
            [("filtered", "1")]
            + [("type", t) for t in saved.get("type", _ALL_ISSUE_TYPES)]
            + [("eltype", t) for t in saved.get("eltype", _ALL_ELTYPES)],
        )
        return RedirectResponse(f"/identity-checks?{params}", status_code=302)
    else:
        selected_types = list(_ALL_ISSUE_TYPES)
        selected_eltypes = list(_ALL_ELTYPES)

    issue_rows = store.list_identity_check_issues()
    issues, summary = _prepare_identity_check_index(issue_rows)
    issues = [issue for issue in issues if issue["status"] != "stale"]
    selected_set = set(selected_types)
    issues = [issue for issue in issues if issue["issue_types"] & selected_set]
    selected_eltype_set = set(selected_eltypes)
    issues = [issue for issue in issues if _issue_matches_eltypes(issue, selected_eltype_set)]
    return templates.TemplateResponse(request, "identity_checks.html", {
        "app_mode": "check",
        "election_tree": _election_tree(root, store),
        "selected_id": None,
        "issues": issues,
        "issue_summary": summary,
        "type_filters": _ISSUE_TYPE_FILTERS,
        "selected_types": selected_types,
        "eltype_filters": _ELTYPE_FILTERS,
        "selected_eltypes": selected_eltypes,
        "operations": store.list_identity_fix_operations(limit=20),
        "generated_count": request.query_params.get("generated"),
    })


@router.post("/identity-checks/scan")
async def scan_identity_checks(request: Request):
    store: Store = request.app.state.store
    count = store.refresh_identity_check_issues()
    logger.info("identity-check scan generated=%d", count)
    return RedirectResponse(f"/identity-checks?{urlencode({'generated': count})}", status_code=303)


@router.get("/identity-checks/{issue_id:int}")
async def identity_check_detail(request: Request, issue_id: int):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates
    detail = store.get_identity_check_detail(issue_id)
    if detail is None:
        return RedirectResponse("/identity-checks", status_code=303)
    _prepare_identity_check_detail(detail)

    issue_rows = store.list_identity_check_issues()
    all_groups, _ = _prepare_identity_check_index(issue_rows)
    nav_groups = [g for g in all_groups if g["status"] != "stale"]
    current_candidate_id = detail["candidate"]["id"]
    current_pos = next((i for i, g in enumerate(nav_groups) if g["candidate_id"] == current_candidate_id), None)
    prev_issue_id = nav_groups[current_pos - 1]["id"] if current_pos is not None and current_pos > 0 else None
    next_issue_id = nav_groups[current_pos + 1]["id"] if current_pos is not None and current_pos < len(nav_groups) - 1 else None

    return templates.TemplateResponse(request, "identity_check_detail.html", {
        "app_mode": "check",
        "election_tree": _election_tree(root, store),
        "selected_id": None,
        "detail": detail,
        "selected_source_record_ids": [],
        "preview": None,
        "error": request.query_params.get("error", ""),
        "prev_issue_id": prev_issue_id,
        "next_issue_id": next_issue_id,
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
        "selected_source_record_ids": source_record_ids,
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
    year_source_counts: dict[tuple[str, str], int] = {}
    for record in records:
        key = (
            _display_compare_value("year", record.get("year")),
            str(record.get("election_id") or ""),
        )
        if key[0] and key[1]:
            year_source_counts[key] = year_source_counts.get(key, 0) + 1

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
        year_source_key = (
            _display_compare_value("year", record.get("year")),
            str(record.get("election_id") or ""),
        )
        record["duplicate_year_source"] = year_source_counts.get(year_source_key, 0) > 1
        record["compare_fields"] = [
            {
                "key": field,
                "label": _COMPARE_LABELS[field],
                "value": _display_compare_value(field, record.get(field)),
                "class": _compare_field_class(
                    field,
                    _display_compare_value(field, record.get(field)),
                    value_classes,
                ),
            }
            for field in _COMPARE_FIELDS
        ]
        record["bulletin_url"] = bulletin_url(record, record.get("election_id") or "")


def _issue_matches_eltypes(group: dict, selected: set[str]) -> bool:
    if not selected:
        return False
    for t in group.get("candidate_election_types") or []:
        if _election_type_category(t) in selected:
            return True
    return False


def _prepare_identity_check_index(issues: list[dict]) -> tuple[list[dict], dict[str, int]]:
    grouped: dict[str, dict] = {}
    summary = {
        "open": 0,
        "open_critical": 0,
        "open_warning": 0,
        "stale": 0,
        "resolved": 0,
        "ignored": 0,
        "total": 0,
    }

    for issue in issues:
        candidate_id = issue["candidate_id"]
        group = grouped.get(candidate_id)
        if group is None:
            group = {
                "id": issue["id"],
                "candidate_id": candidate_id,
                "candidate_name": issue.get("name") or "",
                "status": issue["status"],
                "status_label": issue["status_label"],
                "severity": issue["severity"],
                "severity_label": _index_severity_label(issue["severity"]),
                "reason_text": issue["summary"],
                "issue_types": {issue["issue_type"]},
                "candidate_election_types": list(issue.get("candidate_election_types") or []),
                "_sort_key": _index_issue_sort_key(issue),
            }
            grouped[candidate_id] = group
        else:
            group["reason_text"] = f"{group['reason_text']}; {issue['summary']}"
            group["issue_types"].add(issue["issue_type"])
            current_sort = _index_issue_sort_key(issue)
            if current_sort < group["_sort_key"]:
                group["id"] = issue["id"]
                group["status"] = issue["status"]
                group["status_label"] = issue["status_label"]
                group["severity"] = issue["severity"]
                group["severity_label"] = _index_severity_label(issue["severity"])
                group["_sort_key"] = current_sort
            if issue["severity"] == "critical":
                group["severity"] = "critical"
                group["severity_label"] = "必審"

    rows = sorted(grouped.values(), key=lambda item: item["_sort_key"])
    for row in rows:
        row.pop("_sort_key", None)
        summary[row["status"]] += 1
        if row["status"] == "open":
            summary["open_critical" if row["severity"] == "critical" else "open_warning"] += 1
    summary["total"] = len(rows)
    return rows, summary


def _index_issue_sort_key(issue: dict) -> tuple[int, int, int, int]:
    status_order = _ISSUE_STATUS_ORDER.get(issue.get("status"), 99)
    severity_order = 0 if issue.get("severity") == "critical" else 1
    updated = issue.get("updated_at")
    updated_order = -int(updated.timestamp()) if hasattr(updated, "timestamp") else 0
    issue_id = int(issue.get("id") or 0)
    return (status_order, severity_order, updated_order, issue_id)


def _index_severity_label(severity: str) -> str:
    return "必審" if severity == "critical" else "提醒"


def _display_compare_value(field: str, value) -> str:
    if value is None or value == "":
        return ""
    if field == "elected":
        return "當選" if value in (1, True, "1", "true", "True", "*") else "未當選"
    return str(value)


def _compare_field_class(field: str, value: str, value_classes: dict[tuple[str, str], str]) -> str:
    if not value:
        return ""
    if field == "year":
        return "compare-plain"
    if field == "elected":
        return "compare-elected" if value == "當選" else "compare-not-elected"
    return value_classes.get((field, value), "")
