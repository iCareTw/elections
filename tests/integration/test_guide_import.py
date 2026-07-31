"""真實匯入流程測試(不 mock import_pdf)。需本機 PDF fixture 與 DB,缺則 skip。"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.voter_guide.guide_import import ImportError_, import_pdf
from tests.integration.test_guide_load import _store

ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "_data" / "voter_guide" / "president"
VISION_CACHE = ROOT / "_out" / "parsed" / "vision_cache" / "113.json"


def _pdf(name: str) -> Path:
    p = PDF_DIR / name
    if not p.exists():
        pytest.skip(f"缺 PDF fixture: {name}")
    return p


def test_import_rejects_unparseable_layout(monkeypatch):
    """解析不到候選人 → 明確報錯,而且不留下一場空選舉。

    版面支援度會隨解析器成長而變(085 一度解析不了,現在可以),所以不綁特定年份,
    直接讓解析結果為空來驗這條錯誤路徑。
    """
    p = _pdf("085年第9任總統副總統.pdf")
    monkeypatch.setattr("src.voter_guide.guide_import.parse_pdf",
                        lambda *a, **kw: ([], Path("unused.yaml")))
    store = _store()
    try:
        store.init_schema()
        with pytest.raises(ImportError_):
            import_pdf(store, str(p), progress=lambda *a: None)
        assert not store.guide_election_exists("president_1996_9")
    finally:
        store.close()


def test_import_113_end_to_end():
    """113 完整匯入(靠既有 vision 快取,免打模型);缺快取則 skip 避免拖慢/打模型。"""
    p = _pdf("113年第16任總統副總統.pdf")
    if not VISION_CACHE.exists():
        pytest.skip("無 113 vision 快取,略過(避免呼叫本機模型)")
    store = _store()
    try:
        store.init_schema()
        eid = import_pdf(store, str(p), progress=lambda *a: None)
        assert eid == "president_2024_16"
        assert len(store.guide_candidates_of(eid)) == 6   # 3 組 × 正副
    finally:
        try:
            store.guide_delete_election("president_2024_16")
        except Exception:
            pass
        store.close()
