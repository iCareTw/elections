"""
抓中選會公告的縣市議員缺額補選「選舉結果清冊」。

中選會的選舉資料庫(db.cec.gov.tw)只收錄 2024 年之後的議員補選，更早的場次
只出現在全球資訊網的公告區「罷免、補選及重行選舉資訊／直轄市議員、縣市議員」，
附件是含出生年月日的 PDF 清冊，比資料庫的得票數一覽表還完整。

產出檔案放在 _data/council/{年}/，欄位與正選議員資料一致，可直接由
parse_councilor 解析。
"""
import argparse
import asyncio
import re
from pathlib import Path

import httpx
import openpyxl
import pdfplumber

BASE_URL = "https://www.cec.gov.tw"
# 公告區「罷免、補選及重行選舉資訊／直轄市議員、縣市議員」的分類編號
ARTICLE_LIST_ID = 628
DATA_ROOT = Path("_data/council")

XLSX_COLUMNS = ["地區", "號次", "姓名", "性別", "出生年", "政黨", "得票數", "得票率", "當選"]

_VOTE_DATE_RE = re.compile(r"投[（(]?開?[)）]?票日期[：:]\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_ROC_YEAR_RE = re.compile(r"(\d{2,3})")
_SPACE_RE = re.compile(r"[\s　]+")


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def election_name(article_title: str) -> str:
    """公告標題「…缺額補選結果」→ 選舉名稱「…缺額補選」。"""
    return article_title.strip().removesuffix("結果")


def output_path(year: int, name: str) -> Path:
    return DATA_ROOT / str(year) / f"{_safe_filename(name)}.xlsx"


def _clean(text: object) -> str:
    return _SPACE_RE.sub("", str(text or ""))


def _birthyear(cell: object) -> int | None:
    """清冊的出生年月日有 060/11/06、45 年 4 月 9 日、46.2.2 等寫法，取民國年轉西元。"""
    match = _ROC_YEAR_RE.search(str(cell or ""))
    if not match:
        return None
    return int(match.group(1)) + 1911


def _votes(cell: object) -> int:
    text = _clean(cell).replace(",", "")
    return int(text) if text.isdigit() else 0


def parse_result_pdf(pdf_path: Path) -> tuple[str | None, list[dict]]:
    """讀選舉結果清冊 PDF，回傳 (投票日 YYYY-MM-DD, 候選人記錄)。掃描檔會回傳 (None, [])。"""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""
        tables = page.extract_tables()

    vote_date = None
    match = _VOTE_DATE_RE.search(_SPACE_RE.sub("", text))
    if match:
        roc, month, day = (int(g) for g in match.groups())
        vote_date = f"{roc + 1911:04d}-{month:02d}-{day:02d}"

    rows: list[dict] = []
    for table in tables:
        for row in table:
            cells = [_clean(c) for c in row]
            # 清冊列：選舉區 號次 姓名 性別 出生年月日 政黨 得票數 是否當選 備註
            if len(cells) < 8 or not cells[1].isdigit():
                continue
            name = cells[2]
            if not name or cells[3] not in ("男", "女"):
                continue
            rows.append(
                {
                    "cand_no": int(cells[1]),
                    "name": name,
                    "sex": "1" if cells[3] == "男" else "2",
                    "birthyear": _birthyear(cells[4]),
                    "party": "無黨籍" if cells[5] in ("", "無") else cells[5],
                    "votes": _votes(cells[6]),
                    "elected": cells[7] == "是",
                }
            )
        if rows:
            break
    return vote_date, rows


def write_xlsx(name: str, rows: list[dict], path: Path) -> None:
    total = sum(r["votes"] for r in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(XLSX_COLUMNS)
    for r in rows:
        ws.append(
            [
                name,
                r["cand_no"],
                r["name"],
                r["sex"],
                r["birthyear"],
                r["party"],
                r["votes"],
                round(r["votes"] / total * 100, 2) if total else 0.0,
                "*" if r["elected"] else " ",
            ]
        )
    wb.save(path)


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict:
    r = await client.get(url, headers={"Referer": f"{BASE_URL}/central/article/list/{ARTICLE_LIST_ID}"})
    r.raise_for_status()
    return r.json()


async def list_by_elections(client: httpx.AsyncClient) -> list[dict]:
    """列出公告區裡的議員缺額補選（略過罷免案）。"""
    items: list[dict] = []
    page = 1
    while True:
        url = (
            f"{BASE_URL}/api/central/article/list?id={ARTICLE_LIST_ID}"
            f"&page={page}&keyword&beginDate&endDate&webRoute=central"
        )
        data = (await _fetch_json(client, url))["data"]
        for article in data["articleList"]:
            title = article["directName"]
            if "補選" in title and "罷免" not in title:
                items.append({"title": title, "article_id": article["directPath"]})
        if page >= data["pages"]["totalPage"]:
            return items
        page += 1


async def _scrape_item(client: httpx.AsyncClient, item: dict, force: bool, tmp_dir: Path) -> None:
    name = election_name(item["title"])
    detail = (await _fetch_json(client, f"{BASE_URL}/api/central/article/{item['article_id']}?webRoute=central"))["data"]
    files = detail.get("fileList") or []
    if not files:
        print(f"  WARNING {name}: 公告沒有附件")
        return

    pdf_bytes = (await client.get(f"{BASE_URL}/api/file/{files[0]['fileId']}.pdf")).content
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_pdf = tmp_dir / f"{_safe_filename(name)}.pdf"
    tmp_pdf.write_bytes(pdf_bytes)

    vote_date, rows = parse_result_pdf(tmp_pdf)
    if not vote_date or not rows:
        print(f"  WARNING {name}: 清冊讀不出內容（可能是掃描檔）")
        return

    path = output_path(int(vote_date[:4]), name)
    if path.exists() and not force:
        print(f"  skip {path}")
        return

    write_xlsx(name, rows, path)
    print(f"  wrote {path}  ({len(rows)} 筆)")


async def _run(force: bool, tmp_dir: Path) -> None:
    async with httpx.AsyncClient(timeout=60, verify=False, follow_redirects=True) as client:
        items = await list_by_elections(client)
        print(f"=== 公告區共 {len(items)} 場議員缺額補選 ===")
        for item in items:
            await _scrape_item(client, item, force, tmp_dir)
            await asyncio.sleep(0.3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch councilor by-election result rosters from CEC")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--pdf-dir", default="_out/cec_by_election", help="下載的清冊 PDF 存放位置")
    args = parser.parse_args()
    asyncio.run(_run(args.force, Path(args.pdf_dir)))


if __name__ == "__main__":
    main()
