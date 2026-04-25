# 選舉身分辨識 UI 實作計畫

> **給 agent worker：** 必須使用 superpowers:subagent-driven-development（建議）或 superpowers:executing-plans，逐項完成這份計畫。步驟使用 checkbox（`- [ ]`）語法追蹤。

**Goal:** 建立一個本機 web app，用來列出各場選舉、自動處理明顯屬於同一人的配對、顯示需要人工判斷的同名衝突、記錄 mapping 決策，並重新產生 `candidates.yaml`。

**Architecture:** 保留現有 parser 與正規化邏輯，作為原始選舉資料的唯一真實來源。新增一個小型 Python web server 與以 PostgreSQL 為後端的儲存層，持久化選舉掃描結果與 mapping 決策，最後再從這些已持久化的決策產生 `candidates.yaml`。

**Tech Stack:** Python 3.14、PostgreSQL、`psycopg`、`http.server`、原生 HTML/CSS/JS、`pyyaml`、`pytest`、既有 `src/` parser 模組

---

## 檔案結構

- 建立：`src/webapp/__init__.py`
- 建立：`src/webapp/server.py`
  - 本機 HTTP server 入口、靜態檔案提供、JSON API 路由。
- 建立：`src/webapp/discovery.py`
  - 掃描 `_data/` 與根目錄下的 `*th.yaml`，轉成正規化後的 `election` 列。
- 建立：`src/webapp/store.py`
  - PostgreSQL 連線載入、schema/table 建立，以及 elections、source records、resolutions、logs 的 CRUD helper。
- 建立：`src/webapp/matching.py`
  - V1 身分比對規則：自動配對、人工比對候選人查找、建立新 id。
- 建立：`src/webapp/build_candidates.py`
  - 根據已持久化的 records 與 resolutions 重建 `candidates.yaml`。
- 建立：`src/webapp/static/index.html`
  - 單頁殼層，包含導覽區與比對工作區。
- 建立：`src/webapp/static/app.js`
  - 取得 elections、載入待審項目、送出決策、觸發重建。
- 建立：`src/webapp/static/styles.css`
  - 精簡的樹狀導覽與簡單的比對版面。
- 建立：`tests/unit/test_discovery.py`
- 建立：`tests/unit/test_store.py`
- 建立：`tests/unit/test_matching.py`
- 建立：`tests/integration/test_webapp_build_candidates.py`
- 修改：`main.py`
  - 新增 `serve-ui` 指令，或維持 CLI 不變並新增獨立 runner 模組。
- 修改：`pyproject.toml`
  - 加入 PostgreSQL driver 相依套件。
- 修改：`README.md`
  - 說明如何啟動 UI，以及 `.env` 需要哪些 PostgreSQL 設定。

## 實作備註

- 重用既有 `src.parse_president`、`src.parse_mayor`、`src.parse_legislator` parser。
- 每個來源檔案視為一個 `election`。
- 使用 `source_record_id = "{election_id}:{row_index}"`。
- 在每筆 resolution row 持久化 `mode = auto|manual|new|skip`。
- V1 比對規則：
  - 正規化後姓名相同 + 生日相同 + 只對應到一位既有候選人 => `auto`
  - 正規化後姓名相同 + 生日不同 => `manual`
  - 正規化後姓名相同 + 缺少生日 => `manual`
  - 沒有同名候選人 => 建立新 id
- 最終輸出維持為 `candidates.yaml`。
- app 狀態存放於 PostgreSQL，透過 `.env` 或環境變數提供 `DATABASE_URL` 與 `POSTGRES_SCHEMA`。
- PostgreSQL database 與 schema namespace 由 app 外部建立。`Store.init_schema()` 只負責在 `POSTGRES_SCHEMA` 內建立或確認 app 所需資料表。

### 任務 1：新增選舉探索

**檔案：**
- 建立：`src/webapp/discovery.py`
- 測試：`tests/unit/test_discovery.py`

- [ ] **Step 1: 先寫失敗測試**

