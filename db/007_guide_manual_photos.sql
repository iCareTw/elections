-- 007_guide_manual_photos.sql — 手動更正的照片,獨立於解析產物,重載/重解析都保留。
-- 刻意「不」設 FK 到 guide_elections/guide_groups:使 --force 刪除選舉時本表不被 cascade
-- 清掉,重新載入後可依穩定鍵(選舉+號次+角色)把手動照片套回。schema-agnostic、冪等。
CREATE TABLE IF NOT EXISTS guide_manual_photos (
    id          SERIAL PRIMARY KEY,
    election_id TEXT        NOT NULL,
    ticket      INTEGER     NOT NULL,
    role        VARCHAR(16) NOT NULL,
    path        TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (election_id, ticket, role)
);
