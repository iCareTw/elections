# 選舉公報 Web 檢視與後台修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把總統選舉公報解析結果落地 DB,建立一個獨立的三欄 Web 介面供瀏覽、人工疑慮標記、文字欄 local LLM 背景修復、照片手動圈選補正,並以 commit 快照做版本管理。

**Architecture:** 沿用既有 `Store`(psycopg + schema-scoped)與 FastAPI + Jinja2。新增 `guide_*` 表(欄位化);load 指令由 parser 產物(YAML + 依人類可讀命名慣例的切圖/照片)匯入;獨立 router/templates 呈現;文字欄修復走 `guide_repair_jobs` 背景工作;照片修正走「開 PDF 頁 → 前端框選 → 後端裁切覆蓋」。與 identity UI 完全獨立,不共用路由、不寫其表、不設 FK。

**Tech Stack:** Python 3.14、FastAPI、Jinja2、psycopg(pool)、PostgreSQL、pdfplumber(既有 `src/voter_guide` 幾何/裁切)、pytest。

**Spec:** `docs/superpowers/specs/2026-07-01-voter-guide-web-design.md`

---

## 通用約定

- 所有 Python 指令用 `uv run`(如 `uv run pytest`)。
- DB 測試沿用既有慣例:讀不到 DB 時 `pytest.skip(...)`(見 `tests/unit/test_store.py`)。測試 schema 由 `tests/conftest.py` 設為 `test_elections`。
- 每個 Task 結尾 commit;commit message 末尾附:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- migration 檔命名接續既有:下一個編號為 `005`。
- 新表全部建在目前 schema(schema-agnostic DDL),`guide_*` 前綴。

## File Structure

| 檔案 | 職責 |
|------|------|
| `db/005_voter_guide.sql` | `guide_*` 表 DDL(schema-agnostic、冪等) |
| `src/webapp/store.py`(修改) | `init_schema` 加掛 005;新增 `guide_*` 存取方法(讀樹、讀候選人欄位、標記、手動填值、commit/捨棄、建 job) |
| `src/voter_guide/pipeline.py`(修改) | 切圖/照片輸出改為人類可讀命名慣例,並輸出每人頁碼到 YAML |
| `src/voter_guide/guide_load.py`(新增) | load 指令:讀 parser 產物 → 寫 `guide_*` + 建 v1 snapshot |
| `src/voter_guide/guide_repair.py`(新增) | 文字欄 AI 修復執行器(讀 queued job → 重讀切圖 → 更新) |
| `src/voter_guide/guide_crop.py`(新增) | 依 PDF 頁 + bbox 座標裁切照片、覆蓋 photo_path |
| `src/webapp/routes/guide.py`(新增) | 公報瀏覽/後台 HTTP 路由 |
| `src/webapp/templates/guide/*.html`(新增) | 三欄版面、欄位面板、PDF 圈選頁 |
| `src/webapp/app.py`(修改) | 掛載 `guide.router` |
| `tests/unit/test_guide_*.py`、`tests/integration/test_guide_*.py`(新增) | 對應測試 |

## Phase 總覽(每個 Phase 產出可測試的軟體)

1. **Phase 1 — DB schema**:`guide_*` 表 + init_schema 掛載 + docs。
2. **Phase 2 — Parser 產物契約**:pipeline 命名慣例 + 頁碼輸出。
3. **Phase 3 — Load 指令**:匯入 + v1 snapshot + 缺圖/頁碼處理 + `--force`。
4. **Phase 4 — DB 存取層**:讀樹/欄位、標記、手動填值、commit/捨棄/版本推導。
5. **Phase 5 — Web 瀏覽/標記/版本**:三欄 UI + 版本切換。
6. **Phase 6 — 文字欄 AI 修復**:job + 背景執行 + toast 輪詢。
7. **Phase 7 — 照片手動圈選補正**:PDF 頁渲染 + 框選 + 裁切覆蓋。

---

## Phase 1 — DB Schema

### Task 1.1: 建立 `guide_*` 表 DDL

**Files:**
- Create: `db/005_voter_guide.sql`
- Test: `tests/integration/test_guide_schema.py`

- [ ] **Step 1: 寫 DDL**(schema-agnostic、冪等:全用 `IF NOT EXISTS`)

