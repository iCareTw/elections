---
name: cec-scraper
description: >
  中選會 (CEC) 選舉資料爬蟲知識庫。涵蓋靜態 API 的 subject_id 對照、URL 公式、
  JSON 結構差異（單一 key vs 多 key）、以及各選舉類型的爬取策略。
  TRIGGER when: 討論或實作中選會爬蟲、規劃新的選舉類型爬取、檢查現有爬蟲邏輯。
---

# CEC 爬蟲知識庫

資料來源：`https://db.cec.gov.tw/static/elections/`（靜態 JSON，不需要解析 HTML）

---

## 已知 subject_id 對照表

| subject_id | 選舉類型 | 現有爬蟲 |
|---|---|---|
| `P0` | 總統副總統 | parse only（`_data/president/` 手動取得 XLSX） |
| `C1` | 直轄市長 | parse only（`_data/mayor/` 手動取得 XLSX） |
| `C2` | 縣市長（含補選） | parse only（同上） |
| `L0` | 立法委員 | `fetch_legislator.py` + `parse_legislator.py` |
| `T1` | 直轄市議員 | `fetch_councilor.py` + `parse_councilor.py`；補選見 `fetch_councilor_by_election.py` |
| `T2` | 縣市議員 | `fetch_councilor.py` + `parse_councilor.py`；補選見 `fetch_councilor_by_election.py` |
| `D1` | 直轄市山地原住民區長 | 無 |
| `D2` | 鄉鎮市長 | `fetch_township.py`（規劃中） |
| `R1` | 直轄市山地原住民區民代表 | 無 |
| `R2` | 鄉鎮市民代表 | 無 |
| `V0` | 村里長 | 無 |
| `N0` | 國大代表 | 部分 PDF（`_data/mna/`），暫擱置 |

> 臺灣省長、臺灣省議員：網站有顯示但靜態 API 全為 404，未數位化。

---

## API 端點公式

### 一般選舉（ELC）

```
BASE = https://db.cec.gov.tw/static/elections

# 1. 取得各屆 theme_id 清單
GET {BASE}/list/ELC_{subject_id}.json

# 2. 取得各縣市清單（C = 縣市層）
GET {BASE}/data/areas/ELC/{subject_id}/{legis_id}/{theme_id}/C/00_000_00_000_0000.json

# 3. 取得各區清單（D = 鄉鎮市區層，僅 V0 等需要往下鑽）
GET {BASE}/data/areas/ELC/{subject_id}/{legis_id}/{theme_id}/D/{prv}_{city}_00_000_0000.json

# 4. 取得候選人票選資料
GET {BASE}/data/tickets/ELC/{subject_id}/{legis_id}/{theme_id}/{data_level}/{prv}_{city}_00_000_0000.json
```

- `legis_id`：從 list JSON 的 `legislator_type_id` 欄位取得（多數為 `00`，T1/T2 用 `T1`/`T2`，R1 用 `R3`，R2 用 `R1`/`R2`）
- `data_level`：從 list JSON 的 `data_level` 欄位取得（`N`=全國, `C`=縣市, `D`=鄉鎮市區, `A`=選區, `L`=村里）
- `{prv}_{city}`：從 areas API 取得，例如宜蘭縣 = `10_002`，台北市 = `63_000`

---

### 補選（BEL）— 靜態 API

```
# 1. 取得補選清單（結構與 ELC 不同，見下方說明）
GET {BASE}/list/BEL_{subject_id}.json

# 2. 取得候選人票選資料（僅 has_data=true 的項目）
GET {BASE}/data/tickets/BEL/{subject_id}/{legis_id}/{theme_id}/{data_level}/{loc}.json
```

**BEL list JSON 結構**（與 ELC 完全不同，不要混用）：

```json
[
  {
    "term_index": "...",
    "time_items": [
      {
        "theme_items": [
          {
            "subject_id": "T2",
            "theme_id": "...",
            "theme_name": "宜蘭縣縣議員缺額補選",
            "theme_group": "1e40c844df20ebd152829ef5a2a01720",
            "vote_date": "2024-04-13",
            "has_data": false,
            "data_level": "A",
            "legislator_type_id": "T2"
          }
        ]
      }
    ]
  }
]
```

- `has_data: true` → 可從 tickets API 取得候選人資料
- `has_data: false` → tickets API 無資料，**必須改用附件（attachment）路徑**
- `data_level=C` 的單一選區縣（如花蓮、臺東、新竹縣立委補選）loc 要用 `00_000_00_000_0000` 而非 `{prv}_{city}_00_000_0000`

---

### 補選附件（BEL Attachment）— XLS 備用路徑

當 `has_data=false` 時，用附件端點取得 XLS 檔案：

```
# 取得附件清單
GET {BASE}/data/attachments/BEL/{subject_id}/{theme_group}/list.json

# Response 範例：
[
  {
    "file_name": "得票數一覽表.xls",
    "file_path": "elections/data/attachments/BEL/T2/1e40c844.../得票數一覽表.xls"
  },
  ...
]

# 下載 XLS
GET https://db.cec.gov.tw/static/{file_path}
```

⚠️ URL 含中文，需用支援 Unicode URL 的 HTTP 客戶端（`httpx`，不要用 `urllib`）。

**XLS「得票數一覽表」欄位佈局**：

```
row 0: 標題（含投票日期字串，如「投票日期：113年4月13日」）
row 1: 選舉名稱
row 2: 欄位標題（'行\n政\n區\n別', '各候選人得票情形', ...）
row 3: ['', 1, 2, 3, ...]     ← 候選人號次（float 或 str）
row 4: ['', name1, name2, ...]  ← 候選人姓名
row 5: ['', party1, party2, ...] ← 政黨（無黨籍寫 '無'）
row 6: ['總計', votes1, ...]     ← 全縣總票數
row 7+: 各行政區分項
```

