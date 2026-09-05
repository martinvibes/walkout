/* ---------------------------------------------------------------------------
   Walkout — client

   No framework and no build step. The page has one job: show a survival curve,
   let you open a cliff to see who left, and stream the agent's reasoning while
   it works. All three are small enough to write directly, and a judge cloning
   the repo can read every line of it.
--------------------------------------------------------------------------- */

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = { titleId: null, title: null, cliffs: [], running: false };

/* --- theme --------------------------------------------------------------- */

const THEME_KEY = "walkout:theme";

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* private window */ }
}

function initTheme() {
  // ?theme=light|dark pins the theme, which is what a screenshot or a recorded
  // demo needs -- neither can click the toggle.
  const asked = new URLSearchParams(location.search).get("theme");
  let stored = null;
  try { stored = localStorage.getItem(THEME_KEY); } catch { /* private window */ }
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(asked || stored || (prefersDark ? "dark" : "light"));

  $("#theme").addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    if (state.title) drawChart();          // the curve is painted with theme colours
  });
}

/* --- entrance ------------------------------------------------------------ */

function splitHeadline() {
  const el = $("#headline");
  const lines = el.dataset.text.split("|");
  el.innerHTML = lines.map((line, lineIndex) => {
    const words = line.trim().split(" ").map((word, wordIndex) => {
      const delay = (lineIndex * 4 + wordIndex) * 0.06 + 0.1;
      const cls = lineIndex === 1 ? "reveal-word fade" : "reveal-word";
      return `<span class="${cls}" style="animation-delay:${delay}s">${word}</span>`;
    }).join(" ");
    return `<span style="display:block">${words}</span>`;
  }).join("");
}

function watchScroll() {
  const nav = $("#nav");
  const onScroll = () => nav.classList.toggle("stuck", window.scrollY > 12);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  const io = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("seen");
        io.unobserve(entry.target);
      }
    });
  }, { rootMargin: "0px 0px -12% 0px" });

  $$(".fade-up").forEach((el) => io.observe(el));
}

/* --- formatting ---------------------------------------------------------- */

const timecode = (sec) => {
  const s = Math.max(0, Math.round(sec));
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
};

const commas = (n) => Math.round(n).toLocaleString("en-US");

function countUp(el, target, suffix = "") {
  const duration = 900;
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = commas(target * eased) + suffix;
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

/* A deliberately small markdown renderer: the agent writes headings, bold,
   bullets and rules, and nothing else is worth the attack surface. */
function markdown(src) {
  const lines = escapeHtml(src).split("\n");
  const out = [];
  let inList = false;

  const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^\s*---+\s*$/.test(line)) { closeList(); out.push("<hr>"); continue; }
    if (!line.trim()) { closeList(); continue; }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) { closeList(); out.push(`<h3>${inline(heading[2])}</h3>`); continue; }

    const bullet = line.match(/^\s*[*-]\s+(.*)$/);
    if (bullet) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }
    closeList();
    out.push(`<p>${inline(line)}</p>`);
  }
  closeList();
  return out.join("");

  function inline(text) {
    return text
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
  }
}

