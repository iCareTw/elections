"""網頁匯入公報:一份 PDF → 解析(local 視覺模型)→ 匯入 DB。供 web 背景執行。

progress 回呼:progress(message: str, done: int, total: int)
"""
from __future__ import annotations

from pathlib import Path
from urllib.error import URLError

from src.voter_guide import election_meta
from src.voter_guide.guide_load import load_guide
from src.voter_guide.pipeline import parse_pdf

OUT_DIR = "_out/parsed"


class ImportError_(RuntimeError):
    """匯入失敗,message 為給 user 看的白話說明。"""


def import_pdf(store, pdf_path, *, out_dir: str = OUT_DIR, use_vision: bool = True,
               force: bool = True, progress=None) -> str:
    """解析並匯入一份公報 PDF,回傳 guide_elections.id。失敗丟 ImportError_(白話訊息)。"""
    pdf_path = str(pdf_path)
    out = Path(out_dir)
    try:
        tag = election_meta.from_pdf_path(pdf_path).election_id
    except election_meta.UnknownGazette as exc:
        raise ImportError_(str(exc)) from exc

    def _p(msg, done=0, total=0):
        if progress:
            progress(msg, done, total)

    _p("開始解析")
    try:
        result, yaml_file = parse_pdf(
            pdf_path, tag, out, use_vision,
            progress=lambda i, t, label: _p(label, i, t))
    except (URLError, ConnectionError, TimeoutError, OSError) as exc:
        from src.voter_guide.vision import ENDPOINT
        raise ImportError_(
            f"連不上本機視覺模型({ENDPOINT})。請先啟動視覺模型再匯入。") from exc

    if not result:
        raise ImportError_(
            "解析不到任何候選人 — 這份公報只有掃描圖或版面尚未支援。")

    _p("匯入資料庫中")
    election_id = load_guide(
        store, yaml_path=yaml_file, source_pdf_path=pdf_path,
        crops_base_dir=out, force=force)

    _p("完成", 1, 1)
    return election_id
