BEGIN;

-- 003 給 review_decisions.candidate_id 補了指向 candidates 的 FK, 但這張表是 commit 前的
-- 暫存區: 身分判定結果若是「新人物」, 該 candidate id 要等 commit_election 才會寫進
-- candidates, 因此匯入當下必然違反 FK, 整批決策被 rollback, 每筆記錄都變成待審且
-- 找不到可合併對象. 這裡把該 FK 移除, review_decisions 存的是「提議的 candidate id」.
ALTER TABLE review_decisions
    DROP CONSTRAINT IF EXISTS review_decisions_candidate_id_fkey;

-- 003 只手動套用在正式 schema, 測試 schema 沒有 resolutions 的 FK, 導致
-- commit 時的寫入順序問題測不出來. 這裡以冪等方式補上, 讓兩邊 schema 一致.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'resolutions'::regclass
          AND conname  = 'resolutions_candidate_id_fkey'
    ) THEN
        ALTER TABLE resolutions
            ADD CONSTRAINT resolutions_candidate_id_fkey
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
            ON UPDATE CASCADE ON DELETE CASCADE;
    END IF;
END $$;

COMMIT;
