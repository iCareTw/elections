from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

import src.webapp.app as app_module
from src.webapp.app import create_app
from src.webapp.routes.elections import _election_tree
from src.webapp.store import Store, load_database_config


def _make_app(tmp_path: Path, store: Store):
    app = create_app(root=tmp_path)
    app.state.store = store
    return app


def test_reset_confirm_route_is_not_captured_by_election_detail(tmp_path: Path) -> None:
    class ReadOnlyStore:
        def list_elections(self) -> list[dict]:
            return []

    election_path = tmp_path / "_data" / "councilor" / "2005" / "縣市議員_區域_臺東縣.xlsx"
    election_path.parent.mkdir(parents=True)
    election_path.write_text("")

    app = _make_app(tmp_path, ReadOnlyStore())  # type: ignore[arg-type]
    client = TestClient(app, raise_server_exceptions=True)

    resp = client.get(
        "/elections/councilor/2005/縣市議員_區域_臺東縣.xlsx/reset-confirm",
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert "YES，移除" in resp.text
    assert "NO，返回" in resp.text


def test_app_startup_prepares_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    events: list[str] = []

    class FakeStore:
        def open(self) -> None:
            events.append("open")

        def init_schema(self) -> None:
            events.append("init_schema")

        def close(self) -> None:
            events.append("close")

    monkeypatch.setattr(app_module, "Store", FakeStore)

    with TestClient(app_module.create_app(root=tmp_path)):
        assert events == ["open", "init_schema"]

    assert events == ["open", "init_schema", "close"]


def test_election_tree_does_not_write_discovered_elections(tmp_path: Path) -> None:
    class ReadOnlyStore:
        def upsert_election(self, election: dict) -> None:
            raise AssertionError("GET navigator must not write elections")

        def list_elections(self) -> list[dict]:
            return []

    election_path = tmp_path / "_data" / "president" / "第16任總統副總統選舉.xlsx"
    election_path.parent.mkdir(parents=True)
    election_path.write_text("")

    tree = _election_tree(tmp_path, ReadOnlyStore())  # type: ignore[arg-type]

    assert tree["children"]["president"]["children"]["第16任總統副總統選舉.xlsx"]["kind"] == "election"


def test_election_tree_counts_pending_commit_descendants(tmp_path: Path) -> None:
    class ReadOnlyStore:
        def list_elections(self) -> list[dict]:
            return [
                {"election_id": "councilor/1998/未完成.xlsx", "status": "todo"},
                {"election_id": "councilor/2022/已完成.xlsx", "status": "done"},
            ]

    for path in (
        tmp_path / "_data" / "councilor" / "1998" / "未完成.xlsx",
        tmp_path / "_data" / "councilor" / "2022" / "已完成.xlsx",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    tree = _election_tree(tmp_path, ReadOnlyStore())  # type: ignore[arg-type]

    councilor = tree["children"]["councilor"]
    assert councilor["pending_commit_count"] == 1
    assert councilor["children"]["1998"]["pending_commit_count"] == 1
    assert councilor["children"]["2022"]["pending_commit_count"] == 0


def test_navigator_does_not_expand_unselected_top_level_dirs() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("elections.html")
    election_tree = {
        "children": {
            "president": {
                "kind": "dir",
                "path": "president",
                "pending_commit_count": 1,
                "children": {
                    "第16任總統副總統選舉.xlsx": {
                        "kind": "election",
                        "data": {
                            "election_id": "president/第16任總統副總統選舉.xlsx",
                            "label": "第16任總統副總統選舉.xlsx",
                            "status": "todo",
                        },
                    },
                },
            },
            "mayor": {
                "kind": "dir",
                "path": "mayor",
                "pending_commit_count": 1,
                "children": {
                    "111年直轄市長選舉.xlsx": {
                        "kind": "election",
                        "data": {
                            "election_id": "mayor/111年直轄市長選舉.xlsx",
                            "label": "111年直轄市長選舉.xlsx",
                            "status": "todo",
                        },
                    },
                },
            },
            "legislator": {
                "kind": "dir",
                "path": "legislator",
                "pending_commit_count": 1,
                "children": {
                    "party-list-legislator": {
                        "kind": "dir",
                        "path": "legislator/party-list-legislator",
                        "pending_commit_count": 1,
                        "children": {
                            "11th.yaml": {
                                "kind": "election",
                                "data": {
                                    "election_id": "legislator/party-list-legislator/11th.yaml",
                                    "label": "11th.yaml",
                                    "status": "todo",
                                },
                            },
                        },
                    },
                },
            },
        },
    }

    home_html = template.render(
        election_tree=election_tree,
        selected_id=None,
        election=None,
    )
    selected_html = template.render(
        election_tree=election_tree,
        selected_id="president/第16任總統副總統選舉.xlsx",
        election=None,
    )

    assert home_html.count('class="tree-node dir" open') == 0
    assert 'onclick="goHome()"' in home_html
    assert 'title="Home">⌂</button>' in home_html
    assert 'onclick="collapseAll()"' not in home_html
    assert 'id="build-form"' in home_html
    assert 'id="build-busy-overlay"' in home_html
    assert "產生 candidates.yaml 中, 請稍候" in home_html
    assert selected_html.count('class="tree-node dir" open') == 1
    assert '<span class="tree-dir-label">president</span>' in selected_html
    assert '<span class="badge badge-pending tree-dir-pending">1</span>' in selected_html
    assert "Identity UI" in home_html
    assert "Identity Check" in home_html


def test_election_detail_template_handles_review_status() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("elections.html")

    html = template.render(
        election_tree={"children": {}},
        selected_id="president/第09任總統副總統選舉.xlsx",
        election={
            "election_id": "president/第09任總統副總統選舉.xlsx",
            "type": "president",
            "year": 1996,
            "label": "第09任總統副總統選舉",
            "status": "review",
        },
    )

    assert "此選舉正在審核" in html
    assert "/review/president/" in html


def test_election_detail_template_handles_ready_status() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("elections.html")

    html = template.render(
        election_tree={"children": {}},
        selected_id="president/第16任總統副總統選舉.xlsx",
        election={
            "election_id": "president/第16任總統副總統選舉.xlsx",
            "type": "president",
            "year": 2024,
            "label": "第16任總統副總統選舉",
            "status": "ready",
            "imported_count": 6,
        },
    )

    assert "尚未正式提交" in html
    assert "/review/president/" in html


def test_done_template_shows_all_committed_resolutions() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("elections.html")

    html = template.render(
        election_tree={"children": {}},
        selected_id="legislator/by-election-legislator/7th/第7屆立法委員臺東縣補選.xlsx",
        election={
            "election_id": "legislator/by-election-legislator/7th/第7屆立法委員臺東縣補選.xlsx",
            "type": "legislator-by-election",
            "year": None,
            "label": "第7屆立法委員臺東縣補選",
            "status": "done",
        },
        resolutions=[
            {
                "name": "洪銘堅",
                "mode": "new",
                "mode_label": "自動建立",
                "candidate_id": "id_洪銘堅_1953",
            },
            {
                "name": "賴坤成",
                "mode": "auto",
                "mode_label": "自動匹配",
                "candidate_id": "id_賴坤成_1964",
            },
            {
                "name": "鄺麗貞",
                "mode": "auto",
                "mode_label": "自動匹配",
                "candidate_id": "id_鄺麗貞_1963",
            },
        ],
    )

    assert "已 commit 紀錄（3 筆）" in html
    assert "洪銘堅" in html
    assert "賴坤成" in html
    assert "鄺麗貞" in html
    assert "人工決策紀錄" not in html
    assert "重置來源檔" in html
    assert "/reset-confirm" in html

    confirm_html = env.get_template("reset_election_confirm.html").render(
        app_mode="identity",
        election_tree={"children": {}},
        selected_id="legislator/by-election-legislator/7th/第7屆立法委員臺東縣補選.xlsx",
        election_id="legislator/by-election-legislator/7th/第7屆立法委員臺東縣補選.xlsx",
        next_url="/elections/legislator/by-election-legislator/7th/第7屆立法委員臺東縣補選.xlsx",
    )
    assert "YES，移除" in confirm_html
    assert "NO，返回" in confirm_html
    assert "同一 candidate id 來自其他來源檔的資料會保留" in confirm_html
    assert "/reset" in confirm_html


def test_identity_check_templates_render_review_and_preview() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))

    index_html = env.get_template("identity_checks.html").render(
        app_mode="check",
        election_tree={"children": {}},
        selected_id=None,
        issues=[
            {
                "id": 1,
                "status": "open",
                "status_label": "待審",
                "severity_label": "必審",
                "candidate_id": "id_劉煜基_1946",
                "summary": "劉煜基 在 1998 年有 2 筆參選紀錄",
            }
        ],
        operations=[],
        generated_count=None,
    )
    assert "疑似誤合併檢查" in index_html
    assert "/identity-checks/1" in index_html
    assert "目前使用 Identity Check" in index_html
    assert "待審清單" in index_html
    assert ">查看<" not in index_html
    assert "修正紀錄" not in index_html

    detail = {
        "issue": {
            "id": 1,
            "issue_type_label": "同一年多場選舉",
            "summary": "劉煜基 在 1998 年有 2 筆參選紀錄",
            "source_record_ids": ["legislator:1"],
        },
        "candidate": {"id": "id_劉煜基_1946", "name": "劉煜基", "birthday": 1946},
        "records": [
            {
                "source_record_id": "legislator:1",
                "election_id": "legislator/test.xlsx",
                "year": 1998,
                "type": "立法委員",
                "region": "屏東縣選舉區",
                "party": "建國黨",
            },
            {
                "source_record_id": "council:1",
                "election_id": "councilor/test.xlsx",
                "year": 1998,
                "type": "縣市議員",
                "region": "屏東縣 第03選舉區",
                "party": "建國黨",
            },
        ],
        "nearby_candidates": [],
        "operations": [],
    }
    for record in detail["records"]:
        record["compare_fields"] = [
            {"key": "year", "label": "年份", "value": str(record["year"]), "class": "compare-token-1"},
            {"key": "type", "label": "選舉類別", "value": record["type"], "class": "compare-token-1"},
            {"key": "region", "label": "區域", "value": record["region"], "class": "compare-token-1"},
            {"key": "party", "label": "黨籍", "value": record["party"], "class": "compare-token-1"},
            {"key": "elected", "label": "當選", "value": "", "class": ""},
        ]
        record["bulletin_url"] = "https://example.test/bulletin"
        record["duplicate_year_source"] = False
    detail["records"][1]["duplicate_year_source"] = True
    detail_html = env.get_template("identity_check_detail.html").render(
        app_mode="check",
        election_tree={"children": {}},
        selected_id=None,
        detail=detail,
        preview={
            "action": "selected_new",
            "source_record_ids": ["legislator:1"],
            "target_candidate_id": "id_劉煜基_1946a",
            "after_candidates": [
                {
                    "id": "id_劉煜基_1946",
                    "name": "劉煜基",
                    "elections": [detail["records"][1]],
                },
                {
                    "id": "id_劉煜基_1946a",
                    "name": "劉煜基",
                    "elections": [detail["records"][0]],
                },
            ],
        },
        error="",
    )
    assert "套用前預覽" in detail_html
    assert "id_劉煜基_1946a" in detail_html
    assert "參選紀錄比較" in detail_html
    assert "選舉公報" in detail_html
    assert "重置來源檔" in detail_html
    assert "duplicate-source-file" in detail_html
    assert "/reset-confirm" in detail_html


