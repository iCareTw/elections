# 模型調度守則（dispatch）

主對話（指揮官）只做三件事：**決策、派工、驗收**。工作細節不進主對話 context。

## 0. 先算成本，別 cargo cult

每次 spawn 都是冷啟動：subagent 要重新讀 CLAUDE.md、重新摸索脈絡。派工本身有固定成本，判準如下：

| 情境 | 做法 |
|---|---|
| 讀 ≤5 個已知檔案（合計 ≤300 行）、改 ≤3 個檔案、一次 grep 就能答 | **自己做**，派工反而虧 |
| 掃 repo 找東西（不確定在哪、要試多種關鍵字） | 派 `Explore` |
| 網頁研究、查文件、比對多個來源 | 派 `general-purpose` |
| 讀 >5 檔或合計 >300 行 | 派 `Explore` 或 `general-purpose`，只收結論 |
| 批次改檔（>3 檔）、實作一個完整功能、長時間 build | 派 `general-purpose` 或 `claude` |
| 驗收任何「已完成」的工作 | 派 `verifier`（見第 5 節） |
| 卡關兩次以上、需要第二意見 | 派 `codex:codex-rescue` |

可用 agent 清單以當下 session 開頭的 system-reminder 為準（清單會變，上表列的是 2026-07-06 存在的）。

## 1. Model 與 effort 指定

Agent 呼叫時用 `model` 參數顯式指定，不要留空靠繼承：

- `haiku`：機械性工作——已知 pattern 的批次搜尋、格式轉換、跑指令收輸出。
- `sonnet`：預設。實作、重構、研究、審查都從這裡開始。
- `opus`：設計取捨、跨模組除錯、sonnet 失敗兩次的任務。

**限制（誠實標註）**：Agent 呼叫無法指定 effort；effort 只能寫在 `.claude/agents/*.md` 的 frontmatter。本 repo 已提供 `.claude/agents/verifier.md`（`.claude/` 已 gitignore，只存在本機；不見了就照 `docs/agents/verifier-agent.md` 的副本重建）。

## 2. 派工三件套（缺一不派）

每個派工 prompt 必含：

1. **目標與動機**：要什麼、為什麼要（動機讓 subagent 在邊界情況做對取捨）。
2. **驗收條件**：可機械檢查的成功判準（測試指令、預期輸出、檔案應存在的內容）。寫不出驗收條件＝你自己還沒想清楚，先想清楚再派。
3. **回報格式**：明說要回什麼、多長、什麼格式。

另加兩條保險：明確的檔案／目錄範圍（防亂逛），與禁止事項（預設寫上：「不要 commit、不要改範圍外的檔案、不要動 DB 資料」）。

現成模板見 `docs/agents/delegation-templates.md`。

## 3. 回報合約

- Subagent 只回：**結論 + 檔案:行號 + 驗證證據**。
- 長產物（報告、diff、大量搜尋結果）寫進檔案（scratchpad 或 `_out/`），回報只傳路徑加三行摘要。
- 禁止把整個檔案內容、完整 log 貼回主對話。
- Subagent 的回報 user 看不到——主對話收到後要用自己的話把重點轉述給 user。

## 4. 升降級路徑

- **第 1 次失敗**：檢查是不是 prompt 問題（脈絡不足、驗收條件模糊）。是→補脈絡用 `SendMessage` 續派同一個 agent（保留其 context），或重派同級。
- **第 2 次失敗**：升級——haiku→sonnet→opus，或改派 `codex:codex-rescue` 拿第二意見。升級時把前兩次的失敗方式寫進 prompt。
- **第 3 次失敗**：停。這通常是方向錯了（見 `judgment.md` 第 4 節），整理三次嘗試與卡點，問 user。
- **降級**：opus/sonnet 拆解完問題後，剩餘的機械執行（批次套用同一 pattern）降給 haiku。

## 5. 驗證不自驗（鐵律）

實作者（不管是主對話還是 subagent）不得自己宣告驗收通過。收尾流程：

1. 實作完成後，派 fresh-context 的 verifier：先看 session 開頭 system-reminder 的可用 agent 清單，有 `verifier` 就用 `subagent_type: "verifier"`；**沒有就派 `general-purpose` 並把 `docs/agents/verifier-agent.md` 全文貼進 prompt**（`.claude/` 在 gitignore，此 agent 定義可能不存在於當下機器）。
2. 驗收方式按產物類型：
   - **檔案/文件**：read-back——verifier 實際讀檔，確認內容完整、與宣稱一致。
   - **程式碼**：跑測試（`uv run pytest`）＋照 `/verify` skill 精神實跑受影響的流程，不接受只過 typecheck。
   - **高風險判斷**（資料修正規則、身分判定邏輯）：第二意見——派另一個 agent 獨立解同一題，比對答案；或產多個候選答案後派評審 agent 選優並說明理由。
3. verifier 回報必須含實際執行的指令與關鍵輸出。回報裡沒有證據的「通過」視同未驗收。
