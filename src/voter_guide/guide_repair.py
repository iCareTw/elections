"""文字欄 AI 修復執行器:讀 queued job → 以該欄切圖重新判讀 → 更新欄位值。

照片不走此路(照片以手動圈選補正,見 guide_crop)。
"""
from __future__ import annotations


def run_repair_job(store, job_id: int, *, transcribe_image=None) -> None:
    """執行一筆文字欄修復工作。

    transcribe_image 以參數注入(生產用 src.voter_guide.vision.transcribe_image),
    便於測試以假函式替換。
    """
    if transcribe_image is None:
        from src.voter_guide.vision import transcribe_image as _ti
        transcribe_image = _ti

    job = store.guide_get_repair_job(job_id)
    if job is None:
        return

    store.guide_set_repair_running(job_id)

    field = store.guide_get_field(job["guide_candidate_id"], job["target"])
    before = field["value"] if field else None

    if field is None:
        store.guide_finish_repair_job(
            job_id, status="failed", before_value=before,
            error=f"找不到欄位 {job['target']}")
        return

    crop = field["source_crop_path"]
    if not crop:
        store.guide_finish_repair_job(
            job_id, status="failed", before_value=before,
            error="此欄無來源切圖,無法 AI 修復")
        return

    try:
        new_value = transcribe_image(crop, job["target"], job.get("user_note"))
    except Exception as exc:  # noqa: BLE001 - 任何模型/IO 失敗都記進 job
        store.guide_finish_repair_job(
            job_id, status="failed", before_value=before, error=str(exc))
        return

    # 更新為 AI 值(update_source='ai');標記不自動解除,交由 user 檢視後處理
    store.guide_apply_ai_value(field["id"], new_value)
    store.guide_finish_repair_job(
        job_id, status="done", before_value=before, result_value=new_value)
