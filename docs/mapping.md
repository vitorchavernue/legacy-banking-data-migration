# Source-to-target mapping

Legacy SQL Server (`TB_*`) → PostgreSQL (`core.*`) → MongoDB (`app.customer_profiles`).
Rules are implemented in [`src/migration/rules.py`](../src/migration/rules.py) and
[`src/migration/transform.py`](../src/migration/transform.py), and covered by unit tests.

## Customers — `TB_CLIENTE` → `core.customer`

| Legacy column | Target column | Rule | When it fails |
|---|---|---|---|
| — | `customer_id` | UUID v5 of the CPF (one person = one customer) | — |
| `CD_CLIENTE` | `migration.customer_key_map.legacy_customer_id` | Every legacy registration is kept in the key map | — |
| `NR_CPF` | `cpf` | Digits only, left-padded to 11 (numbers that lost leading zeros), official check-digit validation | **Rejected**: missing, wrong length, invalid check digits |
| `NM_CLIENTE` | `full_name` | Broken accents repaired (Windows-1252 read as UTF-8), spaces collapsed, name case with lowercase particles (da, de, dos…) | **Rejected**: empty or shorter than 3 characters |
| `DS_EMAIL` | `email` | Trimmed, lowercase | Invalid → `NULL` (not a reason to reject) |
| `DT_NASCIMENTO` (text) | `birth_date` | `dd/mm/yyyy` or `yyyy-mm-dd`, between 1900 and today | Invalid → `NULL` |
| `CD_SITUACAO` | `status` | `A` active · `I` inactive · `B` blocked | **Rejected**: unknown code |
| `DT_ULTIMA_ALTERACAO` | `source_updated_at` | Local time (America/Sao_Paulo) → `timestamptz` | — |

**Duplicates:** registrations with the same CPF are merged. The most recently changed one
provides the customer data; all of them map to the same `customer_id`, so their accounts follow.

## Accounts — `TB_CONTA` → `core.account`

| Legacy column | Target column | Rule | When it fails |
|---|---|---|---|
| `CD_CONTA` | `account_id`, `legacy_account_id` | UUID v5 of the legacy id; legacy id kept for traceability | — |
| `CD_CLIENTE` | `customer_id` | Through the key map (after the duplicate merge) | **Rejected**: customer missing or rejected |
| `NR_AGENCIA` | `branch` | Digits, left-padded to 4 | **Rejected**: invalid |
| `NR_CONTA` | `account_number`, `check_digit` | `12345-6` or `123456` → `12345` + `6` | **Rejected**: invalid format |
| `CD_TIPO` | `account_type` | `CC` checking · `PP` savings | **Rejected**: unknown code |
| `CD_SITUACAO` | `status` | `A` active · `E` closed | **Rejected**: unknown code |
| `DT_ABERTURA` | `opened_at` | Local time → `timestamptz` | — |

## Transactions — `TB_LANCAMENTO` → `core.transaction`

| Legacy column | Target column | Rule | When it fails |
|---|---|---|---|
| `CD_LANCAMENTO` | `transaction_id` | Same id | — |
| `CD_CONTA` | `account_id` | Must be a migrated account | **Rejected**: account missing or rejected |
| `VL_LANCAMENTO` + `TP_LANCAMENTO` | `amount`, `direction` | Positive amount + `C`/`D` → signed amount (credits > 0, debits < 0), 2 decimals | **Rejected**: zero, negative or missing amount; unknown type |
| `DT_LANCAMENTO` | `posted_at` | Local time → `timestamptz` | **Rejected**: missing or later than the run start |
| `DS_HISTORICO` | `description` | Trimmed, broken accents repaired | — |

## App profile — `core.*` → MongoDB `customer_profiles`

One document per customer, rebuilt from PostgreSQL after each run (only touched customers in
incremental runs): customer data, CPF index, accounts with **balance** (sum of signed amounts,
stored as `Decimal128`) and last transaction date, and the total balance.

## Rejected records

Every rejected row goes to `migration.rejected_record` with the reason and the original row
(JSON). Rejected records are **retried on every run**: once the business fixes the legacy row,
it is migrated and leaves the list. The list is the work queue for the data owners.
