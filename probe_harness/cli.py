"""Driver de línea de comandos del sondeo autónomo.

Valida configuración y persistencia antes de la primera solicitud y delega la
ejecución en ``ProbeRunner``. No contiene reglas HTTP, inventario ni solver, y
no expone ninguna opción de controles humanos.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .control_solver import load_examples
from .inventory import Inventory
from .oracle_client import OracleClient, SystemClock, UrllibTransport
from .recorder import ExperimentRecorder, PersistenceError, RunStateStore
from .runner import ProbeRunner
from .settings import (
    CUTOFF_AT,
    DEFAULT_LOG_PATH,
    DEFAULT_SEED,
    DEFAULT_STATE_PATH,
    EXAMPLES_PATH,
    ORACLE_BASE_URL,
    ConfigError,
    load_token,
)

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_PERSISTENCE = 2
EXIT_CUTOFF = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="probe_oracle",
        description="Ejecuta el sondeo del servicio original de forma autónoma.",
    )
    parser.add_argument("--log-path", default=DEFAULT_LOG_PATH)
    parser.add_argument("--state-path", default=DEFAULT_STATE_PATH)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--base-url", default=ORACLE_BASE_URL)
    return parser


def _check_writable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with open(path, "a", encoding="utf-8"):
            pass
        return
    with open(path, "a", encoding="utf-8"):
        pass


def _preflight(log_path: Path, state_path: Path) -> None:
    try:
        _check_writable(log_path)
        _check_writable(state_path)
    except OSError as exc:
        raise PersistenceError("persistence_preflight_failure") from exc


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        token = load_token()
    except ConfigError as exc:
        print(f"configuración inválida: {exc}", flush=True)
        return EXIT_CONFIG

    log_path = Path(args.log_path)
    state_path = Path(args.state_path)
    try:
        _preflight(log_path, state_path)
    except PersistenceError as exc:
        print(f"persistence_preflight_failure: {exc}", flush=True)
        return EXIT_PERSISTENCE

    examples_path = Path(EXAMPLES_PATH)
    try:
        examples = load_examples(examples_path)
    except OSError:
        print(f"no se pudo leer {examples_path}", flush=True)
        return EXIT_CONFIG

    clock = SystemClock()
    if clock.now_utc() >= CUTOFF_AT:
        print("cierre alcanzado: no se inicia ninguna llamada", flush=True)
        return EXIT_CUTOFF

    client = OracleClient(UrllibTransport(), clock, token=token, base_url=args.base_url)
    recorder = ExperimentRecorder(log_path)
    state_store = RunStateStore(state_path)
    inventory = Inventory(seed=args.seed)
    runner = ProbeRunner(
        client=client,
        recorder=recorder,
        inventory=inventory,
        examples=examples,
        state_store=state_store,
        clock=clock,
    )
    summary = runner.run()
    if summary.get("stop_reason") == "persistence_failure":
        return EXIT_PERSISTENCE
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
