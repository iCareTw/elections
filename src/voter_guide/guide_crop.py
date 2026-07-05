"""依 PDF 頁 + bbox 座標裁切照片,供 web 手動圈選補正照片使用。

不做 AI:純幾何裁切。座標為 PDF 頁的 (x0, top, x1, bottom),單位 pt。
"""
from __future__ import annotations

from pathlib import Path

from src.voter_guide.vision import crop_cell


def crop_photo(pdf_path, page: int, bbox, dest) -> str:
    """從 pdf_path 的第 page(0-based)頁,依 bbox 裁出照片存到 dest,回傳存檔路徑。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = crop_cell(pdf_path, page, tuple(bbox))
    img.save(dest)
    return str(dest)
