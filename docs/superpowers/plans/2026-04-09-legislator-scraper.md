# Legislator Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `src/fetch_legislator.py` to download district and indigenous legislator election data (sessions 3–11) from the CEC JSON API and save as XLSX files.

**Architecture:** The CEC website serves all data as static JSON. The scraper fetches session metadata from `ELC_L0.json`, discovers city lists and themeIds dynamically, then downloads per-city ticket JSON and converts to XLSX using `openpyxl`. No browser automation needed.

**Tech Stack:** Python 3.14, `httpx` (async HTTP), `openpyxl` (already in project), `asyncio`, `argparse`

---

## File Map

| Action | Path                                        | Responsibility                        |
|--------|---------------------------------------------|---------------------------------------|
| Create | `src/fetch_legislator.py`                   | All scraper logic + CLI               |
| Create | `tests/unit/test_fetch_legislator.py`       | Unit tests for pure functions         |
| Modify | `pyproject.toml`                            | Add `httpx` dependency                |

---

## Task 1: Add httpx dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add httpx**

```bash
uv add httpx
```

- [ ] **Step 2: Verify**

```bash
grep httpx pyproject.toml
```

Expected output contains: `"httpx>=`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add httpx dependency"
```

---

## Task 2: Path + URL helpers

**Files:**
- Create: `src/fetch_legislator.py`
- Create: `tests/unit/test_fetch_legislator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_fetch_legislator.py`:

```python
from pathlib import Path
from src.fetch_legislator import output_path, tickets_url, areas_url

# output_path

def test_output_path_l1():
    assert output_path(11, '區域', '臺北市') == Path('_data/legislator/11th/區域_臺北市.xlsx')

def test_output_path_l1_session3():
    assert output_path(3, '區域', '臺北縣') == Path('_data/legislator/3th/區域_臺北縣.xlsx')

def test_output_path_l2():
    assert output_path(11, '平地原住民') == Path('_data/legislator/11th/平地原住民.xlsx')

def test_output_path_l3():
    assert output_path(9, '山地原住民') == Path('_data/legislator/9th/山地原住民.xlsx')

# tickets_url

def test_tickets_url_l1_city():
    url = tickets_url('L1', 'abc123', '63', 'A')
    assert url == 'https://db.cec.gov.tw/static/elections/data/tickets/ELC/L0/L1/abc123/A/63_000_00_000_0000.json'

def test_tickets_url_l2_national():
    url = tickets_url('L2', 'def456', '00', 'N')
    assert url == 'https://db.cec.gov.tw/static/elections/data/tickets/ELC/L0/L2/def456/N/00_000_00_000_0000.json'

# areas_url

def test_areas_url():
    url = areas_url('abc123')
    assert url == 'https://db.cec.gov.tw/static/elections/data/areas/ELC/L0/L1/abc123/C/00_000_00_000_0000.json'
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/unit/test_fetch_legislator.py -v
```

Expected: `ImportError` — `fetch_legislator` does not exist yet.

- [ ] **Step 3: Create `src/fetch_legislator.py` with helpers**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/unit/test_fetch_legislator.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fetch_legislator.py tests/unit/test_fetch_legislator.py
git commit -m "feat: add path and URL helpers for legislator scraper"
```

---

## Task 3: XLSX writer

**Files:**
- Modify: `src/fetch_legislator.py`
- Modify: `tests/unit/test_fetch_legislator.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_fetch_legislator.py`:

```python
import openpyxl
import tempfile
from src.fetch_legislator import write_xlsx

def test_write_xlsx_creates_file_with_header_and_rows(tmp_path):
    records = [
        {
            'area_name': '臺北市第01選區', 'cand_no': 1, 'cand_name': '吳思瑤',
            'cand_sex': '2', 'cand_birthyear': '1974', 'party_name': '民主進步黨',
            'ticket_num': 91958, 'ticket_percent': 47.22, 'is_victor': '*',
        },
        {
            'area_name': '臺北市第01選區', 'cand_no': 2, 'cand_name': '王某某',
            'cand_sex': '1', 'cand_birthyear': '1970', 'party_name': '中國國民黨',
            'ticket_num': 80000, 'ticket_percent': 41.00, 'is_victor': '',
        },
    ]
    path = tmp_path / '11th' / '區域_臺北市.xlsx'
    write_xlsx(records, path)

    assert path.exists()
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ('地區', '號次', '姓名', '性別', '出生年', '政黨', '得票數', '得票率', '當選')
    assert rows[1][2] == '吳思瑤'
    assert rows[2][2] == '王某某'
    assert len(rows) == 3
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
uv run pytest tests/unit/test_fetch_legislator.py::test_write_xlsx_creates_file_with_header_and_rows -v
```

Expected: `ImportError` — `write_xlsx` not defined.

- [ ] **Step 3: Implement `write_xlsx`**

Add to `src/fetch_legislator.py` after `areas_url`:

```python
def write_xlsx(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([col for col, _ in XLSX_COLUMNS])
    for r in records:
        ws.append([r.get(field) for _, field in XLSX_COLUMNS])
    wb.save(path)
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
uv run pytest tests/unit/test_fetch_legislator.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fetch_legislator.py tests/unit/test_fetch_legislator.py
git commit -m "feat: add XLSX writer"
```

---

## Task 4: Session map parser

**Files:**
- Modify: `src/fetch_legislator.py`
- Modify: `tests/unit/test_fetch_legislator.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_fetch_legislator.py`:

