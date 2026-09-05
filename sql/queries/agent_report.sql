-- ---------------------------------------------------------------------------
-- The newest agent report for a title.
-- FINAL because ReplacingMergeTree collapses duplicates in the background and
-- a report written seconds ago has not been merged yet.
-- ---------------------------------------------------------------------------
SELECT
    title_id,
    model,
    report,
    trace,
    complete,
    duration_ms,
    toString(created_at) AS created_at
FROM walkout.agent_reports FINAL
WHERE title_id = {title_id:String}
ORDER BY created_at DESC
LIMIT 1;