```python
from pathlib import Path

from src.webapp.discovery import discover_elections


def test_discover_elections_groups_known_sources(tmp_path: Path) -> None:
    data_dir = tmp_path / "_data"
    (data_dir / "president").mkdir(parents=True)
    (data_dir / "president" / "第16任總統副總統選舉.xlsx").write_text("")
    (tmp_path / "11th.yaml").write_text("[]", encoding="utf-8")

    elections = discover_elections(tmp_path)

    assert [e["type"] for e in elections] == ["party-list", "president"]
    assert elections[0]["election_id"] == "party-list/11th.yaml"
    assert elections[1]["election_id"] == "president/第16任總統副總統選舉.xlsx"
```

- [ ] **Step 2: 執行測試，確認會失敗**

執行：`uv run pytest tests/unit/test_discovery.py -v`
預期：因 `ModuleNotFoundError` 或缺少 `discover_elections` 而失敗

- [ ] **Step 3: 實作最小版本**

```python
from pathlib import Path


def discover_elections(root: Path) -> list[dict]:
    elections = []
    for path in sorted((root / "_data" / "president").glob("*.xlsx")):
        elections.append({
            "election_id": f"president/{path.name}",
            "type": "president",
            "label": path.stem,
            "path": path,
        })
    for path in sorted(root.glob("*th.yaml")):
        elections.append({
            "election_id": f"party-list/{path.name}",
            "type": "party-list",
            "label": path.stem,
            "path": path,
        })
    return sorted(elections, key=lambda e: e["election_id"])
```

- [ ] **Step 4: 再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_discovery.py -v`
預期：PASS

- [ ] **Step 5: 擴充探索邏輯到目前所有來源型別**

加入對 `mayor`、`legislator`、未來 `_data/<type>` 資料夾的支援，並萃取最基本的顯示 metadata（`year`、`session`、預設 `status='todo'`）。

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_discovery.py src/webapp/discovery.py
git commit -m "feat: add election discovery for web ui"
```

### 任務 2：新增 PostgreSQL 儲存層

**檔案：**
- 建立：`src/webapp/store.py`
- 修改：`pyproject.toml`
- 測試：`tests/unit/test_store.py`

- [ ] **Step 1: 先寫失敗測試**

```python
import pytest

from src.webapp.store import Store, load_database_config


def test_store_saves_resolution_decision() -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("DATABASE_URL is not configured")

    store = Store(config)
    store.init_schema()
    store.save_resolution(
        election_id="president/第16任總統副總統選舉.xlsx",
        source_record_id="president/第16任總統副總統選舉.xlsx:3",
        candidate_id="id_柯文哲_1959",
        mode="manual",
    )

    row = store.get_resolution("president/第16任總統副總統選舉.xlsx:3")
    assert row["candidate_id"] == "id_柯文哲_1959"
    assert row["mode"] == "manual"
```

- [ ] **Step 2: 執行測試，確認會失敗**

執行：`uv run pytest tests/unit/test_store.py -v`
預期：因缺少 `Store` 或 PostgreSQL driver 而失敗

- [ ] **Step 3: 實作最小版本**

```python
from dataclasses import dataclass
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class DatabaseConfig:
    database_url: str
    schema: str


def load_database_config(env_path: Path = Path(".env")) -> DatabaseConfig:
    values = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    database_url = os.environ.get("DATABASE_URL") or values.get("DATABASE_URL", "")
    schema = os.environ.get("POSTGRES_SCHEMA") or values.get("POSTGRES_SCHEMA", "public")
    return DatabaseConfig(database_url=database_url, schema=schema)


class Store:
    def __init__(self, config: DatabaseConfig | None = None):
        self.config = config or load_database_config()

    def connect(self):
        return psycopg.connect(
            self.config.database_url,
            row_factory=dict_row,
            options=f"-c search_path={self.config.schema}",
        )

    def init_schema(self):
        with self.connect() as conn:
            conn.execute(
                """
                create table if not exists resolutions (
                    source_record_id text primary key,
                    election_id text not null,
                    candidate_id text,
                    mode text not null,
                    decided_at text default current_timestamp
                );
                """
            )

    def save_resolution(self, **row):
        with self.connect() as conn:
            conn.execute(
                """
                insert into resolutions(source_record_id, election_id, candidate_id, mode)
                values (:source_record_id, :election_id, :candidate_id, :mode)
                on conflict(source_record_id) do update set
                    candidate_id=excluded.candidate_id,
                    mode=excluded.mode,
                    decided_at=current_timestamp
                """,
                row,
            )

    def get_resolution(self, source_record_id):
        with self.connect() as conn:
            return conn.execute(
                "select * from resolutions where source_record_id = %s",
                (source_record_id,),
            ).fetchone()
```

