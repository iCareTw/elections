# 給未來 session 的信

寫於 2026-07-06，由 Fable 5 在 user 唯一一次使用它的 session 中留下。你（讀者）大概是 Sonnet、Opus 或 Haiku。這封信講三件 user 沒問、但對這個環境最重要的事，以及這套制度最可能怎麼壞掉。

## 一、兩套記憶並存，分工要清楚

這個環境有**兩套**記憶系統，別混用也別重複寫：

- **內建 file-based memory**（`~/.claude/projects/-Users-icaretw-proj-icaretw-elections/memory/`）：存 user 偏好、user 給過的糾正、專案級約束。條目少而精，每個 session 自動載入索引。
- **claude-mem plugin**（SessionStart hook 注入索引＋MCP search 工具）：存工作歷史——哪個 session 做了什麼、決定了什麼。查歷史用它的 `search`/`get_observations`，不要為了了解過去重讀程式碼。

規則：「user 是誰、怎麼跟他工作」→ file memory；「以前做過什麼」→ claude-mem（它自動記，你不用手動餵）。同一件事不要兩邊各寫一份。

## 二、這位 user 的工作方式（尊重它，別重新發明）

- 他要**結論先行、細節後補**。首答 200 字內是全域規則，不是建議。他覺得需要細節自然會追問。
- 他用「操作與體驗」思考，不用「程式碼」思考。跟他確認需求時問「你希望畫面上看到什麼」，不要問「這個函式要回傳什麼」。
- **DB 兩步驟規則是他明確給過的 feedback**（見 auto-memory），踩線會直接傷害信任。寧可多等一則訊息。
- 他能接受你自主做事，但**混合語氣的訊息**（「幫我改…不過你覺得這樣好嗎」）他要的是討論，不是執行。拿不準就當諮詢處理。

## 三、環境的具體陷阱（每個都真實存在）

1. `candidates.yaml` 是 Build 產物。任何「修 yaml 裡的錯字」的衝動都是錯的——去修 DB 或修產生邏輯。
2. `_data/`、`_out/`、`logs/`、`.claude/` 都在 gitignore。`.claude/agents/verifier.md` 不會被 commit，消失了就從 `docs/agents/verifier-agent.md` 重建。
3. `.claude/settings.local.json` 允許清單裡有明碼 DB 密碼（本機 dev 庫）。這串字不得出現在 commit、artifact、對外輸出。
4. 同時載入 claude-in-chrome 與 playwright 兩套瀏覽器工具。此專案既有測試流程用 playwright（allow 清單可證），優先用它，別兩套混用。
5. `docs/drafts/` 是備份與草稿區，明文規定模型不讀。備份放這裡就是為了不汙染 context。
6. 開場注入的 claude-mem 索引約 17k tokens——它是**目錄**，掃 title 就好，別逐條消化。

## 四、這套制度最可能的退化方式與預防

1. **制度檔膨脹成沒人讀的長文** → maintenance.md 有硬性行數門檻（制度檔 160 行、CLAUDE.md 90 行）。觸線就精簡，別「下次再說」。
2. **派工變成儀式**：小事也 spawn，燒錢又慢；或者反過來，全部自己做，回到 #S681 的失焦老路 → dispatch.md 第 0 節的成本表是判準，兩個方向的偏差都對照它修正。
3. **驗收流於形式**：verifier 回「LGTM」沒證據，久了等於沒驗 → verifier 的回報格式強制附指令與輸出原文；收到沒有證據的「通過」，退回重驗，並把該次記進踩坑紀錄。
4. **規則與現實脫節**：agent 名、工具名、plugin 會變，制度檔引用的東西消失後，弱模型可能硬呼叫不存在的工具 → 遇到「制度檔叫我用 X 但 X 不存在」時：以當下環境為準，完成任務，然後照 maintenance.md 更新制度檔。這是明確授權，不用問。

## 五、交接欄（後續 session 有未完成事項寫這裡）

- 2026-07-06 建檔 session：無未完成事項。【需 user】的兩個建議（停用重複 browser plugin、調 claude-mem 開場量）記在 `00-diagnosis.md`，等 user 決定。
