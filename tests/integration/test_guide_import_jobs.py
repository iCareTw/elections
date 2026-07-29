"""匯入佇列清單:同一份公報只呈現最新一筆結果。"""
from __future__ import annotations

from tests.integration.test_guide_load import _store

PDF = "/tmp/test-guide-import-jobs/105年第14任總統副總統.pdf"


def _cleanup(store, path):
    with store.connect() as conn:
        store._setup_conn(conn)
        conn.execute("DELETE FROM guide_import_jobs WHERE pdf_path = %s", (path,))


def test_failed_job_hidden_once_rerun_succeeds():
    store = _store()
    try:
        _cleanup(store, PDF)
        failed = store.guide_create_import_job(PDF, "105年第14任總統副總統")
        store.guide_finish_import_job(failed, status="failed", error="解析不到任何候選人組別")
        retried = store.guide_create_import_job(PDF, "105年第14任總統副總統")
        store.guide_finish_import_job(retried, status="done", message="完成",
                                      election_id="president_2016_14")

        shown = [j for j in store.guide_list_import_jobs() if j["pdf_path"] == PDF]
        assert [j["id"] for j in shown] == [retried]
        assert shown[0]["status"] == "done"
    finally:
        _cleanup(store, PDF)
        store.close()


def test_failed_job_still_shown_when_it_is_the_latest():
    """剛失敗時仍要看得到,否則按下匯入沒有任何回饋。"""
    store = _store()
    try:
        _cleanup(store, PDF)
        failed = store.guide_create_import_job(PDF, "105年第14任總統副總統")
        store.guide_finish_import_job(failed, status="failed", error="模型未啟動")

        shown = [j for j in store.guide_list_import_jobs() if j["pdf_path"] == PDF]
        assert [j["id"] for j in shown] == [failed]
        assert shown[0]["error"] == "模型未啟動"
    finally:
        _cleanup(store, PDF)
        store.close()
