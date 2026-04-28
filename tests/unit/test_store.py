from __future__ import annotations

from uuid import uuid4

import pytest

from src.webapp.store import Store, load_database_config



def test_store_rejects_missing_schema() -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(type(config)(database_url=config.database_url, schema="missing_schema_for_test"))

    with pytest.raises(ConnectionError, match="PostgreSQL schema is not available"):
        store.validate_connection()


def test_store_lists_election_progress_status() -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.init_schema()
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")
    token = uuid4().hex
    election_id = f"test/progress-{token}.yaml"
    source_record_id = f"{election_id}:0"

    try:
        store.upsert_election(
            {
                "election_id": election_id,
                "type": "test",
                "label": "Progress Election",
                "path": f"/tmp/{election_id}",
            }
        )

        row = next(item for item in store.list_elections() if item["election_id"] == election_id)
        assert row["status"] == "todo"
        assert row["imported_count"] == 0
        assert row["unresolved_count"] == 0

        payload = {"name": "測試候選人", "birthday": 1970, "year": 2024, "type": "縣市首長", "region": "臺北市"}
        store.insert_source_record(
            source_record_id=source_record_id,
            election_id=election_id,
            payload=payload,
        )

        row = next(item for item in store.list_elections() if item["election_id"] == election_id)
        assert row["status"] == "review"
        assert row["imported_count"] == 1
        assert row["unresolved_count"] == 1

        candidate_id = f"id_測試候選人_{token[:8]}"
        store.commit_election(
            election_id=election_id,
            decisions={source_record_id: {"mode": "auto", "candidate_id": candidate_id}},
            source_records_map={source_record_id: payload},
        )

        row = next(item for item in store.list_elections() if item["election_id"] == election_id)
        assert row["status"] == "done"
        assert row["imported_count"] == 1
        assert row["unresolved_count"] == 0
    finally:
        store.delete_election(election_id)
        store.delete_candidate(candidate_id)


def test_store_commit_election_writes_candidates_and_elections() -> None:
    from uuid import uuid4
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.init_schema()
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")

    token = uuid4().hex
    election_id = f"test/commit-{token}.yaml"
    src_id = f"{election_id}:0"
    candidate_id = f"id_測試人_{token[:8]}"

    try:
        store.upsert_election({
            "election_id": election_id,
            "type": "test",
            "label": "Commit Test",
            "path": f"/tmp/{election_id}",
        })
        store.insert_source_record(
            source_record_id=src_id,
            election_id=election_id,
            payload={"name": "測試人", "birthday": 1970, "year": 2024,
                     "type": "縣市首長", "region": "臺北市", "party": "無黨籍", "elected": 0},
        )
        auto, manual = store.commit_election(
            election_id=election_id,
            decisions={src_id: {"mode": "auto", "candidate_id": candidate_id}},
            source_records_map={src_id: {"name": "測試人", "birthday": 1970, "year": 2024,
                                         "type": "縣市首長", "region": "臺北市",
                                         "party": "無黨籍", "elected": 0}},
        )

        assert auto == 1 and manual == 0

        candidates = store.list_candidates_with_elections()
        target = next((c for c in candidates if c["id"] == candidate_id), None)
        assert target is not None
        assert target["elections"][0]["year"] == 2024
        assert target["elections"][0]["region"] == "臺北市"
    finally:
        store.delete_election(election_id)
