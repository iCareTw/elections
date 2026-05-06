import asyncio
import argparse
from pathlib import Path

import httpx
import openpyxl

BASE_URL = 'https://db.cec.gov.tw'
DATA_ROOT = Path('_data/township')
SUBJECT_ID = 'D2'
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


def output_path(session: int, area_name: str) -> Path:
    return DATA_ROOT / str(session + 1911) / f'{area_name}.xlsx'


def list_url() -> str:
    return f'{BASE_URL}/static/elections/list/ELC_{SUBJECT_ID}.json'


def areas_url(theme_id: str) -> str:
    return f'{BASE_URL}/static/elections/data/areas/ELC/{SUBJECT_ID}/{LEGIS_ID}/{theme_id}/C/00_000_00_000_0000.json'


def tickets_url(theme_id: str, prv_code: str, city_code: str) -> str:
    loc = f'{prv_code}_{city_code}_00_000_0000'
    return f'{BASE_URL}/static/elections/data/tickets/ELC/{SUBJECT_ID}/{LEGIS_ID}/{theme_id}/D/{loc}.json'


def write_xlsx(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([col for col, _ in XLSX_COLUMNS])
    for r in records:
        ws.append([r.get(field) for _, field in XLSX_COLUMNS])
    wb.save(path)


def parse_session_map(data: list[dict]) -> dict:
    """Returns {session: theme_id} for all entries."""
    result = {}
    for entry in data:
        for item in entry.get('theme_items', []):
            result[item['session']] = item['theme_id']
    return result


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | list:
    r = await client.get(url)
    r.raise_for_status()
    return r.json()


async def _scrape_session(
    client: httpx.AsyncClient,
    session: int,
    theme_id: str,
    force: bool,
) -> None:
    areas_data = await _fetch_json(client, areas_url(theme_id))
    await asyncio.sleep(2)
    counties = list(areas_data.values())[0]

    for county in counties:
        prv_code  = county['prv_code']
        city_code = county['city_code']
        area_name = county['area_name']
        path = output_path(session, area_name)
        if path.exists() and not force:
            print(f'  skip {path.name}')
            continue
        try:
            data = await _fetch_json(client, tickets_url(theme_id, prv_code, city_code))
            records = list(data.values())[0]
            write_xlsx(records, path)
            print(f'  wrote {path}')
            await asyncio.sleep(2)
        except Exception as e:
            print(f'  WARNING {area_name}: {e}')


async def _run(sessions: list[int], force: bool) -> None:
    """
    補齊指定屆次（民國年）的鄉鎮市長原始資料
    ex: uv run src/fetch_township.py --session 111
    """
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        raw = await _fetch_json(client, list_url())
        await asyncio.sleep(2)
        session_map = parse_session_map(raw)

        target_sessions = sessions if sessions else sorted(session_map)

        for s in target_sessions:
            theme_id = session_map.get(s)
            if not theme_id:
                print(f'WARNING: no data for session {s}')
                continue
            print(f'\n=== 鄉鎮市長 {s}年 ===')
            await _scrape_session(client, s, theme_id, force)
            await asyncio.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description='Fetch township mayor XLSX from CEC')
    parser.add_argument('--session', type=int, help='single session (民國年, e.g. 111)')
    parser.add_argument('--force',   action='store_true', help='overwrite existing files')
    args = parser.parse_args()
    sessions = [args.session] if args.session else []
    asyncio.run(_run(sessions, args.force))


if __name__ == '__main__':
    main()
