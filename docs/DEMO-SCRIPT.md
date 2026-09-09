# Demo video: 1 minute 45

The brief asks for a demo of the project *functioning as built*, not a trailer.
So this script shows the thing working and never cuts away to slides, logos or
an architecture diagram. Every second of screen time is the live deployment.

Target: **1:45**. The cap is three minutes; being well under it is an advantage,
because a judge watching thirty of these will thank you for it.

Narration is ~265 words, which lands at 1:45 spoken at a normal pace. Do not
rush to fit more in. If you are running long, cut a sentence rather than talk
faster.

---

## Before you press record

Five things, in this order. The fourth one is the one that ruins takes.

1. **Check the quota.** A full investigation costs about seven model calls and
   the free tier allows twenty per model per day. Record early in the day, and
   budget for exactly two attempts.
2. **Open the page and let it settle.** The retention curve should be drawn and
   the stored investigation should be showing before you start. A judge should
   never watch a skeleton loader.
3. **Pin the theme.** Add `?theme=dark` or `?theme=light` to the URL so the page
   cannot flip mid-recording. Dark reads better on video.
4. **Do not record the agent in real time.** A run takes about 110 seconds,
   which is longer than this entire video. Record the full run, then speed that
   segment up 4x in the edit. Say "sped up" in the narration; hiding it would be
   the one dishonest frame in the whole thing.
5. **Have the fallback ready.** If the live run hits the quota, the page shows a
   real stored investigation with the same verdicts. Point at that instead and
   the demo still works. This is worth knowing before you are live, not during.

One gotcha worth knowing before you are on camera: the written report ranks the
cliffs worst-first by watch hours, so it reads "Cliff 1, Cliff 3, Cliff 2". Those
are detection ids, not an ordering mistake. Refer to everything by timecode and
the question never comes up.

Record at 1920x1080 or larger. Hide bookmarks. Close every other tab.

---

## The numbers on the screen

Read these off the page rather than memorising them, but know them well enough
to notice if a fresh run says something different. This is what the deployed
instance currently shows, worst-first by recoverable watch hours:

| Timecode | Verdict | The evidence | Who fixes it |
|---|---|---|---|
| **00:03:40-04:10** | Pacing | 1,170 watch-hours, 3.1x baseline. Flat across *every* cohort, playback perfect. | The editor |
| **00:02:10-02:40** | Localization | 602 watch-hours, 1.9x baseline. The `subtitle_gap` cohort is 2.1x over-represented. | Localization manager |
| **00:09:20-10:00** | Technical | 283 watch-hours, 2.0x baseline. Android 4.2.1, rebuffering 13.01% against a 1.51% baseline. | App engineer |

**Three cliffs, three causes, three different people.** That is the punchline of
the whole demo, and it is worth building the last twenty seconds around it.

A fourth mild dip at 10:20 is deliberately planted and deliberately ignored,
because it sits below the significance floor. Mention it if you have room.

---

## The script

**1:45.** Narration is 252 words. At a normal pace that is about 101 seconds,
plus roughly eight seconds of holds on the verdict, which are not padding: a
judge needs a beat to read each one. Realistically it lands between 1:45 and
1:50 depending on how fast you talk.

If you need it under 1:45 exactly, cut one sentence: *"Get it backwards and you
break a film that was fine."* That is eleven words and about five seconds, and
the line before it already carries the point. Cut that rather than speeding up.

| Time | On screen | Say |
|---|---|---|
| **0:00-0:10** | Cold open on the retention curve, already drawn. No logo, no title card. Cursor lands on the 03:40 cliff. | "Six thousand six hundred people quit this film at the exact same moment. Every analytics platform shows you that drop. None of them can tell you what caused it." |
| **0:10-0:22** | Slow pan across the three shaded bands. | "A scene that drags and a stream that stutters make an identical cliff. One needs a recut, the other needs an engineer. Get it backwards and you break a film that was fine." |
| **0:22-0:34** | Stage 1. Open a cliff card so the cohort evidence shows. | "Walkout tells them apart. Survival analysis over thirteen million playback events in ClickHouse, live, through the official ClickHouse MCP server. It finds the moments a film loses a room." |
| **0:34-0:50** | Stage 2. Click **Custom**, press **Use playhead**, then **Watch this moment**. | "Then the part telemetry can't do. Gemini watches those exact seconds of the real film. And to prove these aren't prepared clips, I'll pick a window myself. It is never told that anyone walked out there." |
| **0:50-1:02** | Press **Investigate**. Tool calls stream. **Speed to 4x.** | "Now the full agent. The Agent Development Kit making real tool calls, sped up here. It pulls the cohorts, watches each cliff, checks the numbers against the picture." |
| **1:02-1:24** | Scroll the verdict. Hold ~3s on each of the three. Do not rush this. | "Three cliffs. Three different answers. Three-forty: pacing. Everyone left at the same rate, playback flawless. That one's the editor. Two-ten: localization. No subtitle track, more than twice as likely to quit. Nine-twenty: technical. Android 4.2.1, rebuffering at thirteen percent. And in bold: do not recommend an edit." |
| **1:24-1:38** | The API, then the docs. Exact clicks below. | "And none of it is trapped in the page. Every endpoint is public and read-only, so here's a live call against this deployment. And the docs explain how every verdict gets decided." |
| **1:38-1:45** | Back to the verdict, hold on the URL. | "Same shape on the chart. Three different people to fix it. That's *when* your audience left, versus *why*." |

