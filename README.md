# Walkout

**Every platform knows *when* viewers stop watching. None of them know *why*.**

Retention curves are everywhere — YouTube Studio, Mux, Conviva, every OTT
analytics stack. They all tell you the same thing: 18% of your audience left at
04:08. Not one of them tells you what happened at 04:08.

So the answer today is an analyst scrubbing to a timestamp and guessing. And the
guess is often wrong, because two completely different failures produce an
identical cliff:

- **the scene isn't working** → recut it
- **the CDN is rebuffering on one device build** → don't touch the edit, fix delivery

Get that backwards and you either recut a scene that was fine, or ship a broken
stream to everyone. Walkout is an agent that tells them apart.

## What it does

1. **Detect** — queries playback telemetry in ClickHouse and finds statistically
   significant abandonment cliffs, not noise. Hazard rate against a robust
   post-warmup baseline, gated by both an effect-size floor and a binomial
   z-test.
2. **Localize** — turns each cliff into a timecode window, a magnitude, and a
   cohort: *00:04:00–00:04:30, 3.1× baseline hazard, all devices, playback clean.*
3. **Watch** — hands Gemini the actual footage at exactly those timestamps.
   Gemini's agentic video understanding anchors to MM:SS and scans only the
   moments it needs, so a two-hour title costs a handful of windows, not a
   full-length transcript.
4. **Diagnose** — cross-checks quality-of-experience on the same rows (rebuffer
   ratio, bitrate, dropped frames, player build, CDN pop) and classifies the
   cliff: **story · pacing · technical · localization · ad-break**.
5. **Act** — emits a ranked cut list: timecode, cause, evidence, recommended
   action, and recoverable watch-hours. Re-run after a change to see it move.

## Why it needs both halves

Neither piece works alone. Telemetry at this scale tells you where the bodies
are but can't see the film. A model that watches the film has no idea which
thirty seconds out of ninety minutes are worth watching, and no way to know
whether the audience was reacting to the scene or to a buffering wheel. The
diagnosis only exists in the join.

## Stack

| Layer | Technology |
|---|---|
| Agent | Google Agent Development Kit (ADK) on Vertex AI |
| Reasoning + video | Gemini on Vertex AI, agentic video understanding |
| Telemetry | ClickHouse Cloud via the official `mcp-clickhouse` MCP server |
| Serving | Cloud Run |
| Secrets | Google Secret Manager |

No non-Google AI models, APIs, or agent frameworks are used anywhere in this
project — including LangChain, LangGraph and CrewAI. Tool orchestration is
ADK's own `MCPToolset`.

## The demo data

A public dataset of scene-level walk-outs does not exist, so `scripts/simulate.py`
generates realistic OTT telemetry — ~14M playback heartbeats across 250,000
sessions — with **cliffs planted at known timecodes for known reasons**:

| | Window | Cause | Who |
|---|---|---|---|
| A | 04:00–04:30 | story | everyone, playback clean |
| B | 09:20–10:00 | technical | Android players on build 4.2.1, rebuffering |
| C | 01:30–02:00 | localization | non-English regions with no subtitle track |
| D | 10:20–10:40 | *decoy* | mild, universal, below the significance floor |

Planted ground truth is the point: it is the only way to measure whether the
agent's diagnosis is actually **right**, rather than merely plausible. `D` must
never be reported.

The title under analysis is *Sintel* (Blender Foundation, CC-BY 3.0).

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in ClickHouse + Google Cloud

clickhouse-client < sql/01_schema.sql            # or paste into ClickHouse Cloud
python scripts/simulate.py --sessions 250000 --clickhouse
```

## Status

Under construction for [Agentic Cinema: The Blockbuster Hackathon](https://agentic-cinema.devpost.com/)
(ClickHouse track).

- [x] Telemetry schema + generator with planted ground truth
- [x] Cliff detection: hazard baseline, binomial significance, cohort attribution
- [ ] ADK agent + `mcp-clickhouse` toolset
- [ ] Gemini video-window investigation
- [ ] Diagnosis + cut-list export
- [ ] Web UI
- [ ] Cloud Run deploy

## License

Apache-2.0.
