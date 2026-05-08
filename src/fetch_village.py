import asyncio
import argparse
from pathlib import Path

import httpx
import openpyxl

BASE_URL = 'https://db.cec.gov.tw'
DATA_ROOT = Path('_data/village')
SUBJECT_ID = 'V0'
LEGIS_ID = '00'

XLSX_COLUMNS = [
    ('地區',  'area_name'),
    ('號次',  'cand_no'),
    ('姓名',  'cand_name'),
    ('性別',  'cand_sex'),
    ('出生年', 'cand_birthyear'),
    ('政黨',  'party_name'),
    ('得票數', 'ticket_num'),
    ('得票率', 'ticket_percent'),
    ('當選',  'is_victor'),
]


def output_path(session: int, desc: str, area_name: str) -> Path:
    year = str(session + 1911)
    name = f'{desc}_{area_name}.xlsx' if desc else f'{area_name}.xlsx'
    return DATA_ROOT / year / name


def list_url() -> str:
    return f'{BASE_URL}/static/elections/list/ELC_{SUBJECT_ID}.json'


def areas_url(theme_id: str) -> str:
    return f'{BASE_URL}/static/elections/data/areas/ELC/{SUBJECT_ID}/{LEGIS_ID}/{theme_id}/C/00_000_00_000_0000.json'


def tickets_url(theme_id: str, prv_code: str, city_code: str) -> str:
    loc = f'{prv_code}_{city_code}_00_000_0000'
    return f'{BASE_URL}/static/elections/data/tickets/ELC/{SUBJECT_ID}/{LEGIS_ID}/{theme_id}/L/{loc}.json'


def write_xlsx(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([col for col, _ in XLSX_COLUMNS])
    for r in records:
        ws.append([r.get(field) for _, field in XLSX_COLUMNS])
    wb.save(path)


def parse_entries(data: list[dict]) -> list[dict]:
    """Returns list of {session, theme_id, desc} preserving duplicates (e.g. session 99 has two entries)."""
    result = []
    for entry in data:
        for item in entry.get('theme_items', []):
            result.append({
                'session':  item['session'],
                'theme_id': item['theme_id'],
                'desc':     item.get('legislator_desc') or '',
            })
    return result


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | list:
    r = await client.get(url)
    r.raise_for_status()
    return r.json()


async def _scrape_entry(
    client: httpx.AsyncClient,
    session: int,
    theme_id: str,
    desc: str,
    force: bool,
) -> None:
    areas_data = await _fetch_json(client, areas_url(theme_id))
    await asyncio.sleep(2)
    counties = list(areas_data.values())[0]

    for county in counties:
        prv_code  = county['prv_code']
        city_code = county['city_code']
        area_name = county['area_name']
        path = output_path(session, desc, area_name)
        if path.exists() and not force:
            print(f'  skip {path.name}')
            continue
        try:
            url = tickets_url(theme_id, prv_code, city_code)
            data = await _fetch_json(client, url)
            # V0 is multi-key: one key per township — must flatten all values
            records = [row for rows in data.values() for row in rows]
            write_xlsx(records, path)
            print(f'  wrote {path} ({len(records)} records)')
            await asyncio.sleep(2)
        except Exception as e:
            print(f'  WARNING {area_name}: {e}')


async def _run(sessions: list[int], force: bool) -> None:
    """
    補齊指定屆次（民國年）的村里長原始資料
    ex: uv run src/fetch_village.py --session 111
    """
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        raw = await _fetch_json(client, list_url())
        await asyncio.sleep(2)
        entries = parse_entries(raw)

        target = set(sessions) if sessions else None

        for entry in entries:
            s = entry['session']
            if target and s not in target:
                continue
            desc = entry['desc']
            print(f'\n=== 村里長 {s}年 {desc} ===')
            await _scrape_entry(client, s, entry['theme_id'], desc, force)
            await asyncio.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description='Fetch village chief XLSX from CEC')
    parser.add_argument('--session', type=int, help='single session (民國年, e.g. 111)')
    parser.add_argument('--force',   action='store_true', help='overwrite existing files')
    args = parser.parse_args()
    sessions = [args.session] if args.session else []
    asyncio.run(_run(sessions, args.force))


if __name__ == '__main__':
    main()
