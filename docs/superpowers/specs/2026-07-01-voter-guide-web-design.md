# 選舉公報 Web 檢視與後台修正 — 設計 spec

日期:2026-07-01
狀態:設計定稿,待轉實作計畫

## 1. 背景與目標

`src/voter_guide/` 目前能解析總統選舉公報 PDF,產出 YAML + 切圖 + 照片檔於硬碟,尚未進 DB。

本專案要建立:

1. 把公報解析結果落地到 DB(不存 binary,只存切圖/照片路徑)
2. 一個獨立的 Web 介面,可依年度/選戰瀏覽候選人資料
3. 每個欄位(含照片)可做**人工疑慮標記**並補充說明
4. 標記後的修正:文字欄可觸發 **local LLM 背景修復**或**手動填正確值**;照片以**在 PDF 上手動圈選區塊**補正(不走 AI)
5. 以 **commit 快照**建立候選人資料版本,可前後切換檢視

介面同時具備:呈現、後台修改、AI 補救三種能力。

## 2. 範圍

### 本期範圍

- 選舉類型:**僅總統**(president)。schema 與 UI 採通用結構,欄位不寫死總統專屬,未來加入縣市長/立委/議員不需重構。
- 資料來源:既有解析器產出的 YAML + 切圖 + 照片檔。

### 刻意不做(非目標)

- 其他選舉類型(mayor/legislator/councilor)的解析器(尚未實作,無資料可灌)
- 通用資料治理、多人協作、即時監看 `_data/` 變化
- 影像的歷史版本保存(見 §5 相片規則)
- **產出或影響 `candidates.yaml`**:本功能不參與 `candidates.yaml` / `election_types.yaml` 的任何生成或修改。
- **與 identity UI 整合**:現階段本功能與 identity UI(`elections`/`candidates`/`resolutions` 等既有機制)**完全獨立**——不共用其頁面路由、不寫入其資料表、不設指向其表的 FK。`guide_candidates.candidate_id`、`guide_elections.election_id` 僅為**未來備用的可空欄位**,本期不填、不用。任何整合方式將來另議,不在本 spec 範圍。

## 3. 資料模型

新增於既有 `elections` schema。全採**欄位化(field-cell)**:以「單一欄位」為最小單位儲存,以支援每欄獨立的信心分級、切圖來源、疑慮標記與版本。

### 3.1 `guide_elections` — 公報選舉

| field | type | description |
|-------|------|-------------|
| `id` | TEXT PK | 公報選舉識別碼(如 `president_2024_16`) |
| `type` | VARCHAR(32) | 選舉類型,合法值見 `election_types.yaml` |
| `year` | INTEGER | 選舉年份 |
| `session` | INTEGER | 屆/任次(總統為「任」),可 NULL |
| `label` | TEXT | 顯示名稱(如「第16任 2024 總統」) |
| `source_pdf_path` | TEXT | 來源公報 PDF 相對路徑 |
| `election_id` | TEXT NULL | 預留欄位,未來或對應 identity 的 `elections.election_id`;**本期不設 FK、不填值、無任何整合行為** |

### 3.2 `guide_candidates` — 公報候選人

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | surrogate key |
| `guide_election_id` | TEXT FK | → `guide_elections.id`,ON DELETE CASCADE |
| `ticket` | INTEGER | 號次 |
| `role` | VARCHAR(16) NOT NULL DEFAULT '' | 角色:`總統` / `副總統`;無角色概念的類型填 `''`(空字串,非 NULL,確保 unique 可用) |
| `party` | VARCHAR(32) NULL | 政黨(見下方政黨處理說明) |
| `photo_path` | TEXT NULL | **當前**照片檔路徑(單值,不留歷史,見 §5) |
| `photo_flagged` | BOOLEAN NOT NULL DEFAULT false | 照片是否被標記疑慮 |
| `photo_note` | TEXT NULL | 照片疑慮補充說明 |
| `source_page` | INTEGER NULL | 該候選人在來源 PDF 的頁碼,供手動圈選補照片時開啟正確頁面(見 §5) |
| `candidate_id` | VARCHAR(64) NULL | 預留欄位,未來或對應 identity 的 `candidates.id`;**本期不設 FK、不填值、無任何整合行為** |
| `order_id` | INTEGER | 排序用流水號 |

