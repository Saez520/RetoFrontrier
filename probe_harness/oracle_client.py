"""Cliente HTTP reutilizable del servicio original.

El cliente no conoce ejes ni inventario: recibe un ``RequestSpec`` y el cuerpo ya
resuelto, aplica ritmo, presupuesto, cierre y reintentos finitos ante
infraestructura, y devuelve el resultado observable de cada intento. El
transporte y el reloj se inyectan, por lo que las pruebas nunca tocan la red.
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

from .models import (
    AUTH_INVALID,
    AUTH_MISSING,
    AUTH_VALID,
    AttemptResult,
    RequestSpec,
    StopReason,
)
from .settings import (
    CALLS_PER_SECOND,
    CUTOFF_AT,
    INVALID_TOKEN_LITERAL,
    MAX_CALLS,
    MIN_INTERVAL_SECONDS,
    ORACLE_BASE_URL,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_WAITS,
)


class TransportError(Exception):
    """Fallo de transporte: no hubo respuesta del servicio."""


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: dict
    body: bytes


class Transport(Protocol):
    def __call__(
        self, method: str, url: str, headers: dict, body: Optional[bytes], timeout: float
    ) -> TransportResponse: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def now_utc(self) -> datetime: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)


class StopRequested(Exception):
    """Detención de la cola por presupuesto agotado o cierre alcanzado."""

    def __init__(self, reason: StopReason):
        super().__init__(reason.value)
        self.reason = reason


class UrllibTransport:
    """Transporte real basado en la biblioteca estándar."""

    def __call__(
        self, method: str, url: str, headers: dict, body: Optional[bytes], timeout: float
    ) -> TransportResponse:
        request = urllib.request.Request(url, data=body, method=method)
        for key, value in headers.items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
                return TransportResponse(resp.status, dict(resp.headers), resp.read())
        except urllib.error.HTTPError as exc:
            return TransportResponse(exc.code, dict(exc.headers), exc.read())
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            raise TransportError(str(exc)) from exc


@dataclass(frozen=True)
class AttemptMeta:
    """Contexto de un intento individual antes de enviarse."""

    spec: RequestSpec
    attempt_id: str
    retry_index: int
    attempt_of: Optional[str]
    seq: str
    body_text: Optional[str]


class SendHooks(Protocol):
    def before_send(self, meta: AttemptMeta) -> None: ...

    def after_send(self, result: AttemptResult, meta: AttemptMeta) -> None: ...


def _decode_body(body: str | bytes) -> str:
    if isinstance(body, bytes):
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body.decode("latin-1")
    return body


def default_id_factory() -> str:
    return uuid.uuid4().hex


class OracleClient:
    """Cliente con ritmo serial, presupuesto global y reintentos finitos."""

    def __init__(
        self,
        transport: Transport,
        clock: Optional[Clock] = None,
        sleeper: Optional[Callable[[float], None]] = None,
        *,
        base_url: str = ORACLE_BASE_URL,
        token: Optional[str] = None,
        max_calls: int = MAX_CALLS,
        min_interval: float = MIN_INTERVAL_SECONDS,
        cutoff: datetime = CUTOFF_AT,
        retry_waits: tuple = RETRY_WAITS,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        id_factory: Optional[Callable[[], str]] = None,
    ):
        self.transport = transport
        self.clock = clock or SystemClock()
        self.sleeper = sleeper or time.sleep
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.max_calls = max_calls
        self.min_interval = min_interval
        self.cutoff = cutoff
        self.retry_waits = tuple(retry_waits)
        self.timeout = timeout
        self._id_factory = id_factory or default_id_factory
        self.calls_made = 0
        self._last_send: Optional[float] = None

    # -- presupuesto, cierre y ritmo -------------------------------------

    def _reserve(self) -> None:
        if self.calls_made >= self.max_calls:
            raise StopRequested(StopReason.BUDGET)
        if self.clock.now_utc() >= self.cutoff:
            raise StopRequested(StopReason.CUTOFF)
        self.calls_made += 1

    def _pace(self) -> None:
        now = self.clock.monotonic()
        if self._last_send is not None:
            wait = self.min_interval - (now - self._last_send)
            if wait > 0:
                self.sleeper(wait)
                now = self.clock.monotonic()
        self._last_send = now

    # -- cabeceras -------------------------------------------------------

    def _headers(self, spec: RequestSpec) -> dict:
        headers: dict = {}
        if spec.content_type is not None:
            headers["Content-Type"] = spec.content_type
        if spec.auth_mode == AUTH_VALID:
            if self.token is None:
                raise ValueError("token requerido para autenticación válida")
            headers["Authorization"] = f"Bearer {self.token}"
        elif spec.auth_mode == AUTH_INVALID:
            headers["Authorization"] = INVALID_TOKEN_LITERAL
        elif spec.auth_mode == AUTH_MISSING:
            pass
        else:
            raise ValueError(f"modalidad de auth desconocida: {spec.auth_mode!r}")
        return headers

    def _url(self, spec: RequestSpec) -> str:
        return f"{self.base_url}{spec.path}"

    # -- envío -----------------------------------------------------------

    def _attempt(
        self, spec: RequestSpec, body_text: Optional[str], attempt_id: str
    ) -> AttemptResult:
        headers = self._headers(spec)
        body_bytes = body_text.encode("utf-8") if body_text is not None else None
        response = self.transport(
            spec.method, self._url(spec), headers, body_bytes, self.timeout
        )
        lower = {str(k).lower(): v for k, v in response.headers.items()}
        infra_header = lower.get("x-frontier-infra")
        x_req = lower.get("x-req")
        return AttemptResult(
            case_id=spec.case_id,
            attempt_id=attempt_id,
            status=response.status,
            x_req=None if x_req is None else str(x_req),
            response_text=_decode_body(response.body),
            infra=infra_header is not None,
            infra_header=None if infra_header is None else str(infra_header),
            error=None,
            auth_mode=spec.auth_mode,
        )

    def send(
        self,
        spec: RequestSpec,
        body_text: Optional[str],
        *,
        seq: str,
        hooks: Optional[SendHooks] = None,
    ) -> list:
        """Envía una solicitud y sus reintentos finitos ante infraestructura."""

        results = []
        first_id: Optional[str] = None
        retry_index = 0
        while True:
            if retry_index > 0:
                self.sleeper(self.retry_waits[retry_index - 1])
            self._reserve()
            self._pace()
            attempt_id = self._id_factory()
            if first_id is None:
                first_id = attempt_id
            meta = AttemptMeta(
                spec=spec,
                attempt_id=attempt_id,
                retry_index=retry_index,
                attempt_of=None if retry_index == 0 else first_id,
                seq=seq,
                body_text=body_text,
            )
            if hooks is not None:
                hooks.before_send(meta)
            try:
                result = self._attempt(spec, body_text, attempt_id)
            except TransportError as exc:
                result = AttemptResult(
                    case_id=spec.case_id,
                    attempt_id=attempt_id,
                    status=None,
                    x_req=None,
                    response_text=None,
                    infra=False,
                    infra_header=None,
                    error=str(exc),
                    auth_mode=spec.auth_mode,
                )
            results.append(result)
            if hooks is not None:
                hooks.after_send(result, meta)
            if result.infra and retry_index < len(self.retry_waits):
                retry_index += 1
                continue
            break
        return results
