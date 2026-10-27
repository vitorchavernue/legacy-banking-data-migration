from datetime import date
from decimal import Decimal

import pytest

from migration import rules
from migration.legacy.seed import make_cpf, mojibake
from migration.rules import RuleError


@pytest.mark.parametrize("raw", ["529.982.247-25", "52998224725", " 529 982 247 25 "])
def test_cpf_accepts_any_punctuation(raw):
    assert rules.normalize_cpf(raw) == "52998224725"


def test_cpf_stored_as_number_gets_its_leading_zeros_back():
    assert rules.normalize_cpf("1234567890") == "01234567890"


@pytest.mark.parametrize(
    "raw, reason",
    [("529.982.247-26", "check digits"), ("111.111.111-11", "check digits"), ("", "missing"), ("123456789012", "digits")],
)
def test_invalid_cpf_is_rejected_with_a_reason(raw, reason):
    with pytest.raises(RuleError, match=reason):
        rules.normalize_cpf(raw)


def test_generated_cpfs_are_valid():
    import random

    rng = random.Random(1)
    assert all(rules.cpf_is_valid(make_cpf(rng)) for _ in range(500))


def test_name_is_trimmed_and_title_cased_with_lowercase_particles():
    assert rules.normalize_name("  MARIA   DA  SILVA ") == "Maria da Silva"
    assert rules.normalize_name("da costa") == "Da Costa"  # a particle at the start stays capitalized


def test_broken_accents_are_repaired():
    assert rules.fix_encoding(mojibake("TRANSFERÊNCIA")) == "TRANSFERÊNCIA"
    assert rules.normalize_name(mojibake("JOÃO ARAÚJO")) == "João Araújo"
    assert rules.fix_encoding("PIX RECEBIDO") == "PIX RECEBIDO"


def test_email_is_lowercased_and_invalid_becomes_empty():
    assert rules.normalize_email(" ANA@EXAMPLE.COM ") == "ana@example.com"
    assert rules.normalize_email("not-an-email") is None
    assert rules.normalize_email("") is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("15/03/1990", date(1990, 3, 15)),
        ("1990-03-15", date(1990, 3, 15)),
        ("00/00/0000", None),
        ("", None),
        ("31/12/2999", None),
    ],
)
def test_birth_date_formats(raw, expected):
    assert rules.parse_birth_date(raw) == expected


def test_branch_is_zero_padded_and_account_number_split():
    assert rules.normalize_branch("12") == "0012"
    assert rules.split_account_number("12345-6") == ("12345", "6")
    assert rules.split_account_number("123456") == ("12345", "6")
    with pytest.raises(RuleError):
        rules.split_account_number("ABC")


def test_amount_gets_the_sign_of_the_direction():
    assert rules.signed_amount(Decimal("10.5"), "C") == (Decimal("10.50"), "credit")
    assert rules.signed_amount(Decimal("10.5"), "d") == (Decimal("-10.50"), "debit")
    for value in (Decimal("0"), Decimal("-3")):
        with pytest.raises(RuleError, match="greater than zero"):
            rules.signed_amount(value, "C")
    with pytest.raises(RuleError, match="transaction type"):
        rules.signed_amount(Decimal("1"), "X")


def test_unknown_codes_are_rejected():
    assert rules.map_code("a", rules.CUSTOMER_STATUS, "customer status") == "active"
    with pytest.raises(RuleError, match="unknown customer status"):
        rules.map_code("Z", rules.CUSTOMER_STATUS, "customer status")
