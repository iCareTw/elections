import re
from pathlib import Path

import openpyxl


def filename_to_year(filename: str) -> int:
    """第N任總統副總統選舉.xlsx → 西元年"""
    m = re.search(r'第(\d+)任', filename)
    n = int(m.group(1))
    return 1996 + (n - 9) * 4


def parse_workbook(wb: openpyxl.Workbook, year: int) -> list[dict]:
    ws = wb.active
    records = []
    current_type = None
    current_ticket = None
    current_party = None
    current_elected = None

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:  # header
            continue
        _, name, num, _, birth_year, party, _, _, elected_mark, _ = row
        if name is None:
            continue

        if num is not None:
            # 正職候選人（總統），記錄號次、黨籍與當選狀態（副手繼承）
            current_type = '國家元首_總統'
            current_ticket = int(num)
            current_party = '無黨籍' if not party or party == '無黨籍及未經政黨推薦' else party
            current_elected = 1 if elected_mark == '*' else 0
        else:
            current_type = '國家元首_副總統'

        records.append({
            'name': str(name),
            'birthday': int(birth_year) if birth_year else None,
            'year': year,
            'type': current_type,
            'region': '全國',
            'ticket': current_ticket,
            'party': current_party,
            'elected': current_elected,
        })
    return records


def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    year = filename_to_year(path.name)
    wb = openpyxl.load_workbook(path)
    return parse_workbook(wb, year)
