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
| Agent | Google Agent Development Kit (ADK), `LlmAgent` + `MCPToolset` |
| Reasoning | Gemini 3.5 Flash |
| Video | Gemini 3.6 Flash, agentic video understanding over YouTube URIs |
| Telemetry | ClickHouse Cloud via the official `mcp-clickhouse` MCP server |
| API | FastAPI, server-sent events for the agent stream |
| Serving | Docker, deployed on Railway |

No non-Google AI models, APIs, or agent frameworks are used anywhere in this
project — including LangChain, LangGraph and CrewAI. Tool orchestration is
ADK's own `MCPToolset`.

Orchestration and video run on **separate models on purpose**. They want
different things — one is a fast reasoner making a dozen short calls, the other
reads video once and carefully — and the request quota is counted per model, so
separating them also stops a long investigation from starving its own video
reads.

### Two Python environments, one image

ADK's MCP integration needs protocol library `mcp` 1.x. The official ClickHouse
MCP server needs 2.x. They are separate processes talking over stdio, so the
conflict only exists if you insist on running both under one interpreter — and
so the server lives in its own `.venv-mcp` (`make mcp-server`), which the
Dockerfile reproduces as `/opt/mcp`.

## How it tells the causes apart

Two numbers do most of the work, and both come out of ClickHouse rather than out
of a model.

**Concentration** — a cohort's hazard rate inside the window, divided by the
whole audience's hazard rate inside the same window. A cliff that everyone walked
off equally is a cliff in the film. A cliff that is 4× worse on one player build
is a cliff in the pipeline. One `ARRAY JOIN` fans each session into one row per
dimension, so all nine dimensions are sliced in a single pass over the data.

**Rebuffer lift** — rebuffering inside the window against *the same cohort's*
rebuffering across the rest of the title. The comparison is what makes it mean
anything: a cohort that rebuffers everywhere has a platform problem, not a cliff.
Only a cohort that rebuffers *here specifically* explains people leaving *here
specifically*.

Delivery concentration plus rebuffer lift is a technical fault, and the agent is
instructed never to recommend a recut for one. An audience skew with clean
playback is localization. Flat and clean is the interesting case: telemetry has
proven it is **not** a delivery failure and **not** an availability problem, and
then deliberately returns `unknown` rather than guessing. Telemetry cannot tell a
boring scene from a well-earned quiet moment. That call needs eyes on the
footage, which is where Gemini comes in — and pretending otherwise would be the
whole product lying.

## The demo data

A public dataset of scene-level walk-outs does not exist, so `walkout.simulation`
generates realistic OTT telemetry — 13.1M playback heartbeats across 250,000
sessions — with **cliffs planted at known timecodes for known reasons**:

| | Window | Cause | Who |
|---|---|---|---|
| A | 03:40–04:10 | story | everyone, playback clean |
| B | 09:20–10:00 | technical | Android players on build 4.2.1, rebuffering |
| C | 02:05–02:35 | localization | non-English locales with no subtitle track |
| D | 10:20–10:40 | *decoy* | mild, universal, below the significance floor |

Planted ground truth is the point: it is the only way to measure whether the
agent's diagnosis is actually **right**, rather than merely plausible. `D` must
never be reported.

**The timecodes are not arbitrary.** Each was chosen by asking Gemini to survey
the real footage first, so the telemetry and the film agree. `A` sits on the
genuinely slowest passage in the film — Sintel going to bed, static shots, no
score. `C` sits on the shaman scene, where the plot goal is established entirely
through spoken English. An earlier draft planted the story cliff over the dragon
chase at 04:08, which would have produced a demo where the numbers claim a scene
drags while the picture shows a kinetic action sequence.

The film also ends at 12:26, and the simulator models the exodus when the
credits roll. Detection excludes it. An audience leaving as the credits start
has finished the film, and reporting that would bury three real findings under
one meaningless one.

The title under analysis is *Sintel* (Blender Foundation, CC-BY 3.0). Gemini
reads YouTube URLs directly, so the film is never hosted or shipped.

## Run it

```bash
make install                  # venv + editable install
make mcp-server               # the ClickHouse MCP server, in its own venv
cp .env.example .env          # then paste in your ClickHouse + Gemini settings

make doctor                   # verifies the connection before anything long runs
make load                     # applies sql/schema.sql -- safe to repeat, keeps data
make simulate                 # 13.1M events across 250k sessions (~4 min)
```

