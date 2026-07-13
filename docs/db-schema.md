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
| `source_pdf_path`| TEXT        | 來源 PDF 路徑 (可 NULL)                         |
| `election_id`    | TEXT        | 預留; 不設 FK, 本期不填                          |

---

### guide_candidates

公報內每位候選人 (或配對的正/副總統).

| field               | type        | description                                             |
|---------------------|-------------|---------------------------------------------------------|
| `id`                | SERIAL PK   | surrogate key                                           |
| `guide_election_id` | TEXT FK     | 所屬公報選舉 → `guide_elections.id` (CASCADE)            |
| `ticket`            | INTEGER     | 號次 (可 NULL)                                          |
| `role`              | VARCHAR(16) | 角色, 如 `president` / `vp` / 空字串, NOT NULL DEFAULT '' |
| `party`             | VARCHAR(32) | 政黨 (可 NULL)                                          |
| `photo_path`        | TEXT        | 照片儲存路徑 (可 NULL)                                   |
| `photo_flagged`     | BOOLEAN     | 照片是否需人工確認, DEFAULT false                         |
| `photo_note`        | TEXT        | 照片備註 (可 NULL)                                       |
| `source_page`       | INTEGER     | 來源 PDF 頁碼 (可 NULL)                                  |
| `candidate_id`      | VARCHAR(64) | 預留; 不設 FK, 本期不填                                  |
| `order_id`          | INTEGER     | 排序用流水號 (可 NULL)                                   |

Unique constraint: `(guide_election_id, ticket, role)`.

Index: `idx_guide_candidates_election` on `(guide_election_id)`.

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

### guide_snapshots

候選人欄位的版本快照, 供稽核與回復.

| field               | type        | description                                      |
|---------------------|-------------|--------------------------------------------------|
| `id`                | SERIAL PK   | surrogate key                                    |
| `guide_candidate_id`| INTEGER FK  | 所屬候選人 → `guide_candidates.id` (CASCADE)      |
| `version_no`        | INTEGER     | 版本號                                            |
| `note`              | TEXT        | 版本備註 (可 NULL)                                 |
| `created_at`        | TIMESTAMPTZ | 建立時間, DEFAULT current_timestamp               |

Unique constraint: `(guide_candidate_id, version_no)`.

---

### guide_snapshot_fields

快照內各欄位的值.

| field              | type        | description                                 |
|--------------------|-------------|---------------------------------------------|
| `id`               | SERIAL PK   | surrogate key                               |
| `snapshot_id`      | INTEGER FK  | 所屬快照 → `guide_snapshots.id` (CASCADE)    |
| `field_name`       | VARCHAR(32) | 欄位名稱                                     |
| `value`            | TEXT        | 欄位內容 (可 NULL)                            |
| `grade`            | VARCHAR(16) | 解析信心等級 (可 NULL)                         |
| `source_crop_path` | TEXT        | 對應裁圖路徑 (可 NULL)                         |
| `flagged`          | BOOLEAN     | 是否標記 (NOT NULL)                           |
| `flag_note`        | TEXT        | 標記備註 (可 NULL)                            |

Unique constraint: `(snapshot_id, field_name)`.

---

### guide_repair_jobs

文字欄位人工修正任務佇列 (照片不建 job).

| field               | type        | description                                            |
|---------------------|-------------|--------------------------------------------------------|
| `id`                | SERIAL PK   | surrogate key                                          |
| `guide_candidate_id`| INTEGER FK  | 所屬候選人 → `guide_candidates.id` (CASCADE)            |
| `target`            | VARCHAR(32) | 目標欄位名稱                                            |
| `status`            | VARCHAR(16) | `queued` / `done` / `error` 等, DEFAULT 'queued'       |
| `user_note`         | TEXT        | 人工備註 (可 NULL)                                      |
| `before_value`      | TEXT        | 修正前的值 (可 NULL)                                    |
| `result_value`      | TEXT        | 修正後的值 (可 NULL)                                    |
| `error`             | TEXT        | 錯誤訊息 (可 NULL)                                      |
| `created_at`        | TIMESTAMPTZ | 建立時間, DEFAULT current_timestamp                     |
| `finished_at`       | TIMESTAMPTZ | 完成時間 (可 NULL)                                      |

Index: `idx_guide_repair_jobs_status` on `(status)`.
Index: `idx_guide_repair_jobs_cand` on `(guide_candidate_id)`.

---

## iteration 2 變更(組為單位 + 政見,`db/006_*.sql`)

UI 與版本單位由「候選人」改為「組(號次)」。新增組實體與組共用政見、組層級快照;`guide_candidates` 掛到組;汰換每人快照。

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

### guide_candidates 變更

- 移除 `party`(移到 `guide_groups`)、移除 `ticket`(由組提供)。
- 新增 `guide_group_id INTEGER FK → guide_groups.id` (CASCADE)。
- Unique 改為 `(guide_group_id, role)`(以 unique index `uq_guide_candidates_group_role` 實作)。

### guide_repair_jobs 變更

- `guide_candidate_id` 改為可 NULL;新增 `guide_group_id INTEGER NULL FK`。
- 政見修復 job 填 `guide_group_id` + `target='政見'`;文字欄 job 填 `guide_candidate_id` + `target=欄名`。
