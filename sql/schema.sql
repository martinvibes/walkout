-- Walkout: playback telemetry schema
-- One row per player heartbeat / lifecycle event. This is the shape real OTT
-- platforms emit (Sony LIV, Mux et al. run this workload on ClickHouse).

CREATE DATABASE IF NOT EXISTS walkout;

-- Every statement here is IF NOT EXISTS, and that is load-bearing. An earlier
-- version opened each table with DROP TABLE IF EXISTS, which made `make load`
-- -- documented as "applies the schema", and the obvious thing to run on a new
-- deploy -- silently destroy thirteen million rows. Rebuilding the tables is a
-- real need, but it is `walkout-load --reset`, which says so and counts what it
-- is about to delete.

CREATE TABLE IF NOT EXISTS walkout.playback_events
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

-- Session descriptors: one row per viewing, ~250k rows instead of ~14M.
-- The survival simulation runs locally in numpy, where sequential hazard draws
-- belong; only its *outcome* is uploaded, and ClickHouse expands each session
-- into its heartbeats server-side. Pushing 14M rows up a home connection took
-- ten minutes and failed three times; this uploads about 20MB and cannot half-
-- populate the events table, because the expansion is a single statement.
CREATE TABLE IF NOT EXISTS walkout.sessions
(
    session_id      String,
    viewer_id       String,
    title_id        LowCardinality(String),
    device          LowCardinality(String),
    platform        LowCardinality(String),
    region          LowCardinality(String),
    app_version     LowCardinality(String),
    is_first_time   UInt8,
    subtitle_lang   LowCardinality(String),
    audio_lang      LowCardinality(String),
    locale_lang     LowCardinality(String),
    cdn_pop         LowCardinality(String),
    start_ts        UInt32,          -- unix seconds at playback start
    exit_step       UInt16,          -- last heartbeat index reached
    completed       UInt8,
    startup_ms      UInt32,
    degraded_cohort UInt8            -- subject to the delivery failure window
)
ENGINE = MergeTree
ORDER BY (title_id, session_id);

-- Titles under analysis. Kept tiny and human-readable so the agent can
-- resolve "the Sintel cut" -> title_id without guessing.
CREATE TABLE IF NOT EXISTS walkout.titles
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


-- ---------------------------------------------------------------------------
-- The agent's own findings, kept so the page always has something to show.
--
-- A full investigation costs about ten model calls, and a free-tier key is
-- capped per day. Without this, the second person to open the page today gets
-- a quota error instead of a product. The newest report per title wins, which
-- is what ReplacingMergeTree does with a version column.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS walkout.agent_reports
(
    title_id    LowCardinality(String),
    model       LowCardinality(String),
    report      String,                  -- the markdown the agent wrote
    trace       String,                  -- JSON: the tool calls it made
    complete    UInt8,                   -- 0 if the run died before finishing
    duration_ms UInt32,
    created_at  DateTime64(3)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (title_id, model);
