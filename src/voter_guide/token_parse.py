"""沒有格線可用時的讀法:只靠文字塊的座標把表格推回來。

有些公報根本沒畫格線(113 臺東),有些格線斷得切不出格子。這時仍然有兩樣東西
可用:欄位名(姓名、學歷、經歷…)一定存在,而且候選人一定排成整齊的列或行。

做法:
  1. 取得帶座標的文字塊 —— PDF 有內嵌文字就直接讀,沒有就整頁 OCR。
  2. `layout.detect_layout` 用欄位名推出表頭軸(橫列或直行、由左而右或右而左)。
  3. 欄位名的位置切出各欄範圍,其餘文字塊依座標歸到所屬欄。
  4. 沿「候選人並排的方向」依間隙分群,每一群就是一位候選人。

因此橫列、直行、掃描圖、純文字都走同一套,差別只在第 1 步的文字塊哪裡來。
"""
from __future__ import annotations

from collections import defaultdict

import pdfplumber

from . import geometry as geo
from . import layout as lay

MIN_FIELDS = 3             # 一位候選人至少要對到幾個欄位才算數
GAP_RATIO = 0.6            # 群間隙大於「中位字高」的幾倍就切成兩位候選人

# layout 的欄位名 → 本專案的欄位鍵
_FIELD_ALIAS = {"候選人別": "號次"}


