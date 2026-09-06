"""The console's JavaScript and its HTML have to agree about what exists.

There is no build step here -- deliberately, so the image stays Python-only and
nothing can break at 2am before a deadline -- which means nothing checks that
`$("#reading")` matches an element until a browser runs it. A missing id is a
silent failure: the page renders, the console logs, and the visitor sees a
section that never fills in.

That has happened once already, when an edit deleted a function that was still
being called. These tests are cheap and would have caught it.
"""

from __future__ import annotations

import re

from walkout.config import PROJECT_ROOT

STATIC = PROJECT_ROOT / "src" / "walkout" / "web" / "static"

HTML = (STATIC / "index.html").read_text()
JS = (STATIC / "app.js").read_text()

# `$("#thing")` and `$$("#thing .child")` -- take the id, drop any descendant.
SELECTOR = re.compile(r'\$\$?\("#([A-Za-z0-9_-]+)')
MARKUP_ID = re.compile(r'id="([A-Za-z0-9_-]+)"')
# Elements the script builds itself: `banner.id = "clientError"`, and ids
# written into the markup the script renders (the chart is an SVG template).
SCRIPTED_ID = re.compile(r'\.id\s*=\s*"([A-Za-z0-9_-]+)"')

# A call on a bare identifier: `foo(`, never `x.foo(`. Excluding method calls
# structurally rather than by name is what keeps this test from decaying into a
# hand-maintained list of every DOM method the page happens to use.
BARE_CALL = re.compile(r"(?<![.\w$])([a-z][A-Za-z0-9_]*)\s*\(")

KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "typeof", "function", "var"}
BROWSER_GLOBALS = {"fetch", "setTimeout", "setInterval", "clearTimeout",
                   "requestAnimationFrame", "resolve", "reject", "escape"}


def test_every_selector_has_an_element() -> None:
    ids = (set(MARKUP_ID.findall(HTML))
           | set(MARKUP_ID.findall(JS))
           | set(SCRIPTED_ID.findall(JS)))
    missing = sorted({m for m in SELECTOR.findall(JS) if m not in ids})
    assert not missing, f"app.js reaches for ids that do not exist: {missing}"


def test_every_function_called_is_defined() -> None:
    """Catches the edit that removes a function but not its callers."""
    defined = set(re.findall(r"function\s+([A-Za-z_][\w]*)", JS))
    defined |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_][\w]*)\s*=", JS))
    missing = sorted(set(BARE_CALL.findall(JS)) - defined - KEYWORDS - BROWSER_GLOBALS)
    assert not missing, f"app.js calls functions that are not defined: {missing}"


def test_the_film_is_actually_on_the_page() -> None:
    """The product claims a model watches the film; the film should be visible.

    It was not, for the whole first version of this console -- every number was
    there and the thing the numbers were about was nowhere.
    """
    assert 'id="player"' in HTML
    assert "video_uri" in JS


def test_the_console_reads_as_numbered_steps() -> None:
    """Where, then what was on screen, then why -- in that order."""
    stages = re.findall(r'<span class="stage-n">(\d)</span>', HTML)
    assert stages == ["1", "2", "3"], stages
