"""B 路：盲讀裁判。把單一欄位裁成小圖，發無狀態呼叫請本機視覺模型逐字讀出。

獨立性：呼叫只給『圖 + 要讀哪個欄位』，不給參選人是誰、不給 A 路答案，
因此無法附和(球員裁判分離)。結果寫入磁碟快取，重跑不重打模型。
"""
from __future__ import annotations

import base64
import io
import json
import os
import urllib.request
from pathlib import Path

import pypdfium2 as pdfium

ENDPOINT = os.environ.get("LMSTUDIO_URL", "http://localhost:1234") + "/v1/chat/completions"
MODEL = os.environ.get("VOTER_GUIDE_VISION_MODEL", "google/gemma-4-e4b")
RENDER_SCALE = 3.0
PAD = 4


def _b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def crop_cell(pdf_path: str | Path, page_idx: int,
              bbox: tuple[float, float, float, float], scale: float = RENDER_SCALE):
    pdoc = pdfium.PdfDocument(str(pdf_path))
    try:
        pil = pdoc[page_idx].render(scale=scale).to_pil()
    finally:
        pass
    x0, top, x1, bottom = bbox
    crop = pil.crop((max(0, int(x0 * scale) - PAD), max(0, int(top * scale) - PAD),
                     int(x1 * scale) + PAD, int(bottom * scale) + PAD))
    pdoc.close()
    return crop


def _ask(img, field_name: str, timeout: int, note: str | None = None) -> str:
    base = f"這是台灣選舉公報中『{field_name}』欄位的截圖。"
    if field_name in ("學歷", "經歷"):
        fmt = ("請逐條讀出並以 Markdown 無序清單輸出，每一項獨立一行、以 `- ` 開頭。"
               "數字一律用阿拉伯數字。只輸出清單本身，不要任何前言或說明。")
    elif field_name == "政見":
        fmt = ("請完整讀出政見內容，並用 Markdown 適當排版以便閱讀："
               "有標題用 `## `，並列或分點用 `- ` 清單，段落之間空一行。"
               "數字一律用阿拉伯數字。只輸出內容本身，不要任何前言或說明。")
    else:
        fmt = ("請逐字讀出該欄位的全部文字，原樣輸出(含頓號、括號)。"
               "數字一律用阿拉伯數字(例如 31、民國48年8月6日)，不要用中文數字。"
               "只輸出文字本身，不要加任何說明、標題或標點以外的符號。")
    prompt = base + fmt
    if note:
        prompt += f"\n人工提示(前次判讀有誤，請據此重新判讀)：{note}"
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64," + _b64(img)}},
        ]}],
        "temperature": 0,
    }
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    return data["choices"][0]["message"]["content"].strip()


class VisionCache:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, str] = {}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, key: str):
        return self.data.get(key)

    def set(self, key: str, value: str):
        self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                             encoding="utf-8")


def transcribe(pdf_path, page_idx, bbox, field_name, *, key, cache: VisionCache | None,
               crop_save: Path | None = None, timeout: int = 600) -> str:
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached
    img = crop_cell(pdf_path, page_idx, bbox)
    if crop_save is not None:
        crop_save.parent.mkdir(parents=True, exist_ok=True)
        img.save(crop_save)
    text = _ask(img, field_name, timeout)
    if cache is not None:
        cache.set(key, text)
    return text


def transcribe_image(png_path, field_name: str, note: str | None = None,
                     *, timeout: int = 600) -> str:
    """讀已存好的切圖 PNG，帶入(可選的)人工提示，請本機視覺模型重新判讀該欄。

    供 web 端 AI 修復使用:不重算 PDF 幾何,直接吃 source_crop_path 那張圖。
    """
    from PIL import Image

    img = Image.open(png_path)
    return _ask(img, field_name, timeout, note=note)
