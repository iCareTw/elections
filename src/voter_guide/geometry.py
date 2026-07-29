"""A 路：用表格框線(幾何)把總統公報切到單格，取出各參選人各欄位文字與座標。

設計重點：欄位以「表頭文字」定位(讀到『出生地』就抓那一欄)，不寫死欄位序號，
因此各年份欄位順序/有無不同也不會錯。每格同時回傳 bbox 供 B 路(看圖)裁切。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import pdfplumber

CID = re.compile(r"\(cid:(\d+)\)")

# 想抓的欄位 → 可能的表頭關鍵字(由前到後優先)
FIELD_HEADERS = {
    "姓名": ["姓名"],
    "出生年月日": ["出生年月日"],
    "性別": ["性別"],
    "出生地": ["出生地"],
    "登記方式": ["登記方式", "登記"],
    "住址": ["住址"],
    "學歷": ["學歷"],
    "經歷": ["經歷"],
    "政見": ["政見"],
}
ROLES = ("總統候選人", "副總統候選人")


@dataclass
class Cell:
    text: str                       # 已 cid 解碼、未去空白的原始格內文字
    bbox: tuple[float, float, float, float] | None  # (x0, top, x1, bottom) PDF pt


@dataclass
class Person:
    role: str                       # 總統 / 副總統
    page: int
    cells: dict[str, Cell] = dc_field(default_factory=dict)   # 欄位 -> Cell
    basic_cell: Cell | None = None  # 113 把出生年月日/性別/出生地 疊在「基本資料」合併格
    photo_bbox: tuple[float, float, float, float] | None = None
    row_bbox: tuple[float, float, float, float] | None = None
    photo_image: object | None = None  # 掃描圖來源:無 bbox 可裁,直接帶 PIL 圖


@dataclass
class Group:
    ticket: int | None
    page: int
    president: Person | None = None
    vice: Person | None = None


def decode(s: str | None) -> str:
    return CID.sub(lambda m: chr(int(m.group(1))), s or "")


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", "", decode(s)).replace("　", "")


def _find_header_row(grid) -> tuple[int | None, list[str]]:
    for ri, row in enumerate(grid):
        cells = [_norm(c) for c in row]
        if "姓名" in cells and any("學歷" in c for c in cells):
            return ri, cells
    return None, []


def _build_colmap(header_cells: list[str]) -> dict[str, int]:
    colmap: dict[str, int] = {}
    for fname, kws in FIELD_HEADERS.items():
        for ci, h in enumerate(header_cells):
            if any(kw in h for kw in kws):
                colmap.setdefault(fname, ci)
                break
    return colmap


def _assign_photos(persons: list[Person], images: list[dict], photo_x: tuple[float, float]):
    """相片欄內的內嵌圖，依 y 由上而下與 persons 一對一配對(修正撞號)。"""
    cands = [im for im in images
             if photo_x[0] - 6 <= (im["x0"] + im["x1"]) / 2 <= photo_x[1] + 6]
    cands.sort(key=lambda im: im["top"])
    persons_sorted = sorted([p for p in persons if p.row_bbox],
                            key=lambda p: p.row_bbox[1])
    for person, im in zip(persons_sorted, cands):
        person.photo_bbox = (im["x0"], im["top"], im["x1"], im["bottom"])


def parse(pdf_path: str | Path) -> list[Group]:
    groups: list[Group] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            for table in page.find_tables():
                grid = table.extract()
                hr, header = _find_header_row(grid)
                if hr is None:
                    continue
                colmap = _build_colmap(header)
                combined_ci = next((ci for ci, h in enumerate(header)
                                    if "基本資料" in h), None)
                photo_ci = next((ci for ci, h in enumerate(header)
                                 if "相片" in h), None)
                photo_x = None
                if photo_ci is not None:
                    pc = table.rows[hr].cells[photo_ci]
                    if pc:
                        photo_x = (pc[0], pc[2])

                cur: Group | None = None
                page_persons: list[Person] = []
                for ri in range(hr + 1, len(grid)):
                    row = grid[ri]
                    rowtext = [_norm(c) for c in row]
                    role = next((c for c in rowtext if c in ROLES), None)
                    if role is None:
                        continue
                    num = next((c for c in rowtext if re.fullmatch(r"\d+", c)), None)
                    if role == "總統候選人":
                        cur = Group(ticket=int(num) if num else None, page=page_idx)
                        groups.append(cur)
                    if cur is None:
                        continue

                    person = Person(role="總統" if role == "總統候選人" else "副總統",
                                    page=page_idx)
                    person.row_bbox = table.rows[ri].bbox

                    def mkcell(ci: int | None) -> Cell | None:
                        if ci is None or ci >= len(row):
                            return None
                        c = table.rows[ri].cells[ci]
                        return Cell(text=decode(row[ci]), bbox=tuple(c) if c else None)

                    for fname, ci in colmap.items():
                        cell = mkcell(ci)
                        if cell:
                            person.cells[fname] = cell
                    if combined_ci is not None:
                        person.basic_cell = mkcell(combined_ci)

                    if person.role == "總統":
                        cur.president = person
                    else:
                        cur.vice = person
                    page_persons.append(person)

                if photo_x:
                    _assign_photos(page_persons, page.images, photo_x)

    return groups
