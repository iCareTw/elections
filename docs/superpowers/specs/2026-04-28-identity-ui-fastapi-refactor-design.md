# Identity UI — FastAPI 重構設計

**日期**: 2026-04-28
**範疇**: `src/webapp/` 全面重構, 資料架構調整

---

## 目標

1. 以 FastAPI + Jinja2 取代現有 `http.server` 實作.
2. 以 DB 作為候選人資料的 single source of truth, `candidates.yaml` 僅作為 export artifact.
3. 導入以一場選舉為單位的 commit 流程, 確保資料完整性.
4. 以 file-based logging 取代 `operation_logs` table.

---

## DB Schema

### 新增: `candidates`

```sql
CREATE TABLE candidates (
    id       TEXT    PRIMARY KEY,
    name     TEXT    NOT NULL,
    birthday INTEGER
);

CREATE INDEX idx_candidates_name ON candidates (name);
```

用途: `classify_record` 查詢此表取代讀取 `candidates.yaml`.
寫入時機: `POST /elections/{id}/commit` 批次 upsert.

### 移除: `operation_logs`

改以 file logging 取代.

### 保留不動

`elections`, `source_records`, `resolutions`.

### Migration 管理

SQL 腳本納入版本控管:

```
db/
  001_init.sql    ← 最終 schema (elections, source_records, resolutions, candidates + index)
```

`Store.init_schema()` 改為執行 `001_init.sql`, 不再內嵌 DDL.

---

## Logging

以 Python `logging` module 輸出至 `logs/` 目錄, `logs/` 加入 `.gitignore`.

| 檔案                  | 內容                              | Rotation       |
|-----------------------|-----------------------------------|----------------|
| `logs/operations.log` | load, commit, generate 操作摘要   | 10 MB / 5 備份 |
| `logs/errors.log`     | exception traceback               | 10 MB / 5 備份 |

**Commit log 原則**: 只記錄 commit summary (election_id, 總筆數, auto/manual 比例). 不記錄 review 過程中的每一次異動.

---

## 專案結構

```
src/webapp/
  app.py              ← FastAPI app 初始化, SessionMiddleware, router 掛載, logging setup
  routes/
    __init__.py
    elections.py      ← GET /, POST /elections/{id}/load
    review.py         ← GET /review/{id}, POST /review/{id}/resolve, POST /elections/{id}/commit
    build.py          ← POST /build
  templates/
    base.html         ← layout shell (navigator + workspace)
    elections.html    ← 首頁: _data/ 樹狀清單
    review.html       ← 審核頁
  static/
    styles.css        ← 沿用現有色系與樣式
  store.py            ← 更新: 加 candidates methods, 移除 operation_log methods
  matching.py         ← 更新: query candidates table 取代讀 yaml
  build_candidates.py ← 幾乎不動
  discovery.py        ← 不動

db/
  001_init.sql

logs/                 ← gitignore
```

---

## Routes

| Method | Path                          | 說明                                              |
|--------|-------------------------------|---------------------------------------------------|
| GET    | `/`                           | 選舉列表 (樹狀, 鏡像 `_data/`)                    |
| POST   | `/elections/{id}/load`        | 匯入 xlsx, auto-classify, redirect → review 頁    |
| GET    | `/review/{id}`                | 審核頁, 從 session 讀取待審佇列                   |
| POST   | `/review/{id}/resolve`        | 儲存一筆決策到 session, redirect → 同頁            |
| POST   | `/elections/{id}/commit`      | 批次寫入 DB, flush log, 清除 session              |
| POST   | `/build`                      | 產生 `candidates.yaml`, redirect → `/?generated=N` |

---

## UI Layout

左右雙欄配置, 沿用現有 warm paper 色系.

### 左側: Navigator (280px)

- Brand header
- Refresh 按鈕
- `_data/` 鏡像樹狀清單 (緊湊列高, `padding: 1px`, `line-height: 1.5`)
  - 目錄節點: `president/`, `mayor/`
  - 檔案列: 檔名 + status badge (todo / review / done)
  - 點選後 navigate 到對應頁面 (full-page render)
- 底部: **Generate candidates.yaml** 按鈕 (project-level 操作, 與選舉操作明確分離)

### 右側: Workspace

**State A — todo (尚未 load)**

選取 todo 選舉時, workspace 中央顯示檔案名稱與明確 CTA:

```
[檔名]
此選舉尚未匯入
[↓ Load Election]
```

**State B — review (審核中)**

- Header: 路徑 + 檔名 + progress bar ("t / N 已完成")
- 主體: 左右分欄
  - 左: Incoming Record (欄位明細)
  - 右: Possible Existing Candidates (match cards, 可選取)
- 底部操作列:
  - 左: ← 上一筆 / 下一筆 →
  - 右: **Use Selected Match** / **Create New Person** (無 Skip)
- Commit 區塊:
  - t < N: 灰色 disabled 按鈕 + 提示文字
  - t == N: 綠色 banner + 啟用 **Commit to DB →**

**State C — done (已 commit)**

badge 顯示 done, workspace 顯示摘要 (總筆數, auto/manual 分布).

---

## 核心邏輯異動

### `matching.py`

```python
# Before
classify_record(record: dict, existing: list[dict]) -> dict

# After
classify_record(record: dict, store: Store) -> dict
```

查詢 `candidates` table 取代讀取 `candidates.yaml` list.

### Session 結構

```python
# session key: f"pending_{election_id}"
{
    "<source_record_id>": {
        "mode": "auto" | "new" | "manual",
        "candidate_id": "<id>"
    },
    ...
}
```

- Load 時: auto/new 直接寫入 session; manual 列入待審佇列.
- Resolve 時: 更新 session 中該筆決策.
- Commit 條件: session 中所有 source_record 都有決策 (pending == 0).
- Commit 後: 批次寫 `resolutions` + `candidates`, flush log, 清除 session key.

### `election_types.yaml`

維持檔案形式. 僅在 `write_candidates_yaml` 驗證時讀取, 不入 DB.

---

## 不在本次範疇

- Legislator, council 資料處理.
- 使用者認證 / 多人協作.
- htmx 或任何 JS framework.
