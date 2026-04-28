-- 選舉檔案清單
CREATE TABLE IF NOT EXISTS elections (
    election_id TEXT        PRIMARY KEY,
    type        VARCHAR(32) NOT NULL,
    label       TEXT        NOT NULL,
    path        TEXT        NOT NULL,
    year        INTEGER,
    session     INTEGER,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE elections
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE OR REPLACE FUNCTION touch_elections_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_elections_updated_at ON elections;
CREATE TRIGGER trg_elections_updated_at
BEFORE UPDATE ON elections
FOR EACH ROW
EXECUTE FUNCTION touch_elections_updated_at();

-- 從 source data 匯入的原始資料 (raw decision log)
CREATE TABLE IF NOT EXISTS source_records (
    source_record_id TEXT        PRIMARY KEY,
    election_id      TEXT        NOT NULL REFERENCES elections(election_id) ON DELETE CASCADE,
    name             VARCHAR(64) NOT NULL,
    birthday         INTEGER,
    payload          JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_records_election_id
    ON source_records (election_id);

-- 審核期間的草稿判定；Commit 前也必須可恢復
CREATE TABLE IF NOT EXISTS review_decisions (
    source_record_id TEXT        PRIMARY KEY REFERENCES source_records(source_record_id) ON DELETE CASCADE,
    election_id      TEXT        NOT NULL    REFERENCES elections(election_id) ON DELETE CASCADE,
    candidate_id     VARCHAR(64) NOT NULL,
    mode             VARCHAR(16) NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_review_decisions_election_id
    ON review_decisions (election_id);

-- 身分判定結果 (raw decision log)
CREATE TABLE IF NOT EXISTS resolutions (
    source_record_id TEXT        PRIMARY KEY REFERENCES source_records(source_record_id) ON DELETE CASCADE,
    election_id      TEXT        NOT NULL    REFERENCES elections(election_id) ON DELETE CASCADE,
    candidate_id     VARCHAR(64),
    mode             VARCHAR(16) NOT NULL
);
-- mode: auto / new / manual

-- 候選人身分 (業務資料)
CREATE TABLE IF NOT EXISTS candidates (
    id       VARCHAR(64) PRIMARY KEY,
    name     VARCHAR(64) NOT NULL,
    birthday INTEGER
);

CREATE INDEX IF NOT EXISTS idx_candidates_name ON candidates (name);

-- 候選人參選紀錄 (業務資料)
CREATE TABLE IF NOT EXISTS candidate_elections (
    id           SERIAL      PRIMARY KEY,
    candidate_id VARCHAR(64) NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    year         INTEGER     NOT NULL,
    type         VARCHAR(32) NOT NULL,
    region       VARCHAR(32) NOT NULL,
    party        VARCHAR(32),
    elected      INTEGER,
    session      INTEGER,
    ticket       INTEGER,
    order_id     INTEGER,
    UNIQUE (candidate_id, year, type, region)
);

CREATE INDEX IF NOT EXISTS idx_candidate_elections_candidate_id
    ON candidate_elections (candidate_id);
