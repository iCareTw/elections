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


def crop_filename(*, type: str, session: int, minguo_year: int,
                  ticket: int, name: str, field: str) -> str:
    year_ad = minguo_year + 1911
    if field == "政見":  # 政見為組層級,檔名不綁人名
        return f"{type}/{session}th_{year_ad}_ticket_{ticket}_政見.png"
    return f"{type}/{session}th_{year_ad}_ticket_{ticket}_{name}_{field}.png"


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


def _vision_for(pdf_path, person, field, bbox, *, key, cache, crop_save, use_vision):
    if not use_vision or bbox is None:
        return None
    return transcribe(pdf_path, person.page, bbox, field,
                      key=key, cache=cache, crop_save=crop_save)


def _process_person(pdf_path, person: geo.Person, *, cache, use_vision,
                    crop_type: str, session: int, minguo_year: int,
                    ticket: int, name: str, out_dir: Path):
    values: dict[str, str | None] = {}
    report: dict[str, dict] = {}

    # 113：出生年月日/性別/出生地 疊在「基本資料」合併格 → 只呼叫一次看圖、再切子欄
    basic_block = None
    if person.basic_cell:
        basic_crop = out_dir / crop_filename(type=crop_type, session=session,
                                              minguo_year=minguo_year, ticket=ticket,
                                              name=name, field="基本資料")
        basic_key = f"{session}|{ticket}|{person.role}|基本資料"
        basic_block = _vision_for(pdf_path, person, "基本資料(出生年月日、性別、出生地)",
                                   person.basic_cell.bbox,
                                   key=basic_key, cache=cache,
                                   crop_save=basic_crop, use_vision=use_vision)

    for field in PERSON_FIELDS:
        if field in person.cells:                      # 獨立欄(109 各欄、姓名/住址/學歷/經歷)
            cell = person.cells[field]
            geo_text = cell.text
            crop_path = out_dir / crop_filename(type=crop_type, session=session,
                                                 minguo_year=minguo_year, ticket=ticket,
                                                 name=name, field=field)
            key = f"{session}|{ticket}|{person.role}|{field}"
            vis_text = _vision_for(pdf_path, person, field, cell.bbox,
                                    key=key, cache=cache,
                                    crop_save=crop_path, use_vision=use_vision)
        elif field in BASIC_SUBFIELDS and person.basic_cell:   # 113 合併格子欄
            geo_text = _split_basic(person.basic_cell.text, field)
            vis_text = _split_basic(basic_block, field)
        else:                                          # 該欄不存在(如 113 無住址)
            values[field] = None
            report[field] = {"grade": "不適用"}
            continue

        res = verify.verify_field(field, geo_text, vis_text)
        # 學歷/經歷 以 model 的 markdown 輸出為準(幾何無法保留條列格式)
        if field in ("學歷", "經歷") and vis_text:
            values[field] = vis_text
        else:
            values[field] = res["value"]
        report[field] = {k: v for k, v in res.items() if k != "value"}
    return values, report


def _verify_party(pdf_path, group, *, cache, use_vision,
                  crop_type: str, session: int, minguo_year: int, out_dir: Path):
    """政黨為組別層級(登記方式欄常合併跨兩列)，只在有格的那列驗一次。"""
    for person in (group.president, group.vice):
        if person and "登記方式" in person.cells:
            cell = person.cells["登記方式"]
            pname = "".join(person.cells["姓名"].text.split()) if "姓名" in person.cells else ""
            crop_path = out_dir / crop_filename(type=crop_type, session=session,
                                                 minguo_year=minguo_year, ticket=group.ticket,
                                                 name=pname, field="登記方式")
            key = f"{session}|{group.ticket}|{person.role}|登記方式"
            vis = _vision_for(pdf_path, person, "登記方式", cell.bbox,
                              key=key, cache=cache,
                              crop_save=crop_path, use_vision=use_vision)
            res = verify.verify_field("登記方式", cell.text, vis)
            party = (res["value"] or "").replace("推薦", "").strip() or "無黨籍"
            rep = {k: v for k, v in res.items() if k != "value"}
            return party, rep
    return "無黨籍", {"grade": "不適用"}


