"""Draws the architecture and the delivery steps of the project as images for the README.

Diagram as code: the layers, steps and numbers of this project are written in the specification below; the
drawing engine renders them to SVG (sharp, editable in any design tool) and to PNG with Playwright (what
GitHub shows). Change the specification and run the script again to update the images.

    python scripts/build_architecture.py      # writes docs/images/architecture.(svg|png) and delivery_steps.(svg|png)
"""

from __future__ import annotations

from pathlib import Path

# ==========================================================================================================
# Project specification: colours, layers, code, results and delivery steps of this project
# ==========================================================================================================
PALETTE = {"accent": "#F59E0B", "dark": "#B45309", "light": "#FCD34D", "second": "#5EEAD4", "third": "#A5B4FC"}

HEADER = {
    "icon": "migrate",
    "title": "Legacy Banking Data Migration",
    "stack": "Python · SQL Server · PostgreSQL · MongoDB · FastAPI · Power BI",
    "flow": "legacy core banking → extract → transform → load → reconciliation gate → apps",
    "steps_title": "From the legacy core to the cut-over",
}

# Every run, in order: what the scheduler (or the rehearsal) calls
ORCHESTRATION = {
    "icon": "clock",
    "label": "ORCHESTRATION",
    "title": "One run per business day until the cut-over",
    "command": "python -m migration run",
    "steps": ["1  Extract", "2  Transform", "3  Load", "4  Reconcile"],
    "status": [("passed", "good"), ("failed → alert, exit 1", "bad")],
}

LAYERS = [
    {
        "n": "01",
        "icon": "bank",
        "name": "Legacy core",
        "schema": "SQL Server · TB_*",
        "tech": "core banking system",
        "blocks": [
            ("grid", ["TB_CLIENTE", "TB_CONTA", "TB_LANCAMENTO"]),
            (
                "points",
                [
                    "Duplicate registrations of the same customer",
                    "CPFs that lost their leading zeros, broken accents",
                    "Codes instead of descriptions, orphan records",
                ],
            ),
        ],
        "foot": "Read only: the migration never writes here",
    },
    {
        "n": "02",
        "icon": "download",
        "name": "Extract",
        "schema": "extract.py",
        "tech": "keyset pagination",
        "blocks": [
            (
                "points",
                [
                    "Pages by primary key (WHERE id > last ORDER BY id): light on the legacy system",
                    "Full load or only rows changed since the watermark, with a 5-minute overlap",
                    "Rows rejected before are read again until fixed at the source",
                ],
            )
        ],
        "foot": "Incremental run: 771 rows instead of 59,000",
    },
    {
        "n": "03",
        "icon": "filter",
        "name": "Transform",
        "schema": "rules.py · transform.py",
        "tech": "pure functions, unit tested",
        "blocks": [
            (
                "points",
                [
                    "CPF check digits and lost zeros, name case, encoding repair, date formats",
                    "Same CPF typed in different ways: one customer, newest registration wins",
                    "Deterministic UUIDs: any run can be repeated and compared",
                    "Rejected records keep their reason",
                ],
            )
        ],
        "foot": "Mapping documented in docs/mapping.md",
    },
    {
        "n": "04",
        "icon": "db",
        "name": "Load",
        "schema": "load.py",
        "tech": "idempotent upserts",
        "blocks": [
            (
                "boxes",
                "TARGET SYSTEMS",
                [
                    ("PostgreSQL · core", "system of record"),
                    ("PostgreSQL · migration", "runs, checks, rejected"),
                    ("MongoDB · profiles", "app read model, Decimal128"),
                ],
            ),
            ("points", ["INSERT … ON CONFLICT guarded by the legacy 'changed at': re-runs never duplicate"]),
        ],
        "foot": "Newer data is never overwritten by older",
    },
    {
        "n": "05",
        "icon": "shield",
        "name": "Reconciliation gate",
        "schema": "reconcile.py",
        "tech": "7 critical + 3 info checks",
        "blocks": [
            (
                "points",
                [
                    "Every legacy row migrated or rejected: nothing lost, nothing invented",
                    "Every transaction compared field by field",
                    "Money totals and app balances checked",
                    "A failure sends the alert and returns exit code 1",
                ],
            )
        ],
        "foot": "The cut-over waits for a passed run",
    },
    {
        "n": "06",
        "icon": "api",
        "name": "Apps and monitoring",
        "schema": "api/app.py · powerbi/",
        "tech": "FastAPI · Power BI",
        "blocks": [
            (
                "points",
                [
                    "REST API: customer profile, statements, run history (API key, masked CPF)",
                    "Power BI cut-over dashboard: gate, backlog burn-down, check history",
                    "Runbook for cut-over and rollback",
                ],
            )
        ],
        "foot": "No personal data leaves for the dashboard",
    },
]

