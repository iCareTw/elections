from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.voter_guide.pipeline import crop_filename, PERSON_FIELDS

SESSION = 16
MINGUO_YEAR = 113
YEAR_AD = 2024
ELECTION_ID = "president_2024_16"
SOURCE_PDF = f"/fake/{MINGUO_YEAR}年第{SESSION}任總統副總統.pdf"


def _store():
    from src.webapp.store import Store, load_database_config

    cfg = load_database_config()
    if not cfg.database_url:
        pytest.skip("PostgreSQL connection not configured")
    s = Store(cfg)
    try:
        s.open()
    except Exception:
        pytest.skip("PostgreSQL is not reachable")
    return s


def _make_fake_yaml(tmp_path: Path) -> Path:
    data = [
        {
            "號次": 1,
            "總統": {
                "姓名": "蔡英文",
                "出生年月日": "民國46年8月31日",
                "性別": "女",
                "學歷": "法學博士",
                "經歷": "總統",
                "相片": "/fake/photo_cai.png",
                "頁碼": 0,
            },
            "副總統": {
                "姓名": "賴清德",
                "出生年月日": "民國48年10月6日",
                "性別": "男",
                "學歷": "公共衛生碩士",
                "經歷": "行政院長",
                "頁碼": 0,
            },
            "政黨": "民主進步黨",
            "_verify": {
                "總統": {
                    "姓名": {"grade": "EXACT"},
                    "出生年月日": {"grade": "SOFT"},
                    "性別": {"grade": "EXACT"},
                    "學歷": {"grade": "NEAR"},
                    "經歷": {"grade": "NEAR"},
                },
                "副總統": {
                    "姓名": {"grade": "EXACT"},
                    "出生年月日": {"grade": "SOFT"},
                    "性別": {"grade": "EXACT"},
                    "學歷": {"grade": "NEAR"},
                    "經歷": {"grade": "NEAR"},
                },
                "政黨": {"grade": "EXACT"},
            },
        },
        {
            "號次": 2,
            "總統": {
                "姓名": "侯友宜",
                "出生年月日": "民國46年6月13日",
                "性別": "男",
                "學歷": "刑事司法博士",
                "經歷": "新北市長",
                "頁碼": 1,
            },
            "副總統": {
                "姓名": "趙少康",
                "出生年月日": "民國43年2月17日",
                "性別": "男",
                "學歷": "經濟學學士",
                "經歷": "廣播主持人",
                "頁碼": 1,
            },
            "政黨": "中國國民黨",
            "_verify": {
                "總統": {
                    "姓名": {"grade": "EXACT"},
                    "出生年月日": {"grade": "EXACT"},
                    "性別": {"grade": "EXACT"},
                    "學歷": {"grade": "EXACT"},
                    "經歷": {"grade": "EXACT"},
                },
                "副總統": {
                    "姓名": {"grade": "EXACT"},
                    "出生年月日": {"grade": "EXACT"},
                    "性別": {"grade": "EXACT"},
                    "學歷": {"grade": "EXACT"},
                    "經歷": {"grade": "EXACT"},
                },
                "政黨": {"grade": "EXACT"},
            },
        },
    ]
    yaml_path = tmp_path / "guide.yaml"
    yaml_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return yaml_path


def _make_fake_crops(tmp_path: Path) -> Path:
    """Create fake crop PNG files.

    ticket 1, 蔡英文 (總統): all 5 field crops present
    ticket 1, 賴清德 (副總統): 姓名/學歷/經歷 own crops + 基本資料 (no 出生年月日/性別 own crops)
    ticket 2, 侯友宜 (總統): only 姓名
    ticket 2, 趙少康 (副總統): no crop files
    """
    crops_dir = tmp_path / "crops"

    def touch(rel: str) -> None:
        p = crops_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"PNG_FAKE")

    kw = dict(type="president", session=SESSION, minguo_year=MINGUO_YEAR)

    for field in PERSON_FIELDS:
        touch(crop_filename(**kw, ticket=1, name="蔡英文", field=field))

    for field in ["姓名", "學歷", "經歷"]:
        touch(crop_filename(**kw, ticket=1, name="賴清德", field=field))
    touch(crop_filename(**kw, ticket=1, name="賴清德", field="基本資料"))

    touch(crop_filename(**kw, ticket=2, name="侯友宜", field="姓名"))

    # 趙少康: no files

    return crops_dir


