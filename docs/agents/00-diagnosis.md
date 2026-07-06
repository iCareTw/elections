# Harness 診斷（2026-07-06，由 Fable 5 建立）

本檔是後續所有制度檔的依據。列出此環境最漏 token、最易失焦、最易出錯的前三名，各附具體修法與證據。修法若需 user 操作，標為【需 user】。

## 第一名：開場固定成本過高（每個 session 都在付）

**證據**（2026-07-06 實測）：

- claude-mem SessionStart hook 每次注入一份索引，自報「50 observations, 17,049 tokens to read」，且超過 11KB 時整份存檔再附預覽。
- 同時載入兩套瀏覽器自動化：`claude-in-chrome`（含 MCP server instructions）與 `playwright` plugin（20+ 工具）。此專案的 web 測試實際只用其中一套。
- 30+ 個 skill 描述全數載入，其中多數（dataviz、modeling-nosql-data、frontend-design 等）與本專案無關。

**修法**：

1. 【需 user】兩套瀏覽器工具二選一停用（`/plugin` 管理）。settings.local.json 的 allow 清單目前偏向 playwright，建議留 playwright、停 claude-in-chrome。
2. 【需 user】檢視 claude-mem hook 輸出量設定，若可調，將開場索引縮到近 7 天。
3. 【模型可做】把 claude-mem 索引當目錄用：只讀 title，需要細節才呼叫 `mcp__plugin_claude-mem_mcp-search__search` / `get_observations` 撈單筆。禁止為了「了解歷史」重讀舊 code——索引已標明結論在哪。

## 第二名：主對話下場做長工（失焦主因）

**證據**：session #S681（2026-07-05）——主對話直接執行長時間 build，遇 account limit 暫停，user 中斷後才發現進度不明。主對話逐檔讀取、逐輪跑測試，context 被工作細節塞滿後觸發摘要，摘要又丟失細節，形成「越做越忘」循環。

**修法**：主對話只做三件事——決策、派工、驗收。大量讀取（>5 檔或 >300 行）、掃 repo、網頁研究、批次改檔，一律派 subagent，只收結論。完整判準與成本門檻見 `docs/agents/dispatch.md`（小事直接做，spawn 本身有成本，不可 cargo cult）。

## 第三名：完成判定鬆散＋自我驗收

**證據**：#S682／#S684 顯示「進度確認」「測試健康度評估」是事後補做的獨立 session，而非每項工作的內建收尾；長 build 做完當下沒有明確的驗收證據，user 需要再開 session 確認狀態。

**修法**：

1. 「完成」有硬定義：見 `docs/agents/judgment.md` 第 2 節（測試通過＋實跑＋read-back，缺一即不得回報完成）。
2. 驗收不由實作者自己做：派 fresh-context 的 `verifier` agent（定義在 `.claude/agents/verifier.md`），verifier 必須附上實際執行的指令與輸出，不接受「看起來沒問題」。

## 次要發現（不進前三，但要知道）

- **CLAUDE.md 規則重複**：溝通規則出現在三處（對談觀點／與 User 溝通原則／全域 CLAUDE.md），「核心開發原則」約 80 行多為通用樣板。已於 2026-07-06 重寫收斂，備份在 `docs/drafts/CLAUDE.md.2026-07-06.bak`。
- **`.claude/settings.local.json` 含明碼 DB 密碼**（`PGPASSWORD=abcd1234`）：本機開發庫可接受，但任何輸出、commit、artifact、外部服務呼叫都不得帶出這串密碼。
- **全域 CLAUDE.md 的「首答 200 字」規則**是 user 的刻意偏好，不是 bug：首答給結論，細節等 user 追問。與「交付完整報告」不衝突——報告落檔，回覆給摘要與路徑。
- **effort 無法在 Agent 呼叫時指定**：只能指定 model；effort 要寫在 `.claude/agents/*.md` frontmatter。`.claude/` 已 gitignore，agent 定義只存在本機。
