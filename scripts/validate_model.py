"""Quality gate for the Power BI project, run in CI on every push.

1. Loads the semantic model (TMDL) with Microsoft's Tabular Object Model, the same library Power BI
   uses: a syntax or reference error in any table, measure, role or relationship fails here.
2. Applies best-practice rules (documentation, hidden keys, no bidirectional filters, DIVIDE instead
   of "/", snapshot tables never summed across runs ...).
3. Checks the report: every field used by a visual or filter exists in the model, every
   navigation button points to a page, every background image is in the project.

    python scripts/validate_model.py            # exit code 1 when a rule fails
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "powerbi"
MODEL = ROOT / "MigrationControl.SemanticModel" / "definition"
REPORT = ROOT / "MigrationControl.Report"
# measures that return text: no number format
TEXT_MEASURES = {
    "Gate Status",
    "Critical Checks Label",
    "Check Result",
    "Last Run Result",
    "Last Run Legacy Value",
    "Last Run New Value",
    "Last Run Detail",
}
# one row per run: summing them across runs would count the same legacy rows several times
SNAPSHOT_TABLES = {"Coverage", "Backlog"}
# ids shown on purpose: the rejected list is a work list, the data owners search the legacy id
VISIBLE_IDS = {"Rejected Records[Source ID]"}


@dataclass
class Result:
    rule: str
    passed: bool
    detail: str = ""


def load_model():
    """Deserialize the TMDL folder with the Tabular Object Model (TOM)."""
    from pythonnet import load

    load("coreclr")
    import clr

    spec = importlib.util.find_spec("sempy")  # the TOM assemblies ship with Microsoft's semantic-link package
    if spec is None or not spec.submodule_search_locations:
        sys.exit("semantic-link-sempy is not installed (pip install semantic-link-sempy --no-deps)")
    sys.path.append(str(Path(spec.submodule_search_locations[0]) / "lib"))
    clr.AddReference("Microsoft.AnalysisServices.Tabular")
    from Microsoft.AnalysisServices.Tabular import TmdlSerializer

    return TmdlSerializer.DeserializeDatabaseFromFolder(str(MODEL)).Model


def model_rules(model) -> list[Result]:
    tables = list(model.Tables)
    measures = [(t.Name, ms) for t in tables for ms in t.Measures]
    columns = [(t, col) for t in tables for col in t.Columns if col.Type.ToString() != "RowNumber"]
    out: list[Result] = []

    def rule(name, failures):
        out.append(Result(name, not failures, ", ".join(failures[:8]) + (" ..." if len(failures) > 8 else "")))

    # Documentation and usability
    rule("Every measure has a description", [ms.Name for _, ms in measures if not ms.Description])
    rule(
        "Every numeric measure has a format string",
        [ms.Name for _, ms in measures if not ms.FormatString and ms.Name not in TEXT_MEASURES],
    )
    rule("Every measure is in a display folder", [ms.Name for _, ms in measures if not ms.DisplayFolder])
    rule("Every visible table has a description", [t.Name for t in tables if not t.IsHidden and not t.Description])
    rule("Implicit measures are disabled (only curated measures)", [] if model.DiscourageImplicitMeasures else ["model"])

    # Modelling
    rule(
        "Key and id columns are hidden",
        [
            f"{t.Name}[{col.Name}]"
            for t, col in columns
            if re.search(r"( Key| ID)$", col.Name) and not col.IsHidden and f"{t.Name}[{col.Name}]" not in VISIBLE_IDS
        ],
    )
    rule(
        "Visible numeric columns do not sum by default",
        [
            f"{t.Name}[{col.Name}]"
            for t, col in columns
            if not col.IsHidden
            and col.DataType.ToString() in ("Int64", "Double", "Decimal")
            and col.SummarizeBy.ToString() != "None"
        ],
    )
    rule(
        "No bidirectional relationships",
        [
            f"{r.FromTable.Name}->{r.ToTable.Name}"
            for r in model.Relationships
            if r.CrossFilteringBehavior.ToString() == "BothDirections"
        ],
    )
    rule(
        "Text columns with a natural order have a sort column",
        [f"{t.Name}[{col.Name}]" for t, col in columns if col.Name in ("Run Label", "Entity") and col.SortByColumn is None],
    )

    # DAX
    # DAX keywords cannot be variable names (e.g. CURRENT is reserved): the query fails only when a visual runs it
    reserved = {
        "current",
        "previous",
        "next",
        "first",
        "last",
        "value",
        "values",
        "table",
        "column",
        "measure",
        "define",
        "evaluate",
        "order",
        "by",
        "start",
        "at",
        "return",
        "var",
        "true",
        "false",
        "not",
        "in",
    }
    expressions = [(ms.Name, ms.Expression) for _, ms in measures] + [
        (f"{t.Name}[{item.Name}]", item.Expression)
        for t in tables
        if t.CalculationGroup is not None
        for item in t.CalculationGroup.CalculationItems
    ]
    rule(
        "DAX variables do not use reserved words",
        [
            name
            for name, expr in expressions
            if any(v.lower() in reserved for v in re.findall(r"\bVAR\s+([A-Za-z_][\w]*)", expr or "", re.IGNORECASE))
        ],
    )
    division = re.compile(r"\]\s*/\s*[\[\w(]")
    rule(
        "Measures divide with DIVIDE (no division by zero errors)",
        [ms.Name for _, ms in measures if division.search(re.sub(r"--.*", "", ms.Expression))],
    )

    # Snapshots: every measure on a snapshot table picks one run (the last one in the selection by default)
    rule(
        "Snapshot measures never add up several runs",
        [
            ms.Name
            for table, ms in measures
            if table in SNAPSHOT_TABLES and "SUM (" in ms.Expression and "Runs[Run ID] =" not in ms.Expression
        ],
    )
    return out


def report_rules(model) -> list[Result]:
    fields = {(t.Name, x.Name) for t in model.Tables for x in list(t.Columns) + list(t.Measures)}
    pages_dir = REPORT / "definition" / "pages"
    pages = json.loads((pages_dir / "pages.json").read_text(encoding="utf-8"))["pageOrder"]
    resources = {p.name for p in (REPORT / "StaticResources" / "RegisteredResources").glob("*")}
    missing_fields, broken_links, missing_images, visuals = [], [], [], 0

    def walk(node, where):
        if isinstance(node, dict):
            for kind in ("Measure", "Column"):
                ref = node.get(kind)
                if isinstance(ref, dict) and "Entity" in ref.get("Expression", {}).get("SourceRef", {}):
                    key = (ref["Expression"]["SourceRef"]["Entity"], ref["Property"])
                    if key not in fields:
                        missing_fields.append(f"{where}: {key[0]}[{key[1]}]")
            for value in node.values():
                walk(value, where)
        elif isinstance(node, list):
            for value in node:
                walk(value, where)

    for page in pages:
        page_json = json.loads((pages_dir / page / "page.json").read_text(encoding="utf-8"))
        image = page_json["objects"]["background"][0]["properties"]["image"]["image"]["url"]["expr"]
        if image["ResourcePackageItem"]["ItemName"] not in resources:
            missing_images.append(page)
        for path in sorted((pages_dir / page / "visuals").glob("*/visual.json")):
            visuals += 1
            visual = json.loads(path.read_text(encoding="utf-8"))
            walk(visual, f"{page}/{visual['name']}")
            link = visual["visual"].get("visualContainerObjects", {}).get("visualLink")
            if link:
                target = link[0]["properties"]["navigationSection"]["expr"]["Literal"]["Value"].strip("'")
                if target not in pages:
                    broken_links.append(f"{page}/{visual['name']} -> {target}")
    return [
        Result(
            f"Every field used by the {visuals} visuals exists in the model", not missing_fields, ", ".join(missing_fields[:8])
        ),
        Result("Every navigation button points to an existing page", not broken_links, ", ".join(broken_links)),
        Result("Every page background image is in the project", not missing_images, ", ".join(missing_images)),
    ]


def main() -> int:
    model = load_model()
    tables = list(model.Tables)
    print(
        f"Semantic model loaded: {len(tables)} tables, {sum(t.Measures.Count for t in tables)} measures, "
        f"{model.Relationships.Count} relationships, {model.Roles.Count} roles\n"
    )
    results = model_rules(model) + report_rules(model)
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.rule}" + (f"  ({r.detail})" if r.detail and not r.passed else ""))
    failed = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} rules passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