def test_load_guide(tmp_path):
    from src.voter_guide.guide_load import load_guide

    store = _store()
    try:
        store.init_schema()

        yaml_path = _make_fake_yaml(tmp_path)
        crops_dir = _make_fake_crops(tmp_path)

        returned_id = load_guide(
            store,
            yaml_path=yaml_path,
            source_pdf_path=Path(SOURCE_PDF),
            crops_base_dir=crops_dir,
            election_type="president",
            force=True,
        )

        assert returned_id == ELECTION_ID

        with store.connect() as conn:
            store._setup_conn(conn)

            # --- 1 election row ---
            elections = conn.execute(
                "SELECT * FROM guide_elections WHERE id = %s", (ELECTION_ID,)
            ).fetchall()
            assert len(elections) == 1
            e = dict(elections[0])
            assert e["year"] == YEAR_AD
            assert e["session"] == SESSION
            assert e["type"] == "president"
            assert e["label"] == f"第{SESSION}任 {YEAR_AD} 總統"

            # --- 4 candidates ---
            candidates = conn.execute(
                "SELECT * FROM guide_candidates WHERE guide_election_id = %s ORDER BY order_id",
                (ELECTION_ID,),
            ).fetchall()
            assert len(candidates) == 4

            cand_map = {(c["ticket"], c["role"]): dict(c) for c in candidates}
            c1p = cand_map[(1, "總統")]    # 蔡英文
            c1v = cand_map[(1, "副總統")]  # 賴清德
            c2p = cand_map[(2, "總統")]    # 侯友宜
            c2v = cand_map[(2, "副總統")]  # 趙少康

            assert c1p["party"] == "民主進步黨"
            assert c1v["party"] == "民主進步黨"  # party copied to both roles
            assert c2p["party"] == "中國國民黨"
            assert c2v["party"] == "中國國民黨"
            assert c1p["source_page"] == 0
            assert c1v["source_page"] == 0
            assert c2p["source_page"] == 1
            assert c2v["source_page"] == 1
            assert c1p["photo_path"] == "/fake/photo_cai.png"
            assert c1v["photo_path"] is None

            # --- 蔡英文: all 5 fields have crop paths ---
            fields_c1p = {
                f["field_name"]: dict(f)
                for f in conn.execute(
                    "SELECT * FROM guide_fields WHERE guide_candidate_id = %s",
                    (c1p["id"],),
                ).fetchall()
            }
            assert len(fields_c1p) == 5
            for field in PERSON_FIELDS:
                assert fields_c1p[field]["source_crop_path"] is not None, (
                    f"蔡英文 {field} should have a crop path"
                )
            assert fields_c1p["姓名"]["grade"] == "EXACT"
            assert fields_c1p["出生年月日"]["grade"] == "SOFT"
            assert fields_c1p["姓名"]["update_source"] == "parse"

            # --- 賴清德: 姓名/學歷/經歷 own crops; 出生年月日/性別 → 基本資料 fallback ---
            fields_c1v = {
                f["field_name"]: dict(f)
                for f in conn.execute(
                    "SELECT * FROM guide_fields WHERE guide_candidate_id = %s",
                    (c1v["id"],),
                ).fetchall()
            }
            assert len(fields_c1v) == 5
            assert fields_c1v["姓名"]["source_crop_path"] is not None
            assert fields_c1v["學歷"]["source_crop_path"] is not None
            assert fields_c1v["經歷"]["source_crop_path"] is not None

            basic_path = str(
                crops_dir
                / crop_filename(
                    type="president",
                    session=SESSION,
                    minguo_year=MINGUO_YEAR,
                    ticket=1,
                    name="賴清德",
                    field="基本資料",
                )
            )
            assert fields_c1v["出生年月日"]["source_crop_path"] == basic_path
            assert fields_c1v["性別"]["source_crop_path"] == basic_path

            # --- 侯友宜: only 姓名 has crop ---
            fields_c2p = {
                f["field_name"]: dict(f)
                for f in conn.execute(
                    "SELECT * FROM guide_fields WHERE guide_candidate_id = %s",
                    (c2p["id"],),
                ).fetchall()
            }
            assert len(fields_c2p) == 5
            assert fields_c2p["姓名"]["source_crop_path"] is not None
            for field in ["出生年月日", "性別", "學歷", "經歷"]:
                assert fields_c2p[field]["source_crop_path"] is None

            # --- 趙少康: all null ---
            fields_c2v = {
                f["field_name"]: dict(f)
                for f in conn.execute(
                    "SELECT * FROM guide_fields WHERE guide_candidate_id = %s",
                    (c2v["id"],),
                ).fetchall()
            }
            assert len(fields_c2v) == 5
            for field in PERSON_FIELDS:
                assert fields_c2v[field]["source_crop_path"] is None

            # --- Snapshots: each candidate has v1 snapshot matching fields ---
            for cand in candidates:
                cand_id = cand["id"]
                snaps = conn.execute(
                    "SELECT * FROM guide_snapshots WHERE guide_candidate_id = %s",
                    (cand_id,),
                ).fetchall()
                assert len(snaps) == 1, (
                    f"candidate {cand_id} should have exactly 1 snapshot"
                )
                snap = dict(snaps[0])
                assert snap["version_no"] == 1

                snap_fields = {
                    f["field_name"]: dict(f)
                    for f in conn.execute(
                        "SELECT * FROM guide_snapshot_fields WHERE snapshot_id = %s",
                        (snap["id"],),
                    ).fetchall()
                }
                assert len(snap_fields) == 5

                guide_fields_rows = conn.execute(
                    "SELECT * FROM guide_fields WHERE guide_candidate_id = %s",
                    (cand_id,),
                ).fetchall()
                for gf in guide_fields_rows:
                    fn = gf["field_name"]
                    assert snap_fields[fn]["value"] == gf["value"]
                    assert snap_fields[fn]["grade"] == gf["grade"]
                    assert snap_fields[fn]["source_crop_path"] == gf["source_crop_path"]
                    assert snap_fields[fn]["flagged"] == gf["flagged"]
                    assert snap_fields[fn]["flag_note"] == gf["flag_note"]

    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()