```sql
-- 005_voter_guide.sql — 選舉公報 web 資料(欄位化)。schema-agnostic、冪等。
CREATE TABLE IF NOT EXISTS guide_elections (
    id              TEXT PRIMARY KEY,
    type            VARCHAR(32)  NOT NULL,
    year            INTEGER      NOT NULL,
    session         INTEGER,
    label           TEXT,
    source_pdf_path TEXT,
    election_id     TEXT           -- 預留;本期不設 FK、不填
);

CREATE TABLE IF NOT EXISTS guide_candidates (
    id                SERIAL PRIMARY KEY,
    guide_election_id TEXT NOT NULL REFERENCES guide_elections(id) ON DELETE CASCADE,
    ticket            INTEGER,
    role              VARCHAR(16) NOT NULL DEFAULT '',
    party             VARCHAR(32),
    photo_path        TEXT,
    photo_flagged     BOOLEAN NOT NULL DEFAULT false,
    photo_note        TEXT,
    source_page       INTEGER,
    candidate_id      VARCHAR(64),   -- 預留;本期不設 FK、不填
    order_id          INTEGER,
    UNIQUE (guide_election_id, ticket, role)
);

CREATE TABLE IF NOT EXISTS guide_fields (
    id                 SERIAL PRIMARY KEY,
    guide_candidate_id INTEGER NOT NULL REFERENCES guide_candidates(id) ON DELETE CASCADE,
    field_name         VARCHAR(32) NOT NULL,
    value              TEXT,
    grade              VARCHAR(16),
    source_crop_path   TEXT,
    flagged            BOOLEAN NOT NULL DEFAULT false,
    flag_note          TEXT,
    update_source      VARCHAR(16) NOT NULL DEFAULT 'parse',
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (guide_candidate_id, field_name)
);

CREATE TABLE IF NOT EXISTS guide_snapshots (
    id                 SERIAL PRIMARY KEY,
    guide_candidate_id INTEGER NOT NULL REFERENCES guide_candidates(id) ON DELETE CASCADE,
    version_no         INTEGER NOT NULL,
    note               TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (guide_candidate_id, version_no)
);

CREATE TABLE IF NOT EXISTS guide_snapshot_fields (
    id               SERIAL PRIMARY KEY,
    snapshot_id      INTEGER NOT NULL REFERENCES guide_snapshots(id) ON DELETE CASCADE,
    field_name       VARCHAR(32) NOT NULL,
    value            TEXT,
    grade            VARCHAR(16),
    source_crop_path TEXT,
    flagged          BOOLEAN NOT NULL,
    flag_note        TEXT,
    UNIQUE (snapshot_id, field_name)
);

CREATE TABLE IF NOT EXISTS guide_repair_jobs (
    id                 SERIAL PRIMARY KEY,
    guide_candidate_id INTEGER NOT NULL REFERENCES guide_candidates(id) ON DELETE CASCADE,
    target             VARCHAR(32) NOT NULL,   -- 文字欄名;照片不建 job
    status             VARCHAR(16) NOT NULL DEFAULT 'queued',
    user_note          TEXT,
    before_value       TEXT,
    result_value       TEXT,
    error              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    finished_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_guide_candidates_election ON guide_candidates(guide_election_id);
CREATE INDEX IF NOT EXISTS idx_guide_fields_candidate    ON guide_fields(guide_candidate_id);
CREATE INDEX IF NOT EXISTS idx_guide_repair_jobs_status  ON guide_repair_jobs(status);
CREATE INDEX IF NOT EXISTS idx_guide_repair_jobs_cand    ON guide_repair_jobs(guide_candidate_id);
```

- [ ] **Step 2: 寫測試**(套用後所有 `guide_*` 表存在)

```python
# tests/integration/test_guide_schema.py
from __future__ import annotations
import pytest
from src.webapp.store import Store, load_database_config

GUIDE_TABLES = [
    "guide_elections", "guide_candidates", "guide_fields",
    "guide_snapshots", "guide_snapshot_fields", "guide_repair_jobs",
]

def _store():
    cfg = load_database_config()
    if not cfg.database_url:
        pytest.skip("PostgreSQL connection not configured")
    s = Store(cfg)
    try:
        s.open()
    except Exception:
        pytest.skip("PostgreSQL is not reachable")
    return s

def test_guide_tables_created():
    s = _store()
    try:
        s.init_schema()
        with s.connect() as conn:
            s._setup_conn(conn)
            rows = conn.execute(
                "select table_name from information_schema.tables "
                "where table_schema = %s", (s.config.schema,)
            ).fetchall()
        names = {r["table_name"] for r in rows}
        for t in GUIDE_TABLES:
            assert t in names
    finally:
        s.close()
```