- [ ] **Step 4: 再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_store.py -v`
預期：PASS

- [ ] **Step 5: 擴充 schema**

加入以下資料表：
- `elections`
- `source_records`
- `resolutions`
- `operation_logs`

並提供以下 helper：
- discovered elections 的 upsert
- 已解析 source records 的儲存
- 列出單一 election 尚未解決的 records
- 追加 operation log rows

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tests/unit/test_store.py src/webapp/store.py
git commit -m "feat: add postgres store for election ui"
```

### 任務 3：新增比對規則

**檔案：**
- 建立：`src/webapp/matching.py`
- 測試：`tests/unit/test_matching.py`

- [ ] **Step 1: 先寫失敗測試**

```python
from src.webapp.matching import classify_record


def test_classify_record_auto_matches_same_name_same_birthday() -> None:
    record = {"name": "柯文哲", "birthday": 1959}
    existing = [{"name": "柯文哲", "birthday": 1959, "id": "id_柯文哲_1959"}]

    result = classify_record(record, existing)

    assert result["kind"] == "auto"
    assert result["candidate_id"] == "id_柯文哲_1959"
```

- [ ] **Step 2: 執行測試，確認會失敗**

執行：`uv run pytest tests/unit/test_matching.py -v`
預期：因缺少 `classify_record` 而失敗

- [ ] **Step 3: 實作最小版本**

```python
from src.normalize import normalize_name, generate_id


def classify_record(record: dict, existing: list[dict]) -> dict:
    matches = [c for c in existing if normalize_name(c["name"]) == normalize_name(record["name"])]
    if not matches:
        return {"kind": "new", "candidate_id": generate_id(record["name"], record["birthday"])}

    same_birthday = [c for c in matches if c.get("birthday") == record.get("birthday")]
    if record.get("birthday") is not None and len(same_birthday) == 1:
        return {"kind": "auto", "candidate_id": same_birthday[0]["id"]}

    return {"kind": "manual", "matches": matches}
```

- [ ] **Step 4: 再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_matching.py -v`
預期：PASS

- [ ] **Step 5: 補齊其餘規則覆蓋**

新增測試與實作，涵蓋：
- 同名 + 不同生日 => `manual`
- 同名 + 缺少生日 => `manual`
- 同名 + 同生日 + 多個符合 => `manual`
- 沒有同名符合 => `new`

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_matching.py src/webapp/matching.py
git commit -m "feat: add v1 identity matching rules"
```

### 任務 4：匯入來源紀錄到 Store

**檔案：**
- 修改：`src/webapp/discovery.py`
- 修改：`src/webapp/store.py`
- 修改：`src/webapp/matching.py`
- 測試：`tests/unit/test_discovery.py`
- 測試：`tests/unit/test_store.py`

- [ ] **Step 1: 先寫失敗測試**

```python
from pathlib import Path

from src.webapp.discovery import load_election_records


def test_load_election_records_assigns_stable_source_record_ids(tmp_path: Path) -> None:
    election = {
        "election_id": "party-list/11th.yaml",
        "type": "party-list",
        "path": tmp_path / "11th.yaml",
        "session": 11,
    }
    election["path"].write_text("- name: 測試\n  party: 測試黨\n  birthday: 1970\n", encoding="utf-8")

    rows = load_election_records(election)

    assert rows[0]["source_record_id"] == "party-list/11th.yaml:0"
```

