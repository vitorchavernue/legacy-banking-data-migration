# ADR 0002 — PostgreSQL as the system of record, MongoDB as the app read model

**Status:** accepted

## Context

The web and mobile apps open with one screen: the customer, their accounts and balances.
Computing it from the relational model means joins and a sum over every transaction, on the
busiest endpoint.

## Decision

* **PostgreSQL** holds the data with real constraints (keys, foreign keys, checks on status
  and on the sign of amounts). It is the system of record.
* **MongoDB** holds one **customer profile document** per customer, rebuilt from PostgreSQL
  after each run (only customers touched by the run in incremental mode).
* Money is `numeric(15,2)` in PostgreSQL and `Decimal128` in MongoDB — never float — and the
  API returns it as text.

## Consequences

* The profile is a single read by `_id` or CPF (unique index).
* The profile is derived data: it can always be rebuilt, and the reconciliation gate checks
  that every customer has one and that every balance equals the PostgreSQL sum.