CODE = [
    ("src/migration", "Python · SQL", "Extract, rules, load, reconciliation, API, rehearsal, Power BI export", "main"),
    ("powerbi · scripts", "Power BI · TMDL", "Migration Control dashboard: model, report as code, quality gate", "second"),
    ("tests · .github/workflows", "pytest · CI", "Unit + integration on SQL Server, PostgreSQL and MongoDB containers", "test"),
]

PROOFS_TITLE = "What the project proves"
PROOFS = [
    ("0", "differences in 45,803 transactions compared field by field"),
    ("−93%", "rejected backlog in 10 business days (692 → 47)"),
    ("771", "rows read by an incremental run instead of 59,000"),
    ("100%", "of the legacy rows migrated or in the backlog"),
]

STEPS = [
    (
        "search",
        "Assess",
        "Profile the legacy tables and list the defects: duplicates, lost zeros, broken accents, orphans.",
        "docs/mapping.md",
    ),
    (
        "pencil",
        "Design",
        "PostgreSQL as system of record, MongoDB profile for the apps, reconciliation as a release gate.",
        "docs/adr",
    ),
    (
        "filter",
        "Extract and clean",
        "Keyset reads by watermark and one tested rule per field, with rejected records and reasons.",
        "extract · rules",
    ),
    ("db", "Load", "Idempotent upserts into PostgreSQL and one MongoDB document per customer.", "load.py"),
    ("shield", "Gate the release", "7 critical checks after every run; a failure alerts and stops the pipeline.", "reconcile.py"),
    (
        "check",
        "Rehearse",
        "10 business days of runs: backlog −93%, a manual edit caught by the gate and repaired.",
        "simulate.py · powerbi",
    ),
    ("play", "Cut over and serve", "Runbook with rollback, read-only API for the apps and the ops team.", "runbook · api"),
]
PHASES = [("PLAN", 0, 1), ("BUILD", 2, 4), ("PROVE & RUN", 5, 6)]


# ==========================================================================================================
# Drawing engine (the same in every project of the portfolio; only the specification above changes)
# ==========================================================================================================

FONT = "Inter, Segoe UI, sans-serif"
MONO = "JetBrains Mono, Consolas, monospace"
OUT = Path(__file__).resolve().parents[1] / "docs" / "images"

# Neutral dark canvas shared by every project; the accent colours come from PALETTE
BG_1, BG_2 = "#0D0C0E", "#17151A"
CARD, CARD_2, LINE = "#1B191E", "#232027", "#37333C"
INK, MUTED, DIM = "#F4F1F5", "#B0A9B5", "#7E7684"
GOOD, WARN, BAD = "#34D399", "#F2B544", "#F0614D"
ACCENT, ACCENT_DARK, ACCENT_LIGHT = PALETTE["accent"], PALETTE["dark"], PALETTE["light"]
SECOND, THIRD = PALETTE["second"], PALETTE["third"]

