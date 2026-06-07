"""
Fetch T1/T2 by-election (補選) data from CEC attachment XLS files.
These elections have has_data=false in the tickets API; candidate data is only
available as XLS attachments at:
  {BASE}/data/attachments/BEL/{subject_id}/{theme_group}/list.json
"""
import asyncio
import re
from pathlib import Path

import httpx
import openpyxl
import xlrd

BASE_URL = "https://db.cec.gov.tw"
DATA_ROOT = Path("_data/council/by-election-councilor")

XLSX_COLUMNS = [
    ("投票日", "vote_date"),
    ("地區",   "area_name"),
    ("號次",   "cand_no"),
    ("姓名",   "cand_name"),
    ("性別",   "cand_sex"),
    ("出生年", "cand_birthyear"),
    ("政黨",   "party_name"),
    ("得票數", "ticket_num"),
    ("得票率", "ticket_percent"),
    ("當選",   "is_victor"),
]


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def output_path(vote_date: str, theme_name: str) -> Path:
    year = vote_date[:4] if vote_date else "unknown"
    return DATA_ROOT / year / f"{_safe_filename(theme_name)}.xlsx"


def _parse_votes_xls(xls_bytes: bytes, vote_date: str, theme_name: str) -> list[dict]:
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as f:
        f.write(xls_bytes)
        tmp = f.name
    try:
        wb = xlrd.open_workbook(tmp)
        ws = wb.sheet_by_index(0)
    finally:
        os.unlink(tmp)

    # Find candidate number row and 總計 row
    cand_no_row_idx = total_row_idx = None
    for i in range(ws.nrows):
        val0 = ws.cell_value(i, 0)
        val1 = ws.cell_value(i, 1)
        if val0 in ("", None) and (val1 == 1.0 or val1 == "1"):
            cand_no_row_idx = i
        if val0 == "總計":
            total_row_idx = i

    if cand_no_row_idx is None or total_row_idx is None:
        return []

    def row_vals(idx):
        return [ws.cell_value(idx, j) for j in range(ws.ncols)]

    cand_no_vals = row_vals(cand_no_row_idx)
    name_vals    = row_vals(cand_no_row_idx + 1)
    party_vals   = row_vals(cand_no_row_idx + 2)
    total_vals   = row_vals(total_row_idx)

    candidates = []
    for j in range(1, ws.ncols):
        v = cand_no_vals[j]
        if isinstance(v, float) and v >= 1:
            no = int(v)
        elif isinstance(v, str) and v.strip().isdigit():
            no = int(v)
        else:
            continue
        name  = str(name_vals[j]).replace("\n", " ").strip()
        party = str(party_vals[j]).strip() if party_vals[j] not in ("", None) else "無"
        votes = total_vals[j]
        if not name:
            continue
        candidates.append({"no": no, "name": name, "party": party, "votes": int(votes) if votes else 0})

    if not candidates:
        return []

    total_valid = sum(c["votes"] for c in candidates)
    max_votes   = max(c["votes"] for c in candidates)

    records = []
    for c in candidates:
        party = c["party"]
        if party in ("無", "") or not party:
            party = "無黨籍"
        pct = round(c["votes"] / total_valid * 100, 2) if total_valid else 0.0
        records.append({
            "vote_date":     vote_date,
            "area_name":     theme_name,
            "cand_no":       c["no"],
            "cand_name":     c["name"],
            "cand_sex":      None,
            "cand_birthyear": None,
            "party_name":    party,
            "ticket_num":    c["votes"],
            "ticket_percent": pct,
            "is_victor":     "*" if c["votes"] == max_votes else " ",
        })
    return records


def _write_xlsx(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([col for col, _ in XLSX_COLUMNS])
    for r in records:
        ws.append([r.get(field) for _, field in XLSX_COLUMNS])
    wb.save(path)


def _collect_items(raw: list[dict], subject_ids: set[str]) -> list[dict]:
    """Flatten BEL list; keep has_data=false items for the given subject_ids."""
    result = []
    seen = set()
    for term in raw:
        for time_item in term.get("time_items", []):
            for item in time_item.get("theme_items", []):
                tid = item.get("theme_id")
                if (
                    item.get("subject_id") in subject_ids
                    and not item.get("has_data")
                    and tid not in seen
                ):
                    seen.add(tid)
                    result.append(item)
    return result


async def _fetch_json(client: httpx.AsyncClient, url: str) -> list | dict:
    r = await client.get(url)
    r.raise_for_status()
    return r.json()


async def _fetch_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    r = await client.get(url)
    r.raise_for_status()
    return r.content


async def _scrape_item(client: httpx.AsyncClient, item: dict, force: bool) -> None:
    sid        = item["subject_id"]
    theme_name = item["theme_name"]
    theme_grp  = item["theme_group"]
    vote_date  = item.get("vote_date", "")
    path       = output_path(vote_date, theme_name)

    if path.exists() and not force:
        print(f"  skip {path.name}")
        return

    # Get attachment list
    list_url = f"{BASE_URL}/static/elections/data/attachments/BEL/{sid}/{theme_grp}/list.json"
    attachments = await _fetch_json(client, list_url)

    # Find the 得票數一覽表 XLS
    xls_entry = next(
        (a for a in attachments if "得票數一覽表" in a.get("file_name", "")),
        None,
    )
    if xls_entry is None:
        print(f"  WARNING {theme_name}: no 得票數一覽表 attachment")
        return

    xls_url = f"{BASE_URL}/static/{xls_entry['file_path']}"
    xls_bytes = await _fetch_bytes(client, xls_url)
    records = _parse_votes_xls(xls_bytes, vote_date, theme_name)

    if not records:
        print(f"  WARNING {theme_name}: failed to parse XLS")
        return

    _write_xlsx(records, path)
    print(f"  wrote {path}  ({len(records)} 筆)")
    await asyncio.sleep(0.5)


async def _run(subject_ids: list[str], force: bool) -> None:
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        all_items = []
        for sid in subject_ids:
            raw = await _fetch_json(client, f"{BASE_URL}/static/elections/list/BEL_{sid}.json")
            items = _collect_items(raw, {sid})
            print(f"\n=== BEL_{sid}: {len(items)} 場有附件的補選 ===")
            all_items.extend(items)

        for item in sorted(all_items, key=lambda i: (i["subject_id"], i.get("vote_date", ""))):
            await _scrape_item(client, item, force)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Fetch councilor by-election XLS from CEC")
    parser.add_argument("--subject", choices=["T1", "T2"], action="append",
                        help="subject_id to fetch (default: T1 and T2)")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    args = parser.parse_args()
    subjects = args.subject if args.subject else ["T1", "T2"]
    asyncio.run(_run(subjects, args.force))


if __name__ == "__main__":
    main()
