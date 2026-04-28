# Identity UI — FastAPI 重構 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 identity-ui 從 `http.server` 重構為 FastAPI + Jinja2，以 DB 作為候選人資料 single source of truth，導入 session-based commit 流程。

**Architecture:** Store 層負責所有 DB 操作；Routes 層透過 FastAPI router 處理 HTTP 請求，session 保存 review 期間的待決策 (pending decisions)；Jinja2 templates 做 SSR full-page render，無 JS 依賴。

**Tech Stack:** FastAPI, Jinja2, Starlette SessionMiddleware, psycopg3, uvicorn, python-multipart, itsdangerous

---

## File Map

```
Created:
  db/001_init.sql
  src/webapp/app.py
  src/webapp/logging_setup.py
  src/webapp/routes/__init__.py
  src/webapp/routes/elections.py
  src/webapp/routes/review.py
  src/webapp/routes/build.py
  src/webapp/templates/base.html
  src/webapp/templates/elections.html
  src/webapp/templates/review.html

Modified:
  pyproject.toml                               ← add fastapi, jinja2, uvicorn, python-multipart, itsdangerous
  .gitignore                                   ← add logs/
  src/webapp/store.py                          ← schema + new/removed methods
  src/webapp/matching.py                       ← classify_record(record, store)
  src/webapp/build_candidates.py               ← read from candidates + candidate_elections
  src/webapp/static/styles.css                 ← update for new template structure
  tests/unit/test_store.py                     ← update for new schema
  tests/integration/test_webapp_build_candidates.py  ← update for new commit flow

Deleted:
  src/webapp/server.py
  tests/unit/test_server.py   ← replaced by tests/unit/test_routes.py
```

---

## Task 1: Dependencies + DB Migration Script

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Create: `db/001_init.sql`

- [ ] **Step 1: Add dependencies**

```bash
uv add fastapi jinja2 uvicorn python-multipart itsdangerous
```

Expected: pyproject.toml dependencies 新增上述五個套件。

- [ ] **Step 2: Update .gitignore**

在 `.gitignore` 末端加入：

```
logs/
```

- [ ] **Step 3: Create db/001_init.sql**

```sql
-- 選舉檔案清單
CREATE TABLE IF NOT EXISTS elections (
    election_id TEXT        PRIMARY KEY,
    type        VARCHAR(32) NOT NULL,
    label       TEXT        NOT NULL,
    path        TEXT        NOT NULL,
    year        INTEGER,
    session     INTEGER
);

-- 從 source data 匯入的原始資料 (raw decision log)
CREATE TABLE IF NOT EXISTS source_records (
    source_record_id TEXT        PRIMARY KEY,
    election_id      TEXT        NOT NULL REFERENCES elections(election_id) ON DELETE CASCADE,
    name             VARCHAR(64) NOT NULL,
    birthday         INTEGER,
    payload          JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_records_election_id
    ON source_records (election_id);

-- 身分判定結果 (raw decision log)
CREATE TABLE IF NOT EXISTS resolutions (
    source_record_id TEXT        PRIMARY KEY REFERENCES source_records(source_record_id) ON DELETE CASCADE,
    election_id      TEXT        NOT NULL    REFERENCES elections(election_id) ON DELETE CASCADE,
    candidate_id     VARCHAR(64),
    mode             VARCHAR(16) NOT NULL
);
-- mode: auto / new / manual

-- 候選人身分 (業務資料)
CREATE TABLE IF NOT EXISTS candidates (
    id       VARCHAR(64) PRIMARY KEY,
    name     VARCHAR(64) NOT NULL,
    birthday INTEGER
);

CREATE INDEX IF NOT EXISTS idx_candidates_name ON candidates (name);

-- 候選人參選紀錄 (業務資料)
CREATE TABLE IF NOT EXISTS candidate_elections (
    id           SERIAL      PRIMARY KEY,
    candidate_id VARCHAR(64) NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    year         INTEGER     NOT NULL,
    type         VARCHAR(32) NOT NULL,
    region       VARCHAR(32) NOT NULL,
    party        VARCHAR(32),
    elected      INTEGER,
    session      INTEGER,
    ticket       INTEGER,
    order_id     INTEGER,
    UNIQUE (candidate_id, year, type, region)
);

CREATE INDEX IF NOT EXISTS idx_candidate_elections_candidate_id
    ON candidate_elections (candidate_id);
```

- [ ] **Step 4: Commit**

```bash
git add db/001_init.sql pyproject.toml uv.lock .gitignore
git commit -m "chore: add fastapi deps and db migration script"
```

---

## Task 2: Store 重構

**Files:**
- Modify: `src/webapp/store.py`
- Modify: `tests/unit/test_store.py`

### 變更摘要

| 方法 | 變更 |
|------|------|
| `init_schema()` | 執行 `db/001_init.sql`，移除內嵌 DDL |
| `upsert_election()` | 移除 `status` 欄位 |
| `insert_source_record()` | 移除 `imported_at` |
| `list_elections()` | 移除 `elections.status` 欄位（改由 JOIN 推導） |
| `list_source_records()` | **新增** |
| `upsert_candidate()` | **新增** |
| `list_candidates_by_name()` | **新增** |
| `list_candidates_with_elections()` | **新增** |
| `commit_election()` | **新增** |
| `append_operation_log()` | **移除** |
| `iter_resolved_records()` | **移除** |
| `list_unresolved_records()` | **移除** |

