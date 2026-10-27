# ADR 0001 — Incremental sync by "changed at" watermark

**Status:** accepted

## Context

The new systems must stay in sync with the legacy database for weeks before the cut-over,
without overloading it. Options considered:

1. **Full reload every time** — simple, but reads the whole database on every run.
2. **SQL Server Change Data Capture (CDC)** — exact, captures deletes, but needs DBA work,
   the SQL Server Agent and extra storage on a system we are about to retire.
3. **Watermark on the "last changed" column** (`DT_ULTIMA_ALTERACAO`) that the legacy
   application already maintains.

## Decision

Option 3. Each run reads rows changed since the last watermark **minus a 5-minute overlap**
(rows committed late with an older timestamp are not missed), plus every record rejected
before. Writes are upserts guarded by `source_updated_at`, so re-reading a row is harmless and
an old version never overwrites a newer one. Watermarks move forward only after the data is loaded.

## Consequences

* No change to the legacy system; each run reads hundreds of rows instead of the whole database.
* Hard deletes are not seen by the sync. The reconciliation completeness checks catch them
  (rows that exist only in the new systems). If the business requires deletes, switch the
  extraction to SQL Server CDC; the transform and load layers do not change.
