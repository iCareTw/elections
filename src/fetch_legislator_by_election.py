import argparse
import asyncio
import re
from pathlib import Path

import httpx
import openpyxl

from src.cec_attachment import BASE_URL, fetch_attachment_records

DATA_ROOT = Path("_data/legislator/by-election-legislator")
# 中選會的補選得票數一覽表沒有出生年月日,只有選舉公報有,從已下載的公報補回來
GAZETTE_ROOT = Path("_data/voter_guide/legislator")

XLSX_COLUMNS = [
    ("投票日", "vote_date"),
    ("地區", "area_name"),
    ("號次", "cand_no"),
    ("姓名", "cand_name"),
    ("性別", "cand_sex"),
    ("出生年", "cand_birthyear"),
    ("政黨", "party_name"),
    ("得票數", "ticket_num"),
    ("得票率", "ticket_percent"),
    ("當選", "is_victor"),
]


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def output_path(session: int, theme_name: str) -> Path:
    return DATA_ROOT / f"{session}th" / f"{_safe_filename(theme_name)}.xlsx"


def ticket_loc(item: dict) -> str:
    data_level = item["data_level"]
    if data_level in {"N", "C"}:
        return "00_000_00_000_0000"
    if data_level in {"D", "L", "T"}:
        return f"{item['prv_code']}_{item['city_code']}_{item['area_code']}_000_0000"
    return (
        f"{item['prv_code']}_{item['city_code']}_{item['area_code']}_"
        f"{item['dept_code']}_{item['li_code']}"
    )


def tickets_url(item: dict) -> str:
    return (
        f"{BASE_URL}/static/elections/data/tickets/{item['type_id']}/{item['subject_id']}/"
        f"{item['legislator_type_id']}/{item['theme_id']}/{item['data_level']}/{ticket_loc(item)}.json"
    )


def _roc_birthyear(text: str) -> int | None:
    """取民國年轉西元。

    公報有兩種寫法:直排的『57\\n年\\n08\\n月\\n30\\n日』,以及把數字跟欄位標籤拆開的
    合併格『69 12 31\\n出生年月日: 年 月 日』。
    """
    raw = text or ""
    match = re.search(r"(\d{2,3})年", re.sub(r"\s+", "", raw))
    if match:
        roc = int(match.group(1))
    elif "出生年月日" in raw:
        numbers = re.findall(r"\d{1,3}", raw)
        roc = int(numbers[0]) if numbers else None
    else:
        roc = None
    return roc + 1911 if roc and 1 <= roc <= 130 else None


def _name_runs(words: list[dict], name: str) -> list[list[dict]]:
    """公報的姓名是一字一列直排,找出整個名字連成一直行的位置。"""
    runs = []
    for start in (w for w in words if w["text"] == name[0]):
        center = (start["x0"] + start["x1"]) / 2
        picked = [start]
        for char in name[1:]:
            below = [
                w for w in words
                if w["text"] == char
                and abs((w["x0"] + w["x1"]) / 2 - center) < 12
                and 0 < w["top"] - picked[-1]["top"] < 90
            ]
            if not below:
                break
            picked.append(min(below, key=lambda w: w["top"]))
        if len(picked) == len(name):
            runs.append(picked)
    return runs


def _birthyear_beside(words: list[dict], run: list[dict]) -> int | None:
    """姓名右邊那一直行數字就是出生年月日,取第一個(民國年)。"""
    center = (run[0]["x0"] + run[0]["x1"]) / 2
    numbers = sorted(
        (
            w for w in words
            if re.fullmatch(r"\d{1,3}", w["text"])
            and center < (w["x0"] + w["x1"]) / 2 < center + 220
            and run[0]["top"] - 60 <= w["top"] <= run[-1]["top"] + 90
        ),
        key=lambda w: w["top"],
    )
    if not numbers:
        return None
    roc = int(numbers[0]["text"])
    return roc + 1911 if 20 <= roc <= 110 else None


def _pdfplumber_words(pdf: Path) -> list[dict]:
    import pdfplumber

    with pdfplumber.open(pdf) as doc:
        return [w for page in doc.pages for w in page.extract_words()]


def _pypdf_words(pdf: Path) -> list[dict]:
    """有些公報的中文字型 pdfminer 解不開(讀成 (cid:1234)),改用 pypdf 拿字與座標。"""
    from pypdf import PdfReader

    words: list[dict] = []

    def visit(text, _cm, tm, _font_dict, font_size):
        stripped = (text or "").strip()
        if stripped:
            words.append({"text": stripped, "x0": tm[4], "x1": tm[4] + font_size, "top": -tm[5]})

    for page in PdfReader(str(pdf)).pages:
        page.extract_text(visitor_text=visit)
    return words


def _birthyears_by_coordinates(pdf: Path, names: set[str]) -> dict[str, int]:
    """解析器讀不動的公報:已經知道有誰,就直接用座標把名字旁邊的出生年撈出來。"""
    found: dict[str, int] = {}
    for reader in (_pdfplumber_words, _pypdf_words):
        remaining = names - found.keys()
        if not remaining:
            break
        try:
            words = reader(pdf)
        except Exception as exc:
            print(f"  WARNING {reader.__name__} 讀不到 {pdf.name}: {exc}")
            continue
        for name in remaining:
            years = {y for y in (_birthyear_beside(words, r) for r in _name_runs(words, name)) if y}
            if len(years) == 1:
                found[name] = years.pop()
    return found


