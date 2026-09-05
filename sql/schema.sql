-- Walkout: playback telemetry schema
-- One row per player heartbeat / lifecycle event. This is the shape real OTT
-- platforms emit (Sony LIV, Mux et al. run this workload on ClickHouse).

CREATE DATABASE IF NOT EXISTS walkout;

DROP TABLE IF EXISTS walkout.playback_events;

CREATE TABLE walkout.playback_events
(
    event_time      DateTime64(3),
    session_id      String,
    viewer_id       String,
    title_id        LowCardinality(String),

    -- where the playhead was when this event fired
    position_sec    UInt32,

    event_type      Enum8('start' = 1, 'heartbeat' = 2, 'rebuffer' = 3,
                          'exit' = 4, 'complete' = 5, 'error' = 6),

    -- audience dimensions
    device          LowCardinality(String),
    platform        LowCardinality(String),   -- mobile | tv | web
    region          LowCardinality(String),
    app_version     LowCardinality(String),
    is_first_time   UInt8,
    subtitle_lang   LowCardinality(String),   -- '' = no subtitles active
    audio_lang      LowCardinality(String),
    locale_lang     LowCardinality(String),   -- the viewer's device locale

    -- quality-of-experience dimensions (the technical-vs-story tiebreaker)
    bitrate_kbps    UInt32,
    rebuffer_ms     UInt32,
    startup_ms      UInt32,
    dropped_frames  UInt32,
    cdn_pop         LowCardinality(String)
)
ENGINE = MergeTree
PARTITION BY title_id
ORDER BY (title_id, position_sec, session_id)
SETTINGS index_granularity = 8192;

-- Titles under analysis. Kept tiny and human-readable so the agent can
-- resolve "the Sintel cut" -> title_id without guessing.
DROP TABLE IF EXISTS walkout.titles;

CREATE TABLE walkout.titles
(
    title_id      LowCardinality(String),
    title_name    String,
    duration_sec  UInt32,
    credits_start_sec UInt32,        -- leaving after this is finishing, not quitting
    video_uri     String,          -- gs:// or https:// source for Gemini
    license       String
)
ENGINE = MergeTree
ORDER BY title_id;
