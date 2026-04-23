# Election Identity UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web app that lists elections, auto-resolves obvious same-person matches, shows manual same-name conflicts, records mapping decisions, and regenerates `candidates.yaml`.

**Architecture:** Keep the existing parsers and normalization logic as the source of truth for raw election records. Add a small Python web server plus a SQLite-backed `map-state/app.db` to store election scan results and mapping decisions, then generate `candidates.yaml` from those persisted decisions.

**Tech Stack:** Python 3.14, `sqlite3`, `http.server`, vanilla HTML/CSS/JS, `pyyaml`, `pytest`, existing parser modules in `src/`

---

## File Structure

- Create: `src/webapp/__init__.py`
- Create: `src/webapp/server.py`
  - Local HTTP server entrypoint, static file serving, JSON API routing.
- Create: `src/webapp/discovery.py`
  - Scan `_data/` and root `*th.yaml` sources into normalized `election` rows.
- Create: `src/webapp/store.py`
  - SQLite schema creation and CRUD helpers for elections, source records, resolutions, and logs.
- Create: `src/webapp/matching.py`
  - V1 identity rules: auto-match, manual-match candidate lookup, new-id creation.
- Create: `src/webapp/build_candidates.py`
  - Rebuild `candidates.yaml` from persisted records and resolutions.
- Create: `src/webapp/static/index.html`
  - Single-page shell for navigator + compare workspace.
- Create: `src/webapp/static/app.js`
  - Fetch elections, load review items, submit decisions, trigger rebuild.
- Create: `src/webapp/static/styles.css`
  - Compact tree navigator + simple compare layout.
- Create: `tests/unit/test_discovery.py`
- Create: `tests/unit/test_store.py`
- Create: `tests/unit/test_matching.py`
- Create: `tests/integration/test_webapp_build_candidates.py`
- Modify: `main.py`
  - Add a `serve-ui` command or keep CLI unchanged and add a new runner module.
- Modify: `pyproject.toml`
  - Only if a console script entry is added.
- Modify: `README.md`
  - Document how to start the UI and where `map-state/app.db` lives.

## Implementation Notes

- Reuse existing parsers from `src.parse_president`, `src.parse_mayor`, `src.parse_legislator`.
- Treat each source file as one `election`.
- Use `source_record_id = "{election_id}:{row_index}"`.
- Persist `mode = auto|manual|new|skip` on each resolution row.
- For v1 matching rules:
  - same normalized name + same birthday + exactly one existing candidate => auto
  - same normalized name + different birthday => manual
  - same normalized name + missing birthday => manual
  - no same-name candidate => create new id
- Keep final output as `candidates.yaml`.
- Store app state in `map-state/app.db`.

### Task 1: Add Election Discovery

**Files:**
- Create: `src/webapp/discovery.py`
- Test: `tests/unit/test_discovery.py`

- [ ] **Step 1: Write the failing test**

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

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing `discover_elections`

- [ ] **Step 3: Write minimal implementation**

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

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Expand discovery to all current source types**

Add support for `mayor`, `legislator`, future `_data/<type>` folders, and extract minimal display metadata (`year`, `session`, `status='todo'` default).

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_discovery.py src/webapp/discovery.py
git commit -m "feat: add election discovery for web ui"
```

### Task 2: Add SQLite Store

**Files:**
- Create: `src/webapp/store.py`
- Test: `tests/unit/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from src.webapp.store import Store


def test_store_saves_resolution_decision(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.db")
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

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_store.py -v`
Expected: FAIL with missing `Store`

- [ ] **Step 3: Write minimal implementation**

```python
import sqlite3


class Store:
    def __init__(self, path):
        self.path = path

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self):
        with self.connect() as conn:
            conn.executescript(
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
                "select * from resolutions where source_record_id = ?",
                (source_record_id,),
            ).fetchone()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_store.py -v`
Expected: PASS

- [ ] **Step 5: Expand schema**

Add tables for:
- `elections`
- `source_records`
- `resolutions`
- `operation_logs`

Include helpers for:
- upserting discovered elections
- storing parsed source records
- listing unresolved records for one election
- appending operation log rows

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_store.py src/webapp/store.py
git commit -m "feat: add sqlite store for election ui"
```

### Task 3: Add Matching Rules

**Files:**
- Create: `src/webapp/matching.py`
- Test: `tests/unit/test_matching.py`

- [ ] **Step 1: Write the failing test**

```python
from src.webapp.matching import classify_record


def test_classify_record_auto_matches_same_name_same_birthday() -> None:
    record = {"name": "柯文哲", "birthday": 1959}
    existing = [{"name": "柯文哲", "birthday": 1959, "id": "id_柯文哲_1959"}]

    result = classify_record(record, existing)

    assert result["kind"] == "auto"
    assert result["candidate_id"] == "id_柯文哲_1959"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_matching.py -v`
Expected: FAIL with missing `classify_record`

- [ ] **Step 3: Write minimal implementation**

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

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_matching.py -v`
Expected: PASS

- [ ] **Step 5: Add remaining rule coverage**

Add tests and code for:
- same name + different birthday => manual
- same name + missing birthday => manual
- same name + same birthday + multiple matches => manual
- no same-name match => new

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_matching.py src/webapp/matching.py
git commit -m "feat: add v1 identity matching rules"
```

### Task 4: Import Source Records Into Store

