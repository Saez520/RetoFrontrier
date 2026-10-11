# Operación del reemplazo

Runbook para desplegar y comprobar el servicio remoto autenticado. No contiene
credenciales: el token se carga únicamente como variable de entorno segura.

## Alcance vigente

- `GET /health` informa disponibilidad cuando la configuración y el catálogo
  requerido están listos; requiere autenticación.
- `POST /__reset` reinicia de forma idempotente las cuentas, operaciones y
  secuencias del estado temporal.
- `POST /msg` admite `PING`, `ALTA`, `CONSULTA`, `DEPOSITO` y `ANULA` (esta
  última anula depósitos). `PING` con control, por ejemplo `PING;64`, responde
  HTTP 200 `{"pong":true}`. El mensaje exactamente `PING` sin control responde
  HTTP 400 `{"error":"E103","mensaje":"falta control"}` y no tiene efectos.
- `CONSULTA` representa el saldo como texto decimal con dos posiciones.
  Cuentas y operaciones usan identificadores secuenciales `AC-%04d` y
  `OP-%04d`; anular dos veces no revierte dos veces.
- `TRANSFER`, tras pasar las validaciones de entrada, responde HTTP 503 con el
  texto literal `aún no disponible`, sin efectos ni identificador. No se
  habilita por monto ni por nombre de titular.
- Se ejecuta un solo proceso con estado en memoria. Reinicios del proceso o
  redespliegues no prometen conservarlo. Otras rutas/métodos usan las
  respuestas del catálogo de referencia y el fallback vigente.

## Insumos requeridos antes de aceptar

1. `experimentos.jsonl` legible, usado como evidencia de solo lectura.
2. `reference_cases.json` con los selectores de salud, reset, autenticación y
   fallback requeridos por el catálogo.

Una configuración ausente, ilegible o inconsistente mantiene la base no lista.
No se debe recurrir al servicio original para atender solicitudes.

## Pasos de despliegue

1. Conectar Railway al repositorio y a la rama de entrega.
2. Definir **una sola réplica** y desactivar **Serverless** (apagado por
   inactividad).
3. Cargar en la consola de Railway `TEAM_TOKEN` como secreto del equipo y
   `REFERENCE_RESPONSES_PATH` con la ruta del JSONL; nunca guardar el valor del
   token en el repositorio o en registros.
4. Colocar `experimentos.jsonl` y `reference_cases.json` accesibles desde la
   raíz de ejecución.
5. Desplegar. `Procfile` inicia Gunicorn con un worker en
   `replacement.app:app`, escuchando en `0.0.0.0:$PORT`.
6. Registrar URL, fecha, commit desplegado y `evidence_id` utilizados.

> No registrar `/health` como healthcheck de plataforma sin credencial: el
> endpoint exige `Authorization: Bearer`.

## Smoke tests remotos

El desarrollador ejecuta estas comprobaciones después del despliegue. Exportar
URL y token en el shell; el token no se imprime y cada petición tiene timeout
de cinco segundos. El reset borra todo el estado temporal.

```sh
BASE_URL="https://<servicio>.up.railway.app"
: "${TEAM_TOKEN:?definir TEAM_TOKEN en el entorno local}"
TIMEOUT=5
AUTH_HEADER="Authorization: Bearer $TEAM_TOKEN"

# Salud autenticada → 200 y estado listo
curl -s -w '\n%{http_code}\n' --max-time "$TIMEOUT" \
  -H "$AUTH_HEADER" "$BASE_URL/health"

# Reset temporal → 200
curl -s -w '\n%{http_code}\n' --max-time "$TIMEOUT" \
  -X POST -H "$AUTH_HEADER" "$BASE_URL/__reset"

# PING con control → 200/pong; sin control → 400/E103
curl -s -w '\n%{http_code}\n' --max-time "$TIMEOUT" \
  -X POST -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d '{"m":"PING;64"}' "$BASE_URL/msg"
curl -s -w '\n%{http_code}\n' --max-time "$TIMEOUT" \
  -X POST -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d '{"m":"PING"}' "$BASE_URL/msg"

# ALTA → AC-0001; DEPOSITO → OP-0001; CONSULTA refleja el saldo
curl -s -w '\n%{http_code}\n' --max-time "$TIMEOUT" \
  -X POST -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d '{"m":"ALTA;Lucia;82"}' "$BASE_URL/msg"
curl -s -w '\n%{http_code}\n' --max-time "$TIMEOUT" \
  -X POST -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d '{"m":"DEPOSITO;AC-0001;1;28"}' "$BASE_URL/msg"
curl -s -w '\n%{http_code}\n' --max-time "$TIMEOUT" \
  -X POST -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d '{"m":"CONSULTA;AC-0001;14"}' "$BASE_URL/msg"

# ANULA del depósito → éxito; TRANSFER válida → 503 provisional sin efectos
curl -s -w '\n%{http_code}\n' --max-time "$TIMEOUT" \
  -X POST -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d '{"m":"ANULA;OP-0001;66"}' "$BASE_URL/msg"
curl -s -w '\n%{http_code}\n' --max-time "$TIMEOUT" \
  -X POST -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d '{"m":"TRANSFER;AC-0001;AC-0001;1;71"}' "$BASE_URL/msg"

# Ruta desconocida → respuesta del catálogo/fallback
curl -s -o /dev/null -w '%{http_code}\n' --max-time "$TIMEOUT" \
  -H "$AUTH_HEADER" "$BASE_URL/ruta/inexistente"
```

Registrar status, cuerpo pertinente y commit; nunca el token. Estas
comprobaciones no certifican reglas financieras fuera del alcance descrito.

## Criterios de aceptación / no aceptación

- Aceptar la comprobación cuando cada petición termine dentro de cinco
  segundos y coincida con la respuesta esperada para su etapa.
- Si falta configuración/evidencia, el catálogo no está listo o una respuesta
  difiere, detener aceptación; `/health` devuelve HTTP 503 con diagnóstico sin
  secretos cuando la base no está lista.
- No afirmar persistencia después de reinicio, operación multi-réplica,
  TRANSFER exitosa ni conformidad integral con un sistema externo.
- Mantener una réplica y Serverless desactivado porque el estado es local al
  proceso.
