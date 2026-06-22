from __future__ import annotations

from src.webapp.identity_checks import find_identity_check_issues, region_root
from src.webapp.routes.identity_checks import _compute_summary, _prepare_identity_check_index


def test_find_identity_check_issues_detects_same_year_multiple() -> None:
    issues = find_identity_check_issues([
        {
            "id": "id_劉煜基_1946",
            "name": "劉煜基",
            "birthyear": 1946,
            "elections": [
                {
                    "source_record_id": "legislator:1",
                    "year": 1998,
                    "type": "立法委員",
                    "region": "屏東縣選舉區",
                    "elected": 0,
                },
                {
                    "source_record_id": "council:1",
                    "year": 1998,
                    "type": "縣市議員",
                    "region": "屏東縣 第03選舉區",
                    "elected": 0,
                },
            ],
        }
    ])

    assert [issue["issue_type"] for issue in issues] == ["same_year_multiple"]
    assert issues[0]["severity"] == "critical"
    assert issues[0]["source_record_ids"] == ["legislator:1", "council:1"]


def test_find_identity_check_issues_detects_downgrade_after_elected() -> None:
    issues = find_identity_check_issues([
        {
            "id": "id_測試人_1970",
            "name": "測試人",
            "birthyear": 1970,
            "elections": [
                {
                    "source_record_id": "legislator:1",
                    "year": 2016,
                    "type": "立法委員",
                    "region": "臺北市 第04選舉區",
                    "elected": 1,
                },
                {
                    "source_record_id": "council:1",
                    "year": 2022,
                    "type": "縣市議員",
                    "region": "臺北市 第02選舉區",
                    "elected": 1,
                },
            ],
        }
    ])

    assert [issue["issue_type"] for issue in issues] == ["rank_downgrade"]


def test_region_root_treats_county_city_renames_as_same_region() -> None:
    assert region_root("臺北縣 第05選舉區") == "新北市"
    assert region_root("新北市 第03選舉區") == "新北市"


def test_prepare_identity_check_index_groups_issues_by_candidate() -> None:
    issues = [
        {
            "id": 1,
            "candidate_id": "id_陳美玲_1965",
            "name": "陳美玲",
            "status": "open",
            "status_label": "待審",
            "severity": "critical",
            "issue_type": "same_year_multiple",
            "summary": "1998 年有 2 筆參選紀錄",
            "candidate_election_types": ["立法委員"],
            "updated_at": None,
        },
        {
            "id": 2,
            "candidate_id": "id_陳美玲_1965",
            "name": "陳美玲",
            "status": "open",
            "status_label": "待審",
            "severity": "warning",
            "issue_type": "regional_jump",
            "summary": "2002 年有 1 筆參選紀錄",
            "candidate_election_types": ["立法委員"],
            "updated_at": None,
        },
        {
            "id": 3,
            "candidate_id": "id_陳小華_1970",
            "name": "陳小華",
            "status": "stale",
            "status_label": "已過期",
            "severity": "warning",
            "issue_type": "rank_downgrade",
            "summary": "2010 年的問題已失效",
            "candidate_election_types": ["縣市議員"],
            "updated_at": None,
        },
    ]

    rows, _ = _prepare_identity_check_index(issues)

    assert len(rows) == 2
    assert rows[0]["candidate_id"] == "id_陳美玲_1965"
    assert rows[0]["reason_text"] == "1998 年有 2 筆參選紀錄; 2002 年有 1 筆參選紀錄"
    assert rows[0]["severity_label"] == "必審"

    visible_rows = [row for row in rows if row["status"] != "stale"]
    assert len(visible_rows) == 1


def test_compute_summary_reflects_filtered_groups() -> None:
    groups = [
        {"status": "open", "severity": "critical"},
        {"status": "open", "severity": "warning"},
        {"status": "stale", "severity": "warning"},
        {"status": "ignored", "severity": "warning"},
    ]
    summary = _compute_summary(groups)
    assert summary == {
        "open": 2,
        "open_critical": 1,
        "open_warning": 1,
        "stale": 1,
        "resolved": 0,
        "ignored": 1,
        "total": 4,
    }


def test_compute_summary_empty() -> None:
    assert _compute_summary([]) == {
        "open": 0,
        "open_critical": 0,
        "open_warning": 0,
        "stale": 0,
        "resolved": 0,
        "ignored": 0,
        "total": 0,
    }