解析方式：掃描 row 找「第一欄為空、第二欄為數字 1」作為 row 3 起點；找「第一欄為『總計』」作為 votes row。

⚠️ **已知限制**：
- T1/T2 補選 XLS 不含性別與出生年，這兩欄留空（`None`）。
- C2（縣市長）補選全部為**掃描版 PDF**，無法用程式解析（`pdfplumber` 取回空文字），需人工處理。

---

## ⚠️ 關鍵差異：JSON 的 top-level key 結構

tickets JSON 有兩種格式，**混淆會導致靜默漏資料，不會報錯**：

### 單一 key（safe to use `list(d.values())[0]`）

| 選舉類型 | data_level | 說明 |
|---|---|---|
| 直轄市長 (C1)、縣市長 (C2) | C | 整個縣市一個 flat list |
| 立法委員 (L0) | 按 legis_id 不同 | 每個選區一個請求 |
| 直轄市議員 (T1)、縣市議員 (T2) | A | 每縣市一個 key |
| 直轄市山地原住民區長 (D1) | D | 每市一個 key |
| 鄉鎮市長 (D2) | D | 每縣一個 key，全縣鄉鎮在同一 flat list |
| 直轄市山地原住民區民代表 (R1) | A | 每市一個 key |

### 多 key（每個鄉鎮一個 key，**必須合併所有 values**）

| 選舉類型 | data_level | key 格式 |
|---|---|---|
| 鄉鎮市民代表 (R2) | A | `{prv}_{city}_00_{dept}_0000`（一縣 12~13 個 key） |
| 村里長 (V0) | L | `{prv}_{city}_00_{dept}_0000`（一縣 12~13 個 key） |

**正確讀取方式：**

```python
# 單一 key（現有爬蟲用法，對上方單一 key 類型有效）
records = list(d.values())[0]

# 多 key（R2、V0 必須用這個）
records = [row for rows in d.values() for row in rows]
```

---

## 各類型詳細規格

### D1 直轄市山地原住民區長
- legis_id: `00`
- data_level: `D`
- 涵蓋：4 個直轄市（新北 `65_000`、桃園 `68_000`、臺中 `66_000`、高雄 `64_000`）
- 屆次：103、107、111 年（3 屆）
- JSON: 單一 key，每市 ~5 筆

### D2 鄉鎮市長
- legis_id: `00`
- data_level: `D`
- 涵蓋：13 個縣（非直轄市）
- 屆次：87、91、94、98、103、107、111 年（7 屆）
- JSON: 單一 key，全縣鄉鎮在同一 flat list（以 `dept_code` 區分鄉鎮）

### R1 直轄市山地原住民區民代表
- legis_id: `R3`
- data_level: `A`
- 涵蓋：4 個直轄市（同 D1）
- 屆次：103、107、111 年（3 屆）
- JSON: 單一 key（key 為該原住民區的完整地碼，例如 `65_000_00_290_0000`）

### R2 鄉鎮市民代表
- legis_id: `R1`（103 年以後）、`R2`（部分屆次）、`00`（99 年以前）
- data_level: `A`
- 涵蓋：13 個縣
- 屆次：99、103、107、111 年（4 屆）
- JSON: **多 key**，每鄉鎮一個 key，需合併

### V0 村里長
- legis_id: `00`
- data_level: `L`
- 涵蓋：22 縣市（全台）
- 屆次：99（直轄市里長 + 縣市村里長分開）、103、107、111 年（5 筆記錄）
- JSON: **多 key**，每鄉鎮一個 key，需合併
- 注意：99 年分兩筆（直轄市 / 非直轄市），需分開處理

---

## 建議爬蟲組織

參考現有 `fetch_councilor.py`（同時涵蓋 T1 + T2）的分組方式：

| 建議檔案 | 涵蓋 subject_id | 備注 |
|---|---|---|
| `fetch_township.py` | D2 | 鄉鎮市長，模仿 `fetch_councilor.py` |
| `fetch_chief.py` | D1 + D2 | 若要合併：首長類，涵蓋原住民區長和鄉鎮市長 |
| `fetch_township_rep.py` | R1 + R2 | 代表類，R2 需用多 key 合併 |
| `fetch_village.py` | V0 | 村里長，規模最大，多 key 合併 |

---

## 現有爬蟲的 `parse_session_map` 邏輯

以 `fetch_councilor.py` 為範本，list JSON 結構：

```python
# list JSON 的每個 area 底下有 theme_items
for entry in raw_list:
    for item in entry.get('theme_items', []):
        session   = item['session']        # 民國年（如 111）或屆次（如 11）
        legis_id  = item['legislator_type_id']
        theme_id  = item['theme_id']
        subject_id = item['subject_id']
        data_level = item['data_level']
        desc      = item['legislator_desc']  # 可能為 None 或描述字串
```

---

## 輸出格式（XLSX）

所有爬蟲輸出統一存至 `_data/{category}/`，欄位：

```python
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
```

票選 JSON 的可用欄位還包括：`cand_id`、`cand_edu`、`party_code`、`is_current`、`is_vice`。

---

## 注意事項

- 所有 HTTP 請求加 `verify=False`（CEC 的 SSL 憑證有問題）
- 爬取時加 `asyncio.sleep(2)` 避免過於頻繁（參考 `fetch_councilor.py`）
- 執行任何 Python 指令使用 `uv run python`
