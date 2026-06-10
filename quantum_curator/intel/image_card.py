"""Pillow-based renderer for the Bluesky daily-summary image card.

Why this exists
---------------
``render_bluesky()`` in ``daily_summary.py`` has at most 300 graphemes
to work with — barely enough for two TL;DR bullets plus the tag + CTA
suffix. The Implications and Attention sections of the structured
summary never make it into the Bluesky text path. The image card is
the spillover surface: a single PNG attached to the post via
``app.bsky.embed.images`` carrying the full structured payload (TL;DR
+ Implications + Attention + Tags + date + qrater.org footer).

Design notes
------------
* Canvas: 1000x1000 PNG, light background, dark text. Matches the
  high-contrast feel users expect from infographic cards on Bluesky.
* Font: Pillow's bundled ``ImageFont.load_default()`` — keeps the
  dependency footprint to ``pillow`` alone. A bundled TTF is a clean
  follow-up but not blocking.
* Layout: top-down, fixed sections, generous gutters. Long bullets
  word-wrap to the canvas width; overflow past the canvas height is
  truncated with a "(more on qrater.org)" trailer rather than ever
  silently dropping content.
* Output: raw PNG bytes. The caller (``bluesky.py``) uploads via the
  same blob endpoint used for thumbnails.

The module is import-safe — ``PIL`` is imported at function call time
so the rest of the intel package keeps working on a Pillow-less env
(the CLI guards on ``share-intel-summary`` and falls back to text).
"""

from __future__ import annotations

import io
from typing import Iterable


# --- layout constants (px) ---
CANVAS_W = 1000
CANVAS_H = 1000

BG_COLOR = (248, 250, 252)        # slate-50, near-white
PANEL_COLOR = (255, 255, 255)
BORDER_COLOR = (203, 213, 225)    # slate-300
HEADER_COLOR = (15, 23, 42)       # slate-900
TEXT_COLOR = (30, 41, 59)         # slate-800
MUTED_COLOR = (100, 116, 139)     # slate-500
ACCENT_COLOR = (99, 102, 241)     # indigo-500 (matches Qrater --primary)
TAG_BG = (224, 231, 255)          # indigo-100
TAG_FG = (67, 56, 202)            # indigo-700

# Vertical spacing
MARGIN_X = 48
MARGIN_TOP = 48
MARGIN_BOTTOM = 48
SECTION_GAP = 24
BULLET_GAP = 10
HEADER_GAP = 20

# Per-line text height; default font is small (~11px) so we scale via
# multiline rendering with a generous line height.
LINE_HEIGHT = 18
HEADER_LINE_HEIGHT = 28
TITLE_LINE_HEIGHT = 22