```python
from src.fetch_legislator import parse_session_map

def test_parse_session_map_extracts_l1_l2_l3():
    raw = [
        {'area_name': '全國', 'theme_items': [
            {'session': 11, 'legislator_type_id': 'L1', 'theme_id': 'aaa', 'data_level': 'A', 'legislator_desc': '區域'},
            {'session': 11, 'legislator_type_id': 'L2', 'theme_id': 'bbb', 'data_level': 'N', 'legislator_desc': '平地原住民'},
            {'session': 11, 'legislator_type_id': 'L3', 'theme_id': 'ccc', 'data_level': 'N', 'legislator_desc': '山地原住民'},
            {'session': 11, 'legislator_type_id': 'L4', 'theme_id': 'ddd', 'data_level': 'N', 'legislator_desc': '不分區政黨'},
        ]},
    ]
    result = parse_session_map(raw)
    assert (11, 'L1') in result
    assert result[(11, 'L1')] == {'theme_id': 'aaa', 'data_level': 'A', 'desc': '區域'}
    assert (11, 'L2') in result
    assert (11, 'L3') in result
    assert (11, 'L4') not in result  # L4 excluded

def test_parse_session_map_excludes_out_of_range():
    raw = [
        {'area_name': '全國', 'theme_items': [
            {'session': 2,  'legislator_type_id': 'L1', 'theme_id': 'x', 'data_level': 'A', 'legislator_desc': '區域'},
            {'session': 3,  'legislator_type_id': 'L1', 'theme_id': 'y', 'data_level': 'A', 'legislator_desc': '區域'},
            {'session': 11, 'legislator_type_id': 'L1', 'theme_id': 'z', 'data_level': 'A', 'legislator_desc': '區域'},
            {'session': 12, 'legislator_type_id': 'L1', 'theme_id': 'w', 'data_level': 'A', 'legislator_desc': '區域'},
        ]},
    ]
    result = parse_session_map(raw)
    assert (2,  'L1') not in result
    assert (3,  'L1') in result
    assert (11, 'L1') in result
    assert (12, 'L1') not in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/unit/test_fetch_legislator.py::test_parse_session_map_extracts_l1_l2_l3 tests/unit/test_fetch_legislator.py::test_parse_session_map_excludes_out_of_range -v
```

Expected: `ImportError` — `parse_session_map` not defined.

- [ ] **Step 3: Implement `parse_session_map`**

Add to `src/fetch_legislator.py` after `write_xlsx`:

```python
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
```

- [ ] **Step 4: Run all tests**

```bash
uv run pytest tests/unit/test_fetch_legislator.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fetch_legislator.py tests/unit/test_fetch_legislator.py
git commit -m "feat: add session map parser"
```

---

## Task 5: Async scraper + CLI

**Files:**
- Modify: `src/fetch_legislator.py`

No unit tests for this task — network calls are integration-tested in Task 6.

- [ ] **Step 1: Append async scraper and CLI to `src/fetch_legislator.py`**

```python
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
            area_name = city['area_name']
            path = output_path(session, desc, area_name)
            if path.exists() and not force:
                print(f'  skip {path.name}')
                continue
            try:
                data = await _fetch_json(client, tickets_url(legis_id, theme_id, prv_code, data_level))
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
            data = await _fetch_json(client, tickets_url(legis_id, theme_id, '00', data_level))
            records = list(data.values())[0]
            write_xlsx(records, path)
            print(f'  wrote {path}')
        except Exception as e:
            print(f'  WARNING {desc}: {e}')


async def _run(sessions: list[int], force: bool) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        raw = await _fetch_json(client, f'{BASE_URL}/static/elections/list/ELC_L0.json')
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
```

- [ ] **Step 2: Run existing unit tests to confirm nothing broke**

```bash
uv run pytest tests/unit/test_fetch_legislator.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add src/fetch_legislator.py
git commit -m "feat: add async scraper and CLI"
```

---

## Task 6: Integration test — session 11

- [ ] **Step 1: Run session 11 only**

```bash
uv run python src/fetch_legislator.py --session 11
```

Expected output (example):

```
=== 第11屆 ===
  wrote _data/legislator/11th/區域_臺北市.xlsx
  wrote _data/legislator/11th/區域_新北市.xlsx
  ...
  wrote _data/legislator/11th/平地原住民.xlsx
  wrote _data/legislator/11th/山地原住民.xlsx
```

- [ ] **Step 2: Verify file count**

```bash
ls _data/legislator/11th/ | wc -l
```

Expected: 24 (22 cities + 平地原住民 + 山地原住民).

- [ ] **Step 3: Spot-check a file**

```bash
uv run python -c "
import openpyxl
wb = openpyxl.load_workbook('_data/legislator/11th/區域_臺北市.xlsx')
ws = wb.active
for row in list(ws.iter_rows(values_only=True))[:3]:
    print(row)
"
```

Expected: header row + candidate rows with 臺北市 data.

- [ ] **Step 4: Run skip logic — run again without --force**

```bash
uv run python src/fetch_legislator.py --session 11
```

Expected: all lines say `skip ...`, no files re-written.

- [ ] **Step 5: Commit**

```bash
git add _data/legislator/11th/
git commit -m "data: fetch 11th session legislator XLSX"
```

---

## Task 7: Fetch all sessions (3–10)

- [ ] **Step 1: Run remaining sessions**

```bash
uv run python src/fetch_legislator.py
```

This skips session 11 (already exists) and fetches 3–10.

- [ ] **Step 2: Verify directory structure**

```bash
ls _data/legislator/
```

Expected: `3th  4th  5th  6th  7th  8th  9th  10th  11th`

- [ ] **Step 3: Commit**

```bash
git add _data/legislator/
git commit -m "data: fetch legislator XLSX sessions 3–10"
```