def gazette_birthyears(session: int, names: set[str], root: Path = GAZETTE_ROOT) -> dict[str, int]:
    """讀該屆的補選選舉公報,回傳 {姓名: 西元出生年}。

    以姓名對應而非檔名,因為公報檔名的選舉區寫法(第1/第一/臺vs台)跟中選會場次名稱對不起來。
    同名但生年不同時視為無法判斷,不回傳。
    """
    from src.voter_guide import election_meta, strategies

    def _is_by_election(pdf: Path) -> bool:
        # 爬下來的公報有的放在「06補選」目錄,有的混在區域目錄裡只有檔名寫補選
        return any("補選" in part or "by-election" in part for part in (pdf.name, pdf.parent.name))

    session_dirs = sorted(root.glob(f"{session:02d}th_*")) if root.exists() else []
    pdfs = sorted(
        pdf
        for session_dir in session_dirs
        for pdf in session_dir.rglob("*.pdf")
        if _is_by_election(pdf)
    )

    found: dict[str, set[int]] = {}
    for pdf in pdfs:
        parsed: dict[str, int] = {}
        try:
            groups, _source, _report = strategies.parse_best(str(pdf), election_meta.from_pdf_path(str(pdf)))
            for group in groups:
                for member in group.members:
                    cells = member.cells
                    name = re.sub(r"\s+", "", cells["姓名"].text) if "姓名" in cells else ""
                    # 有些年份把出生年月日/性別/出生地疊在同一個「基本資料」合併格
                    birth_cell = cells.get("出生年月日") or member.basic_cell
                    birthyear = _roc_birthyear(birth_cell.text) if birth_cell else None
                    # 解析失敗時姓名常被截成一個字,只認名冊上真的有的人
                    if name in names and birthyear:
                        parsed[name] = birthyear
        except Exception as exc:  # 某一份公報讀不動不該讓整批中斷
            print(f"  WARNING 公報解析失敗 {pdf.name}: {exc}")

        missing = names - parsed.keys()
        if missing:
            try:
                parsed.update(_birthyears_by_coordinates(pdf, missing))
            except Exception as exc:
                print(f"  WARNING 公報座標比對失敗 {pdf.name}: {exc}")

        for name, birthyear in parsed.items():
            found.setdefault(name, set()).add(birthyear)

    return {name: years.pop() for name, years in found.items() if len(years) == 1}


def write_xlsx(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([col for col, _ in XLSX_COLUMNS])
    for r in records:
        ws.append([r.get(field) for _, field in XLSX_COLUMNS])
    wb.save(path)


def parse_by_election_items(data: list[dict], sessions: set[int]) -> list[dict]:
    items = []
    for entry in data:
        for time_item in entry.get("time_items", []):
            for item in time_item.get("theme_items", []):
                if (
                    item.get("subject_id") == "L0"
                    and item.get("legislator_type_id") == "L1"
                    and item.get("session") in sessions
                ):
                    items.append(item)
    return items


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | list:
    r = await client.get(url)
    r.raise_for_status()
    return r.json()


async def _fetch_entry(client: httpx.AsyncClient, item: dict) -> list[dict]:
    if item.get("has_data"):
        data = await _fetch_json(client, tickets_url(item))
        records = [row for rows in data.values() for row in rows]
        for record in records:
            record["vote_date"] = item["vote_date"]
        return records
    # 第 9、10 屆補選在 tickets API 沒有資料，只有得票數一覽表附件（無出生年）
    return await fetch_attachment_records(client, item)


async def _run(sessions: list[int], force: bool) -> None:
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        raw = await _fetch_json(client, f"{BASE_URL}/static/elections/list/BEL_L0.json")
        items = parse_by_election_items(raw, set(sessions))

        pending: list[tuple[dict, Path, list[dict]]] = []
        for item in sorted(items, key=lambda i: (i["session"], i["vote_date"], i["theme_name"])):
            path = output_path(item["session"], item["theme_name"])
            if path.exists() and not force:
                print(f"  skip {path}")
                continue
            records = await _fetch_entry(client, item)
            if not records:
                print(f"  WARNING {item['theme_name']}: 讀不到候選人資料")
                continue
            pending.append((item, path, records))
            await asyncio.sleep(0.3)

        # 先湊齊每屆的名單，再一次讀該屆的公報補出生年
        for session in sorted({item["session"] for item, _, _ in pending}):
            names = {
                str(r["cand_name"]).strip()
                for item, _, records in pending if item["session"] == session
                for r in records
            }
            birthyears = gazette_birthyears(session, names)
            for item, path, records in pending:
                if item["session"] != session:
                    continue
                for record in records:
                    if not record.get("cand_birthyear"):
                        record["cand_birthyear"] = birthyears.get(str(record["cand_name"]).strip())
                write_xlsx(records, path)
                print(f"  wrote {path}  ({len(records)} 筆)")
                missing = [r["cand_name"] for r in records if not r.get("cand_birthyear")]
                if missing:
                    print(f"    WARNING 公報查不到出生年: {'、'.join(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch legislator by-election XLSX from CEC")
    parser.add_argument("--session", type=int, action="append", help="session number, repeatable")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    args = parser.parse_args()
    sessions = args.session if args.session else [7, 8]
    asyncio.run(_run(sessions, args.force))


if __name__ == "__main__":
    main()
