# DB Schema

Schema name: `elections`. 此文件記錄套用 `db/*.sql` 所有 migration 後的最終 schema 狀態.

初始化方式: 使用者先自行建立/切換 schema, 再執行 `db/001_init.sql`. 應用程式啟動時不負責建立或 migration DB schema.

---

## ER Model

```
┌──────────────────────┐                  ┌────────────┐
│      elections       │                  │ candidates │
└───────────┬──────────┘                  └─────┬──────┘
            │ 1                                 │ 1
            │ N                                 │ N
┌───────────▼──────────┐       ┌───────────────▼───────────┐
│    source_records    │       │    candidate_elections    │
└──────────┬───────────┘       └───────────────────────────┘
           │ 1
     ┌─────┴──────────────┐
  0..1                 0..1
     ▼                    ▼
┌──────────────────┐  ┌─────────────┐
│ review_decisions │  │ resolutions │
└──────────────────┘  └─────────────┘

┌───────────────────────┐        ┌─────────────────────────┐
│ identity_check_issues │        │ identity_fix_operations │
└───────────────────────┘        └─────────────────────────┘

candidates.id 另被以下表以 FK 參照 (皆 ON UPDATE/DELETE CASCADE):
  candidate_elections, identity_check_issues, resolutions, review_decisions
identity_fix_operations 僅記錄當時的 candidate id, 不設 FK (稽核歷史).
```

---

## elections

選舉檔案清單. 每筆代表一場從 `_data/` 匯入的選舉.

| field         | type        | description                              |
|---------------|-------------|------------------------------------------|
| `election_id` | TEXT PK     | 選舉唯一識別碼, 格式由 source data 決定      |
| `type`        | VARCHAR(32) | 選舉類型, 合法值見 `election_types.yaml`    |
| `label`       | TEXT        | 選舉顯示名稱                                |
| `path`        | TEXT        | source data 在 `_data/` 下的相對路徑        |
| `year`        | INTEGER     | 選舉年份                                   |
| `session`     | INTEGER     | 屆次 (適用立法委員等有屆次的選舉)             |
| `updated_at`  | TIMESTAMPTZ | 最後更新時間, 由 trigger 自動維護            |

Trigger:

- `trg_elections_updated_at`: `BEFORE UPDATE`, 執行 `touch_updated_at()`.

---

## source_records

從 source file 匯入的原始記錄, file 裡頭有幾筆, 這邊就應該要有幾筆. 不可修改.

| field              | type        | description                                                              |
|--------------------|-------------|--------------------------------------------------------------------------|
| `source_record_id` | TEXT PK     | 原始記錄唯一識別碼                                                          |
| `election_id`      | TEXT FK     | 所屬選舉 → `elections.election_id`                                         |
| `name`             | VARCHAR(64) | 候選人姓名 (原始 source data)                                               |
| `birthyear`         | INTEGER     | 出生年份 (整數 `yyyy`), NOT NULL; 原始 source data 值, 可能與 `candidates.birthyear` 不一致 |
| `payload`          | JSONB       | source data 完整原始內容                                                   |
| `original_kind`    | VARCHAR(16) | load 時 classify_record 的結果: `auto` / `new` / `manual` (見下方說明)     |

`original_kind` 值說明:

| 值        | 意義                                               |
|-----------|----------------------------------------------------|
| `auto`    | 生日完全吻合, 系統自動匹配                             |
| `new`     | 無任何同名候選人, 系統自動建立新人物                    |
| `manual`  | 存在模糊候選人 (同名但生日不符等), 需人工判斷            |

Index:

- `idx_source_records_election_id` on `(election_id)`.

---

## review_decisions

審核期間的草稿判定. Commit 前必須可恢復, Commit 後寫入 `resolutions`.

| field              | type        | description                                       |
|--------------------|-------------|---------------------------------------------------|
| `source_record_id` | TEXT PK FK  | 1-to-1 對應 `source_records.source_record_id`      |
| `election_id`      | TEXT FK     | 所屬選舉 → `elections.election_id` (denormalized)  |
| `candidate_id`     | VARCHAR(64) FK | 審核人員判定對應的候選人 → `candidates.id` (`ON UPDATE/DELETE CASCADE`) |
| `mode`             | VARCHAR(16) | 判定方式                                           |
| `updated_at`       | TIMESTAMPTZ | 最後修改時間, 由 trigger 自動維護                    |

