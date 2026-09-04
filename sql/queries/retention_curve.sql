-- ---------------------------------------------------------------------------
-- Survival curve for a title.
-- hazard = fraction of viewers still watching at this bucket who leave during it.
-- Hazard, not raw retention, is what makes a cliff visible: a 5% drop late in a
-- title where only 20% remain is a far bigger event than a 5% drop at minute one.
-- ---------------------------------------------------------------------------
WITH
    sess AS (
        -- A session that reached the credits is a *censored* observation, not a
        -- walk-out. Counting completions as exits would report a 100% cliff at
        -- the end of every title.
        SELECT
            session_id,
            max(position_sec)                       AS last_pos,
            max(event_type = 'complete')            AS completed
        FROM walkout.playback_events
        WHERE title_id = {title_id:String}
        GROUP BY session_id
    ),
    total AS (SELECT count() AS n FROM sess),
    buckets AS (
        SELECT intDiv(last_pos, {bucket_sec:UInt32}) AS b, countIf(NOT completed) AS exits
        FROM sess
        GROUP BY b
    )
SELECT
    b * {bucket_sec:UInt32}                                        AS position_sec,
    (SELECT n FROM total) - ifNull(sum(exits) OVER (
        ORDER BY b ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS reached,
    exits,
    round(exits / nullIf(reached, 0), 5)                           AS hazard,
    round(reached / (SELECT n FROM total), 5)                      AS retention
FROM buckets
ORDER BY b;
