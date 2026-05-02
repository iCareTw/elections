# DB Schema

Schema name: `elections`. 此文件記錄所有 migration 套用後的最終狀態.

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

---

## source_records

從 source file 匯入的原始記錄, file 裡頭有幾筆, 這邊就應該要有幾筆. 不可修改.

| field              | type        | description                                                              |
|--------------------|-------------|--------------------------------------------------------------------------|
| `source_record_id` | TEXT PK     | 原始記錄唯一識別碼                                                          |
| `election_id`      | TEXT FK     | 所屬選舉 → `elections.election_id`                                         |
| `name`             | VARCHAR(64) | 候選人姓名 (原始 source data)                                               |
| `birthday`         | INTEGER     | 生日, 原始 source data 值, 可能與 `candidates.birthday` 不一致               |
| `payload`          | JSONB       | source data 完整原始內容                                                   |
| `original_kind`    | VARCHAR(16) | load 時 classify_record 的結果: `auto` / `new` / `manual` (見下方說明)     |

`original_kind` 值說明:

| 值        | 意義                                               |
|-----------|----------------------------------------------------|
| `auto`    | 生日完全吻合, 系統自動匹配                             |
| `new`     | 無任何同名候選人, 系統自動建立新人物                    |
| `manual`  | 存在模糊候選人 (同名但生日不符等), 需人工判斷            |

---

## review_decisions

審核期間的草稿判定. Commit 前必須可恢復, Commit 後寫入 `resolutions`.

| field              | type        | description                                       |
|--------------------|-------------|---------------------------------------------------|
| `source_record_id` | TEXT PK FK  | 1-to-1 對應 `source_records.source_record_id`      |
| `election_id`      | TEXT FK     | 所屬選舉 → `elections.election_id` (denormalized)  |
| `candidate_id`     | VARCHAR(64) | 審核人員判定對應的候選人 ID                           |
| `mode`             | VARCHAR(16) | 判定方式                                           |
| `updated_at`       | TIMESTAMPTZ | 最後修改時間, 由 trigger 自動維護                    |

---

## resolutions

已 commit 的身分判定結果. 為業務資料的 single source of truth.

| field              | type        | description                                       |
|--------------------|-------------|---------------------------------------------------|
| `source_record_id` | TEXT PK FK  | 1-to-1 對應 `source_records.source_record_id`      |
| `election_id`      | TEXT FK     | 所屬選舉 → `elections.election_id` (denormalized)  |
| `candidate_id`     | VARCHAR(64) | 對應的候選人 ID, NULL 表示無法判定                    |
| `mode`             | VARCHAR(16) | 判定來源: `auto` / `new` / `manual_new` / `manual` (見下方說明) |

`mode` 值說明:

| 值            | 意義                                                    |
|---------------|---------------------------------------------------------|
| `auto`        | 系統自動匹配 (生日完全吻合)                               |
| `new`         | 系統自動建立新人物 (無同名候選人)                          |
| `manual_new`  | 人工判斷後選擇建立新人物 (有模糊候選人但決定不合併)          |
| `manual`      | 人工判斷後選擇合併至現有候選人                             |

---

## candidates

候選人身分主檔. 由 `resolutions` commit 後的 build 操作產生並維護.

| field      | type           | description         |
|------------|----------------|---------------------|
| `id`       | VARCHAR(64) PK | 候選人唯一識別碼       |
| `name`     | VARCHAR(64)    | 候選人姓名            |
| `birthday` | INTEGER        | 生日, YYYYMMDD 格式   |

---

## candidate_elections

候選人參選紀錄. 每筆代表一位候選人在一場選舉中的參選資訊.

| field          | type           | description                                        |
|----------------|----------------|----------------------------------------------------|
| `id`           | SERIAL PK      | surrogate key                                      |
| `candidate_id` | VARCHAR(64) FK | 候選人 → `candidates.id`                            |
| `year`         | INTEGER        | 選舉年份                                            |
| `type`         | VARCHAR(32)    | 選舉類型                                            |
| `region`       | VARCHAR(32)    | 選區官方全名 (使用臺而非台, 如 `臺北市`)                |
| `party`        | VARCHAR(32)    | 政黨                                               |
| `elected`      | INTEGER        | 是否當選: `1` 當選, `0` 未當選, NULL 不適用            |
| `session`      | INTEGER        | 屆次                                               |
| `ticket`       | INTEGER        | 號次                                               |
| `order_id`     | INTEGER        | 排序用流水號                                        |

Unique constraint: `(candidate_id, year, type, region)`.
