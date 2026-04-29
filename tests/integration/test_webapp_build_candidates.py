from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from src.webapp.build_candidates import build_candidates_yaml, write_candidates_yaml
from src.webapp.store import Store, load_database_config

ROOT = Path(__file__).resolve().parents[2]


def test_build_candidates_yaml_groups_records_by_candidate_id(tmp_path: Path) -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.open()
        store.init_schema()
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")

    token = uuid4().hex
    election_id = f"test/build-{token}.yaml"
    src_id = f"{election_id}:0"
    candidate_id = f"id_測試建置候選人_{token[:8]}"
    payload = {
        "name": "測試建置候選人",
        "birthday": 1959,
        "year": 2024,
        "type": "立法委員",
        "region": "全國",
        "party": "台灣民眾黨",
        "elected": 0,
    }

    try:
        store.upsert_election({
            "election_id": election_id,
            "type": "test",
            "label": "Build Test",
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

        rows = build_candidates_yaml(store)
        target = next(r for r in rows if r["id"] == candidate_id)
        assert target["elections"][0]["year"] == 2024

        output = tmp_path / "candidates.yaml"
        write_candidates_yaml(store, output, ROOT / "election_types.yaml")
        written = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert any(r["id"] == candidate_id for r in written)
    finally:
        store.delete_election(election_id)
        store.delete_candidate(candidate_id)
        store.close()
