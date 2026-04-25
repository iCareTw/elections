# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 環境

Python 環境使用 `uv` 管理。執行任何 Python 指令請使用 `uv run`：

```bash
uv run python main.py
uv add <package>
```

## 專案目標

從 `_data/`（中選會原始選舉資料，已 gitignore）產生並維護兩份 YAML 檔：

- `candidates.yaml` — 候選人主 mapping 檔（姓名、id、生日、參選紀錄）
- `election_types.yaml` — 合法 type enum 清單

詳細 schema 設計見 `docs/superpowers/specs/2026-04-08-candidates-mapping-design.md`。

## 資料結構

`_data/` 下分四類，目前只處理前兩類：

- `president/` — 總統副總統選舉 `.xlsx`（每任一檔）
- `mayor/` — 縣市首長選舉 `.xlsx`（直轄市與縣市分開，民國年份命名）
- `legislator/` — 立法委員（暫不處理，格式不一致）
- `council/` — 縣市議員（暫不處理，格式不一致）

## 命名規範

- region 欄位使用官方全名，`臺` 不寫作 `台`（如 `臺北市`、`臺中市`）
- `election_types.yaml` 中的合法 type 值：`國家元首_總統`、`國家元首_副總統`、`縣市首長`、`立法委員`、`縣市議員`

---

## Karpathy Skills — 核心開發原則

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

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
