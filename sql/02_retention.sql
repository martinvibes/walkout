-- Walkout analytical core.
-- Each statement below is exposed to the agent as a parameterised tool query.
-- Parameters use ClickHouse native binding so the model never concatenates SQL.

-- ---------------------------------------------------------------------------
-- [retention_curve] Survival curve for a title.
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

-- ---------------------------------------------------------------------------
-- [detect_cliffs] Statistically significant abandonment cliffs.
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

-- ---------------------------------------------------------------------------
-- [segment_cliff] Who actually walked out at this cliff?
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

-- ---------------------------------------------------------------------------
-- [qoe_at_window] The story-vs-technical tiebreaker.
-- If playback was clean through the window, the cliff is editorial.
-- If rebuffering / bitrate collapsed, do NOT recut the scene -- fix delivery.
-- ---------------------------------------------------------------------------
SELECT
    {dim:Identifier}                                              AS cohort,
    count()                                                       AS events,
    round(avg(rebuffer_ms), 1)                                    AS avg_rebuffer_ms,
    round(sum(rebuffer_ms) / (count() * {bucket_sec:UInt32} * 1000.0), 5) AS rebuffer_ratio,
    round(avg(bitrate_kbps), 0)                                   AS avg_bitrate_kbps,
    round(avg(dropped_frames), 1)                                 AS avg_dropped_frames,
    countIf(event_type = 'rebuffer')                              AS rebuffer_events,
    countIf(event_type = 'error')                                 AS error_events,
    topK(3)(cdn_pop)                                              AS top_cdn_pops,
    topK(3)(app_version)                                          AS top_app_versions
FROM walkout.playback_events
WHERE title_id = {title_id:String}
  AND position_sec >= {start_sec:UInt32}
  AND position_sec <  {end_sec:UInt32}
GROUP BY cohort
ORDER BY rebuffer_ratio DESC;

-- ---------------------------------------------------------------------------
-- [qoe_baseline] Same metrics across the whole title, for contrast.
-- A cohort that rebuffers everywhere is a platform problem, not a cliff cause.
-- ---------------------------------------------------------------------------
SELECT
    {dim:Identifier}                                              AS cohort,
    round(avg(rebuffer_ms), 1)                                    AS avg_rebuffer_ms,
    round(avg(bitrate_kbps), 0)                                   AS avg_bitrate_kbps,
    round(countIf(event_type = 'rebuffer') / count(), 5)          AS rebuffer_event_rate
FROM walkout.playback_events
WHERE title_id = {title_id:String}
GROUP BY cohort;
