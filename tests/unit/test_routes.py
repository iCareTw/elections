from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient

from src.webapp.app import create_app
from src.webapp.store import Store, load_database_config


def _make_app(tmp_path: Path, store: Store):
    app = create_app(root=tmp_path)
    app.state.store = store
    return app


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
