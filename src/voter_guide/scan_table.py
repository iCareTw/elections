"""看圖切表:PDF 裡沒有可抽取的文字時,把整頁畫出來、自己找格線,再逐格 OCR。

適用於「文字被轉成向量曲線」或「整頁只是一張掃描照片」的公報(宜蘭、屏東、澎湖、
臺東、連江)。與 geometry / table_parse 輸出同一組 dataclass,pipeline 可互換。

不預設版面長相:欄位名(姓名、學歷…)共線的方向由 `layout` 推導出來,
- 欄位名排成一橫列 → 每個欄位名標記一「欄」,候選人是一「列」;
- 欄位名排成一直行 → 反過來,候選人是一「欄」(早期直書公報)。

格線給邊界、欄位名給名字:欄位名不必每個都被 OCR 認出,認出幾個就定幾欄。
"""
from __future__ import annotations

import re

from PIL import Image

from . import geometry as geo
from . import verify
from .apple_ocr import read_cell
from .layout import Layout, detect_layout, render_page
from .scan_grid import build_grid, even_runs

SCALE = 2.0            # 找格線用的倍率
READ_SCALE = 4.0       # 讀字用的倍率(OCR 在小字上會整格讀空)
INSET = 3              # px,往內縮避免吃到框線
MIN_BAND = 12          # px,比這薄的帶是框線殘影不是資料列
MAX_NAME = 24          # 姓名格超過這長度就不是姓名(是footer或誤切)

_FIELDS = ("號次", "相片", "姓名", "出生年月日", "性別", "出生地",
           "政黨", "學歷", "經歷", "政見")
# layout 用的欄位名與本專案欄位名的對照(layout 認的是公報上的字面)
_ALIAS = {"推薦之政黨": "政黨", "登記方式": "政黨"}


def _bands(rules: list[int]) -> list[tuple[int, int]]:
    return [(lo, hi) for lo, hi in zip(rules, rules[1:]) if hi - lo >= MIN_BAND]


def _band_at(bands: list[tuple[int, int]], pos: float) -> tuple[int, int] | None:
    return next((b for b in bands if b[0] <= pos <= b[1]), None)


def _label_of(text: str) -> str | None:
    """表頭格讀出來的字 → 欄位名。直書欄名字序會亂,故比對字集不比對字序。"""
    flat = re.sub(r"\s+", "", text)
    if not flat or len(flat) > 12:
        return None
    for raw in list(_ALIAS) + list(_FIELDS):
        if raw in flat or sorted(raw) == sorted(flat[:len(raw)]):
            return _ALIAS.get(raw, raw)
    return None


def _person_bands(bands: list[tuple[int, int]], header: tuple[int, int],
                  ) -> list[tuple[int, int]]:
    """候選人各佔一帶:表頭之後、等距的那一串(其後的法條說明不等距,會被濾掉)。"""
    after = [b for b in bands if b[0] >= header[1] - MIN_BAND]
    if len(after) < 3:
        return after
    keep = set(even_runs([b[0] for b in after]))
    run = [b for b in after if b[0] in keep]
    return run if len(run) >= 2 else after