# Line icons, 24x24
ICONS = {
    "db": '<ellipse cx="12" cy="5.5" rx="7" ry="2.8"/><path d="M5 5.5v13c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-13"/>'
    '<path d="M5 12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8"/>',
    "file": '<path d="M7 3.5h7l4 4v13H7z"/><path d="M14 3.5v4h4M9.5 12h6M9.5 15.5h6"/>',
    "cloud": '<path d="M7 18.5h10a4 4 0 0 0 .6-8 6 6 0 0 0-11.4 1.6A3.3 3.3 0 0 0 7 18.5z"/>',
    "download": '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14"/>',
    "layers": '<path d="M12 3.5 21 8l-9 4.5L3 8z"/><path d="M3 12.5l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5"/>',
    "filter": '<path d="M4 5h16l-6 7.5V19l-4 1.5v-8z"/>',
    "star": '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
    "shield": '<path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.2-7.5 9.9-4.3-1.7-7.5-5.3-7.5-9.9V6z"/><path d="M8.8 12.2l2.2 2.2 4.3-4.6"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "clock": '<circle cx="12" cy="12.5" r="8"/><path d="M12 8v4.5l3 2"/>',
    "code": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M15.5 15.5 20 20"/>',
    "pencil": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "check": '<circle cx="12" cy="12" r="8.5"/><path d="M8 12.3l2.6 2.6 5.4-5.6"/>',
    "gauge": '<path d="M4 16a8 8 0 1 1 16 0"/><path d="M12 16l4.5-5"/><circle cx="12" cy="16" r="1.5"/>',
    "play": '<circle cx="12" cy="12" r="8.5"/><path d="M10 8.5l5 3.5-5 3.5z"/>',
    "flow": '<circle cx="5.5" cy="6" r="2.5"/><circle cx="18.5" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/>'
    '<path d="M8 6h8M7 8l3.6 7.8M17 8l-3.6 7.8"/>',
    "spark": '<path d="M13 2.5 5 13.5h6l-1 8 8-11h-6z"/>',
    "brain": '<path d="M9 4.5a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5.5a3 3 0 0 0-3-1z"/>'
    '<path d="M15 4.5a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1"/>',
    "map": '<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    "api": '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M7.5 10l2.5 2-2.5 2M12 14h4.5"/>',
    "users": '<circle cx="9" cy="8" r="3"/><path d="M3.5 19.5a5.5 5.5 0 0 1 11 0"/><circle cx="17" cy="9" r="2.4"/>'
    '<path d="M15.6 14.1a4.5 4.5 0 0 1 5.4 4.4"/>',
    "headset": '<path d="M4.5 14v-2a7.5 7.5 0 0 1 15 0v2"/><rect x="3.5" y="13.5" width="4" height="6" rx="1.5"/>'
    '<rect x="16.5" y="13.5" width="4" height="6" rx="1.5"/><path d="M18.5 19.5c0 1.2-2 2-5 2"/>',
    "truck": '<path d="M2.5 6.5h11v9h-11zM13.5 9.5h4l3 3v3h-7z"/><circle cx="6.5" cy="17" r="1.8"/><circle cx="17" cy="17" r="1.8"/>',
    "coin": '<rect x="2.5" y="6.5" width="19" height="11" rx="1.5"/><circle cx="12" cy="12" r="2.6"/><path d="M6 9.5v5M18 9.5v5"/>',
    "bank": '<path d="M3 9.5 12 4l9 5.5"/><path d="M5 10.5v7.5M9.5 10.5v7.5M14.5 10.5v7.5M19 10.5v7.5"/><path d="M3 20.5h18"/>',
    "cart": '<path d="M3 4.5h2.5l2.2 10.5h10.5l2-7.5H6.4"/><circle cx="9" cy="19" r="1.5"/><circle cx="17" cy="19" r="1.5"/>',
    "gov": '<path d="M12 3.5 4 8h16z"/><path d="M6 10v7M10 10v7M14 10v7M18 10v7M3.5 20h17"/>',
    "migrate": '<ellipse cx="6.5" cy="6" rx="3.5" ry="1.8"/><path d="M3 6v11c0 1 1.6 1.8 3.5 1.8S10 18 10 17V6"/>'
    '<ellipse cx="17.5" cy="6" rx="3.5" ry="1.8"/><path d="M14 6v11c0 1 1.6 1.8 3.5 1.8S21 18 21 17V6"/><path d="M10 12h4"/>',
    "bolt": '<circle cx="12" cy="12" r="8.5"/><path d="M12.5 6.5 9 13h3.5l-1 4.5L15 11h-3.5z"/>',
}


def icon(name, x, y, size, stroke, width=1.9):
    k = size / 24
    return (
        f'<g transform="translate({x:.1f} {y:.1f}) scale({k:.4f})" fill="none" stroke="{stroke}" '
        f'stroke-width="{width:.2f}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>'
    )


def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def txt(x, y, value, size=18, color=INK, weight=400, anchor="start", family=FONT, spacing=0):
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
        f'fill="{color}" text-anchor="{anchor}"{ls}>{esc(value)}</text>'
    )


