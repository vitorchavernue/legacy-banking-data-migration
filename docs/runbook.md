# Cut-over runbook

How this migration is run in production, from the first load to switching the apps.

## 1. Before the cut-over (weeks)

1. **Full load** in a quiet window: `python -m migration run --mode full`.
2. **Incremental runs** on a schedule (e.g. every 15 minutes), keeping the new systems in sync
   while the legacy system is still the system of record: `python -m migration run --mode incremental`.
3. Every run ends with the **reconciliation gate**. A failure stops the pipeline (exit code 1),
   records the run as `failed` and sends an alert to the team channel.
4. Business owners work the **rejected records** list (`migration.rejected_record`, or the
   `Rejected records by reason` line of each report). Fixed rows are migrated by the next run.
5. Apps are tested against the new systems in a staging environment (API `/customers`, `/accounts`).

## 2. Cut-over (hours)

1. Freeze writes in the legacy system.
2. Last incremental run → must be `passed`, with **zero critical failures**.
3. Business sign-off on the remaining rejected records and on the money they hold
   (`Money in rejected transactions` line).
4. Switch the apps to the new API / databases. Keep the legacy system read-only.

## 3. Rollback

Nothing is ever deleted from the legacy system. If the gate fails or the apps misbehave,
the apps point back to the legacy system and the new databases are rebuilt with a full load
(all writes are idempotent upserts, so a full run can always be repeated).

## Monitoring

| Signal | Where |
|---|---|
| Run status, duration, volumes | `migration.run`, API `GET /migration/runs` |
| Each reconciliation check | `migration.reconciliation_check`, API `GET /migration/runs/{id}`, `reports/*.md` |
| Failures | Chat alert (webhook in `ALERT_WEBHOOK_URL`) + exit code 1 for the scheduler |
| Databases reachable | API `GET /health` |

## Known limitation

Hard deletes in the legacy system are not visible to the incremental sync (there is no "changed
at" on a deleted row). They are still caught: the completeness checks report rows that exist
only in the new systems. Closing an account or blocking a customer is a status change and is synced.
