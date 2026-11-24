"""Checks a real browser page must pass: fit, type floor, contrast, clickable elements.

Each function takes a Playwright ``Page`` and returns the problems it found, as sentences, so a
test asserts the list is empty and a planted fault shows up in words. Nothing here imports
Playwright, so the application itself never depends on it.
"""

from __future__ import annotations

from typing import Any

TYPE_FLOOR_PX = 12.0
CONTRAST_MIN = 4.5
FOCUS_RING_MIN_PX = 2.0
MAX_TILES = 3

RECORD_CLICKS = """
(() => {
  window.__clickTargets = [];
  const original = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, ...rest) {
    if (type === 'click' && this instanceof Element) window.__clickTargets.push(this);
    return original.call(this, type, ...rest);
  };
})();
"""

_ANSWER = """
() => {
  const answer = document.querySelector('[data-hook="answer"]');
  const root = document.documentElement;
  return {
    hasAnswer: !!answer,
    sentence: answer ? (answer.querySelector('[data-hook="sentence"]')?.innerText ?? '') : '',
    tiles: document.querySelectorAll('[data-hook="tile"]').length,
    exhibits: document.querySelectorAll('[data-hook="exhibit"]').length,
    answerOverflow: answer ? answer.scrollHeight - answer.clientHeight : 0,
    pageOverflowY: root.scrollHeight - window.innerHeight,
    pageOverflowX: root.scrollWidth - window.innerWidth,
    answerBottom: answer ? answer.getBoundingClientRect().bottom : 0,
    innerHeight: window.innerHeight,
  };
}
"""

_TEXT_NODES = """
() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const text = node.textContent.trim();
    const el = node.parentElement;
    if (!text || !el || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName)) continue;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const box = el.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) continue;
    out.push({ text: text.slice(0, 60), tag: el.tagName, size: parseFloat(style.fontSize), color: style.color, bg: effectiveBackground(el) });
  }
  function effectiveBackground(el) {
    for (let e = el; e; e = e.parentElement) {
      const c = getComputedStyle(e).backgroundColor;
      const m = c.match(/rgba?\\(([^)]+)\\)/);
      if (!m) continue;
      const parts = m[1].split(',').map(Number);
      if (parts.length === 3 || parts[3] > 0.99) return `rgb(${parts[0]}, ${parts[1]}, ${parts[2]})`;
    }
    return 'rgb(255, 255, 255)';
  }
  return out;
}
"""  # noqa: E501

_CLICKABLES = """
() => {
  const seen = new Set();
  const list = [];
  const add = (el, why) => { if (!seen.has(el)) { seen.add(el); list.push([el, why]); } };
  document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, summary, label[for]').forEach(e => add(e, 'control'));
  document.querySelectorAll('[onclick], [role=button], [role=link], [tabindex]:not([tabindex="-1"])').forEach(e => add(e, 'handler'));
  (window.__clickTargets || []).forEach(e => add(e, 'listener'));
  document.querySelectorAll('body *').forEach(e => { if (getComputedStyle(e).cursor === 'pointer') add(e, 'cursor'); });
  return list.filter(([e]) => {
    const s = getComputedStyle(e);
    const b = e.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && (b.width > 0 || b.height > 0);
  }).map(([e, why], i) => {
    e.setAttribute('data-sweep-id', String(i));
    const s = getComputedStyle(e);
    const tag = e.tagName.toLowerCase();
    const labelled = e.labels && e.labels.length ? [...e.labels].map(l => l.innerText.trim()).join(' ') : '';
    return {
      id: i, tag, why, type: e.getAttribute('type') || '', name: e.getAttribute('name') || '',
      text: (e.innerText || e.value || '').trim().slice(0, 40),
      cursor: s.cursor, title: (e.getAttribute('title') || '').trim(), label: labelled,
      ariaLabel: (e.getAttribute('aria-label') || '').trim(), disabled: !!e.disabled,
      href: e.getAttribute('href'),
    };
  });
}
"""  # noqa: E501

_ACTIVE = """
() => {
  const e = document.activeElement;
  if (!e || e === document.body) return null;
  const s = getComputedStyle(e);
  return { id: Number(e.getAttribute('data-sweep-id')), name: e.getAttribute('name') || '',
           type: e.getAttribute('type') || '', outlineWidth: parseFloat(s.outlineWidth),
           outlineStyle: s.outlineStyle };
}
"""

_CLIPPED = """
() => [...document.querySelectorAll('body *')].filter(e => {
  const s = getComputedStyle(e);
  const cut = s.overflowX === 'hidden' || s.textOverflow === 'ellipsis';
  return cut && e.scrollWidth > e.clientWidth + 1 && !e.getAttribute('title');
}).map(e => `<${e.tagName.toLowerCase()}> '${(e.innerText || '').trim().slice(0, 40)}'`)
"""

POINTER_TAGS = {"a", "button", "select", "summary", "label"}
POINTER_INPUT_TYPES = {"radio", "checkbox", "submit", "button"}
TITLED_TAGS = {"a", "button", "summary"}


