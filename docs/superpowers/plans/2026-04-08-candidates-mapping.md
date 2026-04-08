# Candidates Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 從 `_data/president/` 與 `_data/mayor/` 的 xlsx 檔自動解析, 產生 `candidates.yaml` 與 `election_types.yaml`. 

**Architecture:** 三個獨立模組(normalize, parse_president, parse_mayor)各自解析資料, draft 模組整合成 YAML 草稿供人工審閱後寫入 `candidates.yaml`. validate 模組驗證最終結果. 

**Tech Stack:** Python 3.14, openpyxl, PyYAML, pytest(透過 `uv run` 執行)

---

## 檔案結構

```
elections/
├── src/
│   ├── __init__.py
│   ├── normalize.py        # 姓名正規化, ID 生成
│   ├── parse_president.py  # 解析總統 xlsx
│   ├── parse_mayor.py      # 解析縣市首長 xlsx
│   ├── draft.py            # 整合解析結果, 輸出 YAML 草稿
│   └── validate.py         # 驗證 candidates.yaml
├── tests/
│   ├── __init__.py
│   ├── test_normalize.py
│   ├── test_parse_president.py
│   ├── test_parse_mayor.py
│   └── test_validate.py
├── candidates.yaml
├── election_types.yaml
└── main.py                 # CLI 入口
```

---

### Task 1: 安裝相依套件, 建立 election_types.yaml 與 pytest 設定

**Files:**
- Modify: `pyproject.toml`
- Create: `election_types.yaml`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: 安裝套件**

```bash
uv add pyyaml pytest
```

- [ ] **Step 2: 建立 src/ 與 tests/ 目錄**

```bash
mkdir -p src tests
touch src/__init__.py tests/__init__.py
```

- [ ] **Step 3: 建立 election_types.yaml**

```yaml
- id: 國家元首
  aliases:
    - 總統副總統選舉

- id: 縣市首長
  aliases:
    - 直轄市市長選舉
    - 縣市長選舉
    - 縣(市)長選舉

- id: 立法委員
  aliases:
    - 立法委員選舉
    - 立法委員補選

- id: 縣市議員
  aliases:
    - 直轄市議員選舉
    - 縣市議員選舉
    - 縣(市)議員選舉
```

- [ ] **Step 4: 確認 pytest 可執行**

```bash
uv run pytest --collect-only
```

Expected: `no tests ran`(不報錯即可)

- [ ] **Step 5: Commit**

```bash
git add src/ tests/ election_types.yaml pyproject.toml uv.lock
git commit -m "feat: setup project structure and election_types.yaml"
```

---

### Task 2: normalize 模組

**Files:**
- Create: `src/normalize.py`
- Create: `tests/test_normalize.py`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_normalize.py
from src.normalize import normalize_name, generate_id

def test_remove_special_chars():
    assert normalize_name("伍麗華Saidhai‧Tahovecahe") == "伍麗華SaidhaiTahovecahe"

def test_remove_whitespace():
    assert normalize_name("陳 明") == "陳明"

def test_remove_fullwidth_space():
    assert normalize_name("陳　明") == "陳明"

def test_remove_brackets():
    assert normalize_name("陳明(阿明)") == "陳明"
    assert normalize_name("陳明(阿明)") == "陳明"

def test_keep_english():
    assert normalize_name("SaidhaiTahovecahe") == "SaidhaiTahovecahe"

def test_generate_id_no_conflict():
    assert generate_id("許淑華") == "id_許淑華"

def test_generate_id_with_birth_year():
    assert generate_id("許淑華", birthday=1973) == "id_許淑華_1973"

def test_generate_id_with_birth_yearmonth():
    assert generate_id("許淑華", birthday="1973/05") == "id_許淑華_197305"

def test_generate_id_with_full_birthday():
    assert generate_id("許淑華", birthday="1973/05/22") == "id_許淑華_19730522"
```

- [ ] **Step 2: 確認測試失敗**

```bash
uv run pytest tests/test_normalize.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 實作 normalize.py**

