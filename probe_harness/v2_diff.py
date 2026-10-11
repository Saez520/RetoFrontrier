"""Replay diferencial del transcript de baseline contra el oráculo activo.

El baseline V1 (``experimentos.jsonl``, ids 1–924) se congela y se reproduce
request por request y en orden: método, ruta, cuerpo raw/ausente, content-type y
modalidad de auth. Cada respuesta observada se registra fielmente como una línea
nueva, ``append-only``, con ``case_id`` que apunta al baseline y firma V1
esperada en la nota. La comparación posterior aísla la primera divergencia de
cada tramo delimitado por un reset efectivo, sin contar cascadas de estado como
cambios independientes.

Este módulo no interpreta el reemplazo: solo captura y compara. Reutiliza
``OracleClient`` (ritmo, presupuesto, retries, corte) y ``ExperimentRecorder``
(ids monotónicos, schema de ``ExperimentRecord``). El token se mantiene en
memoria desde el ``.env`` principal y nunca se reproduce.

Subcomandos:
  replay   reproduce el baseline completo (924 requests) contra el oráculo.
  confirm  reproduce un tramo mínimo desde su reset para confirmar un candidato.
  compare  compara V2 contra V1 por ``baseline_id`` y reporta divergencias.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from .models import (
    KIND_AUXILIARY,
    KIND_EXPLORATION,
    RequestSpec,
)
from .oracle_client import OracleClient, StopRequested, SystemClock, UrllibTransport
from .recorder import ExperimentRecorder, PersistenceError, RunStateStore
from .settings import (
    CUTOFF_AT,
    DEFAULT_LOG_PATH,
    MAX_CALLS,
    TOKEN_ENV_VAR,
    ConfigError,
    ORACLE_BASE_URL,
    read_dotenv,
)

AXIS_REPLAY = "V2-DIFF"
AXIS_CONFIRM = "V2-CONF"
RESET_PATH = "/__reset"
REPLAY_PREFIX = "V2-REPLAY-"
CONFIRM_PREFIX = "V2-CONF-"
V1_BASELINE_MIN_ID = 1
V1_BASELINE_MAX_ID = 924

EXIT_OK = 0
EXIT_GAP = 4
EXIT_CONFIG = 1


# -- baseline ---------------------------------------------------------------


def load_baseline(path: str | os.PathLike) -> list:
    """Devuelve las filas del baseline ordenadas por ``id`` ascendente."""

    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows.sort(key=lambda r: r.get("id", 0))
    return rows


def is_real_reset(row: dict) -> bool:
    """Un reset efectivo es ``POST /__reset`` con status 200.

    ``GET /__reset`` (E404) y los reset sin autorización (401) no reinician el
    estado y por lo tanto no delimitan tramos.
    """

    return (
        row.get("ruta") == RESET_PATH
        and row.get("metodo") == "POST"
        and row.get("status") == 200
    )


def _baseline_signature(row: dict) -> dict:
    return {"status": row.get("status"), "response": row.get("response")}


def _signature_text(row: dict) -> str:
    return json.dumps(_baseline_signature(row), ensure_ascii=False, sort_keys=True)


def _case_id(prefix: str, baseline_id: int) -> str:
    return f"{prefix}{baseline_id:04d}"


def _spec_from_row(row: dict, case_id: str, axis: str, hypothesis: str) -> RequestSpec:
    kind = KIND_AUXILIARY if row.get("kind") == "auxiliary" else KIND_EXPLORATION
    return RequestSpec(
        case_id=case_id,
        method=row.get("metodo"),
        path=row.get("ruta"),
        hypothesis=hypothesis,
        axis=axis,
        kind=kind,
        auth_mode=row.get("auth", "valid"),
        body_raw=row.get("request_raw"),
        content_type=row.get("tipo_contenido"),
        sequence=row.get("seq"),
    )


def resolve_token(env_path: str | os.PathLike) -> str:
    """Obtiene el token del oráculo sin reproducir su valor.

    Prioriza ``ORACLE_TOKEN`` del entorno; si no está, lee el ``.env`` indicado
    y acepta ``ORACLE_TOKEN`` o la clave ``token`` que el entorno local usa.
    """

    from_env = os.environ.get(TOKEN_ENV_VAR)
    if from_env and from_env.strip():
        return from_env
    values = read_dotenv(env_path)
    token = values.get(TOKEN_ENV_VAR) or values.get("token")
    if token is None or not token.strip():
        raise ConfigError("token del oráculo ausente en .env (ORACLE_TOKEN/token)")
    return token


def build_client(args, token: str, limit: int) -> OracleClient:
    return OracleClient(
        UrllibTransport(),
        SystemClock(),
        token=token,
        base_url=args.base_url,
        max_calls=limit,
        cutoff=CUTOFF_AT,
    )


# -- replay -----------------------------------------------------------------


def run_replay(args) -> int:
    baseline = load_baseline(args.baseline)
    if not baseline:
        print("baseline vacío", file=sys.stderr)
        return EXIT_GAP
    try:
        token = resolve_token(args.env_path)
    except ConfigError as exc:
        print(f"configuración inválida: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    recorder = ExperimentRecorder(args.log_path)
    state_store = RunStateStore(args.state_path)
    done = recorder.case_ids_done()

    pending = [r for r in baseline if _case_id(REPLAY_PREFIX, r["id"]) not in done]
    if not pending:
        print("replay ya completo: 0 pendientes", file=sys.stderr)
        return EXIT_OK

    first = pending[0]
    if done and not is_real_reset(first):
        print(
            "GAP: reanudación insegura; el siguiente baseline "
            f"{first['id']} no inicia tramo con reset. Ejecutar un replay limpio.",
            file=sys.stderr,
        )
        return EXIT_GAP

    client = build_client(args, token, args.limit)
    infra_streak = 0
    recorded = 0
    for row in baseline:
        if row["id"] < first["id"]:
            continue
        case_id = _case_id(REPLAY_PREFIX, row["id"])
        if case_id in done:
            continue
        hypothesis = (
            f"V2-DIFF: replay de baseline id {row['id']} "
            f"({row.get('case_id')}); firma V1 {_signature_text(row)}"
        )
        spec = _spec_from_row(row, case_id, AXIS_REPLAY, hypothesis)
        note = (
            f"baseline_id={row['id']}; v1_status={row.get('status')}; "
            f"v1_response={json.dumps(row.get('response'), ensure_ascii=False)}"
        )
        try:
            results = client.send(spec, row.get("request_raw"), seq=AXIS_REPLAY)
        except StopRequested as exc:
            print(
                f"GAP: detención {exc.reason.value} antes de baseline id {row['id']}",
                file=sys.stderr,
            )
            _save_progress(state_store, client, row["id"])
            return EXIT_GAP
        result = results[-1]
        try:
            recorder.record(
                spec,
                result,
                body_text=row.get("request_raw"),
                observed_at=SystemClock().now_utc().isoformat(),
                seq=AXIS_REPLAY,
                retry_index=len(results) - 1,
                note=note,
            )
        except PersistenceError as exc:
            print(f"GAP: persistencia falló en baseline id {row['id']}: {exc}", file=sys.stderr)
            return EXIT_GAP
        recorded += 1

        if result.infra:
            infra_streak += 1
        else:
            infra_streak = 0
        if infra_streak >= 3:
            print(
                "GAP: infraestructura persistente (3 seguidos con X-Frontier-Infra) "
                f"en baseline id {row['id']}",
                file=sys.stderr,
            )
            _save_progress(state_store, client, row["id"])
            return EXIT_GAP
        if is_real_reset(row) and result.status != 200:
            print(
                "GAP: el reset efectivo baseline id "
                f"{row['id']} no reinició el estado (status {result.status})",
                file=sys.stderr,
            )
            _save_progress(state_store, client, row["id"])
            return EXIT_GAP
        if recorded % 100 == 0:
            _save_progress(state_store, client, row["id"])
            print(f"[v2_diff] replay {recorded} registros", file=sys.stderr)

    _save_progress(state_store, client, baseline[-1]["id"])
    print(f"replay completo: {recorded} registros nuevos", file=sys.stderr)
    return EXIT_OK


def _save_progress(state_store: RunStateStore, client: OracleClient, last_id: int) -> None:
    try:
        state_store.save(
            {
                "call_count": client.calls_made,
                "last_baseline_id": last_id,
                "updated_at": SystemClock().now_utc().isoformat(),
            }
        )
    except PersistenceError:
        pass


# -- confirmación -----------------------------------------------------------


def run_confirm(args) -> int:
    baseline = {r["id"]: r for r in load_baseline(args.baseline)}
    ids = [int(x) for x in args.ids.split(",") if x.strip()]
    if not ids:
        print("sin ids a confirmar", file=sys.stderr)
        return EXIT_GAP
    try:
        token = resolve_token(args.env_path)
    except ConfigError as exc:
        print(f"configuración inválida: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    recorder = ExperimentRecorder(args.log_path)
    done = recorder.case_ids_done()
    client = build_client(args, token, args.limit)
    recorded = 0
    for n in ids:
        row = baseline.get(n)
        if row is None:
            print(f"baseline id {n} inexistente", file=sys.stderr)
            return EXIT_GAP
        case_id = _case_id(CONFIRM_PREFIX, n)
        if case_id in done:
            continue
        hypothesis = (
            args.hypothesis
            or f"V2-CONF: control de un factor para baseline id {n}; firma V1 "
            f"{_signature_text(row)}"
        )
        spec = _spec_from_row(row, case_id, AXIS_CONFIRM, hypothesis)
        note = (
            f"baseline_id={n}; v1_status={row.get('status')}; "
            f"v1_response={json.dumps(row.get('response'), ensure_ascii=False)}; "
            f"confirm='{args.label or 'candidato'}'"
        )
        try:
            results = client.send(spec, row.get("request_raw"), seq=AXIS_CONFIRM)
        except StopRequested as exc:
            print(f"GAP: detención {exc.reason.value} en baseline id {n}", file=sys.stderr)
            return EXIT_GAP
        result = results[-1]
        try:
            recorder.record(
                spec,
                result,
                body_text=row.get("request_raw"),
                observed_at=SystemClock().now_utc().isoformat(),
                seq=AXIS_CONFIRM,
                retry_index=len(results) - 1,
                note=note,
            )
        except PersistenceError as exc:
            print(f"GAP: persistencia falló en baseline id {n}: {exc}", file=sys.stderr)
            return EXIT_GAP
        recorded += 1
    print(f"confirmación completa: {recorded} registros nuevos", file=sys.stderr)
    return EXIT_OK


# -- comparación ------------------------------------------------------------


def _replay_index(rows: list) -> dict:
    """Mapea ``baseline_id → fila V2-REPLAY``."""

    index = {}
    for r in rows:
        cid = r.get("case_id") or ""
        if cid.startswith(REPLAY_PREFIX):
            try:
                index[int(cid[len(REPLAY_PREFIX):])] = r
            except ValueError:
                continue
    return index


def _diverges(v1: dict, v2: dict) -> bool:
    return (
        v1.get("status") != v2.get("status")
        or v1.get("response") != v2.get("response")
    )


def run_compare(args) -> int:
    # El log predeterminado es append-only y contiene tanto V1 como evidencia
    # V2. Solo los IDs originales 1–924 constituyen el baseline de comparación.
    baseline = [
        row
        for row in load_baseline(args.baseline)
        if V1_BASELINE_MIN_ID <= row.get("id", 0) <= V1_BASELINE_MAX_ID
    ]
    all_rows = load_baseline(args.log_path)
    v2 = _replay_index(all_rows)

    tramo_id = None
    tramo_first = None
    divergences = []
    compared = 0
    missing = []
    for row in baseline:
        n = row["id"]
        if is_real_reset(row):
            tramo_id = n
        rep = v2.get(n)
        if rep is None:
            missing.append(n)
            continue
        compared += 1
        if _diverges(row, rep) and tramo_first != n:
            # Solo la primera divergencia de cada tramo cuenta como candidato;
            # las siguientes pueden ser cascadas de estado.
            already = any(d["baseline_id"] == n for d in divergences)
            key_reset = tramo_id
            if any(d["tramo_reset"] == key_reset for d in divergences):
                continue
            divergences.append(
                {
                    "baseline_id": n,
                    "tramo_reset": key_reset,
                    "case_id": row.get("case_id"),
                    "request": row.get("request_raw"),
                    "v1_status": row.get("status"),
                    "v1_response": row.get("response"),
                    "v2_status": rep.get("status"),
                    "v2_response": rep.get("response"),
                }
            )

    report = {
        "baseline_total": len(baseline),
        "compared": compared,
        "missing_replay": missing,
        "tramos": len({d["tramo_reset"] for d in divergences}),
        "tramo_first_divergences": divergences,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return EXIT_OK


# -- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v2_diff",
        description="Replay diferencial V1→V2 del oráculo activo.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    r = sub.add_parser("replay", help="reproduce el baseline completo")
    r.add_argument("--baseline", default=DEFAULT_LOG_PATH)
    r.add_argument("--log-path", default=DEFAULT_LOG_PATH)
    r.add_argument("--state-path", default=".probe-state.v2-diff.json")
    r.add_argument("--env-path", default=".env")
    r.add_argument("--base-url", default=ORACLE_BASE_URL)
    r.add_argument("--limit", type=int, default=MAX_CALLS)
    r.set_defaults(func=run_replay)

    c = sub.add_parser("confirm", help="reproduce un tramo mínimo")
    c.add_argument("--baseline", default=DEFAULT_LOG_PATH)
    c.add_argument("--log-path", default=DEFAULT_LOG_PATH)
    c.add_argument("--state-path", default=".probe-state.v2-diff.json")
    c.add_argument("--env-path", default=".env")
    c.add_argument("--base-url", default=ORACLE_BASE_URL)
    c.add_argument("--limit", type=int, default=150)
    c.add_argument("--ids", required=True, help="ids de baseline separados por coma")
    c.add_argument("--label", default=None)
    c.add_argument("--hypothesis", default=None)
    c.set_defaults(func=run_confirm)

    p = sub.add_parser("compare", help="compara V2 contra V1")
    p.add_argument("--baseline", default=DEFAULT_LOG_PATH)
    p.add_argument("--log-path", default=DEFAULT_LOG_PATH)
    p.set_defaults(func=run_compare)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in ("replay", "confirm"):
        if not Path(args.env_path).exists():
            print(f"configuración inválida: {args.env_path} no existe", file=sys.stderr)
            return EXIT_CONFIG
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