def wrap(value: str, width_px: float, size: float, factor: float = 0.53) -> list[str]:
    """Splits a sentence into lines that fit a width (average glyph width = factor x font size)."""
    per_line = max(6, int(width_px / (size * factor)))
    lines, current = [], ""
    for word in value.split():
        if len(current) + len(word) + 1 > per_line and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def paragraph(x, y, value, width, size=16, color=MUTED, leading=1.42, family=FONT, weight=400):
    lines = wrap(value, width, size, 0.6 if family == MONO else 0.53)
    out = "".join(txt(x, y + i * size * leading, line, size, color, weight, family=family) for i, line in enumerate(lines))
    return out, y + len(lines) * size * leading


def chip(x, y, label, color, size=14, pad=12, family=FONT, fill=None):
    w = len(label) * size * (0.6 if family == MONO else 0.56) + 2 * pad
    h = size + 14
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h}" rx="{h / 2}" fill="{fill or CARD_2}" '
        f'stroke="{color}" stroke-opacity="0.6" stroke-width="1.2"/>'
        + txt(x + pad, y + size + 3.5, label, size, color, 600, family=family)
    ), w


def defs():
    return f"""<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{BG_1}"/><stop offset="1" stop-color="{BG_2}"/></linearGradient>
  <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0"><stop stop-color="{ACCENT_LIGHT}"/><stop offset="1" stop-color="{ACCENT_DARK}"/></linearGradient>
  <radialGradient id="glow" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(1800 0) scale(900)">
    <stop stop-color="{ACCENT}" stop-opacity="0.16"/><stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></radialGradient>
  <pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="#fff" fill-opacity="0.04"/></pattern>
  <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0 0 L10 5 L0 10 z" fill="{ACCENT_LIGHT}"/></marker>
</defs>"""