```python
# src/normalize.py
import re

# 罕見字與特殊符號清單(寫死)
_REMOVE_PATTERN = re.compile(r'[\s\u3000‧·•()()【】\[\]]')

def normalize_name(name: str) -> str:
    """移除空白, 特殊符號, 罕見字, 保留中文, 英文, 數字. """
    return _REMOVE_PATTERN.sub('', name)

def generate_id(name: str, birthday=None) -> str:
    """
    birthday 可為 int (year only), str "yyyy/mm", str "yyyy/mm/dd", or None.
    """
    base = normalize_name(name)
    if birthday is None:
        return f"id_{base}"
    if isinstance(birthday, int):
        return f"id_{base}_{birthday}"
    # string: yyyy/mm/dd or yyyy/mm
    parts = str(birthday).split('/')
    suffix = ''.join(parts)
    return f"id_{base}_{suffix}"
```

- [ ] **Step 4: 確認測試通過**

```bash
uv run pytest tests/test_normalize.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/normalize.py tests/test_normalize.py
git commit -m "feat: add normalize module"
```

---

### Task 3: parse_president 模組

**Files:**
- Create: `src/parse_president.py`
- Create: `tests/test_parse_president.py`

xlsx 欄位順序：`地區, 姓名, 號次, 性別, 出生年次, 推薦政黨, 得票數, 得票率, 當選, 現任`

副手(running mate)的列：`號次=None`, `推薦政黨=None`(繼承正職候選人的黨籍與當選結果). 

任次 → 西元年公式：`year = 1996 + (任次 - 9) * 4`(第10任=2000, 第16任=2024)

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_parse_president.py
import openpyxl
from src.parse_president import parse_workbook, filename_to_year

