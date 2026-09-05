-- ---------------------------------------------------------------------------
-- Who walked out at this cliff -- every dimension in one pass.
--
-- The per-dimension version of this query was correct and far too slow: nine
-- dimensions meant nine scans of the same sessions, and three cliffs meant
-- twenty-seven. One aggregation builds the session facts, and an ARRAY JOIN
-- fans each session out into one row per dimension, so the table is read once.
--
-- The dimension list is substituted from SEGMENT_EXPRESSIONS in Python rather
-- than written out here, so the allow-list stays the single source of truth.
-- ---------------------------------------------------------------------------
WITH
    sess AS (
        SELECT
            session_id,
            max(position_sec)               AS last_pos,
            max(event_type = 'complete')    AS completed,
            any(device)                     AS device,
            any(platform)                   AS platform,
            any(region)                     AS region,
            any(app_version)                AS app_version,
            any(cdn_pop)                    AS cdn_pop,
            any(subtitle_lang)              AS subtitle_lang,
            any(locale_lang)                AS locale_lang,
            any(audio_lang)                 AS audio_lang,
            any(is_first_time)              AS is_first_time
        FROM walkout.playback_events
        WHERE title_id = {title_id:String}
        GROUP BY session_id
    ),
    tagged AS (
        SELECT
            last_pos,
            completed,
            arrayJoin([$DIMS$]) AS pair
        FROM sess
    )
SELECT
    pair.1                                                                    AS dimension,
    pair.2                                                                    AS cohort,
    countIf(last_pos >= {start_sec:UInt32})                                   AS reached,
    countIf(NOT completed AND last_pos >= {start_sec:UInt32}
                            AND last_pos <  {end_sec:UInt32})                 AS exits_in_window,
    round(exits_in_window / nullIf(reached, 0), 5)                            AS hazard_in_window,
    countIf(last_pos >= {end_sec:UInt32})                                     AS survived,
    round(countIf(NOT completed AND last_pos < {start_sec:UInt32}) / count(), 5) AS share_lost_before,
    round(count() / (SELECT count() FROM sess), 4)                            AS cohort_share
FROM tagged
GROUP BY dimension, cohort
HAVING reached >= {min_cohort:UInt32}
ORDER BY dimension, hazard_in_window DESC;
