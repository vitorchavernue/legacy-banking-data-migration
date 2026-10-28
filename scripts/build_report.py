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

# ------------------------------------------------------------------ design tokens (navy, banking)
SHELL_900, SHELL_800, SHELL_700 = "#0A1B33", "#10294D", "#163866"
TEAL_600, TEAL_500, MINT_400 = "#2563EB", "#3B82F6", "#38BDF8"  # blue accents
PANEL, CARD, LINE = "#F3F6FB", "#FFFFFF", "#DFE6F1"
INK, MUTED, CHIP = "#0F1B33", "#5B6B85", "#E6EEFC"
CORAL = "#E0604F"
THEME = {
    "name": "Migration Control",
    "dataColors": [TEAL_600, "#F2A541", "#14B8A6", CORAL, "#8B5CF6", "#16A34A", "#94A3B8", "#EC4899"],
    "foreground": INK,
    "foregroundNeutralSecondary": MUTED,
    "background": CARD,
    "backgroundLight": PANEL,
    "tableAccent": TEAL_600,
    "good": "#2FB57C",
    "neutral": "#F2A541",
    "bad": CORAL,
    "maximum": TEAL_600,
    "center": "#BFD3F7",
    "minimum": "#FFFFFF",
}

ICONS = {
    "shield": '<path d="M12 3.5 19 6v5.5c0 4.3-3 7.6-7 9-4-1.4-7-4.7-7-9V6z"/><path d="M9 12l2.2 2.2L15.5 10"/>',
    "database": '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6"/>'
    '<path d="M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3"/>',
    "layers": '<path d="M12 3.5 21 8l-9 4.5L3 8z"/><path d="M3 12.5l9 4.5 9-4.5"/><path d="M3 17l9 4.5 9-4.5"/>',
    "inbox": '<path d="M3.5 13.5 6 5h12l2.5 8.5V19a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19z"/><path d="M3.5 13.5H8l1.5 2.5h5l1.5-2.5h4.5"/>',
    "coin": '<circle cx="12" cy="12" r="8"/><path d="M14.8 9.2c-.6-.9-1.6-1.4-2.8-1.4-1.6 0-2.8.9-2.8 2.1 0 2.9 5.6 1.4 5.6 4.2 0 1.2-1.2 2.1-2.8 2.1-1.2 0-2.3-.5-2.9-1.4M12 6.3v1.5M12 16.8v1.4"/>',
    "history": '<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6"/><path d="M3.5 4v4h4"/><path d="M12 7.5V12l3 2"/>',
    "migrate": '<rect x="3" y="4" width="7" height="16" rx="1.5"/><rect x="14" y="4" width="7" height="16" rx="1.5"/><path d="M8 12h8M13.5 9.5 16 12l-2.5 2.5"/>',
    "home": '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v10h13V10"/><path d="M10 20v-5h4v5"/>',
    "overview": '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/>'
    '<rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "scorecard": '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "trend": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "headset": '<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="13" width="4" height="6" rx="1.5"/>'
    '<rect x="17" y="13" width="4" height="6" rx="1.5"/><path d="M19 19c0 1.5-1.5 2.5-4 2.5h-2"/>',
    "target": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.8"/><circle cx="12" cy="12" r="1.3"/>',
    "check": '<circle cx="12" cy="12" r="8.5"/><path d="M8.3 12.2l2.5 2.5 4.9-5"/>',
    "exit": '<path d="M14 4h4.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H14"/><path d="M10 16l4-4-4-4M14 12H4"/>',
    "hourglass": '<path d="M7 3.5h10M7 20.5h10M8 3.5c0 4 8 4.5 8 8.5s-8 4.5-8 8.5M16 3.5c0 4-8 4.5-8 8.5"/>',
    "users": '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.4 2.7-6 6-6s6 2.6 6 6"/><circle cx="17.5" cy="9" r="2.4"/>'
    '<path d="M16.5 14.2c2.6.3 4.5 2.4 4.5 5"/>',
    "alert": '<path d="M12 4 21 19.5H3z"/><path d="M12 10v4.2"/><circle cx="12" cy="17" r=".6"/>',
    "filter": '<path d="M4 5h16l-6 7.5V19l-4 1.5v-8z"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
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
            {"properties": {"show": lit("true" if (len(values) > 1 or series) else "false"), "position": text("TopRight")}}
        ],
        "valueAxis": [{"properties": {"gridlineColor": color("#E6EFEF"), "fontSize": num(9), "labelColor": color(MUTED)}}],
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
                            "fontColor": color(SHELL_800),
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
                            "backColorSecondary": color("#F6FAFA"),
                        }
                    }
                ],
                "grid": [{"properties": {"gridHorizontalColor": color("#EAF1F1"), "outlineColor": color(LINE)}}],
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
            "objects": {"data": [{"properties": {"mode": text("Dropdown")}}], "header": [{"properties": {"show": lit("false")}}]},
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
        colors=[TEAL_600],
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
        colors=[TEAL_600],
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
    <stop stop-color="{SHELL_900}"/><stop offset="0.55" stop-color="{SHELL_800}"/><stop offset="1" stop-color="{SHELL_700}"/>
  </linearGradient>
  <linearGradient id="accent" x1="0" y1="0" x2="0" y2="1">
    <stop stop-color="{MINT_400}"/><stop offset="1" stop-color="{TEAL_600}"/>
  </linearGradient>
  <linearGradient id="activeChip" x1="0" y1="0" x2="1" y2="1">
    <stop stop-color="{TEAL_500}"/><stop offset="1" stop-color="{MINT_400}"/>
  </linearGradient>
  <radialGradient id="glow" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(1700 120) scale(900)">
    <stop stop-color="{MINT_400}" stop-opacity="0.30"/><stop offset="1" stop-color="{MINT_400}" stop-opacity="0"/>
  </radialGradient>
  <filter id="shadow" x="-10%" y="-10%" width="120%" height="140%" color-interpolation-filters="sRGB">
    <feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="{SHELL_800}" flood-opacity="0.08"/>
    <feDropShadow dx="0" dy="1" stdDeviation="1.5" flood-color="{SHELL_800}" flood-opacity="0.06"/>
  </filter>
  <filter id="panelShadow" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
    <feDropShadow dx="0" dy="12" stdDeviation="24" flood-color="#00110F" flood-opacity="0.35"/>
  </filter>
  <pattern id="dots" x="0" y="0" width="28" height="28" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="2" r="1.6" fill="#FFFFFF" fill-opacity="0.08"/>
  </pattern>
