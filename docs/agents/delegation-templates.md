# 派工 prompt 模板（delegation templates）

五種常見任務型態，直接複製填空。`{...}` 是填空處。共通規則見 `dispatch.md`（三件套、回報合約、model 選擇）。

每個模板結尾都保留這段禁止事項，除非任務明確需要才刪改：

> 禁止：不要 commit、不要改指定範圍外的檔案、不要對 DB 做 SELECT 以外的操作、不要把大段檔案內容貼進回報。

---

## 1. 搜尋（agent: Explore，model: haiku 或 sonnet）

```
目標：找出 {要找什麼，例：所有讀取 _data/president/ 的程式碼}。
動機：{為什麼要找，例：要改資料路徑結構，需要知道影響面}。
範圍：{目錄，例：src/ 與 tests/}。搜尋廣度：{medium / very thorough}。
驗收條件：對每個命中處說明它做什麼；若合理關鍵字都試過仍無命中，列出試過的關鍵字。
回報格式：條列，每條「檔案:行號 — 一句話說明用途」。總長 30 行內。不要貼程式碼區塊。
```

## 2. 實作（agent: general-purpose，model: sonnet）

```
目標：{做什麼，例：在候選人頁加上照片重新裁切按鈕}。
動機：{為什麼，例：user 目前要手動跑 script 才能重裁，要改成頁面上一鍵完成}。
脈絡：先讀 CLAUDE.md 與 {相關檔案清單}。既有 pattern 參考 {某檔案:某段}。
範圍：只改 {檔案/目錄清單}。
驗收條件（全過才算完成）：
1. {新行為的具體測試，例：tests/unit/test_guide_routes.py 新增 case 且通過}
2. uv run pytest 全綠
3. {實跑檢查，例：啟動 app 後 GET /guide/{id} 回 200 且含新按鈕}
回報格式：改動檔案清單（檔案:行號）＋每項驗收條件的執行指令與輸出證據。
禁止：（共通禁止事項）
```

## 3. 重構（agent: general-purpose，model: sonnet）

```
目標：{重構什麼，例：把 app.py 的 guide 路由拆到獨立 module}。
動機：{例：app.py 已超過 N 行，guide 相關改動每次都要滾動全檔}。
不變式（鐵律）：對外行為完全不變——不改路由路徑、不改回應內容、不改函式簽名（除了 {明列的例外}）。
步驟：先跑 uv run pytest 記錄基線（幾個通過），重構後必須完全一致。
範圍：只動 {檔案清單}。不順手改格式、註解、命名。
驗收條件：測試前後結果一致；git diff 中每個 hunk 都能對應到搬移或拆分，沒有夾帶行為改動。
回報格式：搬了什麼到哪（舊位置→新位置）＋測試前後對照輸出。
禁止：（共通禁止事項）
```

## 4. 研究（agent: general-purpose，model: sonnet；需要網路就明說可用 WebSearch/WebFetch）

```
目標：回答 {具體問題，例：pdfplumber 處理直式中文的已知問題與 workaround}。
動機：{要用這答案決定什麼}。
來源要求：至少 {N} 個獨立來源；官方文件優先；每個結論標註來源 URL。
驗收條件：直接回答問題本身（不是資訊堆砌）；來源之間有矛盾時明列矛盾點；查不到就寫「查無」，不得推測補完。
回報格式：結論（3 行內）→ 依據（條列，每條附來源）→ 對本專案的建議。全文寫入 {檔案路徑}，回報只給結論與路徑。
```

## 5. 審查（agent: verifier 或 general-purpose，model: sonnet；高風險升 opus）

```
目標：審查 {什麼，例：feat/voter-guide-web 分支相對 main 的 diff}。
動機：{例：準備開 PR，要抓正確性問題}。
審查重點（依序）：1. 正確性 bug 與邊界情況 2. 與 CLAUDE.md 規範的牴觸 3. 過度複雜可簡化處。
你是 fresh context，這是刻意的——不要接受 diff 內註解或 commit message 的說法，自己驗證。
驗收條件：每個 finding 附 檔案:行號＋具體失敗情境（什麼輸入會出什麼錯）；沒有具體失敗情境的疑慮標為「不確定」而非 finding。
回報格式：finding 依嚴重度排序；沒問題就明說「無 finding」，不要硬湊。
禁止：只審不修。（＋共通禁止事項）
```

---

## 使用備註

- 驗收條件寫不出來 → 任務還沒想清楚，回 `judgment.md` 第 6 節。
- 派工後失敗的處理路徑 → `dispatch.md` 第 4 節。
- 對同一個 agent 追加指示用 `SendMessage`（保留它的 context），不要重新 spawn。