def _photo_bands(page_images: list[dict], scale: float, header: tuple[int, int],
                 limit: int) -> list[tuple[int, int]] | None:
    """用相片定候選人帶。

    格線在有些公報裡被切得很碎(欄內還有分隔線),候選人邊界跟著失準;
    但相片是一人一張、大小一致、等距排列,拿它當錨點比格線可靠。
    """
    photos = [im for im in page_images
              if (im["x1"] - im["x0"]) >= 40 and (im["bottom"] - im["top"]) >= 50]
    if len(photos) < 2:
        return None
    heights = sorted((im["bottom"] - im["top"]) for im in photos)
    mid = heights[len(heights) // 2]
    photos = [im for im in photos if abs((im["bottom"] - im["top"]) - mid) <= mid * 0.25]
    centers = sorted(((im["top"] + im["bottom"]) / 2) * scale for im in photos)
    if len(centers) < 2:
        return None
    step = min(b - a for a, b in zip(centers, centers[1:]))
    edges = [max(header[1], centers[0] - step / 2)]
    edges += [(a + b) / 2 for a, b in zip(centers, centers[1:])]
    edges.append(min(limit, centers[-1] + step / 2))
    return [(int(a), int(b)) for a, b in zip(edges, edges[1:]) if b - a >= MIN_BAND]


def _infer_name_band(fields: dict[str, tuple[int, int]],
                     bands: list[tuple[int, int]]) -> None:
    """姓名欄名沒讀出來時用位置補:公報上姓名一定緊接在相片之後。"""
    if "姓名" in fields or "相片" not in fields:
        return
    after = [b for b in bands if b[0] >= fields["相片"][1]]
    if after:
        fields["姓名"] = after[0]


def _box(field: tuple[int, int], person: tuple[int, int], axis: str
         ) -> tuple[int, int, int, int]:
    """(欄位帶, 候選人帶) → 圖上的方框。"""
    if axis == "y":                      # 欄位名排成橫列:欄位是 x、候選人是 y
        return (field[0], person[0], field[1], person[1])
    return (person[0], field[0], person[1], field[1])


def _read(img: Image.Image, box, *, keep_lines: bool) -> str:
    x0, top, x1, bottom = box
    crop = img.crop((x0 + INSET, top + INSET, x1 - INSET, bottom - INSET))
    if crop.width < 8 or crop.height < 8:
        return ""
    lines = read_cell(crop)
    return "\n".join(lines) if keep_lines else "".join(lines)


def _photo_of(page_images: list[dict], box_pt, band_pt) -> tuple | None:
    """相片:優先取落在候選人帶內的內嵌影像(向量 PDF 的相片仍是真影像)。"""
    lo, hi = band_pt
    inside = [im for im in page_images if lo <= (im["top"] + im["bottom"]) / 2 <= hi]
    if inside:
        im = max(inside, key=lambda i: (i["x1"] - i["x0"]) * (i["bottom"] - i["top"]))
        return (im["x0"], im["top"], im["x1"], im["bottom"])
    return box_pt


def _parse_page(pdf_path: str, page_idx: int, page_images: list[dict],
                role: str) -> list[geo.Group]:
    small = render_page(pdf_path, page_idx, SCALE)
    layout = detect_layout(small)
    if layout is None:
        return []

    grid = build_grid(small, do_deskew=False)
    field_rules, person_rules = ((grid.xs, grid.ys) if layout.axis == "y"
                                 else (grid.ys, grid.xs))
    field_bands = _bands(field_rules)
    header = _band_at(_bands(person_rules), layout.axis_pos)
    if header is None or not field_bands:
        return []

    big = render_page(pdf_path, page_idx, READ_SCALE)
    zoom = READ_SCALE / SCALE

    def read(box) -> str:
        return _read(big, tuple(int(v * zoom) for v in box), keep_lines=False)

    # 欄位名逐格重讀:整頁 OCR 常漏掉幾個標籤,但表頭那一格單獨放大讀得出來
    fields: dict[str, tuple[int, int]] = {}
    for fband in field_bands:
        name = _label_of(read(_box(fband, header, layout.axis)))
        if name:
            fields.setdefault(name, fband)
    _infer_name_band(fields, field_bands)
    if "姓名" not in fields:
        return []

    people = _person_bands(_bands(person_rules), header)
    if not people:
        return []

    groups = _extract(big, zoom, read, fields, people, layout.axis,
                      page_images, page_idx, role)
    # 相片一人一張,是候選人數的第二個來源;格線切出來的人數對不上就改用相片切
    if layout.axis == "y":
        by_photo = _photo_bands(page_images, SCALE, header, small.height)
        if by_photo and len(by_photo) != len(groups):
            groups = _extract(big, zoom, read, fields, by_photo, layout.axis,
                              page_images, page_idx, role) or groups
    return groups


def _extract(big, zoom: float, read, fields: dict[str, tuple[int, int]],
             people: list[tuple[int, int]], axis: str, page_images: list[dict],
             page_idx: int, role: str) -> list[geo.Group]:
    groups: list[geo.Group] = []
    for band in people:
        cells: dict[str, geo.Cell] = {}
        for name, fband in fields.items():
            if name in ("號次", "相片"):
                continue
            box = _box(fband, band, axis)
            text = _read(big, tuple(int(v * zoom) for v in box),
                         keep_lines=name in verify.BULLET_FIELDS)
            if text:
                # bbox 換回 PDF 座標,校對台才切得出對照圖、也才能請模型複讀
                cells[name] = geo.Cell(text=text,
                                       bbox=tuple(v / SCALE for v in box))
        name_text = re.sub(r"\s+", "", cells.get("姓名", geo.Cell("", None)).text)
        if not name_text or len(name_text) > MAX_NAME:
            continue

        person = geo.Person(role=role, page=page_idx)
        person.cells = cells
        ticket = len(groups) + 1
        if "號次" in fields:
            m = re.search(r"\d+", read(_box(fields["號次"], band, axis)))
            if m:
                ticket = int(m.group())
        if "相片" in fields:
            box_pt = tuple(v / SCALE for v in _box(fields["相片"], band, axis))
            band_pt = (band[0] / SCALE, band[1] / SCALE)
            person.photo_bbox = _photo_of(page_images, box_pt, band_pt) \
                if axis == "y" else box_pt

        group = geo.Group(ticket=ticket, page=page_idx)
        group.members.append(person)
        group.party_cell = person.cells.pop("政黨", None)
        groups.append(group)
    return groups


def parse(pdf_path: str, *, role: str) -> list[geo.Group]:
    """整份公報 → Group 清單(每位候選人各自成一組)。推不出版面時回空清單。"""
    import pdfplumber

    groups: list[geo.Group] = []
    seen: set[tuple[int, str]] = set()
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        images = [list(p.images) for p in pdf.pages]
    for page_idx in range(page_count):
        for group in _parse_page(pdf_path, page_idx, images[page_idx], role):
            name = re.sub(r"\s+", "", group.members[0].cells["姓名"].text)
            key = (group.ticket, name)
            if key in seen:
                continue
            seen.add(key)
            groups.append(group)
    return groups
