-- 005_voter_guide.sql — 選舉公報 web 資料(欄位化)。schema-agnostic、冪等。
CREATE TABLE IF NOT EXISTS guide_elections (
    id              TEXT PRIMARY KEY,
    type            VARCHAR(32)  NOT NULL,
    year            INTEGER      NOT NULL,
    session         INTEGER,
    label           TEXT,
    source_pdf_path TEXT,
    election_id     TEXT           -- 預留;本期不設 FK、不填
);

CREATE TABLE IF NOT EXISTS guide_candidates (
    id                SERIAL PRIMARY KEY,
    guide_election_id TEXT NOT NULL REFERENCES guide_elections(id) ON DELETE CASCADE,
    ticket            INTEGER,
    role              VARCHAR(16) NOT NULL DEFAULT '',
    party             VARCHAR(32),
    photo_path        TEXT,
    photo_flagged     BOOLEAN NOT NULL DEFAULT false,
    photo_note        TEXT,
    source_page       INTEGER,
    candidate_id      VARCHAR(64),   -- 預留;本期不設 FK、不填
    order_id          INTEGER,
    UNIQUE (guide_election_id, ticket, role)
);

CREATE TABLE IF NOT EXISTS guide_fields (
    id                 SERIAL PRIMARY KEY,
    guide_candidate_id INTEGER NOT NULL REFERENCES guide_candidates(id) ON DELETE CASCADE,
    field_name         VARCHAR(32) NOT NULL,
    value              TEXT,
    grade              VARCHAR(16),
    source_crop_path   TEXT,
    flagged            BOOLEAN NOT NULL DEFAULT false,
    flag_note          TEXT,
    update_source      VARCHAR(16) NOT NULL DEFAULT 'parse',
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (guide_candidate_id, field_name)
);

CREATE TABLE IF NOT EXISTS guide_snapshots (
    id                 SERIAL PRIMARY KEY,
    guide_candidate_id INTEGER NOT NULL REFERENCES guide_candidates(id) ON DELETE CASCADE,
    version_no         INTEGER NOT NULL,
    note               TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (guide_candidate_id, version_no)
);

CREATE TABLE IF NOT EXISTS guide_snapshot_fields (
    id               SERIAL PRIMARY KEY,
    snapshot_id      INTEGER NOT NULL REFERENCES guide_snapshots(id) ON DELETE CASCADE,
    field_name       VARCHAR(32) NOT NULL,
    value            TEXT,
    grade            VARCHAR(16),
    source_crop_path TEXT,
    flagged          BOOLEAN NOT NULL,
    flag_note        TEXT,
    UNIQUE (snapshot_id, field_name)
);

CREATE TABLE IF NOT EXISTS guide_repair_jobs (
    id                 SERIAL PRIMARY KEY,
    guide_candidate_id INTEGER NOT NULL REFERENCES guide_candidates(id) ON DELETE CASCADE,
    target             VARCHAR(32) NOT NULL,   -- 文字欄名;照片不建 job
    status             VARCHAR(16) NOT NULL DEFAULT 'queued',
    user_note          TEXT,
    before_value       TEXT,
    result_value       TEXT,
    error              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    finished_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_guide_candidates_election ON guide_candidates(guide_election_id);
CREATE INDEX IF NOT EXISTS idx_guide_fields_candidate    ON guide_fields(guide_candidate_id);
CREATE INDEX IF NOT EXISTS idx_guide_repair_jobs_status  ON guide_repair_jobs(status);
CREATE INDEX IF NOT EXISTS idx_guide_repair_jobs_cand    ON guide_repair_jobs(guide_candidate_id);
