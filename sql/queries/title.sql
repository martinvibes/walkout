-- ---------------------------------------------------------------------------
-- One title's metadata: runtime, where the credits start, and the video URI
-- the agent hands to Gemini.
-- ---------------------------------------------------------------------------
SELECT title_id, title_name, duration_sec, credits_start_sec, video_uri, license
FROM walkout.titles
WHERE title_id = {title_id:String};