def _extract_platform(pdf_path, group, *, cache, use_vision,
                      crop_type: str, session: int, minguo_year: int, out_dir: Path):
    """政見為組別層級(跨正副兩列的合併格,掛在有格的那列)。表格文字常為空,
    以切圖 + 看圖讀出。回傳 (value, report)。"""
    for person in (group.president, group.vice):
        if person and "政見" in person.cells:
            cell = person.cells["政見"]
            crop_path = out_dir / crop_filename(type=crop_type, session=session,
                                                 minguo_year=minguo_year, ticket=group.ticket,
                                                 name="", field="政見")
            key = f"{session}|{group.ticket}|政見"
            vis = _vision_for(pdf_path, person, "政見", cell.bbox,
                              key=key, cache=cache,
                              crop_save=crop_path, use_vision=use_vision)
            res = verify.verify_field("政見", cell.text, vis)
            rep = {k: v for k, v in res.items() if k != "value"}
            # 政見以 model 的 markdown 原文為準(verify 取值會清掉換行/空白 → 排版糊掉)
            value = vis if vis else res["value"]
            return value, rep
    return None, {"grade": "不適用"}


def _save_photo(pdf_path, person, dest: Path, scale=3.0):
    if not person.photo_bbox:
        return None
    crop_cell(pdf_path, person.page, person.photo_bbox, scale=scale).save(dest_mk(dest))
    return dest


def dest_mk(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def _pdf_session_year(pdf_path: str) -> tuple[int, int]:
    """PDF 檔名 → (session, minguo_year). 找不到時 return (0, 0)."""
    m = re.search(r"(\d+)年第(\d+)任", Path(pdf_path).stem)
    if m:
        return int(m.group(2)), int(m.group(1))
    return 0, 0


def parse_pdf(pdf_path: str, tag: str, out_dir: Path, use_vision: bool, progress=None):
    session, minguo_year = _pdf_session_year(pdf_path)
    crop_type = "president"

    cache = VisionCache(out_dir / "vision_cache" / f"{tag}.json")

    groups = list(geo.parse(pdf_path))
    total = len(groups)
    result = []
    for gi, g in enumerate(groups):
        if progress:
            progress(gi, total, f"解析第{g.ticket}組")
        entry: dict = {"號次": g.ticket}
        verify_block: dict = {}
        party, party_rep = _verify_party(pdf_path, g, cache=cache,
                                          use_vision=use_vision,
                                          crop_type=crop_type, session=session,
                                          minguo_year=minguo_year, out_dir=out_dir)
        for role, person in (("總統", g.president), ("副總統", g.vice)):
            if person is None:
                continue
            # 先讀姓名(幾何)，避免切圖命名的雞生蛋問題
            name = "".join(person.cells["姓名"].text.split()) if "姓名" in person.cells else ""

            values, report = _process_person(
                pdf_path, person, cache=cache, use_vision=use_vision,
                crop_type=crop_type, session=session, minguo_year=minguo_year,
                ticket=g.ticket, name=name, out_dir=out_dir)
            rec = {f: values.get(f) for f in PERSON_FIELDS}
            rec["頁碼"] = person.page  # 0-based PDF 頁索引,供 load 填 source_page

            photo_path = out_dir / crop_filename(type=crop_type, session=session,
                                                  minguo_year=minguo_year, ticket=g.ticket,
                                                  name=name, field="相片")
            photo = _save_photo(pdf_path, person, photo_path)
            if photo:
                rec["相片"] = str(photo)
            entry[role] = rec
            verify_block[role] = report
        entry["政黨"] = party
        verify_block["政黨"] = party_rep
        platform, platform_rep = _extract_platform(
            pdf_path, g, cache=cache, use_vision=use_vision,
            crop_type=crop_type, session=session, minguo_year=minguo_year, out_dir=out_dir)
        entry["政見"] = platform
        verify_block["政見"] = platform_rep
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
    ap.add_argument("--out-dir", default="_out/parsed")
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
