import asyncio
import argparse
from pathlib import Path

import httpx
import openpyxl

BASE_URL = 'https://db.cec.gov.tw'
DATA_ROOT = Path('_data/council')

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

# ELC_T1 = 直轄市議員, ELC_T2 = 縣市議員
SUBJECT_LIST = [
    ('T1', '直轄市議員'),
    ('T2', '縣市議員'),
]


def output_path(session: int, council_type: str, desc: str, area_name: str | None = None) -> Path:
    folder = DATA_ROOT / str(session + 1911)
    if area_name:
        return folder / f'{council_type}_{desc}_{area_name}.xlsx'
    return folder / f'{council_type}_{desc}.xlsx'


def list_url(subject_id: str) -> str:
    return f'{BASE_URL}/static/elections/list/ELC_{subject_id}.json'


def areas_url(subject_id: str, legis_id: str, theme_id: str) -> str:
    return f'{BASE_URL}/static/elections/data/areas/ELC/{subject_id}/{legis_id}/{theme_id}/C/00_000_00_000_0000.json'


def tickets_url(subject_id: str, legis_id: str, theme_id: str, data_level: str, prv_code: str, city_code: str = '000') -> str:
    loc = f'{prv_code}_{city_code}_00_000_0000'
    return f'{BASE_URL}/static/elections/data/tickets/ELC/{subject_id}/{legis_id}/{theme_id}/{data_level}/{loc}.json'


def write_xlsx(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([col for col, _ in XLSX_COLUMNS])
    for r in records:
        ws.append([r.get(field) for _, field in XLSX_COLUMNS])
    wb.save(path)


def parse_session_map(data: list[dict]) -> dict:
    """Returns {(session, legis_id): {theme_id, data_level, desc}} for all entries."""
    result = {}
    for entry in data:
        for item in entry.get('theme_items', []):
            s = item['session']
            lid = item['legislator_type_id']
            result[(s, lid)] = {
                'theme_id':   item['theme_id'],
                'subject_id': item['subject_id'],
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
    council_type: str,
    legis_id: str,
    entry: dict,
    force: bool,
) -> None:
    theme_id   = entry['theme_id']
    subject_id = entry['subject_id']
    data_level = entry['data_level']
    desc       = entry['desc']

    if data_level == 'A':
        # 需按縣市逐一抓取
        areas_data = await _fetch_json(client, areas_url(subject_id, legis_id, theme_id))
        await asyncio.sleep(2)
        cities = list(areas_data.values())[0]
        for city in cities:
            prv_code  = city['prv_code']
            city_code = city['city_code']
            area_name = city['area_name']
            path = output_path(session, council_type, desc, area_name)
            if path.exists() and not force:
                print(f'  skip {path.name}')
                continue
            try:
                url = tickets_url(subject_id, legis_id, theme_id, data_level, prv_code, city_code)
                data = await _fetch_json(client, url)
                records = list(data.values())[0]
                write_xlsx(records, path)
                print(f'  wrote {path}')
                await asyncio.sleep(2)
            except Exception as e:
                print(f'  WARNING {area_name}: {e}')
    else:
        # dataLevel=C：全國單一檔案
        path = output_path(session, council_type, desc)
        if path.exists() and not force:
            print(f'  skip {path.name}')
            return
        try:
            url = tickets_url(subject_id, legis_id, theme_id, data_level, '00')
            data = await _fetch_json(client, url)
            records = list(data.values())[0]
            write_xlsx(records, path)
            print(f'  wrote {path}')
            await asyncio.sleep(2)
        except Exception as e:
            print(f'  WARNING {council_type} {desc}: {e}')


async def _run(sessions: list[int], force: bool) -> None:
    """
    補齊指定屆次（民國年）的直轄市/縣市議員原始資料
    ex: uv run src/fetch_council.py --session 111
    """
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        for subject_id, council_type in SUBJECT_LIST:
            raw = await _fetch_json(client, list_url(subject_id))
            await asyncio.sleep(2)
            session_map = parse_session_map(raw)

            target_sessions = sessions if sessions else sorted({s for s, _ in session_map})

            for s in target_sessions:
                print(f'\n=== {council_type} 第{s}屆 ===')
                for legis_id in ('T1', 'T2', 'T3'):
                    entry = session_map.get((s, legis_id))
                    if not entry:
                        continue
                    await _scrape_entry(client, s, council_type, legis_id, entry, force)
                    await asyncio.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description='Fetch council member XLSX from CEC')
    parser.add_argument('--session', type=int, help='single session (民國年, e.g. 111)')
    parser.add_argument('--force',   action='store_true', help='overwrite existing files')
    args = parser.parse_args()
    sessions = [args.session] if args.session else []
    asyncio.run(_run(sessions, args.force))


if __name__ == '__main__':
    main()
