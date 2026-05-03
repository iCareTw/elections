BEGIN;

CREATE TABLE elections (
    election_id TEXT        PRIMARY KEY,
    type        VARCHAR(32) NOT NULL,
    label       TEXT        NOT NULL,
    path        TEXT        NOT NULL,
    year        INTEGER,
    session     INTEGER,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE FUNCTION touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_elections_updated_at
BEFORE UPDATE ON elections
FOR EACH ROW
EXECUTE FUNCTION touch_updated_at();

CREATE TABLE source_records (
    source_record_id TEXT        PRIMARY KEY,
    election_id      TEXT        NOT NULL REFERENCES elections(election_id) ON DELETE CASCADE,
    name             VARCHAR(64) NOT NULL,
    birthday         INTEGER,
    payload          JSONB       NOT NULL,
    original_kind    VARCHAR(16) NOT NULL DEFAULT 'unknown'
);

CREATE INDEX idx_source_records_election_id
    ON source_records (election_id);

CREATE TABLE review_decisions (
    source_record_id TEXT        PRIMARY KEY REFERENCES source_records(source_record_id) ON DELETE CASCADE,
    election_id      TEXT        NOT NULL REFERENCES elections(election_id) ON DELETE CASCADE,
    candidate_id     VARCHAR(64) NOT NULL,
    mode             VARCHAR(16) NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_review_decisions_election_id
    ON review_decisions (election_id);

CREATE TRIGGER trg_review_decisions_updated_at
BEFORE UPDATE ON review_decisions
FOR EACH ROW
EXECUTE FUNCTION touch_updated_at();

CREATE TABLE resolutions (
    source_record_id TEXT        PRIMARY KEY REFERENCES source_records(source_record_id) ON DELETE CASCADE,
    election_id      TEXT        NOT NULL REFERENCES elections(election_id) ON DELETE CASCADE,
    candidate_id     VARCHAR(64),
    mode             VARCHAR(16) NOT NULL,
    CONSTRAINT chk_resolutions_mode CHECK (mode IN ('auto', 'new', 'manual_new', 'manual'))
);

CREATE INDEX idx_resolutions_election_id
    ON resolutions (election_id);

CREATE TABLE candidates (
    id       VARCHAR(64) PRIMARY KEY,
    name     VARCHAR(64) NOT NULL,
    birthday INTEGER
);

CREATE INDEX idx_candidates_name
    ON candidates (name);

CREATE TABLE candidate_elections (
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

COMMIT;
