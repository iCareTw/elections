-- 008_guide_import_jobs.sql — 公報匯入工作佇列。
-- 目的:匯入狀態改存 DB(原本只存 web 程序記憶體),使匯入進度可跨頁面查詢、
--       離開匯入頁後仍能在側欄看到進行中,不再「不知道能不能離開」。
-- 刻意「不」設 FK 到 guide_elections:匯入失敗或選舉被刪時,工作紀錄仍保留供查閱。

BEGIN;

CREATE TABLE IF NOT EXISTS guide_import_jobs (
    id           SERIAL PRIMARY KEY,
    pdf_path     TEXT NOT NULL,
    pdf_name     TEXT,
    status       VARCHAR(16) NOT NULL DEFAULT 'queued',  -- queued/running/done/failed
    message      TEXT,
    done         INTEGER NOT NULL DEFAULT 0,
    total        INTEGER NOT NULL DEFAULT 0,
    election_id  TEXT,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    finished_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_guide_import_jobs_status ON guide_import_jobs(status);

COMMIT;
