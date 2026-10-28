"""Synthetic legacy core banking data, with the defects found in real legacy systems.

All data is fictitious (generated names and valid-format CPFs). Defects are planted on
purpose, in known proportions, so the migration must deal with them:

* the same person registered twice (CPF typed with and without punctuation)
* CPFs stored as numbers that lost their leading zeros, and CPFs with wrong check digits
* names in upper case with extra spaces, broken accents (Windows-1252 read as UTF-8)
* birth dates in two text formats, or impossible dates
* accounts pointing to customers that do not exist, transactions pointing to missing accounts
* transactions with zero or negative amounts, or dated in the future
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, select, text, update

from migration.config import get_settings
from migration.legacy.schema import accounts, customers, metadata, transactions
from migration.rules import cpf_is_valid

FIRST = (
    "Ana Bruno Carla Daniel Eduarda Felipe Gabriela Hugo Isabela João "
    "Larissa Marcos Natália Otávio Paula Rafael Sofia Tiago Vitória William"
).split()
LAST = (
    "Silva Santos Oliveira Souza Lima Pereira Costa Rodrigues Almeida Nascimento Araújo Ferreira Carvalho Gomes Ribeiro Martins"
).split()
HISTORY = ["PIX RECEBIDO", "PIX ENVIADO", "TRANSFERÊNCIA", "PAGAMENTO BOLETO", "SAQUE", "DEPÓSITO", "TARIFA", "COMPRA DÉBITO"]


def legacy_now() -> datetime:
    """Current time as the legacy system records it: local time of the bank, without offset.

    Using the server clock instead would put rows hours in the future on machines running in UTC.
    """
    return datetime.now(ZoneInfo(get_settings().legacy_timezone)).replace(tzinfo=None, microsecond=0)


def make_cpf(rng: random.Random) -> str:
    """Random CPF with valid check digits."""
    base = [rng.randint(0, 9) for _ in range(9)]
    for size in (9, 10):
        total = sum(d * w for d, w in zip(base, range(size + 1, 1, -1), strict=False))
        base.append((total * 10) % 11 % 10)
    return "".join(map(str, base))


def mojibake(text_: str) -> str:
    """How a UTF-8 text looks when read as Windows-1252 (e.g. 'TRANSFERÃŠNCIA')."""
    return text_.encode("utf-8").decode("cp1252", errors="replace")


def generate(scale: float = 1.0, seed: int = 42, now: datetime | None = None) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    now = (now or legacy_now()).replace(microsecond=0)
    n_customers = max(50, int(5_000 * scale))

    def changed_at() -> datetime:
        return now - timedelta(days=rng.randint(2, 700), seconds=rng.randint(0, 86_399))

    # 1. Customers, with duplicates and typing defects
    cust_rows: list[dict] = []
    for cid in range(1, n_customers + 1):
        cpf = make_cpf(rng)
        roll = rng.random()
        if roll < 0.005:
            shown_cpf = cpf[:9] + str((int(cpf[9]) + 1) % 10) + cpf[10]  # wrong check digit
        elif roll < 0.10 and cpf.startswith("0"):
            shown_cpf = str(int(cpf))  # stored as a number: leading zeros lost
        elif roll < 0.55:
            shown_cpf = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
        else:
            shown_cpf = cpf
        name = f"{rng.choice(FIRST)} {rng.choice(['da', 'de', 'dos', ''])} {rng.choice(LAST)}".replace("  ", " ")
        if rng.random() < 0.3:
            name = f"  {name.upper()}   "
        if rng.random() < 0.05:
            name = mojibake(name)
        birth = now.date() - timedelta(days=rng.randint(18 * 365, 85 * 365))
        birth_txt = birth.strftime("%d/%m/%Y") if rng.random() < 0.6 else birth.isoformat()
        if rng.random() < 0.01:
            birth_txt = "00/00/0000"
        email = f"{name.split()[0].lower()}.{cid}@example.com"
        cust_rows.append(
            {
                "CD_CLIENTE": cid,
                "NM_CLIENTE": name,
                "NR_CPF": shown_cpf,
                "DS_EMAIL": email.upper() if rng.random() < 0.2 else ("" if rng.random() < 0.05 else email),
                "DT_NASCIMENTO": birth_txt,
                "CD_SITUACAO": rng.choices("AIB", weights=[90, 8, 2])[0],
                "DT_ULTIMA_ALTERACAO": changed_at(),
            }
        )
    # Same person registered twice (about 2%): other format, older record, other e-mail
    next_id = n_customers + 1
    for original in rng.sample(cust_rows, k=int(n_customers * 0.02)):
        digits = "".join(ch for ch in original["NR_CPF"] if ch.isdigit()).zfill(11)
        dup = dict(original)
        dup.update(
            CD_CLIENTE=next_id,
            NR_CPF=f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}",
            DS_EMAIL=f"old.{next_id}@example.com",
            DT_ULTIMA_ALTERACAO=original["DT_ULTIMA_ALTERACAO"] - timedelta(days=rng.randint(30, 400)),
        )
        cust_rows.append(dup)
        next_id += 1

    # 2. Accounts: 1 to 3 per customer, a few orphans
    acct_rows: list[dict] = []
    acct_id = 10_001
    for cust in cust_rows:
        for _ in range(rng.choices([1, 2, 3], weights=[60, 30, 10])[0]):
            owner = cust["CD_CLIENTE"] if rng.random() > 0.003 else 9_000_000 + acct_id  # orphan
            number = f"{rng.randint(10_000, 99_999)}"
            acct_rows.append(
                {
                    "CD_CONTA": acct_id,
                    "CD_CLIENTE": owner,
                    "NR_AGENCIA": str(rng.choice([1, 12, 345, 1234])),
                    "NR_CONTA": f"{number}-{rng.randint(0, 9)}" if rng.random() < 0.7 else f"{number}{rng.randint(0, 9)}",
                    "CD_TIPO": rng.choices(["CC", "PP"], weights=[75, 25])[0],
                    "DT_ABERTURA": now - timedelta(days=rng.randint(30, 3_000)),
                    "CD_SITUACAO": rng.choices("AE", weights=[92, 8])[0],
                    "DT_ULTIMA_ALTERACAO": changed_at(),
                }
            )
            acct_id += 1

    # 3. Transactions over the last 12 months, with a few invalid ones
    txn_rows: list[dict] = []
    txn_id = 1_000_001
    for acct in acct_rows:
        for _ in range(rng.randint(0, 12)):
            roll = rng.random()
            amount = Decimal(rng.randint(100, 500_000)) / 100
            posted = now - timedelta(days=rng.randint(1, 365), seconds=rng.randint(0, 86_399))
            account_ref = acct["CD_CONTA"]
            if roll < 0.002:
                amount = Decimal("0.00")
            elif roll < 0.003:
                amount = -amount
            elif roll < 0.004:
                posted = now + timedelta(days=rng.randint(10, 60))
            elif roll < 0.005:
                account_ref = 8_000_000 + txn_id  # orphan
            history = rng.choice(HISTORY)
            txn_rows.append(
                {
                    "CD_LANCAMENTO": txn_id,
                    "CD_CONTA": account_ref,
                    "VL_LANCAMENTO": amount,
                    "TP_LANCAMENTO": rng.choices("CD", weights=[55, 45])[0],
                    "DT_LANCAMENTO": posted,
                    "DS_HISTORICO": mojibake(history) if rng.random() < 0.1 else history,
                    "DT_ULTIMA_ALTERACAO": min(posted, now - timedelta(days=1)),
                }
            )
            txn_id += 1
    return {"TB_CLIENTE": cust_rows, "TB_CONTA": acct_rows, "TB_LANCAMENTO": txn_rows}


def load(engine: Engine, rows: dict[str, list[dict]], batch: int = 2_000) -> dict[str, int]:
    """Recreate the legacy tables and insert the generated rows."""
    metadata.drop_all(engine)
    metadata.create_all(engine)
    counts = {}
    with engine.begin() as conn:
        for table in (customers, accounts, transactions):
            data = rows[table.name]
            for start in range(0, len(data), batch):
                conn.execute(table.insert(), data[start : start + batch])
            counts[table.name] = len(data)
    return counts


def apply_changes(engine: Engine, now: datetime | None = None, seed: int = 7, fix_cpfs: bool = True) -> dict[str, int]:
    """Day-to-day activity in the legacy system after the initial load, for the incremental run.

    * customers update their e-mail
    * the branch fixes customers whose CPF was typed wrong (they must now be migrated)
    * new customers open accounts and make transactions
    * a transaction amount is corrected and an account is closed
    """
    rng = random.Random(seed)
    now = (now or legacy_now()).replace(microsecond=0)
    changes = {"emails_updated": 0, "cpfs_fixed": 0, "new_customers": 0, "new_transactions": 0}
    with engine.begin() as conn:
        ids = [r[0] for r in conn.execute(select(customers.c.CD_CLIENTE).order_by(customers.c.CD_CLIENTE))]
        for cid in rng.sample(ids, k=min(25, len(ids))):
            conn.execute(
                update(customers)
                .where(customers.c.CD_CLIENTE == cid)
                .values(DS_EMAIL=f"new.{cid}@example.com", DT_ULTIMA_ALTERACAO=now)
            )
            changes["emails_updated"] += 1

        for cid, raw in conn.execute(select(customers.c.CD_CLIENTE, customers.c.NR_CPF)).all() if fix_cpfs else []:
            digits = "".join(ch for ch in raw or "" if ch.isdigit()).zfill(11)
            if not cpf_is_valid(digits):
                fixed = make_cpf(random.Random(cid))
                conn.execute(update(customers).where(customers.c.CD_CLIENTE == cid).values(NR_CPF=fixed, DT_ULTIMA_ALTERACAO=now))
                changes["cpfs_fixed"] += 1

        max_c = conn.execute(select(func.max(customers.c.CD_CLIENTE))).scalar_one()
        max_a = conn.execute(select(func.max(accounts.c.CD_CONTA))).scalar_one()
        max_t = conn.execute(select(func.max(transactions.c.CD_LANCAMENTO))).scalar_one()
        for i in range(1, 11):
            cid, aid = max_c + i, max_a + i
            conn.execute(
                customers.insert(),
                {
                    "CD_CLIENTE": cid,
                    "NM_CLIENTE": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                    "NR_CPF": make_cpf(rng),
                    "DS_EMAIL": f"new.customer.{cid}@example.com",
                    "DT_NASCIMENTO": "15/03/1990",
                    "CD_SITUACAO": "A",
                    "DT_ULTIMA_ALTERACAO": now,
                },
            )
            conn.execute(
                accounts.insert(),
                {
                    "CD_CONTA": aid,
                    "CD_CLIENTE": cid,
                    "NR_AGENCIA": "1",
                    "NR_CONTA": f"{rng.randint(10_000, 99_999)}-{rng.randint(0, 9)}",
                    "CD_TIPO": "CC",
                    "DT_ABERTURA": now,
                    "CD_SITUACAO": "A",
                    "DT_ULTIMA_ALTERACAO": now,
                },
            )
            for j in range(1, 4):
                max_t += 1
                conn.execute(
                    transactions.insert(),
                    {
                        "CD_LANCAMENTO": max_t,
                        "CD_CONTA": aid,
                        "VL_LANCAMENTO": Decimal(rng.randint(1_000, 90_000)) / 100,
                        "TP_LANCAMENTO": "C" if j == 1 else "D",
                        "DT_LANCAMENTO": now - timedelta(minutes=10 * j),
                        "DS_HISTORICO": "PIX RECEBIDO" if j == 1 else "COMPRA DÉBITO",
                        "DT_ULTIMA_ALTERACAO": now,
                    },
                )
                changes["new_transactions"] += 1
            changes["new_customers"] += 1

        # A transaction amount corrected by the back office, and an account closed
        first_valid = conn.execute(
            select(transactions.c.CD_LANCAMENTO)
            .where(transactions.c.VL_LANCAMENTO > 0)
            .order_by(transactions.c.CD_LANCAMENTO)
            .limit(1)
        ).scalar_one()
        conn.execute(
            update(transactions)
            .where(transactions.c.CD_LANCAMENTO == first_valid)
            .values(VL_LANCAMENTO=transactions.c.VL_LANCAMENTO + Decimal("10.00"), DT_ULTIMA_ALTERACAO=now)
        )
        conn.execute(update(accounts).where(accounts.c.CD_CONTA == max_a).values(CD_SITUACAO="E", DT_ULTIMA_ALTERACAO=now))
    return changes


def fix_some_defects(engine: Engine, share: float, now: datetime | None = None, seed: int = 11) -> dict[str, int]:
    """The business works the rejected list: each day a share of each kind of defect is fixed at the source.

    * wrong CPF typed again from the customer's document
    * zero or negative amounts corrected from the bank statement
    * transactions dated in the future moved to the right date
    * accounts and transactions pointing to records that do not exist re-linked by the back office
    """
    rng = random.Random(seed)
    now = (now or legacy_now()).replace(microsecond=0)
    fixed = {"cpf": 0, "amount": 0, "future_date": 0, "orphan_account": 0, "orphan_transaction": 0}

    def pick(items: list) -> list:
        return rng.sample(items, k=round(len(items) * share)) if items else []

    with engine.begin() as conn:
        bad_cpf = [
            cid
            for cid, raw in conn.execute(select(customers.c.CD_CLIENTE, customers.c.NR_CPF))
            if not cpf_is_valid("".join(ch for ch in raw or "" if ch.isdigit()).zfill(11))
        ]
        for cid in pick(bad_cpf):
            conn.execute(
                update(customers)
                .where(customers.c.CD_CLIENTE == cid)
                .values(NR_CPF=make_cpf(random.Random(cid)), DT_ULTIMA_ALTERACAO=now)
            )
            fixed["cpf"] += 1

        bad_amount = [r[0] for r in conn.execute(select(transactions.c.CD_LANCAMENTO).where(transactions.c.VL_LANCAMENTO <= 0))]
        for tid in pick(bad_amount):
            conn.execute(
                update(transactions)
                .where(transactions.c.CD_LANCAMENTO == tid)
                .values(VL_LANCAMENTO=Decimal(rng.randint(500, 50_000)) / 100, DT_ULTIMA_ALTERACAO=now)
            )
            fixed["amount"] += 1

        future = [r[0] for r in conn.execute(select(transactions.c.CD_LANCAMENTO).where(transactions.c.DT_LANCAMENTO > now))]
        for tid in pick(future):
            conn.execute(
                update(transactions)
                .where(transactions.c.CD_LANCAMENTO == tid)
                .values(DT_LANCAMENTO=now - timedelta(days=rng.randint(1, 30)), DT_ULTIMA_ALTERACAO=now)
            )
            fixed["future_date"] += 1

        customer_ids = [r[0] for r in conn.execute(select(customers.c.CD_CLIENTE))]
        known_customers = set(customer_ids)
        orphan_accounts = [
            aid for aid, owner in conn.execute(select(accounts.c.CD_CONTA, accounts.c.CD_CLIENTE)) if owner not in known_customers
        ]
        for aid in pick(orphan_accounts):
            conn.execute(
                update(accounts)
                .where(accounts.c.CD_CONTA == aid)
                .values(CD_CLIENTE=rng.choice(customer_ids), DT_ULTIMA_ALTERACAO=now)
            )
            fixed["orphan_account"] += 1

        account_ids = [r[0] for r in conn.execute(select(accounts.c.CD_CONTA))]
        known_accounts = set(account_ids)
        txn_accounts = conn.execute(select(transactions.c.CD_LANCAMENTO, transactions.c.CD_CONTA))
        orphan_txn = [tid for tid, acc in txn_accounts if acc not in known_accounts]
        for tid in pick(orphan_txn):
            conn.execute(
                update(transactions)
                .where(transactions.c.CD_LANCAMENTO == tid)
                .values(CD_CONTA=rng.choice(account_ids), DT_ULTIMA_ALTERACAO=now)
            )
            fixed["orphan_transaction"] += 1
    return fixed


def create_database_if_missing(server_url: str, name: str) -> None:
    """Create the legacy database on SQL Server (CI starts with an empty server)."""
    from sqlalchemy import create_engine

    engine = create_engine(server_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f"IF DB_ID('{name}') IS NULL CREATE DATABASE [{name}]"))
    engine.dispose()
