"""Función de control del reemplazo (ISO 7064 MOD 97-10).

``S(base)`` concatena cada letra por su posición 1..26 (sin distinguir
mayúsculas), cada dígito tal cual y omite cualquier otro carácter. El control
canónico es ``f(base) = 98 - (N*100 % 97)`` (rango 2..98, sin reducción final
mod 97) y la aceptación es por igualdad exacta ``int(control) == f(base)``.

La congruencia ``(N*100 + control) % 97 == 1`` no describe al original: en los
bordes ``N*100 % 97 == 0`` (f=98) y ``== 1`` (f=97) aceptaría 1 y 0, que el
servicio rechaza con ``E202``.

Sin dependencias externas.
"""

from __future__ import annotations

_MODULUS = 97


def _encode_base(base: str) -> str:
    parts = []
    for char in base:
        if "0" <= char <= "9":
            parts.append(char)
        elif "A" <= char <= "Z":
            parts.append(str(ord(char) - ord("A") + 1))
        elif "a" <= char <= "z":
            parts.append(str(ord(char) - ord("a") + 1))
    return "".join(parts)


def _base_number(base: str) -> int:
    encoded = _encode_base(base)
    return int(encoded) if encoded else 0


def control_for(base: str) -> int:
    """Control canónico ``f(base) = 98 - (N*100 % 97)`` (rango 2..98)."""

    number = _base_number(base)
    return 98 - (number * 100 % _MODULUS)


def is_numeric(control_str: str) -> bool:
    """``True`` si el control es una secuencia no vacía de dígitos ASCII."""

    return bool(control_str) and all("0" <= char <= "9" for char in control_str)


def is_valid(base: str, control_str: str) -> bool:
    """Aceptación exacta: control numérico igual a ``f(base)``."""

    if not is_numeric(control_str):
        return False
    return int(control_str) == control_for(base)