Unique:`(guide_election_id, ticket, role)`。

**政黨處理(明確設計):** parser 的政黨是**組別層級**(登記方式欄,一組一值,並帶自己的 verify grade)。本期**刻意**將政黨視為候選人的**顯示屬性**,非可標記的欄位:

- load 時將該組單一政黨值**複製到正、副兩列**的 `party`。
- parser 算出的政黨 grade **不保留**(政黨極少誤判,不納入信心分級與 AI 修復)。
- 政黨在 UI 以組別標籤呈現(如「第1組 · 民進黨」),**不可標記疑慮、不進 `guide_fields`、不進版本快照**。
- 未來若需讓政黨可標記/修復,再以擴充處理(非本期範圍)。

### 3.3 `guide_fields` — 欄位工作中資料(current / working state)

代表某候選人某文字欄位的**目前值**,是 AI 修復與手動修改直接改動的對象。

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | surrogate key |
| `guide_candidate_id` | INTEGER FK | → `guide_candidates.id`,ON DELETE CASCADE |
| `field_name` | VARCHAR(32) | 欄名:`姓名` / `出生年月日` / `性別` / `學歷` / `經歷`(通用,依類型可擴充) |
| `value` | TEXT NULL | 目前值(僅存公報真值,不含任何系統註記) |
| `grade` | VARCHAR(16) NULL | 信心分級(解析時的比對結果,如 `完全一致`) |
| `source_crop_path` | TEXT NULL | 此值來源切圖相對路徑 |
| `flagged` | BOOLEAN NOT NULL DEFAULT false | 是否被標記疑慮(標記 = 此欄值有問題) |
| `flag_note` | TEXT NULL | 疑慮補充說明 |
| `update_source` | VARCHAR(16) | 目前值來源:`parse` / `ai` / `manual` |
| `updated_at` | TIMESTAMPTZ | 最後更新時間 |

Unique:`(guide_candidate_id, field_name)`。

注:

- `相片` 不列入 `guide_fields`,以 `guide_candidates.photo_*` 承載。
- **值格式**:`value` 一律存 parser 產出的原字串(如 `出生年月日` 為 `民國{y}年{m}月{d}日`);任何格式正規化屬 UI 呈現層,不改動儲存值。
- **`grade` 值域**(來自 parser verify):`完全一致` / `幾乎一致` / `大部分一致` / `資料不可靠` / `無法解析` / `看圖存疑` / `不適用`(皆 ≤5 字,VARCHAR(16) 足夠)。手動填值(`update_source=manual`)時 `grade` 設 NULL。
- **`source_crop_path` 可為 NULL**:見 §4「切圖來源與缺圖處理」。缺圖時該欄的「AI 修復」停用(見 §4.3)。
- **性別渲染**:值為 `男`→藍、`女`→粉小人圖示;非此二值(理論上罕見)則不顯示圖示,僅以文字呈現原值。

### 3.4 `guide_snapshots` — 已提交版本

一次 commit = 該候選人一個版本快照。

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | surrogate key |
| `guide_candidate_id` | INTEGER FK | → `guide_candidates.id`,ON DELETE CASCADE |
| `version_no` | INTEGER | 該候選人版本序號,從 1 遞增 |
| `note` | TEXT NULL | commit 備註 |
| `created_at` | TIMESTAMPTZ | 建立時間 |

Unique:`(guide_candidate_id, version_no)`。

### 3.5 `guide_snapshot_fields` — 版本欄位凍結副本

