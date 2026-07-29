"""voter-guide web 路由測試(iteration 2:組視圖)。

用真實 DB seed(reuse test_guide_load helpers,skip if no DB)+ TestClient。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.webapp.app import create_app
from tests.integration.test_guide_load import ELECTION_ID, _load, _store


def _client_with_data(tmp_path):
    store = _store()               # skips if no DB
    store.guide_delete_election(ELECTION_ID)
    _load(store, tmp_path)
    app = create_app(root=tmp_path)
    app.state.store = store        # 注入已連線的 store(不觸發 lifespan)
    return TestClient(app, raise_server_exceptions=True), store


def _ctx(store):
    v = store.guide_group_view(ELECTION_ID, 1)
    gid = v["group"]["id"]
    fid = next(f for f in v["president"]["fields"] if f["field_name"] == "學歷")["id"]
    cid = v["president"]["candidate"]["id"]
    return v, gid, fid, cid


def _teardown(store):
    try:
        store.guide_delete_election(ELECTION_ID)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 瀏覽
# ---------------------------------------------------------------------------

def test_home_and_election(tmp_path):
    client, store = _client_with_data(tmp_path)
    try:
        assert client.get("/guide").status_code == 200
        r = client.get(f"/guide/election/{ELECTION_ID}")
        assert r.status_code == 200
        assert "第16任 2024 總統" in r.text or "第1組" in r.text
    finally:
        _teardown(store)


def test_group_view_shows_both_roles_and_platform(tmp_path):
    client, store = _client_with_data(tmp_path)
    try:
        _, gid, _, _ = _ctx(store)
        r = client.get(f"/guide/group/{gid}")
        assert r.status_code == 200
        assert "總統" in r.text and "副總統" in r.text
        assert "蔡英文" in r.text and "賴清德" in r.text
        assert "政見" in r.text
        assert "開啟公報 PDF" in r.text
        assert "g-f" in r.text            # 蔡英文(女)粉色小人
    finally:
        _teardown(store)


def test_candidate_link_redirects_to_group(tmp_path):
    client, store = _client_with_data(tmp_path)
    try:
        _, gid, _, cid = _ctx(store)
        r = client.get(f"/guide/candidate/{cid}", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == f"/guide/group/{gid}"
    finally:
        _teardown(store)


# ---------------------------------------------------------------------------
# 標記 / 手動 / commit(redirect 回組)
# ---------------------------------------------------------------------------

def test_field_manual_edit_and_uncommitted_banner(tmp_path):
    client, store = _client_with_data(tmp_path)
    try:
        _, gid, fid, _ = _ctx(store)
        r = client.post(f"/guide/field/{fid}/value",
                        data={"group_id": gid, "value": "手動改的學歷"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"/guide/group/{gid}"
        page = client.get(f"/guide/group/{gid}").text
        assert "手動改的學歷" in page and "有未提交變更" in page
    finally:
        _teardown(store)


def test_platform_value_and_commit(tmp_path):
    client, store = _client_with_data(tmp_path)
    try:
        _, gid, _, _ = _ctx(store)
        # 手動填政見
        assert client.post(f"/guide/group/{gid}/platform/value",
                           data={"value": "新政見"}, follow_redirects=False).status_code == 303
        assert "新政見" in client.get(f"/guide/group/{gid}").text
        # commit → v2
        assert client.post(f"/guide/group/{gid}/commit",
                           data={"note": ""}, follow_redirects=False).status_code == 303
        v = store.guide_group_view(ELECTION_ID, 1)
        assert v["latest_version"] == 2 and v["has_uncommitted"] is False
    finally:
        _teardown(store)


def test_version_snapshot_readonly(tmp_path):
    client, store = _client_with_data(tmp_path)
    try:
        _, gid, _, _ = _ctx(store)
        store.guide_group_commit(gid, "v2")
        r = client.get(f"/guide/group/{gid}?version=1")
        assert r.status_code == 200
        assert "唯讀快照" in r.text
    finally:
        _teardown(store)


# ---------------------------------------------------------------------------
# AI 修復觸發 + 輪詢(background monkeypatched)
# ---------------------------------------------------------------------------

def test_field_repair_creates_job(tmp_path, monkeypatch):
    import src.webapp.routes.guide as guidemod

    client, store = _client_with_data(tmp_path)
    try:
        _, gid, fid, _ = _ctx(store)

        def fake_run(store, job_id):
            store.guide_finish_repair_job(job_id, status="done", result_value="修復值")
        monkeypatch.setattr(guidemod, "run_repair_job", fake_run)

        r = client.post(f"/guide/field/{fid}/repair",
                        data={"group_id": gid, "note": "讀錯"})
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        s = client.get(f"/guide/repair/{job_id}/status")
        assert s.status_code == 200 and s.json()["status"] == "done"
    finally:
        _teardown(store)


def test_platform_repair_creates_job(tmp_path, monkeypatch):
    import src.webapp.routes.guide as guidemod

    client, store = _client_with_data(tmp_path)
    try:
        _, gid, _, _ = _ctx(store)          # 第1組政見有切圖
        monkeypatch.setattr(guidemod, "run_repair_job",
                            lambda store, jid: store.guide_finish_repair_job(jid, status="done"))
        r = client.post(f"/guide/group/{gid}/platform/repair", data={"note": "政見錯"})
        assert r.status_code == 200 and "job_id" in r.json()
    finally:
        _teardown(store)


# ---------------------------------------------------------------------------
# PDF / crop 安全
# ---------------------------------------------------------------------------

def test_pdf_route_rejects_outside_path(tmp_path):
    client, store = _client_with_data(tmp_path)
    try:
        # seed 的 source_pdf_path 為 /fake/...,不在 _data/_out → 403
        r = client.get(f"/guide/election/{ELECTION_ID}/pdf")
        assert r.status_code in (403, 404)
    finally:
        _teardown(store)


def test_crop_route_path_safety(tmp_path):
    client, store = _client_with_data(tmp_path)
    try:
        assert client.get("/guide/crop", params={"path": "/etc/passwd"}).status_code == 403
        assert client.get("/guide/crop", params={"path": "../../etc/passwd"}).status_code == 403
    finally:
        _teardown(store)


# ---------------------------------------------------------------------------
# 匯入公報 PDF
# ---------------------------------------------------------------------------

def _mk_pdf(tmp_path, name="113年第16任總統副總統.pdf"):
    p = tmp_path / "_data" / "voter_guide" / "president" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4 fake")
    return p


def test_import_page_lists_pdfs(tmp_path):
    client, store = _client_with_data(tmp_path)
    try:
        _mk_pdf(tmp_path)
        r = client.get("/guide/import")
        assert r.status_code == 200
        assert "匯入公報" in r.text and "113年第16任" in r.text
    finally:
        _teardown(store)


def test_import_row_shows_last_failure_with_date(tmp_path):
    """失敗原因長在該份公報那一列,並附日期,避免舊紀錄被當成現況。"""
    client, store = _client_with_data(tmp_path)
    try:
        p = _mk_pdf(tmp_path, "089年第10任總統副總統.pdf")
        job_id = store.guide_create_import_job(str(p.resolve()), p.stem)
        store.guide_finish_import_job(job_id, status="failed", error="解析不到任何候選人組別")

        rows = client.get("/guide/import/jobs").json()["rows"]
        row = next(r for r in rows if r["name"] == p.stem)
        assert row["status"] == "failed"
        assert row["error"] == "解析不到任何候選人組別"
        assert row["when"]                      # 有日期才看得出是不是舊紀錄
        assert not row["imported"] and not row["active"]   # 仍可重選重跑

        r = client.get("/guide/import")
        assert "解析不到任何候選人組別" in r.text
        assert "匯入佇列" not in r.text          # 佇列面板已移除
    finally:
        with store.connect() as conn:
            store._setup_conn(conn)
            conn.execute("DELETE FROM guide_import_jobs WHERE pdf_path = %s",
                         (str(p.resolve()),))
        _teardown(store)


def test_import_rejects_outside_path(tmp_path):
    client, store = _client_with_data(tmp_path)
    try:
        r = client.post("/guide/import", data={"pdf": "/etc/passwd"}, follow_redirects=False)
        assert r.status_code == 400
    finally:
        _teardown(store)


def test_import_start_and_status(tmp_path, monkeypatch):
    import time
    import src.voter_guide.guide_import as gi

    client, store = _client_with_data(tmp_path)
    try:
        _mk_pdf(tmp_path, "x.pdf")

        def fake_import(store, p, progress=None):
            if progress:
                progress("完成", 1, 1)
            return "president_2024_16"
        monkeypatch.setattr(gi, "import_pdf", fake_import)

        r = client.post("/guide/import",
                        data={"pdf": "_data/voter_guide/president/x.pdf"})
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        s = {"status": "running"}
        for _ in range(60):
            s = client.get(f"/guide/import/status/{job_id}").json()
            if s["status"] != "running":
                break
            time.sleep(0.05)
        assert s["status"] == "done" and s["election_id"] == "president_2024_16"
    finally:
        _teardown(store)
