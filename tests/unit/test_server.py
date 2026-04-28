from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.webapp.server import build_api
from src.webapp.store import Store, load_database_config


def test_api_loads_election_and_lists_manual_review_items(tmp_path: Path) -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    token = uuid4().hex
    election_path = tmp_path / "_data" / "legislator" / "party-list-legislator" / f"{token}th.yaml"
    election_path.parent.mkdir(parents=True)
    election_path.write_text(
        "- name: 測試候選人\n  party: 測試黨\n  birthday: 1970\n"
        "  year: 2024\n  region: 全國\n  type: 立法委員\n  elected: 0\n",
        encoding="utf-8",
    )
    (tmp_path / "candidates.yaml").write_text(
        "- name: 測試候選人\n  id: id_測試候選人_1960\n  birthday: 1960\n  elections: []\n",
        encoding="utf-8",
    )
    election_id = f"legislator/party-list-legislator/{token}th.yaml"
    store = Store(config)
    try:
        api = build_api(tmp_path, store)
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")

    try:
        elections = api.handle_json("GET", "/api/elections")
        assert any(e["election_id"] == election_id for e in elections)

        summary = api.handle_json("POST", "/api/elections/load", {"election_id": election_id})
        assert summary["manual"] == 1

        elections = api.handle_json("GET", "/api/elections")
        election = next(e for e in elections if e["election_id"] == election_id)
        assert election["status"] == "review"
        assert election["unresolved_count"] == 1

        items = api.handle_json("GET", f"/api/review-items?election_id={election_id}")
        assert items[0]["source_record_id"] == f"{election_id}:0"
        assert items[0]["matches"][0]["id"] == "id_測試候選人_1960"

        resolution = api.handle_json(
            "POST",
            "/api/resolutions",
            {
                "election_id": election_id,
                "source_record_id": f"{election_id}:0",
                "candidate_id": "id_測試候選人_1960",
                "mode": "manual",
            },
        )
        assert resolution["mode"] == "manual"

        elections = api.handle_json("GET", "/api/elections")
        election = next(e for e in elections if e["election_id"] == election_id)
        assert election["status"] == "done"
        assert election["unresolved_count"] == 0
    finally:
        store.delete_election(election_id)
