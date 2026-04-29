# CLAUDE.md

使用繁體中文作為溝通語言

## 環境

Python 環境使用 `uv` 管理. 執行任何 Python 指令請使用 `uv run`:

```bash
uv run python -m src.webapp.app   # 啟動 identity-ui
uv run pytest                     # 執行測試
uv add <package>
```

## 專案目標

從 `_data/` (中選會原始選舉資料, 已 gitignore) 產生並維護:

- `candidates.yaml` — 候選人主 mapping 檔
- `election_types.yaml` — 合法 type enum 清單

`_data/` 資料類型: `president/`, `mayor/`, `legislator/`, `council/`

## Identity UI (`src/webapp/`)

FastAPI + Jinja2 候選人身分判定介面. 以 DB 作為 single source of truth, `candidates.yaml` 由 Build 操作產生.

- 設計規格: `docs/superpowers/specs/2026-04-28-identity-ui-fastapi-refactor-design.md`
- `identity ui`, `identity-ui`, `mapping app` 為同義詞, 均指此介面

## 命名規範

- region 欄位使用官方全名, `臺` 不寫作 `台` (如 `臺北市`, `臺中市`)
- `election_types.yaml` 合法 type 值: `國家元首_總統`, `國家元首_副總統`, `縣市首長`, `立法委員`, `縣市議員`

---

## 核心開發原則

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 0. Read-Only Gate

**Consultation overrides execution when intent is mixed.**

Before changing files, running write operations, or touching external state:
- If the user asks for advice, evaluation, review, "is this a good approach", "think about it first", or similar wording, treat the request as read-only consultation.
- If a message contains both an apparent command and consultation wording, do not execute the command yet. Explain the possible interpretations, give the recommendation, and wait for an explicit follow-up such as "please change it", "do it", or "apply this".
- Do not rely on the first sentence alone when the later text narrows the request to advice or decision support.
- A brief "I will not edit files yet" statement is required when answering a mixed-intent request.

Before any edit is allowed, the assistant must be able to state:
- what files or state will be changed,
- why the user's latest message clearly authorizes that change,
- what success condition will be checked.

If any of these cannot be stated clearly, stop and ask or answer read-only.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