def test_identity_check_detail_marks_duplicate_year_source_rows() -> None:
    from src.webapp.routes.identity_checks import _prepare_identity_check_detail

    detail = {
        "records": [
            {
                "source_record_id": "councilor/test.xlsx:1",
                "election_id": "councilor/test.xlsx",
                "year": 2005,
                "type": "縣市議員",
                "region": "臺東縣 第01選舉區",
                "elected": 1,
            },
            {
                "source_record_id": "councilor/test.xlsx:2",
                "election_id": "councilor/test.xlsx",
                "year": 2005,
                "type": "縣市議員",
                "region": "臺東縣 台東市",
                "elected": 0,
            },
            {
                "source_record_id": "councilor/test.xlsx:3",
                "election_id": "councilor/test.xlsx",
                "year": 2009,
                "type": "縣市議員",
                "region": "臺東縣 第01選舉區",
            },
        ]
    }

    _prepare_identity_check_detail(detail)

    assert detail["records"][0]["duplicate_year_source"] is True
    assert detail["records"][1]["duplicate_year_source"] is True
    assert detail["records"][2]["duplicate_year_source"] is False
    assert detail["records"][0]["compare_fields"][0]["class"] == "compare-plain"
    assert detail["records"][0]["compare_fields"][4]["class"] == "compare-elected"
    assert detail["records"][1]["compare_fields"][4]["class"] == "compare-not-elected"


