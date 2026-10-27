"""Legacy core banking tables, as they exist in the old SQL Server database.

Typical legacy design: Portuguese abbreviations, codes instead of descriptions, dates stored
as text in some columns, no foreign keys and a "last changed" column maintained by the old
application. These tables are only read by the migration (except by the seed script).
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Integer, MetaData, Numeric, String, Table, Unicode
from sqlalchemy.dialects import mssql

# DATETIME2 on SQL Server (DATETIME would round milliseconds and break comparisons)
Timestamp = DateTime().with_variant(mssql.DATETIME2(), "mssql")

metadata = MetaData()

# Customers: CPF stored as typed by the branch (with or without punctuation, sometimes as a
# number that lost its leading zeros), birth date as free text, status as a one-letter code.
customers = Table(
    "TB_CLIENTE",
    metadata,
    Column("CD_CLIENTE", Integer, primary_key=True, autoincrement=False),
    Column("NM_CLIENTE", Unicode(120)),
    Column("NR_CPF", String(14)),
    Column("DS_EMAIL", String(120)),
    Column("DT_NASCIMENTO", String(10)),
    Column("CD_SITUACAO", String(1)),  # A = active, I = inactive, B = blocked
    Column("DT_ULTIMA_ALTERACAO", Timestamp, nullable=False),
)

# Accounts: no foreign key to customers (orphans exist), branch without padding,
# account number with the check digit in the same column.
accounts = Table(
    "TB_CONTA",
    metadata,
    Column("CD_CONTA", Integer, primary_key=True, autoincrement=False),
    Column("CD_CLIENTE", Integer),
    Column("NR_AGENCIA", String(4)),
    Column("NR_CONTA", String(12)),
    Column("CD_TIPO", String(2)),  # CC = checking, PP = savings
    Column("DT_ABERTURA", Timestamp),
    Column("CD_SITUACAO", String(1)),  # A = active, E = closed (encerrada)
    Column("DT_ULTIMA_ALTERACAO", Timestamp, nullable=False),
)

# Transactions: always a positive amount plus a credit/debit flag.
transactions = Table(
    "TB_LANCAMENTO",
    metadata,
    Column("CD_LANCAMENTO", BigInteger, primary_key=True, autoincrement=False),
    Column("CD_CONTA", Integer),
    Column("VL_LANCAMENTO", Numeric(15, 2)),
    Column("TP_LANCAMENTO", String(1)),  # C = credit, D = debit
    Column("DT_LANCAMENTO", Timestamp),
    Column("DS_HISTORICO", Unicode(60)),
    Column("DT_ULTIMA_ALTERACAO", Timestamp, nullable=False),
)

# Source table -> primary key column, used by extraction and reconciliation
PRIMARY_KEYS = {
    "TB_CLIENTE": "CD_CLIENTE",
    "TB_CONTA": "CD_CONTA",
    "TB_LANCAMENTO": "CD_LANCAMENTO",
}
TABLES = {t.name: t for t in (customers, accounts, transactions)}
