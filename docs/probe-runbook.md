# Runbook: sondeo autónomo del original

Herramienta para ejecutar y registrar de forma determinista el sondeo del
servicio original antes del cierre. No implementa el reemplazo, no despliega y
no compara.

## Requisitos

- Python ≥ 3.11 (sin dependencias externas).
- Un archivo `.env` local en la raíz del proyecto con la credencial del equipo:

  ```
  ORACLE_TOKEN=<token-del-equipo>
  ```

  `.env` está en `.gitignore`: nunca se versiona, nunca se copia a la evidencia
  y su valor jamás se imprime ni aparece en los registros.

## Ejecución autónoma

Un único comando, sin entradas ni pausas:

```
python3 scripts/probe_oracle.py --log-path experimentos.jsonl --state-path .probe-state.json
```

Opciones disponibles y nada más:

| Opción | Default | Uso |
| --- | --- | --- |
| `--log-path` | `experimentos.jsonl` | Destino append-only de la evidencia. |
| `--state-path` | `.probe-state.json` | Journal atómico de ejecución y reanudación. |
| `--seed` | `20261010` | Semilla del generador combinario E8. |
| `--base-url` | URL del original | Solo para pruebas locales; por defecto el original. |

Antes de la primera solicitud el driver valida Python, token, escritura del
destino, estado consistente y corte temporal. Si el destino no es escribible
termina con `persistence_preflight_failure` y código distinto de cero, sin
imprimir la credencial.

## Qué hace

1. Ejecuta el reset único y las 300 posiciones de control E0.
2. Invoca **una sola vez** el solver de control: combina los valores aceptados de
   E0 con los pares documentados de `docs/material/ejemplos.jsonl`, prueba el
   catálogo finito de canonicalizadores, métricas y familias afines, y adopta una
   función solo si supera ajuste y hold-out y produce un único vector.
3. Corre E1, E2, E3 y E6 (independientes) y E4, E5 y E8 (dependientes del vector).
4. Procesa E7 entre secuencias: repite los veinte mensajes de ejemplo tras un
   reset, cada hora desde el arranque y a las 19:50 UTC-05.

Los límites son fijos: hasta 1000 llamadas al original, 8 llamadas por segundo y
corte absoluto a las `2026-10-10 20:00` hora Colombia (`2026-10-11T01:00:00Z`).

### E7 es horario: re-invocar el comando

El inventario E0–E6/E8 se completa en minutos, pero E7 está agendado por reloj
(cada hora desde `started_at` y a las 19:50 UTC-05). Un proceso que termina antes
de la próxima marca horaria no ejecuta esas repeticiones: E7 solo avanza cuando
el comando vuelve a correr con el **mismo** `--state-path` y `--log-path`.

Para cubrir la agenda completa, re-invocar el comando de forma periódica entre el
arranque y el cierre, por ejemplo con `cron` cada 15 minutos:

```
*/15 * * * * cd /ruta/al/proyecto && python3 scripts/probe_oracle.py \
  --log-path experimentos.jsonl --state-path .probe-state.json >> probe.log 2>&1
```

o con un bucle externo equivalente. Cada invocación retoma del estado persistido,
no repite `case_id` ya registrados, no reinicia el presupuesto y solo ejecuta las
marcas horarias de E7 que ya vencieron y no estén en `e7_done`. El token se lee del
`.env` local: no lo ponga en la línea de `cron` ni en el log.

## Salida esperada del solver

- `accepted`: existe una función válida y un único vector de controles; E4/E5/E8
  se ejecutan normalmente. El resumen reporta el candidato de procedencia y la
  huella SHA-256 del vector.
- `no_candidate`: ningún candidato supera ajuste y hold-out.
- `ambiguous_e0`: E0 no arrojó exactamente un control aceptado por base, o no
  coincide con los ejemplos.
- `ambiguous_candidate`: varios candidatos superan las pruebas pero producen
  vectores distintos.
- `control_candidate_rejected`: ya en ejecución, una llamada dependiente devolvió
  `E202`; se detienen E4/E5/E8 y se continúa con los ejes independientes y E7.

Con `no_candidate`, `ambiguous_e0` o `ambiguous_candidate`, el runner ejecuta
E1/E2/E3/E6 y E7 y marca E4/E5/E8 como `pending_control_solver` con la causa. No
pausa, no pide intervención y no reenvía E0.

## Reanudación

Volver a ejecutar el mismo comando con el mismo `--state-path` y `--log-path`
retoma el trabajo:

- No se repite ningún `case_id` ya registrado.
- El presupuesto acumulado nunca se reinicia.
- El resultado del solver se reutiliza tal como quedó persistido.
- Un intento preparado sin respuesta se registra como `resultado_desconocido` y
  nunca se reenvía automáticamente.

## Interpretación y límites

- La evidencia vive en `experimentos.jsonl` (una línea JSON por intento) con
  `conclusion` siempre `null`: la captura no interpreta el servicio.
- Las respuestas con `X-Frontier-Infra` se conservan marcadas como
  infraestructura y no cuentan como evidencia del comportamiento del servicio.
- El resumen final (stderr) distingue exploración prevista/ejecutada/pendiente,
  auxiliares, reintentos, infraestructura, estados del solver, secuencias
  completas/incompletas/inciertas, E7 prevista/efectiva/pendiente, consumo
  asumido/verificado y el motivo de detención. No declara cobertura total.

## Reutilización para comparación diferencial

`OracleClient` y `ExperimentRecorder` son el punto de integración para un
consumidor que agregue otro cliente y una comparación diferencial. Este script no
se extiende a esa función: no incluye cliente del reemplazo ni comparador.

## Prohibiciones

- No versionar `.env`, tokens ni logs con secretos.
- No imprimir el valor de `Authorization`.
- No ejecutar el original desde el reemplazo.
