"""單人一筆的公報表格解析(縣市長)。

跟總統公報的差別有兩點,都由這裡吸收:

1. **一份 PDF 常同時刊多場選舉**(市長 + 議員各選舉區)。用段落標題(「市長候選人」、
   「第12選舉區(平地原住民)候選人」)把不屬於本場的候選人濾掉;比對是按「候選人所在
   的 y 位置落在哪個標題之後」,因此連同一張表格裡上半市長、下半議員也切得開。

2. **各縣市自己排版,版式由表格自身判定**,不看縣市名:

   | 版式 | 長相 | 例 |
   |---|---|---|
   | H(表頭列) | 一列全是欄名,其後每列一位候選人 | 桃園、臺中、彰化 |
   | I(內嵌欄名) | 每位候選人一張卡片,欄名與值成對相鄰,多人並排 | 新北、臺南 |
   | V(直式欄名) | 一張表格一位候選人,欄名在上、值在正下方 | 臺北 |

   欄名右邊直接是資料 → 卡片列(I);否則是表頭列(H)。整組欄名重複代表同一列
   並排多位候選人(新竹市),切成多組欄位對照。
   直書欄名被列邊界切成上下兩段時(金門的「號／次」)先併回去,再照 H 處理。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import pdfplumber

from . import geometry as geo

# 段落標題:本場要留的 / 夾帶其他選舉要濾掉的
SECTION_KEEP = re.compile(r"[市縣]長")
SECTION_SKIP = re.compile(r"議員|選舉區|代表|里長|鄉鎮市長")
_HEADING_MAX = 30          # 標題行長度上限(超過就是內文,不是標題)

# 欄名 → 正規化後可能的寫法(比對用完全相等,避免把值當欄名)
_LABEL_FORMS = {
    "號次": ("號次", "號碼"),
    "相片": ("相片", "照片"),
    "姓名": ("姓名",),
    "出生年月日": ("出生年月日", "出生年月"),
    "性別": ("性別",),
    "出生地": ("出生地",),
    "政黨": ("推薦之政黨", "政黨", "登記方式"),
    "學歷": ("學歷",),
    "經歷": ("經歷",),
    "政見": ("政見",),
}


def _pure_label(text: str) -> str | None:
    """整格就是一個欄名時回欄名。

    直書欄名被排版切成兩段後字序會交錯(『出年月日生』其實是『出生年月日』),
    所以三字以上的欄名比對「字集」而不比對字序。
    """
    for name, forms in _LABEL_FORMS.items():
        for form in forms:
            if text == form:
                return name
            if len(form) >= 3 and len(text) == len(form) and sorted(text) == sorted(form):
                return name
    return None


def _split_label(text: str) -> tuple[str, str] | None:
    """欄名和值黏在同一格時 → (欄名, 值)。"""
    for name, forms in _LABEL_FORMS.items():
        for form in forms:
            n = len(form)
            if len(text) < n:
                continue
            if text[:n] == form or (n >= 3 and sorted(text[:n]) == sorted(form)):
                return name, text[n:]
    return None


# 欄名同時列出兩欄的合併寫法(如「號次·姓名」),值也黏成「1張家豪」
_COMBINED = re.compile(r"^號次\W?姓名$")
_TICKET_NAME = re.compile(r"^(\d{1,2})\s*(\S{1,20})$")

# 出生年月日/性別/出生地 疊在同一格的合併欄名
_BASIC_LABEL = "個人資料"


@dataclass
class _Grid:
    """一張表格攤平成 (列, 欄) 的文字與 bbox,兩種版式共用。

    `text` 去掉空白供比對欄名,`raw` 保留原樣供取值;`fixed` 記下被
    `_unsplit_labels` 修過的格(那些格的值只剩正規化後的文字可用)。
    """
    text: list[list[str]]
    raw: list[list[str]]
    bbox: list[list[tuple[float, float, float, float] | None]]
    row_top: list[float]
    page: int
    fixed: set[tuple[int, int]] = dc_field(default_factory=set)

    @property
    def nrows(self) -> int:
        return len(self.text)

    def value(self, ri: int, ci: int) -> str:
        return self.text[ri][ci] if (ri, ci) in self.fixed else self.raw[ri][ci]

    def labels(self, ri: int) -> list[tuple[int, str]]:
        out = []
        for ci, t in enumerate(self.text[ri]):
            name = _pure_label(t)
            if name:
                out.append((ci, name))
        return out


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", "", geo.decode(s)).replace("　", "")


# --------------------------------------------------------------- 段落標題

_HEADING = re.compile(r"候選人\s*[:：]?$")   # 標題以「候選人」收尾,才不會誤抓經歷內文


def _marker_of(text: str) -> bool | None:
    """這行/這格是不是段落標題;是的話回傳「屬於本場嗎」。"""
    t = _norm(text)
    if len(t) > _HEADING_MAX or not _HEADING.search(t):
        return None
    if SECTION_SKIP.search(t):
        return False
    if SECTION_KEEP.search(t):
        return True
    return None


def _markers(pdf, page_grids: list[list[_Grid]]) -> list[tuple[int, float, bool]]:
    """全文件的段落標題,依出現順序回 (頁, y, 是否本場)。

    標題可能是內文的一行,也可能是表格裡的一格(臺中把「選舉類別」做成表格首欄),
    兩種都收。
    """
    out: list[tuple[int, float, bool]] = []
    for pi, page in enumerate(pdf.pages):
        try:
            lines = page.extract_text_lines()
        except Exception:                      # 沒有內嵌文字的頁
            lines = []
        for ln in lines:
            keep = _marker_of(ln.get("text"))
            if keep is not None:
                out.append((pi, float(ln["top"]), keep))
        for grid in page_grids[pi]:
            for ri in range(grid.nrows):
                for t in grid.text[ri]:
                    keep = _marker_of(t)
                    if keep is not None:
                        out.append((pi, grid.row_top[ri], keep))
    out.sort(key=lambda m: (m[0], m[1]))
    return out


def _in_section(markers, page: int, top: float) -> bool:
    """某位候選人(頁 page、y=top)是否屬於本場。沒有任何標題時視為屬於本場。"""
    active = True
    for mp, my, keep in markers:
        if mp < page or (mp == page and my <= top):
            active = keep
        else:
            break
    return active


# --------------------------------------------------------------- 表格 → 網格

def _to_grid(page, table, page_idx: int) -> _Grid:
    extracted = table.extract()
    ncols = max((len(r) for r in extracted), default=0)
    text, raw, bbox, row_top = [], [], [], []
    for ri, row in enumerate(extracted):
        trow, rrow, brow = [], [], []
        cells = table.rows[ri].cells
        for ci in range(ncols):
            cell_text = row[ci] if ci < len(row) else ""
            trow.append(_norm(cell_text))
            rrow.append(geo.decode(cell_text))
            c = cells[ci] if ci < len(cells) else None
            brow.append(tuple(c) if c else None)
        text.append(trow)
        raw.append(rrow)
        bbox.append(brow)
        row_top.append(float(table.rows[ri].bbox[1]))
    grid = _Grid(text=text, raw=raw, bbox=bbox, row_top=row_top, page=page_idx)
    _unsplit_labels(grid)
    return grid


# ------------------------------------------------------------ 欄名被切成兩列

def _unsplit_labels(grid: _Grid) -> None:
    """直書欄名被列邊界切成上下兩段時(金門),把欄名併回上列,值留在下列。

    公報把『號次』排成一直行,表格線正好切在『號』與『次』之間,
    於是下列那格變成「次+值」。就地修掉,後面就能照一般表頭列處理。
    """
    for ri in range(grid.nrows - 1):
        fixed: dict[int, tuple[str, str]] = {}
        for ci in range(len(grid.text[ri])):
            head = grid.text[ri][ci]
            if not head or _pure_label(head):
                continue
            got = _split_label(head + grid.text[ri + 1][ci])
            if got:
                fixed[ci] = got
        if len(fixed) >= 3 and any(n == "姓名" for n, _ in fixed.values()):
            for ci, (name, rest) in fixed.items():
                grid.text[ri][ci] = name
                grid.text[ri + 1][ci] = rest
                grid.fixed.add((ri + 1, ci))


# --------------------------------------------------------------- 版式判定

def _anchor_rows(grid: _Grid) -> list[tuple[int, int]]:
    """所有「號次」欄名的位置(內嵌版式每位候選人一個;表頭版式只在表頭列)。"""
    hits = []
    for ri in range(grid.nrows):
        for ci, t in enumerate(grid.text[ri]):
            if _pure_label(t) == "號次" or _COMBINED.match(t):
                hits.append((ri, ci))
    return hits


def _is_card_row(grid: _Grid, ri: int) -> bool:
    """欄名右邊直接就是資料 → 這列是候選人卡片(版式 I),不是表頭列。

    表頭列裡欄名旁邊只會是別的欄名或空格;偶爾一格合併雜訊會誤判,所以要兩處以上。
    """
    row = grid.text[ri]
    n = 0
    for ci, name in grid.labels(ri):
        nxt = row[ci + 1] if ci + 1 < len(row) else ""
        if nxt and not _pure_label(nxt):
            n += 1
    return n >= 2


def _header_rows(grid: _Grid) -> list[int]:
    """表頭列:含姓名(或號次·姓名)與其他欄名,且不是候選人卡片列。"""
    out = []
    for ri in range(grid.nrows):
        names = [n for _, n in grid.labels(ri)]
        has_name = "姓名" in names or any(_COMBINED.match(t) for t in grid.text[ri])
        has_more = any(n in ("學歷", "經歷", "政見", "出生年月日") for n in names)
        if has_name and has_more and not _is_card_row(grid, ri):
            out.append(ri)
    return out


# --------------------------------------------------------------- 版式 H

def _header_blocks(grid: _Grid, ri: int) -> list[dict[str, int]]:
    """表頭列 → 一或多組欄位對照。

    整組欄名重複出現代表同一列並排 N 位候選人(新竹市把兩位排在同一列),
    欄名重覆時就切出下一組。
    """
    blocks: list[dict[str, int]] = []
    cur: dict[str, int] = {}
    for ci, name in grid.labels(ri):
        if name in cur:
            blocks.append(cur)
            cur = {}
        cur[name] = ci
    for ci, t in enumerate(grid.text[ri]):
        if _COMBINED.match(t):
            (blocks[0] if blocks and not cur else cur).setdefault("號次·姓名", ci)
    if cur:
        blocks.append(cur)
    return blocks


_Record = tuple[dict[str, tuple[int, int]], tuple[int, int, int, int]]


def _records_style_h(grid: _Grid) -> list[_Record]:
    """表頭列之後、有姓名的每一列各是一位候選人。"""
    headers = _header_rows(grid)
    ncols = len(grid.text[0]) if grid.nrows else 0
    out: list[_Record] = []
    for hi, header_ri in enumerate(headers):
        stop = headers[hi + 1] if hi + 1 < len(headers) else grid.nrows
        blocks = _header_blocks(grid, header_ri)
        starts = [min(b.values()) for b in blocks]
        for bi, colmap in enumerate(blocks):
            name_ci = colmap.get("姓名", colmap.get("號次·姓名"))
            if name_ci is None:
                continue
            c0 = starts[bi]
            c1 = starts[bi + 1] if bi + 1 < len(starts) else ncols
            for ri in range(header_ri + 1, min(stop, grid.nrows)):
                if not grid.text[ri][name_ci]:
                    continue
                cellmap = {f: (ri, ci) for f, ci in colmap.items() if f != "號次·姓名"}
                if "號次·姓名" in colmap:
                    cellmap["姓名"] = (ri, colmap["號次·姓名"])
                out.append((cellmap, (ri, ri + 1, c0, c1)))
    return out


# --------------------------------------------------------------- 版式 I

def _cards_style_i(grid: _Grid, anchors: list[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """每個「號次」錨點展開成一張卡片 (r0, r1, c0, c1),邊界由相鄰錨點決定。"""
    anchor_rows = sorted({r for r, _ in anchors})
    cards = []
    for ri, ci in anchors:
        same_row = sorted(c for r, c in anchors if r == ri)
        nxt_c = next((c for c in same_row if c > ci), len(grid.text[ri]))
        nxt_r = next((r for r in anchor_rows if r > ri), grid.nrows)
        cards.append((ri, nxt_r, ci, nxt_c))
    return cards


# --------------------------------------------------------------- 版式 V

def _label_below(text: str) -> str | None:
    """版式 V 的欄名格:整格是欄名,或前一欄的內容溢出後接著欄名。"""
    if text == _BASIC_LABEL:
        return _BASIC_LABEL
    if _COMBINED.match(text):        # 號次·姓名 由錨點自己處理
        return None
    for name, forms in _LABEL_FORMS.items():
        for form in forms:
            if text.endswith(form):
                return name
    return None


def _records_style_v(grid: _Grid) -> list[_Record]:
    """版式 V:一張表格就是一位候選人,欄名在上、值在正下方(臺北市)。"""
    anchor = next(((ri, ci) for ri in range(grid.nrows)
                   for ci, t in enumerate(grid.text[ri]) if _COMBINED.match(t)), None)
    if anchor is None:
        return []
    ri, ci = anchor
    if ri + 1 >= grid.nrows or not _TICKET_NAME.match(grid.text[ri + 1][ci]):
        return []
    cellmap: dict[str, tuple[int, int]] = {"號次·姓名": (ri + 1, ci)}
    for rr in range(grid.nrows - 1):
        for cc in range(len(grid.text[rr])):
            name = _label_below(grid.text[rr][cc])
            if name and name not in cellmap and grid.text[rr + 1][cc]:
                cellmap[name] = (rr + 1, cc)
    return [(cellmap, (0, grid.nrows, 0, len(grid.text[0])))]


def _records_style_i(grid: _Grid) -> list[_Record]:
    out: list[_Record] = []
    for card in _cards_style_i(grid, _anchor_rows(grid)):
        cellmap = _read_card(grid, card)
        if "姓名" in cellmap:
            out.append((cellmap, card))
    return out


def _read_card(grid: _Grid, card: tuple[int, int, int, int]) -> dict[str, tuple[int, int]]:
    """卡片內每個欄名對應的值格位置。號次的值在下方,其餘在右方。"""
    r0, r1, c0, c1 = card
    found: dict[str, tuple[int, int]] = {}
    for ri in range(r0, r1):
        for ci in range(c0, c1):
            name = _pure_label(grid.text[ri][ci])
            if name is None or name in found:
                continue
            if name == "號次":
                if ri + 1 < grid.nrows:
                    found[name] = (ri + 1, ci)
            elif ci + 1 < c1:
                found[name] = (ri, ci + 1)
    return found


# --------------------------------------------------------------- 組裝

def _mk_person(grid: _Grid, role: str, cellmap: dict[str, tuple[int, int]],
               row_bbox) -> geo.Person:
    person = geo.Person(role=role, page=grid.page)
    person.row_bbox = row_bbox
    for field, (ri, ci) in cellmap.items():
        if field in ("號次", "相片"):
            continue
        cell = geo.Cell(text=grid.value(ri, ci), bbox=grid.bbox[ri][ci])
        if field == _BASIC_LABEL:
            person.basic_cell = cell
        elif field == "號次·姓名":
            m = _TICKET_NAME.match(grid.text[ri][ci])
            person.cells["姓名"] = geo.Cell(text=m.group(2) if m else cell.text,
                                           bbox=cell.bbox)
        else:
            person.cells[field] = cell
    return person


def _ticket(grid: _Grid, cellmap: dict[str, tuple[int, int]], fallback: int) -> int:
    pos = cellmap.get("號次") or cellmap.get("號次·姓名")
    if pos is not None:
        m = re.search(r"\d+", grid.text[pos[0]][pos[1]])
        if m:
            return int(m.group())
    return fallback


def _region_bbox(grid: _Grid, r0: int, r1: int, c0: int, c1: int):
    boxes = [grid.bbox[r][c] for r in range(r0, min(r1, grid.nrows))
             for c in range(c0, min(c1, len(grid.bbox[r]))) if grid.bbox[r][c]]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _assign_photo(person: geo.Person, images: list[dict], region) -> None:
    """相片欄沒有內嵌文字可比對,以「圖心落在候選人區塊內、面積最大」認定。"""
    if region is None:
        return
    x0, top, x1, bottom = region
    inside = [im for im in images
              if x0 <= (im["x0"] + im["x1"]) / 2 <= x1
              and top <= (im["top"] + im["bottom"]) / 2 <= bottom]
    if not inside:
        return
    im = max(inside, key=lambda i: (i["x1"] - i["x0"]) * (i["bottom"] - i["top"]))
    person.photo_bbox = (im["x0"], im["top"], im["x1"], im["bottom"])


def parse(pdf_path: str | Path, *, role: str) -> list[geo.Group]:
    """回傳每位候選人各自成一組(單人)的 Group 清單。"""
    groups: list[geo.Group] = []
    seen: set[tuple[int, str]] = set()
    with pdfplumber.open(str(pdf_path)) as pdf:
        found = [[(t, _to_grid(page, t, pi)) for t in page.find_tables()]
                 for pi, page in enumerate(pdf.pages)]
        markers = _markers(pdf, [[g for _, g in pg] for pg in found])
        for page_idx, page in enumerate(pdf.pages):
            for _table, grid in found[page_idx]:
                records = (_records_style_v(grid) or _records_style_h(grid)
                           or _records_style_i(grid))

                for cellmap, span in records:
                    r0, r1, c0, c1 = span
                    if not _in_section(markers, page_idx, grid.row_top[r0]):
                        continue
                    ticket = _ticket(grid, cellmap, len(groups) + 1)
                    region = _region_bbox(grid, r0, r1, c0, c1)
                    person = _mk_person(grid, role, cellmap, region)
                    name = _norm(person.cells["姓名"].text) if "姓名" in person.cells else ""
                    if not name or (ticket, name) in seen:
                        continue
                    seen.add((ticket, name))
                    _assign_photo(person, page.images, region)
                    group = geo.Group(ticket=ticket, page=page_idx)
                    group.members.append(person)
                    party = person.cells.pop("政黨", None)
                    if party is not None:
                        group.party_cell = party
                    groups.append(group)
    groups.sort(key=lambda g: (g.ticket or 0))
    return groups
