# 選舉公報 Web iteration 2(組視圖 + 政見 + PDF)Implementation Plan

**Goal:** 把公報 web 從「候選人為單位」改為「組為單位」:同組正副合併呈現、新增組共用政見、版本/commit 改組層級、加開啟公報 PDF 按鈕。

**Architecture:** 新增 `guide_groups` 與組層級政見/快照;`guide_candidates` 掛到組(移除 party/ticket)。解析器輸出政見。組視圖頁取代候選人進入點。inline 開發,每 phase 跑測試,完工派 verifier 驗收。

**Spec:** `docs/superpowers/specs/2026-07-14-voter-guide-group-view-design.md`
**前身:** iteration 1 已完成於 `adad5f6`。

通用:Python 用 `uv run`;DB 測試無連線則 skip;commit 訊息末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`;migration 下一號為 `006`。

---

## Phase G1 — Schema 006(組結構)
- [ ] `db/006_voter_guide_groups.sql`:
  - 建 `guide_groups`(id, guide_election_id FK, ticket, party, order_id;UNIQUE(election_id,ticket))
  - 建 `guide_group_platform`(id, guide_group_id FK UNIQUE, value, grade, source_crop_path, flagged, flag_note, update_source, updated_at)
  - 建 `guide_group_snapshots`(id, guide_group_id FK, version_no, note, created_at;UNIQUE(group_id,version_no))
  - 建 `guide_group_snapshot_fields`(id, snapshot_id FK, scope, field_name, value, grade, source_crop_path, flagged, flag_note;UNIQUE(snapshot_id,scope,field_name))
  - 改 `guide_candidates`:DROP party、DROP ticket、ADD guide_group_id FK;調整 unique 為 (guide_group_id, role)
  - 改 `guide_repair_jobs`:guide_candidate_id 改可空、ADD guide_group_id INTEGER NULL
  - DROP `guide_snapshots`、`guide_snapshot_fields`
  - index:group_platform(group_id)、group_snapshots(group_id)
- [ ] 掛入 `store.init_schema` 的 ddl_files(006)
- [ ] `tests/integration/test_guide_schema.py`:更新斷言(新表在、舊每人快照表不在、candidates 無 party 欄)
- [ ] 更新 `docs/db-schema.md`
- [ ] commit `feat(guide): 006 組結構 schema`

## Phase G2 — 解析器輸出政見
- [ ] `crop_filename` 政見特例:`field="政見"` 時檔名不綁人名,用 `..._ticket_{ticket}_政見.png`(改 `crop_filename` 或在 pipeline 呼叫端處理)
- [ ] pipeline:每組取政見(組層級合併格,類似 `_verify_party` 的跨列處理),值 + grade + 切圖,寫入 entry `政見` / `_verify['政見']`
- [ ] 測試:`test_guide_naming.py` 加政見切圖檔名 + parse_pdf entry 含 `政見`(用本機 PDF,skip if absent)
- [ ] commit `feat(guide): parser 輸出組共用政見`

## Phase G3 — Load 改組結構
- [ ] `guide_load`:每 entry 建 `guide_groups`(party、ticket)→ 候選人掛 guide_group_id(不再寫 party/ticket)→ 政見寫 `guide_group_platform`(切圖 field=政見 回推)→ 建**組** v1 snapshot(凍結正副各欄 + 政見)
- [ ] store 低階方法調整:guide_insert_group、candidate 改接 group_id、guide_upsert_platform、guide_create_group_snapshot、guide_insert_group_snapshot_field;移除每人快照寫入
- [ ] `test_guide_load.py`:改為驗組(groups=3、candidates 掛組、政見寫入、組 v1 快照含政見 + 正副欄)
- [ ] commit `feat(guide): load 改組結構並寫政見`

## Phase G4 — Store 組存取層
- [ ] `guide_group_view(election_id, ticket)` → `{group:{id,ticket,party,election_id,election_label}, president:{candidate+fields}, vice:{candidate+fields}, platform:{value,grade,source_crop_path,flagged,flag_note,can_ai_repair}, has_uncommitted, latest_version}`
- [ ] 政見:`guide_flag_platform`/`guide_unflag_platform`/`guide_set_platform_value`/`guide_platform_ref`
- [ ] 組版本:`guide_group_commit`/`guide_group_discard`/`guide_group_snapshot_view(group_id, version_no)`;has_uncommitted 比對組快照(含政見),照片不參與
- [ ] `guide_candidates_of` 調整回傳(附 group/ticket/party)供 rail
- [ ] `test_guide_store.py`:改組層級斷言(組視圖、政見標記/手動、組 commit→v2/捨棄、版本邊界)
- [ ] commit `feat(guide): store 組視圖與組層級版本`

## Phase G5 — 文字欄與政見 AI 修復(組相容)
- [ ] `guide_repair`:支援政見 job(target='政見' + group_id)→ 讀 `guide_group_platform.source_crop_path` → `transcribe_image` → 更新 platform
- [ ] store repair job 方法:相容 candidate 與 group 兩種來源
- [ ] `test_guide_repair.py`:加政見修復案例(含缺圖失敗)
- [ ] commit `feat(guide): 政見 AI 修復`

## Phase G6 — Web 組視圖 + PDF + 政見互動
- [ ] 路由 `GET /guide/group/{election_id}/{ticket}` 渲染組視圖(正副並排 + 政見);候選人 rail 連到組視圖
- [ ] `GET /guide/election/{election_id}/pdf` → FileResponse(source_pdf_path,限來源路徑),頁面加「📄 開啟公報 PDF」
- [ ] 政見區塊:標記/AI修復/手動填值(重用欄位面板樣式);組層級 Commit/捨棄/版本 ◀▶/未提交橫幅
- [ ] 舊 `GET /guide/candidate/{id}` 導向所屬組視圖(或移除,擇一;保留候選人層 POST 動作供欄位操作)
- [ ] `test_guide_routes.py`:組視圖 200 含正副+政見、PDF 路由回檔且拒絕越界、政見標記/修復觸發、組 commit/版本
- [ ] commit `feat(guide): web 組視圖、政見互動與開啟 PDF`

## 完成準則
- 全 guide 測試綠;`--force` 重 load 113 後,組視圖同頁看到正副 + 政見、可標記/AI修復/手動、組層級 commit/版本、開啟 PDF。
- `docs/db-schema.md` 同步。
- 派 `verifier` 做 fresh-context 驗收。