# Max chars per wrapped line at the default font; tuned for canvas
# width 1000 - 2*MARGIN_X = 904 px.
WRAP_WIDTH_BODY = 95
WRAP_WIDTH_HEADER = 60


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word-wrap. No external dep (textwrap.wrap is fine but
    this lets us treat ascii-as-display-cells which matches the
    default font's narrow glyphs).
    """
    if not text:
        return [""]
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if not cur:
            cur = w
            continue
        if len(cur) + 1 + len(w) <= width:
            cur = cur + " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_section(
    draw,
    title: str,
    bullets: Iterable[str],
    *,
    x: int,
    y: int,
    width: int,
) -> int:
    """Draw a titled section of bullet lines. Returns the new y cursor
    (the y just below the last bullet). If ``bullets`` is empty the
    section is skipped entirely (title not drawn).
    """
    bullets = [b for b in bullets if b]
    if not bullets:
        return y

    # Section title
    draw.text((x, y), title.upper(), fill=ACCENT_COLOR)
    y += TITLE_LINE_HEIGHT

    for b in bullets:
        wrapped = _wrap(f"• {b}", WRAP_WIDTH_BODY)
        for i, line in enumerate(wrapped):
            indent = x if i == 0 else x + 12
            draw.text((indent, y), line, fill=TEXT_COLOR)
            y += LINE_HEIGHT
        y += BULLET_GAP

    return y


def _draw_tags(draw, tags: Iterable[str], *, x: int, y: int) -> int:
    """Draw the tag row (text-only chips). Returns new y."""
    tags = [t for t in tags if t]
    if not tags:
        return y
    line = "  ".join(f"#{t}" for t in tags)
    wrapped = _wrap(line, WRAP_WIDTH_BODY)
    for w_line in wrapped:
        draw.text((x, y), w_line, fill=TAG_FG)
        y += LINE_HEIGHT
    return y


def render_summary_card(payload: dict, summary_date: str) -> bytes:
    """Render the structured daily-summary payload to a PNG.

    Parameters
    ----------
    payload:
        The dict returned by ``build_daily_summary()`` — must have
        ``tldr``, ``implications``, ``attention``, ``tags`` keys (empty
        lists are fine). Missing keys are treated as empty.
    summary_date:
        YYYY-MM-DD string for the header. Caller decides timezone;
        ``share_intel_summary`` uses the UTC date.

    Returns
    -------
    bytes
        Raw PNG bytes ready for ``com.atproto.repo.uploadBlob``.

    Raises
    ------
    ImportError
        If Pillow is not installed. Callers should guard with
        try/except and fall back to text-only posting.
    """
    # Local import so the intel package stays import-safe on Pillow-less envs.
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Outer panel: subtle inner border
    draw.rectangle(
        [(MARGIN_X - 8, MARGIN_TOP - 8), (CANVAS_W - MARGIN_X + 8, CANVAS_H - MARGIN_BOTTOM + 8)],
        fill=PANEL_COLOR,
        outline=BORDER_COLOR,
        width=2,
    )

    x = MARGIN_X
    y = MARGIN_TOP
    inner_width = CANVAS_W - (2 * MARGIN_X)

    # Header — "Quantum Intel" / date
    draw.text((x, y), "QUANTUM INTEL", fill=HEADER_COLOR)
    y += HEADER_LINE_HEIGHT
    draw.text((x, y), summary_date, fill=MUTED_COLOR)
    y += HEADER_LINE_HEIGHT + HEADER_GAP

    # Sections
    y = _draw_section(
        draw, "TL;DR", payload.get("tldr") or [],
        x=x, y=y, width=inner_width,
    )
    if y > MARGIN_TOP + HEADER_LINE_HEIGHT * 2 + HEADER_GAP:
        y += SECTION_GAP // 2

    y = _draw_section(
        draw, "Implications", payload.get("implications") or [],
        x=x, y=y, width=inner_width,
    )
    y += SECTION_GAP // 2

    y = _draw_section(
        draw, "Attention", payload.get("attention") or [],
        x=x, y=y, width=inner_width,
    )

    # Tags row
    tags = payload.get("tags") or []
    if tags:
        y += SECTION_GAP // 2
        y = _draw_tags(draw, tags, x=x, y=y)

    # Overflow guard: if we've run past the canvas, draw an
    # "(more on qrater.org)" marker at a safe-y. Never silently drop.
    # (Default-font rendering rarely overflows at <=4 bullets/section,
    # but long bullets can push us close.)
    footer_y = CANVAS_H - MARGIN_BOTTOM - LINE_HEIGHT
    if y >= footer_y:
        # The content already filled or overran the footer slot;
        # the prose may be partly clipped — surface that to the viewer.
        draw.text(
            (x, footer_y - LINE_HEIGHT),
            "(more on qrater.org)",
            fill=MUTED_COLOR,
        )

    # Footer right-aligned: "qrater.org"
    footer_text = "qrater.org"
    # Approximate width via char count (default font is monospace-ish);
    # for default font this is good enough to right-justify visually.
    approx_w = len(footer_text) * 6
    draw.text((CANVAS_W - MARGIN_X - approx_w, footer_y), footer_text, fill=ACCENT_COLOR)

    # Bluesky's blob limit is 1MB; PNGs of this canvas at this palette
    # come out well under 100KB so no JPEG fallback is wired here.
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