Index:

- `idx_review_decisions_election_id` on `(election_id)`.

Trigger:

- `trg_review_decisions_updated_at`: `BEFORE UPDATE`, 執行 `touch_updated_at()`.

---

## resolutions

已 commit 的身分判定結果. 為業務資料的 single source of truth.

| field              | type        | description                                       |
|--------------------|-------------|---------------------------------------------------|
| `source_record_id` | TEXT PK FK  | 1-to-1 對應 `source_records.source_record_id`      |
| `election_id`      | TEXT FK     | 所屬選舉 → `elections.election_id` (denormalized)  |
| `candidate_id`     | VARCHAR(64) FK | 對應的候選人 → `candidates.id`, NULL 表示無法判定 (`ON UPDATE/DELETE CASCADE`) |
| `mode`             | VARCHAR(16) | 判定來源: `auto` / `new` / `manual_new` / `manual` (見下方說明) |

`mode` 值說明:

| 值            | 意義                                                    |
|---------------|---------------------------------------------------------|
| `auto`        | 系統自動匹配 (生日完全吻合)                               |
| `new`         | 系統自動建立新人物 (無同名候選人)                          |
| `manual_new`  | 人工判斷後選擇建立新人物 (有模糊候選人但決定不合併)          |
| `manual`      | 人工判斷後選擇合併至現有候選人                             |

Constraint:

- `chk_resolutions_mode`: `mode IN ('auto', 'new', 'manual_new', 'manual')`.

Index:

- `idx_resolutions_election_id` on `(election_id)`.

---

## candidates

候選人身分主檔. 由 `resolutions` commit 後的 build 操作產生並維護.

| field         | type           | description                                                                     |
|---------------|----------------|---------------------------------------------------------------------------------|
| `id`          | VARCHAR(64) PK | 候選人唯一識別碼                                                                  |
| `name`        | VARCHAR(64)    | 候選人姓名, 經 `normalize_candidate_name` 處理: 移除空白與括號, `‧·•．` 轉為 `.` |
| `birthyear`    | INTEGER        | 出生年份, 必填整數 `yyyy` (非 YYYYMMDD); 中選會資料皆含出生年, 實務上無 NULL       |
| `alias_names` | TEXT[]         | 人工維護的別名, 僅供產出 `candidates.yaml` 使用                                   |

Index:

- `idx_candidates_name` on `(name)`.

### id 與生日設計規則

`id` 格式為 `id_<正規化姓名>_<出生年份>`. 設計取捨:

- **生日只取年份**: 原始資料僅提供出生年, 故 `birthyear` 一律填 `yyyy` 整數.
- **同名衝突解法**: 一般情況以出生年區隔 (`id_許淑華_1973`); 同名同年 (罕見) 以人工加尾碼處理 (例如 `id_陳進財_1950a`).

---

## candidate_elections

候選人參選紀錄. 每筆代表一位候選人在一場選舉中的參選資訊.

| field          | type           | description                                        |
|----------------|----------------|----------------------------------------------------|
| `id`           | SERIAL PK      | surrogate key                                      |
| `candidate_id` | VARCHAR(64) FK | 候選人 → `candidates.id` (`ON UPDATE/DELETE CASCADE`)  |
| `year`         | INTEGER        | 選舉年份                                            |
| `type`         | VARCHAR(32)    | 選舉類型                                            |
| `region`       | VARCHAR(32)    | 選區官方全名 (使用臺而非台, 如 `臺北市`)                |
| `party`        | VARCHAR(32)    | 政黨                                               |
| `elected`      | INTEGER        | 是否當選: `1` 當選, `0` 未當選, NULL 不適用            |
| `session`      | INTEGER        | 屆次                                               |
| `ticket`       | INTEGER        | 號次                                               |
| `order_id`     | INTEGER        | 排序用流水號                                        |

Unique constraint: `(candidate_id, year, type, region)`.

`region` 標準值 (官方全名, `臺` 不寫作 `台`):

- 22 縣市: 臺北市、新北市、桃園市、臺中市、臺南市、高雄市、基隆市、新竹市、新竹縣、嘉義市、嘉義縣、宜蘭縣、苗栗縣、彰化縣、南投縣、雲林縣、屏東縣、花蓮縣、臺東縣、澎湖縣、金門縣、連江縣
- 國家元首: `全國`
- 立委: 選舉區名稱; 縣市議員: 縣市名稱 (不含選區)

