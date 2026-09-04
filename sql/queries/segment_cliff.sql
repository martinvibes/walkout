-- ---------------------------------------------------------------------------
-- Who actually walked out at this cliff?
-- Compares each cohort's hazard inside the window against that same cohort's
-- own baseline elsewhere in the title -- so a cohort that always churns hard
-- doesn't get blamed for a cliff it didn't cause.
-- ---------------------------------------------------------------------------
WITH
    sess AS (
        SELECT
            session_id,
            max(position_sec)                       AS last_pos,
            max(event_type = 'complete')            AS completed,
            any({dim:Identifier})                   AS cohort
        FROM walkout.playback_events
        WHERE title_id = {title_id:String}
        GROUP BY session_id
    )
SELECT
    cohort,
    countIf(last_pos >= {start_sec:UInt32})                                   AS reached,
    countIf(NOT completed AND last_pos >= {start_sec:UInt32}
                            AND last_pos <  {end_sec:UInt32})                AS exits_in_window,
    round(exits_in_window / nullIf(reached, 0), 5)                            AS hazard_in_window,
    countIf(last_pos >= {end_sec:UInt32})                                     AS survived,
    round(countIf(NOT completed AND last_pos < {start_sec:UInt32}) / count(), 5) AS share_lost_before,
    round(count() / (SELECT count() FROM sess), 4)                            AS cohort_share
FROM sess
GROUP BY cohort
HAVING reached >= {min_cohort:UInt32}
ORDER BY hazard_in_window DESC;