def _pdf_tokens(page) -> list[lay.Token]:
    """PDF 內嵌文字 → 文字塊。

    以「字元」為起點自己併,不用 extract_text_lines():整條表頭常是同一行
    (『號次•姓名 學歷 經歷』),併成一塊就失去各欄位名自己的座標,推不出欄界。
    """
    chars = [c for c in page.chars if (c.get("text") or "").strip()]
    if not chars:
        return []
    widths = sorted(c["x1"] - c["x0"] for c in chars)
    unit = widths[len(widths) // 2] or 6.0

    lines: list[list[dict]] = []
    for ch in sorted(chars, key=lambda c: (round(c["top"] / max(unit, 1)), c["x0"])):
        for line in lines:
            prev = line[-1]
            if abs(prev["top"] - ch["top"]) <= unit * 0.6:
                line.append(ch)
                break
        else:
            lines.append([ch])

    tokens = []
    for line in lines:
        line.sort(key=lambda c: c["x0"])
        run = [line[0]]
        for ch in line[1:]:
            if ch["x0"] - run[-1]["x1"] > unit * 0.6:   # 字距拉開 = 換一欄
                tokens.append(_token(run))
                run = []
            run.append(ch)
        tokens.append(_token(run))
    return [t for t in tokens if t.text]


def _token(chars: list[dict]) -> lay.Token:
    return lay.Token(
        text=geo.decode("".join(c["text"] for c in chars)).strip(),
        x0=min(c["x0"] for c in chars), x1=max(c["x1"] for c in chars),
        top=min(c["top"] for c in chars), bottom=max(c["bottom"] for c in chars))


def _ocr_tokens(pdf_path: str, page_idx: int, size) -> list[lay.Token]:
    """整頁 OCR → 文字塊,座標換回 PDF 單位。"""
    from . import apple_ocr

    if not apple_ocr.available():
        return []
    img = lay.render_page(pdf_path, page_idx)
    sx, sy = size[0] / img.width, size[1] / img.height
    tokens = []
    for text, _conf, x, y_from_bottom, height in apple_ocr.ocr_blocks(img):
        text = text.strip()
        if not text:
            continue
        # Vision 給的是 0~1 正規化座標、原點在左下
        x0 = x * img.width * sx
        bottom = (1 - y_from_bottom) * img.height * sy
        top = bottom - height * img.height * sy
        tokens.append(lay.Token(text=text, x0=x0, x1=x0 + len(text) * height * img.width * sx,
                                top=top, bottom=bottom))
    return tokens


def _median_height(tokens: list[lay.Token]) -> float:
    heights = sorted(max(1.0, t.bottom - t.top) for t in tokens)
    return heights[len(heights) // 2] if heights else 10.0


def _label_hits(tokens: list[lay.Token], layout: lay.Layout,
                tol: float) -> list[tuple[str, float]]:
    """表頭那條線上的欄位名 → (欄位, 位置),同一塊裡有兩個欄位名就都算。

    『號次•姓名』是常見的合併表頭,只取第一個就會漏掉姓名欄,整份因此讀不出人。
    """
    out = []
    for token in tokens:
        on_axis = token.cx if layout.axis == "x" else token.cy
        if abs(on_axis - layout.axis_pos) > tol:
            continue
        pos = token.cy if layout.axis == "x" else token.cx
        for name in lay.FIELD_LABELS:
            if name in token.text:
                out.append((_FIELD_ALIAS.get(name, name), pos))
    return sorted(out, key=lambda kv: kv[1])


def _bands(hits: list[tuple[str, float]]) -> list[list[tuple[str, float]]]:
    """一頁排成好幾個並排的表格時,整組欄位名會重複出現 → 切成一段一段。"""
    bands: list[list[tuple[str, float]]] = []
    current: list[tuple[str, float]] = []
    seen: set[str] = set()
    for field, pos in hits:
        if field in seen:
            bands.append(current)
            current, seen = [], set()
        current.append((field, pos))
        seen.add(field)
    if current:
        bands.append(current)
    bands = [_collapse(b) for b in bands]
    return [b for b in bands if any(f == "姓名" for f, _ in b)] or bands


def _collapse(band: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """同一個位置上有兩個欄位名時(『號次·姓名』合併表頭)只留一個。

    留姓名:它是分人用的錨點,留成號次的話整欄的值都會歸錯欄,一位也讀不出來。
    """
    out: list[tuple[str, float]] = []
    for field, pos in band:
        if out and abs(out[-1][1] - pos) < 1e-6:
            if field == "姓名":
                out[-1] = (field, pos)
            continue
        out.append((field, pos))
    return out


def _assign_column(columns, pos: float) -> str | None:
    """文字塊落在哪一欄:取位置最接近的欄位名。"""
    if not columns:
        return None
    return min(columns, key=lambda kv: abs(kv[1] - pos))[0]


_NAME_OK = __import__("re").compile(r"^[^\d\s]{2,15}$")


def _looks_like_name(text: str) -> bool:
    text = text.strip()
    return bool(_NAME_OK.match(text)) and not any(
        lab in text for lab in lay.FIELD_LABELS)


def _person_groups(tokens: list[lay.Token], layout: lay.Layout,
                   name_pos: float, tol: float) -> list[list[lay.Token]]:
    """以姓名欄的每一塊當錨點分人:其餘文字塊歸給最近的那個錨點。

    不用「間隙大於某個值就切一刀」——學經歷本來就有大量換行,間隙切法會把
    一位候選人切成十幾份。姓名一定存在且一人一個,拿它當錨點最穩。
    """
    def along(t: lay.Token) -> float:
        return t.cx if layout.person_axis == "x" else t.cy

    def across(t: lay.Token) -> float:
        return t.cy if layout.axis == "x" else t.cx

    anchors = sorted((t for t in tokens
                      if abs(across(t) - name_pos) <= tol and _looks_like_name(t.text)),
                     key=along)
    if not anchors:
        return []
    buckets: list[list[lay.Token]] = [[a] for a in anchors]
    spots = [along(a) for a in anchors]
    for token in tokens:
        if token in anchors:
            continue
        idx = min(range(len(spots)), key=lambda i: abs(spots[i] - along(token)))
        buckets[idx].append(token)
    return buckets


def _build_person(bucket: list[lay.Token], layout: lay.Layout, columns,
                  role: str, page_idx: int) -> geo.Person | None:
    cells: dict[str, list[lay.Token]] = defaultdict(list)
    for token in bucket:
        pos = token.cy if layout.axis == "x" else token.cx
        field = _assign_column(columns, pos)
        if field and field not in ("相片",):
            cells[field].append(token)
    if "姓名" not in cells or len(cells) < MIN_FIELDS:
        return None
    person = geo.Person(role=role, page=page_idx)
    for field, items in cells.items():
        items.sort(key=lambda t: (t.top, t.x0))
        text = "".join(t.text for t in items)
        box = (min(t.x0 for t in items), min(t.top for t in items),
               max(t.x1 for t in items), max(t.bottom for t in items))
        person.cells[field] = geo.Cell(text=text, bbox=box)
    return person


def parse(pdf_path: str, *, role: str, ocr: bool = False) -> list[geo.Group]:
    """回傳每位候選人各自成一組的 Group 清單。`ocr=True` 時不看 PDF 文字層。"""
    groups: list[geo.Group] = []
    with geo.open_pdf(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            size = (int(page.width), int(page.height))
            tokens = [] if ocr else _pdf_tokens(page)
            if not tokens:
                tokens = _ocr_tokens(str(pdf_path), page_idx, size)
            if len(tokens) < 5:
                continue
            layout = lay.detect_layout(_Canvas(size), tokens=tokens)
            if layout is None:
                continue
            tol = max(size) * lay.AXIS_TOLERANCE
            for band in _bands(_label_hits(tokens, layout, tol)):
                name_pos = next((pos for f, pos in band if f == "姓名"), None)
                if name_pos is None:
                    continue
                lo, hi = _band_span(band, tokens, layout)
                body = [t for t in tokens
                        if lo <= (t.cy if layout.axis == "x" else t.cx) <= hi
                        and abs((t.cx if layout.axis == "x" else t.cy)
                                - layout.axis_pos) > tol]
                for bucket in _person_groups(body, layout, name_pos, tol * 2):
                    person = _build_person(bucket, layout, band, role, page_idx)
                    if person is None:
                        continue
                    group = geo.Group(ticket=len(groups) + 1, page=page_idx)
                    group.members.append(person)
                    party = person.cells.pop("政黨", None)
                    if party is not None:
                        group.party_cell = party
                    groups.append(group)
    return groups


def _band_span(band, tokens: list[lay.Token], layout: lay.Layout) -> tuple[float, float]:
    """這一段表格在「跨欄方向」上的範圍:從本段第一欄到下一段開始之前。"""
    positions = [pos for _, pos in band]
    width = max(positions) - min(positions)
    return min(positions) - width * 0.2, max(positions) + width * 0.2


class _Canvas:
    """detect_layout 只用到影像尺寸,不必真的給圖。"""

    def __init__(self, size):
        self.size = size