---

## identity_check_issues

commit 後的候選人合理性檢查清單. 每筆代表一個需要人工確認的疑點.

| field               | type        | description                                  |
|---------------------|-------------|----------------------------------------------|
| `id`                | SERIAL PK   | 流水號                                        |
| `issue_key`         | TEXT UNIQUE | 同一疑點的穩定識別碼                           |
| `candidate_id`      | VARCHAR(64) FK | 被檢查的候選人 → `candidates.id` (`ON UPDATE/DELETE CASCADE`) |
| `issue_type`        | VARCHAR(32) | `same_year_multiple` / `rank_downgrade` / `regional_jump` / `region_zigzag` |
| `severity`          | VARCHAR(16) | `critical` / `warning`                       |
| `summary`           | TEXT        | UI 顯示摘要                                    |
| `source_record_ids` | TEXT[]      | 牽涉的 committed source records               |
| `election_refs`     | JSONB       | UI 顯示用的參選紀錄快照                         |
| `status`            | VARCHAR(16) | `open` / `ignored` / `resolved` / `stale`     |
| `decision_note`     | TEXT        | 保留給人工備註                                 |
| `created_at`        | TIMESTAMPTZ | 建立時間                                      |
| `updated_at`        | TIMESTAMPTZ | 最後更新時間                                   |

Index:

- `idx_identity_check_issues_status` on `(status)`.
- `idx_identity_check_issues_candidate_id` on `(candidate_id)`.

Trigger:

- `trg_identity_check_issues_updated_at`: `BEFORE UPDATE`, 執行 `touch_updated_at()`.

---

## identity_fix_operations

疑似誤合併修正操作紀錄. 用 before / after snapshot 支援追蹤與還原.

| field                     | type        | description                      |
|---------------------------|-------------|----------------------------------|
| `id`                      | SERIAL PK   | 流水號                            |
| `issue_id`                | INTEGER FK  | 來源疑點 → `identity_check_issues.id` |
| `operation`               | VARCHAR(32) | 修正方式                          |
| `source_candidate_id`     | VARCHAR(64) | 原本 candidate id                 |
| `target_candidate_id`     | VARCHAR(64) | 移入或新建 candidate id            |
| `moved_source_record_ids` | TEXT[]      | 本次移動的 committed source records |
| `before_snapshot`         | JSONB       | 套用前候選人參選快照                |
| `after_snapshot`          | JSONB       | 套用後候選人參選快照                |
| `created_at`              | TIMESTAMPTZ | 操作時間                          |

Index:

- `idx_identity_fix_operations_issue_id` on `(issue_id)`.

---

## Functions

| function             | description                                      |
|----------------------|--------------------------------------------------|
| `touch_updated_at()` | 將 `NEW.updated_at` 設為 `CURRENT_TIMESTAMP`, 供 updated_at triggers 共用 |

---

## guide_* 表群 (選舉公報 web 功能)

`guide_*` 表與 identity UI 獨立, 專供選舉公報 web 檢視/後台使用. `candidate_id` / `election_id` 為預留欄位, 本階段不設 FK, 不填值.

### guide_elections

公報對應的選舉清單.

| field            | type        | description                                    |
|------------------|-------------|------------------------------------------------|
| `id`             | TEXT PK     | 公報選舉識別碼                                  |
| `type`           | VARCHAR(32) | 選舉類型                                        |
| `year`           | INTEGER     | 選舉年份                                        |
| `session`        | INTEGER     | 屆次 (可 NULL)                                  |
| `label`          | TEXT        | 顯示名稱 (可 NULL)                              |
| `region`         | VARCHAR(16) | 地區 (縣市長用; 總統為 NULL)                     |
| `source_pdf_path`| TEXT        | 來源 PDF 路徑 (可 NULL)                         |
| `election_id`    | TEXT        | 預留; 不設 FK, 本期不填                          |

---

### guide_candidates

公報內每位候選人 (或配對的正/副總統).

