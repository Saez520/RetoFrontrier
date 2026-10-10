"""Estado temporal en memoria.

Esta fase no modela cuentas, saldos, operaciones ni identificadores. El
contenedor arranca vacío y ``reset`` restaura la condición inicial de forma
idempotente.
"""

from __future__ import annotations

from typing import Any


class TemporaryState:
    """Contenedor temporal vacío y reseteable."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def reset(self) -> None:
        """Restaura la condición inicial; idempotente."""
        self._data = {}

    def snapshot(self) -> dict[str, Any]:
        """Copia del estado actual (vacío en esta fase)."""
        return dict(self._data)
