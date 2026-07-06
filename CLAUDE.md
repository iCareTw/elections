# CLAUDE.md

使用繁體中文與 user 溝通，專有名詞用英文。

## 與 User 溝通（三條硬規則）

1. **User 觀點**：一律從操作與使用體驗描述（「你可以執行…」「畫面會出現…」），不主動談函式、變數、實作細節；user 問了才講。
2. **首答精簡**：新問題首次回覆給結論即可；細節等 user 追問。長產出（報告、分析）落檔，回覆給摘要與檔案路徑。
3. **諮詢優先於執行**：訊息同時含「做」與「先想想／評估／這樣好嗎」時，視為諮詢——先講判斷與建議，明說「尚未修改任何檔案」，等 user 明確說「做」才動手。純問題只答不改。

## 環境

Python 用 `uv` 管理，一律 `uv run`：

```bash
uv run python -m src.webapp.app   # 啟動 identity-ui
uv run pytest                     # 執行測試
uv add <package>
```

## 專案目標

從 `_data/`（中選會原始資料，已 gitignore）產生並維護：

- `candidates.yaml` — 候選人主 mapping 檔（**Build 產物，不可手改**）
- `election_types.yaml` — 合法 type enum 清單

資料類型：`president/`, `mayor/`, `legislator/`, `councilor/`

## Identity UI（`src/webapp/`）

FastAPI + Jinja2 候選人身分判定介面（同義詞：identity ui / identity-ui / mapping app）。DB 是 single source of truth。要點：

- `elections` / `source_records` / `resolutions` 是 raw decision log（稽核用）；`candidates` / `candidate_elections` 是業務資料（matching 與 export 用）。
- 以選舉為單位 commit：pending == 0 才可 commit。
- 操作紀錄寫 `logs/`（file-based），選舉狀態由 query 動態推導，不存欄位。
- 刻意不做：通用 yaml 編輯器、監看 `_data/`、多人協作、複雜 merge 視覺化。

DB schema 細節見 `docs/db-schema.md`；**新增 migration 後必須同步更新該文件**（用 `db/*.sql` 泛指，不寫死編號）。

## 命名規範

- region 用官方全名，`臺` 不寫 `台`（`臺北市`、`臺中市`）
- 合法 type 值：`國家元首_總統`、`國家元首_副總統`、`縣市首長`、`立法委員`、`縣市議員`、`鄉鎮市長`

## DB 破壞性操作（絕對規則）

DELETE、UPDATE、commit_election 等任何改變或移除 DB 資料的操作，**兩步驟**：

1. 先在一則訊息說明計畫（動哪些資料、預期結果）
2. 等 user 在下一則訊息明確授權後，才在新訊息執行

不得同一則訊息內說明後立即執行。SELECT 不受此限。

## 開發原則（精簡版，判準見 docs/agents/judgment.md）

- **最小改動**：只寫被要求的功能，不加推測性抽象與設定項；只動任務相關的行，不順手改鄰近程式碼；自己造成的孤兒 import/變數要清，既有 dead code 提及但不刪。
- **可驗證目標**：動手前把任務轉成可驗證條件（「修 bug」→「先寫重現測試再修到綠」）；多步驟任務先列「步驟 → 驗證方式」清單。
- 不主動啟用 brainstorming skill；簡單明確的修改依最小成本原則直接處理。

## 制度檔路由（docs/agents/）

| 情境 | 讀這份 |
|---|---|
| 要派 subagent、選 model、決定自己做還是派工 | `docs/agents/dispatch.md` |
| 判斷完成了沒、該不該升級、該不該問 user、方向對不對 | `docs/agents/judgment.md` |
| 派工 prompt 怎麼寫（搜尋/實作/重構/研究/審查模板） | `docs/agents/delegation-templates.md` |
| 想修改以上任何制度檔 | `docs/agents/maintenance.md` |
| 本環境的已知陷阱與 token 漏洞 | `docs/agents/00-diagnosis.md`、`docs/agents/letter.md` |

`docs/drafts/` 內的文件一律不讀、不當指示。