def test_home_returns_200(tmp_path: Path) -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.open()
    except Exception:
        pytest.skip("PostgreSQL is not reachable")
    try:
        store.init_schema()
        (tmp_path / "_data" / "president").mkdir(parents=True)
        app = _make_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Identity Workbench" in resp.text
    finally:
        store.close()


def test_load_and_review_flow(tmp_path: Path) -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.open()
    except Exception:
        pytest.skip("PostgreSQL is not reachable")
    try:
        store.init_schema()
    except ConnectionError:
        store.close()
        pytest.skip("PostgreSQL is not reachable")

    token = uuid4().hex
    election_path = (
        tmp_path / "_data" / "legislator" / "party-list-legislator" / f"{token}th.yaml"
    )
    election_path.parent.mkdir(parents=True)
    election_path.write_text(
        "- name: 測試候選人\n  party: 測試黨\n  birthday: 1970\n"
        "  year: 2024\n  region: 全國\n  type: 立法委員\n  elected: 0\n  session: 11\n",
        encoding="utf-8",
    )
    election_id = f"legislator/party-list-legislator/{token}th.yaml"
    candidate_id = None

    app = _make_app(tmp_path, store)
    client = TestClient(app, raise_server_exceptions=True)

    try:
        # Load
        resp = client.post(f"/elections/{election_id}/load", follow_redirects=False)
        assert resp.status_code == 303

        # Review page
        resp = client.get(f"/review/{election_id}")
        assert resp.status_code == 200
        assert "測試候選人" in resp.text

        # Resolve
        src_records = store.list_source_records(election_id)
        src_id = src_records[0]["source_record_id"]
        resp = client.post(
            f"/review/{election_id}/resolve",
            data={"source_record_id": src_id, "mode": "new", "i": "0"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Commit
        resp = client.post(f"/elections/{election_id}/commit", follow_redirects=False)
        assert resp.status_code == 303

        candidates = store.list_candidates_with_elections()
        match = next((c for c in candidates if c["name"] == "測試候選人"), None)
        assert match is not None
        candidate_id = match["id"]
    finally:
        store.delete_election(election_id)
        if candidate_id:
            store.delete_candidate(candidate_id)
        store.close()


def test_auto_decisions_survive_without_browser_session(tmp_path: Path) -> None:
    # Load with one client, commit with another — confirms decisions are persisted in DB, not tied to session.
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.open()
    except Exception:
        pytest.skip("PostgreSQL is not reachable")
    try:
        store.init_schema()
    except ConnectionError:
        store.close()
        pytest.skip("PostgreSQL is not reachable")

    token = uuid4().hex
    election_path = (
        tmp_path / "_data" / "legislator" / "party-list-legislator" / f"{token}th.yaml"
    )
    election_path.parent.mkdir(parents=True)
    election_path.write_text(
        "- name: 自動測試候選人\n  party: 測試黨\n  birthday: 1980\n"
        "  year: 2024\n  region: 全國\n  type: 立法委員\n  elected: 0\n  session: 11\n"
        "- name: 人工測試候選人\n  party: 測試黨\n  birthday: 1990\n"
        "  year: 2024\n  region: 全國\n  type: 立法委員\n  elected: 0\n  session: 11\n",
        encoding="utf-8",
    )
    election_id = f"legislator/party-list-legislator/{token}th.yaml"
    candidate_id = "id_自動測試候選人_1980"
    manual_candidate_ids = [
        f"id_人工測試候選人_A_{token[:8]}",
        f"id_人工測試候選人_B_{token[:8]}",
    ]

    with store.connect() as conn:
        store._setup_conn(conn)
        for manual_candidate_id in manual_candidate_ids:
            conn.execute(
                """
                INSERT INTO candidates(id, name, birthday)
                VALUES (%s, %s, %s)
                """,
                (manual_candidate_id, "人工測試候選人", 1990),
            )

    app = _make_app(tmp_path, store)
    load_client = TestClient(app, raise_server_exceptions=True)
    commit_client = TestClient(app, raise_server_exceptions=True)

    try:
        resp = load_client.post(f"/elections/{election_id}/load", follow_redirects=False)
        assert resp.status_code == 303

        row = next(item for item in store.list_elections() if item["election_id"] == election_id)
        assert row["status"] == "review"
        assert row["resolved_count"] == 1
        assert row["unresolved_count"] == 1
        assert len(store.list_review_decisions(election_id)) == 1

        manual_source_record_id = next(
            record["source_record_id"]
            for record in store.list_source_records(election_id)
            if record["name"] == "人工測試候選人"
        )
        resp = load_client.post(
            f"/review/{election_id}/resolve",
            data={
                "source_record_id": manual_source_record_id,
                "mode": "use_match",
                "candidate_id": manual_candidate_ids[0],
                "i": "0",
                "total_count": "2",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

        resp = commit_client.post(f"/elections/{election_id}/commit", follow_redirects=False)
        assert resp.status_code == 303

        row = next(item for item in store.list_elections() if item["election_id"] == election_id)
        assert row["status"] == "done"
        assert store.list_review_decisions(election_id) == []
    finally:
        store.delete_election(election_id)
        store.delete_candidate(candidate_id)
        for manual_candidate_id in manual_candidate_ids:
            store.delete_candidate(manual_candidate_id)
        store.close()
