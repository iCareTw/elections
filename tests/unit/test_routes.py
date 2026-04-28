from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

from src.webapp.app import create_app
from src.webapp.routes.elections import _election_tree
from src.webapp.store import Store, load_database_config


def _make_app(tmp_path: Path, store: Store):
    app = create_app(root=tmp_path)
    app.state.store = store
    return app


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


def test_navigator_does_not_expand_unselected_top_level_dirs() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("elections.html")
    election_tree = {
        "children": {
            "president": {
                "kind": "dir",
                "path": "president",
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
                "children": {
                    "party-list-legislator": {
                        "kind": "dir",
                        "path": "legislator/party-list-legislator",
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
    assert selected_html.count('class="tree-node dir" open') == 1
    assert '<details class="tree-node dir" open>\n            <summary class="tree-dir">president</summary>' in selected_html


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

    assert "此選舉已匯入, 尚未完成審核" in html
    assert "/review/president/" in html


def test_home_returns_200(tmp_path: Path) -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.init_schema()
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")

    (tmp_path / "_data" / "president").mkdir(parents=True)
    app = _make_app(tmp_path, store)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Identity Workbench" in resp.text


def test_load_and_review_flow(tmp_path: Path) -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.init_schema()
    except ConnectionError:
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