Then either watch it work:

```bash
make serve                    # the console on http://127.0.0.1:8000
make agent                    # the same investigation, in the terminal
```

or check that it is right:

```bash
make eval                     # grade the diagnosis against planted ground truth
make eval-mcp                 # the same grading, read through the MCP server
make test                     # unit tests, no cluster required
```

`make eval-mcp` matters more than it looks. It grades the pipeline over the
*exact* path the agent uses — the official ClickHouse MCP server, not the Python
driver — so "it works in the agent" is a measured claim rather than a hopeful
one.

## The console

`make serve` puts up a page with two halves, separated on purpose.

The **deterministic half** — retention curve, cliffs, cohort breakdown — is pure
ClickHouse and answers in a couple of seconds. The page is alive and useful
before the agent has said a word.

The **agent half** streams. An investigation takes about a minute because it is
really reading the film, and hiding that behind a spinner would waste the most
interesting thing the product does, so every tool call is sent to the browser as
it happens.

Finished investigations are written back to `walkout.agent_reports` and replayed
on the next page load, timestamped, with the button offering a fresh run. A full
investigation costs about ten model calls against a per-day quota; without this
the second person to open the page gets an error where the product should be.

## Layout

```
src/walkout/
  config.py         settings and credentials, resolved once
  models.py         Cliff, CohortSignal, Diagnosis, Cause -- the shared vocabulary
  warehouse.py      the Warehouse protocol, parameter binding, segment allow-list
  clickhouse.py     the driver implementation, schema loading, event expansion
  mcp_warehouse.py  the same interface over the official ClickHouse MCP server
  queries.py        loads sql/queries/*.sql by name
  detection.py      pure logic: merging flagged buckets, cohort concentration
  analysis.py       cliff detection and evidence gathering -- no model involved
  gemini.py         the shared client, with retry policy in one place
  vision.py         Gemini reading one window of the film, cached to disk
  reports.py        finished investigations, stored so they can be replayed
  evaluation.py     grading against planted ground truth
  simulation.py     telemetry generator with planted ground truth
  cli.py            entry points behind the Makefile
  agent/
    agent.py        the ADK LlmAgent and its MCPToolset
    prompts.py      the method and the evidence rules, in words
    tools.py        find_walkouts, investigate_walkout, watch_scene
  web/
    app.py          FastAPI, SSE agent stream
    static/         the console
sql/
  schema.sql        tables
  queries/          one parameter-bound statement per file, reviewable on its own
tests/              detection, parameter binding and grading -- no cluster required
```

Two things are worth calling out.

**`warehouse.py` is an interface, not a client.** The same analysis code runs
over the Python driver and over the MCP server without knowing which it has,
which is what makes `make eval-mcp` a real test rather than a second
implementation that might drift.

**Queries live in `sql/`, one statement per file.** They are the part of this
system most worth reviewing, and they are much easier to review as SQL than as
strings concatenated inside Python. Parameters are bound through a typed
allow-list; the only interpolation is a dimension name, checked against a fixed
set.

## Deploy

The image builds both environments and runs the console:

```bash
docker build -t walkout .
docker run --rm --env-file .env -p 8080:8000 walkout
```

`railway.json` points the platform's health check at `/api/health`, which
actually queries ClickHouse rather than just proving the process is alive.
Step-by-step instructions are in [docs/DEPLOY.md](docs/DEPLOY.md).

`make load` is safe to run on a deploy: every statement in the schema is
`CREATE ... IF NOT EXISTS`, so it brings a fresh cluster up and leaves a
populated one alone. Rebuilding the tables after a schema change is
`make reload`, which drops them and prints the row count first. That separation
exists because it was missing once, and applying the schema quietly deleted
thirteen million rows.

## Status

Built for [Agentic Cinema: The Blockbuster Hackathon](https://agentic-cinema.devpost.com/)
(ClickHouse track).

- [x] Telemetry schema + generator with planted ground truth
- [x] Cliff detection: hazard baseline, binomial significance, cohort attribution
- [x] ADK agent + `mcp-clickhouse` toolset
- [x] Gemini video-window investigation
- [x] Diagnosis with recoverable watch-hours
- [x] Web console with streaming agent
- [x] Container + deploy

On the planted dataset the agent finds all three real cliffs, gets all three
causes right, and ignores the decoy.

## License

Apache-2.0.