**Files:**
- Modify: `src/webapp/discovery.py`
- Modify: `src/webapp/store.py`
- Modify: `src/webapp/matching.py`
- Test: `tests/unit/test_discovery.py`
- Test: `tests/unit/test_store.py`

- [ ] **Step 1: Write the failing test**

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

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discovery.py tests/unit/test_store.py -v`
Expected: FAIL with missing `load_election_records`

- [ ] **Step 3: Write minimal implementation**

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

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discovery.py tests/unit/test_store.py -v`
Expected: PASS

- [ ] **Step 5: Persist imported rows and auto decisions**

For one election:
- parse records
- persist records to `source_records`
- load existing candidates from current `candidates.yaml`
- classify each row
- save `auto` and `new` resolutions immediately
- leave `manual` rows unresolved for UI review

- [ ] **Step 6: Commit**

```bash
git add src/webapp/discovery.py src/webapp/store.py src/webapp/matching.py tests/unit/test_discovery.py tests/unit/test_store.py
git commit -m "feat: persist imported source records"
```

### Task 5: Build `candidates.yaml` From Resolutions

**Files:**
- Create: `src/webapp/build_candidates.py`
- Test: `tests/integration/test_webapp_build_candidates.py`

- [ ] **Step 1: Write the failing integration test**

```python
from pathlib import Path

from src.webapp.build_candidates import build_candidates_yaml
from src.webapp.store import Store


def test_build_candidates_yaml_groups_records_by_candidate_id(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.db")
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

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_webapp_build_candidates.py -v`
Expected: FAIL with missing `build_candidates_yaml`

- [ ] **Step 3: Write minimal implementation**

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

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_webapp_build_candidates.py -v`
Expected: PASS

- [ ] **Step 5: Add file output + validation**

Write `write_candidates_yaml(store, output_path)` that:
- builds grouped candidates
- validates with `validate_candidates`
- writes `candidates.yaml`

- [ ] **Step 6: Commit**

```bash
git add src/webapp/build_candidates.py tests/integration/test_webapp_build_candidates.py
git commit -m "feat: rebuild candidates yaml from resolutions"
```

### Task 6: Add Local Web Server API

**Files:**
- Create: `src/webapp/server.py`
- Test: `tests/unit/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
from src.webapp.server import build_api


def test_build_api_lists_elections(tmp_path):
    app = build_api(tmp_path)
    data = app.handle_json("GET", "/api/elections")
    assert data[0]["election_id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_store.py -v`
Expected: FAIL with missing `build_api`

- [ ] **Step 3: Write minimal implementation**

```python
def build_api(root):
    class API:
        def handle_json(self, method, path, body=None):
            if method == "GET" and path == "/api/elections":
                return store.list_elections()
            raise KeyError(path)
    return API()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_store.py -v`
Expected: PASS

- [ ] **Step 5: Expand real HTTP endpoints**

Implement:
- `GET /api/elections`
- `POST /api/elections/<id>/load`
- `GET /api/elections/<id>/review-items`
- `POST /api/resolutions`
- `POST /api/build`

Serve `src/webapp/static/` for the frontend shell.

- [ ] **Step 6: Commit**

```bash
git add src/webapp/server.py tests/unit/test_store.py
git commit -m "feat: add local api server for web ui"
```

### Task 7: Add Minimal Frontend

**Files:**
- Create: `src/webapp/static/index.html`
- Create: `src/webapp/static/app.js`
- Create: `src/webapp/static/styles.css`
- Modify: `README.md`

- [ ] **Step 1: Build the HTML shell**

Create:
- compact left tree navigator
- right compare panel
- buttons for `Use Selected Match`, `Create New Person`, `Skip`

- [ ] **Step 2: Add failing smoke check**

Document a manual smoke check:

Run: `uv run python -m src.webapp.server`
Expected:
- browser opens `http://127.0.0.1:8000`
- left side lists elections
- right side loads one review item after selecting an election

- [ ] **Step 3: Write minimal frontend implementation**

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

- [ ] **Step 4: Verify manual workflow**

Check:
- selecting an election loads pending manual items
- selecting a match submits a resolution
- `Create New Person` generates and stores a new id
- `Build` rewrites `candidates.yaml`

- [ ] **Step 5: Document startup in README**

Add:
- `uv run python -m src.webapp.server`
- what lives in `map-state/app.db`
- how to rebuild `candidates.yaml`

- [ ] **Step 6: Commit**

```bash
git add src/webapp/static/index.html src/webapp/static/app.js src/webapp/static/styles.css README.md
git commit -m "feat: add election identity web ui"
```

### Task 8: End-to-End Verification

**Files:**
- Modify: `tests/integration/test_webapp_build_candidates.py`
- Modify: `README.md`

- [ ] **Step 1: Add end-to-end integration coverage**

Cover this sequence:
- discover one election
- import source records
- auto-resolve one same-name same-birthday row
- manually resolve one same-name different-birthday row
- rebuild `candidates.yaml`
- assert expected ids and elections exist

- [ ] **Step 2: Run focused tests**

Run: `uv run pytest tests/unit/test_discovery.py tests/unit/test_store.py tests/unit/test_matching.py tests/integration/test_webapp_build_candidates.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `make test`
Expected: all existing and new tests PASS

- [ ] **Step 4: Final commit**

```bash
git add tests README.md
git commit -m "test: cover election identity ui flow"
```
