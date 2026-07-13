-- 006_voter_guide_groups.sql — iteration 2:以「組」為單位 + 政見 + 組層級版本。
-- schema-agnostic、冪等。汰換 iteration 1 的每人快照結構(僅 demo 資料)。

-- 1) 組(號次)
CREATE TABLE IF NOT EXISTS guide_groups (
    id                SERIAL PRIMARY KEY,
    guide_election_id TEXT NOT NULL REFERENCES guide_elections(id) ON DELETE CASCADE,
    ticket            INTEGER,
    party             VARCHAR(32),
    order_id          INTEGER,
    UNIQUE (guide_election_id, ticket)
);

-- 2) 組共用政見(欄位化)
CREATE TABLE IF NOT EXISTS guide_group_platform (
    id               SERIAL PRIMARY KEY,
    guide_group_id   INTEGER NOT NULL UNIQUE REFERENCES guide_groups(id) ON DELETE CASCADE,
    value            TEXT,
    grade            VARCHAR(16),
    source_crop_path TEXT,
    flagged          BOOLEAN NOT NULL DEFAULT false,
    flag_note        TEXT,
    update_source    VARCHAR(16) NOT NULL DEFAULT 'parse',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

-- 3) 組層級快照
CREATE TABLE IF NOT EXISTS guide_group_snapshots (
    id             SERIAL PRIMARY KEY,
    guide_group_id INTEGER NOT NULL REFERENCES guide_groups(id) ON DELETE CASCADE,
    version_no     INTEGER NOT NULL,
    note           TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (guide_group_id, version_no)
);

CREATE TABLE IF NOT EXISTS guide_group_snapshot_fields (
    id               SERIAL PRIMARY KEY,
    snapshot_id      INTEGER NOT NULL REFERENCES guide_group_snapshots(id) ON DELETE CASCADE,
    scope            VARCHAR(16) NOT NULL,   -- 總統 / 副總統 / 政見
    field_name       VARCHAR(32) NOT NULL,
    value            TEXT,
    grade            VARCHAR(16),
    source_crop_path TEXT,
    flagged          BOOLEAN NOT NULL,
    flag_note        TEXT,
    UNIQUE (snapshot_id, scope, field_name)
);

-- 4) guide_candidates 掛到組;移除 party/ticket
ALTER TABLE guide_candidates
    DROP CONSTRAINT IF EXISTS guide_candidates_guide_election_id_ticket_role_key;
ALTER TABLE guide_candidates
    ADD COLUMN IF NOT EXISTS guide_group_id INTEGER REFERENCES guide_groups(id) ON DELETE CASCADE;
ALTER TABLE guide_candidates DROP COLUMN IF EXISTS party;
ALTER TABLE guide_candidates DROP COLUMN IF EXISTS ticket;
CREATE UNIQUE INDEX IF NOT EXISTS uq_guide_candidates_group_role
    ON guide_candidates(guide_group_id, role);

-- 5) guide_repair_jobs 相容組政見:candidate_id 可空、加 group_id
ALTER TABLE guide_repair_jobs ALTER COLUMN guide_candidate_id DROP NOT NULL;
ALTER TABLE guide_repair_jobs
    ADD COLUMN IF NOT EXISTS guide_group_id INTEGER REFERENCES guide_groups(id) ON DELETE CASCADE;

-- 6) 汰換每人快照
DROP TABLE IF EXISTS guide_snapshot_fields;
DROP TABLE IF EXISTS guide_snapshots;

-- 7) index
CREATE INDEX IF NOT EXISTS idx_guide_groups_election ON guide_groups(guide_election_id);
CREATE INDEX IF NOT EXISTS idx_guide_candidates_group ON guide_candidates(guide_group_id);
CREATE INDEX IF NOT EXISTS idx_guide_group_snapshots_group ON guide_group_snapshots(guide_group_id);
