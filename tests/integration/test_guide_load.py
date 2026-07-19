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


def _person(name, birth, gender, edu, exp, page, photo=None):
    d = {"姓名": name, "出生年月日": birth, "性別": gender,
         "學歷": edu, "經歷": exp, "頁碼": page}
    if photo:
        d["相片"] = photo
    return d


def _verify_all(grade="EXACT"):
    block = {g: {f: {"grade": grade} for f in PERSON_FIELDS} for g in ("總統", "副總統")}
    block["政黨"] = {"grade": "EXACT"}
    block["政見"] = {"grade": "無法解析"}
    return block


def _make_fake_yaml(tmp_path: Path) -> Path:
    data = [
        {
            "號次": 1,
            "總統": _person("蔡英文", "民國46年8月31日", "女", "法學博士", "總統", 0,
                            photo="/fake/photo_cai.png"),
            "副總統": _person("賴清德", "民國48年10月6日", "男", "公共衛生碩士", "行政院長", 0),
            "政黨": "民主進步黨",
            "政見": "第1組政見內容…",
            "_verify": {
                "總統": {**{f: {"grade": "EXACT"} for f in PERSON_FIELDS},
                         "出生年月日": {"grade": "SOFT"}},
                "副總統": {f: {"grade": "EXACT"} for f in PERSON_FIELDS},
                "政黨": {"grade": "EXACT"},
                "政見": {"grade": "無法解析"},
            },
        },
        {
            "號次": 2,
            "總統": _person("侯友宜", "民國46年6月13日", "男", "刑事司法博士", "新北市長", 1),
            "副總統": _person("趙少康", "民國43年2月17日", "男", "經濟學學士", "廣播主持人", 1),
            "政黨": "中國國民黨",
            "政見": None,               # 第2組政見缺(測 None)
            "_verify": _verify_all(),
        },
    ]
    yaml_path = tmp_path / "guide.yaml"
    yaml_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return yaml_path