- [ ] **Step 1: 更新 test_store.py — 移除 status 欄位**

將所有 `upsert_election` 呼叫中的 `"status": "todo"` 移除：

```python
# Before (每個測試都有)
store.upsert_election({
    "election_id": election_id,
    "type": "test",
    "label": "Test Election",
    "path": f"/tmp/{election_id}",
    "status": "todo",  # ← 移除這行
})

# After
store.upsert_election({
    "election_id": election_id,
    "type": "test",
    "label": "Test Election",
    "path": f"/tmp/{election_id}",
})
```

- [ ] **Step 2: 執行現有測試，確認目前狀態**

```bash
uv run pytest tests/unit/test_store.py -v 2>&1 | head -40
```

預期：部分 PASS，有些因為 schema 問題 FAIL（`status` column 不存在等）。

- [ ] **Step 3: 更新 store.py — init_schema() 改執行 SQL 檔**

```python
ROOT = Path(__file__).resolve().parents[2]

def init_schema(self) -> None:
    sql_path = ROOT / "db" / "001_init.sql"
    ddl = sql_path.read_text(encoding="utf-8")
    with self.connect() as conn:
        conn.execute(ddl)
```

- [ ] **Step 4: 更新 store.py — upsert_election() 移除 status**

```python
def upsert_election(self, election: dict[str, Any]) -> None:
    with self.connect() as conn:
        conn.execute(
            """
            INSERT INTO elections(election_id, type, label, path, year, session)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT(election_id) DO UPDATE SET
                type    = EXCLUDED.type,
                label   = EXCLUDED.label,
                path    = EXCLUDED.path,
                year    = EXCLUDED.year,
                session = EXCLUDED.session
            """,
            (
                election["election_id"],
                election["type"],
                election["label"],
                str(election["path"]),
                election.get("year"),
                election.get("session"),
            ),
        )
```

- [ ] **Step 5: 更新 store.py — insert_source_record() 移除 imported_at**

```python
def insert_source_record(
    self,
    *,
    source_record_id: str,
    election_id: str,
    payload: dict[str, Any],
) -> None:
    with self.connect() as conn:
        conn.execute(
            """
            INSERT INTO source_records(source_record_id, election_id, name, birthday, payload)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(source_record_id) DO UPDATE SET
                election_id = EXCLUDED.election_id,
                name        = EXCLUDED.name,
                birthday    = EXCLUDED.birthday,
                payload     = EXCLUDED.payload
            """,
            (
                source_record_id,
                election_id,
                payload["name"],
                payload.get("birthday"),
                Jsonb(payload),
            ),
        )
```

- [ ] **Step 6: 新增 store.py — list_source_records()**

```python
def list_source_records(self, election_id: str) -> list[dict[str, Any]]:
    with self.connect() as conn:
        rows = conn.execute(
            """
            SELECT source_record_id, election_id, name, birthday, payload
            FROM source_records
            WHERE election_id = %s
            ORDER BY source_record_id
            """,
            (election_id,),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 7: 新增 store.py — upsert_candidate() 與 list_candidates_by_name()**

`candidates` 表儲存 `normalize_name(name)`，讓 matching 查詢可以精確比對：

```python
from src.normalize import normalize_name as _normalize_name

def upsert_candidate(self, id: str, name: str, birthday: int | None) -> None:
    with self.connect() as conn:
        conn.execute(
            """
            INSERT INTO candidates(id, name, birthday)
            VALUES (%s, %s, %s)
            ON CONFLICT(id) DO NOTHING
            """,
            (id, _normalize_name(name), birthday),
        )

