"""Run report in Markdown (for people) and JSON (for tools), saved under reports/."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from migration.reconcile import Check


def write(reports_dir: str, run_id: int, mode: str, status: str, stats: dict, checks: list[Check]) -> Path:
    folder = Path(reports_dir)
    folder.mkdir(parents=True, exist_ok=True)
    icon = {"passed": "✅", "failed": "❌"}.get(status, "⚠️")
    lines = [
        f"# Migration run {run_id} ({mode}) — {icon} {status.upper()}",
        "",
        "## Volumes",
        "",
        "| Legacy table | Read | Migrated | Rejected |",
        "|---|---:|---:|---:|",
    ]
    for table, s in stats.get("tables", {}).items():
        lines.append(f"| {table} | {s['read']:,} | {s['loaded']:,} | {s['rejected']:,} |")
    lines += [
        "",
        f"App profiles refreshed in MongoDB: **{stats.get('profiles_refreshed', 0):,}** · "
        f"duration: **{stats.get('duration_s', 0):.1f} s**",
        "",
        "## Reconciliation",
        "",
        "| Check | Severity | Result | Legacy | New systems | Detail |",
        "|---|---|---|---|---|---|",
    ]
    for c in checks:
        result = "✅" if c.passed else ("❌" if c.severity == "critical" else "⚠️")
        lines.append(f"| {c.name} | {c.severity} | {result} | {c.source_value} | {c.target_value} | {c.detail} |")
    text = "\n".join(lines) + "\n"
    path = folder / f"run_{run_id:04d}.md"
    path.write_text(text, encoding="utf-8")
    (folder / "latest.md").write_text(text, encoding="utf-8")
    payload = {"run_id": run_id, "mode": mode, "status": status, "stats": stats, "checks": [asdict(c) for c in checks]}
    (folder / "latest.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