/* --- data ---------------------------------------------------------------- */

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body.slice(0, 180)}`);
  }
  return response.json();
}

async function loadTitles() {
  const titles = await getJson("/api/titles");
  $("#titles").innerHTML = titles.map((t) => `
    <button class="chip" data-id="${t.title_id}" aria-pressed="false">${escapeHtml(t.title_name)}</button>
  `).join("");

  $$("#titles .chip").forEach((chip) => {
    chip.addEventListener("click", () => selectTitle(chip.dataset.id));
  });

  if (titles.length) selectTitle(titles[0].title_id);
}

async function selectTitle(titleId) {
  if (state.running) return;
  state.titleId = titleId;
  $$("#titles .chip").forEach((chip) => {
    chip.setAttribute("aria-pressed", String(chip.dataset.id === titleId));
  });

  showSkeletons();
  try {
    const data = await getJson(`/api/retention/${titleId}`);
    state.title = data;
    state.cliffs = data.cliffs;
    renderStats(data);
    drawChart();
    renderCliffs(data.cliffs);
  } catch (err) {
    $("#cliffs").innerHTML = `<div class="banner err">Could not reach the warehouse. ${escapeHtml(err.message)}</div>`;
  }
}

function showSkeletons() {
  $("#stats").innerHTML = Array.from({ length: 4 }, () => `
    <div class="stat"><div class="k skeleton">loading</div><div class="v skeleton">000,000</div></div>
  `).join("");
  $("#cliffs").innerHTML = Array.from({ length: 3 }, () => `
    <div class="cliff"><div class="cliff-top"><span class="cliff-time skeleton">00:00-00:00</span></div></div>
  `).join("");
}

function renderStats(data) {
  const worst = data.cliffs[0];
  const hours = data.cliffs.reduce((sum, c) => sum + c.recoverable_watch_hours, 0);
  const cells = [
    { k: "Sessions analysed", v: data.sessions },
    { k: "Runtime", v: null, text: timecode(data.title.duration_sec) },
    { k: "Cliffs found", v: data.cliffs.length },
    { k: "Recoverable", v: hours, suffix: "", unit: "watch hours" },
  ];

  $("#stats").innerHTML = cells.map((cell) => `
    <div class="stat">
      <div class="k">${cell.k}</div>
      <div class="v"><span data-v="${cell.v ?? ""}">${cell.text ?? "0"}</span>${cell.unit ? `<small>${cell.unit}</small>` : ""}</div>
    </div>
  `).join("");

  $$("#stats .v span").forEach((span) => {
    const value = span.dataset.v;
    if (value !== "") countUp(span, Number(value));
  });

  if (worst) $("#stats").dataset.worst = worst.cliff_id;
}

/* --- chart --------------------------------------------------------------- */

const PLOT = { left: 46, right: 14, top: 18, curveH: 178, gap: 20, hazardH: 66 };

function drawChart() {
  const svg = $("#curve");
  const data = state.title;
  if (!data) return;

  const W = 1000;
  const innerW = W - PLOT.left - PLOT.right;
  const curveTop = PLOT.top;
  const curveBottom = curveTop + PLOT.curveH;
  const hazTop = curveBottom + PLOT.gap;
  const hazBottom = hazTop + PLOT.hazardH;

  const duration = data.title.duration_sec;
  const points = data.curve;

  // The credits exodus is ten times any real cliff. Scaling the hazard axis to
  // it would flatten every finding on the page into a rounding error, so the
  // axis is scaled to the feature and the credits are allowed to overflow.
  const feature = points.filter((p) => p.position_sec < data.credits_start_sec);
  const maxHazard = Math.max(...feature.map((p) => p.hazard || 0), 0.001);

  const x = (sec) => PLOT.left + (sec / duration) * innerW;
  const yRet = (r) => curveBottom - r * PLOT.curveH;

  const inCliff = (sec) => data.cliffs.some((c) => sec >= c.start_sec && sec < c.end_sec);

  // retention path
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.position_sec).toFixed(1)},${yRet(p.retention).toFixed(1)}`).join("");
  const area = `${line}L${x(points.at(-1).position_sec).toFixed(1)},${curveBottom}L${x(points[0].position_sec).toFixed(1)},${curveBottom}Z`;

  const gridRows = [0, 0.25, 0.5, 0.75, 1].map((r) => `
    <line class="grid-line" x1="${PLOT.left}" y1="${yRet(r).toFixed(1)}" x2="${W - PLOT.right}" y2="${yRet(r).toFixed(1)}"/>
    <text class="axis" x="${PLOT.left - 9}" y="${(yRet(r) + 3).toFixed(1)}" text-anchor="end">${r * 100}%</text>
  `).join("");

  const ticks = [];
  for (let sec = 0; sec <= duration; sec += 120) {
    ticks.push(`<text class="axis" x="${x(sec).toFixed(1)}" y="${hazBottom + 18}" text-anchor="middle">${timecode(sec)}</text>`);
  }

  const barW = Math.max(1.2, (innerW / points.length) - 0.6);
  const bars = points.map((p) => {
    const h = Math.min(PLOT.hazardH, ((p.hazard || 0) / maxHazard) * PLOT.hazardH);
    const cls = inCliff(p.position_sec) ? "hazard-bar in-cliff" : "hazard-bar";
    const fill = inCliff(p.position_sec) ? ' style="fill:var(--danger)"' : "";
    return `<rect class="${cls}"${fill} x="${(x(p.position_sec) - barW / 2).toFixed(1)}" y="${(hazBottom - h).toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0.6, h).toFixed(1)}"/>`;
  }).join("");

  const bands = data.cliffs.map((c, i) => {
    const bx = x(c.start_sec);
    const bw = Math.max(6, x(c.end_sec) - bx);
    return `
      <g class="cliff-band" data-cliff="${c.cliff_id}" style="transition-delay:${1.2 + i * 0.14}s">
        <rect x="${bx.toFixed(1)}" y="${curveTop}" width="${bw.toFixed(1)}" height="${(hazBottom - curveTop).toFixed(1)}"
              fill="var(--danger)" opacity="0.09"/>
        <line x1="${bx.toFixed(1)}" y1="${curveTop}" x2="${bx.toFixed(1)}" y2="${hazBottom}"
              stroke="var(--danger)" stroke-width="1" stroke-dasharray="2 3" opacity="0.55"/>
        <text class="cliff-flag" x="${(bx + 4).toFixed(1)}" y="${curveTop + 12}">${c.start_timecode.slice(3)}</text>
      </g>`;
  }).join("");

  const creditsX = x(data.credits_start_sec);
  const credits = `
    <line class="credits-line" x1="${creditsX.toFixed(1)}" y1="${curveTop}" x2="${creditsX.toFixed(1)}" y2="${hazBottom}"/>
    <text class="axis" x="${(creditsX + 5).toFixed(1)}" y="${hazBottom - 4}">credits</text>`;

  svg.setAttribute("viewBox", `0 0 ${W} ${hazBottom + 30}`);
  svg.innerHTML = `
    <defs>
      <linearGradient id="curveFill" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%"   stop-color="var(--ink)" stop-opacity="0.14"/>
        <stop offset="100%" stop-color="var(--ink)" stop-opacity="0"/>
      </linearGradient>
    </defs>
    ${gridRows}
    ${bands}
    ${credits}
    <path class="curve-area" d="${area}"/>
    <path class="curve-line" id="curvePath" d="${line}"/>
    <text class="axis" x="${PLOT.left - 9}" y="${hazTop + 8}" text-anchor="end">haz</text>
    ${bars}
    ${ticks.join("")}
  `;

  const path = $("#curvePath");
  const length = path.getTotalLength();
  path.style.setProperty("--len", length);
  path.classList.add("draw");

  requestAnimationFrame(() => {
    $$(".cliff-band", svg).forEach((band) => band.classList.add("shown"));
  });
}

