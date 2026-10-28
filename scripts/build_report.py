"""Builds the migration monitoring report (PBIR format) and its designed page backgrounds from one layout spec.

Report as code: every page, visual, position and format is defined here, so a layout change is a
reviewed diff instead of clicks. Each visual gets a frame drawn in the page background (SVG for
design tools, PNG for Power BI) at exactly the same position (Power BI 1280x720 = SVG 1920x1080 / 1.5).

    python scripts/build_report.py            # write the report pages and the SVG backgrounds
    python scripts/build_report.py --render   # also render the PNG backgrounds (needs Playwright)
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "powerbi"
REPORT = ROOT / "MigrationControl.Report"
OUT = REPORT / "definition"
RES = REPORT / "StaticResources" / "RegisteredResources"
DESIGN = ROOT / "design"
VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.4.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
PAGES_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json"
REPORT_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json"
VERSION_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
PLATFORM_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json"
S = 1.5  # Power BI px -> design px
F = "Checks"  # default table for measures (overridden per call)

# ------------------------------------------------------------------ design tokens (graphite + amber, dark)
SHELL_900, SHELL_800, SHELL_700 = "#0C0B0A", "#14120F", "#1D1A16"
AMBER_600, AMBER_500, AMBER_300 = "#D97706", "#F59E0B", "#FCD34D"
PANEL, CARD, CARD_ALT, LINE = "#12100E", "#1C1916", "#221E1A", "#2F2A24"
INK, MUTED, CHIP = "#F3EDE4", "#A39A8E", "#2A241D"
CORAL, GREEN = "#F0614D", "#34D399"
THEME = {
    "name": "Migration Control (dark)",
    "dataColors": [AMBER_500, "#D6D3D1", GREEN, CORAL, "#A78BFA", "#F472B6", "#78716C", "#FDE68A"],
    "foreground": INK,
    "foregroundNeutralSecondary": MUTED,
    "foregroundNeutralTertiary": "#6F675D",
    "background": CARD,
    "backgroundLight": CARD_ALT,
    "backgroundNeutral": LINE,
    "tableAccent": AMBER_500,
    "good": GREEN,
    "neutral": AMBER_500,
    "bad": CORAL,
    "maximum": AMBER_500,
    "center": "#7C5A1E",
    "minimum": CARD,
    "textClasses": {
        "label": {"color": INK},
        "callout": {"color": INK},
        "title": {"color": INK},
        "header": {"color": INK},
    },
}

# Line icons, 24x24 (bank building, gauge, scales, paper stack, padlock, banknote ...)
ICONS = {
    "home": '<path d="M3 9.5 12 4l9 5.5"/><path d="M5 10.5v7.5M9.5 10.5v7.5M14.5 10.5v7.5M19 10.5v7.5"/><path d="M3 20.5h18"/>',
    "overview": '<path d="M4 16a8 8 0 1 1 16 0"/><path d="M12 16l4.5-5"/><circle cx="12" cy="16" r="1.5"/><path d="M4 20h16"/>',
    "history": '<path d="M12 4v16M8 20h8M5 8h14"/><path d="M5 8 2.5 13.5a2.5 2.5 0 0 0 5 0z"/>'
    '<path d="M19 8l-2.5 5.5a2.5 2.5 0 0 0 5 0z"/>',
    "inbox": '<rect x="7" y="3.5" width="12" height="14.5" rx="1.5"/><path d="M4.5 7v12A1.5 1.5 0 0 0 6 20.5h10"/>'
    '<path d="M10 8h6M10 11h6M10 14h3"/>',
    "shield": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>'
    '<path d="M9.5 15.5l1.8 1.8 3.2-3.3"/>',
    "check": '<rect x="5.5" y="4.5" width="13" height="16" rx="2"/><path d="M9 4.5V3h6v1.5"/><path d="M9 12.5l2 2 4-4.5"/>',
    "database": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5V12h8.5"/>',
    "layers": '<path d="M4 8h13M14 5l3 3-3 3"/><path d="M20 16H7M10 13l-3 3 3 3"/>',
    "coin": '<rect x="2.5" y="6.5" width="19" height="11" rx="1.5"/><circle cx="12" cy="12" r="2.6"/><path d="M6 9.5v5M18 9.5v5"/>',
    "alert": '<path d="M8.5 3.5h7l5 5v7l-5 5h-7l-5-5v-7z"/><path d="M9.5 9.5l5 5M14.5 9.5l-5 5"/>',
    "calendar": '<rect x="4" y="5.5" width="16" height="15" rx="2"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>'
    '<circle cx="12" cy="15" r="1.6"/>',
    "clock": '<circle cx="12" cy="13.5" r="7"/><path d="M12 13.5V10M10 3.5h4M18 7l1.5-1.5"/>',
    "trend": '<path d="M3 7l6 6 4-4 8 8"/><path d="M15 17h6v-6"/>',
    "filter": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "migrate": '<ellipse cx="6.5" cy="6" rx="3.5" ry="1.8"/><path d="M3 6v11c0 1 1.6 1.8 3.5 1.8S10 18 10 17V6"/>'
    '<ellipse cx="17.5" cy="6" rx="3.5" ry="1.8"/><path d="M14 6v11c0 1 1.6 1.8 3.5 1.8S21 18 21 17V6"/><path d="M10 12h4"/>',
}


def icon(name, x, y, size, stroke, width=1.8, ident=None):
    k = size / 24
    gid = f' id="{ident}"' if ident else ""
    return (
        f'<g{gid} transform="translate({x:.1f} {y:.1f}) scale({k:.4f})" fill="none" stroke="{stroke}" '
        f'stroke-width="{width:.2f}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>'
    )


# ------------------------------------------------------------------ PBIR query helpers
def lit(value):
    return {"expr": {"Literal": {"Value": value}}}


def text(value):
    return lit("'" + value.replace("'", "''") + "'")


def num(value):
    return lit(f"{value}D")


def color(hex_):
    return {"solid": {"color": text(hex_)}}


def m(prop, entity=F):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def c(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(field, display=None):
    kind = "Measure" if "Measure" in field else "Column"
    entity, prop = field[kind]["Expression"]["SourceRef"]["Entity"], field[kind]["Property"]
    p = {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    return p


def in_filter(name, entity, prop, values):
    """Visual-level filter: column in (values)."""
    return {
        "name": name,
        "field": c(entity, prop),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "t", "Entity": entity, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": prop}}],
                            "Values": [[{"Literal": {"Value": "'" + v + "'"}}] for v in values],
                        }
                    }
                }
            ],
        },
    }


# ------------------------------------------------------------------ page model
NAV = [
    ("home", "Home", "Cover"),
    ("overview", "Status", "Cut-over status"),
    ("history", "Reconciliation", "Reconciliation history"),
    ("inbox", "Backlog", "Rejected backlog"),
]
X0, X1, Y0, Y1 = 88, 1256, 84, 700  # content area (Power BI px)


class Page:
    def __init__(self, name, display, title, subtitle, nav):
        self.name, self.display, self.title, self.subtitle, self.nav = name, display, title, subtitle, nav
        self.visuals, self.frames, self.z = [], [], 0

    def frame(self, vid, x, y, w, h, kind="chart", icon_name=None):
        self.frames.append({"id": vid, "x": x, "y": y, "w": w, "h": h, "kind": kind, "icon": icon_name})

    def add(self, vid, x, y, w, h, visual, filters=None):
        self.z += 1
        cont = {
            "$schema": VC_SCHEMA,
            "name": vid,
            "position": {"x": x, "y": y, "z": self.z * 1000, "width": w, "height": h, "tabOrder": self.z * 1000},
            "visual": visual,
        }
        if filters:
            cont["filterConfig"] = {"filters": filters}
        self.visuals.append(cont)


def container(title=None, subtitle=None, pad_left=20):
    """Transparent container: the frame drawn in the background is the card."""
    objs = {
        "background": [{"properties": {"show": lit("false")}}],
        "border": [{"properties": {"show": lit("false")}}],
        "dropShadow": [{"properties": {"show": lit("false")}}],
        "visualHeader": [{"properties": {"show": lit("false")}}],
        "padding": [{"properties": {"top": num(10), "bottom": num(8), "left": num(pad_left), "right": num(14)}}],
    }
    if title:
        objs["title"] = [
            {
                "properties": {
                    "show": lit("true"),
                    "text": text(title),
                    "fontColor": color(INK),
                    "fontSize": num(11),
                    "bold": lit("true"),
                    "fontFamily": text("Segoe UI Semibold"),
                }
            }
        ]
        if subtitle:
            objs["subTitle"] = [
                {"properties": {"show": lit("true"), "text": text(subtitle), "fontColor": color(MUTED), "fontSize": num(9)}}
            ]
    else:
        objs["title"] = [{"properties": {"show": lit("false")}}]
    return objs


def link_button(page, vid, x, y, w, h, target, tooltip):
    page.add(
        vid,
        x,
        y,
        w,
        h,
        {
            "visualType": "actionButton",
            "objects": {
                "icon": [{"properties": {"shapeType": text("blank")}, "selector": {"id": "default"}}],
                "fill": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
                "outline": [
                    {"properties": {"show": lit("false"), "transparency": num(100), "weight": num(0)}},
                    {
                        "properties": {"show": lit("false"), "transparency": num(100), "weight": num(0)},
                        "selector": {"id": "default"},
                    },
                ],
                "text": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
            },
            "visualContainerObjects": {
                "title": [{"properties": {"show": lit("false")}}],
                "background": [{"properties": {"show": lit("false")}}],
                "border": [{"properties": {"show": lit("false")}}],
                "visualLink": [
                    {
                        "properties": {
                            "show": lit("true"),
                            "type": text("PageNavigation"),
                            "navigationSection": text(target),
                            "tooltip": text(tooltip),
                        }
                    }
                ],
            },
        },
    )


def nav_buttons(page):
    for i, (_, target, label) in enumerate(NAV):
        if target != page.name:
            link_button(page, f"nav_{target}", 8, 108 + i * 64, 48, 48, target, label)


def card(page, vid, x, y, w, h, field, label, icon_name, filters=None, font=22):
    page.frame(vid, x, y, w, h, "kpi", icon_name)
    page.add(
        vid,
        x,
        y,
        w,
        h,
        {
            "visualType": "card",
            "query": {"queryState": {"Values": {"projections": [proj(field, label)]}}},
            "objects": {
                "labels": [
                    {
                        "properties": {
                            "color": color(INK),
                            "fontSize": num(font),
                            "labelDisplayUnits": num(1),
                            "fontFamily": text("Segoe UI Semibold"),
                        }
                    }
                ],
                "categoryLabels": [{"properties": {"show": lit("true"), "color": color(MUTED), "fontSize": num(9)}}],
            },
            "visualContainerObjects": container(pad_left=14),
        },
        filters,
    )


def chart(
    page,
    vid,
    x,
    y,
    w,
    h,
    kind,
    category,
    values,
    title,
    subtitle=None,
    series=None,
    tooltips=None,
    sort=None,
    filters=None,
    labels=False,
    colors=None,
    axis_range=None,
):
    page.frame(vid, x, y, w, h, "chart")
    state = {"Category": {"projections": [proj(category)]}, "Y": {"projections": [proj(v, d) for v, d in values]}}
    if series:
        state["Series"] = {"projections": [proj(series)]}
    if tooltips:
        state["Tooltips"] = {"projections": [proj(t, d) for t, d in tooltips]}
    query = {"queryState": state}
    if sort:
        query["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": False}
    objects = {
        "labels": [{"properties": {"show": lit("true" if labels else "false"), "color": color(INK), "fontSize": num(9)}}],
        "legend": [
            {
                "properties": {
                    "show": lit("true" if (len(values) > 1 or series) else "false"),
                    "position": text("TopRight"),
                    "labelColor": color(MUTED),
                }
            }
        ],
        "valueAxis": [{"properties": {"gridlineColor": color(LINE), "fontSize": num(9), "labelColor": color(MUTED)}}],
        "categoryAxis": [{"properties": {"fontSize": num(9), "showAxisTitle": lit("false"), "labelColor": color(MUTED)}}],
    }
    if colors and not series:
        objects["dataPoint"] = [
            {"properties": {"fill": color(col)}, "selector": {"metadata": proj(v)["queryRef"]}}
            for (v, _), col in zip(values, colors, strict=False)
        ]
    if axis_range:  # zoom the value axis so small differences against the target are visible
        objects["valueAxis"][0]["properties"]["start"] = num(axis_range[0])
        objects["valueAxis"][0]["properties"]["end"] = num(axis_range[1])
    if kind == "lineChart":
        objects["lineStyles"] = [{"properties": {"strokeWidth": num(3)}}]
    if kind == "clusteredBarChart":
        objects["categoryAxis"][0]["properties"]["maxMarginFactor"] = num(45)
    page.add(
        vid,
        x,
        y,
        w,
        h,
        {"visualType": kind, "query": query, "objects": objects, "visualContainerObjects": container(title, subtitle)},
        filters,
    )


def table(page, vid, x, y, w, h, columns, title, subtitle=None, sort=None, kind="tableEx", rows=None, cols=None, filters=None):
    page.frame(vid, x, y, w, h, "chart")
    if kind == "tableEx":
        state = {"Values": {"projections": [proj(f, d) for f, d in columns]}}
    else:  # matrix
        state = {
            "Rows": {"projections": [proj(rows)]},
            "Columns": {"projections": [proj(cols)]},
            "Values": {"projections": [proj(f, d) for f, d in columns]},
        }
    query = {"queryState": state}
    if sort:
        query["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": False}
    page.add(
        vid,
        x,
        y,
        w,
        h,
        {
            "visualType": kind,
            "query": query,
            "objects": {
                "columnHeaders": [
                    {
                        "properties": {
                            "fontColor": color(AMBER_300),
                            "backColor": color(CHIP),
                            "fontSize": num(9),
                            "bold": lit("true"),
                        }
                    }
                ],
                "values": [
                    {
                        "properties": {
                            "fontSize": num(9),
                            "fontColor": color(INK),
                            "backColorPrimary": color(CARD),
                            "backColorSecondary": color(CARD_ALT),
                        }
                    }
                ],
                "rowHeaders": [{"properties": {"fontColor": color(INK), "backColor": color(CARD), "fontSize": num(9)}}],
                "total": [{"properties": {"fontColor": color(INK), "backColor": color(CHIP)}}],
                "subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}],
                "grid": [
                    {
                        "properties": {
                            "gridHorizontalColor": color(LINE),
                            "gridVerticalColor": color(LINE),
                            "outlineColor": color(LINE),
                        }
                    }
                ],
            },
            "visualContainerObjects": container(title, subtitle),
        },
        filters,
    )


def slicer(page, vid, x, y, w, h, field, title, icon_name="filter"):
    page.frame(vid, x, y, w, h, "control", icon_name)
    page.add(
        vid,
        x,
        y,
        w,
        h,
        {
            "visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [proj(field)]}}},
            "objects": {
                "data": [{"properties": {"mode": text("Dropdown")}}],
                "header": [{"properties": {"show": lit("false")}}],
                "items": [{"properties": {"fontColor": color(INK), "background": color(CARD_ALT)}}],
            },
            "visualContainerObjects": container(title),
        },
    )


# ------------------------------------------------------------------ pages
HALF = round((X1 - X0 - 12) / 2)
RUN = c("Runs", "Run Label")
ENTITY = c("Source Tables", "Entity")


def cover():
    p = Page("Home", "Home", "", "", "home")
    p.kind = "cover"
    for i, (_, target, label) in enumerate(NAV[1:]):
        link_button(p, f"go_{target}", 88 + i * 292, 560, 276, 96, target, label)
    return p


def status():
    p = Page(
        "Status",
        "Cut-over status",
        "Cut-over Status",
        "Can the apps be switched to the new systems? Last run of the rehearsal against the legacy system",
        "overview",
    )
    w6 = round((X1 - X0 - 5 * 12) / 6)
    k6 = [X0 + i * (w6 + 12) for i in range(6)]
    card(p, "k_gate", k6[0], Y0, w6, 92, m("Gate Status", "Runs"), "Last run gate", "shield")
    card(p, "k_checks", k6[1], Y0, w6, 92, m("Critical Checks Label"), "Critical checks passed", "check")
    card(p, "k_accounted", k6[2], Y0, w6, 92, m("Accounted For %", "Coverage"), "Legacy rows accounted for", "database")
    card(p, "k_migrated", k6[3], Y0, w6, 92, m("Migrated Rows", "Coverage"), "Rows migrated", "layers")
    card(p, "k_backlog", k6[4], Y0, w6, 92, m("Backlog Records", "Backlog"), "Records waiting for a fix", "inbox")
    card(p, "k_hold", k6[5], Y0, w6, 92, m("Money on Hold", "Coverage"), "Money on hold", "coin")
    chart(
        p,
        "backlog_run",
        X0,
        188,
        HALF,
        252,
        "columnChart",
        RUN,
        [(m("Backlog Records", "Backlog"), "Records")],
        "Rejected backlog after each run",
        "The business fixes records at the source every day",
        series=ENTITY,
        sort=(RUN, "Ascending"),
    )
    chart(
        p,
        "money_run",
        X0 + HALF + 12,
        188,
        HALF,
        252,
        "clusteredColumnChart",
        RUN,
        [(m("Money on Hold", "Coverage"), "Money on hold")],
        "Money on hold after each run",
        "Rejected transactions waiting for a business decision",
        sort=(RUN, "Ascending"),
        colors=[AMBER_500],
    )
    table(
        p,
        "last_checks",
        X0,
        452,
        X1 - X0,
        Y1 - 452,
        [
            (c("Checks", "Check"), "Check"),
            (c("Checks", "Severity"), "Severity"),
            (m("Last Run Result"), "Result"),
            (m("Last Run Legacy Value"), "Legacy system"),
            (m("Last Run New Value"), "New systems"),
            (m("Last Run Detail"), "Detail"),
        ],
        "Reconciliation of the last run",
        "Any ✖ on a critical check stops the cut-over",
    )
    return p


def reconciliation():
    p = Page(
        "Reconciliation",
        "Reconciliation history",
        "Reconciliation History",
        "Every check in every run · run 6 failed: a value edited by hand in PostgreSQL, repaired by the next full run",
        "history",
    )
    w4 = round((X1 - X0 - 36) / 4)
    k4 = [X0 + i * (w4 + 12) for i in range(4)]
    card(p, "k_runs", k4[0], Y0, w4, 92, m("Run Count", "Runs"), "Runs", "history")
    card(p, "k_failed", k4[1], Y0, w4, 92, m("Failed Runs", "Runs"), "Runs stopped by the gate", "alert")
    card(p, "k_last", k4[2], Y0, w4, 92, m("Last Business Day", "Runs"), "Last run", "calendar")
    card(p, "k_duration", k4[3], Y0, w4, 92, m("Average Duration (s)", "Runs"), "Average duration (s)", "clock")
    table(
        p,
        "matrix",
        X0,
        188,
        X1 - X0,
        300,
        [(m("Check Result"), "Result")],
        "Every check in every run",
        "✔ passed · ✖ failed",
        kind="pivotTable",
        rows=c("Checks", "Check"),
        cols=RUN,
        sort=(c("Checks", "Check"), "Ascending"),
    )
    chart(
        p,
        "volume",
        X0,
        500,
        X1 - X0,
        Y1 - 500,
        "columnChart",
        RUN,
        [(m("Rows Read", "Run Volumes"), "Rows read")],
        "Rows read from the legacy system per run",
        "Full loads read everything · incremental runs read only changes and earlier rejects",
        series=c("Runs", "Mode"),
        sort=(RUN, "Ascending"),
    )
    return p


def backlog():
    p = Page(
        "Backlog",
        "Rejected backlog",
        "Rejected Backlog",
        "Records the new systems refused, why, and how fast the business is fixing them at the source",
        "inbox",
    )
    slicer(p, "f_entity", X0, Y0, 280, 92, ENTITY, "Legacy table")
    w3 = round((X1 - X0 - 292 - 24) / 3)
    k3 = [X0 + 292 + i * (w3 + 12) for i in range(3)]
    card(p, "k_backlog", k3[0], Y0, w3, 92, m("Backlog Records", "Backlog"), "Records waiting for a fix", "inbox")
    card(p, "k_burn", k3[1], Y0, w3, 92, m("Backlog Burn-down %", "Backlog"), "Fixed since the full load", "trend")
    card(p, "k_amount", k3[2], Y0, w3, 92, m("Backlog Amount", "Backlog"), "Money in rejected transactions", "coin")
    chart(
        p,
        "by_reason",
        X0,
        188,
        HALF,
        252,
        "clusteredBarChart",
        c("Backlog", "Reason"),
        [(m("Backlog Records", "Backlog"), "Records")],
        "Why records are rejected (last run)",
        "Each reason has an owner in the business",
        tooltips=[(m("Backlog Amount", "Backlog"), "Amount")],
        sort=(m("Backlog Records", "Backlog"), "Descending"),
        labels=True,
        colors=[AMBER_500],
    )
    chart(
        p,
        "burn_down",
        X0 + HALF + 12,
        188,
        HALF,
        252,
        "lineChart",
        RUN,
        [(m("Backlog Records", "Backlog"), "Records")],
        "Backlog burn-down by table",
        "Customers fixed at the branch release their accounts and transactions",
        series=ENTITY,
        sort=(RUN, "Ascending"),
    )
    table(
        p,
        "records",
        X0,
        452,
        X1 - X0,
        Y1 - 452,
        [
            (ENTITY, "Table"),
            (c("Rejected Records", "Source ID"), "Legacy id"),
            (c("Rejected Records", "Reason"), "Reason"),
            (c("Rejected Records", "Amount"), "Amount"),
            (c("Rejected Records", "Rejected At"), "Last attempt"),
        ],
        "Records rejected right now",
        "Work list for the data owners · ids only, no personal data",
        sort=(c("Rejected Records", "Amount"), "Descending"),
    )
    return p


# ------------------------------------------------------------------ SVG backgrounds
def defs():
    return f"""<defs>
  <linearGradient id="shell" x1="0" y1="0" x2="1920" y2="1080" gradientUnits="userSpaceOnUse">
    <stop stop-color="{SHELL_900}"/><stop offset="0.6" stop-color="{SHELL_800}"/><stop offset="1" stop-color="{SHELL_700}"/>
  </linearGradient>
  <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
    <stop stop-color="{AMBER_300}"/><stop offset="1" stop-color="{AMBER_600}"/>
  </linearGradient>
  <radialGradient id="ember" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(1820 1040) scale(820)">
    <stop stop-color="{AMBER_500}" stop-opacity="0.16"/><stop offset="1" stop-color="{AMBER_500}" stop-opacity="0"/>
  </radialGradient>
  <pattern id="hatch" x="0" y="0" width="22" height="22" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
    <line x1="0" y1="0" x2="0" y2="22" stroke="#FFFFFF" stroke-opacity="0.035" stroke-width="2"/>
  </pattern>
