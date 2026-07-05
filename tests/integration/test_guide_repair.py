from __future__ import annotations

from pathlib import Path

from src.voter_guide.guide_load import load_guide
from src.voter_guide.guide_repair import run_repair_job
from tests.integration.test_guide_load import (
    ELECTION_ID,
    SOURCE_PDF,
    _make_fake_crops,
    _make_fake_yaml,
    _store,
)


def _seed(store, tmp_path):
    store.init_schema()
    yaml_path = _make_fake_yaml(tmp_path)
    crops_dir = _make_fake_crops(tmp_path)
    load_guide(store, yaml_path=yaml_path, source_pdf_path=Path(SOURCE_PDF),
               crops_base_dir=crops_dir, election_type="president", force=True)


def _candidate_id(store, name):
    for c in store.guide_candidates_of(ELECTION_ID):
        if c["name"] == name:
            return c["id"]
    raise AssertionError(f"candidate {name} not found")


def test_run_repair_job_updates_field(tmp_path):
    store = _store()
    try:
        _seed(store, tmp_path)
        cid = _candidate_id(store, "蔡英文")           # 該候選人各欄皆有切圖
        field = store.guide_get_field(cid, "學歷")
        assert field["source_crop_path"] is not None
        store.guide_flag_field(field["id"], "學歷讀錯了")  # 先標記,驗證不自動解除

        job_id = store.guide_create_repair_job(cid, "學歷", "請重讀學歷欄")

        captured = {}
        def fake_transcribe_image(png_path, field_name, note=None):
            captured["args"] = (png_path, field_name, note)
            return "法學博士(修復後)"

        run_repair_job(store, job_id, transcribe_image=fake_transcribe_image)

        # 傳給模型的是該欄切圖 + 欄名 + 人工提示
        assert captured["args"][0] == field["source_crop_path"]
        assert captured["args"][1] == "學歷"
        assert captured["args"][2] == "請重讀學歷欄"

        updated = store.guide_get_field(cid, "學歷")
        job = store.guide_get_repair_job(job_id)
        view = store.guide_candidate_view(cid)
        f = next(x for x in view["fields"] if x["field_name"] == "學歷")

        assert updated["value"] == "法學博士(修復後)"
        assert f["value"] == "法學博士(修復後)"
        assert f["flagged"] is True                     # 標記不自動解除
        assert job["status"] == "done"
        assert job["result_value"] == "法學博士(修復後)"
        assert job["before_value"] == "法學博士"
        assert view["has_uncommitted"] is True           # 值變了 → 未提交
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()


def test_run_repair_job_fails_without_crop(tmp_path):
    store = _store()
    try:
        _seed(store, tmp_path)
        cid = _candidate_id(store, "趙少康")            # 該候選人無任何切圖
        field = store.guide_get_field(cid, "學歷")
        assert field["source_crop_path"] is None

        job_id = store.guide_create_repair_job(cid, "學歷", None)

        def boom(*a, **k):
            raise AssertionError("transcribe_image should not be called when no crop")

        run_repair_job(store, job_id, transcribe_image=boom)

        job = store.guide_get_repair_job(job_id)
        assert job["status"] == "failed"
        assert job["error"]
        # 值未變
        assert store.guide_get_field(cid, "學歷")["value"] == field["value"]
    finally:
        try:
            store.guide_delete_election(ELECTION_ID)
        except Exception:
            pass
        store.close()
