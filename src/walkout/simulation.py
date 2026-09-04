#!/usr/bin/env python3
"""Generate realistic OTT playback telemetry with known abandonment cliffs.

Real platforms will point Walkout at their own event stream. For the demo we
synthesise one, because a public dataset of scene-level walk-outs does not
exist -- and because planting cliffs with *known causes* is the only way to
measure whether the agent's diagnosis is actually right (see eval.py).

Three cliffs are planted, one per cause class, plus one decoy dip that sits
below the detection floor and must NOT be reported:

  A  story         240-270s   every cohort, playback clean
  B  technical     560-600s   Android players on build 4.2.1 only, rebuffering
  C  localization   90-120s   non-English regions with no subtitle track
  D  decoy         620-640s   mild, universal, statistically insignificant

Driven by `walkout.cli`; see `make simulate`.
"""

from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np

from .config import DATA_DIR

# --- title under analysis ---------------------------------------------------
# Sintel: Blender Foundation open movie, CC-BY 3.0. Safe to ship in a public
# repo and safe to hand to Gemini.
TITLE = {
    "title_id": "sintel",
    "title_name": "Sintel (Blender Foundation, 2010)",
    "duration_sec": 888,
    "video_uri": "https://download.blender.org/durian/movies/Sintel.2010.720p.mkv",
    "license": "CC-BY 3.0",
}

BUCKET_SEC = 10

DEVICES = ["mobile_android", "mobile_ios", "web_desktop", "tv_android", "tv_roku", "tv_samsung"]
DEVICE_P = [0.30, 0.16, 0.22, 0.12, 0.10, 0.10]
PLATFORM = {
    "mobile_android": "mobile", "mobile_ios": "mobile", "web_desktop": "web",
    "tv_android": "tv", "tv_roku": "tv", "tv_samsung": "tv",
}

REGIONS = ["US", "IN", "BR", "GB", "DE", "NG", "JP", "MX"]
REGION_P = [0.28, 0.20, 0.11, 0.09, 0.08, 0.09, 0.08, 0.07]
# Sintel's audio track is English. These regions need subtitles to follow it.
NON_EN_REGIONS = {"IN", "BR", "DE", "JP", "MX"}
REGION_LANG = {"US": "en", "GB": "en", "NG": "en", "IN": "hi",
               "BR": "pt", "DE": "de", "JP": "ja", "MX": "es"}
REGION_POP = {"US": ["iad1", "sfo1"], "IN": ["bom1", "del1"], "BR": ["gru1"],
              "GB": ["lhr1"], "DE": ["fra1"], "NG": ["los1"], "JP": ["nrt1"], "MX": ["qro1"]}

VERSIONS = ["4.1.7", "4.2.1", "4.3.0"]
VERSION_P = [0.25, 0.35, 0.40]

# --- planted ground truth ---------------------------------------------------
CLIFFS = [
    {"id": "A", "cause": "story",        "start": 240, "end": 270, "mult": 3.1},
    {"id": "B", "cause": "technical",    "start": 560, "end": 600, "mult": 9.0},
    {"id": "C", "cause": "localization", "start":  90, "end": 120, "mult": 4.0},
    {"id": "D", "cause": "decoy",        "start": 620, "end": 640, "mult": 1.35},
]


def base_hazard(steps: int) -> np.ndarray:
    """Per-bucket exit probability for a viewer who has survived this far.

    Front-loaded: the first thirty seconds are a browsing decision, not a
    reaction to the film. Everything after settles to a low flat rate, which is
    what makes a genuine cliff stand out at all.
    """
    s = np.arange(steps, dtype=np.float32)
    return (0.006 + 0.090 * np.exp(-s / 1.6)).astype(np.float32)


