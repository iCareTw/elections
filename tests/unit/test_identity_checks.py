from __future__ import annotations

from src.webapp.identity_checks import find_identity_check_issues, region_root
from src.webapp.routes.identity_checks import _prepare_identity_check_index


def test_find_identity_check_issues_detects_same_year_multiple() -> None:
    issues = find_identity_check_issues([
        {
            "id": "id_劉煜基_1946",
            "name": "劉煜基",
            "birthday": 1946,
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
            "birthday": 1970,
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


def test_prepare_identity_check_index_groups_issues_by_candidate_and_hides_expired() -> None:
    issues = [
        {
            "id": 1,
            "candidate_id": "id_陳美玲_1965",
            "name": "陳美玲",
            "status": "open",
            "status_label": "待審",
            "severity": "critical",
            "summary": "1998 年有 2 筆參選紀錄",
        },
        {
            "id": 2,
            "candidate_id": "id_陳美玲_1965",
            "name": "陳美玲",
            "status": "open",
            "status_label": "待審",
            "severity": "warning",
            "summary": "2002 年有 1 筆參選紀錄",
        },
        {
            "id": 3,
            "candidate_id": "id_陳小華_1970",
            "name": "陳小華",
            "status": "stale",
            "status_label": "已過期",
            "severity": "warning",
            "summary": "2010 年的問題已失效",
        },
    ]

    rows, summary = _prepare_identity_check_index(issues)

    assert len(rows) == 2
    assert rows[0]["candidate_id"] == "id_陳美玲_1965"
    assert rows[0]["reason_text"] == "1998 年有 2 筆參選紀錄; 2002 年有 1 筆參選紀錄"
    assert rows[0]["severity_label"] == "必審"
    assert summary == {
        "critical": 1,
        "warning": 1,
        "open": 1,
        "stale": 1,
        "resolved": 0,
        "ignored": 0,
        "total": 2,
    }

    visible_rows = [row for row in rows if row["status"] != "stale"]
    assert len(visible_rows) == 1
