# 選舉公報 Web — iteration 2:以「組」為單位 + 政見 + 開啟 PDF

日期:2026-07-14
狀態:設計定稿,待轉實作計畫
前身:`docs/superpowers/specs/2026-07-01-voter-guide-web-design.md`(iteration 1,候選人為單位,已完成並 commit 至 `adad5f6`)

## 1. 背景

iteration 1 完成後,實際檢視 113 總統公報介面,提出三項需求變更:

1. 一顆按鈕,點了在瀏覽器**開啟該場公報 PDF**。
2. 總統與副總統有**共用的「政見」欄位**,目前缺,需補上。
3. 呈現時**同一組的總統+副總統一起呈現**(不再各自獨立頁),並把政見整合進這個組視圖。

核心變化:**UI 與版本的單位從「候選人」改為「組(號次)」**。使用者已拍板:版本以整組為單位(一次 commit 凍結該組總統各欄 + 副總統各欄 + 共用政見)。

## 2. 需求與範圍

### 本期做

- 「組」成為業務與版本單位:一個號次 = 一組 = 政黨 + 共用政見 + 正/副兩位候選人。
- 新增**政見**欄位(組層級、共用、欄位化:值/信心/切圖/標記/補充說明;可標記、可 AI 修復)。
- 網頁改為**組視圖**:一頁同時呈現正、副兩欄 + 共用政見;版本 ◀▶、commit、未提交橫幅皆在組層級。
- 新增「📄 開啟公報 PDF」按鈕。
- 解析器輸出政見(geometry 已能定位「政見」欄,見 §5)。

### 不做(維持 iteration 1 的非目標)

- 其他選舉類型的解析器;identity UI 整合;影像歷史版本;通用治理。
- 照片仍為當前單值、手動圈選補正(不變)。

## 3. 資料模型變更

以 `db/006_*.sql` 進行。**目前僅有 demo 資料(`guide_demo` schema),故可直接汰換 iteration 1 的「每人快照」結構,不需保留遷移。**

### 3.1 新增 `guide_groups` — 組(號次)

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | surrogate key |
| `guide_election_id` | TEXT FK | → `guide_elections.id`,ON DELETE CASCADE |
| `ticket` | INTEGER | 號次 |
| `party` | VARCHAR(32) | 政黨(**由候選人上移到組**) |
| `order_id` | INTEGER | 排序 |

Unique:`(guide_election_id, ticket)`。

### 3.2 `guide_candidates` 變更

- **移除** `party`(移到 `guide_groups`)。
- **移除** `ticket`(改由所屬組提供)。
- **新增** `guide_group_id INTEGER FK → guide_groups.id ON DELETE CASCADE`。
- 其餘(`role`、`photo_path`、`photo_flagged`、`photo_note`、`source_page`、`candidate_id`)不變。
- Unique 改為 `(guide_group_id, role)`。

### 3.3 `guide_fields`(候選人文字欄)— 不變

仍為每位候選人的文字欄(姓名/出生年月日/性別/學歷/經歷),`guide_candidate_id` 為鍵。

### 3.4 新增 `guide_group_platform` — 組共用政見(欄位化)

政見為組層級的單一欄位工作值(與 `guide_fields` 同型,但一組一筆)。

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | |
| `guide_group_id` | INTEGER FK | → `guide_groups.id`,ON DELETE CASCADE,UNIQUE |
| `value` | TEXT | 政見目前值 |
| `grade` | VARCHAR(16) | 信心分級 |
| `source_crop_path` | TEXT | 來源切圖(政見合併格) |
| `flagged` | BOOLEAN NOT NULL DEFAULT false | |
| `flag_note` | TEXT | |
| `update_source` | VARCHAR(16) NOT NULL DEFAULT 'parse' | `parse`/`ai`/`manual` |
| `updated_at` | TIMESTAMPTZ NOT NULL DEFAULT current_timestamp | |

### 3.5 版本改為組層級:`guide_group_snapshots` + `guide_group_snapshot_fields`

**汰換** iteration 1 的 `guide_snapshots` / `guide_snapshot_fields`(每人)。

`guide_group_snapshots`

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | |
| `guide_group_id` | INTEGER FK | → `guide_groups.id`,ON DELETE CASCADE |
| `version_no` | INTEGER | 該組版本序號,從 1 遞增 |
| `note` | TEXT | |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT current_timestamp | |

Unique:`(guide_group_id, version_no)`。

`guide_group_snapshot_fields`(凍結整組:兩位候選人各欄 + 政見)