def _make_fake_crops(tmp_path: Path) -> Path:
    """建假切圖:
    ticket 1 蔡英文(總統):5 欄齊全;賴清德(副總統):姓名/學歷/經歷 + 基本資料(缺出生/性別自己的圖)
    ticket 1 政見:有切圖
    ticket 2 侯友宜(總統):只有姓名;趙少康(副總統):無;政見:無
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
    touch(crop_filename(**kw, ticket=1, name="", field="政見"))   # 組層級政見切圖
    touch(crop_filename(**kw, ticket=2, name="侯友宜", field="姓名"))
    return crops_dir


def _load(store, tmp_path):
    from src.voter_guide.guide_load import load_guide
    store.init_schema()
    return load_guide(
        store,
        yaml_path=_make_fake_yaml(tmp_path),
        source_pdf_path=Path(SOURCE_PDF),
        crops_base_dir=_make_fake_crops(tmp_path),
        election_type="president",
        force=True,
    )


def test_load_guide_group_shaped(tmp_path):
    store = _store()
    try:
        returned_id = _load(store, tmp_path)
        assert returned_id == ELECTION_ID

        with store.connect() as conn:
            store._setup_conn(conn)

            # 1 場選舉
            e = conn.execute("SELECT * FROM guide_elections WHERE id=%s",
                             (ELECTION_ID,)).fetchone()
            assert e and e["year"] == YEAR_AD and e["label"] == f"第{SESSION}任 {YEAR_AD} 總統"

            # 2 組
            groups = conn.execute(
                "SELECT * FROM guide_groups WHERE guide_election_id=%s ORDER BY ticket",
                (ELECTION_ID,)).fetchall()
            assert len(groups) == 2
            g1, g2 = dict(groups[0]), dict(groups[1])
            assert g1["ticket"] == 1 and g1["party"] == "民主進步黨"
            assert g2["ticket"] == 2 and g2["party"] == "中國國民黨"

            # 每組 4 候選人(2 組 × 正副),掛在組上
            cands = conn.execute(
                "SELECT c.* FROM guide_candidates c JOIN guide_groups g ON g.id=c.guide_group_id "
                "WHERE g.guide_election_id=%s", (ELECTION_ID,)).fetchall()
            assert len(cands) == 4
            by = {(c["guide_group_id"], c["role"]): dict(c) for c in cands}
            c1p = by[(g1["id"], "總統")]
            assert c1p["photo_path"] == "/fake/photo_cai.png"
            assert c1p["source_page"] == 0

            # 每候選人 5 欄;蔡英文各欄有切圖
            f1p = {f["field_name"]: dict(f) for f in conn.execute(
                "SELECT * FROM guide_fields WHERE guide_candidate_id=%s", (c1p["id"],)).fetchall()}
            assert len(f1p) == 5
            assert all(f1p[f]["source_crop_path"] for f in PERSON_FIELDS)
            assert f1p["出生年月日"]["grade"] == "SOFT"

            # 賴清德 出生年月日/性別 → 基本資料 fallback
            c1v = by[(g1["id"], "副總統")]
            f1v = {f["field_name"]: dict(f) for f in conn.execute(
                "SELECT * FROM guide_fields WHERE guide_candidate_id=%s", (c1v["id"],)).fetchall()}
            assert "基本資料" in (f1v["出生年月日"]["source_crop_path"] or "")
            assert "基本資料" in (f1v["性別"]["source_crop_path"] or "")

            # 組共用政見
            p1 = conn.execute("SELECT * FROM guide_group_platform WHERE guide_group_id=%s",
                              (g1["id"],)).fetchone()
            assert p1 and p1["value"] == "第1組政見內容…"
            assert "政見" in (p1["source_crop_path"] or "")
            p2 = conn.execute("SELECT * FROM guide_group_platform WHERE guide_group_id=%s",
                              (g2["id"],)).fetchone()
            assert p2 and p2["value"] is None            # 第2組政見缺 + 無切圖
            assert p2["source_crop_path"] is None

            # 組 v1 快照:正副各 5 欄 + 政見 = 11 筆
            snap = conn.execute(
                "SELECT * FROM guide_group_snapshots WHERE guide_group_id=%s", (g1["id"],)).fetchone()
            assert snap and snap["version_no"] == 1
            sf = conn.execute(
                "SELECT scope, field_name FROM guide_group_snapshot_fields WHERE snapshot_id=%s",
                (snap["id"],)).fetchall()
            scopes = [(r["scope"], r["field_name"]) for r in sf]
            assert len(scopes) == 11
            assert ("政見", "政見") in scopes
            assert sum(1 for s, _ in scopes if s == "總統") == 5
            assert sum(1 for s, _ in scopes if s == "副總統") == 5
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_reload_without_force_raises_and_keeps_data(tmp_path):
    from src.voter_guide.guide_load import load_guide, GuideElectionExists

    store = _store()
    try:
        store.init_schema()
        store.guide_delete_election(ELECTION_ID)
        common = dict(yaml_path=_make_fake_yaml(tmp_path),
                      source_pdf_path=Path(SOURCE_PDF),
                      crops_base_dir=_make_fake_crops(tmp_path),
                      election_type="president")

        load_guide(store, **common, force=False)

        def _group_ids():
            with store.connect() as conn:
                store._setup_conn(conn)
                rows = conn.execute(
                    "SELECT id FROM guide_groups WHERE guide_election_id=%s ORDER BY id",
                    (ELECTION_ID,)).fetchall()
            return [r["id"] for r in rows]

        before = _group_ids()
        assert len(before) == 2

        with pytest.raises(GuideElectionExists):
            load_guide(store, **common, force=False)
        assert _group_ids() == before

        load_guide(store, **common, force=True)
        after = _group_ids()
        assert len(after) == 2 and set(after).isdisjoint(before)
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_manual_photo_survives_force_reload(tmp_path):
    """手動更正的照片,在 --force 重載後仍套回對應候選人。"""
    store = _store()
    try:
        store.guide_delete_election(ELECTION_ID)
        _clear_manual(store)
        _load(store, tmp_path)                              # v1

        manual = tmp_path / "manual_ticket2_president.png"
        manual.write_bytes(b"PNG_MANUAL")
        store.guide_upsert_manual_photo(ELECTION_ID, 2, "總統", str(manual))

        _load(store, tmp_path)                              # --force 重載 → 應套回手動照片

        cid = next(c["id"] for c in store.guide_candidates_of(ELECTION_ID)
                   if c["ticket"] == 2 and c["role"] == "總統")
        assert store.guide_candidate_pdf_ref(cid)["photo_path"] == str(manual)
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
            _clear_manual(store)
        except Exception:
            pass
        store.close()


def _clear_manual(store):
    with store.connect() as conn:
        store._setup_conn(conn)
        conn.execute("DELETE FROM guide_manual_photos WHERE election_id = %s", (ELECTION_ID,))
