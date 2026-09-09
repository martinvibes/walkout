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

Target **2:00**, which is still a full minute under the cap. The extra fifteen
seconds over a rushed 1:45 buys the two beats that make it land: holding on
each verdict long enough to read it, and proving the API is real.

| Time | On screen | Say |
|---|---|---|
| **0:00-0:11** | Cold open on the retention curve, already drawn. No logo, no title card. Cursor lands on the 03:40 cliff. | "Six thousand six hundred people quit this film at the exact same moment. Every analytics platform can show you that drop. None of them can tell you what caused it." |
| **0:11-0:25** | Slow pan across the three shaded bands. | "And that's the problem, because a scene that drags and a stream that stutters make an identical cliff. One needs a recut. The other needs an engineer. Get it backwards and you damage a film that was fine." |
| **0:25-0:38** | Stage 1. Open a cliff card so the cohort evidence is visible. | "Walkout tells them apart. It runs survival analysis over thirteen million playback events in ClickHouse, live, through the official ClickHouse MCP server, and finds the moments a film loses a room." |
| **0:38-0:56** | Stage 2. Click **Custom**, press **Use playhead**, then **Watch this moment**. Hold on the loader a beat, cut to the reading. | "Then it does what telemetry can't. Gemini watches those exact seconds of the real film. And to prove these aren't three prepared clips, I'll pick a window myself, right now. It is never told that anyone walked out there." |
| **0:56-1:10** | Press **Investigate**. Tool calls stream in. **Speed this segment to 4x.** | "Now the full agent. This is the Agent Development Kit making real tool calls, sped up. It pulls the cohorts, watches each cliff, and checks the numbers against what's on screen." |
| **1:10-1:34** | Scroll the verdict slowly. Hold ~3 seconds on each of the three. This is the punchline; do not rush it. | "Three cliffs. Three different answers. At three-forty: pacing. Everyone left at the same rate and playback was flawless, so that one is the editor's. At two-ten: localization. Viewers with no subtitle track, more than twice as likely to quit. At nine-twenty: technical. Android 4.2.1, rebuffering at thirteen percent. And in bold: do not recommend an edit to the film." |
| **1:34-1:50** | Cut to `/api/docs`. Expand `GET /api/retention/{title_id}`, hit **Try it out**, then **Execute**. Let the real JSON land. Then one quick scroll of `/docs`. | "And none of it is trapped in this page. Everything the console does is a public, read-only API you can call right now, with documentation for how every verdict is decided and what it refuses to guess at." |
| **1:50-2:00** | Back to the verdict, then hold on the live URL. | "Same shape on the chart. Three different people to fix it. That's the difference between knowing *when* your audience left, and knowing *why*." |

### The hook, if you want a different one

The opening line is doing the most work in the whole video, so pick the one you
can say most naturally. All three are true of what is on screen.

1. **"Six thousand six hundred people quit this film at the exact same moment."**
   Concrete and human. A number of people beats a multiple of a baseline, which
   is why this is the default.
2. **"At three minutes forty, this film loses a room."** Shortest and most
   cinematic. Good if you want to be on the product two seconds sooner.
3. **"Something happens at three minutes forty. Nobody can tell you what."**
   Most direct statement of the gap. Follow it immediately with the curve.

Whichever you pick, the second sentence stays: every platform shows the drop,
none of them says why. That contrast is the entire pitch.

### The API beat is worth the fifteen seconds

Most hackathon demos are a page with a model behind it. Executing a real request
against the deployed instance, on camera, and watching JSON come back proves in
one shot that this is a service rather than a screen recording. It is also the
cheapest credibility in the video: no quota, no waiting, and it cannot fail.

Have `/api/docs` open in a second tab before you record so the cut is instant.

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