| field               | type        | description                                             |
|---------------------|-------------|---------------------------------------------------------|
| `id`                | SERIAL PK   | surrogate key                                           |
| `guide_election_id` | TEXT FK     | 所屬公報選舉 → `guide_elections.id` (CASCADE, denormalized) |
| `guide_group_id`    | INTEGER FK  | 所屬組 → `guide_groups.id` (CASCADE)                     |
| `role`              | VARCHAR(16) | 角色, 如 `總統` / `副總統` / `市長` / `縣長`, NOT NULL DEFAULT '' |
| `photo_path`        | TEXT        | 照片儲存路徑 (可 NULL)                                   |
| `photo_flagged`     | BOOLEAN     | 照片是否需人工確認, DEFAULT false                         |
| `photo_note`        | TEXT        | 照片備註 (可 NULL)                                       |
| `source_page`       | INTEGER     | 來源 PDF 頁碼 (0-based, 可 NULL)                         |
| `candidate_id`      | VARCHAR(64) | 預留; 不設 FK, 本期不填                                  |
| `order_id`          | INTEGER     | 排序用流水號 (可 NULL)                                   |

號次 (`ticket`) 與政黨 (`party`) 移至 `guide_groups`。

Unique constraint: `(guide_group_id, role)` (以 unique index `uq_guide_candidates_group_role` 實作).

Index: `idx_guide_candidates_election` on `(guide_election_id)`, `idx_guide_candidates_group` on `(guide_group_id)`.

---

### guide_fields

每位候選人的欄位化資料 (姓名、學歷、政見等), 一欄一列.

| field               | type        | description                                          |
|---------------------|-------------|------------------------------------------------------|
| `id`                | SERIAL PK   | surrogate key                                        |
| `guide_candidate_id`| INTEGER FK  | 所屬候選人 → `guide_candidates.id` (CASCADE)          |
| `field_name`        | VARCHAR(32) | 欄位名稱                                              |
| `value`             | TEXT        | 欄位內容 (可 NULL)                                    |
| `grade`             | VARCHAR(16) | 解析信心等級 (可 NULL)                                 |
| `source_crop_path`  | TEXT        | 對應裁圖路徑 (可 NULL)                                 |
| `flagged`           | BOOLEAN     | 是否需人工確認, DEFAULT false                          |
| `flag_note`         | TEXT        | 標記備註 (可 NULL)                                    |
| `update_source`     | VARCHAR(16) | 資料來源: `parse` / `manual` 等, DEFAULT 'parse'      |
| `updated_at`        | TIMESTAMPTZ | 最後更新時間, DEFAULT current_timestamp               |

Unique constraint: `(guide_candidate_id, field_name)`.

Index: `idx_guide_fields_candidate` on `(guide_candidate_id)`.

---

### 每人快照(已移除)

`guide_snapshots` / `guide_snapshot_fields`(iteration 1 的每候選人快照)已由後續 migration DROP,改以組層級快照取代,見下方 `guide_group_snapshots` / `guide_group_snapshot_fields`。

---

### guide_repair_jobs

文字欄位或組共用政見的人工修正任務佇列 (照片不建 job).

| field               | type        | description                                            |
|---------------------|-------------|--------------------------------------------------------|
| `id`                | SERIAL PK   | surrogate key                                          |
| `guide_candidate_id`| INTEGER FK  | 文字欄修復對象 → `guide_candidates.id` (CASCADE, 可 NULL) |
| `guide_group_id`    | INTEGER FK  | 政見修復對象 → `guide_groups.id` (CASCADE, 可 NULL)      |
| `target`            | VARCHAR(32) | 目標欄位名稱;政見填 `政見`                              |
| `status`            | VARCHAR(16) | `queued` / `running` / `done` / `failed`, DEFAULT 'queued' |
| `user_note`         | TEXT        | 人工備註 (可 NULL)                                      |
| `before_value`      | TEXT        | 修正前的值 (可 NULL)                                    |
| `result_value`      | TEXT        | 修正後的值 (可 NULL)                                    |
| `error`             | TEXT        | 錯誤訊息 (可 NULL)                                      |
| `created_at`        | TIMESTAMPTZ | 建立時間, DEFAULT current_timestamp                     |
| `finished_at`       | TIMESTAMPTZ | 完成時間 (可 NULL)                                      |

文字欄 job 填 `guide_candidate_id` + `target=欄名`;政見 job 填 `guide_group_id` + `target='政見'`(二者擇一)。

Index: `idx_guide_repair_jobs_status` on `(status)`, `idx_guide_repair_jobs_cand` on `(guide_candidate_id)`.

---

## iteration 2 變更(組為單位 + 政見)