def canvas(width, height, body, eyebrow, title, subtitle):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
{defs()}
<rect width="{width}" height="{height}" rx="28" fill="url(#bg)"/>
<rect width="{width}" height="{height}" rx="28" fill="url(#glow)"/>
<rect width="{width}" height="{height}" rx="28" fill="url(#dots)"/>
<g id="Header">
<circle cx="88" cy="78" r="30" fill="none" stroke="url(#accent)" stroke-width="2.5"/>{icon(HEADER["icon"], 70, 60, 36, ACCENT_LIGHT, 2)}
{txt(136, 70, eyebrow, 17, ACCENT_LIGHT, 600, spacing=4)}
{txt(136, 108, title, 38, INK, 800)}
{txt(width - 60, 70, HEADER["stack"], 17, MUTED, 500, "end")}
{txt(width - 60, 100, subtitle, 17, DIM, 400, "end")}
<rect x="60" y="138" width="{width - 120}" height="1.5" fill="{LINE}"/><rect x="60" y="137.5" width="120" height="2.5" fill="url(#accent)"/>
</g>
{body}
</svg>"""


# ------------------------------------------------------------------ 1. architecture
def orchestration_band(width, y):
    o = ORCHESTRATION
    parts = [
        f'<rect x="60" y="{y}" width="{width - 120}" height="92" rx="20" fill="{CARD}" stroke="{LINE}" stroke-width="1.5"/>',
        f'<circle cx="112" cy="{y + 46}" r="26" fill="{CARD_2}" stroke="{ACCENT_DARK}" stroke-width="1.5"/>',
        icon(o["icon"], 96, y + 30, 32, ACCENT_LIGHT),
        txt(154, y + 40, o["label"], 14, ACCENT_LIGHT, 700, spacing=3),
        txt(154, y + 66, o["title"], 20, INK, 700),
    ]
    # Chips start after the title (long titles push them to the right)
    x = max(o.get("start_x", 600), 154 + len(o["title"]) * 20 * 0.55 + 40)
    if o.get("command"):
        c, w = chip(x, y + 30, o["command"], SECOND, size=15, family=MONO)
        parts.append(c)
        x += w + 26
    for i, s in enumerate(o["steps"]):
        c, w = chip(x, y + 30, s, ACCENT_LIGHT, size=15)
        parts.append(c)
        if i < len(o["steps"]) - 1:
            parts.append(
                f'<path d="M{x + w + 6:.1f} {y + 44.5} h14" stroke="{ACCENT_LIGHT}" stroke-width="2" marker-end="url(#arrow)"/>'
            )
        x += w + 28
    for label, kind in o.get("status", []):
        c, w = chip(x, y + 30, label, {"good": GOOD, "warn": WARN, "bad": BAD}[kind], size=14)
        parts.append(c)
        x += w + 10
    return parts


def layer_body(layer, x, top, card_w):
    """Draws the content of one layer card; returns the SVG parts and the y where the content ends."""
    parts, inner = [], card_w - 52
    parts.append(f'<circle cx="{x + 52:.1f}" cy="{top + 56}" r="28" fill="{CARD_2}" stroke="{ACCENT_DARK}" stroke-width="1.5"/>')
    parts.append(icon(layer["icon"], x + 35, top + 39, 34, ACCENT_LIGHT))
    parts.append(txt(x + card_w - 26, top + 48, layer["n"], 30, LINE, 800, "end"))
    block, y = paragraph(x + 26, top + 118, layer["name"], inner, 24, INK, 1.15, weight=800)
    parts.append(block)
    block, y = paragraph(x + 26, y + 4, layer["schema"], inner, 14, ACCENT_LIGHT, 1.35, family=MONO, weight=600)
    parts.append(block)
    block, y = paragraph(x + 26, y + 2, layer["tech"], inner, 14.5, MUTED, 1.35)
    parts.append(block)
    parts.append(f'<rect x="{x + 26:.1f}" y="{y - 4:.1f}" width="{inner:.1f}" height="1" fill="{LINE}"/>')
    y += 30
    for kind, *args in layer["blocks"]:
        if kind == "grid":  # names of tables / files: two per row when they fit, otherwise one
            items = args[0]
            cols = 2 if max(len(t) for t in items) * 12 * 0.6 <= inner / 2 - 20 else 1
            cell = inner / cols - (4 if cols == 2 else 0)
            for k, t in enumerate(items):
                col, row = k % cols, k // cols
                parts.append(
                    f'<rect x="{x + 26 + col * (cell + 8):.1f}" y="{y + row * 36 - 20:.1f}" width="{cell:.1f}" '
                    f'height="28" rx="8" fill="{CARD_2}" stroke="{LINE}"/>'
                )
                size = min(12, (cell - 20) / max(len(t), 1) / 0.6)
                parts.append(txt(x + 36 + col * (cell + 8), y + row * 36 - 1, t, size, INK, 500, family=MONO))
            y += ((len(items) + cols - 1) // cols) * 36 + 14
        elif kind == "chips":  # title + chips (e.g. dimensions)
            title, items = args
            parts.append(txt(x + 26, y, title, 12, DIM, 700, spacing=2))
            y += 14
            cx, cy = x + 26, y
            for d in items:
                w = len(d) * 13 * 0.6 + 20
                if cx + w > x + card_w - 20:
                    cx, cy = x + 26, cy + 36
                parts.append(
                    f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{w:.1f}" height="28" rx="14" fill="{CARD_2}" stroke="{THIRD}" stroke-opacity="0.55"/>'
                )
                parts.append(txt(cx + 10, cy + 19, d, 13, THIRD, 600))
                cx += w + 8
            y = cy + 62
        elif kind == "boxes":  # title + boxes with a subtitle (e.g. facts)
            title, items = args
            parts.append(txt(x + 26, y, title, 12, DIM, 700, spacing=2))
            y += 14
            for name, sub in items:
                parts.append(
                    f'<rect x="{x + 26:.1f}" y="{y:.1f}" width="{inner:.1f}" height="46" rx="10" fill="{CARD_2}" stroke="{SECOND}" stroke-opacity="0.5"/>'
                )
                parts.append(txt(x + 40, y + 20, name, 14, INK, 600))
                parts.append(txt(x + 40, y + 38, sub, 12, SECOND, 500))
                y += 54
            y += 22
        elif kind == "points":
            for point in args[0]:
                parts.append(f'<circle cx="{x + 31:.1f}" cy="{y - 5:.1f}" r="3.5" fill="{ACCENT}"/>')
                block, y = paragraph(x + 44, y, point, inner - 22, 15, INK)
                parts.append(block)
                y += 12
    return parts, y


def architecture():
    width = 1920
    parts = []
    y0 = 172
    if ORCHESTRATION:
        parts += orchestration_band(width, y0)
        top = 300
    else:
        top = 180
    n = len(LAYERS)
    gap = 52 if n <= 5 else 36
    card_w = (width - 120 - gap * (n - 1)) / n
    # First pass: measure the tallest layer so every card has the same height
    ends = [layer_body(layer, 60 + i * (card_w + gap), top, card_w)[1] for i, layer in enumerate(LAYERS)]
    foot_lines = max(len(wrap(layer["foot"], card_w - 64, 13)) for layer in LAYERS)
    foot_h = 24 + foot_lines * 18
    card_h = max(ends) - top + foot_h + 36
    for i, layer in enumerate(LAYERS):
        x = 60 + i * (card_w + gap)
        parts.append(f'<g id="Layer {i + 1} {esc(layer["name"])}">')
        parts.append(
            f'<rect x="{x:.1f}" y="{top}" width="{card_w:.1f}" height="{card_h:.1f}" rx="22" fill="{CARD}" stroke="{LINE}" stroke-width="1.5"/>'
        )
        parts.append(f'<rect x="{x + 26:.1f}" y="{top}" width="70" height="3.5" rx="1.75" fill="url(#accent)"/>')
        body, _ = layer_body(layer, x, top, card_w)
        parts += body
        parts.append(
            f'<rect x="{x + 18:.1f}" y="{top + card_h - foot_h - 18:.1f}" width="{card_w - 36:.1f}" height="{foot_h}" rx="12" fill="{CARD_2}"/>'
        )
        block, _ = paragraph(x + 32, top + card_h - foot_h + 9, layer["foot"], card_w - 64, 13, MUTED, 1.38)
        parts.append(block)
        parts.append("</g>")
        if i < n - 1:
            parts.append(
                f'<path d="M{x + card_w + 6:.1f} {top + card_h / 2:.1f} h{gap - 14}" stroke="{ACCENT_LIGHT}" stroke-width="2.5" marker-end="url(#arrow)"/>'
            )

    # Bottom: where the code is, and what the project proves
    by = top + card_h + 40
    half = (width - 120 - 24) / 2
    rows_h = 80 + len(CODE) * 70 + 20
    box_h = max(rows_h, 300)
    parts.append(
        f'<rect x="60" y="{by:.1f}" width="{half:.1f}" height="{box_h}" rx="22" fill="{CARD}" stroke="{LINE}" stroke-width="1.5"/>'
    )
    parts.append(icon("code", 88, by + 26, 30, ACCENT_LIGHT))
    parts.append(txt(130, by + 50, "Where the code is", 22, INK, 800))
    y = by + 80
    for path, lang, what, kind in CODE:
        color = {"main": ACCENT_LIGHT, "second": SECOND, "test": GOOD, "third": THIRD}[kind]
        parts.append(f'<rect x="88" y="{y:.1f}" width="{half - 56:.1f}" height="62" rx="10" fill="{CARD_2}"/>')
        parts.append(f'<rect x="88" y="{y:.1f}" width="5" height="62" rx="2.5" fill="{color}"/>')
        parts.append(txt(108, y + 26, path, 14, INK, 600, family=MONO))
        parts.append(txt(half + 60 - 40, y + 26, lang, 14, color, 700, "end"))
        parts.append(txt(108, y + 49, what, 13.5, MUTED))
        y += 70

    rx = 60 + half + 24
    parts.append(
        f'<rect x="{rx:.1f}" y="{by:.1f}" width="{half:.1f}" height="{box_h}" rx="22" fill="{CARD}" stroke="{LINE}" stroke-width="1.5"/>'
    )
    parts.append(icon("gauge", rx + 28, by + 26, 30, SECOND))
    parts.append(txt(rx + 70, by + 50, PROOFS_TITLE, 22, INK, 800))
    k_n = len(PROOFS)
    kw = (half - 56 - 12 * (k_n - 1)) / k_n
    for k, (big, small) in enumerate(PROOFS):
        kx = rx + 28 + k * (kw + 12)
        parts.append(f'<rect x="{kx:.1f}" y="{by + 82:.1f}" width="{kw:.1f}" height="{box_h - 108}" rx="14" fill="{CARD_2}"/>')
        parts.append(f'<rect x="{kx + 18:.1f}" y="{by + 82:.1f}" width="44" height="3" rx="1.5" fill="{SECOND}"/>')
        size = 40 if len(big) <= 6 else 30
        parts.append(txt(kx + 18, by + 146, big, size, SECOND, 800))
        block, _ = paragraph(kx + 18, by + 184, small, kw - 36, 14, MUTED)
        parts.append(block)

    height = int(by + box_h + 40)
    svg = canvas(width, height, "\n".join(parts), "ARCHITECTURE", HEADER["title"], HEADER["flow"])
    return svg, width, height


# ------------------------------------------------------------------ 2. delivery steps
def delivery():
    width = 1920
    parts = []
    n = len(STEPS)
    gap = 22
    w = (width - 120 - gap * (n - 1)) / n
    top = 300

    # Measure title + description of every step so all cards have the same height
    def title_size(title):
        return 22 if len(wrap(title, w - 44, 22)) == 1 else 20

    def text_end(title, what):
        _, end = paragraph(0, 128, title, w - 44, title_size(title), INK, 1.15)
        _, end = paragraph(0, end + 14, what, w - 44, 15.5, MUTED, 1.5)
        return end

    card_h = max(text_end(title, what) for _, title, what, _ in STEPS) + 90
    parts.append(
        f'<rect x="{60 + w / 2:.1f}" y="{top - 46}" width="{width - 120 - w:.1f}" height="3" rx="1.5" fill="url(#accent)"/>'
    )
    for label, a, b in PHASES:
        xa = 60 + a * (w + gap)
        xb = 60 + b * (w + gap) + w
        parts.append(
            f'<rect x="{xa:.1f}" y="{top - 112}" width="{xb - xa:.1f}" height="34" rx="17" fill="{CARD}" stroke="{LINE}"/>'
        )
        parts.append(txt((xa + xb) / 2, top - 89, label, 14, ACCENT_LIGHT, 700, "middle", spacing=4))
    for i, (ic, title, what, files) in enumerate(STEPS):
        x = 60 + i * (w + gap)
        cx = x + w / 2
        parts.append(f'<circle cx="{cx:.1f}" cy="{top - 44.5}" r="17" fill="{BG_1}" stroke="{ACCENT_LIGHT}" stroke-width="2.5"/>')
        parts.append(txt(cx, top - 38, str(i + 1), 16, INK, 800, "middle"))
        parts.append(
            f'<rect x="{x:.1f}" y="{top}" width="{w:.1f}" height="{card_h:.1f}" rx="20" fill="{CARD}" stroke="{LINE}" stroke-width="1.5"/>'
        )
        parts.append(f'<rect x="{x + 22:.1f}" y="{top}" width="56" height="3" rx="1.5" fill="url(#accent)"/>')
        parts.append(
            f'<circle cx="{x + 50:.1f}" cy="{top + 58}" r="28" fill="{CARD_2}" stroke="{ACCENT_DARK}" stroke-width="1.5"/>'
        )
        parts.append(icon(ic, x + 33, top + 41, 34, ACCENT_LIGHT))
        block, end = paragraph(x + 22, top + 128, title, w - 44, title_size(title), INK, 1.15, weight=800)
        parts.append(block)
        block, _ = paragraph(x + 22, end + 14, what, w - 44, 15.5, MUTED, 1.5)
        parts.append(block)
        parts.append(
            f'<rect x="{x + 16:.1f}" y="{top + card_h - 68:.1f}" width="{w - 32:.1f}" height="48" rx="12" fill="{CARD_2}"/>'
        )
        parts.append(txt(x + 30, top + card_h - 49, "DELIVERABLE", 11, DIM, 700, spacing=2))
        size = min(12.5, (w - 60) / max(len(files), 1) / 0.6)
        parts.append(txt(x + 30, top + card_h - 30, files, size, SECOND, 600, family=MONO))
    height = int(top + card_h + 40)
    svg = canvas(width, height, "\n".join(parts), "HOW IT WAS BUILT", HEADER["steps_title"], "plan → build → prove → run")
    return svg, width, height


def render(svgs):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, (svg, w, h) in svgs.items():
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            page.set_content(f"<html><body style='margin:0;background:transparent'>{svg}</body></html>")
            page.screenshot(path=str(OUT / f"{name}.png"), clip={"x": 0, "y": 0, "width": w, "height": h}, omit_background=True)
            page.close()
        browser.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    svgs = {"architecture": architecture(), "delivery_steps": delivery()}
    for name, (svg, _, _) in svgs.items():
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
    render(svgs)
    print("written:", ", ".join(f"docs/images/{n}.svg/.png" for n in svgs))


if __name__ == "__main__":
    main()