/* --- cliffs -------------------------------------------------------------- */

function renderCliffs(cliffs) {
  if (!cliffs.length) {
    $("#cliffs").innerHTML = `<div class="banner info">No significant cliffs in this title. The audience stayed.</div>`;
    return;
  }

  $("#cliffs").innerHTML = cliffs.map((c) => `
    <article class="cliff" data-id="${c.cliff_id}">
      <div class="cliff-top">
        <span class="cliff-time">${c.start_timecode.slice(3)}–${c.end_timecode.slice(3)}</span>
        <span class="cliff-lift">${c.lift.toFixed(1)}× normal</span>
        <span class="cause-tag" data-role="cause">analysing…</span>
        <span class="cliff-hours">
          <b>${commas(c.recoverable_watch_hours)}</b>
          <span>watch hours</span>
        </span>
      </div>
      <div class="cliff-body"><div>
        <div class="evidence" data-role="evidence">
          <div class="skeleton" style="height:13px;width:80%"></div>
          <div class="skeleton" style="height:13px;width:64%"></div>
        </div>
      </div></div>
    </article>
  `).join("");

  $$("#cliffs .cliff").forEach((el) => {
    el.addEventListener("click", () => toggleCliff(el));
  });

  // Open the worst one and let it explain itself; a blank panel teaches nothing.
  toggleCliff($("#cliffs .cliff"));

  // The rest are fetched anyway. They are three cheap queries, they run in
  // parallel, and a row that still says "analysing" once the page has settled
  // reads as broken rather than as lazy.
  investigateAll(cliffs);
}

