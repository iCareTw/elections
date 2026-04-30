import asyncio
import argparse
from pathlib import Path

import httpx
import openpyxl

BASE_URL = 'https://db.cec.gov.tw'
DATA_ROOT = Path('_data/legislator/district-legislator')

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


def output_path(session: int, desc: str, area_name: str | None = None) -> Path:
    folder = DATA_ROOT / f'{session}th'
    if desc == '區域':
        return folder / f'區域_{area_name}.xlsx'
    return folder / f'{desc}.xlsx'


def tickets_url(legis_id: str, theme_id: str, prv_code: str, city_code: str, data_level: str) -> str:
    loc = f'{prv_code}_{city_code}_00_000_0000'
    return f'{BASE_URL}/static/elections/data/tickets/ELC/L0/{legis_id}/{theme_id}/{data_level}/{loc}.json'


def areas_url(theme_id: str) -> str:
    return f'{BASE_URL}/static/elections/data/areas/ELC/L0/L1/{theme_id}/C/00_000_00_000_0000.json'


def write_xlsx(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([col for col, _ in XLSX_COLUMNS])
    for r in records:
        ws.append([r.get(field) for _, field in XLSX_COLUMNS])
    wb.save(path)


def parse_session_map(data: list[dict]) -> dict:
    """Returns {(session, legis_id): {theme_id, data_level, desc}} for sessions 3–11, L1/L2/L3."""
    result = {}
    for entry in data:
        for item in entry.get('theme_items', []):
            s = item['session']
            lid = item['legislator_type_id']
            if 3 <= s <= 11 and lid in ('L1', 'L2', 'L3'):
                result[(s, lid)] = {
                    'theme_id':   item['theme_id'],
                    'data_level': item['data_level'],
                    'desc':       item['legislator_desc'],
                }
    return result


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | list:
    r = await client.get(url)
    r.raise_for_status()
    return r.json()


async def _scrape_entry(
    client: httpx.AsyncClient,
    session: int,
    legis_id: str,
    entry: dict,
    force: bool,
) -> None:
    theme_id   = entry['theme_id']
    data_level = entry['data_level']
    desc       = entry['desc']

    if legis_id == 'L1':
        areas_data = await _fetch_json(client, areas_url(theme_id))
        cities = list(areas_data.values())[0]
        for city in cities:
            prv_code  = city['prv_code']
            city_code = city['city_code']
            area_name = city['area_name']
            path = output_path(session, desc, area_name)
            if path.exists() and not force:
                print(f'  skip {path.name}')
                continue
            try:
                data = await _fetch_json(client, tickets_url(legis_id, theme_id, prv_code, city_code, data_level))
                records = list(data.values())[0]
                write_xlsx(records, path)
                print(f'  wrote {path}')
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f'  WARNING {area_name}: {e}')
    else:
        path = output_path(session, desc)
        if path.exists() and not force:
            print(f'  skip {path.name}')
            return
        try:
            data = await _fetch_json(client, tickets_url(legis_id, theme_id, '00', '000', data_level))
            records = list(data.values())[0]
            write_xlsx(records, path)
            print(f'  wrote {path}')
        except Exception as e:
            print(f'  WARNING {desc}: {e}')


async def _run(sessions: list[int], force: bool) -> None:
    """
    補齊指定屆次的 區域/平地原住民/山地原住民 立委 的原始資料
    ex: uv run src/fetch_legislator.py --session 11
    """
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        raw = await _fetch_json(client, f'{BASE_URL}/static/elections/list/ELC_L0.json')
        # https://db.cec.gov.tw/static/elections/list/ELC_L0.json
        session_map = parse_session_map(raw)
        for s in sorted(sessions):
            print(f'\n=== 第{s}屆 ===')
            for legis_id in ('L1', 'L2', 'L3'):
                entry = session_map.get((s, legis_id))
                if not entry:
                    print(f'  WARNING: no data for session {s} {legis_id}')
                    continue
                await _scrape_entry(client, s, legis_id, entry, force)
                await asyncio.sleep(0.3)


def main() -> None:
    parser = argparse.ArgumentParser(description='Fetch legislator XLSX from CEC')
    parser.add_argument('--session', type=int, help='single session number (3–11)')
    parser.add_argument('--force',   action='store_true', help='overwrite existing files')
    args = parser.parse_args()
    sessions = [args.session] if args.session else list(range(3, 12))
    asyncio.run(_run(sessions, args.force))


if __name__ == '__main__':
    main()
