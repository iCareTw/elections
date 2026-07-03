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

    return crops_dir


def _seed(store, tmp_path: Path) -> None:
    from src.voter_guide.guide_load import load_guide

    yaml_path = _make_fake_yaml(tmp_path)
    crops_dir = _make_fake_crops(tmp_path)
    load_guide(
        store,
        yaml_path=yaml_path,
        source_pdf_path=Path(SOURCE_PDF),
        crops_base_dir=crops_dir,
        election_type="president",
        force=True,
    )


# ---------------------------------------------------------------------------
# Task 4.1 — 讀導覽樹與候選人清單
# ---------------------------------------------------------------------------


def test_guide_tree(tmp_path):
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        tree = store.guide_tree()

        assert isinstance(tree, list)
        # At least one group with type "president"
        types = [g["type"] for g in tree]
        assert "president" in types

        pres_group = next(g for g in tree if g["type"] == "president")
        assert "elections" in pres_group
        elections = pres_group["elections"]
        assert len(elections) >= 1

        # Check the seeded election is in the list
        ids = [e["id"] for e in elections]
        assert ELECTION_ID in ids

        e = next(el for el in elections if el["id"] == ELECTION_ID)
        assert e["year"] == YEAR_AD
        assert e["session"] == SESSION
        assert "label" in e
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_guide_candidates_of(tmp_path):
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)

        assert len(candidates) == 4

        # ordered by order_id
        order_ids = [c["order_id"] for c in candidates]
        assert order_ids == sorted(order_ids)

        # check required keys
        for c in candidates:
            for key in ("id", "ticket", "role", "party", "name", "photo_flagged", "any_flag"):
                assert key in c, f"missing key {key!r}"

        # names come from guide_fields 姓名
        names = {c["name"] for c in candidates}
        assert names == {"蔡英文", "賴清德", "侯友宜", "趙少康"}

        # any_flag is False initially (no fields flagged)
        assert all(c["any_flag"] is False for c in candidates)

        # photo_flagged is False initially
        assert all(c["photo_flagged"] is False for c in candidates)
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


# ---------------------------------------------------------------------------
# Task 4.2 — 讀候選人工作版欄位
# ---------------------------------------------------------------------------

STABLE_ORDER = ["姓名", "出生年月日", "性別", "學歷", "經歷"]


def test_guide_candidate_view(tmp_path):
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        # pick 蔡英文 (ticket=1, role=總統)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        view = store.guide_candidate_view(cai_id)

        # top-level keys
        for key in ("candidate", "fields", "has_uncommitted", "latest_version"):
            assert key in view, f"missing key {key!r}"

        # candidate meta
        cand = view["candidate"]
        for key in ("id", "ticket", "role", "party", "gender", "photo_path", "photo_flagged",
                    "photo_note", "source_page", "election_id", "election_label"):
            assert key in cand, f"missing candidate key {key!r}"

        assert cand["ticket"] == 1
        assert cand["role"] == "總統"
        assert cand["gender"] == "女"
        assert cand["election_id"] == ELECTION_ID

        # fields in stable order
        fields = view["fields"]
        assert len(fields) == 5
        field_names = [f["field_name"] for f in fields]
        assert field_names == STABLE_ORDER

        for f in fields:
            for key in ("id", "field_name", "value", "grade", "source_crop_path",
                        "flagged", "flag_note", "can_ai_repair"):
                assert key in f, f"missing field key {key!r}"

        # 蔡英文 has all crop paths → can_ai_repair True
        assert all(f["can_ai_repair"] is True for f in fields)

        # right after load: has_uncommitted == False (fields match snapshot)
        assert view["has_uncommitted"] is False

        # latest_version == 1 (v1 from load)
        assert view["latest_version"] == 1
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_guide_candidate_view_has_uncommitted_excludes_photo(tmp_path):
    """Flagging a photo must NOT affect has_uncommitted."""
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        # Initially no uncommitted
        view = store.guide_candidate_view(cai_id)
        assert view["has_uncommitted"] is False

        # Flag photo
        store.guide_flag_photo(cai_id, "photo looks wrong")

        # has_uncommitted must remain False (photo is not versioned)
        view2 = store.guide_candidate_view(cai_id)
        assert view2["has_uncommitted"] is False
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


# ---------------------------------------------------------------------------
# Task 4.3 — 欄位/照片標記與解除
# ---------------------------------------------------------------------------


def _get_field(store, candidate_id: int, field_name: str) -> dict:
    with store.connect() as conn:
        store._setup_conn(conn)
        row = conn.execute(
            "SELECT id, flagged, flag_note FROM guide_fields WHERE guide_candidate_id = %s AND field_name = %s",
            (candidate_id, field_name),
        ).fetchone()
    return dict(row)