| field | type | description |
|-------|------|-------------|
| `id` | SERIAL PK | |
| `snapshot_id` | INTEGER FK | → `guide_group_snapshots.id`,ON DELETE CASCADE |
| `scope` | VARCHAR(16) | `總統` / `副總統` / `政見`(政見時 role 無關) |
| `field_name` | VARCHAR(32) | 文字欄名;scope=政見 時填 `政見` |
| `value` | TEXT | |
| `grade` | VARCHAR(16) | |
| `source_crop_path` | TEXT | |
| `flagged` | BOOLEAN NOT NULL | |
| `flag_note` | TEXT | |

Unique:`(snapshot_id, scope, field_name)`。

### 3.6 `guide_repair_jobs` 變更

- `target` 仍為欄名;新增可能值 `政見`。
- 需能指向「組的政見」或「某候選人的文字欄」。做法:新增 `guide_group_id INTEGER NULL`,`guide_candidate_id` 改為 NULL 可空;政見 job 填 `guide_group_id`+`target='政見'`,文字欄 job 填 `guide_candidate_id`+`target=欄名`。二者擇一。

## 4. 版本 / commit(組層級)

- **有未提交變更(組)**:該組任一候選人的 `guide_fields` 或該組 `guide_group_platform`,與最後一個組快照的凍結內容(value/flagged/flag_note)不同。照片狀態仍不參與(不變)。
- **Commit(組)**:凍結該組兩位候選人所有 `guide_fields` + 該組政見 → 新 `guide_group_snapshots`(version+1)+ `guide_group_snapshot_fields`。
- **捨棄(組)**:以最後組快照還原兩位候選人的 `guide_fields` 與該組政見。照片不還原。

## 5. 解析器

- geometry 的 `FIELD_HEADERS` 已含 `政見`;pipeline 需將政見納入輸出。政見為組層級的合併格(跨正副兩列,類似「政黨/登記方式」),取一次切圖與值。
- YAML 每個 entry(號次)新增 `政見` 與其 `_verify` grade、以及政見切圖(命名沿用慣例,`field="政見"`)。
- 命名慣例的政見切圖:`crop_filename(..., field="政見")`;因政見屬組層級,`name` 用該組某一固定人(如總統)或改用 `ticket` 段——**採用**:政見切圖檔名以 `ticket` 為主、不綁人名:`_out/parsed/{type}/{session}th_{year}_ticket_{ticket}_政見.png`(load 依此回推)。

## 6. 網頁 / 程式結構

- **新增組視圖路由** `GET /guide/group/{election_id}/{ticket}`(取代以候選人為進入點;候選人 rail 點選導到其所屬組視圖並可高亮該人)。
- 版面:一頁上半並排「總統」「副總統」兩欄面板(各欄可標記/AI修復/手動填值),下半「政見」區塊(可標記/AI修復/手動填值);頂部組層級版本 ◀▶、未提交橫幅、Commit/捨棄。
- **📄 開啟公報 PDF**:新增路由 `GET /guide/election/{election_id}/pdf` 回該場 `source_pdf_path`(限 `_data/` 或既有來源路徑;`FileResponse`,inline 顯示),頁面加按鈕於組視圖或選舉層。
- 照片列與手動圈選補正(iteration 1)不變,置於各候選人欄內。
- AI 修復:文字欄與政見都走 `guide_repair_jobs` 背景 + toast(政見 job 用 `guide_group_id`)。

## 7. 元件邊界(增量)

| 元件 | 變更 |
|------|------|
| 解析器 pipeline | 輸出組層級政見(值 + 切圖) |
| load | 建 `guide_groups`、把候選人掛到組、寫政見、建組 v1 快照(取代每人快照) |
| store 存取層 | 新增組視圖讀取、政見標記/手動/修復、組層級 commit/捨棄/版本;移除每人快照用法 |
| web | 組視圖頁 + PDF 開啟 + 政見互動 |

## 8. 遷移與相容

- `db/006_*.sql`:建 `guide_groups`、`guide_group_platform`、`guide_group_snapshots`、`guide_group_snapshot_fields`;改 `guide_candidates`(移除 party/ticket、加 guide_group_id);改 `guide_repair_jobs`(candidate_id 可空、加 group_id);**drop** `guide_snapshots`、`guide_snapshot_fields`。
- 因無正式資料,採「重建式」migration;demo 資料以 `--force` 重新 load。
- 同步更新 `docs/db-schema.md`。

## 9. 開放待實作細節(非規格缺口)

- 政見切圖若某年份非合併格(未來其他類型)之處理,屆時再議;本期以總統合併格為準。
- PDF 於瀏覽器 inline 顯示的 header 設定屬實作細節。