commit 當下,將該候選人所有 `guide_fields` 凍結一份;版本 ◀▶ 切換即讀此表。**不含相片**。

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | surrogate key |
| `snapshot_id` | INTEGER FK | → `guide_snapshots.id`,ON DELETE CASCADE |
| `field_name` | VARCHAR(32) | 欄名 |
| `value` | TEXT NULL | 該版本凍結值 |
| `grade` | VARCHAR(16) NULL | 凍結信心分級 |
| `source_crop_path` | TEXT NULL | 凍結切圖路徑 |
| `flagged` | BOOLEAN NOT NULL | 凍結標記狀態 |
| `flag_note` | TEXT NULL | 凍結補充說明 |

Unique:`(snapshot_id, field_name)`。

### 3.6 `guide_repair_jobs` — AI 修復背景工作

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | surrogate key |
| `guide_candidate_id` | INTEGER FK | → `guide_candidates.id`,ON DELETE CASCADE |
| `target` | VARCHAR(32) | 修復對象:**文字欄名**(如 `學歷`);**照片不走 AI,不建此類 job**(見 §5) |
| `status` | VARCHAR(16) | `queued` / `running` / `done` / `failed` |
| `user_note` | TEXT NULL | 觸發時帶入的人工補充說明 |
| `before_value` | TEXT NULL | 修復前的欄位值 |
| `result_value` | TEXT NULL | 修復後的欄位值 |
| `error` | TEXT NULL | 失敗原因 |
| `created_at` | TIMESTAMPTZ | 建立時間 |
| `finished_at` | TIMESTAMPTZ NULL | 完成時間 |

Index:`(status)`、`(guide_candidate_id)`。

### 3.7 版本 / commit 狀態推導

- **有未提交變更**:候選人存在任一 `guide_fields` 於最後一次 snapshot 之後被改動(以 `updated_at` 對比最後 snapshot `created_at`,或以「與最後 snapshot_fields 內容不同」判定),或照片被更換/標記。
- **Commit**:將目前 `guide_fields` 全部寫入新的 `guide_snapshots` + `guide_snapshot_fields`,`version_no` = 前一版 +1。
- **捨棄變更**:以最後一個 snapshot 的 `guide_snapshot_fields` 覆蓋回 `guide_fields`(照片不受版本管理,不還原)。

## 4. 資料流

1. **載入(load 指令)**
   解析器產出 YAML + 切圖 + 照片檔;切圖/照片的輸出路徑與命名須依下述**人類可讀命名慣例**(相對現況是一項有界的 parser 產出調整)。獨立 `load` 指令讀取產物,寫入 `guide_elections` / `guide_candidates` / `guide_fields`(僅存路徑),並自動建立 **v1 snapshot**。

   **切圖來源與缺圖處理**(重要):parser 的 YAML 不含切圖路徑,切圖以下列**人類可讀命名慣例**落地(此為與 parser 約定的產物契約,parser 產出路徑需調整為此規格):

   `_out/parsed/{type}/{session}th_{year_ad}_ticket_{ticket}_{name}_{field}.png`

   例:`_out/parsed/president/16th_2024_ticket_1_柯文哲_學歷.png`

   各代號:
   - `{type}`:選舉類型英文目錄(`president` / 未來 `mayor` / `legislator` / `councilor`)。
   - `{session}th`:任/屆次 + 字面 `th`(第16任 → `16th`)。
   - `{year_ad}`:**西元年** = 民國年 + 1911(113 → `2024`)。
   - `ticket_{ticket}`:字面 `ticket_` + **號次**(第1組 → `ticket_1`)。
   - `{name}`:**參選人姓名**(如 `柯文哲`);同一號次的正/副以姓名區分,不需 role。
   - `{field}`:**欄名**(`姓名` / `出生年月日` / `性別` / `學歷` / `經歷`;照片為 `相片`)。

   **產物契約補充**(parser 須提供,load 須寫入):
   - **來源頁碼**:parser 解析階段已知每位候選人的 PDF 頁碼(`geo.Person.page`),須寫入 YAML(或 load 可讀來源),由 load 填入 `guide_candidates.source_page`。此為 §5.2 手動圈選補照片的前置,缺此則照片無法補正。
   - **name ↔ role 映射**:檔名以 `{name}`(姓名)為鍵,DB unique 以 `role` 為鍵;parser 兩者皆知,load 負責建立對應。同一號次正副同名(總統選舉近乎不可能)才會檔名相撞,屬可忽略邊界。
   - **session 缺值命名**:總統恆有任次(`16th`);未來 `session` 可為 NULL 的類型,檔名該段以固定字面 `session0`(或省略該段)處理,屆時於各類型 parser 明定,本期不涉及。

   load 依此慣例由(type、session、西元年、號次、姓名、欄名)重組每欄 `source_crop_path`,並**以檔案存在與否**決定填值或填 NULL。已知缺圖情況:
   - 113 的 `出生年月日` / `性別` 來自合併「基本資料」格再切子欄,**無各自切圖**:這兩欄 `source_crop_path` 填該「基本資料」整格圖(若存在),否則 NULL。
   - parser 以 `--no-vision` 執行時**不產生任何切圖**:全欄 `source_crop_path` = NULL。
   - `source_crop_path` 為 NULL 的欄位,其「AI 修復」在 UI 停用(見 §4.3);仍可手動填值。

   **重複載入政策**(避免資料遺失):`load` 預設**只處理尚未載入的選舉**;若該 `guide_elections.id` 已存在,**預設拒絕並提示**,不覆蓋。需要強制重灌時以明確 `--force` 旗標執行,且 `--force` 會**警示將刪除該場所有 `guide_*` 資料(含已提交 snapshot、人工修正、標記)並重建 v1**,由操作者確認。無 `--force` 絕不覆蓋既有資料。