- [ ] **Step 2: 執行測試，確認會失敗**

執行：`uv run pytest tests/unit/test_discovery.py tests/unit/test_store.py -v`
預期：因缺少 `load_election_records` 而失敗

- [ ] **Step 3: 實作最小版本**

```python
def load_election_records(election: dict) -> list[dict]:
    parser = _resolve_parser(election)
    records = parser(election["path"])
    rows = []
    for i, record in enumerate(records):
        rows.append({
            **record,
            "election_id": election["election_id"],
            "source_record_id": f'{election["election_id"]}:{i}',
        })
    return rows
```

- [ ] **Step 4: 再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_discovery.py tests/unit/test_store.py -v`
預期：PASS

- [ ] **Step 5: 持久化匯入 rows 與自動決策**

針對單一 election：
- parse records
- 將 records 存入 `source_records`
- 從目前的 `candidates.yaml` 載入既有 candidates
- 對每一列執行 classify
- 立即寫入 `auto` 與 `new` resolution
- `manual` 列先保留為未解決，交由 UI 審查

- [ ] **Step 6: Commit**

```bash
git add src/webapp/discovery.py src/webapp/store.py src/webapp/matching.py tests/unit/test_discovery.py tests/unit/test_store.py
git commit -m "feat: persist imported source records"
```

### 任務 5：從 Resolutions 建立 `candidates.yaml`

**檔案：**
- 建立：`src/webapp/build_candidates.py`
- 測試：`tests/integration/test_webapp_build_candidates.py`

- [ ] **Step 1: 先寫失敗的整合測試**

```python
from src.webapp.build_candidates import build_candidates_yaml
from src.webapp.store import Store, load_database_config


def test_build_candidates_yaml_groups_records_by_candidate_id() -> None:
    store = Store(load_database_config())
    store.init_schema()
    store.insert_source_record(
        source_record_id="president/a.xlsx:0",
        election_id="president/a.xlsx",
        payload={"name": "柯文哲", "birthday": 1959, "year": 2024, "type": "國家元首", "region": "全國", "party": "台灣民眾黨", "elected": 0},
    )
    store.save_resolution(
        source_record_id="president/a.xlsx:0",
        election_id="president/a.xlsx",
        candidate_id="id_柯文哲_1959",
        mode="auto",
    )

    rows = build_candidates_yaml(store)

    assert rows[0]["id"] == "id_柯文哲_1959"
    assert rows[0]["elections"][0]["year"] == 2024
```

- [ ] **Step 2: 執行測試，確認會失敗**

執行：`uv run pytest tests/integration/test_webapp_build_candidates.py -v`
預期：因缺少 `build_candidates_yaml` 而失敗

- [ ] **Step 3: 實作最小版本**

```python
def build_candidates_yaml(store):
    grouped = {}
    for row in store.iter_resolved_records():
        candidate = grouped.setdefault(row["candidate_id"], {
            "name": row["name"],
            "id": row["candidate_id"],
            "birthday": row["birthday"],
            "elections": [],
        })
        candidate["elections"].append({
            "year": row["year"],
            "type": row["type"],
            "region": row["region"],
            "party": row["party"],
            "elected": row["elected"],
        })
    return sorted(grouped.values(), key=lambda c: min(e["year"] for e in c["elections"]))
```

- [ ] **Step 4: 再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_webapp_build_candidates.py -v`
預期：PASS

- [ ] **Step 5: 補上檔案輸出與驗證**

撰寫 `write_candidates_yaml(store, output_path)`，負責：
- 建立 grouped candidates
- 用 `validate_candidates` 驗證
- 寫出 `candidates.yaml`

- [ ] **Step 6: Commit**

```bash
git add src/webapp/build_candidates.py tests/integration/test_webapp_build_candidates.py
git commit -m "feat: rebuild candidates yaml from resolutions"
```

### 任務 6：新增本機 Web Server API

