"""Recorder duradero y journal de reanudación.

Se escribe una única línea JSON por intento, con ``flush`` y ``fsync`` antes de
continuar. El journal de estado se guarda de forma atómica para que una caída
entre preparación y respuesta no pierda la evidencia del intento.

Ninguna representación incluye el valor de la credencial.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from .models import (
    AttemptResult,
    ExperimentRecord,
    RequestSpec,
    KIND_RECOVERY,
    desired_kind,
    parse_semantic,
)


class PersistenceError(Exception):
    """La evidencia no puede garantizarse; se detienen nuevos envíos."""


class FileLock:
    """Bloqueo de proceso cooperativo sobre un archivo dedicado."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+", encoding="utf-8")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._fh.close()
            self._fh = None
            raise PersistenceError(
                f"otra ejecución mantiene el bloqueo {self.path.name}"
            ) from exc

    def release(self) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class ExperimentRecorder:
    """Append-only de evidencia con ids monotónicos."""

    def __init__(self, log_path: str | os.PathLike):
        self.log_path = Path(log_path)
        self._next_id = 1
        self._load_existing()

    def _load_existing(self) -> None:
        if not self.log_path.exists():
            return
        max_id = 0
        with open(self.log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("id"), int):
                    max_id = max(max_id, obj["id"])
        self._next_id = max_id + 1

    @property
    def next_id(self) -> int:
        return self._next_id

    def read_all(self) -> list:
        """Devuelve todas las líneas de evidencia; nunca lanza por una línea suelta."""

        records = []
        if not self.log_path.exists():
            return records
        with open(self.log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def case_ids_done(self) -> set:
        """Case_ids ya registrados (terminales): no se reenvían en reanudación."""

        return {
            record.get("case_id")
            for record in self.read_all()
            if record.get("case_id")
        }

    def _append_line(self, record: dict) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise PersistenceError(
                f"no se pudo persistir la evidencia en {self.log_path.name}"
            ) from exc

    def record(
        self,
        spec: RequestSpec,
        result: AttemptResult,
        *,
        body_text: Optional[str],
        observed_at: str,
        seq: str,
        attempt_of: Optional[str] = None,
        retry_index: int = 0,
        kind: Optional[str] = None,
        note: Optional[str] = None,
    ) -> dict:
        """Agrega una línea de evidencia fiel para un intento enviado."""

        record = ExperimentRecord(
            id=self._next_id,
            attempt_id=result.attempt_id,
            case_id=spec.case_id,
            seq=seq,
            x_req=result.x_req,
            hipotesis=spec.hypothesis,
            request=parse_semantic(spec.content_type, body_text),
            status=result.status,
            response=parse_semantic(None, result.response_text),
            conclusion=None,
            observed_at=observed_at,
            axis=spec.axis,
            kind=kind or desired_kind(spec.kind, retry_index),
            attempt_of=attempt_of,
            retry_index=retry_index,
            infra=result.infra,
            metodo=spec.method,
            ruta=spec.path,
            tipo_contenido=spec.content_type,
            auth=spec.auth_mode,
            request_raw=body_text,
            response_raw=result.response_text,
            infra_header=result.infra_header,
            nota=note,
        ).to_dict()
        self._append_line(record)
        self._next_id += 1
        return record

    def recover_pending(self, pending: dict, *, observed_at: str) -> Optional[dict]:
        """Convierte un intento huérfano en evidencia de resultado desconocido.

        Nunca reenvía la solicitud: solo deja constancia de que se preparó sin
        resultado conocido.
        """

        if not pending:
            return None
        record = {
            "id": self._next_id,
            "attempt_id": pending.get("attempt_id"),
            "case_id": pending.get("case_id"),
            "seq": pending.get("seq"),
            "x_req": None,
            "hipotesis": pending.get("hipotesis"),
            "request": pending.get("request"),
            "status": None,
            "response": None,
            "conclusion": None,
            "observed_at": observed_at,
            "axis": pending.get("axis"),
            "kind": KIND_RECOVERY,
            "attempt_of": pending.get("attempt_of"),
            "retry_index": pending.get("retry_index", 0),
            "infra": False,
            "metodo": pending.get("metodo"),
            "ruta": pending.get("ruta"),
            "tipo_contenido": pending.get("tipo_contenido"),
            "auth": pending.get("auth"),
            "request_raw": pending.get("request_raw"),
            "response_raw": None,
            "infra_header": None,
            "nota": "resultado_desconocido",
        }
        self._append_line(record)
        self._next_id += 1
        return record


class RunStateStore:
    """Journal de estado atómico y reanudable."""

    def __init__(self, state_path: str | os.PathLike):
        self.state_path = Path(state_path)

    def load(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            text = self.state_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PersistenceError(
                f"estado ilegible en {self.state_path.name}"
            ) from exc
        # El preflight crea el journal vacío antes de la primera corrida; un
        # archivo vacío o solo con espacios equivale a un estado inexistente.
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise PersistenceError(
                f"estado ilegible en {self.state_path.name}"
            ) from exc

    def save(self, state: dict) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.state_path.parent), prefix=".probe-state-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(state, fh, ensure_ascii=False)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.state_path)
                _fsync_dir(self.state_path.parent)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as exc:
            raise PersistenceError(
                f"no se pudo persistir el estado en {self.state_path.name}"
            ) from exc