- [ ] **Step 3: 掛載到 init_schema** — 修改 `src/webapp/store.py` 的 `init_schema`,把 `005_voter_guide.sql` 加入 `ddl_files`:

```python
        ddl_files = ("001_init.sql", "004_rename_birthday_to_birthyear.sql", "005_voter_guide.sql")
```

- [ ] **Step 4: 跑測試**
Run: `uv run pytest tests/integration/test_guide_schema.py -v`
Expected: PASS(無 DB 則 SKIP)

- [ ] **Step 5: 更新 schema 文件** — 於 `docs/db-schema.md` 追加 `guide_*` 六張表的欄位說明(照 §3 spec)。

- [ ] **Step 6: Commit**
```bash
git add db/005_voter_guide.sql src/webapp/store.py tests/integration/test_guide_schema.py docs/db-schema.md
git commit -m "feat(guide): 新增選舉公報 web guide_* 資料表"
```

---

## Phase 2 — Parser 產物契約(命名慣例 + 頁碼)

目標:讓 parser 輸出符合 spec §4 的人類可讀命名,並在 YAML 帶入每位候選人的來源頁碼(供 `source_page`)。

### Task 2.1: 切圖/照片路徑改為人類可讀命名

**Files:**
- Modify: `src/voter_guide/pipeline.py`
- Test: `tests/unit/test_guide_naming.py`

- [ ] **Step 1: 寫命名函式的失敗測試**

```python
# tests/unit/test_guide_naming.py
from src.voter_guide.pipeline import crop_filename

def test_crop_filename_president():
    # 民國113 → 西元2024;第16任;第1組;柯文哲;學歷
    got = crop_filename(type="president", session=16, minguo_year=113,
                        ticket=1, name="柯文哲", field="學歷")
    assert got == "president/16th_2024_ticket_1_柯文哲_學歷.png"
```

- [ ] **Step 2: 跑測試確認失敗**
Run: `uv run pytest tests/unit/test_guide_naming.py -v`
Expected: FAIL(`crop_filename` 未定義)

- [ ] **Step 3: 實作 `crop_filename`**(加到 `pipeline.py`)

```python
def crop_filename(*, type: str, session: int, minguo_year: int,
                  ticket: int, name: str, field: str) -> str:
    year_ad = minguo_year + 1911
    return f"{type}/{session}th_{year_ad}_ticket_{ticket}_{name}_{field}.png"
```

- [ ] **Step 4: 跑測試確認通過**
Run: `uv run pytest tests/unit/test_guide_naming.py -v`
Expected: PASS

- [ ] **Step 5: 接到實際輸出** — 修改 `parse_pdf` 的切圖/照片落地路徑:
  - `out_dir` 基底改用 `_out/parsed/`;切圖與照片依 `crop_filename` 命名(照片 field 用 `相片`)。
  - **參數來源(不要重用 `--tag`)**:`--tag` 可被覆寫成非數字字串,故 `session` 與 `minguo_year` 一律**獨立**由 PDF 檔名 regex `(\d+)年第(\d+)任` 取(年=群1、任次=群2),透過 `parse_pdf` 明確傳入,不從 tag 推。`type` 為 `president`(固定),`ticket` 由組別、`name` 為候選人姓名。
  - **`name` 先讀(避免雞生蛋)**:姓名本身也是一欄,其切圖檔名需要 `name`。在進 vision 迴圈前,先由幾何取 `person.cells["姓名"].text` 得 `name`,之後所有切圖(含姓名欄自己)才能一次命名妥當。
  - **113 基本資料合併格 token**:`出生年月日`/`性別` 無自己的切圖,來自合併「基本資料」格。此合併格切圖須以**固定 token** `基本資料` 命名(即 `crop_filename(..., field="基本資料")`),讓 load 能以同一 token 回推路徑。不要沿用目前那個很長的中文標籤當檔名。

