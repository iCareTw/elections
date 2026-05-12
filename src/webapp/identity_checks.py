from __future__ import annotations

from collections import defaultdict
from typing import Any


LOCAL_TYPES = {"村里長", "鄉鎮市長", "縣市議員", "縣市首長"}
TYPE_RANK = {
    "村里長": 1,
    "鄉鎮市長": 2,
    "縣市議員": 3,
    "縣市首長": 4,
    "立法委員": 4,
    "國家元首_副總統": 5,
    "國家元首_總統": 5,
}
REGION_ALIASES = {
    "臺北縣": "新北市",
    "桃園縣": "桃園市",
    "臺中縣": "臺中市",
    "臺南縣": "臺南市",
    "高雄縣": "高雄市",
}


def region_root(region: str | None) -> str:
    if not region:
        return ""
    root = region.split(" ", 1)[0]
    if root.endswith("選舉區"):
        root = root.removesuffix("選舉區")
    return REGION_ALIASES.get(root, root)


def find_identity_check_issues(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for candidate in candidates:
        elections = sorted(
            candidate.get("elections", []),
            key=lambda e: (e.get("year") or 0, e.get("type") or "", e.get("region") or ""),
        )
        issues.extend(_same_year_issues(candidate, elections))
        downgrade = _rank_downgrade_issue(candidate, elections)
        if downgrade:
            issues.append(downgrade)
        regional = _regional_jump_issue(candidate, elections)
        if regional:
            issues.append(regional)
    return issues


def _same_year_issues(candidate: dict[str, Any], elections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for election in elections:
        year = election.get("year")
        if year is not None:
            by_year[int(year)].append(election)

    issues = []
    for year, items in by_year.items():
        if len(items) < 2:
            continue
        refs = _refs(items)
        issues.append({
            "issue_key": f"same_year_multiple:{candidate['id']}:{year}",
            "candidate_id": candidate["id"],
            "issue_type": "same_year_multiple",
            "severity": "critical",
            "summary": f"{candidate['name']} 在 {year} 年有 {len(items)} 筆參選紀錄",
            "source_record_ids": [r["source_record_id"] for r in refs],
            "election_refs": refs,
        })
    return issues


def _rank_downgrade_issue(candidate: dict[str, Any], elections: list[dict[str, Any]]) -> dict[str, Any] | None:
    refs_by_id: dict[str, dict[str, Any]] = {}
    for earlier in elections:
        if earlier.get("elected") != 1:
            continue
        earlier_rank = TYPE_RANK.get(str(earlier.get("type")))
        earlier_year = earlier.get("year")
        if earlier_rank is None or earlier_year is None:
            continue
        for later in elections:
            later_rank = TYPE_RANK.get(str(later.get("type")))
            later_year = later.get("year")
            if later_rank is None or later_year is None or later_year <= earlier_year:
                continue
            if later_rank < earlier_rank:
                refs_by_id[earlier["source_record_id"]] = _ref(earlier)
                refs_by_id[later["source_record_id"]] = _ref(later)

    refs = sorted(refs_by_id.values(), key=lambda r: (r.get("year") or 0, r.get("type") or ""))
    if not refs:
        return None
    return {
        "issue_key": f"rank_downgrade:{candidate['id']}",
        "candidate_id": candidate["id"],
        "issue_type": "rank_downgrade",
        "severity": "warning",
        "summary": f"{candidate['name']} 有當選後往較低位階參選的紀錄",
        "source_record_ids": [r["source_record_id"] for r in refs],
        "election_refs": refs,
    }


def _regional_jump_issue(candidate: dict[str, Any], elections: list[dict[str, Any]]) -> dict[str, Any] | None:
    local = [e for e in elections if e.get("type") in LOCAL_TYPES]
    roots = {region_root(e.get("region")) for e in local}
    roots.discard("")
    if len(roots) < 2:
        return None
    refs = _refs(local)
    return {
        "issue_key": f"regional_jump:{candidate['id']}",
        "candidate_id": candidate["id"],
        "issue_type": "regional_jump",
        "severity": "warning",
        "summary": f"{candidate['name']} 有跨地區地方選舉紀錄",
        "source_record_ids": [r["source_record_id"] for r in refs],
        "election_refs": refs,
    }


def _refs(elections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_ref(e) for e in elections if e.get("source_record_id")]


def _ref(election: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_record_id": election["source_record_id"],
        "election_id": election.get("election_id"),
        "year": election.get("year"),
        "type": election.get("type"),
        "region": election.get("region"),
        "party": election.get("party"),
        "elected": election.get("elected"),
        "session": election.get("session"),
    }