</defs>"""


FONT = "Inter, Segoe UI, sans-serif"


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def shell(active):
    out = [
        '<rect id="Background" width="1920" height="1080" fill="url(#shell)"/>',
        '<rect id="Glow" width="1920" height="1080" fill="url(#glow)"/>',
        '<rect id="Dot grid" x="1500" y="0" width="420" height="300" fill="url(#dots)"/>',
        '<g id="Navigation rail">',
        '<g id="Brand mark"><rect x="24" y="30" width="48" height="48" rx="14" fill="url(#activeChip)"/>'
        + icon("migrate", 33, 39, 30, "#FFFFFF", 2.2)
        + "</g>",
    ]
    for i, (name, _, label) in enumerate(NAV):
        cy = (108 + i * 64 + 24) * S
        if name == active:
            out.append(
                f'<rect id="Active {label}" x="20" y="{cy - 28:.0f}" width="56" height="56" rx="16" fill="url(#activeChip)"/>'
                f'<rect x="0" y="{cy - 20:.0f}" width="5" height="40" rx="2.5" fill="{MINT_400}"/>'
            )
            out.append(icon(name, 33, cy - 15, 30, "#FFFFFF", 2, f"Icon {label}"))
        else:
            out.append(
                icon(name, 33, cy - 15, 30, "#FFFFFF", 1.8, f"Icon {label}").replace(
                    'stroke="#FFFFFF"', 'stroke="#FFFFFF" stroke-opacity="0.62"'
                )
            )
    out.append("</g>")
    out.append(
        f'<rect id="Content panel" x="{72 * S}" y="{8 * S}" width="{(1272 - 72) * S}" height="{(712 - 8) * S}" rx="30" '
        f'fill="{PANEL}" filter="url(#panelShadow)"/>'
    )
    return out


def page_header(page):
    return [
        '<g id="Header">',
        f'<rect x="{94 * S}" y="{20 * S}" width="{30 * S}" height="{30 * S}" rx="12" fill="{CHIP}"/>',
        icon(page.nav, 94 * S + 10, 20 * S + 10, 25, TEAL_600, 2, "Header icon"),
        f'<rect x="{126 * S}" y="{24 * S}" width="2" height="{22 * S}" rx="1" fill="{LINE}"/>',
        f'<rect id="Data badge" x="{994 * S}" y="{26 * S}" width="{256 * S}" height="{28 * S}" rx="{14 * S}" fill="{CHIP}"/>',
        f'<circle cx="{1008 * S}" cy="{40 * S}" r="5" fill="{MINT_400}"/>',
        f'<text x="{1018 * S}" y="{40 * S + 7}" font-family="{FONT}" font-size="19" font-weight="600" fill="{TEAL_600}">'
        "Cut-over rehearsal · 10 business days</text>",
        f'<text id="Page title" x="{136 * S}" y="{37 * S}" font-family="{FONT}" font-size="28" font-weight="700" fill="{INK}">'
        f"{esc(page.title)}</text>",
        f'<text id="Page subtitle" x="{136 * S}" y="{58 * S}" font-family="{FONT}" font-size="17" fill="{MUTED}">'
        f"{esc(page.subtitle)}</text>",
        f'<rect x="{X0 * S}" y="{76 * S}" width="{(X1 - X0) * S}" height="1.5" fill="{LINE}"/>',
        "</g>",
    ]


def frames_svg(page):
    out = ['<g id="Frames">']
    for f in page.frames:
        x, y, w, h = f["x"] * S, f["y"] * S, f["w"] * S, f["h"] * S
        out.append(f'<g id="Frame {f["id"]}">')
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="20" fill="{CARD}" '
            f'stroke="{LINE}" stroke-width="1.5" filter="url(#shadow)"/>'
        )
        if f["kind"] == "kpi":
            out.append(f'<rect x="{x:.1f}" y="{y + 18:.1f}" width="5" height="{h - 36:.1f}" rx="2.5" fill="url(#accent)"/>')
        if f["kind"] in ("kpi", "control") and f["icon"]:
            cx, cy = x + w - 52, y + 16
            out.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="38" height="38" rx="11" fill="{CHIP}"/>')
            out.append(icon(f["icon"], cx + 8, cy + 8, 22, TEAL_600, 2))
        if f["kind"] == "chart":
            out.append(f'<rect x="{x + 16:.1f}" y="{y + 20:.1f}" width="5" height="22" rx="2.5" fill="url(#accent)"/>')
        out.append("</g>")
    out.append("</g>")
    return out


def cover_svg():
    tiles = []
    descriptions = ["Gate, coverage and money", "Every check in every run", "Reasons and burn-down"]
    labels = ["Cut-over status", "Reconciliation", "Rejected backlog"]
    for i, (name, _, _) in enumerate(NAV[1:]):
        x, y, w, h = (88 + i * 292) * S, 560 * S, 276 * S, 96 * S
        tiles.append(
            f'<g id="Tile {labels[i]}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="22" fill="#FFFFFF" '
            f'fill-opacity="0.07" stroke="#FFFFFF" stroke-opacity="0.16" stroke-width="1.5"/>'
            f'<rect x="{x + 22}" y="{y + 30}" width="84" height="84" rx="20" fill="url(#activeChip)"/>'
            + icon(name, x + 43, y + 51, 42, "#FFFFFF", 2)
            + f'<text x="{x + 126}" y="{y + 66}" font-family="{FONT}" font-size="25" font-weight="600" fill="#FFFFFF">'
            f"{labels[i]}</text>"
            f'<text x="{x + 126}" y="{y + 100}" font-family="{FONT}" font-size="18" fill="#FFFFFF" fill-opacity="0.66">'
            f"{descriptions[i]}</text>"
            f'<path d="M{x + w - 36} {y + h / 2 - 9} l9 9 -9 9" stroke="{MINT_400}" stroke-width="3" fill="none" '
            'stroke-linecap="round" stroke-linejoin="round"/></g>'
        )
    # burn-down motif: the rejected backlog shrinking day after day
    heights = [380, 270, 190, 140, 115, 85, 60, 45, 32, 28]
    bars = "".join(
        f'<rect x="{1300 + i * 58}" y="{720 - hgt}" width="40" height="{hgt}" rx="10" fill="#FFFFFF" '
        f'fill-opacity="{0.22 - i * 0.015:.3f}"/>'
        for i, hgt in enumerate(heights)
    )
    trend = " ".join(f"{1320 + i * 58},{720 - hgt}" for i, hgt in enumerate(heights))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
{defs()}
<rect id="Background" width="1920" height="1080" fill="url(#shell)"/>
<rect id="Glow" width="1920" height="1080" fill="url(#glow)"/>
<rect id="Dot grid" x="1080" y="80" width="760" height="560" fill="url(#dots)"/>
<g id="Burn-down bars">{bars}</g>
<polyline id="Burn-down line" points="{trend}" stroke="{MINT_400}" stroke-opacity="0.7" stroke-width="4" fill="none"/>
<g id="Brand"><rect x="132" y="150" width="72" height="72" rx="20" fill="url(#activeChip)"/>
{icon("migrate", 146, 164, 44, "#FFFFFF", 2.2)}
<text x="228" y="196" font-family="{FONT}" font-size="26" font-weight="600" letter-spacing="3" fill="#FFFFFF" fill-opacity="0.8">DATA MIGRATION</text></g>
<g id="Title pill"><rect x="-60" y="300" width="1100" height="150" rx="75" fill="#FFFFFF"/>
<text x="132" y="398" font-family="{FONT}" font-size="64" font-weight="700" fill="{SHELL_800}">Migration Control</text>
<circle cx="965" cy="375" r="50" fill="url(#activeChip)"/><path d="M952 352 l30 23 -30 23z" fill="#FFFFFF"/></g>
<text id="Subtitle" x="132" y="520" font-family="{FONT}" font-size="28" fill="#FFFFFF" fill-opacity="0.78">Legacy core banking (SQL Server) → PostgreSQL + MongoDB</text>
<g id="Navigation tiles">{"".join(tiles)}</g>
<text id="Footer" x="132" y="1030" font-family="{FONT}" font-size="18" fill="#FFFFFF" fill-opacity="0.45">Power BI · PBIP / TMDL · DAX · run history exported by the migration pipeline</text>
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