def _get_candidate_row(store, candidate_id: int) -> dict:
    with store.connect() as conn:
        store._setup_conn(conn)
        row = conn.execute(
            "SELECT photo_flagged, photo_note FROM guide_candidates WHERE id = %s",
            (candidate_id,),
        ).fetchone()
    return dict(row)


def test_guide_flag_unflag_field(tmp_path):
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        field = _get_field(store, cai_id, "姓名")
        field_id = field["id"]
        assert field["flagged"] is False
        assert field["flag_note"] is None

        # flag
        store.guide_flag_field(field_id, "字跡不清")
        updated = _get_field(store, cai_id, "姓名")
        assert updated["flagged"] is True
        assert updated["flag_note"] == "字跡不清"

        # unflag
        store.guide_unflag_field(field_id)
        cleared = _get_field(store, cai_id, "姓名")
        assert cleared["flagged"] is False
        assert cleared["flag_note"] is None
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_guide_flag_unflag_photo(tmp_path):
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        row = _get_candidate_row(store, cai_id)
        assert row["photo_flagged"] is False
        assert row["photo_note"] is None

        # flag
        store.guide_flag_photo(cai_id, "照片模糊")
        row2 = _get_candidate_row(store, cai_id)
        assert row2["photo_flagged"] is True
        assert row2["photo_note"] == "照片模糊"

        # unflag
        store.guide_unflag_photo(cai_id)
        row3 = _get_candidate_row(store, cai_id)
        assert row3["photo_flagged"] is False
        assert row3["photo_note"] is None
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_any_flag_reflects_flagged_field(tmp_path):
    """guide_candidates_of any_flag must be True when a text field is flagged."""
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        field = _get_field(store, cai_id, "學歷")
        store.guide_flag_field(field["id"], "疑問")

        candidates2 = store.guide_candidates_of(ELECTION_ID)
        cai2 = next(c for c in candidates2 if c["name"] == "蔡英文")
        assert cai2["any_flag"] is True

        # unflag → back to False
        store.guide_unflag_field(field["id"])
        candidates3 = store.guide_candidates_of(ELECTION_ID)
        cai3 = next(c for c in candidates3 if c["name"] == "蔡英文")
        assert cai3["any_flag"] is False
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


# ---------------------------------------------------------------------------
# Task 4.4 — 手動填欄位值
# ---------------------------------------------------------------------------


def test_guide_set_field_value(tmp_path):
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        with store.connect() as conn:
            store._setup_conn(conn)
            row = conn.execute(
                "SELECT id, value, grade, update_source, flagged, flag_note FROM guide_fields "
                "WHERE guide_candidate_id = %s AND field_name = '學歷'",
                (cai_id,),
            ).fetchone()
        original = dict(row)
        field_id = original["id"]
        assert original["grade"] == "NEAR"
        assert original["update_source"] == "parse"

        # Flag the field first, to verify flag is not touched
        store.guide_flag_field(field_id, "先標記")

        # manual set
        store.guide_set_field_value(field_id, "法學博士(修正)")

        with store.connect() as conn:
            store._setup_conn(conn)
            row2 = conn.execute(
                "SELECT value, grade, update_source, flagged, flag_note, updated_at FROM guide_fields WHERE id = %s",
                (field_id,),
            ).fetchone()
        updated = dict(row2)

        assert updated["value"] == "法學博士(修正)"
        assert updated["update_source"] == "manual"
        assert updated["grade"] is None
        # flagged/flag_note must NOT be changed
        assert updated["flagged"] is True
        assert updated["flag_note"] == "先標記"
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_set_field_value_causes_has_uncommitted(tmp_path):
    """After manual edit, guide_candidate_view must report has_uncommitted=True."""
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        view0 = store.guide_candidate_view(cai_id)
        assert view0["has_uncommitted"] is False

        field_id = next(f["id"] for f in view0["fields"] if f["field_name"] == "學歷")
        store.guide_set_field_value(field_id, "新學歷")

        view1 = store.guide_candidate_view(cai_id)
        assert view1["has_uncommitted"] is True
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


# ---------------------------------------------------------------------------
# Task 4.5 — Commit 快照與捨棄變更
# ---------------------------------------------------------------------------


