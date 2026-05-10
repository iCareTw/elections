import asyncio
import argparse
from pathlib import Path

import httpx
import openpyxl

BASE_URL = 'https://db.cec.gov.tw'

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

SUBJECT_LIST = [
    ('D1', '00', 'D', 'indigenous_chief', '直轄市山地原住民區長'),
    ('R1', 'R3', 'A', 'indigenous_rep',   '直轄市山地原住民區民代表'),
]


def output_path(data_dir: str, session: int, area_name: str) -> Path:
    return Path('_data') / data_dir / str(session + 1911) / f'{area_name}.xlsx'


def list_url(subject_id: str) -> str:
    return f'{BASE_URL}/static/elections/list/ELC_{subject_id}.json'


def areas_url(subject_id: str, legis_id: str, theme_id: str) -> str:
    return f'{BASE_URL}/static/elections/data/areas/ELC/{subject_id}/{legis_id}/{theme_id}/C/00_000_00_000_0000.json'


def tickets_url(subject_id: str, legis_id: str, theme_id: str, data_level: str, prv: str, city: str) -> str:
    loc = f'{prv}_{city}_00_000_0000'
    return f'{BASE_URL}/static/elections/data/tickets/ELC/{subject_id}/{legis_id}/{theme_id}/{data_level}/{loc}.json'


def write_xlsx(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([col for col, _ in XLSX_COLUMNS])
    for r in records:
        ws.append([r.get(field) for _, field in XLSX_COLUMNS])
    wb.save(path)


def parse_session_map(data: list[dict]) -> dict[int, str]:
    result = {}
    for entry in data:
        for item in entry.get('theme_items', []):
            result[item['session']] = item['theme_id']
    return result


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | list:
    r = await client.get(url)
    r.raise_for_status()
    return r.json()


async def _scrape_subject(
    client: httpx.AsyncClient,
    subject_id: str,
    legis_id: str,
    data_level: str,
    data_dir: str,
    label: str,
    sessions: list[int],
    force: bool,
) -> None:
    raw = await _fetch_json(client, list_url(subject_id))
    await asyncio.sleep(2)
    session_map = parse_session_map(raw)

    target = sessions if sessions else sorted(session_map)

    for s in target:
        theme_id = session_map.get(s)
        if not theme_id:
            print(f'  WARNING: no data for {label} session {s}')
            continue
        print(f'\n=== {label} {s}年 ===')

        areas_data = await _fetch_json(client, areas_url(subject_id, legis_id, theme_id))
        await asyncio.sleep(2)
        cities = list(areas_data.values())[0]

        for city in cities:
            prv_code  = city['prv_code']
            city_code = city['city_code']
            area_name = city['area_name']
            path = output_path(data_dir, s, area_name)
            if path.exists() and not force:
                print(f'  skip {path.name}')
                continue
            try:
                url = tickets_url(subject_id, legis_id, theme_id, data_level, prv_code, city_code)
                data = await _fetch_json(client, url)
                records = list(data.values())[0]
                write_xlsx(records, path)
                print(f'  wrote {path} ({len(records)} records)')
                await asyncio.sleep(2)
            except Exception as e:
                print(f'  WARNING {area_name}: {e}')


async def _run(sessions: list[int], force: bool) -> None:
    """
    補齊原住民區長（D1）及區民代表（R1）資料
    ex: uv run src/fetch_indigenous.py --session 111
    """
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        for subject_id, legis_id, data_level, data_dir, label in SUBJECT_LIST:
            await _scrape_subject(client, subject_id, legis_id, data_level, data_dir, label, sessions, force)
            await asyncio.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description='Fetch indigenous district election XLSX from CEC')
    parser.add_argument('--session', type=int, help='single session (民國年, e.g. 111)')
    parser.add_argument('--force',   action='store_true', help='overwrite existing files')
    args = parser.parse_args()
    sessions = [args.session] if args.session else []
    asyncio.run(_run(sessions, args.force))


if __name__ == '__main__':
    main()
