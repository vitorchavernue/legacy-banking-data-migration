# ADR 0003 — Reconciliation is a release gate, not a report

**Status:** accepted

## Context

In a banking migration, "the job finished" says nothing about the data. The risk is silent:
a transaction lost, a sign inverted, an account attached to the wrong customer.

## Decision

Every run ends with reconciliation between the legacy system and the new systems:

| Check | Severity |
|---|---|
| Every legacy customer / account / transaction is migrated or rejected (nothing lost, nothing invented) | critical |
| Accounts belong to the customer their legacy owner maps to | critical |
| Transactions match field by field (amount with sign, date, account) | critical |
| Net amount of migrated transactions matches | critical |
| Every customer has an app profile; app balances equal PostgreSQL | critical |
| Duplicates merged, money in rejected transactions, rejects by reason | info |

Any critical failure marks the run as `failed`, exits with code 1 (the scheduler stops), sends
an alert and blocks the cut-over. Results are stored per run (`migration.reconciliation_check`),
published as a Markdown/JSON report and exposed by the API.

## Consequences

* The integration tests prove the gate works: a value edited by hand in PostgreSQL makes the
  next run fail, and a full run repairs it.
* Row-by-row comparison runs in memory, which is fine for this volume. For hundreds of millions
  of rows it would move to hash-bucket comparison in SQL on both sides.