def make_wb(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    return wb

def test_filename_to_year():
    assert filename_to_year("第16任總統副總統選舉.xlsx") == 2024
    assert filename_to_year("第14任總統副總統選舉.xlsx") == 2016
    assert filename_to_year("第10任總統副總統選舉.xlsx") == 2000

def test_parse_single_pair():
    wb = make_wb([
        ('地區', '姓名', '號次', '性別', '出生年次', '推薦政黨', '得票數', '得票率', '當選', '現任'),
        ('全國', '賴清德', 2, '男', '1959', '民主進步黨', '5,586,019', '40.05%', '*', '是'),
        (None,   '蕭美琴', None, '女', '1971', None, None, None, None, None),
    ])
    records = parse_workbook(wb, year=2024)
    assert len(records) == 2
    assert records[0] == {
        'name': '賴清德', 'birthday': 1959, 'year': 2024,
        'type': '國家元首', 'region': None,
        'party': '民主進步黨', 'elected': 1,
    }
    assert records[1] == {
        'name': '蕭美琴', 'birthday': 1971, 'year': 2024,
        'type': '國家元首', 'region': None,
        'party': '民主進步黨', 'elected': 1,
    }

def test_parse_losing_candidate():
    wb = make_wb([
        ('地區', '姓名', '號次', '性別', '出生年次', '推薦政黨', '得票數', '得票率', '當選', '現任'),
        ('全國', '侯友宜', 3, '男', '1957', '中國國民黨', '4,671,021', '33.49%', ' ', None),
        (None,   '趙少康', None, '男', '1950', None, None, None, None, None),
    ])
    records = parse_workbook(wb, year=2024)
    assert records[0]['elected'] == 0
    assert records[1]['elected'] == 0
    assert records[1]['party'] == '中國國民黨'
```

- [ ] **Step 2: 確認測試失敗**

```bash
uv run pytest tests/test_parse_president.py -v
```

Expected: FAIL

- [ ] **Step 3: 實作 parse_president.py**

```python
# src/parse_president.py
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
    current_party = None
    current_elected = None

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:  # header
            continue
        _, name, num, _, birth_year, party, _, _, elected_mark, _ = row
        if name is None:
            continue

        if num is not None:
            # 正職候選人
            current_party = party or '無黨籍及未經政黨推薦'
            current_elected = 1 if elected_mark == '*' else 0

        records.append({
            'name': str(name),
            'birthday': int(birth_year) if birth_year else None,
            'year': year,
            'type': '國家元首',
            'region': None,
            'party': current_party,
            'elected': current_elected,
        })
    return records

def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    year = filename_to_year(path.name)
    wb = openpyxl.load_workbook(path)
    return parse_workbook(wb, year)
```

- [ ] **Step 4: 確認測試通過**

```bash
uv run pytest tests/test_parse_president.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/parse_president.py tests/test_parse_president.py
git commit -m "feat: add parse_president module"
```

---

### Task 4: parse_mayor 模組

**Files:**
- Create: `src/parse_mayor.py`
- Create: `tests/test_parse_mayor.py`

xlsx 欄位同 president. `地區` 欄位：非 None 的列是新縣市的開始, 之後連續的 None 列屬同一縣市. 

民國年 → 西元：`西元 = 民國 + 1911`(從檔名解析, 如 `111年直轄市長選舉.xlsx` → 民國111 → 2022)

region 正規化：`臺` 取代 `台`. 

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_parse_mayor.py
import openpyxl
from src.parse_mayor import parse_workbook, filename_to_year, normalize_region

def make_wb(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    return wb

def test_filename_to_year():
    assert filename_to_year("111年直轄市長選舉.xlsx") == 2022
    assert filename_to_year("103年縣市長選舉.xlsx") == 2014

def test_normalize_region():
    assert normalize_region("臺北市") == "臺北市"
    assert normalize_region("台北市") == "臺北市"
    assert normalize_region("台中市") == "臺中市"

def test_parse_basic():
    wb = make_wb([
        ('地區', '姓名', '號次', '性別', '出生年次', '推薦政黨', '得票數', '得票率', '當選', '現任'),
        ('臺北市', '蔣萬安', 6, '男', '1978', '中國國民黨', '575,590', '42.29%', '*', None),
        (None,    '黃珊珊', 8, '女', '1969', '無黨籍及未經政黨推薦', '342,141', '25.14%', ' ', None),
    ])
    records = parse_workbook(wb, year=2022)
    assert len(records) == 2
    assert records[0] == {
        'name': '蔣萬安', 'birthday': 1978, 'year': 2022,
        'type': '縣市首長', 'region': '臺北市',
        'party': '中國國民黨', 'elected': 1,
    }
    assert records[1]['region'] == '臺北市'
    assert records[1]['elected'] == 0

def test_region_carries_across_rows():
    wb = make_wb([
        ('地區', '姓名', '號次', '性別', '出生年次', '推薦政黨', '得票數', '得票率', '當選', '現任'),
        ('新北市', '候選人A', 1, '男', '1970', '民主進步黨', '100', '50%', '*', None),
        (None,    '候選人B', 2, '男', '1975', '中國國民黨', '100', '50%', ' ', None),
        ('臺中市', '候選人C', 1, '女', '1980', '民主進步黨', '200', '60%', '*', None),
    ])
    records = parse_workbook(wb, year=2022)
    assert records[0]['region'] == '新北市'
    assert records[1]['region'] == '新北市'
    assert records[2]['region'] == '臺中市'
```

- [ ] **Step 2: 確認測試失敗**

```bash
uv run pytest tests/test_parse_mayor.py -v
```

Expected: FAIL

- [ ] **Step 3: 實作 parse_mayor.py**

```python
# src/parse_mayor.py
import re
from pathlib import Path
import openpyxl

def filename_to_year(filename: str) -> int:
    """103年直轄市長選舉.xlsx → 2014"""
    m = re.search(r'(\d+)年', filename)
    return int(m.group(1)) + 1911

def normalize_region(region: str) -> str:
    return region.replace('台', '臺')

def parse_workbook(wb: openpyxl.Workbook, year: int) -> list[dict]:
    ws = wb.active
    records = []
    current_region = None

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        region, name, _, _, birth_year, party, _, _, elected_mark, _ = row
        if name is None:
            continue
        if region is not None:
            current_region = normalize_region(str(region))

        records.append({
            'name': str(name),
            'birthday': int(birth_year) if birth_year else None,
            'year': year,
            'type': '縣市首長',
            'region': current_region,
            'party': party or '無黨籍及未經政黨推薦',
            'elected': 1 if elected_mark == '*' else 0,
        })
    return records

def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    year = filename_to_year(path.name)
    wb = openpyxl.load_workbook(path)
    return parse_workbook(wb, year)
```

- [ ] **Step 4: 確認測試通過**

```bash
uv run pytest tests/test_parse_mayor.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/parse_mayor.py tests/test_parse_mayor.py
git commit -m "feat: add parse_mayor module"
```

---

### Task 5: validate 模組

**Files:**
- Create: `src/validate.py`
- Create: `tests/test_validate.py`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_validate.py
from src.validate import validate_candidates

VALID_TYPES = {'國家元首', '縣市首長', '立法委員', '縣市議員'}

def test_valid_passes():
    candidates = [{
        'name': '柯文哲', 'id': 'id_柯文哲', 'birthday': 1959,
        'elections': [
            {'year': 2014, 'type': '縣市首長', 'region': '臺北市', 'party': '無黨籍及未經政黨推薦', 'elected': 1},
            {'year': 2024, 'type': '國家元首', 'region': None, 'party': '台灣民眾黨', 'elected': 0},
        ]
    }]
    assert validate_candidates(candidates, VALID_TYPES) == []

def test_invalid_type():
    candidates = [{'name': 'X', 'id': 'id_X', 'birthday': None,
        'elections': [{'year': 2024, 'type': '未知類型', 'region': None, 'party': 'A', 'elected': 0}]}]
    errors = validate_candidates(candidates, VALID_TYPES)
    assert any('未知類型' in e for e in errors)

def test_elections_not_sorted():
    candidates = [{'name': 'X', 'id': 'id_X', 'birthday': None,
        'elections': [
            {'year': 2024, 'type': '國家元首', 'region': None, 'party': 'A', 'elected': 0},
            {'year': 2018, 'type': '縣市首長', 'region': '臺北市', 'party': 'B', 'elected': 1},
        ]}]
    errors = validate_candidates(candidates, VALID_TYPES)
    assert any('排序' in e for e in errors)

def test_duplicate_ids():
    candidates = [
        {'name': 'X', 'id': 'id_X', 'birthday': None, 'elections': []},
        {'name': 'Y', 'id': 'id_X', 'birthday': None, 'elections': []},
    ]
    errors = validate_candidates(candidates, VALID_TYPES)
    assert any('id_X' in e for e in errors)
```

- [ ] **Step 2: 確認測試失敗**

```bash
uv run pytest tests/test_validate.py -v
```

Expected: FAIL

- [ ] **Step 3: 實作 validate.py**

```python
# src/validate.py

def validate_candidates(candidates: list[dict], valid_types: set[str]) -> list[str]:
    errors = []
    seen_ids = {}

    for c in candidates:
        cid = c.get('id', '')
        if cid in seen_ids:
            errors.append(f"重複 ID: {cid} ({seen_ids[cid]} 與 {c['name']})")
        seen_ids[cid] = c['name']

        years = [e['year'] for e in c.get('elections', [])]
        if years != sorted(years):
            errors.append(f"{c['name']} ({cid}): elections 未依 year 升冪排序")

        for e in c.get('elections', []):
            if e['type'] not in valid_types:
                errors.append(f"{c['name']} ({cid}): 未知 type '{e['type']}'")

    return errors
```

- [ ] **Step 4: 確認測試通過**

```bash
uv run pytest tests/test_validate.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/validate.py tests/test_validate.py
git commit -m "feat: add validate module"
```

---

### Task 6: merge 模組（比對邏輯）

**Files:**
- Create: `src/merge.py`
- Create: `tests/test_merge.py`

比對新解析的 records 與現有 candidates.yaml，分類為三種結果：
- `NEW` — 現有 yaml 找不到此人（normalized name 無匹配）
- `EXISTS` — 找到唯一匹配，且新的 election 尚未存在 → 自動合併
- `CONFLICT` — 同名多人，或同名一人但 birthday 不符

```python
# 回傳結構
{
    'auto': [   # 可直接處理，不需詢問
        {'action': 'new',    'record': {...}, 'candidate': None},
        {'action': 'merge',  'record': {...}, 'candidate': existing_candidate},
    ],
    'conflicts': [  # 需人工確認
        {
            'record': {...},           # 新資料
            'matches': [existing, ...] # 現有同名候選人列表
        },
    ]
}
```

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_merge.py
from src.merge import classify_records

EXISTING = [
    {
        'name': '柯文哲', 'id': 'id_柯文哲', 'birthday': 1959,
        'elections': [
            {'year': 2014, 'type': '縣市首長', 'region': '臺北市', 'party': '無黨籍及未經政黨推薦', 'elected': 1},
        ]
    },
    {'name': '許淑華', 'id': 'id_許淑華_1973', 'birthday': 1973, 'elections': []},
    {'name': '許淑華', 'id': 'id_許淑華_1975', 'birthday': 1975, 'elections': []},
]

def test_new_person():
    records = [{'name': '吳欣盈', 'birthday': 1978, 'year': 2024,
                'type': '國家元首', 'region': None, 'party': '台灣民眾黨', 'elected': 0}]
    result = classify_records(records, EXISTING)
    assert len(result['auto']) == 1
    assert result['auto'][0]['action'] == 'new'
    assert len(result['conflicts']) == 0

def test_existing_person_new_election():
    records = [{'name': '柯文哲', 'birthday': 1959, 'year': 2024,
                'type': '國家元首', 'region': None, 'party': '台灣民眾黨', 'elected': 0}]
    result = classify_records(records, EXISTING)
    assert len(result['auto']) == 1
    assert result['auto'][0]['action'] == 'merge'
    assert result['auto'][0]['candidate']['id'] == 'id_柯文哲'

def test_conflict_multiple_same_name():
    records = [{'name': '許淑華', 'birthday': 1971, 'year': 2024,
                'type': '國家元首', 'region': None, 'party': '民主進步黨', 'elected': 0}]
    result = classify_records(records, EXISTING)
    assert len(result['conflicts']) == 1
    assert len(result['conflicts'][0]['matches']) == 2

def test_duplicate_election_skipped():
    records = [{'name': '柯文哲', 'birthday': 1959, 'year': 2014,
                'type': '縣市首長', 'region': '臺北市', 'party': '無黨籍及未經政黨推薦', 'elected': 1}]
    result = classify_records(records, EXISTING)
    # 已存在的 election，不重複新增
    assert len(result['auto']) == 0
    assert len(result['conflicts']) == 0
```

- [ ] **Step 2: 確認測試失敗**

```bash
uv run pytest tests/test_merge.py -v
```

Expected: FAIL

- [ ] **Step 3: 實作 merge.py**

```python
# src/merge.py
from src.normalize import normalize_name


def classify_records(records: list[dict], existing: list[dict]) -> dict:
    """
    比對新 records 與現有 candidates，分類為 auto（可自動處理）與 conflicts（需人工）。
    """
    # 建立現有候選人的 normalized name index
    index: dict[str, list[dict]] = {}
    for c in existing:
        norm = normalize_name(c['name'])
        index.setdefault(norm, []).append(c)

    auto = []
    conflicts = []

    for r in records:
        norm = normalize_name(r['name'])
        matches = index.get(norm, [])

        if not matches:
            auto.append({'action': 'new', 'record': r, 'candidate': None})
            continue

        # 同名只有一人
        if len(matches) == 1:
            c = matches[0]
            # birthday 相符（或其中一方為 null）
            bday_ok = (r['birthday'] is None or c['birthday'] is None
                       or r['birthday'] == c['birthday'])
            if bday_ok:
                election = {k: r[k] for k in ('year', 'type', 'region', 'party', 'elected')}
                if election in c['elections']:
                    continue  # 已存在，跳過
                auto.append({'action': 'merge', 'record': r, 'candidate': c})
            else:
                conflicts.append({'record': r, 'matches': matches})
            continue

        # 同名多人 → conflict
        conflicts.append({'record': r, 'matches': matches})

    return {'auto': auto, 'conflicts': conflicts}


def apply_auto(auto: list[dict], existing: list[dict], valid_types: set[str]) -> list[dict]:
    """將 auto 結果套用至 existing（in-place 修改），回傳更新後的 list。"""
    from src.normalize import generate_id

    result = list(existing)
    name_index = {normalize_name(c['name']): c for c in result if
                  len([x for x in result if normalize_name(x['name']) == normalize_name(c['name'])]) == 1}

    for item in auto:
        r = item['record']
        if item['action'] == 'new':
            new_candidate = {
                'name': r['name'],
                'id': generate_id(r['name']),
                'birthday': r['birthday'],
                'elections': [{k: r[k] for k in ('year', 'type', 'region', 'party', 'elected')}],
            }
            result.append(new_candidate)
        elif item['action'] == 'merge':
            c = item['candidate']
            election = {k: r[k] for k in ('year', 'type', 'region', 'party', 'elected')}
            c['elections'].append(election)
            c['elections'].sort(key=lambda e: e['year'])

    return result
```

- [ ] **Step 4: 確認測試通過**

```bash
uv run pytest tests/test_merge.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/merge.py tests/test_merge.py
git commit -m "feat: add merge module with auto/conflict classification"
```

---

### Task 7: CLI 整合（main.py）

**Files:**
- Modify: `main.py`

CLI 格式：`uv run python main.py --type president --year 2024`

支援的 `--type` 值：`president`、`mayor`

- [ ] **Step 1: 實作 main.py**

```python
# main.py
import argparse
import sys
import yaml
from pathlib import Path

from src.parse_president import parse_file as parse_president
from src.parse_mayor import parse_file as parse_mayor
from src.merge import classify_records, apply_auto
from src.validate import validate_candidates

DATA_DIR = Path('_data')
CANDIDATES_FILE = Path('candidates.yaml')
ELECTION_TYPES_FILE = Path('election_types.yaml')

PARSERS = {
    'president': (parse_president, DATA_DIR / 'president'),
    'mayor':     (parse_mayor,     DATA_DIR / 'mayor'),
}

YEAR_FILTERS = {
    'president': lambda path, year: str(year) in path.stem or _president_year(path) == year,
    'mayor':     lambda path, year: str(int(path.stem[:3]) + 1911) == str(year) or
                                    str(int(''.join(filter(str.isdigit, path.stem[:4]))) + 1911) == str(year),
}

def _president_year(path: Path) -> int:
    import re
    m = re.search(r'第(\d+)任', path.stem)
    if not m:
        return 0
    return 1996 + (int(m.group(1)) - 9) * 4

def load_yaml(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or []

def load_valid_types() -> set[str]:
    data = load_yaml(ELECTION_TYPES_FILE)
    return {t['id'] for t in data}

def find_xlsx(type_: str, year: int) -> list[Path]:
    _, data_dir = PARSERS[type_]
    files = sorted(data_dir.glob('*.xlsx'))
    if type_ == 'president':
        return [f for f in files if _president_year(f) == year]
    else:
        return [f for f in files if str(int(''.join(filter(str.isdigit, f.stem[:3]))) + 1911) == str(year)]

def resolve_conflicts(conflicts: list[dict], existing: list[dict]) -> list[dict]:
    """互動式處理 conflicts，回傳需要追加至 existing 的新候選人（若選 n）。"""
    to_add = []
    from src.normalize import generate_id

    for i, item in enumerate(conflicts, 1):
        r = item['record']
        matches = item['matches']
        print(f'\n\033[33m─── 衝突 {i}/{len(conflicts)} ───────────────────────────────────────\033[0m')
        print(f'新資料：\033[1m{r["name"]}\033[0m  birthday:{r["birthday"]} | {r["type"]} {r["year"]} | {r["party"]} | elected:{r["elected"]}')
        print()
        print('\033[34m現有同名候選人：\033[0m')
        for j, c in enumerate(matches, 1):
            last = c['elections'][-1] if c['elections'] else {}
            print(f'  [{j}] {c["id"]}  生年:{c["birthday"]}  '
                  f'{last.get("type","")} {last.get("year","")} ({last.get("party","")})')

        choices = [str(j) for j in range(1, len(matches) + 1)]
        prompt = f'\n請選擇：{" ".join(f"[{j}]" for j in choices)} 合併  [n] 新增第三人  [s] 跳過 > '
        while True:
            ans = input(prompt).strip().lower()
            if ans in choices:
                c = matches[int(ans) - 1]
                election = {k: r[k] for k in ('year', 'type', 'region', 'party', 'elected')}
                c['elections'].append(election)
                c['elections'].sort(key=lambda e: e['year'])
                break
            elif ans == 'n':
                new_c = {
                    'name': r['name'],
                    'id': generate_id(r['name'], r['birthday']),
                    'birthday': r['birthday'],
                    'elections': [{k: r[k] for k in ('year', 'type', 'region', 'party', 'elected')}],
                }
                to_add.append(new_c)
                break
            elif ans == 's':
                print('  跳過')
                break
    return to_add

def main():
    parser = argparse.ArgumentParser(description='解析選舉資料並更新 candidates.yaml')
    parser.add_argument('--type', required=True, choices=list(PARSERS.keys()), help='選舉類型')
    parser.add_argument('--year', required=True, type=int, help='西元年份')
    args = parser.parse_args()

    parse_fn, _ = PARSERS[args.type]
    xlsx_files = find_xlsx(args.type, args.year)
    if not xlsx_files:
        print(f'找不到 {args.type} {args.year} 的資料檔', file=sys.stderr)
        sys.exit(1)

    print(f'解析 {len(xlsx_files)} 個檔案 ...')
    records = []
    for f in xlsx_files:
        records.extend(parse_fn(f))
    print(f'共 {len(records)} 筆記錄')

    existing = load_yaml(CANDIDATES_FILE)

    if not existing:
        # 首次執行：直接從新資料建立
        from src.merge import apply_auto
        result = apply_auto(
            [{'action': 'new', 'record': r, 'candidate': None} for r in records],
            [],
            load_valid_types()
        )
        print(f'\n首次建立 candidates.yaml，寫入 {len(result)} 筆')
    else:
        classified = classify_records(records, existing)
        auto_count = len(classified['auto'])
        conflict_count = len(classified['conflicts'])

        print(f'\n\033[32m自動合併 {auto_count} 筆\033[0m（無歧義）')
        if conflict_count:
            print(f'\033[33m需人工確認 {conflict_count} 筆\033[0m')

        result = apply_auto(classified['auto'], existing, load_valid_types())

        if classified['conflicts']:
            extra = resolve_conflicts(classified['conflicts'], result)
            result.extend(extra)

    # 驗證
    valid_types = load_valid_types()
    errors = validate_candidates(result, valid_types)
    if errors:
        print('\n驗證錯誤：', file=sys.stderr)
        for e in errors:
            print(f'  {e}', file=sys.stderr)
        sys.exit(1)

    result.sort(key=lambda c: c['name'])
    with open(CANDIDATES_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(result, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    print(f'\n\033[32m✓ 寫入 {CANDIDATES_FILE}（共 {len(result)} 筆）\033[0m')

if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 首次執行（candidates.yaml 不存在）**

```bash
uv run python main.py --type mayor --year 2022
```

Expected: 印出 `首次建立 candidates.yaml，寫入 N 筆`，產生 `candidates.yaml`

- [ ] **Step 3: 第二次執行（yaml 已存在，新增 president 2024）**

```bash
uv run python main.py --type president --year 2024
```

Expected: 印出自動合併筆數，若有衝突則出現互動提示

- [ ] **Step 4: 確認全部測試仍通過**

```bash
uv run pytest -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add main.py candidates.yaml
git commit -m "feat: wire CLI with incremental merge and interactive conflict resolution"
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add main.py candidates.yaml
git commit -m "feat: wire CLI and generate initial candidates.yaml"
```
