"""Business rules that clean and validate legacy values, one function per field.

Each function returns the clean value, or raises ``RuleError`` with a reason that is stored
with the rejected record, so the business team knows exactly what to fix in the old system.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

CUSTOMER_STATUS = {"A": "active", "I": "inactive", "B": "blocked"}
ACCOUNT_STATUS = {"A": "active", "E": "closed"}
ACCOUNT_TYPE = {"CC": "checking", "PP": "savings"}
DIRECTION = {"C": "credit", "D": "debit"}

_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
_ACCOUNT_NUMBER = re.compile(r"^(\d{1,10})-?(\d|X)$")
# Lowercase particles inside Brazilian names ("Maria da Silva", not "Maria Da Silva")
_NAME_PARTICLES = {"da", "de", "do", "das", "dos", "e"}


class RuleError(ValueError):
    """A legacy value that cannot be migrated as is."""


# --- Customers ---------------------------------------------------------------------------


def normalize_cpf(raw: str | None) -> str:
    """CPF as 11 digits. Accepts punctuation and numbers that lost their leading zeros."""
    if raw is None or not str(raw).strip():
        raise RuleError("CPF is missing")
    digits = re.sub(r"\D", "", str(raw))
    if not 1 <= len(digits) <= 11:
        raise RuleError(f"CPF has {len(digits)} digits")
    digits = digits.zfill(11)
    if not cpf_is_valid(digits):
        raise RuleError("CPF check digits are invalid")
    return digits


def cpf_is_valid(digits: str) -> bool:
    """Official CPF check-digit algorithm (two mod-11 digits). Repeated digits are invalid."""
    if len(digits) != 11 or not digits.isdigit() or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1), strict=True))
        check = (total * 10) % 11 % 10
        if check != int(digits[size]):
            return False
    return True


def normalize_name(raw: str | None) -> str:
    """Trim, collapse spaces, fix broken accents and use name case."""
    name = " ".join(fix_encoding(raw or "").split())
    if len(name) < 3:
        raise RuleError("name is missing or too short")
    words = name.lower().split(" ")
    return " ".join(w if i and w in _NAME_PARTICLES else w.capitalize() for i, w in enumerate(words))


def normalize_email(raw: str | None) -> str | None:
    """Lowercase e-mail, or None when empty or not a valid address (not a reason to reject)."""
    email = (raw or "").strip().lower()
    return email if _EMAIL.match(email) else None


def parse_birth_date(raw: str | None) -> date | None:
    """Birth date typed as dd/mm/yyyy or yyyy-mm-dd. Unknown dates become None."""
    text = (raw or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            value = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        return value if date(1900, 1, 1) <= value <= date.today() else None
    return None


def map_code(raw: str | None, mapping: dict[str, str], field: str) -> str:
    code = (raw or "").strip().upper()
    if code not in mapping:
        raise RuleError(f"unknown {field} code {raw!r}")
    return mapping[code]


# --- Accounts ----------------------------------------------------------------------------


def normalize_branch(raw: str | None) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not 1 <= len(digits) <= 4:
        raise RuleError(f"invalid branch {raw!r}")
    return digits.zfill(4)


def split_account_number(raw: str | None) -> tuple[str, str]:
    """'12345-6' or '123456' -> ('12345', '6')."""
    match = _ACCOUNT_NUMBER.match((raw or "").strip().upper())
    if not match:
        raise RuleError(f"invalid account number {raw!r}")
    return match.group(1), match.group(2)


# --- Transactions ------------------------------------------------------------------------


def signed_amount(value: Decimal | None, direction_code: str | None) -> tuple[Decimal, str]:
    """Legacy stores a positive amount plus C/D. Target stores the signed amount."""
    direction = map_code(direction_code, DIRECTION, "transaction type")
    if value is None:
        raise RuleError("amount is missing")
    amount = Decimal(value).quantize(Decimal("0.01"))
    if amount <= 0:
        raise RuleError("amount must be greater than zero")
    return (amount if direction == "credit" else -amount), direction


def fix_encoding(text: str) -> str:
    """Repair text saved as Windows-1252 and read as UTF-8 ('TRANSFERÃŠNCIA' -> 'TRANSFERÊNCIA')."""
    if not text or not any(ch in text for ch in "ÃÂ"):
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