async function investigateAll(cliffs) {
  // One request for all of them. Fanning out one request per cliff queues a
  // dozen queries each down a single MCP pipe and times the whole page out.
  let investigations = [];
  try {
    investigations = await getJson(`/api/investigate/${state.titleId}`);
  } catch (err) {
    $("#previewTitle").textContent = state.title.title.title_name;
    $("#previewRows").innerHTML = `<div class="banner err">${escapeHtml(err.message)}</div>`;
    return;
  }

  const byId = new Map(investigations.map((inv) => [inv.cliff_id, inv]));
  const results = cliffs.map((c) => [c, byId.get(c.cliff_id) || null]);

  results.forEach(([c, data]) => {
    if (!data) return;
    const el = $(`#cliffs .cliff[data-id="${c.cliff_id}"]`);
    if (el && !el.dataset.loaded) {
      el.dataset.loaded = "1";
      renderEvidence(el, data);
    }
    c.investigation = data;
  });

  renderPreview(results);
}


function toggleCliff(el) {
  if (!el) return;
  const wasOpen = el.classList.contains("open");
  $$("#cliffs .cliff").forEach((other) => other.classList.remove("open"));
  if (wasOpen) return;
  el.classList.add("open");

  // Evidence arrives from the batch call; nothing to fetch here.
  animateMeters(el);
}

function renderEvidence(el, data) {
  const cause = data.proposed_cause || "unknown";
  el.classList.add(`cause-${cause}`);

  const tag = $('[data-role="cause"]', el);
  tag.textContent = cause === "unknown" ? "needs the film" : cause;

  const signals = Object.entries(data.cohorts || {})
    .flatMap(([, list]) => list)
    .sort((a, b) => b.concentration - a.concentration)
    .slice(0, 4);

  const cohortHtml = signals.length ? `
    <div class="cohort-grid">
      ${signals.map((s) => `
        <div class="cohort">
          <span class="label"><b>${escapeHtml(s.value)}</b> · ${escapeHtml(s.dimension)}</span>
          <span class="x">${s.concentration.toFixed(2)}×</span>
          <span class="meter"><i data-w="${Math.min(100, (s.concentration / 3) * 100).toFixed(1)}"></i></span>
        </div>`).join("")}
    </div>` : "";

  $('[data-role="evidence"]', el).innerHTML =
    (data.evidence || []).map((line) => `<li>${escapeHtml(line)}</li>`).join("") + cohortHtml;

  animateMeters(el);
}

function animateMeters(el) {
  requestAnimationFrame(() => {
    $$(".cohort .meter i", el).forEach((bar) => { bar.style.width = `${bar.dataset.w}%`; });
  });
}

/* --- the agent ----------------------------------------------------------- */

const STEP_LABELS = {
  __opening:           ["Reading the brief", "planning the investigation"],
  find_walkouts:       ["Finding the cliffs", "survival analysis over every heartbeat"],
  investigate_walkout: ["Slicing the audience", "device · build · CDN · locale · subtitles"],
  watch_scene:         ["Watching the film", "Gemini reads that window of video"],
  run_query:           ["Asking the warehouse", "direct SQL through the MCP server"],
  list_tables:         ["Reading the schema", "walkout.*"],
  list_databases:      ["Listing databases", "clickhouse mcp"],
};

function addStep(name, args) {
  const [what, detail] = STEP_LABELS[name] || [name, ""];
  const extra = args && args.cliff_id ? ` · cliff ${args.cliff_id}` : "";
  const step = document.createElement("div");
  step.className = "step running";
  step.dataset.name = name + (args?.cliff_id || "");
  step.innerHTML = `
    <div class="rail"><div class="dot"></div></div>
    <div><div class="what">${escapeHtml(what)}</div><div class="detail">${escapeHtml(detail + extra)}</div></div>`;
  const trace = $("#trace");
  trace.appendChild(step);
  trace.scrollTop = trace.scrollHeight;
  return step;
}

function runAgent() {
  if (state.running || !state.titleId) return;
  state.running = true;

  const button = $("#run");
  button.disabled = true;
  button.innerHTML = 'Investigating<span class="arrow">…</span>';

  const trace = $("#trace");
  trace.innerHTML = "";
  const verdict = $("#verdict");
  verdict.hidden = true;
  verdict.innerHTML = "";

  let answer = "";
  const opening = addStep("__opening", null);
  const source = new EventSource(`/api/agent/${state.titleId}`);

  const finish = (message, isError) => {
    source.close();
    state.running = false;
    button.disabled = false;
    button.innerHTML = 'Investigate again <span class="arrow">→</span>';
    $$("#trace .step").forEach((s) => s.classList.replace("running", "done"));
    if (message) {
      trace.insertAdjacentHTML("beforeend",
        `<div class="banner ${isError ? "err" : "info"}">${escapeHtml(message)}</div>`);
    }
  };

  source.onmessage = (message) => {
    const event = JSON.parse(message.data);

    if (event.type === "tool_call") {
      opening.classList.replace("running", "done");
      addStep(event.name, event.args);
      return;
    }

    if (event.type === "tool_result") {
      const open = $$("#trace .step.running").find((s) => s.dataset.name.startsWith(event.name));
      if (open) open.classList.replace("running", "done");
      return;
    }

    if (event.type === "text") {
      answer += event.text;
      verdict.hidden = false;
      verdict.innerHTML = markdown(answer);
      verdict.scrollTop = verdict.scrollHeight;
      return;
    }

    if (event.type === "error") { finish(event.message, true); return; }
    if (event.type === "done")  { finish(null, false); }
  };

  source.onerror = () => {
    if (state.running) finish("The stream dropped. The agent may still be running on the server.", true);
  };
}