</defs>"""


FONT = "Inter, Segoe UI, sans-serif"


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def shell(active):
    """Dark canvas, hatched texture, slim navigation rail with an amber ring on the active page."""
    out = [
        '<rect id="Background" width="1920" height="1080" fill="url(#shell)"/>',
        '<rect id="Ember" width="1920" height="1080" fill="url(#ember)"/>',
        '<rect id="Hatch" width="1920" height="1080" fill="url(#hatch)"/>',
        '<g id="Navigation rail">',
        '<g id="Brand mark"><circle cx="48" cy="54" r="26" fill="none" stroke="url(#accent)" stroke-width="2.5"/>'
        + icon("migrate", 33, 39, 30, AMBER_300, 2)
        + "</g>",
        f'<rect x="30" y="98" width="36" height="1.5" fill="{LINE}"/>',
    ]
    for i, (name, _, label) in enumerate(NAV):
        cy = (108 + i * 64 + 24) * S
        if name == active:
            out.append(
                f'<circle id="Active {label}" cx="48" cy="{cy:.0f}" r="27" fill="{CHIP}" stroke="{AMBER_500}" stroke-width="2"/>'
                f'<rect x="0" y="{cy - 18:.0f}" width="4" height="36" rx="2" fill="{AMBER_500}"/>'
            )
            out.append(icon(name, 33, cy - 15, 30, AMBER_300, 2, f"Icon {label}"))
        else:
            out.append(icon(name, 33, cy - 15, 30, MUTED, 1.8, f"Icon {label}"))
    out.append("</g>")
    out.append(
        f'<rect id="Content panel" x="{72 * S}" y="{8 * S}" width="{(1272 - 72) * S}" height="{(712 - 8) * S}" rx="18" '
        f'fill="{PANEL}" stroke="{LINE}" stroke-width="1.5"/>'
    )
    return out


def page_header(page):
    return [
        '<g id="Header">',
        f'<circle cx="{109 * S}" cy="{35 * S}" r="{15 * S}" fill="{CHIP}" stroke="{LINE}" stroke-width="1.5"/>',
        icon(page.nav, 109 * S - 12.5, 35 * S - 12.5, 25, AMBER_300, 2, "Header icon"),
        f'<rect id="Data badge" x="{980 * S}" y="{26 * S}" width="{270 * S}" height="{28 * S}" rx="{14 * S}" '
        f'fill="none" stroke="{AMBER_600}" stroke-width="1.5"/>',
        f'<circle cx="{994 * S}" cy="{40 * S}" r="5" fill="{AMBER_500}"/>',
        f'<text x="{1004 * S}" y="{40 * S + 7}" font-family="{FONT}" font-size="19" font-weight="600" fill="{AMBER_300}">'
        "Cut-over rehearsal · 10 business days</text>",
        f'<text id="Page title" x="{132 * S}" y="{37 * S}" font-family="{FONT}" font-size="28" font-weight="700" fill="{INK}">'
        f"{esc(page.title)}</text>",
        f'<text id="Page subtitle" x="{132 * S}" y="{58 * S}" font-family="{FONT}" font-size="17" fill="{MUTED}">'
        f"{esc(page.subtitle)}</text>",
        f'<rect x="{X0 * S}" y="{76 * S}" width="{(X1 - X0) * S}" height="1.5" fill="{LINE}"/>',
        f'<rect x="{X0 * S}" y="{76 * S - 0.5}" width="90" height="2.5" fill="url(#accent)"/>',
        "</g>",
    ]


def frames_svg(page):
    """Dark cards, hairline border, amber top rule on KPIs, round icon badges."""
    out = ['<g id="Frames">']
    for f in page.frames:
        x, y, w, h = f["x"] * S, f["y"] * S, f["w"] * S, f["h"] * S
        out.append(f'<g id="Frame {f["id"]}">')
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="14" fill="{CARD}" '
            f'stroke="{LINE}" stroke-width="1.5"/>'
        )
        if f["kind"] == "kpi":
            out.append(f'<rect x="{x + 20:.1f}" y="{y:.1f}" width="56" height="3" rx="1.5" fill="url(#accent)"/>')
        if f["kind"] in ("kpi", "control") and f["icon"]:
            cx, cy = x + w - 34, y + 34
            out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="19" fill="{CHIP}" stroke="{LINE}" stroke-width="1.2"/>')
            out.append(icon(f["icon"], cx - 11, cy - 11, 22, AMBER_300, 1.9))
        if f["kind"] == "chart":
            out.append(f'<circle cx="{x + 20:.1f}" cy="{y + 31:.1f}" r="4" fill="{AMBER_500}"/>')
        out.append("</g>")
    out.append("</g>")
    return out


def cover_svg():
    """Cover: legacy database -> new systems, connected by the reconciliation gate."""
    tiles = []
    descriptions = ["Gate, coverage and money", "Every check in every run", "Reasons and burn-down"]
    labels = ["Cut-over status", "Reconciliation", "Rejected backlog"]
    for i, (name, _, _) in enumerate(NAV[1:]):
        x, y, w, h = (88 + i * 292) * S, 560 * S, 276 * S, 96 * S
        tiles.append(
            f'<g id="Tile {labels[i]}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{CARD}" '
            f'stroke="{LINE}" stroke-width="1.5"/>'
            f'<rect x="{x + 24}" y="{y}" width="64" height="3" rx="1.5" fill="url(#accent)"/>'
            f'<circle cx="{x + 66}" cy="{y + h / 2}" r="38" fill="{CHIP}" stroke="{AMBER_600}" stroke-width="1.5"/>'
            + icon(name, x + 45, y + h / 2 - 21, 42, AMBER_300, 1.9)
            + f'<text x="{x + 124}" y="{y + 66}" font-family="{FONT}" font-size="25" font-weight="600" fill="{INK}">'
            f"{labels[i]}</text>"
            f'<text x="{x + 124}" y="{y + 100}" font-family="{FONT}" font-size="18" fill="{MUTED}">{descriptions[i]}</text>'
            f'<path d="M{x + w - 36} {y + h / 2 - 9} l9 9 -9 9" stroke="{AMBER_500}" stroke-width="3" fill="none" '
            'stroke-linecap="round" stroke-linejoin="round"/></g>'
        )

    def cylinder(cx, top, label, sub, stroke):
        rx, ry, hgt = 120, 30, 230
        return (
            f'<g id="{label}"><path d="M{cx - rx} {top} v{hgt} a{rx} {ry} 0 0 0 {2 * rx} 0 v-{hgt}" fill="{CARD}" '
            f'stroke="{stroke}" stroke-width="2.5"/>'
            f'<ellipse cx="{cx}" cy="{top}" rx="{rx}" ry="{ry}" fill="{CHIP}" stroke="{stroke}" stroke-width="2.5"/>'
            f'<path d="M{cx - rx} {top + 80} a{rx} {ry} 0 0 0 {2 * rx} 0 M{cx - rx} {top + 160} a{rx} {ry} 0 0 0 {2 * rx} 0" '
            f'fill="none" stroke="{stroke}" stroke-opacity="0.45" stroke-width="2"/>'
            f'<text x="{cx}" y="{top + hgt + 80}" text-anchor="middle" font-family="{FONT}" font-size="24" font-weight="600" '
            f'fill="{INK}">{label}</text>'
            f'<text x="{cx}" y="{top + hgt + 112}" text-anchor="middle" font-family="{FONT}" font-size="18" fill="{MUTED}">'
            f"{sub}</text></g>"
        )

    flow = "".join(
        f'<path d="M1395 {300 + k * 50} C1480 {300 + k * 50} 1500 {330 + k * 30} 1560 {330 + k * 30}" fill="none" '
        f'stroke="{AMBER_500}" stroke-opacity="{0.75 - k * 0.15:.2f}" stroke-width="2.5" stroke-dasharray="8 8"/>'
        for k in range(4)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
{defs()}
<rect id="Background" width="1920" height="1080" fill="url(#shell)"/>
<rect id="Ember" width="1920" height="1080" fill="url(#ember)"/>
<rect id="Hatch" width="1920" height="1080" fill="url(#hatch)"/>
<g id="Illustration">
{cylinder(1270, 250, "Legacy", "SQL Server", MUTED)}
{flow}
<g id="Gate"><circle cx="1560" cy="380" r="46" fill="{CHIP}" stroke="{AMBER_500}" stroke-width="2.5"/>
{icon("check", 1538, 358, 44, AMBER_300, 2)}</g>
<path d="M1606 380 H1650" stroke="{AMBER_500}" stroke-width="2.5"/>
{cylinder(1770, 250, "New systems", "PostgreSQL + MongoDB", AMBER_500)}
</g>
<g id="Brand"><circle cx="168" cy="186" r="36" fill="none" stroke="url(#accent)" stroke-width="3"/>
{icon("migrate", 146, 164, 44, AMBER_300, 2)}
<text x="228" y="196" font-family="{FONT}" font-size="26" font-weight="600" letter-spacing="4" fill="{AMBER_300}">DATA MIGRATION</text></g>
<text id="Title" x="128" y="400" font-family="{FONT}" font-size="92" font-weight="800" fill="{INK}">Migration</text>
<text id="Title accent" x="128" y="500" font-family="{FONT}" font-size="92" font-weight="800" fill="{AMBER_500}">Control</text>
<rect x="132" y="540" width="120" height="4" rx="2" fill="url(#accent)"/>
<text id="Subtitle" x="132" y="600" font-family="{FONT}" font-size="26" fill="{MUTED}">Legacy core banking → new systems, one reconciled run at a time</text>
<g id="Navigation tiles">{"".join(tiles)}</g>
<text id="Footer" x="132" y="1030" font-family="{FONT}" font-size="18" fill="{MUTED}" fill-opacity="0.7">Power BI · PBIP / TMDL · DAX · run history exported by the migration pipeline</text>
</svg>"""