def test_guide_commit(tmp_path):
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        view0 = store.guide_candidate_view(cai_id)
        assert view0["latest_version"] == 1
        assert view0["has_uncommitted"] is False

        # mutate a field
        field_id = next(f["id"] for f in view0["fields"] if f["field_name"] == "學歷")
        store.guide_set_field_value(field_id, "修改學歷")

        view1 = store.guide_candidate_view(cai_id)
        assert view1["has_uncommitted"] is True

        # commit
        new_version = store.guide_commit(cai_id, note="first manual commit")
        assert new_version == 2

        view2 = store.guide_candidate_view(cai_id)
        assert view2["latest_version"] == 2
        assert view2["has_uncommitted"] is False

        # verify snapshot was created
        with store.connect() as conn:
            store._setup_conn(conn)
            snap_row = conn.execute(
                "SELECT id, version_no, note FROM guide_snapshots WHERE guide_candidate_id = %s AND version_no = 2",
                (cai_id,),
            ).fetchone()
        assert snap_row is not None
        assert snap_row["note"] == "first manual commit"

        # verify snapshot fields
        with store.connect() as conn:
            store._setup_conn(conn)
            sf = conn.execute(
                "SELECT field_name, value FROM guide_snapshot_fields WHERE snapshot_id = %s",
                (snap_row["id"],),
            ).fetchall()
        sf_map = {r["field_name"]: r["value"] for r in sf}
        assert sf_map["學歷"] == "修改學歷"
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_guide_discard(tmp_path):
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        view0 = store.guide_candidate_view(cai_id)
        original_xueliValue = next(f["value"] for f in view0["fields"] if f["field_name"] == "學歷")

        # mutate
        field_id = next(f["id"] for f in view0["fields"] if f["field_name"] == "學歷")
        store.guide_set_field_value(field_id, "壞掉的學歷")
        store.guide_flag_field(field_id, "壞掉的 note")

        view1 = store.guide_candidate_view(cai_id)
        assert view1["has_uncommitted"] is True

        # discard
        store.guide_discard(cai_id)

        view2 = store.guide_candidate_view(cai_id)
        assert view2["has_uncommitted"] is False

        # value restored
        restored_xueli = next(f for f in view2["fields"] if f["field_name"] == "學歷")
        assert restored_xueli["value"] == original_xueliValue
        assert restored_xueli["flagged"] is False
        assert restored_xueli["flag_note"] is None
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_guide_commit_then_discard(tmp_path):
    """Seed → commit v2 → mutate → discard → fields match v2 snapshot."""
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        # commit v2 with a change
        view0 = store.guide_candidate_view(cai_id)
        field_id = next(f["id"] for f in view0["fields"] if f["field_name"] == "學歷")
        store.guide_set_field_value(field_id, "v2學歷")
        store.guide_commit(cai_id)

        # now mutate again
        view2 = store.guide_candidate_view(cai_id)
        field_id2 = next(f["id"] for f in view2["fields"] if f["field_name"] == "學歷")
        store.guide_set_field_value(field_id2, "v3壞掉")

        # discard → should restore to v2
        store.guide_discard(cai_id)

        view3 = store.guide_candidate_view(cai_id)
        assert view3["has_uncommitted"] is False
        assert view3["latest_version"] == 2
        restored = next(f for f in view3["fields"] if f["field_name"] == "學歷")
        assert restored["value"] == "v2學歷"
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


# ---------------------------------------------------------------------------
# Task 4.6 — 讀指定版本快照
# ---------------------------------------------------------------------------


def test_guide_snapshot_view(tmp_path):
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        # Check v1 snapshot
        snap = store.guide_snapshot_view(cai_id, 1)

        for key in ("fields", "version_no", "min_version", "max_version"):
            assert key in snap, f"missing key {key!r}"

        assert snap["version_no"] == 1
        assert snap["min_version"] == 1
        assert snap["max_version"] == 1

        # fields in stable order
        assert len(snap["fields"]) == 5
        field_names = [f["field_name"] for f in snap["fields"]]
        assert field_names == STABLE_ORDER

        for f in snap["fields"]:
            for key in ("field_name", "value", "grade", "source_crop_path", "flagged", "flag_note"):
                assert key in f, f"missing field key {key!r}"
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_guide_snapshot_view_after_commit(tmp_path):
    """After committing v2, snapshot_view shows correct bounds and fields."""
    store = _store()
    try:
        store.init_schema()
        _seed(store, tmp_path)

        candidates = store.guide_candidates_of(ELECTION_ID)
        cai = next(c for c in candidates if c["name"] == "蔡英文")
        cai_id = cai["id"]

        # mutate + commit v2
        view0 = store.guide_candidate_view(cai_id)
        field_id = next(f["id"] for f in view0["fields"] if f["field_name"] == "學歷")
        store.guide_set_field_value(field_id, "v2學歷")
        store.guide_commit(cai_id, note="v2")

        # v2 snapshot
        snap2 = store.guide_snapshot_view(cai_id, 2)
        assert snap2["version_no"] == 2
        assert snap2["min_version"] == 1
        assert snap2["max_version"] == 2

        xueli2 = next(f for f in snap2["fields"] if f["field_name"] == "學歷")
        assert xueli2["value"] == "v2學歷"

        # v1 snapshot (should still have original)
        snap1 = store.guide_snapshot_view(cai_id, 1)
        xueli1 = next(f for f in snap1["fields"] if f["field_name"] == "學歷")
        assert xueli1["value"] != "v2學歷"
        assert snap1["min_version"] == 1
        assert snap1["max_version"] == 2
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()
