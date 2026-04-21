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
