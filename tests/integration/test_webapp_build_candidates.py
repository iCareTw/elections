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
        pytest.skip("DATABASE_URL is not configured")

    store = Store(config)
    try:
        store.init_schema()
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")

    token = uuid4().hex
    election_id = f"test/build-{token}.yaml"
    source_record_id = f"{election_id}:0"

    try:
        store.upsert_election(
            {
                "election_id": election_id,
                "type": "test",
                "label": "Build Test",
                "path": f"/tmp/{election_id}",
                "status": "todo",
            }
        )
        store.insert_source_record(
            source_record_id=source_record_id,
            election_id=election_id,
            payload={
                "name": "柯文哲",
                "birthday": 1959,
                "year": 2024,
                "type": "立法委員",
                "region": "全國",
                "party": "台灣民眾黨",
                "elected": 0,
            },
        )
        store.save_resolution(
            source_record_id=source_record_id,
            election_id=election_id,
            candidate_id="id_柯文哲_1959",
            mode="auto",
        )

        rows = build_candidates_yaml(store)
        target = [row for row in rows if row["id"] == "id_柯文哲_1959"][0]

        assert target["elections"][0]["year"] == 2024

        output = tmp_path / "candidates.yaml"
        write_candidates_yaml(store, output, ROOT / "election_types.yaml")

        written = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert any(row["id"] == "id_柯文哲_1959" for row in written)
    finally:
        store.delete_election(election_id)