UI 與版本單位由「候選人」改為「組(號次)」。新增組實體與組共用政見、組層級快照;`guide_candidates` 掛到組(見上方最終定義);汰換每人快照。

### guide_groups — 組(號次)

一個號次一筆。擁有政黨與(關聯的)共用政見、正/副候選人。

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | |
| `guide_election_id` | TEXT FK | → `guide_elections.id` (CASCADE) |
| `ticket` | INTEGER | 號次 |
| `party` | VARCHAR(32) | 政黨(由 `guide_candidates` 上移到此) |
| `order_id` | INTEGER | 排序 |

Unique: `(guide_election_id, ticket)`。

### guide_group_platform — 組共用政見(欄位化)

一組一筆政見工作值(可標記、可 AI 修復)。

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | |
| `guide_group_id` | INTEGER FK UNIQUE | → `guide_groups.id` (CASCADE) |
| `value` | TEXT | 政見目前值 |
| `grade` | VARCHAR(16) | 信心分級 |
| `source_crop_path` | TEXT | 政見合併格切圖路徑 |
| `flagged` | BOOLEAN | 是否標記疑慮 |
| `flag_note` | TEXT | 補充說明 |
| `update_source` | VARCHAR(16) | `parse`/`ai`/`manual` |
| `updated_at` | TIMESTAMPTZ | |

### guide_group_snapshots / guide_group_snapshot_fields — 組層級版本

取代 iteration 1 的每人快照(`guide_snapshots`/`guide_snapshot_fields` 已 DROP)。一次 commit 凍結整組:正、副候選人各欄 + 政見。

`guide_group_snapshots`: `id`, `guide_group_id` FK, `version_no`(UNIQUE with group), `note`, `created_at`。

`guide_group_snapshot_fields`: `id`, `snapshot_id` FK, `scope`(`總統`/`副總統`/`政見`), `field_name`, `value`, `grade`, `source_crop_path`, `flagged`, `flag_note`。Unique `(snapshot_id, scope, field_name)`。

註:`guide_candidates`(移除 party/ticket、掛 `guide_group_id`)與 `guide_repair_jobs`(`guide_candidate_id` 可 NULL、新增 `guide_group_id`)的最終定義見前面各該節。

---

## 手動照片保留(guide_manual_photos)

手動「圈選補照片」的結果獨立保存,重載(`--force`)與重跑解析都不會遺失。

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | |
| `election_id` | TEXT | 公報選舉識別碼(穩定鍵,**刻意不設 FK**,故 `--force` 刪選舉時本表不被 cascade 清掉) |
| `ticket` | INTEGER | 號次 |
| `role` | VARCHAR(16) | 角色(總統/副總統) |
| `path` | TEXT | 手動照片檔路徑(存於 `_out/guide_manual/`,解析器不會覆蓋) |
| `updated_at` | TIMESTAMPTZ | 更新時間 |

Unique: `(election_id, ticket, role)`。

機制:圈選補照片時存到 `_out/guide_manual/{election_id}/ticket{n}_{role}.png` 並 upsert 本表;`load` 完成後以 `guide_apply_manual_photos(election_id)` 依穩定鍵把仍存在的手動照片套回對應候選人的 `guide_candidates.photo_path`。

---

## 公報匯入工作(guide_import_jobs)

匯入公報 PDF 的背景工作狀態。改存 DB(原本只在 web 程序記憶體),使匯入進度可跨頁面查詢:離開匯入頁後仍能在側欄看到「匯入進行中」。**刻意不設 FK** 到 `guide_elections`,匯入失敗或選舉被刪時工作紀錄仍保留供查閱。

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | |
| `pdf_path` | TEXT | 來源公報 PDF 路徑 |
| `pdf_name` | TEXT | 顯示名(PDF stem) |
| `status` | VARCHAR(16) | `queued` / `running` / `done` / `failed`(建立即為 `running`) |
| `message` | TEXT | 目前進度訊息 |
| `done` / `total` | INTEGER | 進度分子/分母(供進度條) |
| `election_id` | TEXT | 完成後產生的公報選舉識別碼 |
| `error` | TEXT | 失敗原因 |
| `created_at` / `updated_at` / `finished_at` | TIMESTAMPTZ | |

Index: `idx_guide_import_jobs_status` on `(status)`。

側欄常駐指示由 `guide_active_import_job()`(取最近一筆 `queued`/`running`)驅動,前端輪詢 `GET /guide/import/active`。
