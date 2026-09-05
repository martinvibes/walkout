-- Expand session descriptors into playback heartbeats, server-side.
--
-- One row per session becomes one row per ten-second heartbeat up to the point
-- the viewer left. Quality-of-experience columns are drawn here rather than
-- uploaded: bitrate and rebuffering are per-heartbeat noise, and generating
-- 14M values locally only to push them over the wire is the expensive way to
-- get the same distribution.
--
-- rand(n) is called with distinct seeds so the draws are independent of one
-- another; without the seeds every column would share a single random value
-- per row and the QoE dimensions would be perfectly correlated.
INSERT INTO walkout.playback_events
SELECT
    event_time,
    session_id,
    viewer_id,
    title_id,
    position_sec,
    multiIf(
        step = 0,                        'start',
        step = exit_step AND completed,  'complete',
        step = exit_step,                'exit',
        rebuffer_ms > 900,               'rebuffer',
                                         'heartbeat'
    ) AS event_type,
    device,
    platform,
    region,
    app_version,
    is_first_time,
    subtitle_lang,
    audio_lang,
    locale_lang,
    bitrate_kbps,
    rebuffer_ms,
    startup_ms,
    dropped_frames,
    cdn_pop
FROM
(
    SELECT
        s.session_id            AS session_id,
        s.viewer_id             AS viewer_id,
        s.title_id              AS title_id,
        s.device                AS device,
        s.platform              AS platform,
        s.region                AS region,
        s.app_version           AS app_version,
        s.is_first_time         AS is_first_time,
        s.subtitle_lang         AS subtitle_lang,
        s.audio_lang            AS audio_lang,
        s.locale_lang           AS locale_lang,
        s.cdn_pop               AS cdn_pop,
        s.startup_ms            AS startup_ms,
        s.exit_step             AS exit_step,
        s.completed             AS completed,
        step,
        toUInt32(step * {bucket_sec:UInt32})                                AS position_sec,
        toDateTime64((s.start_ts + step * {bucket_sec:UInt32}) * 1000, 3)   AS event_time,

        -- The delivery failure: this cohort, this window, most of the time.
        (s.degraded_cohort = 1)
            AND (position_sec >= {degraded_start:UInt32})
            AND (position_sec <  {degraded_end:UInt32})
            AND ((rand(1) % 100) < 78)                                      AS degraded,

        if(degraded,
           250 + (rand(2) % 650),
           multiIf(platform = 'tv',  5500 + (rand(3) % 6500),
                   platform = 'web', 2800 + (rand(4) % 5200),
                                     1100 + (rand(5) % 3100)))              AS bitrate_kbps,

        if(degraded,
           1800 + (rand(6) % 4700),
           if((rand(7) % 1000) < if(platform = 'mobile', 12, 5),
              180 + (rand(8) % 1220),
              0))                                                           AS rebuffer_ms,

        if(degraded, 20 + (rand(9) % 120), rand(10) % 4)                     AS dropped_frames
    FROM walkout.sessions AS s
    ARRAY JOIN range(toUInt32(s.exit_step) + 1) AS step
    WHERE s.title_id = {title_id:String}
);