- [ ] **Step 6: 跑既有 parser 測試確保未破壞**
Run: `uv run pytest tests/unit/test_parse_president.py tests/integration/test_president.py -v`
Expected: PASS

- [ ] **Step 7: Commit**
```bash
git add src/voter_guide/pipeline.py tests/unit/test_guide_naming.py
git commit -m "feat(guide): parser 切圖/照片改人類可讀命名"
```

### Task 2.2: YAML 輸出每人來源頁碼

**Files:**
- Modify: `src/voter_guide/pipeline.py`
- Test: `tests/unit/test_guide_naming.py`(追加)

- [ ] **Step 1: 失敗測試** — 對解析結果的每個 role entry,斷言含 `頁碼` 鍵(值為 `int`,來自 `geo.Person.page`)。用既有 president 測試 PDF 或 fixture。

- [ ] **Step 2: 跑測試確認失敗** — `uv run pytest tests/unit/test_guide_naming.py -v`

- [ ] **Step 3: 實作** — 在 `parse_pdf` 組 `rec` 時加 `rec["頁碼"] = person.page`。**註**:`person.page` 為 **0-based** 索引(來自 `enumerate(pdf.pages)`),與 `crop_cell`/`crop_photo` 的 `page_idx` 一致;`source_page` 直接存此 0-based 值,若 UI 要顯示給人看再 +1。

- [ ] **Step 4: 跑測試確認通過**

- [ ] **Step 5: Commit**
```bash
git commit -am "feat(guide): parser YAML 輸出候選人來源頁碼"
```

---

## Phase 3 — Load 指令

### Task 3.1: load 匯入 + v1 snapshot

**Files:**
- Create: `src/voter_guide/guide_load.py`
- Modify: `src/webapp/store.py`(新增 `guide_upsert_election` / `guide_insert_candidate` / `guide_insert_field` / `guide_create_snapshot` 等低階寫入方法)
- Test: `tests/integration/test_guide_load.py`

- [ ] **Step 1: 失敗測試** — 準備一個小的假 YAML(2 組、每組正副、各欄位)與對應假切圖檔;呼叫 `load_guide(store, yaml_path, ...)`;斷言:
  - `guide_elections` 1 筆、`guide_candidates` 4 筆(2 組 × 正副)。
  - `guide_fields`:每位候選人有 姓名/出生年月日/性別/學歷/經歷 五欄。
  - 存在切圖檔的欄位 `source_crop_path` 非 NULL;不存在者 NULL。
  - `source_page` 由 YAML `頁碼` 填入。
  - 每位候選人有 `version_no=1` 的 snapshot,且 `guide_snapshot_fields` 內容 == 當時 `guide_fields`。

- [ ] **Step 2: 跑測試確認失敗**
Run: `uv run pytest tests/integration/test_guide_load.py -v`

- [ ] **Step 3: 實作 `load_guide`**(要點)
  - 解析 YAML → 逐 entry(號次)逐 role 建 `guide_candidates`(role、party 複製組別政黨、photo_path、source_page)。
  - 逐欄建 `guide_fields`:`value` 取 YAML 值、`grade` 取 `_verify[role][field].grade`、`source_crop_path` 依 `crop_filename(..., field=欄名)` 組出並檢查檔案存在。缺圖 → NULL。**113 的 `出生年月日`/`性別`**:先試該欄自己的檔,不存在則回退 `crop_filename(..., field="基本資料")`(與 Task 2.1 Step 5 定義的固定 token 一致);仍不存在則 NULL。
  - `party` 依 spec:單一組別政黨複製到正副兩列;不建欄位、不記 grade。
  - 建立完該候選人所有欄位後,呼叫建立 v1 snapshot(把當前 `guide_fields` 凍結進 `guide_snapshot_fields`,`version_no=1`)。

- [ ] **Step 4: 跑測試確認通過**

- [ ] **Step 5: Commit**
```bash
git add src/voter_guide/guide_load.py src/webapp/store.py tests/integration/test_guide_load.py
git commit -m "feat(guide): load 匯入公報產物並建 v1 snapshot"
```

### Task 3.2: 重複載入保護(`--force`)

**Files:**
- Modify: `src/voter_guide/guide_load.py`
- Test: `tests/integration/test_guide_load.py`(追加)

