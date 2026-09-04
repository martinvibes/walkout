-- ---------------------------------------------------------------------------
-- Statistically significant abandonment cliffs.
-- Baseline is the *median* post-warmup hazard (robust to the cliffs themselves).
-- Significance is a binomial z-test: given `reached` viewers and the baseline
-- exit probability, how surprising is the observed number of exits?
-- Both a lift floor and a z floor must clear, so ordinary noise never gets
-- promoted into a finding the agent then wastes Gemini tokens investigating.
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
        FROM sess GROUP BY b
    ),
    curve AS (
        SELECT
            b * {bucket_sec:UInt32} AS position_sec,
            exits,
            (SELECT n FROM total) - ifNull(sum(exits) OVER (
                ORDER BY b ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS reached,
            exits / nullIf(reached, 0) AS hazard
        FROM buckets
    ),
    baseline AS (
        SELECT quantileExact(0.5)(hazard) AS h0
        FROM curve
        WHERE position_sec >= {warmup_sec:UInt32}   -- the opening drop-off is normal, not a defect
    )
SELECT
    position_sec,
    position_sec + {bucket_sec:UInt32}                          AS position_end_sec,
    formatDateTime(toDateTime(position_sec), '%H:%i:%S')        AS timecode,
    reached,
    exits,
    round(hazard, 5)                                            AS hazard,
    round((SELECT h0 FROM baseline), 5)                         AS baseline_hazard,
    round(hazard / (SELECT h0 FROM baseline), 2)                AS lift,
    round((exits - reached * (SELECT h0 FROM baseline))
        / sqrt(reached * (SELECT h0 FROM baseline)
               * (1 - (SELECT h0 FROM baseline))), 2)           AS z_score,
    -- viewers beyond what the baseline would have cost us at this point
    toUInt32(greatest(exits - reached * (SELECT h0 FROM baseline), 0)) AS excess_exits
FROM curve
WHERE position_sec >= {warmup_sec:UInt32}
  AND hazard / (SELECT h0 FROM baseline) >= {min_lift:Float64}
  AND (exits - reached * (SELECT h0 FROM baseline))
      / sqrt(reached * (SELECT h0 FROM baseline)
             * (1 - (SELECT h0 FROM baseline))) >= {min_z:Float64}
  AND exits >= {min_exits:UInt32}
ORDER BY excess_exits DESC;
