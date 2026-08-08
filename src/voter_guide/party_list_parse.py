"""不分區(政黨名單)公報解析:一個政黨一組,底下是照名單次序排的候選人。

跟區域公報最大的不同是「一組不只一個人,而且人數不固定」:號次屬於政黨,
政見也是政黨的,候選人只有名單次序、姓名與個人資料。

兩種版面,同一套讀法:

    101/105/109  一整頁是一張大表格,實際上是報紙式的 2~3 直欄。
                 每個直欄各有一組欄位(名單次序/姓名/出生年月日/性別/出生地/學歷/經歷),
                 一個政黨的名單常常左欄排不下就接到中欄、右欄、下一頁。
    113          一個政黨一張小表格,個人資料疊成「基本資料」合併格。

因此解析是一台跨頁的狀態機:把每一頁的直欄由左到右、由上到下攤成一條閱讀順序,
遇到「號次·名稱」就換一個政黨,遇到「名單次序」就換一組欄位對照,
其餘有名單次序的列都算在當下這個政黨名下。
"""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from . import geometry as geo
from .table_parse import _norm, _to_grid, _union

# 候選人那一列的欄位;「基本資料」是 113 把出生年月日/性別/出生地 疊在一起的合併格
SEQ = "名單次序"
_CANDIDATE_FIELDS = (SEQ, "姓名", "出生年月日", "性別", "出生地", "學歷", "經歷", "基本資料")

_PARTY_HEAD = re.compile(r"^.{0,20}?號次\W?名稱$")   # 113 把兩個欄名擠在同一格
_TICKET_PARTY = re.compile(r"^(\d{1,3})\s*(\S.*)$")  # 「1小民參政歐巴桑聯盟」
_PLATFORM = "政見"


class _Marker:
    """閱讀順序上的一個事件:換政黨 / 換欄位對照 / 政見。"""

    def __init__(self, kind: str, row: int, col: int, extra=None):
        self.kind, self.row, self.col, self.extra = kind, row, col, extra


def _party_head_at(grid, ri: int, ci: int) -> bool:
    """(ri, ci) 是不是「號次」欄名,右邊跟著「名稱」。"""
    if grid.text[ri][ci] != "號次":
        return False
    row = grid.text[ri]
    return any(row[cc] == "名稱" for cc in range(ci + 1, min(ci + 4, len(row))))


def _markers_of(grid) -> tuple[list[int], list[_Marker]]:
    """回傳 (直欄起點, 事件清單)。直欄起點只由欄名決定,政見再往左靠到所屬直欄。"""
    marks: list[_Marker] = []
    bases: set[int] = set()
    for ri in range(grid.nrows):
        for ci, text in enumerate(grid.text[ri]):
            if not text:
                continue
            if _party_head_at(grid, ri, ci) or _PARTY_HEAD.match(text):
                marks.append(_Marker("party", ri, ci))
                bases.add(ci)
            elif text == SEQ or (text and SEQ.startswith(text)
                                 and ci + 1 < len(grid.text[ri])
                                 and text + grid.text[ri][ci + 1] == SEQ):
                offsets = _field_offsets(grid, ri, ci)
                if offsets:
                    marks.append(_Marker("fields", ri, ci, offsets))
                    bases.add(ci)
            elif text.startswith(_PLATFORM):
                marks.append(_Marker("platform", ri, ci, len(text) > len(_PLATFORM)))
    if not bases:
        return [], []
    ordered = sorted(bases)
    for mark in marks:                      # 政見:靠到左邊最近的直欄
        mark.col = max(b for b in ordered if b <= mark.col) if mark.col >= ordered[0] \
            else ordered[0]
    return ordered, marks


def _field_offsets(grid, ri: int, ci: int) -> dict[str, tuple[int, int]]:
    """名單次序那一列的欄位對照,存「相對這個直欄起點的欄範圍」,換直欄時直接平移。

    欄名與值都可能被排版切成相鄰兩格(『名單次』+『序』、『史惟』+『筑』),
    所以記的是範圍而不是單一欄:一個欄位吃到下一個欄名為止。
    """
    row = grid.text[ri]
    hits: list[tuple[int, str]] = []
    cc = ci
    while cc < len(row):
        name = row[cc]
        if cc > ci and name in ("號次", "名稱"):     # 碰到下一個直欄的欄名就停
            break
        if name in _CANDIDATE_FIELDS:
            hits.append((cc, name))
        elif cc + 1 < len(row) and name + row[cc + 1] in _CANDIDATE_FIELDS:
            hits.append((cc, name + row[cc + 1]))
            cc += 1
        cc += 1
    out: dict[str, tuple[int, int]] = {}
    for idx, (start, name) in enumerate(hits):
        stop = hits[idx + 1][0] if idx + 1 < len(hits) else len(row)
        out.setdefault(name, (start - ci, stop - ci))
    return out if SEQ in out else {}


def _cell(grid, ri: int, ci: int) -> geo.Cell | None:
    return _span(grid, ri, ci, ci + 1)


def _span(grid, ri: int, c0: int, c1: int) -> geo.Cell | None:
    """把一個欄位範圍內的格子併成一格(文字相接、bbox 取聯集)。"""
    if ri >= grid.nrows:
        return None
    text, box = "", None
    for ci in range(max(c0, 0), min(c1, len(grid.text[ri]))):
        if grid.bbox[ri][ci] is None:
            continue
        text += grid.value(ri, ci)
        box = _union(box, grid.bbox[ri][ci])
    return geo.Cell(text=text, bbox=box) if box is not None else None