2. **標記**
   欄位或照片按「⚑ 標記」→ 出現補充說明輸入框 → 寫入 `flagged` + `flag_note` / `photo_flagged` + `photo_note`。標記即代表「此欄值有問題」。

3. **AI 修復(背景,僅文字欄)**
   建立 `guide_repair_jobs`(status=queued)後背景執行:餵〔該欄 `source_crop_path` 切圖 + `user_note` 補充說明 + 欄名〕給 local 視覺模型重讀,得新值。**前置條件**:`source_crop_path` 非 NULL;為 NULL 時 UI 不提供「AI 修復」按鈕(僅能手動填值)。
   完成 → 更新 `guide_fields`(`update_source=ai`),job status=done → 前端輪詢後右上角跳 toast 告知。失敗則 status=failed 並記 `error`。
   **照片不走此路**:照片修正一律用手動圈選(見 §5),不建 AI job。
   **標記不自動解除**:AI 修復完成後,該欄 `flagged` 維持,由 user 檢視結果後自行「解除標記」或直接 commit;避免修復結果未經確認就視為已解決。

4. **手動修正**
   - **文字欄**:直接改 `guide_fields.value`(`update_source=manual`,`grade` 設 NULL)。列為未提交變更。
   - **照片**:用手動圈選補照片(見 §5)。
   兩者標記皆不自動解除,由 user 自行「解除標記」。

5. **Commit / 捨棄**:見 §3.7。

## 5. 相片規則與手動圈選補照片

### 5.1 相片為當前單值

相片只有「正確 / 錯誤」兩種狀態,保存錯誤舊版無意義:

- 相片為**當前單值**(`guide_candidates.photo_path`),**不進版本快照**、**不留歷史**。
- 更換照片即**覆蓋**當前路徑,舊錯圖檔可刪除。
- 版本 ◀▶ 切換僅影響文字欄;各版本畫面顯示的照片皆為當前照片。
- 相片可標記疑慮,但**不走 AI 修復**;修正一律用下述手動圈選。

### 5.2 手動圈選補照片(照片修正的唯一機制)

照片抓錯(如 113 全部誤用第1組照片)時,以手動圈選補正,取代不可靠的 AI 重新偵測:

