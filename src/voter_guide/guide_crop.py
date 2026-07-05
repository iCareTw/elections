"""依 PDF 頁 + bbox 座標裁切照片,供 web 手動圈選補正照片使用。

不做 AI:純幾何裁切。座標為 PDF 頁的 (x0, top, x1, bottom),單位 pt。
"""
from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium

from src.voter_guide.vision import crop_cell


def crop_photo(pdf_path, page: int, bbox, dest) -> str:
    """從 pdf_path 的第 page(0-based)頁,依 bbox 裁出照片存到 dest,回傳存檔路徑。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = crop_cell(pdf_path, page, tuple(bbox))
    img.save(dest)
    return str(dest)


def page_size_pt(pdf_path, page: int) -> tuple[float, float]:
    """回傳該頁 (width, height),單位 PDF pt。"""
    pdoc = pdfium.PdfDocument(str(pdf_path))
    try:
        return tuple(pdoc[page].get_size())
    finally:
        pdoc.close()


def crop_photo_frac(pdf_path, page: int, frac_bbox, dest) -> str:
    """frac_bbox 為 (x0,y0,x1,y1),各值 0~1(相對頁面)。換算成 pt 後裁切。

    前端在渲染後的頁面圖上框選,送回相對比例即可,免於處理縮放。
    """
    x0f, y0f, x1f, y1f = frac_bbox
    x0f, x1f = sorted((float(x0f), float(x1f)))
    y0f, y1f = sorted((float(y0f), float(y1f)))
    w, h = page_size_pt(pdf_path, page)
    bbox = (x0f * w, y0f * h, x1f * w, y1f * h)
    return crop_photo(pdf_path, page, bbox, dest)


def render_page(pdf_path, page: int, scale: float = 2.0):
    """整頁渲染成 PIL 圖(供 web 圈選頁顯示)。"""
    pdoc = pdfium.PdfDocument(str(pdf_path))
    try:
        return pdoc[page].render(scale=scale).to_pil()
    finally:
        pdoc.close()
