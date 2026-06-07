BEGIN;

ALTER TABLE elections.identity_check_issues
    DROP CONSTRAINT chk_identity_check_issue_type;

ALTER TABLE elections.identity_check_issues
    ADD CONSTRAINT chk_identity_check_issue_type CHECK (
        issue_type IN ('same_year_multiple', 'rank_downgrade', 'regional_jump', 'region_zigzag')
    );

COMMIT;
