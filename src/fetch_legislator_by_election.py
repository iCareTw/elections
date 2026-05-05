import argparse
import asyncio
import re
from pathlib import Path

import httpx
import openpyxl

BASE_URL = "https://db.cec.gov.tw"
DATA_ROOT = Path("_data/legislator/by-election-legislator")

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
                    and item.get("has_data") is True
                ):
                    items.append(item)
    return items


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | list:
    r = await client.get(url)
    r.raise_for_status()
    return r.json()


async def _scrape_entry(client: httpx.AsyncClient, item: dict, force: bool) -> None:
    path = output_path(item["session"], item["theme_name"])
    if path.exists() and not force:
        print(f"  skip {path}")
        return

    data = await _fetch_json(client, tickets_url(item))
    records = [row for rows in data.values() for row in rows]
    for record in records:
        record["vote_date"] = item["vote_date"]
    write_xlsx(records, path)
    print(f"  wrote {path}")


async def _run(sessions: list[int], force: bool) -> None:
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        raw = await _fetch_json(client, f"{BASE_URL}/static/elections/list/BEL_L0.json")
        items = parse_by_election_items(raw, set(sessions))
        for item in sorted(items, key=lambda i: (i["session"], i["vote_date"], i["theme_name"])):
            await _scrape_entry(client, item, force)
            await asyncio.sleep(0.3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch legislator by-election XLSX from CEC")
    parser.add_argument("--session", type=int, action="append", help="session number, repeatable")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    args = parser.parse_args()
    sessions = args.session if args.session else [7, 8]
    asyncio.run(_run(sessions, args.force))


if __name__ == "__main__":
    main()
