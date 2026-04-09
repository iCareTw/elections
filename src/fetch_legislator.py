import asyncio
import argparse
from pathlib import Path

import httpx
import openpyxl

BASE_URL = 'https://db.cec.gov.tw'
DATA_ROOT = Path('_data/legislator')

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


def tickets_url(legis_id: str, theme_id: str, prv_code: str, data_level: str) -> str:
    loc = f'{prv_code}_000_00_000_0000'
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