def list_candidates_by_name(self, name: str) -> list[dict[str, Any]]:
    normalized = _normalize_name(name)
    with self.connect() as conn:
        rows = conn.execute(
            "SELECT id, name, birthday FROM candidates WHERE name = %s",
            (normalized,),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 8: 新增 store.py — list_candidates_with_elections()**

`build_candidates.py` 用這個方法讀取業務資料：

```python
def list_candidates_with_elections(self) -> list[dict[str, Any]]:
    with self.connect() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id, c.name, c.birthday,
                ce.year, ce.type, ce.region, ce.party,
                ce.elected, ce.session, ce.ticket, ce.order_id
            FROM candidates c
            LEFT JOIN candidate_elections ce ON ce.candidate_id = c.id
            ORDER BY c.id, ce.year NULLS LAST
            """
        ).fetchall()

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        cid = row["id"]
        if cid not in grouped:
            grouped[cid] = {
                "id": cid,
                "name": row["name"],
                "birthday": row["birthday"],
                "elections": [],
            }
        if row["year"] is not None:
            election = {k: row[k] for k in ("year", "type", "region", "party", "elected", "session", "ticket", "order_id") if row[k] is not None}
            grouped[cid]["elections"].append(election)

    return list(grouped.values())
```

- [ ] **Step 9: 新增 store.py — commit_election()**

```python
def commit_election(
    self,
    *,
    election_id: str,
    decisions: dict[str, dict[str, Any]],
    source_records_map: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    """Batch write resolutions + candidates + candidate_elections in one transaction.
    Returns (auto_count, manual_count).
    """
    auto = manual = 0
    _ELECTION_KEYS = ("year", "type", "region", "party", "elected", "session", "ticket", "order_id")

    with self.connect() as conn:
        for src_id, decision in decisions.items():
            candidate_id = decision["candidate_id"]
            mode = decision["mode"]
            payload = source_records_map[src_id]

            conn.execute(
                """
                INSERT INTO resolutions(source_record_id, election_id, candidate_id, mode)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(source_record_id) DO UPDATE SET
                    candidate_id = EXCLUDED.candidate_id,
                    mode         = EXCLUDED.mode
                """,
                (src_id, election_id, candidate_id, mode),
            )
            conn.execute(
                """
                INSERT INTO candidates(id, name, birthday)
                VALUES (%s, %s, %s)
                ON CONFLICT(id) DO NOTHING
                """,
                (candidate_id, _normalize_name(payload["name"]), payload.get("birthday")),
            )
            conn.execute(
                """
                INSERT INTO candidate_elections
                    (candidate_id, year, type, region, party, elected, session, ticket, order_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(candidate_id, year, type, region) DO UPDATE SET
                    party   = EXCLUDED.party,
                    elected = EXCLUDED.elected
                """,
                (
                    candidate_id,
                    payload.get("year"),
                    payload.get("type"),
                    payload.get("region"),
                    payload.get("party"),
                    payload.get("elected"),
                    payload.get("session"),
                    payload.get("ticket"),
                    payload.get("order_id"),
                ),
            )
            if mode in ("auto", "new"):
                auto += 1
            else:
                manual += 1

    return auto, manual
```

- [ ] **Step 10: 移除 store.py 中的廢棄方法**

移除以下三個方法（完整刪除）：
- `append_operation_log()`
- `iter_resolved_records()`
- `list_unresolved_records()`

- [ ] **Step 11: 新增 test_store.py — 測試新方法**

```python
def test_store_commit_election_writes_candidates_and_elections() -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.init_schema()
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")

    token = uuid4().hex
    election_id = f"test/commit-{token}.yaml"
    src_id = f"{election_id}:0"
    candidate_id = f"id_測試人_{token[:8]}"

    try:
        store.upsert_election({
            "election_id": election_id,
            "type": "test",
            "label": "Commit Test",
            "path": f"/tmp/{election_id}",
        })
        store.insert_source_record(
            source_record_id=src_id,
            election_id=election_id,
            payload={"name": "測試人", "birthday": 1970, "year": 2024,
                     "type": "縣市首長", "region": "臺北市", "party": "無黨籍", "elected": 0},
        )
        auto, manual = store.commit_election(
            election_id=election_id,
            decisions={src_id: {"mode": "auto", "candidate_id": candidate_id}},
            source_records_map={src_id: {"name": "測試人", "birthday": 1970, "year": 2024,
                                         "type": "縣市首長", "region": "臺北市",
                                         "party": "無黨籍", "elected": 0}},
        )

        assert auto == 1 and manual == 0

        candidates = store.list_candidates_with_elections()
        target = next((c for c in candidates if c["id"] == candidate_id), None)
        assert target is not None
        assert target["elections"][0]["year"] == 2024
        assert target["elections"][0]["region"] == "臺北市"
    finally:
        store.delete_election(election_id)
```

- [ ] **Step 12: 執行測試，確認通過**

```bash
uv run pytest tests/unit/test_store.py -v
```

預期：全部 PASS。

- [ ] **Step 13: Commit**

```bash
git add src/webapp/store.py tests/unit/test_store.py
git commit -m "refactor(store): update schema methods, add candidates/commit_election"
```

---

## Task 3: matching.py + build_candidates.py 更新

**Files:**
- Modify: `src/webapp/matching.py`
- Modify: `src/webapp/build_candidates.py`
- Modify: `tests/integration/test_webapp_build_candidates.py`

- [ ] **Step 1: 更新 matching.py**

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.normalize import generate_id, normalize_name

if TYPE_CHECKING:
    from src.webapp.store import Store


def classify_record(record: dict[str, Any], store: Store) -> dict[str, Any]:
    normalized_name = normalize_name(record["name"])
    matches = store.list_candidates_by_name(record["name"])
    # list_candidates_by_name returns candidates whose name == normalized_name
    # filter defensively in case store contains mixed normalization
    matches = [c for c in matches if normalize_name(c["name"]) == normalized_name]

    if not matches:
        return {"kind": "new", "candidate_id": generate_id(record["name"], record.get("birthday"))}

    birthday = record.get("birthday")
    same_birthday = [c for c in matches if c.get("birthday") == birthday]
    if birthday is not None and len(same_birthday) == 1:
        return {"kind": "auto", "candidate_id": same_birthday[0]["id"]}

    return {"kind": "manual", "matches": matches}
```

- [ ] **Step 2: 更新 build_candidates.py**

`build_candidates_yaml` 改從 `list_candidates_with_elections()` 讀取，不再依賴 `resolutions + source_records`：

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.validate import validate_candidates
from src.webapp.store import Store


def build_candidates_yaml(store: Store) -> list[dict[str, Any]]:
    candidates = store.list_candidates_with_elections()
    for candidate in candidates:
        candidate["elections"].sort(key=lambda e: e["year"])
    return sorted(candidates, key=lambda c: (c["elections"][0]["year"] if c["elections"] else 0, c["id"]))


def _load_valid_types(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as f:
        return {row["id"] for row in yaml.safe_load(f) or []}


def write_candidates_yaml(store: Store, output_path: Path, election_types_path: Path) -> list[dict[str, Any]]:
    candidates = build_candidates_yaml(store)
    errors = validate_candidates(candidates, _load_valid_types(election_types_path))
    if errors:
        raise ValueError("; ".join(errors))
    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(candidates, f, allow_unicode=True, sort_keys=False)
    return candidates
```

- [ ] **Step 3: 更新 test_webapp_build_candidates.py**

新的 commit flow 改用 `commit_election()`，不再直接呼叫 `save_resolution()`：

```python
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from src.webapp.build_candidates import build_candidates_yaml, write_candidates_yaml
from src.webapp.store import Store, load_database_config

ROOT = Path(__file__).resolve().parents[2]


def test_build_candidates_yaml_groups_records_by_candidate_id(tmp_path: Path) -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.init_schema()
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")

    token = uuid4().hex
    election_id = f"test/build-{token}.yaml"
    src_id = f"{election_id}:0"
    candidate_id = "id_柯文哲_1959"
    payload = {
        "name": "柯文哲",
        "birthday": 1959,
        "year": 2024,
        "type": "立法委員",
        "region": "全國",
        "party": "台灣民眾黨",
        "elected": 0,
    }

    try:
        store.upsert_election({
            "election_id": election_id,
            "type": "test",
            "label": "Build Test",
            "path": f"/tmp/{election_id}",
        })
        store.insert_source_record(
            source_record_id=src_id,
            election_id=election_id,
            payload=payload,
        )
        store.commit_election(
            election_id=election_id,
            decisions={src_id: {"mode": "auto", "candidate_id": candidate_id}},
            source_records_map={src_id: payload},
        )

        rows = build_candidates_yaml(store)
        target = next(r for r in rows if r["id"] == candidate_id)
        assert target["elections"][0]["year"] == 2024

        output = tmp_path / "candidates.yaml"
        write_candidates_yaml(store, output, ROOT / "election_types.yaml")
        written = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert any(r["id"] == candidate_id for r in written)
    finally:
        store.delete_election(election_id)
```

- [ ] **Step 4: 執行測試**

```bash
uv run pytest tests/integration/test_webapp_build_candidates.py -v
```

預期：PASS。

- [ ] **Step 5: Commit**

```bash
git add src/webapp/matching.py src/webapp/build_candidates.py \
        tests/integration/test_webapp_build_candidates.py
git commit -m "refactor: update matching and build_candidates to use DB"
```

---

## Task 4: Logging Setup + FastAPI Skeleton

**Files:**
- Create: `src/webapp/logging_setup.py`
- Create: `src/webapp/app.py`
- Create: `src/webapp/routes/__init__.py`
- Create: `src/webapp/routes/elections.py` (stub)
- Create: `src/webapp/routes/review.py` (stub)
- Create: `src/webapp/routes/build.py` (stub)

- [ ] **Step 1: Create logging_setup.py**

```python
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    ops_handler = logging.handlers.RotatingFileHandler(
        log_dir / "operations.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    ops_handler.setFormatter(fmt)
    ops_handler.setLevel(logging.INFO)

    err_handler = logging.handlers.RotatingFileHandler(
        log_dir / "errors.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    err_handler.setFormatter(fmt)
    err_handler.setLevel(logging.ERROR)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(ops_handler)
    root.addHandler(err_handler)
```

- [ ] **Step 2: Create route stubs**

`src/webapp/routes/__init__.py` — 空檔。

`src/webapp/routes/elections.py`:
```python
from fastapi import APIRouter

router = APIRouter()
```

`src/webapp/routes/review.py`:
```python
from fastapi import APIRouter

router = APIRouter()
```

`src/webapp/routes/build.py`:
```python
from fastapi import APIRouter

router = APIRouter()
```

- [ ] **Step 3: Create app.py**

```python
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from src.webapp.logging_setup import setup_logging
from src.webapp.routes import build, elections, review
from src.webapp.store import Store

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(root: Path = ROOT) -> FastAPI:
    setup_logging(root / "logs")

    app = FastAPI(title="Identity Workbench")
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-in-prod"),
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    store = Store()
    store.init_schema()

    app.state.store = store
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.root = root

    app.include_router(elections.router)
    app.include_router(review.router)
    app.include_router(build.router)

    return app


def main() -> None:
    import uvicorn
    app = create_app()
    app.state.store.validate_connection()
    uvicorn.run(app, host="127.0.0.1", port=23088)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 確認 app 可啟動（不報 import error）**

```bash
uv run python -c "from src.webapp.app import create_app; print('OK')"
```

預期：`OK`

- [ ] **Step 5: Commit**

```bash
git add src/webapp/logging_setup.py src/webapp/app.py \
        src/webapp/routes/__init__.py src/webapp/routes/elections.py \
        src/webapp/routes/review.py src/webapp/routes/build.py
git commit -m "feat: add fastapi skeleton and logging setup"
```

---

## Task 5: Templates + CSS

**Files:**
- Create: `src/webapp/templates/base.html`
- Create: `src/webapp/templates/elections.html`
- Create: `src/webapp/templates/review.html`
- Modify: `src/webapp/static/styles.css`

- [ ] **Step 1: Create base.html**

Navigator 永遠顯示，workspace 由各頁 override。

```html
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Identity Workbench</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
<main class="shell">

  <aside class="navigator">
    <div class="brand">
      <span class="eyebrow">Candidate Merge</span>
      <h1>Identity Workbench</h1>
    </div>

    <button class="button ghost" onclick="location.reload()">Refresh</button>

    <div class="election-list">
      {% for group_name, group_elections in election_groups %}
      <div class="tree-dir">▾ {{ group_name }}</div>
      {% for election in group_elections %}
      <a class="tree-row {% if election.election_id == selected_id %}selected{% endif %}"
         href="/elections/{{ election.election_id | urlencode }}">
        <span class="tree-label">{{ election.label }}</span>
        <span class="badge badge-{{ election.status }}">
          {% if election.status == 'review' %}{{ election.unresolved_count }} 待審
          {% else %}{{ election.status }}{% endif %}
        </span>
      </a>
      {% endfor %}
      {% endfor %}
    </div>

    <div class="nav-footer">
      <form method="post" action="/build">
        <button class="generate-btn" type="submit">⬇ Generate candidates.yaml</button>
      </form>
      {% if generated is defined %}
      <p class="build-result">✓ {{ generated }} 位候選人已匯出</p>
      {% endif %}
    </div>
  </aside>

  <section class="workspace">
    {% block workspace %}{% endblock %}
  </section>

</main>
</body>
</html>
```

- [ ] **Step 2: Create elections.html**

```html
{% extends "base.html" %}
{% block workspace %}

{% if not election %}
  {# 首頁，未選取任何選舉 #}
  <div class="workspace-empty">
    <p>← 從左側選取一場選舉開始</p>
  </div>

{% elif election.status == 'todo' %}
  {# State A: todo #}
  <div class="state-todo">
    <p class="pathline">{{ election.type }} / {{ election.year }}</p>
    <h2>{{ election.label }}</h2>
    <p>此選舉尚未匯入資料</p>
    <form method="post" action="/elections/{{ election.election_id | urlencode }}/load">
      <button class="button primary load-btn" type="submit">↓ Load Election</button>
    </form>
  </div>

{% elif election.status == 'done' %}
  {# State C: done #}
  <div class="workspace-header">
    <div>
      <p class="pathline">{{ election.type }} / {{ election.year }}</p>
      <h2>{{ election.label }}</h2>
    </div>
  </div>
  <div class="status">
    ✓ 已完成：{{ election.resolved_count }} 筆 ({{ election.imported_count }} 匯入)
  </div>

{% endif %}

{% endblock %}
```

- [ ] **Step 3: Create review.html**

```html
{% extends "base.html" %}
{% block workspace %}

<div class="workspace-header">
  <div>
    <p class="pathline">{{ election.type }} / {{ election.year }}</p>
    <h2>{{ election.label }}</h2>
    <div class="progress-wrap">
      <div class="progress-track">
        <div class="progress-fill" style="width: {{ progress_pct }}%;"></div>
      </div>
      <span class="progress-label">{{ resolved_count }} / {{ total_count }} 已完成</span>
    </div>
  </div>
</div>

<div class="review-grid">
  {# Incoming Record #}
  <article class="panel">
    <h3>Incoming Record</h3>
    {% for key, value in record_fields %}
    <div class="record-field"><strong>{{ key }}</strong><span>{{ value }}</span></div>
    {% endfor %}
  </article>

  {# Possible Matches #}
  <article class="panel">
    <h3>Possible Existing Candidates</h3>
    <form method="post" action="/review/{{ election.election_id | urlencode }}/resolve">
      <input type="hidden" name="source_record_id" value="{{ current_record.source_record_id }}">
      <input type="hidden" name="i" value="{{ i }}">

      {% for match in matches %}
      <label class="match-card {% if loop.first %}selected{% endif %}">
        <input type="radio" name="candidate_id" value="{{ match.id }}"
               {% if loop.first %}checked{% endif %} style="display:none">
        <strong>{{ match.name }}</strong>
        <span>生日：{{ match.birthday }} ｜ {{ match.id }}</span>
      </label>
      {% endfor %}

      <div class="decision-bar">
        <button class="button primary" name="mode" value="use_match"
                {% if not matches %}disabled{% endif %}>
          Use Selected Match
        </button>
        <button class="button secondary" name="mode" value="new">
          Create New Person
        </button>
      </div>
    </form>
  </article>
</div>

{# Navigation #}
<div class="bottom-bar">
  <div class="nav-btns">
    {% if i > 0 %}
    <a class="button ghost" href="/review/{{ election.election_id | urlencode }}?i={{ i - 1 }}">← 上一筆</a>
    {% endif %}
    {% if i < total_count - 1 %}
    <a class="button ghost" href="/review/{{ election.election_id | urlencode }}?i={{ i + 1 }}">下一筆 →</a>
    {% endif %}
  </div>
</div>

{# Commit area #}
{% if resolved_count < total_count %}
<div class="commit-pending">
  <p>⏳ 仍有 {{ total_count - resolved_count }} 筆待審核</p>
  <button class="button" disabled>Commit to DB</button>
</div>
{% else %}
<div class="commit-ready">
  <p>✓ 全部 {{ total_count }} 筆審核完畢，可提交至 DB</p>
  <form method="post" action="/elections/{{ election.election_id | urlencode }}/commit">
    <button class="button primary" type="submit">Commit to DB →</button>
  </form>
</div>
{% endif %}

{% endblock %}
```

- [ ] **Step 4: 更新 styles.css**

保留現有色系，新增 review 頁所需的 class。在現有 `styles.css` 末尾加入：

```css
/* Tree compact */
.election-list { display: flex; flex-direction: column; gap: 0; margin-top: 12px; max-height: calc(100vh - 200px); overflow-y: auto; }
.tree-dir { padding: 8px 8px 2px; color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; }
.tree-row { display: flex; align-items: center; justify-content: space-between; padding: 1px 8px 1px 20px; border-radius: 6px; line-height: 1.5; text-decoration: none; color: var(--ink); font-size: 12px; }
.tree-row:hover { background: rgba(226,244,237,.72); }
.tree-row.selected { background: #e2f4ed; color: var(--accent-strong); }
.tree-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.badge { border-radius: 8px; padding: 0 5px; font-size: 9.5px; font-weight: 700; margin-left: 4px; }
.badge-todo { background: #f3f4f6; color: #9ca3af; }
.badge-review { background: #fef3c7; color: #d97706; }
.badge-done { background: #d1fae5; color: #059669; }

/* Navigator footer */
.nav-footer { border-top: 1px solid var(--line); padding-top: 10px; margin-top: auto; }
.generate-btn { width: 100%; border-radius: 10px; padding: 9px 12px; font-size: 12px; font-weight: 700; background: var(--accent); color: white; border: 0; cursor: pointer; text-align: left; }
.generate-btn:hover { background: var(--accent-strong); }
.build-result { color: var(--accent-strong); font-size: 12px; margin: 6px 0 0; }

/* State todo */
.state-todo { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 60vh; gap: 14px; text-align: center; }
.load-btn { border-radius: 14px; padding: 12px 28px; font-size: 14px; }
.workspace-empty { display: flex; align-items: center; justify-content: center; min-height: 60vh; color: var(--muted); }

/* Review layout */
.review-grid { display: grid; grid-template-columns: minmax(220px,.9fr) minmax(280px,1.1fr); gap: 14px; }
.record-field { display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--line); padding: 5px 0; font-size: 12px; }
.record-field span { color: var(--muted); }
.match-card { border: 1px solid var(--line); border-radius: 12px; padding: 8px 10px; margin-bottom: 6px; cursor: pointer; display: grid; gap: 2px; background: rgba(255,255,255,.58); }
.match-card:has(input:checked) { border-color: var(--accent); background: #e2f4ed; }
.match-card strong { font-size: 12.5px; }
.match-card span { color: var(--muted); font-size: 11px; }
.decision-bar { display: flex; gap: 8px; margin-top: 12px; }
.bottom-bar { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.nav-btns { display: flex; gap: 6px; }
.progress-wrap { display: flex; align-items: center; gap: 8px; margin-top: 5px; }
.progress-track { flex: 1; height: 3px; border-radius: 2px; background: var(--line); }
.progress-fill { height: 3px; border-radius: 2px; background: var(--accent); }
.progress-label { font-size: 11px; color: var(--muted); white-space: nowrap; }
.commit-pending { border-radius: 12px; padding: 10px 14px; background: #f9fafb; border: 1px solid var(--line); display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.commit-pending p { color: var(--muted); font-size: 12px; }
.commit-ready { border-radius: 12px; padding: 10px 14px; background: #d1fae5; border: 1px solid #6ee7b7; display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.commit-ready p { color: #065f46; font-size: 12.5px; }
```

- [ ] **Step 5: Commit**

```bash
git add src/webapp/templates/ src/webapp/static/styles.css
git commit -m "feat: add jinja2 templates and updated styles"
```

---

## Task 6: Elections Routes (GET / + GET /elections/{id} + POST /elections/{id}/load)

**Files:**
- Modify: `src/webapp/routes/elections.py`

- [ ] **Step 1: 實作 helper — election_tree()**

在 `routes/elections.py` 加入 helper，供所有 route 取得 navigator 資料：

```python
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.webapp.discovery import discover_elections, load_election_records
from src.webapp.matching import classify_record
from src.webapp.store import Store

router = APIRouter()
logger = logging.getLogger(__name__)


def _election_tree(root: Path, store: Store) -> list[tuple[str, list[dict]]]:
    """Discover _data/ and return grouped elections for the navigator."""
    raw = discover_elections(root)
    for e in raw:
        store.upsert_election(e)

    db_map = {e["election_id"]: e for e in store.list_elections()}
    groups: dict[str, list[dict]] = {}
    for e in raw:
        group = e["election_id"].split("/")[0]
        db_e = db_map.get(e["election_id"], e)
        db_e.setdefault("status", "todo")
        groups.setdefault(group, []).append(db_e)

    return list(groups.items())
```

- [ ] **Step 2: 實作 GET /**

```python
@router.get("/")
async def home(request: Request):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates

    generated = request.query_params.get("generated")
    election_groups = _election_tree(root, store)

    return templates.TemplateResponse("elections.html", {
        "request": request,
        "election_groups": election_groups,
        "selected_id": None,
        "election": None,
        "generated": int(generated) if generated else None,
    })
```

- [ ] **Step 3: 實作 GET /elections/{election_id:path}**

```python
@router.get("/elections/{election_id:path}")
async def election_detail(request: Request, election_id: str):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates

    election_groups = _election_tree(root, store)
    db_map = {e["election_id"]: e for g, es in election_groups for e in es}
    election = db_map.get(election_id)
    if election is None:
        return RedirectResponse("/")

    return templates.TemplateResponse("elections.html", {
        "request": request,
        "election_groups": election_groups,
        "selected_id": election_id,
        "election": election,
    })
```

- [ ] **Step 4: 實作 POST /elections/{election_id:path}/load**

```python
@router.post("/elections/{election_id:path}/load")
async def load_election(request: Request, election_id: str):
    store: Store = request.app.state.store
    root: Path = request.app.state.root

    election_groups = _election_tree(root, store)
    raw_elections = {e["election_id"]: e for g, es in election_groups for e in es}
    election = raw_elections.get(election_id)
    if election is None:
        return RedirectResponse("/", status_code=303)

    # Load source records from file
    # Discover again to get the path
    raw = {e["election_id"]: e for e in discover_elections(root)}
    raw_election = raw.get(election_id)
    if raw_election is None:
        return RedirectResponse("/", status_code=303)

    session = request.session
    pending_key = f"pending_{election_id}"
    decisions: dict[str, dict] = {}

    for record in load_election_records(raw_election):
        store.insert_source_record(
            source_record_id=record["source_record_id"],
            election_id=election_id,
            payload=record,
        )
        result = classify_record(record, store)
        if result["kind"] in ("auto", "new"):
            decisions[record["source_record_id"]] = {
                "mode": result["kind"],
                "candidate_id": result["candidate_id"],
            }

    session[pending_key] = decisions
    logger.info("load election=%s records=%d auto=%d manual=%d",
                election_id, len(store.list_source_records(election_id)),
                len(decisions),
                len(store.list_source_records(election_id)) - len(decisions))

    return RedirectResponse(f"/review/{election_id}", status_code=303)
```

- [ ] **Step 5: 手動驗證（啟動 server）**

```bash
uv run python -m src.webapp.app
```

打開 http://127.0.0.1:23088，確認：
- 左側顯示 `_data/` 樹狀清單
- 點選 todo 選舉後出現 State A workspace

- [ ] **Step 6: Commit**

```bash
git add src/webapp/routes/elections.py
git commit -m "feat(routes): add elections list and load routes"
```

---

## Task 7: Review Routes (GET /review/{id} + POST /resolve + POST /commit)

**Files:**
- Modify: `src/webapp/routes/review.py`

- [ ] **Step 1: 實作 GET /review/{election_id:path}**

```python
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.webapp.discovery import discover_elections
from src.webapp.matching import classify_record
from src.webapp.store import Store
from src.webapp.routes.elections import _election_tree

router = APIRouter()
logger = logging.getLogger(__name__)

_FIELD_LABELS = {
    "name": "姓名", "birthday": "生日", "party": "政黨",
    "type": "選舉", "region": "地區", "elected": "當選",
    "year": "年份", "session": "屆次", "ticket": "號次",
}


@router.get("/review/{election_id:path}")
async def review_page(request: Request, election_id: str, i: int = 0):
    store: Store = request.app.state.store
    root: Path = request.app.state.root
    templates: Jinja2Templates = request.app.state.templates

    pending_key = f"pending_{election_id}"
    decisions: dict = request.session.get(pending_key, {})

    source_records = store.list_source_records(election_id)
    if not source_records:
        return RedirectResponse(f"/elections/{election_id}", status_code=303)

    total_count = len(source_records)
    resolved_count = sum(1 for r in source_records if r["source_record_id"] in decisions)
    progress_pct = int(resolved_count / total_count * 100) if total_count else 0

    i = max(0, min(i, total_count - 1))
    current_record = source_records[i]
    payload = current_record["payload"]

    result = classify_record(payload, store)
    matches = result.get("matches", [])

    record_fields = [
        (_FIELD_LABELS.get(k, k), payload[k])
        for k in ("name", "birthday", "year", "type", "region", "party", "elected")
        if k in payload
    ]

    election_groups = _election_tree(root, store)
    db_map = {e["election_id"]: e for g, es in election_groups for e in es}
    election = db_map.get(election_id, {"election_id": election_id, "label": election_id})

    return templates.TemplateResponse("review.html", {
        "request": request,
        "election_groups": election_groups,
        "selected_id": election_id,
        "election": election,
        "current_record": current_record,
        "record_fields": record_fields,
        "matches": matches,
        "i": i,
        "total_count": total_count,
        "resolved_count": resolved_count,
        "progress_pct": progress_pct,
    })
```

- [ ] **Step 2: 實作 POST /review/{election_id:path}/resolve**

```python
@router.post("/review/{election_id:path}/resolve")
async def resolve(request: Request, election_id: str):
    form = await request.form()
    mode = form.get("mode")
    source_record_id = form.get("source_record_id")
    candidate_id = form.get("candidate_id")
    i = int(form.get("i", 0))

    store: Store = request.app.state.store

    if mode == "new":
        # Generate new candidate id from this source record
        record = store.get_source_record(source_record_id)
        if record:
            from src.normalize import generate_id
            candidate_id = generate_id(record["name"], record.get("birthday"))

    if source_record_id and mode and candidate_id:
        pending_key = f"pending_{election_id}"
        decisions = request.session.get(pending_key, {})
        decisions[source_record_id] = {"mode": mode, "candidate_id": candidate_id}
        request.session[pending_key] = decisions

    next_i = i + 1
    source_records = store.list_source_records(election_id)
    next_i = min(next_i, len(source_records) - 1)

    return RedirectResponse(f"/review/{election_id}?i={next_i}", status_code=303)
```

- [ ] **Step 3: 實作 POST /elections/{election_id:path}/commit**

```python
@router.post("/elections/{election_id:path}/commit")
async def commit(request: Request, election_id: str):
    store: Store = request.app.state.store

    pending_key = f"pending_{election_id}"
    decisions: dict = request.session.get(pending_key, {})
    source_records = store.list_source_records(election_id)

    if len(decisions) < len(source_records):
        return RedirectResponse(f"/review/{election_id}", status_code=303)

    source_records_map = {r["source_record_id"]: r["payload"] for r in source_records}
    auto, manual = store.commit_election(
        election_id=election_id,
        decisions=decisions,
        source_records_map=source_records_map,
    )

    logger.info("commit election=%s auto=%d manual=%d total=%d",
                election_id, auto, manual, auto + manual)

    request.session.pop(pending_key, None)
    return RedirectResponse(f"/elections/{election_id}", status_code=303)
```

- [ ] **Step 4: 手動驗證**

啟動 server，選取一場 todo 選舉，load，在 review 頁逐筆操作，確認：
- 上一筆 / 下一筆 navigation 正常
- Use Selected Match / Create New Person 儲存到 session
- 全部完成後 Commit to DB 按鈕啟用
- Commit 後跳回 election 頁，badge 變為 done

- [ ] **Step 5: Commit**

```bash
git add src/webapp/routes/review.py
git commit -m "feat(routes): add review, resolve, and commit routes"
```

---

## Task 8: Build Route + FastAPI TestClient Tests + Cleanup

**Files:**
- Modify: `src/webapp/routes/build.py`
- Create: `tests/unit/test_routes.py`
- Delete: `src/webapp/server.py`
- Delete: `tests/unit/test_server.py`

- [ ] **Step 1: 實作 POST /build**

```python
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from src.webapp.build_candidates import write_candidates_yaml
from src.webapp.store import Store

router = APIRouter()
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]


@router.post("/build")
async def build(request: Request):
    store: Store = request.app.state.store
    root: Path = request.app.state.root

    try:
        candidates = write_candidates_yaml(
            store,
            root / "candidates.yaml",
            root / "election_types.yaml",
        )
        logger.info("build candidates count=%d", len(candidates))
        return RedirectResponse(f"/?generated={len(candidates)}", status_code=303)
    except Exception as exc:
        logger.error("build failed: %s", exc, exc_info=True)
        return RedirectResponse("/?build_error=1", status_code=303)
```

- [ ] **Step 2: 新增 tests/unit/test_routes.py**

```python
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient

from src.webapp.app import create_app
from src.webapp.store import Store, load_database_config


def _make_app(tmp_path: Path, store: Store):
    app = create_app(root=tmp_path)
    app.state.store = store
    return app


def test_home_returns_200(tmp_path: Path) -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.init_schema()
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")

    # _data/ が必要
    (tmp_path / "_data" / "president").mkdir(parents=True)
    app = _make_app(tmp_path, store)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Identity Workbench" in resp.text


def test_load_and_review_flow(tmp_path: Path) -> None:
    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.init_schema()
    except ConnectionError:
        pytest.skip("PostgreSQL is not reachable")

    token = uuid4().hex
    election_path = (
        tmp_path / "_data" / "legislator" / "party-list-legislator" / f"{token}th.yaml"
    )
    election_path.parent.mkdir(parents=True)
    election_path.write_text(
        "- name: 測試候選人\n  party: 測試黨\n  birthday: 1970\n"
        "  year: 2024\n  region: 全國\n  type: 立法委員\n  elected: 0\n  session: 11\n",
        encoding="utf-8",
    )
    election_id = f"legislator/party-list-legislator/{token}th.yaml"

    app = _make_app(tmp_path, store)
    client = TestClient(app, raise_server_exceptions=True)

    try:
        # Load
        resp = client.post(f"/elections/{election_id}/load", follow_redirects=False)
        assert resp.status_code == 303

        # Review page
        resp = client.get(f"/review/{election_id}")
        assert resp.status_code == 200
        assert "測試候選人" in resp.text

        # Resolve
        src_records = store.list_source_records(election_id)
        src_id = src_records[0]["source_record_id"]
        resp = client.post(
            f"/review/{election_id}/resolve",
            data={"source_record_id": src_id, "mode": "new", "i": "0"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Commit
        resp = client.post(f"/elections/{election_id}/commit", follow_redirects=False)
        assert resp.status_code == 303

        candidates = store.list_candidates_with_elections()
        assert any(c["name"] == "測試候選人" for c in candidates)
    finally:
        store.delete_election(election_id)
```

- [ ] **Step 3: 執行新 test_routes.py**

```bash
uv run pytest tests/unit/test_routes.py -v
```

預期：全部 PASS。

- [ ] **Step 4: 刪除舊檔案**

```bash
rm src/webapp/server.py tests/unit/test_server.py
```

- [ ] **Step 5: 執行全部測試確認無殘留依賴**

```bash
uv run pytest -v
```

預期：全部 PASS，無 import error。

- [ ] **Step 6: Commit**

```bash
git add src/webapp/routes/build.py tests/unit/test_routes.py
git rm src/webapp/server.py tests/unit/test_server.py
git commit -m "feat: complete fastapi routes, add route tests, remove old server"
```
