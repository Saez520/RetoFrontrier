"""Punto de integración del probe-harness.

Expone el cliente del original y el recorder reutilizables, más los tipos y el
orquestador. Un consumidor futuro puede importar ``OracleClient`` y
``ExperimentRecorder`` y añadir su propio cliente destino y comparación sin
duplicar transporte, ritmo ni captura.
"""

from .control_solver import apply_control_vector, load_examples, solve
from .inventory import Inventory, build_e7_replay
from .models import (
    AttemptResult,
    ControlProvenance,
    ExperimentRecord,
    ProbeSequence,
    RequestSpec,
    RunState,
    SequenceState,
    SolverResult,
    StopReason,
)
from .oracle_client import (
    AttemptMeta,
    OracleClient,
    StopRequested,
    SystemClock,
    TransportError,
    TransportResponse,
    UrllibTransport,
)
from .recorder import ExperimentRecorder, PersistenceError, RunStateStore
from .runner import ProbeRunner
from .settings import (
    CALLS_PER_SECOND,
    CUTOFF_AT,
    DEFAULT_LOG_PATH,
    DEFAULT_SEED,
    DEFAULT_STATE_PATH,
    MAX_CALLS,
    ORACLE_BASE_URL,
)

__all__ = [
    "AttemptMeta",
    "AttemptResult",
    "CALLS_PER_SECOND",
    "CUTOFF_AT",
    "ControlProvenance",
    "DEFAULT_LOG_PATH",
    "DEFAULT_SEED",
    "DEFAULT_STATE_PATH",
    "ExperimentRecord",
    "ExperimentRecorder",
    "Inventory",
    "MAX_CALLS",
    "ORACLE_BASE_URL",
    "OracleClient",
    "PersistenceError",
    "ProbeRunner",
    "ProbeSequence",
    "RequestSpec",
    "RunState",
    "RunStateStore",
    "SequenceState",
    "SolverResult",
    "StopReason",
    "StopRequested",
    "SystemClock",
    "TransportError",
    "TransportResponse",
    "UrllibTransport",
    "apply_control_vector",
    "build_e7_replay",
    "load_examples",
    "solve",
]
