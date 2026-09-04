-- ---------------------------------------------------------------------------
-- The story-vs-technical tiebreaker.
-- If playback was clean through the window, the cliff is editorial.
-- If rebuffering / bitrate collapsed, do NOT recut the scene -- fix delivery.
-- ---------------------------------------------------------------------------
SELECT
    $DIM$                                              AS cohort,
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
