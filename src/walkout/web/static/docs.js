/* Documentation page behaviour.

   Two things only: the theme has to match the rest of the site, and the
   contents rail has to say where you are. Everything else on this page is
   text, and text does not need JavaScript. */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* --- theme ---------------------------------------------------------------
   Same key as the console, so switching here and going back does not flip the
   site under you. Reads are wrapped because storage throws outright in some
   privacy modes rather than merely returning nothing. */

const THEME_KEY = "walkout:theme";

function storedTheme() {
  try {
    return localStorage.getItem(THEME_KEY);
  } catch {
    return null;
  }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* private window */ }
}

function initTheme() {
  const fromUrl = new URLSearchParams(location.search).get("theme");
  const system = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  applyTheme(fromUrl || storedTheme() || system);

  $("#theme").addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
}

/* --- contents rail -------------------------------------------------------
   Highlights the section you are actually reading. The rule is "the last
   heading you scrolled past", which is what a reader means by where they are;
   an observer that lights up whichever section merely overlaps the viewport
   flickers between two of them at every boundary. */

function watchSections() {
  const links = new Map(
    $$(".toc a").map((a) => [a.getAttribute("href").slice(1), a]));
  const sections = $$(".doc-body section").filter((s) => links.has(s.id));
  if (!sections.length) return;

  let current = "";

  const update = () => {
    const line = window.scrollY + 140;      // just under the sticky nav
    let active = sections[0].id;
    for (const section of sections) {
      if (section.offsetTop <= line) active = section.id;
    }
    if (active === current) return;
    links.get(current)?.classList.remove("active");
    links.get(active)?.classList.add("active");
    current = active;
  };

  // Coalesce to one update per frame; scroll fires far faster than paint.
  let queued = false;
  addEventListener("scroll", () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; update(); });
  }, { passive: true });

  addEventListener("resize", update, { passive: true });
  update();
}

/* --- nav shadow on scroll, matching the console -------------------------- */

function watchNav() {
  const nav = $("#nav");
  const update = () => nav.classList.toggle("scrolled", window.scrollY > 8);
  addEventListener("scroll", update, { passive: true });
  update();
}

initTheme();
watchSections();
watchNav();