def page_svg(page):
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">', defs()]
    parts += shell(page.nav) + page_header(page) + frames_svg(page) + ["</svg>"]
    return "\n".join(parts)


# ------------------------------------------------------------------ write everything
def image_background(file_name):
    return {
        "image": {
            "image": {
                "name": text(file_name),
                "url": {
                    "expr": {
                        "ResourcePackageItem": {"PackageName": "RegisteredResources", "PackageType": 1, "ItemName": file_name}
                    }
                },
                "scaling": text("Fit"),
            }
        },
        "transparency": num(0),
    }


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_png(svgs: dict[str, str]) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        for slug, svg in svgs.items():
            page.set_content(f"<html><body style='margin:0'>{svg}</body></html>")
            page.screenshot(path=str(RES / f"bg_{slug}.png"), clip={"x": 0, "y": 0, "width": 1920, "height": 1080})
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true", help="render the PNG backgrounds with Playwright")
    args = parser.parse_args()
    pages = [cover(), status(), reconciliation(), backlog()]
    DESIGN.mkdir(parents=True, exist_ok=True)
    RES.mkdir(parents=True, exist_ok=True)
    svgs = {}
    for i, p in enumerate(pages):
        slug = f"{i}_{p.name}"
        svgs[slug] = cover_svg() if getattr(p, "kind", "") == "cover" else page_svg(p)
        (DESIGN / f"bg_{slug}.svg").write_text(svgs[slug], encoding="utf-8")
        if p.name != "Home":
            nav_buttons(p)
    if args.render:
        render_png(svgs)

    pages_dir = OUT / "pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    for i, p in enumerate(pages):
        img = f"bg_{i}_{p.name}.png"
        page_json = {
            "$schema": PAGE_SCHEMA,
            "name": p.name,
            "displayName": p.display,
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
            "objects": {
                "background": [{"properties": image_background(img)}],
                "outspace": [{"properties": {"color": color(SHELL_900), "transparency": num(0)}}],
            },
        }
        dump(pages_dir / p.name / "page.json", page_json)
        for v in p.visuals:
            dump(pages_dir / p.name / "visuals" / v["name"] / "visual.json", v)
    dump(pages_dir / "pages.json", {"$schema": PAGES_SCHEMA, "pageOrder": [p.name for p in pages], "activePageName": "Home"})

    theme_file = "MigrationTheme.json"
    dump(RES / theme_file, THEME)
    items = [{"name": f"bg_{i}_{p.name}.png", "path": f"bg_{i}_{p.name}.png", "type": "Image"} for i, p in enumerate(pages)]
    items.append({"name": theme_file, "path": theme_file, "type": "BaseTheme"})
    dump(
        OUT / "report.json",
        {
            "$schema": REPORT_SCHEMA,
            "themeCollection": {
                "customTheme": {
                    "name": theme_file,
                    "reportVersionAtImport": {"visual": "1.8.95", "report": "2.0.95", "page": "1.3.95"},
                    "type": "RegisteredResources",
                }
            },
            "objects": {"outspacePane": [{"properties": {"expanded": lit("false")}}]},
            "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources", "items": items}],
            "settings": {"useEnhancedTooltips": False},
        },
    )
    dump(OUT / "version.json", {"$schema": VERSION_SCHEMA, "version": "2.0.0"})
    (REPORT / "definition.pbir").write_text(
        json.dumps({"version": "4.0", "datasetReference": {"byPath": {"path": "../MigrationControl.SemanticModel"}}}, indent=2),
        encoding="utf-8",
    )
    platform = REPORT / ".platform"
    if not platform.exists():
        import uuid

        dump(
            platform,
            {
                "$schema": PLATFORM_SCHEMA,
                "metadata": {"type": "Report", "displayName": "MigrationControl"},
                "config": {"version": "2.0", "logicalId": str(uuid.uuid4())},
            },
        )
    print("pages:", [(p.display, len(p.visuals)) for p in pages])


if __name__ == "__main__":
    main()