---

## The API and docs beat, click by click

This is fourteen seconds and it has to be rehearsed, because fumbling a click
here costs more time than the beat is worth.

**Before recording: open both in their own tabs.** Do not navigate to them on
camera. Loading a page live burns three seconds and shows a blank screen.

- Tab 2: `walkout-production-f914.up.railway.app/api/docs`
- Tab 3: `walkout-production-f914.up.railway.app/docs`

### 1:24-1:33 — the API (9 seconds)

Cut to tab 2. The endpoints are grouped **Telemetry / Agent / Vision /
Service**, which is worth one second of hover because the grouping is by what
each call costs you, not by URL shape.

Then, in order:

1. Click the **`GET /api/retention/{title_id}`** row. It expands.
2. Click **Try it out** (top right of the expanded block).
3. The `title_id` box goes editable. Type **`sintel`**.
4. Click **Execute**.
5. Real JSON lands in about a second and a half. **Scroll it for two seconds**
   so they see the curve points and the cliffs come back as data.

That is the whole beat. You are proving one thing: this is a running service,
not a screen recording. It is the cheapest credibility in the video because it
costs no quota and cannot fail.

Say it over the click, not after: *"Every endpoint is public and read-only, so
here's a live call against this deployment."*

### 1:33-1:38 — the docs (5 seconds)

Cut to tab 3. **Do not read anything aloud and do not stop on a paragraph.**
Scroll briskly through and let three things flash past:

1. The two panels near the top: **"The scene isn't working"** against **"The
   stream is broken"**. That is the thesis restated, and it reads in a glance.
2. The **How it decides** table, which is the thresholds written down.
3. Land on it and stop.

Say over it: *"And the docs explain how every verdict gets decided."*

The point of this beat is not that they read the docs. It is that they see
documentation exists and is specific, which is the difference between a
hackathon demo and something someone could actually pick up.

## What to actually explain, and what to leave out

**Say these. They are what you are being judged on.**

- **The discriminator.** A story problem and a delivery problem make an
  identical cliff and demand opposite fixes. This is the whole idea, and it is
  the one sentence a judge should remember. Say it in the first fifteen seconds.
- **That both integrations are live.** "Through the official ClickHouse MCP
  server" and "the Agent Development Kit making real tool calls" are the two
  phrases that satisfy the partner-track and Google-runtime requirements out
  loud. Say them while the tool calls are visibly streaming.
- **That the model is blind.** Gemini is never told that anyone walked out. That
  is what makes agreement between the footage and the numbers mean something
  rather than being an echo. It is also the most interesting design decision in
  the project, so do not skip it to save two seconds.
- **That it names an owner.** Localization manager, app engineer, editor. A
  diagnosis nobody can act on is a chart with extra steps.
- **That it refuses to guess.** If you have time, mention that a fourth mild dip
  is deliberately ignored, and that "unknown" is a real answer. Restraint reads
  as rigour.

**Leave these out.**

- How long you spent on it, that you built it solo, or anything about the
  deadline. Nobody is scoring effort.
- A cinematic cold open, a logo animation, or music over the narration. The
  brief explicitly asks for a working demo, not a trailer.
- A tour of the codebase. One tab, one page, all the way through. If they want
  the code they will open the repo, which is why the README points at the exact
  lines.
- The word "simply". Nothing here is simple and it does not need to sound it.
- Reading the on-screen text aloud. Let them read it; say something else.

**If something breaks mid-take**, say what happened and keep going. A demo that
handles a failure gracefully on camera is more convincing than one that never
meets one, and the failure states were built for exactly this.

---

## Uploading

- YouTube or Vimeo, **public** (not unlisted-only if the form asks for public).
- English audio. If your mic is rough, add English subtitles; YouTube's
  auto-captions are acceptable but check them for "ClickHouse" and "Gemini",
  which they routinely mangle.
- Title it plainly: `Walkout: scene-level abandonment forensics (Agentic Cinema,
  ClickHouse track)`.
- Put the live URL and the repo URL in the description, not only in the video.
