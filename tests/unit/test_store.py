from __future__ import annotations

from datetime import timedelta
import time
from uuid import uuid4

import pytest

from src.webapp.store import Store, load_database_config


def test_store_uses_taipei_timezone() -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.open()
    except Exception:
        pytest.skip("PostgreSQL is not reachable")
    try:
        with store.connect() as conn:
            assert conn.execute("show timezone").fetchone()["TimeZone"] == "Asia/Taipei"
            assert conn.execute("select current_timestamp as now").fetchone()["now"].utcoffset() == timedelta(hours=8)
    finally:
        store.close()


def test_upsert_election_refreshes_updated_at_on_update() -> None:
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
    election_id = f"test/updated-at-{token}.yaml"

    try:
        store.upsert_election(
            {
                "election_id": election_id,
                "type": "test",
                "label": "Updated At Test",
                "path": f"/tmp/{election_id}",
            }
        )
        with store.connect() as conn:
            first = conn.execute(
                "select updated_at from elections where election_id = %s",
                (election_id,),
            ).fetchone()["updated_at"]

        time.sleep(0.01)
        store.upsert_election(
            {
                "election_id": election_id,
                "type": "test",
                "label": "Updated At Test Changed",
                "path": f"/tmp/{election_id}",
            }
        )

        with store.connect() as conn:
            second = conn.execute(
                "select updated_at from elections where election_id = %s",
                (election_id,),
            ).fetchone()["updated_at"]

        assert first.utcoffset() == timedelta(hours=8)
        assert second.utcoffset() == timedelta(hours=8)
        assert second > first
    finally:
        store.delete_election(election_id)
        store.close()


def test_store_rejects_missing_schema() -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(type(config)(database_url=config.database_url, schema="missing_schema_for_test"))
    try:
        store.open()
    except Exception:
        pytest.skip("PostgreSQL is not reachable")
    try:
        with pytest.raises(ConnectionError, match="PostgreSQL schema is not available"):
            store.validate_connection()
    finally:
        store.close()


def test_store_lists_election_progress_status() -> None:
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
    election_id = f"test/progress-{token}.yaml"
    source_record_id = f"{election_id}:0"
    candidate_id = None

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
        store.upsert_review_decision(
            source_record_id=source_record_id,
            election_id=election_id,
            candidate_id=candidate_id,
            mode="new",
        )

        row = next(item for item in store.list_elections() if item["election_id"] == election_id)
        assert row["status"] == "ready"
        assert row["imported_count"] == 1
        assert row["unresolved_count"] == 0
        assert row["resolved_count"] == 1

        store.commit_election(
            election_id=election_id,
            decisions={source_record_id: {"mode": "auto", "candidate_id": candidate_id}},
            source_records_map={source_record_id: payload},
        )

        row = next(item for item in store.list_elections() if item["election_id"] == election_id)
        assert row["status"] == "done"
        assert row["imported_count"] == 1
        assert row["unresolved_count"] == 0
        assert store.list_review_decisions(election_id) == []
    finally:
        store.delete_election(election_id)
        if candidate_id:
            store.delete_candidate(candidate_id)
        store.close()


def test_store_commit_election_writes_candidates_and_elections() -> None:
    from uuid import uuid4
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
        store.delete_candidate(candidate_id)
        store.close()