- [ ] **Step 1: 失敗測試**
  - 對同一 `guide_elections.id` 二次 `load_guide` 且未帶 force → 應 raise(或回傳明確拒絕),且既有資料不變。
  - 帶 `force=True` → 刪除該場所有 `guide_*` 後重建,回到 v1。

- [ ] **Step 2: 跑測試確認失敗**

- [ ] **Step 3: 實作** — load 前檢查 `guide_elections.id` 是否存在:存在且非 force → raise `GuideElectionExists`;force → 先 `DELETE FROM guide_elections WHERE id=%s`(CASCADE 清乾淨)再重建。

- [ ] **Step 4: 跑測試確認通過**

- [ ] **Step 5: 提供 CLI 入口** — `guide_load.py` 加 `main()`(argparse:yaml 路徑、`--force`),`uv run python -m src.voter_guide.guide_load ...`。

- [ ] **Step 6: Commit**
```bash
git commit -am "feat(guide): load 重複載入保護與 --force 重灌"
```

---

## Phase 4 — DB 存取層(讀 + 標記 + 手動 + 版本)

新增於 `src/webapp/store.py` 的 `guide_*` 高階方法。每個方法一個 Task,TDD。

### Task 4.1: 讀取導覽樹與候選人清單

- [ ] **Step 1: 失敗測試** — `guide_tree()` 回傳 `[{type, elections:[{id,label,year,session}]}]`;`guide_candidates_of(election_id)` 回傳組別/正副清單(含是否有任一 flagged 供橙點)。
- [ ] **Step 2/4: 跑測試(失敗→通過)** — `uv run pytest tests/unit/test_guide_store.py -v`
- [ ] **Step 3: 實作** — SELECT + 聚合。
- [ ] **Step 5: Commit** `feat(guide): store 讀導覽樹與候選人清單`

### Task 4.2: 讀單一候選人「最新工作版」欄位

- [ ] **Step 1: 失敗測試** — `guide_candidate_view(candidate_id)` 回傳:候選人 meta(號次/角色/政黨/性別/photo_path/photo_flagged/source_page)、各欄位列(field_name/value/grade/source_crop_path/flagged/flag_note、以及「是否可 AI 修復」= crop 非 NULL)、以及「有無未提交變更」旗標與目前最新 `version_no`。
- [ ] **Step 3: 實作**「有無未提交變更」= 比對 `guide_fields` 與最後 snapshot 的 `guide_snapshot_fields`(值/flag/note 任一不同),或照片被更換/標記。
- [ ] **Step 5: Commit** `feat(guide): store 讀候選人工作版欄位`

### Task 4.3: 標記 / 解除標記(文字欄 + 照片)

- [ ] **Step 1: 失敗測試** — `guide_flag_field(field_id, note)` 設 `flagged=true,flag_note=note`;`guide_unflag_field(field_id)` 清除。照片對應 `guide_flag_photo(candidate_id, note)` / `guide_unflag_photo`。
- [ ] **Step 3: 實作** UPDATE。
- [ ] **Step 5: Commit** `feat(guide): store 欄位/照片標記與解除`

### Task 4.4: 手動填正確值(文字欄)

- [ ] **Step 1: 失敗測試** — `guide_set_field_value(field_id, value)` → `value` 更新、`update_source='manual'`、`grade=NULL`、`updated_at` 更新;標記不自動解除。
- [ ] **Step 3: 實作** UPDATE。
- [ ] **Step 5: Commit** `feat(guide): store 手動填欄位值`

### Task 4.5: Commit 快照 / 捨棄變更

- [ ] **Step 1: 失敗測試**
  - `guide_commit(candidate_id, note)` → 新 `guide_snapshots`(version_no = 前一版+1)+ 凍結當前 `guide_fields`;commit 後「有無未提交變更」為 false。
  - `guide_discard(candidate_id)` → 以最後 snapshot 的 `guide_snapshot_fields` 覆蓋回 `guide_fields`(照片不還原)。
- [ ] **Step 3: 實作**(single transaction)。
- [ ] **Step 5: Commit** `feat(guide): store commit 快照與捨棄變更`

### Task 4.6: 讀指定版本快照(供 ◀▶)

