"""網頁匯入公報:一份 PDF → 解析(local 視覺模型)→ 匯入 DB。供 web 背景執行。

progress 回呼:progress(message: str, done: int, total: int)
"""
from __future__ import annotations

from pathlib import Path

from src.voter_guide.guide_load import load_guide
from src.voter_guide.pipeline import parse_pdf, _pdf_session_year

OUT_DIR = "_out/parsed"


def import_pdf(store, pdf_path, *, out_dir: str = OUT_DIR,
               election_type: str = "president", use_vision: bool = True,
               force: bool = True, progress=None) -> str:
    """解析並匯入一份公報 PDF,回傳 guide_elections.id。"""
    pdf_path = str(pdf_path)
    out = Path(out_dir)
    _, minguo = _pdf_session_year(pdf_path)
    tag = str(minguo) if minguo else Path(pdf_path).stem

    def _p(msg, done=0, total=0):
        if progress:
            progress(msg, done, total)

    _p("開始解析")
    _, yaml_file = parse_pdf(
        pdf_path, tag, out, use_vision,
        progress=lambda i, t, label: _p(label, i, t))

    _p("匯入資料庫中")
    election_id = load_guide(
        store, yaml_path=yaml_file, source_pdf_path=pdf_path,
        crops_base_dir=out, election_type=election_type, force=force)

    _p("完成", 1, 1)
    return election_id
