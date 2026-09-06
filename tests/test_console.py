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

import pytest

from walkout.config import PROJECT_ROOT

STATIC = PROJECT_ROOT / "src" / "walkout" / "web" / "static"

HTML = (STATIC / "index.html").read_text()
JS = (STATIC / "app.js").read_text()

DOCS_HTML = (STATIC / "docs.html").read_text()
DOCS_JS = (STATIC / "docs.js").read_text()

# Named so a failure says "docs" rather than printing both files into the
# assertion message, which is what happens if pytest has to derive an id.
PAGES = [("console", HTML, JS), ("docs", DOCS_HTML, DOCS_JS)]
PAGE_IDS = [page[0] for page in PAGES]

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
# Bare `window` methods -- the page calls them unqualified, as everyone does.
BROWSER_GLOBALS = {"fetch", "setTimeout", "setInterval", "clearTimeout",
                   "clearInterval", "requestAnimationFrame", "addEventListener",
                   "removeEventListener", "matchMedia", "resolve", "reject",
                   "escape"}


@pytest.mark.parametrize("name, markup, script", PAGES, ids=PAGE_IDS)
def test_every_selector_has_an_element(name, markup, script) -> None:
    ids = (set(MARKUP_ID.findall(markup))
           | set(MARKUP_ID.findall(script))
           | set(SCRIPTED_ID.findall(script)))
    missing = sorted({m for m in SELECTOR.findall(script) if m not in ids})
    assert not missing, f"{name} reaches for ids that do not exist: {missing}"


@pytest.mark.parametrize("name, markup, script", PAGES, ids=PAGE_IDS)
def test_every_function_called_is_defined(name, markup, script) -> None:
    """Catches the edit that removes a function but not its callers."""
    defined = set(re.findall(r"function\s+([A-Za-z_][\w]*)", script))
    defined |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_][\w]*)\s*=", script))
    missing = sorted(set(BARE_CALL.findall(script)) - defined - KEYWORDS - BROWSER_GLOBALS)
    assert not missing, f"{name} calls functions that are not defined: {missing}"


@pytest.mark.parametrize("name, markup, script", PAGES, ids=PAGE_IDS)
def test_every_internal_anchor_has_a_target(name, markup, script) -> None:
    """A contents rail pointing at a section that does not exist is dead furniture."""
    ids = set(MARKUP_ID.findall(markup))
    anchors = {a for a in re.findall(r'href="#([A-Za-z0-9_-]+)"', markup) if a}
    missing = sorted(anchors - ids)
    assert not missing, f"{name} links to anchors that do not exist: {missing}"


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


def test_api_key_mode_does_not_demand_a_cloud_project(monkeypatch) -> None:
    """The deploy came up healthy and then failed on the first model call.

    `GOOGLE_CLOUD_PROJECT` was required unconditionally but read by nothing.
    In API-key mode there is no project to name, so demanding one turned a
    correctly configured deployment into a 500 the moment anyone pressed a
    button. Health checks do not touch a model, so nothing caught it.
    """
    from walkout.config import GoogleConfig

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "false")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    config = GoogleConfig.from_env()
    assert config.use_vertex is False
    assert config.project == ""
    assert config.model


def test_vertex_mode_still_requires_a_project(monkeypatch) -> None:
    from walkout.config import ConfigError, GoogleConfig

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    try:
        GoogleConfig.from_env()
    except ConfigError as exc:
        assert "GOOGLE_CLOUD_PROJECT" in str(exc)
    else:
        raise AssertionError("Vertex mode should demand a project")
