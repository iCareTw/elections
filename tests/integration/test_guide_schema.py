from __future__ import annotations
import pytest
from src.webapp.store import Store, load_database_config

GUIDE_TABLES = [
    "guide_elections", "guide_candidates", "guide_fields",
    "guide_snapshots", "guide_snapshot_fields", "guide_repair_jobs",
]

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

def test_guide_tables_created():
    s = _store()
    try:
        s.init_schema()
        with s.connect() as conn:
            s._setup_conn(conn)
            rows = conn.execute(
                "select table_name from information_schema.tables "
                "where table_schema = %s", (s.config.schema,)
            ).fetchall()
        names = {r["table_name"] for r in rows}
        for t in GUIDE_TABLES:
            assert t in names
    finally:
        s.close()
