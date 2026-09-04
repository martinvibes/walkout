-- ---------------------------------------------------------------------------
-- Same metrics across the whole title, for contrast.
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
