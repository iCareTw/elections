BEGIN;

-- 讓所有參照 candidates.id 的業務表在 candidate id 變更/刪除時自動同步.
-- 既有 FK 重建為 ON UPDATE CASCADE ON DELETE CASCADE;
-- 原本無 FK 的 resolutions / review_decisions 補上 FK.
-- 注意: identity_fix_operations 為稽核歷史紀錄, 刻意保留當時的 candidate id, 不加 FK.

-- candidate_elections: 既有 FK 改加 ON UPDATE CASCADE
ALTER TABLE candidate_elections
    DROP CONSTRAINT candidate_elections_candidate_id_fkey;
ALTER TABLE candidate_elections
    ADD CONSTRAINT candidate_elections_candidate_id_fkey
    FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    ON UPDATE CASCADE ON DELETE CASCADE;

-- identity_check_issues: 既有 FK 改加 ON UPDATE CASCADE
ALTER TABLE identity_check_issues
    DROP CONSTRAINT identity_check_issues_candidate_id_fkey;
ALTER TABLE identity_check_issues
    ADD CONSTRAINT identity_check_issues_candidate_id_fkey
    FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    ON UPDATE CASCADE ON DELETE CASCADE;

-- resolutions: 原本無 FK, 補上
ALTER TABLE resolutions
    ADD CONSTRAINT resolutions_candidate_id_fkey
    FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    ON UPDATE CASCADE ON DELETE CASCADE;

-- review_decisions: 原本無 FK, 補上
ALTER TABLE review_decisions
    ADD CONSTRAINT review_decisions_candidate_id_fkey
    FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    ON UPDATE CASCADE ON DELETE CASCADE;

COMMIT;
