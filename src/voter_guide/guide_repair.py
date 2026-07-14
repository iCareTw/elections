"""AI 修復執行器:讀 queued job → 以切圖重新判讀 → 更新值。

對象為文字欄(候選人)或組共用政見。照片不走此路(以手動圈選補正,見 guide_crop)。
"""
from __future__ import annotations


def run_repair_job(store, job_id: int, *, transcribe_image=None) -> None:
    """執行一筆修復工作(文字欄或政見)。

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

    # 政見(組共用) vs 文字欄(候選人)
    is_platform = job["target"] == "政見" and job.get("guide_group_id") is not None
    if is_platform:
        ref = store.guide_platform_ref(job["guide_group_id"])
        target_label = "政見"
        apply = lambda val: store.guide_apply_ai_platform(job["guide_group_id"], val)  # noqa: E731
    else:
        ref = store.guide_get_field(job["guide_candidate_id"], job["target"])
        target_label = job["target"]
        apply = (lambda val: store.guide_apply_ai_value(ref["id"], val)) if ref else None  # noqa: E731

    before = ref["value"] if ref else None

    if ref is None:
        store.guide_finish_repair_job(
            job_id, status="failed", before_value=before,
            error=f"找不到修復對象 {job['target']}")
        return

    crop = ref["source_crop_path"]
    if not crop:
        store.guide_finish_repair_job(
            job_id, status="failed", before_value=before,
            error="無來源切圖,無法 AI 修復")
        return

    try:
        new_value = transcribe_image(crop, target_label, job.get("user_note"))
    except Exception as exc:  # noqa: BLE001 - 任何模型/IO 失敗都記進 job
        store.guide_finish_repair_job(
            job_id, status="failed", before_value=before, error=str(exc))
        return

    # 更新為 AI 值(update_source='ai');標記不自動解除,交由 user 檢視後處理
    apply(new_value)
    store.guide_finish_repair_job(
        job_id, status="done", before_value=before, result_value=new_value)
