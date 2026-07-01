"""總統公報解析主流程：幾何切分(A) + 盲讀裁判(B) + 信心分級 → YAML + 相片。

用法:
    uv run python -m src.voter_guide.pipeline <pdf> [<pdf> ...] [--no-vision]
    uv run python -m src.voter_guide.pipeline <pdf> --out-dir out/ --tag 109
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from . import geometry as geo
from . import verify
from .vision import VisionCache, crop_cell, transcribe

PERSON_FIELDS = ["姓名", "出生年月日", "性別", "學歷", "經歷"]
BASIC_SUBFIELDS = {"出生年月日", "性別"}

_BASIC_PATTERNS = {
    "出生年月日": r"出生年月日[:：]\s*(.+?)(?=性別[:：]|出生地[:：]|$)",
    "性別": r"性別[:：]\s*(.+?)(?=出生年月日[:：]|出生地[:：]|$)",
    "出生地": r"出生地[:：]\s*(.+?)(?=出生年月日[:：]|性別[:：]|$)",
}


def _split_basic(text: str | None, field: str) -> str | None:
    if not text:
        return None
    dec = geo.decode(text)
    m = re.search(_BASIC_PATTERNS[field], dec, re.S)
    if m:
        return m.group(1)
    # 日期容錯：看圖有時誤寫標籤(出生→出年)，直接用日期樣式抓
    if field == "出生年月日":
        m2 = re.search(r"\d+\s*年\s*\d+\s*月\s*\d+\s*日", verify.cn_to_arabic(dec))
        if m2:
            return m2.group(0)
    return None


def _vision_for(pdf_path, person, field, bbox, *, tag, ticket, cache, crops_dir, use_vision):
    if not use_vision or bbox is None:
        return None
    key = f"{tag}|{ticket}|{person.role}|{field}"
    crop = crops_dir / f"{tag}_{ticket}_{person.role}_{field}.png"
    return transcribe(pdf_path, person.page, bbox, field,
                      key=key, cache=cache, crop_save=crop)


def _process_person(pdf_path, person: geo.Person, *, tag, ticket, cache,
                    crops_dir, use_vision):
    values: dict[str, str | None] = {}
    report: dict[str, dict] = {}

    # 113：出生年月日/性別/出生地 疊在「基本資料」合併格 → 只呼叫一次看圖、再切子欄
    basic_block = None
    if person.basic_cell:
        basic_block = _vision_for(pdf_path, person, "基本資料(出生年月日、性別、出生地)",
                                  person.basic_cell.bbox, tag=tag, ticket=ticket,
                                  cache=cache, crops_dir=crops_dir, use_vision=use_vision)

    for field in PERSON_FIELDS:
        if field in person.cells:                      # 獨立欄(109 各欄、姓名/住址/學歷/經歷)
            cell = person.cells[field]
            geo_text = cell.text
            vis_text = _vision_for(pdf_path, person, field, cell.bbox, tag=tag,
                                   ticket=ticket, cache=cache, crops_dir=crops_dir,
                                   use_vision=use_vision)
        elif field in BASIC_SUBFIELDS and person.basic_cell:   # 113 合併格子欄
            geo_text = _split_basic(person.basic_cell.text, field)
            vis_text = _split_basic(basic_block, field)
        else:                                          # 該欄不存在(如 113 無住址)
            values[field] = None
            report[field] = {"grade": "不適用"}
            continue

        res = verify.verify_field(field, geo_text, vis_text)
        values[field] = res["value"]
        report[field] = {k: v for k, v in res.items() if k != "value"}
    return values, report


def _verify_party(pdf_path, group, *, tag, cache, crops_dir, use_vision):
    """政黨為組別層級(登記方式欄常合併跨兩列)，只在有格的那列驗一次。"""
    for person in (group.president, group.vice):
        if person and "登記方式" in person.cells:
            cell = person.cells["登記方式"]
            vis = _vision_for(pdf_path, person, "登記方式", cell.bbox, tag=tag,
                              ticket=group.ticket, cache=cache, crops_dir=crops_dir,
                              use_vision=use_vision)
            res = verify.verify_field("登記方式", cell.text, vis)
            party = (res["value"] or "").replace("推薦", "").strip() or "無黨籍"
            rep = {k: v for k, v in res.items() if k != "value"}
            return party, rep
    return "無黨籍", {"grade": "不適用"}


def _save_photo(pdf_path, person, dest: Path, scale=3.0):
    if not person.photo_bbox:
        return None
    crop_cell(pdf_path, person.page, person.photo_bbox, scale=scale).save(dest_mk(dest))
    return dest


def dest_mk(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def parse_pdf(pdf_path: str, tag: str, out_dir: Path, use_vision: bool):
    cache = VisionCache(out_dir / "vision_cache" / f"{tag}.json")
    crops_dir = out_dir / "cells" / tag
    photos_dir = out_dir / "photos"

    result = []
    for g in geo.parse(pdf_path):
        entry: dict = {"號次": g.ticket}
        verify_block: dict = {}
        party, party_rep = _verify_party(pdf_path, g, tag=tag, cache=cache,
                                         crops_dir=crops_dir, use_vision=use_vision)
        for role, person in (("總統", g.president), ("副總統", g.vice)):
            if person is None:
                continue
            values, report = _process_person(
                pdf_path, person, tag=tag, ticket=g.ticket, cache=cache,
                crops_dir=crops_dir, use_vision=use_vision)
            rec = {f: values.get(f) for f in PERSON_FIELDS}
            photo = _save_photo(pdf_path, person,
                                photos_dir / f"{tag}_{g.ticket}_{role}.png")
            if photo:
                rec["相片"] = str(photo)
            entry[role] = rec
            verify_block[role] = report
        entry["政黨"] = party
        verify_block["政黨"] = party_rep
        entry["_verify"] = verify_block
        result.append(entry)

    out_file = out_dir / f"{tag}.yaml"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    return result, out_file


def _default_tag(pdf_path: str) -> str:
    m = re.search(r"(\d+)年第(\d+)任", Path(pdf_path).stem)
    return m.group(1) if m else Path(pdf_path).stem


_OK_GRADES = (verify.EXACT, verify.SOFT, verify.NEAR, "不適用")


def _count_flagged(result) -> int:
    """需注意 = 大部分一致 / 資料不可靠 / 無法解析(SOFT、完全一致、幾乎一致不計)。"""
    n = 0
    for entry in result:
        for role in ("總統", "副總統"):
            for r in entry.get("_verify", {}).get(role, {}).values():
                if r.get("grade") not in _OK_GRADES:
                    n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description="總統公報解析(幾何+盲讀裁判+信心分級)")
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--out-dir", default="_out/voter_guide/president")
    ap.add_argument("--tag", default=None, help="輸出檔名標籤(預設用民國年)")
    ap.add_argument("--no-vision", action="store_true", help="只跑幾何(快、不打模型)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    for pdf in args.pdfs:
        tag = args.tag or _default_tag(pdf)
        print(f"\n=== {pdf} (tag={tag}, vision={not args.no_vision}) ===")
        result, out_file = parse_pdf(pdf, tag, out_dir, use_vision=not args.no_vision)
        if not result:
            print(f"  0 組 → 需 OCR 來源（掃描圖、無可解析文字/格線），現有幾何無法處理")
        else:
            print(f"  {len(result)} 組 → {out_file}；需注意欄位 {_count_flagged(result)} 個")


if __name__ == "__main__":
    main()