def _spanned(grid, ri: int, base: int, offsets: dict[str, tuple[int, int]],
             field: str) -> geo.Cell | None:
    span = offsets.get(field)
    if span is None:
        return None
    return _span(grid, ri, base + span[0], base + span[1])


def _reading_order(page) -> list:
    """把一頁的表格排成閱讀順序:先分直欄(以左緣分群),同一欄由上往下。

    113 一個政黨一張小表格,報紙式排成兩直欄;名單排不下時接到同一欄的下一張、
    再接到右欄。find_tables() 給的順序不是這個順序,不排會把接續的人算到別黨頭上。
    """
    tables = page.find_tables()
    if len(tables) < 2:
        return tables
    tolerance = page.width * 0.05
    lefts: list[float] = []
    for t in tables:
        if not any(abs(t.bbox[0] - x) <= tolerance for x in lefts):
            lefts.append(t.bbox[0])
    lefts.sort()

    def key(t):
        column = min(range(len(lefts)), key=lambda i: abs(lefts[i] - t.bbox[0]))
        return (column, t.bbox[1])
    return sorted(tables, key=key)


class _Reader:
    """跨頁的狀態機:目前在讀哪個政黨、用哪一組欄位對照。"""

    def __init__(self):
        self.groups: list[geo.Group] = []
        self.platform: dict[int, geo.Cell] = {}    # 政黨 → 政見格(最後掛到第一位候選人)
        self.offsets: dict[str, tuple[int, int]] | None = None
        self.current: geo.Group | None = None
        self.last_base = 0

    def read_grid(self, grid) -> None:
        bases, marks = _markers_of(grid)
        if not bases:
            # 整張表格沒有任何欄名 = 上一張表格的名單接下來(113 民進黨接到下一頁),
            # 沿用目前的政黨與欄位對照繼續讀。
            self._rows(grid, self.last_base, 0, grid.nrows)
            return
        self.last_base = bases[0]
        for base in bases:
            band = sorted((m for m in marks if m.col == base), key=lambda m: m.row)
            rows_done = 0
            for mark in band:
                self._rows(grid, base, rows_done, mark.row)
                rows_done = self._apply(grid, base, mark)
            self._rows(grid, base, rows_done, grid.nrows)

    def _apply(self, grid, base: int, mark: _Marker) -> int:
        if mark.kind == "fields":
            self.offsets = mark.extra
            return mark.row + 1
        if mark.kind == "party":
            return self._new_party(grid, base, mark.row)
        if mark.kind == "platform" and self.current is not None:
            # 「政見：…」自己就是內容;只寫「政見」兩個字的,內容在正下方那格
            cell = _cell(grid, mark.row, mark.col) if mark.extra \
                else _cell(grid, mark.row + 1, mark.col)
            if cell is not None:
                self.platform.setdefault(id(self.current), cell)
            return mark.row + (1 if mark.extra else 2)
        return mark.row + 1

    def _new_party(self, grid, base: int, ri: int) -> int:
        """號次與政黨名稱在欄名的下一列;113 兩者黏在同一格。

        排版有時會在欄名與內容之間夾一列空白(101 的親民黨),所以往下找幾列。
        """
        for rr in range(ri + 1, min(ri + 4, grid.nrows)):
            head = grid.text[rr][base]
            if not head:
                continue
            name_cell = _cell(grid, rr, base + 1)
            if re.fullmatch(r"\d{1,3}", head) and name_cell and _norm(name_cell.text):
                ticket, party = int(head), name_cell
            else:
                m = _TICKET_PARTY.match(head)
                if not m:
                    return rr
                ticket = int(m.group(1))
                party = geo.Cell(text=m.group(2), bbox=grid.bbox[rr][base])
            group = geo.Group(ticket=ticket, page=grid.page)
            group.party_cell = party
            self.current = group
            self.groups.append(group)
            return rr + 1
        return ri + 1

    def _rows(self, grid, base: int, start: int, stop: int) -> None:
        if self.offsets is None or self.current is None:
            return
        for ri in range(max(start, 0), min(stop, grid.nrows)):
            seq_cell = _spanned(grid, ri, base, self.offsets, SEQ)
            name_cell = _spanned(grid, ri, base, self.offsets, "姓名")
            if seq_cell is None or name_cell is None:
                continue
            seq = _norm(seq_cell.text)
            if not seq.isdigit():
                continue
            # 姓名格抽不到文字(排版把名字畫成圖)仍然收下,格子留給看圖那一路去讀
            person = geo.Person(role=f"第{int(seq)}名", page=grid.page)
            for field in self.offsets:
                if field == SEQ:
                    continue
                cell = _spanned(grid, ri, base, self.offsets, field)
                if cell is None:
                    continue
                if field == "基本資料":
                    person.basic_cell = cell
                else:
                    person.cells[field] = cell
            if "姓名" not in person.cells:
                continue
            self.current.members.append(person)


def parse(pdf_path: str | Path) -> list[geo.Group]:
    """回傳每個政黨一組、成員為名單上候選人的 Group 清單。"""
    reader = _Reader()
    with geo.open_pdf(pdf_path) as pdf:
        for pi, page in enumerate(pdf.pages):
            for table in _reading_order(page):
                reader.read_grid(_to_grid(page, table, pi))
    for group in reader.groups:
        cell = reader.platform.get(id(group))
        if cell is not None and group.members:
            group.members[0].cells[_PLATFORM] = cell
    return [g for g in reader.groups if g.members]