- [ ] **Step 1: 失敗測試** — `guide_snapshot_view(candidate_id, version_no)` 回傳該版凍結欄位;`version_no` 邊界(第一版無上一版、最新版無下一版)由回傳的 min/max 判定。
- [ ] **Step 3: 實作** SELECT。
- [ ] **Step 5: Commit** `feat(guide): store 讀指定版本快照`

---

## Phase 5 — Web 瀏覽 / 標記 / 版本

### Task 5.1: router 骨架 + 三欄頁

**Files:**
- Create: `src/webapp/routes/guide.py`, `src/webapp/templates/guide/index.html`
- Modify: `src/webapp/app.py`(`app.include_router(guide.router)`)
- Test: `tests/unit/test_guide_routes.py`

- [ ] **Step 1: 失敗測試** — `GET /guide` 200,含左欄類型>年度樹;`GET /guide/election/{id}` 回中欄候選人清單。用 FastAPI `TestClient`(參考 `tests/unit/test_routes.py`)。
- [ ] **Step 3: 實作** router + 模板(左欄樹、中欄清單);沿用 `request.app.state.templates`。
- [ ] **Step 4: 跑測試** `uv run pytest tests/unit/test_guide_routes.py -v`
- [ ] **Step 5: Commit** `feat(guide): web 三欄瀏覽骨架`

### Task 5.2: 欄位面板頁(最新工作版)

- [ ] **Step 1: 失敗測試** — `GET /guide/candidate/{id}` 200,含各欄位列、性別小人圖示(男藍/女粉/其他不顯示)、切圖縮圖、標記鈕;文字欄 crop 為 NULL 時不出現「AI 修復」鈕;有未提交變更時出現黃色橫幅 + Commit/捨棄。
- [ ] **Step 3: 實作** 模板 `templates/guide/candidate.html`,對接 `guide_candidate_view`。版面依定稿 mockup(見 spec §6)。
- [ ] **Step 5: Commit** `feat(guide): web 候選人欄位面板`

### Task 5.3: 標記 / 手動填值 / 解除 的 POST 動作

- [ ] **Step 1: 失敗測試** — POST 標記(帶補充說明)、POST 手動填值、POST 解除標記,各自更新後 redirect 回候選人頁,狀態正確。
- [ ] **Step 3: 實作** 對接 4.3/4.4 store 方法。
- [ ] **Step 5: Commit** `feat(guide): web 標記與手動修正動作`

### Task 5.4: Commit / 捨棄 / 版本 ◀▶

- [ ] **Step 1: 失敗測試** — POST commit 後版本 +1、橫幅消失;POST 捨棄還原;`GET /guide/candidate/{id}?version=N` 顯示該版凍結欄位且為唯讀(無標記/修復鈕)。
- [ ] **Step 3: 實作** 對接 4.5/4.6;版本列 ◀▶ 連結,邊界版停用箭頭。
- [ ] **Step 5: Commit** `feat(guide): web commit/捨棄與版本切換`

---

## Phase 6 — 文字欄 AI 修復(背景 + toast)

### Task 6.1: 建 job + 背景執行器

**Files:**
- Create: `src/voter_guide/guide_repair.py`
- Modify: `src/voter_guide/vision.py`(新增 `transcribe_image` — 讀 PNG base64 餵模型)
- Modify: `src/webapp/store.py`(`guide_create_repair_job` / `guide_take_queued_job` / `guide_finish_job`)
- Test: `tests/integration/test_guide_repair.py`、`tests/unit/test_vision_transcribe_image.py`

