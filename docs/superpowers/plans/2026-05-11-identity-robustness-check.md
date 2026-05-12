# Identity Robustness Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent post-commit review flow for suspicious candidate identity merges.

**Architecture:** The feature scans committed DB records and writes reviewable issue rows. A separate UI lets the user inspect suspicious elections, preview a split or merge result, and apply the correction with a durable operation record.

**Tech Stack:** FastAPI, Jinja2, PostgreSQL, pytest.

---

### Task 1: Persistence

**Files:**
- Modify: `db/001_init.sql`
- Modify: `docs/db-schema.md`
- Modify: `src/webapp/store.py`

- [ ] Add `identity_check_issues` for review state.
- [ ] Add `identity_fix_operations` for before / after repair history.
- [ ] Add store methods for scan, preview data, and atomic repair.

### Task 2: Detection

**Files:**
- Create: `src/webapp/identity_checks.py`
- Test: `tests/unit/test_identity_checks.py`

- [ ] Detect same-year multiple elections.
- [ ] Detect elected high-office to later lower-office paths.
- [ ] Detect local election region jumps with county-city equivalence.

### Task 3: UI Flow

**Files:**
- Create: `src/webapp/routes/identity_checks.py`
- Create: `src/webapp/templates/identity_checks.html`
- Create: `src/webapp/templates/identity_check_detail.html`
- Modify: `src/webapp/templates/base.html`
- Modify: `src/webapp/static/styles.css`
- Modify: `src/webapp/app.py`

- [ ] Add scan button and issue list.
- [ ] Add detail page with suspicious election selection.
- [ ] Add preview page before applying a repair.
- [ ] Add operation log display.

### Task 4: Verification

**Files:**
- Test: `tests/unit/test_store.py`
- Test: `tests/unit/test_routes.py`

- [ ] Verify scan creates issues from committed records.
- [ ] Verify repair moves committed records and rebuilds affected candidate histories.
- [ ] Verify UI pages render issue list, detail, preview, and operation logs.
