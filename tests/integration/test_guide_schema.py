from __future__ import annotations
import pytest
from src.webapp.store import Store, load_database_config

GUIDE_TABLES = [
    "guide_elections", "guide_candidates", "guide_fields", "guide_repair_jobs",
    # iteration 2 組結構
    "guide_groups", "guide_group_platform",
    "guide_group_snapshots", "guide_group_snapshot_fields",
    # 手動照片保留機制
    "guide_manual_photos",
]

# iteration 2 汰換的每人快照表
DROPPED_TABLES = ["guide_snapshots", "guide_snapshot_fields"]

def _store():
    cfg = load_database_config()
    if not cfg.database_url:
        pytest.skip("PostgreSQL connection not configured")
    s = Store(cfg)
    try:
        s.open()
    except Exception:
        pytest.skip("PostgreSQL is not reachable")
    return s

def _table_names(s):
    with s.connect() as conn:
        s._setup_conn(conn)
        rows = conn.execute(
            "select table_name from information_schema.tables "
            "where table_schema = %s", (s.config.schema,)
        ).fetchall()
    return {r["table_name"] for r in rows}

def _column_names(s, table):
    with s.connect() as conn:
        s._setup_conn(conn)
        rows = conn.execute(
            "select column_name from information_schema.columns "
            "where table_schema = %s and table_name = %s", (s.config.schema, table)
        ).fetchall()
    return {r["column_name"] for r in rows}

def test_guide_tables_created():
    s = _store()
    try:
        s.init_schema()
        names = _table_names(s)
        for t in GUIDE_TABLES:
            assert t in names
        for t in DROPPED_TABLES:
            assert t not in names, f"{t} 應已於 006 汰換"
    finally:
        s.close()

def test_guide_candidates_group_shaped():
    s = _store()
    try:
        s.init_schema()
        cols = _column_names(s, "guide_candidates")
        assert "guide_group_id" in cols
        assert "party" not in cols   # party 移到 guide_groups
        assert "ticket" not in cols  # ticket 由組提供
    finally:
        s.close()
