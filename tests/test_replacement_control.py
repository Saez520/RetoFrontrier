"""Función de control del reemplazo: pares, bordes y aceptación exacta."""

import pytest

from replacement.control import control_for, is_numeric, is_valid

# Pares del catálogo más las dos bases de borde (r=0 → f=98; r=1 → f=97).
KNOWN_PAIRS = (
    ("ALTA;Lucia", 82),
    ("ALTA;Mateo", 3),
    ("CONSULTA;AC-0001", 14),
    ("CONSULTA;AC-0002", 11),
    ("CONSULTA;AC-0009", 87),
    ("DEPOSITO;AC-0001;250000", 86),
    ("DEPOSITO;AC-0002;700", 35),
    ("TRANSFER;AC-0001;AC-0002;40000", 86),
    ("TRANSFER;AC-0001;AC-0002;120000", 55),
    ("TRANSFER;AC-0001;AC-0002;100000", 12),
    ("TRANSFER;AC-0002;AC-0001;50000", 23),
    ("ANULA;OP-0003", 66),
    ("CONSULTA;AC-9964", 98),
    ("CONSULTA;AC-9932", 97),
)


@pytest.mark.parametrize("base,expected", KNOWN_PAIRS)
def test_control_for_known_pairs(base, expected):
    assert control_for(base) == expected


@pytest.mark.parametrize("base,expected", KNOWN_PAIRS)
def test_is_valid_accepts_canonical_control(base, expected):
    assert is_valid(base, str(expected)) is True


def test_is_valid_rejects_wrong_numeric():
    assert is_valid("ALTA;Lucia", "83") is False


def test_is_valid_rejects_non_numeric():
    assert is_valid("DEPOSITO;AC-0002;700", "5X") is False


def test_r0_border_rejects_mod97_twin():
    # r=0: f=98; el gemelo mod-97 (1) no es aceptado por el original.
    assert control_for("CONSULTA;AC-9964") == 98
    assert is_valid("CONSULTA;AC-9964", "98") is True
    assert is_valid("CONSULTA;AC-9964", "1") is False


def test_r1_border_rejects_mod97_twin():
    # r=1: f=97; el gemelo mod-97 (0) no es aceptado por el original.
    assert control_for("CONSULTA;AC-9932") == 97
    assert is_valid("CONSULTA;AC-9932", "97") is True
    assert is_valid("CONSULTA;AC-9932", "0") is False


def test_is_numeric_requires_ascii_digits():
    assert is_numeric("0") is True
    assert is_numeric("82") is True
    assert is_numeric("") is False
    assert is_numeric("5X") is False
    assert is_numeric(" 1") is False