**檔案：**
- 建立：`src/webapp/server.py`
- 測試：`tests/unit/test_store.py`

- [ ] **Step 1: 先寫失敗測試**

```python
from src.webapp.server import build_api


def test_build_api_lists_elections(tmp_path):
    app = build_api(tmp_path)
    data = app.handle_json("GET", "/api/elections")
    assert data[0]["election_id"]
```

- [ ] **Step 2: 執行測試，確認會失敗**

執行：`uv run pytest tests/unit/test_store.py -v`
預期：因缺少 `build_api` 而失敗

- [ ] **Step 3: 實作最小版本**

```python
def build_api(root):
    class API:
        def handle_json(self, method, path, body=None):
            if method == "GET" and path == "/api/elections":
                return store.list_elections()
            raise KeyError(path)
    return API()
```

- [ ] **Step 4: 再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_store.py -v`
預期：PASS

- [ ] **Step 5: 擴充為正式 HTTP endpoints**

實作：
- `GET /api/elections`
- `POST /api/elections/<id>/load`
- `GET /api/elections/<id>/review-items`
- `POST /api/resolutions`
- `POST /api/build`

並提供 `src/webapp/static/` 作為前端殼層的靜態資源。

- [ ] **Step 6: Commit**

```bash
git add src/webapp/server.py tests/unit/test_store.py
git commit -m "feat: add local api server for web ui"
```

### 任務 7：新增最小可用前端

**檔案：**
- 建立：`src/webapp/static/index.html`
- 建立：`src/webapp/static/app.js`
- 建立：`src/webapp/static/styles.css`
- 修改：`README.md`

- [ ] **Step 1: 建立 HTML 殼層**

建立：
- 左側精簡樹狀導覽
- 右側比對面板
- `Use Selected Match`、`Create New Person`、`Skip` 三個按鈕

- [ ] **Step 2: 補上會失敗的 smoke check**

記錄一個手動 smoke check：

執行：`uv run python -m src.webapp.server`
預期：
- browser 開啟 `http://127.0.0.1:8000`
- 左側列出 elections
- 選擇某個 election 後，右側載入一筆待審項目

- [ ] **Step 3: 實作最小前端**

```js
async function loadElections() {
  const res = await fetch('/api/elections');
  const elections = await res.json();
  renderNavigator(elections);
}

async function saveResolution(payload) {
  await fetch('/api/resolutions', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}
```

- [ ] **Step 4: 驗證手動流程**

檢查：
- 選擇某個 election 後，會載入待處理的 `manual` 項目
- 選擇某個 match 後，會送出 resolution
- `Create New Person` 會產生並儲存新的 id
- `Build` 會重寫 `candidates.yaml`

- [ ] **Step 5: 在 README 補上啟動方式**

新增：
- `uv run python -m src.webapp.server`
- 必要的 `.env` PostgreSQL 設定
- 如何重建 `candidates.yaml`

- [ ] **Step 6: Commit**

```bash
git add src/webapp/static/index.html src/webapp/static/app.js src/webapp/static/styles.css README.md
git commit -m "feat: add election identity web ui"
```

### 任務 8：端對端驗證

**檔案：**
- 修改：`tests/integration/test_webapp_build_candidates.py`
- 修改：`README.md`

- [ ] **Step 1: 補上端對端整合測試覆蓋**

涵蓋以下流程：
- 探索出一場 election
- 匯入 source records
- 自動解決一筆同名同生日資料
- 手動解決一筆同名不同生日資料
- 重建 `candidates.yaml`
- 驗證預期的 ids 與 elections 都存在

- [ ] **Step 2: 執行聚焦測試**

執行：`uv run pytest tests/unit/test_discovery.py tests/unit/test_store.py tests/unit/test_matching.py tests/integration/test_webapp_build_candidates.py -v`
預期：PASS

- [ ] **Step 3: 執行完整測試集**

執行：`make test`
預期：既有與新增測試全部 PASS

- [ ] **Step 4: 最後 commit**

```bash
git add tests README.md
git commit -m "test: cover election identity ui flow"
```
