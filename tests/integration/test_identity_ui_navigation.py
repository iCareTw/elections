from __future__ import annotations

import os
from pathlib import Path
from shutil import copyfile
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from src.webapp.app import create_app
from src.webapp.store import Store, load_database_config

ROOT = Path(__file__).resolve().parents[2]


def _client(tmp_path: Path, store: Store) -> TestClient:
    cwd = Path.cwd()
    try:
        os.chdir(ROOT)
        app = create_app(root=tmp_path)
    finally:
        os.chdir(cwd)
    app.state.store = store
    return TestClient(app, raise_server_exceptions=True)


def test_loaded_review_election_can_be_reopened_after_switching(tmp_path: Path) -> None:
    config = load_database_config(ROOT / ".env")
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.init_schema()
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")

    data_dir = tmp_path / "_data" / "president"
    data_dir.mkdir(parents=True)
    loaded_name = "第09任總統副總統選舉.xlsx"
    other_name = "第10任總統副總統選舉.xlsx"
    copyfile(ROOT / "_data" / "president" / loaded_name, data_dir / loaded_name)
    copyfile(ROOT / "_data" / "president" / other_name, data_dir / other_name)

    loaded_id = f"president/{loaded_name}"
    other_id = f"president/{other_name}"
    loaded_url = quote(loaded_id, safe="/")
    other_url = quote(other_id, safe="/")
    review_url = f"/review/{loaded_url}"

    try:
        store.delete_election(loaded_id)
        store.delete_election(other_id)

        client = _client(tmp_path, store)

        resp = client.post(f"/elections/{loaded_url}/load", follow_redirects=False)
        assert resp.status_code == 303

        resp = client.get(f"/elections/{other_url}")
        assert resp.status_code == 200
        assert "此選舉尚未匯入資料" in resp.text
        assert f'href="{review_url}"' in resp.text

        resp = client.get(f"/elections/{loaded_url}", follow_redirects=True)
        assert resp.status_code == 200
        assert "Incoming Record" in resp.text
        assert "第09任總統副總統選舉.xlsx" in resp.text
    finally:
        store.delete_election(loaded_id)
        store.delete_election(other_id)