def luminance(rgb: str) -> float:
    """Return the relative luminance of a CSS ``rgb(r, g, b)`` colour.

    Args:
        rgb: A colour as the browser reports it, for example ``rgb(27, 36, 48)``.

    Returns:
        The luminance from 0 (black) to 1 (white).
    """
    inner = rgb[rgb.index("(") + 1 : rgb.rindex(")")]
    channels = [float(x) / 255 for x in inner.split(",")[:3]]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the WCAG contrast ratio of two CSS colours, from 1 to 21."""
    a, b = luminance(foreground), luminance(background)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def answer_problems(page: Any, *, tall_exhibit_allowed: bool = False) -> list[str]:
    """Check that the page opens on one sentence, at most three tiles and one exhibit, and fits.

    Args:
        page: The Playwright page, loaded.
        tall_exhibit_allowed: Whether the page may scroll below the answer (a long table).

    Returns:
        What is wrong, in words; empty when the page is as the design says.
    """
    found: dict[str, Any] = page.evaluate(_ANSWER)
    problems = []
    if not found["hasAnswer"] or not found["sentence"].strip():
        problems.append("The page has no answer sentence.")
    if found["tiles"] > MAX_TILES:
        problems.append(f"The page has {found['tiles']} tiles; the most is {MAX_TILES}.")
    if found["exhibits"] != 1:
        problems.append(f"The page has {found['exhibits']} exhibits; it needs one.")
    if found["answerOverflow"] > 1:
        problems.append("The answer region has a scrollbar.")
    if found["pageOverflowX"] > 1:
        problems.append(f"The page is {found['pageOverflowX']} pixels too wide.")
    if found["answerBottom"] > found["innerHeight"]:
        problems.append("The answer does not fit above the fold.")
    if not tall_exhibit_allowed and found["pageOverflowY"] > 1:
        problems.append(f"The page scrolls by {found['pageOverflowY']} pixels.")
    return problems


def type_floor_problems(page: Any) -> list[str]:
    """Return every text node set below the 12 pixel type floor."""
    nodes = page.evaluate(_TEXT_NODES)
    return [
        f"'{n['text']}' in <{n['tag'].lower()}> is {n['size']:g} pixels."
        for n in nodes
        if n["size"] < TYPE_FLOOR_PX
    ]


def contrast_problems(page: Any) -> list[str]:
    """Return every text node whose colour on its surface is under 4.5 to 1."""
    nodes = page.evaluate(_TEXT_NODES)
    out = []
    for n in nodes:
        ratio = contrast_ratio(n["color"], n["bg"])
        if ratio < CONTRAST_MIN:
            out.append(f"'{n['text']}' is {ratio:.2f} to 1 ({n['color']} on {n['bg']}).")
    return out


def clickable_problems(page: Any) -> list[str]:
    """Check every clickable element: right element, pointer, name, keyboard reach, focus ring.

    Args:
        page: The Playwright page, loaded with ``RECORD_CLICKS`` added as an init script.

    Returns:
        What is wrong, in words.
    """
    items: list[dict[str, Any]] = page.evaluate(_CLICKABLES)
    problems = []
    for item in items:
        name = f"<{item['tag']}> '{item['text']}'"
        is_input = item["tag"] in {"input", "textarea", "select"}
        if item["why"] in {"handler", "listener", "cursor"} and item["tag"] not in {"a", "button"}:
            if not (is_input or item["tag"] in {"summary", "label"}):
                problems.append(f"{name} is clickable but is neither a link nor a button.")
        if item["tag"] == "a" and not item["href"]:
            problems.append(f"{name} is a link without an address.")
        if item["tag"] in TITLED_TAGS and not item["title"]:
            problems.append(f"{name} has no title naming its action.")
        if is_input and not (item["label"] or item["ariaLabel"] or item["title"]):
            problems.append(f"{name} has no label.")
        wants_pointer = item["tag"] in POINTER_TAGS or item["type"] in POINTER_INPUT_TYPES
        if wants_pointer and not item["disabled"] and item["cursor"] != "pointer":
            if not (item["tag"] == "label" and item["cursor"] == "default"):
                problems.append(f"{name} does not show a pointer cursor ({item['cursor']}).")
    focusable = {
        i["id"]: i
        for i in items
        if not i["disabled"] and i["tag"] != "label" and i["type"] != "hidden"
    }
    reached: dict[int, dict[str, Any]] = {}
    page.evaluate("() => document.body.focus()")
    for _ in range(len(focusable) + 40):
        page.keyboard.press("Tab")
        active = page.evaluate(_ACTIVE)
        if active is None:
            continue
        reached.setdefault(active["id"], active)
        if len(reached) >= len(focusable):
            break
    radio_groups = {r["name"] for r in reached.values() if r["type"] == "radio"}
    for ident, item in focusable.items():
        name = f"<{item['tag']}> '{item['text']}'"
        got = reached.get(ident)
        if got is None:
            if item["type"] == "radio" and item["name"] in radio_groups:
                continue
            problems.append(f"{name} cannot be reached with the Tab key.")
            continue
        if got["outlineStyle"] == "none" or got["outlineWidth"] < FOCUS_RING_MIN_PX:
            problems.append(f"{name} has no visible focus ring of {FOCUS_RING_MIN_PX:g} pixels.")
    return problems


def clipped_problems(page: Any) -> list[str]:
    """Return every element whose text is cut off without its full text in a title."""
    return [
        f"{item} is cut off and has no title with the full text."
        for item in page.evaluate(_CLIPPED)
    ]