def build_chunk(rng: np.random.Generator, n: int, steps: int, t0: datetime):
    """Simulate `n` sessions end to end and return them as columnar arrays."""
    device = rng.choice(len(DEVICES), size=n, p=DEVICE_P)
    region = rng.choice(len(REGIONS), size=n, p=REGION_P)
    version = rng.choice(len(VERSIONS), size=n, p=VERSION_P)
    first_time = (rng.random(n) < 0.42).astype(np.uint8)

    dev_names = np.array(DEVICES)[device]
    reg_names = np.array(REGIONS)[region]
    ver_names = np.array(VERSIONS)[version]
    plat = np.array([PLATFORM[d] for d in DEVICES])[device]

    # Subtitles only shipped for some locales, so many non-English viewers get
    # an English-only stream. That is cliff C waiting to happen.
    needs_subs = np.isin(reg_names, list(NON_EN_REGIONS))
    has_subs = needs_subs & (rng.random(n) < 0.45)
    sub_lang = np.where(has_subs, np.array([REGION_LANG[r] for r in REGIONS])[region], "")

    pop = np.array([rng.choice(REGION_POP[r]) for r in reg_names])

    # --- hazard matrix ------------------------------------------------------
    h = np.tile(base_hazard(steps), (n, 1))
    pos = np.arange(steps, dtype=np.int64) * BUCKET_SEC

    cohort_b = (np.isin(dev_names, ["mobile_android", "tv_android"])) & (ver_names == "4.2.1")
    cohort_c = needs_subs & (sub_lang == "")

    for c in CLIFFS:
        win = (pos >= c["start"]) & (pos < c["end"])
        if c["cause"] == "technical":
            mask = cohort_b
        elif c["cause"] == "localization":
            mask = cohort_c
        else:
            mask = np.ones(n, dtype=bool)
        h[np.ix_(mask, win)] *= c["mult"]

    np.clip(h, 0.0, 0.95, out=h)

    # --- survival -----------------------------------------------------------
    left = rng.random((n, steps)).astype(np.float32) < h
    left[:, -1] = True                       # everyone terminates somewhere
    exit_step = np.argmax(left, axis=1)
    completed = exit_step == (steps - 1)

    # --- expand sessions into one row per heartbeat --------------------------
    lengths = (exit_step + 1).astype(np.int64)
    total = int(lengths.sum())
    sidx = np.repeat(np.arange(n), lengths)                       # session index per row
    step = np.arange(total) - np.repeat(np.cumsum(lengths) - lengths, lengths)
    position = (step * BUCKET_SEC).astype(np.uint32)

    is_first = step == 0
    is_last = step == np.repeat(exit_step, lengths)

    # --- quality of experience ----------------------------------------------
    row_plat = plat[sidx]
    bitrate = np.where(row_plat == "tv", rng.integers(5500, 12000, total),
              np.where(row_plat == "web", rng.integers(2800, 8000, total),
                                          rng.integers(1100, 4200, total))).astype(np.int64)
    p_rebuf = np.where(row_plat == "mobile", 0.012, 0.005)
    rebuffer = np.where(rng.random(total) < p_rebuf,
                        rng.integers(180, 1400, total), 0).astype(np.int64)
    dropped = rng.integers(0, 4, total).astype(np.int64)

    # The technical cliff has to be *visible in the telemetry*, otherwise the
    # agent has no honest way to tell it apart from a bad scene.
    tech = next(c for c in CLIFFS if c["cause"] == "technical")
    in_tech = cohort_b[sidx] & (position >= tech["start"]) & (position < tech["end"])
    hit = in_tech & (rng.random(total) < 0.78)
    rebuffer = np.where(hit, rng.integers(1800, 6500, total), rebuffer)
    bitrate = np.where(hit, rng.integers(250, 900, total), bitrate)
    dropped = np.where(hit, rng.integers(20, 140, total), dropped)

    startup = np.where(row_plat == "mobile", rng.integers(700, 3200, total),
                                             rng.integers(400, 1800, total)).astype(np.int64)

    etype = np.where(is_first, "start",
             np.where(is_last, np.where(completed[sidx], "complete", "exit"),
              np.where(rebuffer > 900, "rebuffer", "heartbeat")))

    # sessions start at random points across a week of traffic
    sess_offset = rng.integers(0, 7 * 24 * 3600, n)
    epoch = int(t0.timestamp())
    ts = epoch + sess_offset[sidx] + position.astype(np.int64)

    sess_ids = np.array([f"s{i:012x}" for i in rng.integers(0, 2**44, n)])
    view_ids = np.array([f"v{i:010x}" for i in rng.integers(0, 2**38, n)])

    return {
        "event_time": ts, "session_id": sess_ids[sidx], "viewer_id": view_ids[sidx],
        "title_id": np.full(total, TITLE["title_id"]), "position_sec": position,
        "event_type": etype, "device": dev_names[sidx], "platform": row_plat,
        "region": reg_names[sidx], "app_version": ver_names[sidx],
        "is_first_time": first_time[sidx], "subtitle_lang": sub_lang[sidx],
        "audio_lang": np.full(total, "en"), "bitrate_kbps": bitrate,
        "rebuffer_ms": rebuffer, "startup_ms": startup, "dropped_frames": dropped,
        "cdn_pop": pop[sidx],
    }


COLUMNS = ["event_time", "session_id", "viewer_id", "title_id", "position_sec",
           "event_type", "device", "platform", "region", "app_version",
           "is_first_time", "subtitle_lang", "audio_lang", "bitrate_kbps",
           "rebuffer_ms", "startup_ms", "dropped_frames", "cdn_pop"]


def generate(
    sessions: int = 250_000,
    chunk: int = 25_000,
    seed: int = 7,
    on_chunk: Callable[[dict[str, np.ndarray]], None] | None = None,
) -> dict[str, Any]:
    """Simulate `sessions` viewings, handing each chunk to `on_chunk`.

    Chunked so a run of any size stays inside a fixed memory budget -- 250k
    sessions is roughly 14M events, which is not something to hold in a list.
    """
    rng = np.random.default_rng(seed)
    steps = TITLE["duration_sec"] // BUCKET_SEC + 1
    t0 = datetime.now(timezone.utc) - timedelta(days=7)

    events = 0
    done = 0
    while done < sessions:
        n = min(chunk, sessions - done)
        cols = build_chunk(rng, n, steps, t0)
        if on_chunk is not None:
            on_chunk(cols)
        events += len(cols["position_sec"])
        done += n
        print(f"  {done:>9,} sessions  {events:>12,} events", flush=True)

    truth = {
        "title": TITLE,
        "bucket_sec": BUCKET_SEC,
        "sessions": sessions,
        "events": events,
        "seed": seed,
        "cliffs": CLIFFS,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "ground_truth.json").write_text(json.dumps(truth, indent=2))
    return truth


def write_csv_chunk(out_dir: Path, part: int, cols: dict[str, np.ndarray]) -> Path:
    """Gzipped CSV, one file per chunk, in COLUMNS order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"playback_events.{part:04d}.csv.gz"
    arrays = [cols[c] for c in COLUMNS]
    with gzip.open(path, "wt", newline="") as fh:
        for row in range(len(cols["position_sec"])):
            fh.write(",".join(str(a[row]) for a in arrays) + "\n")
    return path
