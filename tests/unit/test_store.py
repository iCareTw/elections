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


def test_reset_election_data_removes_committed_rows_and_resyncs_candidate_history() -> None:
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
    reset_election_id = f"test/reset-{token}.yaml"
    keep_election_id = f"test/keep-{token}.yaml"
    reset_src_id = f"{reset_election_id}:0"
    keep_src_id = f"{keep_election_id}:0"
    shared_candidate_id = f"id_重置測試_{token[:8]}"

    try:
        for election_id, label in (
            (reset_election_id, "Reset Test"),
            (keep_election_id, "Keep Test"),
        ):
            store.upsert_election({
                "election_id": election_id,
                "type": "test",
                "label": label,
                "path": f"/tmp/{election_id}",
            })

        reset_payload = {
            "name": "重置測試",
            "birthday": 1970,
            "year": 2020,
            "type": "縣市議員",
            "region": "臺東縣 第01選舉區",
            "party": "無黨籍",
            "elected": 1,
        }
        keep_payload = {
            "name": "重置測試",
            "birthday": 1970,
            "year": 2024,
            "type": "縣市議員",
            "region": "臺東縣 第01選舉區",
            "party": "無黨籍",
            "elected": 0,
        }
        store.insert_source_record(
            source_record_id=reset_src_id,
            election_id=reset_election_id,
            payload=reset_payload,
        )
        store.insert_source_record(
            source_record_id=keep_src_id,
            election_id=keep_election_id,
            payload=keep_payload,
        )
        store.commit_election(
            election_id=reset_election_id,
            decisions={reset_src_id: {"mode": "auto", "candidate_id": shared_candidate_id}},
            source_records_map={reset_src_id: reset_payload},
        )
        store.commit_election(
            election_id=keep_election_id,
            decisions={keep_src_id: {"mode": "auto", "candidate_id": shared_candidate_id}},
            source_records_map={keep_src_id: keep_payload},
        )

        stats = store.reset_election_data(reset_election_id)

        assert stats["source_records"] == 1
        assert stats["resolutions"] == 1
        assert store.list_source_records(reset_election_id) == []
        assert store.list_resolutions(reset_election_id) == []
        target = next(c for c in store.list_candidates_with_elections() if c["id"] == shared_candidate_id)
        assert [e["year"] for e in target["elections"]] == [2024]
    finally:
        store.delete_election(reset_election_id)
        store.delete_election(keep_election_id)
        store.delete_candidate(shared_candidate_id)
        store.close()


def test_identity_fix_splits_committed_candidate_with_operation_snapshot() -> None:
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
    candidate_id = f"id_疑似誤合併_{token[:8]}"
    election_id_a = f"test/identity-check-a-{token}.yaml"
    election_id_b = f"test/identity-check-b-{token}.yaml"
    src_a = f"{election_id_a}:0"
    src_b = f"{election_id_b}:0"
    payload_a = {
        "name": "疑似誤合併",
        "birthday": 1970,
        "year": 1998,
        "type": "立法委員",
        "region": "屏東縣選舉區",
        "party": "測試黨",
        "elected": 0,
    }
    payload_b = {
        "name": "疑似誤合併",
        "birthday": 1970,
        "year": 1998,
        "type": "縣市議員",
        "region": "屏東縣 第03選舉區",
        "party": "測試黨",
        "elected": 0,
    }

    try:
        for election_id, src_id, payload in (
            (election_id_a, src_a, payload_a),
            (election_id_b, src_b, payload_b),
        ):
            store.upsert_election({
                "election_id": election_id,
                "type": "test",
                "label": election_id,
                "path": f"/tmp/{election_id}",
            })
            store.insert_source_record(
                source_record_id=src_id,
                election_id=election_id,
                payload=payload,
            )
            store.commit_election(
                election_id=election_id,
                decisions={src_id: {"mode": "auto", "candidate_id": candidate_id}},
                source_records_map={src_id: payload},
            )

        assert store.refresh_identity_check_issues() >= 1
        issue = next(
            item
            for item in store.list_identity_check_issues()
            if item["candidate_id"] == candidate_id
            and item["issue_type"] == "same_year_multiple"
        )

        preview = store.preview_identity_fix(
            issue_id=issue["id"],
            action="selected_new",
            source_record_ids=[src_a],
        )
        assert preview["target_candidate_id"] == f"{candidate_id}a"
        assert len(preview["after_candidates"]) == 2

        operation_id = store.apply_identity_fix(
            issue_id=issue["id"],
            action="selected_new",
            source_record_ids=[src_a],
        )

        with store.connect() as conn:
            store._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT source_record_id, candidate_id
                FROM resolutions
                WHERE source_record_id = ANY(%s)
                ORDER BY source_record_id
                """,
                ([src_a, src_b],),
            ).fetchall()
        assert {r["source_record_id"]: r["candidate_id"] for r in rows} == {
            src_a: f"{candidate_id}a",
            src_b: candidate_id,
        }

        operations = store.list_identity_fix_operations(issue_id=issue["id"])
        assert operations[0]["id"] == operation_id
        assert operations[0]["before_snapshot"]
        assert operations[0]["after_snapshot"]
    finally:
        with store.connect() as conn:
            store._setup_conn(conn)
            conn.execute(
                "DELETE FROM identity_fix_operations WHERE source_candidate_id = %s OR target_candidate_id = %s",
                (candidate_id, f"{candidate_id}a"),
            )
        store.delete_election(election_id_a)
        store.delete_election(election_id_b)
        store.delete_candidate(candidate_id)
        store.delete_candidate(f"{candidate_id}a")
        store.close()
