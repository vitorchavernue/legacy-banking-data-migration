"""Command line.

    python -m migration seed --scale 1        # create the legacy database with synthetic data
    python -m migration changes               # simulate a day of activity in the legacy system
    python -m migration run --mode full       # initial load + reconciliation gate
    python -m migration run --mode incremental
    python -m migration reset-target          # empty PostgreSQL and MongoDB (development only)
    python -m migration serve                 # read-only API for the apps and the ops team
    python -m migration simulate --days 10    # cut-over rehearsal: full load + daily incremental runs
    python -m migration export --out powerbi/data   # run history for the Power BI dashboard

Exit code 1 when the reconciliation gate fails (CI and schedulers stop the pipeline).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from sqlalchemy.engine import make_url

from migration.config import get_settings
from migration.db import legacy_engine


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
    )
    parser = argparse.ArgumentParser(prog="migration")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed", help="create the legacy tables with synthetic data")
    seed.add_argument("--scale", type=float, default=1.0)
    sub.add_parser("changes", help="apply day-to-day changes to the legacy data")
    sub.add_parser("reset-target", help="empty PostgreSQL (core, migration) and the MongoDB profiles")
    run = sub.add_parser("run", help="migrate and reconcile")
    run.add_argument("--mode", choices=["full", "incremental"], default="full")
    sim = sub.add_parser("simulate", help="cut-over rehearsal with daily runs (recreates the legacy data)")
    sim.add_argument("--days", type=int, default=10)
    sim.add_argument("--scale", type=float, default=1.0)
    exp = sub.add_parser("export", help="export the run history for the Power BI dashboard")
    exp.add_argument("--out", default="powerbi/data")
    serve = sub.add_parser("serve", help="start the API")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    settings = get_settings()

    if args.command == "seed":
        from migration.legacy import seed as seed_mod

        url = make_url(settings.legacy_db_url)
        if url.get_backend_name() == "mssql":
            seed_mod.create_database_if_missing(url.set(database="master"), url.database)
        counts = seed_mod.load(legacy_engine(settings), seed_mod.generate(scale=args.scale))
        print(json.dumps(counts))
        return 0
    if args.command == "changes":
        from migration.legacy.seed import apply_changes

        print(json.dumps(apply_changes(legacy_engine(settings))))
        return 0
    if args.command == "reset-target":
        from sqlalchemy import text

        from migration.db import mongo_db, target_engine

        with target_engine(settings).begin() as conn:
            conn.execute(text("drop schema if exists core cascade"))
            conn.execute(text("drop schema if exists migration cascade"))
        mongo_db(settings).customer_profiles.drop()
        print("target emptied")
        return 0
    if args.command == "run":
        from migration.runner import run as run_migration

        result = run_migration(args.mode, settings)
        print(json.dumps({"run_id": result["run_id"], "status": result["status"], "stats": result["stats"]}))
        return 0 if result["status"] == "passed" else 1
    if args.command == "simulate":
        from migration.simulate import simulate

        results = simulate(days=args.days, scale=args.scale, settings=settings)
        print(json.dumps([{"run_id": r["run_id"], "status": r["status"]} for r in results]))
        return 0
    if args.command == "export":
        from migration.export import export

        print(json.dumps(export(args.out, settings)))
        return 0
    if args.command == "serve":
        import uvicorn

        uvicorn.run("migration.api.app:app", host="0.0.0.0", port=args.port)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