1. 在照片列按「圈選補照片」→ web 依 `guide_candidates.source_page` 開啟該候選人所屬**來源 PDF 頁面**並渲染於畫面。
2. User 在頁面上**畫一個方框**框住正確的大頭照區塊。
3. 確認後,前端把方框座標(換算回 PDF 頁座標)送回後端;後端沿用既有裁切能力,依該座標從 PDF 裁出新照片檔 → 覆蓋 `guide_candidates.photo_path`。
4. 此操作為**即時**(僅裁切,不需模型),不建背景 job;完成即更新畫面。列為未提交變更,標記不自動解除。

此機制同時涵蓋「照片本來就抓錯」與「照片缺圖」兩種情況——只要有來源 PDF 與頁碼即可補正。文字欄的缺圖不適用本機制(文字缺圖改以手動填值)。

**防呆**:`source_page` 為 NULL 時(理論上不應發生,見 §4 產物契約),「圈選補照片」按鈕停用並提示缺來源頁碼,避免死路。

## 6. Web / 程式結構

- 沿用既有技術棧 **FastAPI + Jinja2**,共用 DB 連線;作為**獨立的公報瀏覽/後台介面**,與 identity UI 產品邊界分開,不混用其頁面與路由。
- 版面(三欄,已於 brainstorming 定稿):
  - **左**:類型 > 年度/屆次 樹狀選單(現僅總統)。
  - **中**:選定年度下的候選組別 → 正/副候選人清單,用於**切換候選人**;有疑慮者以橙點標示。
  - **右**:欄位面板。
    - 標題列右側:版本切換 ◀ / `v{n}(已提交)` / ▶。
    - 有未提交變更時,面板上方顯示黃色橫幅 +「建立快照(Commit)」「捨棄變更」。
    - 每欄一列:欄名、值、信心分級標籤、來源切圖縮圖、「⚑ 標記」。
    - 姓名列左側依性別顯示藍(男)/粉(女)小人圖示。
    - 已標記**文字欄**展開顯示補充說明框與動作:🤖 用 AI 修復(切圖存在才有此鈕)/ ✎ 手動填正確值 / 解除標記。
    - **相片列**:可標記;修正動作為「🖼 圈選補照片」(開 PDF 手動框選,見 §5.2),無 AI 修復。
- **AI 修復通知**:文字欄 AI 修復為背景作業;前端輪詢 `guide_repair_jobs` 狀態,完成時右上角跳 toast。手動圈選補照片為即時操作,無需輪詢。

## 7. 元件邊界

| 元件 | 職責 | 對外介面 | 依賴 |
|------|------|----------|------|
| load 指令 | 將解析產物匯入 `guide_*` 表並建 v1 | CLI:輸入 YAML/產物路徑 | 檔案系統、DB |
| DB 存取層 | `guide_*` 表讀寫、commit/捨棄、未提交判定 | 函式介面 | DB |
| AI 修復執行器(文字欄) | 依 job 重讀文字欄切圖得新值 | 讀 `guide_repair_jobs` queued → 更新結果 | local 視覺模型、`src/voter_guide` 視覺能力 |
| 手動圈選補照片模組 | 渲染來源 PDF 頁、接收框選座標、裁切覆蓋照片 | HTTP:輸入候選人+框座標 → 新照片 | `src/voter_guide` 裁切能力、來源 PDF |
| Web(FastAPI+Jinja2) | 呈現、標記、觸發文字 AI 修復、圈選補照片、手動填值、commit、版本切換、通知輪詢 | HTTP 路由 + 頁面 | DB 存取層、AI 修復執行器、圈選補照片模組 |

## 8. 開放待實作細節(交由實作計畫決定,非規格缺口)

- 背景工作載體:FastAPI BackgroundTasks 或簡易輪詢 worker(單人本機,擇一即可)。
- local 視覺模型的呼叫沿用 `src/voter_guide` 既有 `transcribe` 能力。
- 手動圈選補照片:PDF 頁在瀏覽器的渲染方式、螢幕框選座標 ↔ PDF 頁座標的換算與縮放校正,屬實作細節;裁切沿用 `src/voter_guide` 既有 `crop_cell` 能力。
- migration 檔編號依 `db/` 現況接續,並同步更新 `docs/db-schema.md`。