/* --- boot ---------------------------------------------------------------- */

/* A silent client-side failure on a demo looks like a broken product. If
   something throws, say so on the page rather than only in a console nobody
   has open. */
function reportFailure(message) {
  const existing = $("#clientError");
  if (existing) { existing.textContent = message; return; }
  const banner = document.createElement("div");
  banner.id = "clientError";
  banner.className = "banner err";
  banner.style.cssText = "position:fixed;bottom:16px;left:16px;right:16px;max-width:520px;z-index:99";
  banner.textContent = message;
  document.body.appendChild(banner);
}

window.addEventListener("error", (e) => reportFailure(`Client error: ${e.message}`));
window.addEventListener("unhandledrejection", (e) => reportFailure(`Client error: ${e.reason}`));


initTheme();
splitHeadline();
watchScroll();
loadTitles();

$("#run").addEventListener("click", runAgent);
$("#jump").addEventListener("click", () => {
  $("#console").scrollIntoView({ behavior: "smooth", block: "start" });
});

/* --- hero preview -------------------------------------------------------- */

const DELIVERY_DIMENSIONS = ["device", "platform", "app_version", "cdn_pop"];

/* The deterministic layer will not name a story problem from telemetry alone,
   and that refusal is the point of the product rather than a gap in it. So the
   preview says what the numbers have actually ruled out, and leaves the rest
   to the agent. */
const PREVIEW_LINE = {
  technical:    (inv) => `delivery fault in ${deliveryCohort(inv) || "one build"} \u2014 do not recut`,
  localization: () => "no subtitle track for these viewers",
  unknown:      () => "clean playback, no cohort signal",
  pacing:       () => "the scene itself is losing them",
  story:        () => "the scene itself is losing them",
};

const PREVIEW_TAG = {
  technical: "delivery", localization: "localization",
  unknown: "needs the film", pacing: "pacing", story: "story",
};

function renderPreview(results) {
  const data = state.title;
  if (!data) return;

  $("#previewTitle").textContent = data.title.title_name.replace(/\s*\(.*\)$/, "");
  $("#previewCount").textContent = `${commas(data.sessions)} sessions`;

  $("#previewRows").innerHTML = results.map(([c, investigation], i) => {
    const cause = investigation?.proposed_cause || "unknown";
    const line = (PREVIEW_LINE[cause] || PREVIEW_LINE.unknown)(investigation);
    return `
      <div class="preview-row cause-${cause}" style="animation-delay:${0.05 + i * 0.09}s">
        <span class="tc">${c.start_timecode.slice(3)}</span>
        <span class="verdictline">${escapeHtml(line)}</span>
        <span class="cause-tag">${PREVIEW_TAG[cause] || cause}</span>
      </div>`;
  }).join("");
}


/* A localization finding must never be labelled with an app build, and a
   delivery finding must never be labelled with a locale -- naming the wrong
   cohort sends the fix to the wrong team, which is the exact failure this
   product exists to prevent. */
function deliveryCohort(investigation) {
  if (investigation?.worst_delivery_cohort) return investigation.worst_delivery_cohort;
  return topCohort(investigation, DELIVERY_DIMENSIONS);
}

function topCohort(investigation, dimensions) {
  const signals = Object.entries(investigation?.cohorts || {})
    .filter(([dim]) => !dimensions || dimensions.includes(dim))
    .flatMap(([, list]) => list);
  if (!signals.length) return null;
  return signals.sort((a, b) => b.concentration - a.concentration)[0].value;
}

