"""Binding de identificadores por secuencia.

Durante una secuencia, los cuerpos pueden referirse a cuentas y operaciones por
su nombre de creación (``E4-A``, ``E5-09-B``, ``E8-A-01``) o por el índice de la
operación creada (``OP-0002``), pero el original exige los identificadores reales
devueltos por ALTA/DEPOSITO/TRANSFER (``AC-####``, ``OP-####``).

El binding observa cada respuesta de la secuencia, liga esos tokens a los IDs
reales y los sustituye en los cuerpos posteriores *antes* de calcular el control
(que se computa sobre el mensaje final). No inventa valores: un token no ligado
se envía tal cual y se anota.
"""

from __future__ import annotations

import re
from typing import Optional

# Tokens por índice de operación creada (``OP-000k`` → k-ésima operación).
OP_TOKEN = re.compile(r"OP-(\d{4})")

# Tokens de nombre de creación (``E4-A``, ``E5-09-A``, ``E8-B-03``). Se distinguen
# de los identificadores reales ``AC-####``/``OP-####`` porque empiezan con ``E``
# seguido de dígitos.
NAME_TOKEN = re.compile(r"E\d+-(?:[0-9A-Za-z]+)(?:-[0-9A-Za-z]+)*")


def _boundary_pattern(token: str) -> "re.Pattern[str]":
    return re.compile(
        r"(?<![0-9A-Za-z-])" + re.escape(token) + r"(?![0-9A-Za-z-])"
    )


class IdentifierBinding:
    """Mapa ``nombre→cuentaId`` y lista de operaciones de una secuencia."""

    def __init__(self) -> None:
        self._cuenta_ids: dict[str, str] = {}
        self._operaciones: list[str] = []

    def reset(self) -> None:
        """Reinicia el binding; idempotente."""
        self._cuenta_ids = {}
        self._operaciones = []

    def observe(self, message: Optional[str], response) -> None:
        """Actualiza el binding con el mensaje enviado y su respuesta.

        Un ``ALTA;<nombre>`` confirmado liga ``<nombre>`` a ``cuentaId``. Toda
        respuesta con ``operacionId`` agrega la operación al orden de creación.
        """

        if not isinstance(message, str) or not isinstance(response, dict):
            return
        fields = message.split(";")
        if fields and fields[0] == "ALTA" and len(fields) >= 2:
            cuenta_id = response.get("cuentaId")
            if isinstance(cuenta_id, str) and cuenta_id:
                self._cuenta_ids[fields[1]] = cuenta_id
        operacion_id = response.get("operacionId")
        if isinstance(operacion_id, str) and operacion_id:
            self._operaciones.append(operacion_id)

    def substitute(self, message: str) -> tuple[str, Optional[str]]:
        """Devuelve ``(mensaje_sustituido, nota)``.

        Sustituye nombres ligados y tokens ``OP-000k``. Un token no ligado se
        deja literal y se agrega a la nota; la nota es ``None`` si no quedaron
        tokens sin resolver.
        """

        fields = message.split(";")
        command = fields[0] if fields else ""
        unresolved: list[str] = []

        for name in sorted(self._cuenta_ids, key=len, reverse=True):
            message = _boundary_pattern(name).sub(self._cuenta_ids[name], message)

        def _replace_op(match: "re.Match[str]") -> str:
            index = int(match.group(1))
            if 1 <= index <= len(self._operaciones):
                return self._operaciones[index - 1]
            unresolved.append(match.group(0))
            return match.group(0)

        message = OP_TOKEN.sub(_replace_op, message)

        for token in NAME_TOKEN.findall(message):
            unresolved.append(token)
        if command == "ALTA" and len(fields) >= 2 and fields[1] in unresolved:
            # El primer argumento de ALTA es el nombre a crear, no un token a
            # resolver: su presencia sin ligar no es una anomalía.
            unresolved.remove(fields[1])

        note = None
        if unresolved:
            note = "token no ligado: " + ",".join(sorted(set(unresolved)))
        return message, note
