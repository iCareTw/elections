"""公報解析主流程：幾何切分(A) + 盲讀裁判(B) + 信心分級 → YAML + 相片。

總統(正副成組)與縣市長(單人一號)走同一條流程,差別只在「一組有哪些角色」與
「用哪個切分器」,都由 `election_meta` 依 PDF 放的位置判定。

用法:
    uv run python -m src.voter_guide.pipeline <pdf> [<pdf> ...] [--no-vision]
    uv run python -m src.voter_guide.pipeline <pdf> --out-dir out/ --tag 109
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from . import apple_ocr
from . import election_meta
from . import geometry as geo
from . import party_list_parse
from .strategies import _for_this_election, parse_best
from . import scan_parse
from . import scan_table
from . import table_parse
from . import verify
from .vision import VisionCache, crop_cell, transcribe

PERSON_FIELDS = ["姓名", "出生年月日", "性別", "學歷", "經歷"]
BASIC_SUBFIELDS = {"出生年月日", "性別"}

SOURCE_TEXT = "PDF 文字"
SOURCE_OCR = "圖像辨識"
SOURCE_SCAN = "掃描圖重建"

_BASIC_PATTERNS = {
    "出生年月日": r"出生年月日[:：]\s*(.+?)(?=性別[:：]|出生地[:：]|$)",
    "性別": r"性別[:：]\s*(.+?)(?=出生年月日[:：]|出生地[:：]|$)",
    "出生地": r"出生地[:：]\s*(.+?)(?=出生年月日[:：]|性別[:：]|$)",
}


def crop_filename(*, slug: str, ticket: int, name: str, field: str) -> str:
    """切圖檔名。slug 由 election_meta 給(如 president/16th_2024、mayor/2022_臺北市)。"""
    if field == "政見":  # 政見為組層級,檔名不綁人名
        return f"{slug}_ticket_{ticket}_政見.png"
    return f"{slug}_ticket_{ticket}_{name}_{field}.png"


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
                    slug: str, ticket: int, name: str, out_dir: Path,
                    source: str = SOURCE_TEXT):
    values: dict[str, str | None] = {}
    report: dict[str, dict] = {}

    # 113：出生年月日/性別/出生地 疊在「基本資料」合併格 → 只呼叫一次看圖、再切子欄
    basic_block = None
    if person.basic_cell:
        basic_crop = out_dir / crop_filename(slug=slug, ticket=ticket,
                                             name=name, field="基本資料")
        basic_key = f"{slug}|{ticket}|{person.role}|基本資料"
        basic_block = _vision_for(pdf_path, person, "基本資料(出生年月日、性別、出生地)",
                                   person.basic_cell.bbox,
                                   key=basic_key, cache=cache,
                                   crop_save=basic_crop, use_vision=use_vision)

    for field in PERSON_FIELDS:
        if field in person.cells:                      # 獨立欄(109 各欄、姓名/住址/學歷/經歷)
            cell = person.cells[field]
            geo_text = cell.text
            crop_path = out_dir / crop_filename(slug=slug, ticket=ticket,
                                                name=name, field=field)
            key = f"{slug}|{ticket}|{person.role}|{field}"
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
        if field in verify.BULLET_FIELDS and source == SOURCE_OCR:
            # OCR 有可靠的視覺行結構 → 用它切條目,看圖那路只做交叉驗證。
            # (模型會改壞字:倫敦→備敬、成淵→成潮,而 OCR 逐字正確)
            values[field] = verify.to_bullets(geo_text) or res["value"]
        elif field in verify.BULLET_FIELDS and vis_text:
            # PDF 內嵌文字的行序不保證(113 直排數字會落到別行) → 仍用 model 排版
            values[field] = vis_text
        else:
            values[field] = res["value"]
        report[field] = {k: v for k, v in res.items() if k != "value"}
    return values, report


def _party_cell(group) -> tuple[geo.Person | None, geo.Cell | None, str]:
    """政黨欄的位置。總統公報叫「登記方式」(合併跨正副兩列),縣市長叫「推薦之政黨」。"""
    for person in group.members:
        if "登記方式" in person.cells:
            return person, person.cells["登記方式"], "登記方式"
    if group.party_cell is not None:
        return (group.members[0] if group.members else None), group.party_cell, "推薦之政黨"
    return None, None, "登記方式"


def _verify_party(pdf_path, group, *, cache, use_vision, slug: str, out_dir: Path):
    """政黨掛在組別層級,只驗一次。"""
    person, cell, field = _party_cell(group)
    if person is None or cell is None:
        return "無黨籍", {"grade": "不適用"}
    pname = "".join(person.cells["姓名"].text.split()) if "姓名" in person.cells else ""
    crop_path = out_dir / crop_filename(slug=slug, ticket=group.ticket,
                                        name=pname, field=field)
    key = f"{slug}|{group.ticket}|{person.role}|{field}"
    vis = _vision_for(pdf_path, person, field, cell.bbox,
                      key=key, cache=cache,
                      crop_save=crop_path, use_vision=use_vision)
    res = verify.verify_field(field, cell.text, vis)
    party = (res["value"] or "").replace("推薦", "").strip() or "無黨籍"
    rep = {k: v for k, v in res.items() if k != "value"}
    return party, rep


def _extract_platform(pdf_path, group, *, cache, use_vision, slug: str, out_dir: Path):
    """政見掛在組別層級(總統公報是跨正副兩列的合併格)。表格文字常為空,
    以切圖 + 看圖讀出。回傳 (value, report)。"""
    for person in group.members:
        if "政見" in person.cells:
            cell = person.cells["政見"]
            crop_path = out_dir / crop_filename(slug=slug, ticket=group.ticket,
                                                name="", field="政見")
            key = f"{slug}|{group.ticket}|政見"
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
    if getattr(person, "photo_image", None) is not None:
        person.photo_image.save(dest_mk(dest))   # 掃描圖:已裁好的圖
        return dest
    if not person.photo_bbox:
        return None
    crop_cell(pdf_path, person.page, person.photo_bbox, scale=scale).save(dest_mk(dest))
    return dest


def dest_mk(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def _parse_structure(pdf_path: str, meta=None) -> tuple[list[geo.Group], str]:
    """A 路來源，依 PDF 裡實際有什麼逐級退讓。純程式判斷，不打模型：

    1. 有內嵌文字 → 直接讀(101/109/113、多數縣市長公報)
    2. 只有向量格線 → 逐格看圖(105:文字被轉成曲線)
    3. 什麼都沒有,只有掃描照片 → 自己找格線重建(085/089/093/097)
    """
    if meta is None:
        meta = election_meta.from_pdf_path(pdf_path)
    if meta.layout == election_meta.PARTY_LIST:
        # 不分區:一個政黨一組,成員人數不固定,沒有掃描圖那條退路
        return list(party_list_parse.parse(pdf_path)), SOURCE_TEXT
    if meta.paired:
        groups = list(geo.parse(pdf_path))
    else:
        groups = list(table_parse.parse(pdf_path, role=meta.roles[0]))
    if groups:
        return groups, SOURCE_TEXT
    if not apple_ocr.available():
        return [], SOURCE_TEXT
    if not meta.paired:
        # 匡線切得出格子、只有文字層壞掉(字型無對照表、欄名畫成圖)→ 沿用格子逐格 OCR
        groups = list(table_parse.parse(pdf_path, role=meta.roles[0], ocr=True))
        if groups:
            return groups, SOURCE_OCR
        # 連格子都沒有(整頁被畫成向量曲線)→ 畫出來自己找格線
        return list(scan_table.parse(pdf_path, role=meta.roles[0])), SOURCE_SCAN
    groups = list(apple_ocr.parse(pdf_path))
    if groups:
        return groups, SOURCE_OCR
    return list(scan_parse.parse(pdf_path)), SOURCE_SCAN


def _district_meta(meta, group: geo.Group):
    """合刊公報裡,這一組屬於哪一場。

    區域/補選以選舉區號分,原住民以平地/山地分(101 把兩者刊在同一份,
    號次也各自從 1 編起)。
    """
    scope = group.members[0].district if group.members else None
    if not (meta.splits_by_scope and scope is not None):
        return meta, None
    if meta.by_district:
        # 只有寫號碼的才需要拆;單一席次的縣市寫「基隆市選舉區」,本來就只有一場
        return (meta.for_scope(scope), scope) if isinstance(scope, int) else (meta, None)
    kind = election_meta.native_kind(scope)
    return meta.for_scope(kind), kind


def parse_pdf(pdf_path: str, tag: str, out_dir: Path, use_vision: bool, progress=None):
    meta = election_meta.from_pdf_path(pdf_path)

    cache = VisionCache(out_dir / "vision_cache" / f"{tag}.json")

    # 依序試各種讀法,以中選會名冊驗收;過程寫進 report 供匯入時落檔
    groups, source, parse_report = parse_best(pdf_path, meta, progress=progress)
    total = len(groups)
    if progress and total:
        progress(0, total, f"以{source}讀出 {total} 位候選人")
    result = []
    for gi, g in enumerate(groups):
        if progress:
            progress(gi, total, f"解析第{g.ticket}{meta.ticket_label}")
        # 合刊公報要拆場:切圖檔名跟著各選舉區走,否則不同區的第1號會互相覆蓋
        gmeta, district = _district_meta(meta, g)
        slug = gmeta.crop_slug
        entry: dict = {"號次": g.ticket}
        if district is not None:
            entry["選舉區"] = district
        verify_block: dict = {}
        party, party_rep = _verify_party(pdf_path, g, cache=cache,
                                         use_vision=use_vision,
                                         slug=slug, out_dir=out_dir)
        for person in g.members:
            # 先讀姓名(幾何)，避免切圖命名的雞生蛋問題
            name = "".join(person.cells["姓名"].text.split()) if "姓名" in person.cells else ""

            values, report = _process_person(
                pdf_path, person, cache=cache, use_vision=use_vision,
                slug=slug, ticket=g.ticket, name=name, out_dir=out_dir, source=source)
            rec = {f: values.get(f) for f in PERSON_FIELDS}
            rec["頁碼"] = person.page  # 0-based PDF 頁索引,供 load 填 source_page

            photo_path = out_dir / crop_filename(slug=slug, ticket=g.ticket,
                                                 name=name, field="相片")
            photo = _save_photo(pdf_path, person, photo_path)
            if photo:
                rec["相片"] = str(photo)
            entry[person.role] = rec
            verify_block[person.role] = report
        entry["政黨"] = party
        verify_block["政黨"] = party_rep
        platform, platform_rep = _extract_platform(
            pdf_path, g, cache=cache, use_vision=use_vision,
            slug=slug, out_dir=out_dir)
        entry["政見"] = platform
        verify_block["政見"] = platform_rep
        entry["_verify"] = verify_block
        result.append(entry)

    out_file = out_dir / f"{tag}.yaml"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    return result, out_file, parse_report


def _default_tag(pdf_path: str) -> str:
    """輸出檔名標籤:用選舉身分,同年不同縣市不會互相覆蓋。"""
    try:
        return election_meta.from_pdf_path(pdf_path).election_id
    except election_meta.UnknownGazette:
        return Path(pdf_path).stem


_OK_GRADES = (verify.EXACT, verify.SOFT, verify.NEAR, "不適用")


def _count_flagged(result) -> int:
    """需注意 = 大部分一致 / 資料不可靠 / 無法解析(SOFT、完全一致、幾乎一致不計)。"""
    n = 0
    for entry in result:
        for scope, report in entry.get("_verify", {}).items():
            if not isinstance(report, dict) or scope == "政黨":
                continue
            for r in report.values():
                if isinstance(r, dict) and r.get("grade") not in _OK_GRADES:
                    n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description="公報解析(幾何+盲讀裁判+信心分級)")
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--out-dir", default="_out/parsed")
    ap.add_argument("--tag", default=None, help="輸出檔名標籤(預設用民國年)")
    ap.add_argument("--no-vision", action="store_true", help="只跑幾何(快、不打模型)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    for pdf in args.pdfs:
        tag = args.tag or _default_tag(pdf)
        print(f"\n=== {pdf} (tag={tag}, vision={not args.no_vision}) ===")
        result, out_file, parse_report = parse_pdf(
            pdf, tag, out_dir, use_vision=not args.no_vision)
        print(parse_report.as_text())
        if not result:
            print("  0 組 → PDF 文字與圖像辨識都讀不到表格（掃描圖或未支援的版面）")
        else:
            print(f"  {len(result)} 組 → {out_file}；需注意欄位 {_count_flagged(result)} 個")


if __name__ == "__main__":
    main()