- [ ] **Step 1: 失敗測試** — 對某文字欄建 job(status=queued、帶 user_note);跑 `run_repair_job(store, job_id, transcribe_image=fake)`(以假 helper 回固定字串)→ `guide_fields.value` 更新、`update_source='ai'`、job status=done、`result_value` 記錄、標記不自動解除。
- [ ] **Step 3: 實作**
  - **注意(避免走錯路)**:既有 `vision.transcribe(pdf_path, page_idx, bbox, field_name, ...)`(`src/voter_guide/vision.py`)是從 **PDF 幾何重新算圖**,**不吃**存好的切圖 PNG。而 `guide_fields` 存的是 `source_crop_path`(PNG 路徑),不含 bbox/pdf。因此本路徑**需新增一個讀 PNG 檔的視覺 helper**,而非重用 `transcribe`。
  - 先在 `src/voter_guide/vision.py` 新增 `transcribe_image(png_path, field_name, note=None)`:讀該 PNG → base64 → 帶〔圖 + 欄名 + 補充說明 note〕呼叫 local 視覺模型 → 回傳讀出的字串。(先寫此函式的獨立單元測試,可用 monkeypatch 假 model client。)
  - `run_repair_job`:讀 job → 讀該欄 `source_crop_path`(NULL 直接 fail 並記 error)→ 呼叫 `transcribe_image(crop_path, field_name, user_note)` → 更新欄位值(`update_source='ai'`)+ job 完成。
  - `transcribe_image` 以參數注入 `run_repair_job`,測試用 fake 回固定字串;生產用真函式。
  - 缺圖(`source_crop_path` NULL)因此正確地無法 AI 修復,與 UI 停用按鈕一致。
- [ ] **Step 5: Commit** `feat(guide): 文字欄 AI 修復執行器`

### Task 6.2: web 觸發 + 背景排程 + 狀態輪詢

**Files:**
- Modify: `src/webapp/routes/guide.py`
- Test: `tests/unit/test_guide_routes.py`(追加)

- [ ] **Step 1: 失敗測試** — POST `/guide/field/{id}/repair`(帶 user_note)建立 job 並回 202/redirect;`GET /guide/repair/{job_id}/status` 回 job status JSON(供前端輪詢)。
- [ ] **Step 3: 實作** — 用 FastAPI `BackgroundTasks` 排 `run_repair_job`(單人本機足夠);前端輪詢 status,done 時右上角 toast(前端小 script,置於 `candidate.html`)。
- [ ] **Step 5: Commit** `feat(guide): web 觸發 AI 修復與狀態輪詢`

---

## Phase 7 — 照片手動圈選補正

### Task 7.1: 依 PDF 頁 + bbox 裁切覆蓋照片

**Files:**
- Create: `src/voter_guide/guide_crop.py`
- Test: `tests/integration/test_guide_crop.py`

- [ ] **Step 1: 失敗測試** — `crop_photo(pdf_path, page, bbox, dest)` 產出圖檔於 dest(沿用 `src/voter_guide/vision.py` 的 `crop_cell`,**非** geometry.py);回傳存檔路徑。`page` 為 0-based。
- [ ] **Step 3: 實作** — 薄封裝 `from src.voter_guide.vision import crop_cell`;`crop_cell(pdf_path, page, bbox, scale=...)` → 存檔。
- [ ] **Step 5: Commit** `feat(guide): 依 PDF bbox 裁切照片`

### Task 7.2: web 圈選頁 + 送座標補照片

**Files:**
- Modify: `src/webapp/routes/guide.py`
- Create: `src/webapp/templates/guide/crop.html`
- Test: `tests/unit/test_guide_routes.py`(追加)

- [ ] **Step 1: 失敗測試**
  - `GET /guide/candidate/{id}/crop`:`source_page` 為 NULL → 回提示/停用(防呆);非 NULL → 200 顯示該 PDF 頁渲染 + 畫框介面。
  - POST `/guide/candidate/{id}/crop`(帶 bbox 座標)→ 呼叫 `crop_photo` 覆蓋 `photo_path`,redirect 回候選人頁;列為未提交變更。
- [ ] **Step 3: 實作**
  - 頁面把 PDF 該頁渲染成圖(以 pdfplumber/pdf → PNG,或前端 pdf.js;實作細節見 spec §8),前端畫矩形取螢幕座標。
  - 送出前把螢幕座標依渲染縮放換算回 PDF pt 座標,後端據此 `crop_photo`。
- [ ] **Step 5: Commit** `feat(guide): web 手動圈選補照片`

---

## 完成準則

- 全部 Task 的測試通過(`uv run pytest`),無 DB 時相關測試 SKIP。
- 可 `uv run python -m src.voter_guide.guide_load <yaml> [--force]` 匯入 113 總統公報。
- 啟動 web(掛載 guide router)後,可依 §6 版面瀏覽、標記、AI 修復文字欄、手動圈選補照片、commit 版本並前後切換。
- `docs/db-schema.md` 已含 `guide_*` 表。
