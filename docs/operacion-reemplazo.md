# Operación del reemplazo (base remota)

Runbook para desplegar y validar la base remota autenticada con mensajes
provisionalmente no disponibles. No contiene credenciales: el token se carga
solo como variable de entorno segura.

## Alcance de esta base

- Servicio público en Railway, un único proceso, estado en memoria.
- `GET /health` responde cuando la base está lista para su alcance.
- `POST /__reset` restaura el estado temporal y es idempotente.
- `POST /msg` con credencial válida responde `503` con el texto literal
  `aún no disponible`; no interpreta comandos ni crea estado de negocio.
- Otras rutas y métodos reproducen la respuesta de referencia medida; las no
  observadas usan el fallback de ruta como supuesto.

## Insumos requeridos antes de aceptar

1. `experimentos.jsonl` con las respuestas de referencia (solo lectura).
2. `reference_cases.json` con los once selectores mínimos:
   - `GET /health` válido / ausente / inválido
   - `POST /__reset` válido / ausente / inválido
   - `POST /msg` ausente / inválido
   - fallback de ruta válido / ausente / inválido

`POST /msg` con credencial válida no usa evidencia: siempre devuelve el aviso
provisional.

## Pasos de despliegue

1. Conectar Railway al repositorio y a la rama de entrega.
2. Definir **una sola réplica**.
3. Desactivar **Serverless** (apagado por inactividad).
4. Cargar las variables de entorno desde la consola de Railway:
   - `TEAM_TOKEN` = credencial del equipo (nunca en el repositorio).
   - `REFERENCE_RESPONSES_PATH` = ruta del JSONL de evidencia.
5. Colocar `experimentos.jsonl` y `reference_cases.json` accesibles en la raíz
   de ejecución del servicio.
6. Desplegar. El comando de proceso (`Procfile`) arranca Gunicorn con un único
   worker sobre `replacement.app:app`, escuchando en `0.0.0.0:$PORT`.
7. Registrar la URL pública resultante.
8. Guardar la fecha, el commit desplegado y los `evidence_id` usados.

> No registrar `/health` como healthcheck de plataforma: el endpoint exige
> `Authorization: Bearer`, por lo que un chequeo no autenticado fallaría.

## Smoke tests remotos

Exportar la URL y el token en el shell local. El token **no se imprime** y cada
petición usa un timeout de cinco segundos.

```sh
BASE_URL="https://<servicio>.up.railway.app"
: "${TEAM_TOKEN:?definir TEAM_TOKEN en el entorno local}"
TIMEOUT=5

# 1. Salud con credencial válida → 200 y cuerpo de referencia
curl -s -o /dev/null -w '%{http_code}\n' --max-time "$TIMEOUT" \
  -H "Authorization: Bearer $TEAM_TOKEN" "$BASE_URL/health"

# 2. Reinicio con credencial válida → cuerpo de referencia
curl -s -o /dev/null -w '%{http_code}\n' --max-time "$TIMEOUT" \
  -X POST -H "Authorization: Bearer $TEAM_TOKEN" "$BASE_URL/__reset"

# 3. Mensaje provisional → 503 y "aún no disponible"
curl -s -w '\n%{http_code}\n' --max-time "$TIMEOUT" \
  -X POST -H "Authorization: Bearer $TEAM_TOKEN" \
  -H 'Content-Type: application/json' -d '{"m":"PING;64"}' "$BASE_URL/msg"

# 4. Ruta inexistente con credencial válida → respuesta de referencia
curl -s -o /dev/null -w '%{http_code}\n' --max-time "$TIMEOUT" \
  -H "Authorization: Bearer $TEAM_TOKEN" "$BASE_URL/ruta/inexistente"
```

Registrar solo el status y el cuerpo esperados; nunca el token.

## Criterios de aceptación / no aceptación

- **Aceptada** si los cuatro smoke tests terminan dentro de cinco segundos y
  coinciden con sus respuestas de referencia.
- **Bloqueada, no aceptada** si el catálogo no está listo (falta la credencial,
  la evidencia no es legible, una línea es inválida o el manifiesto no resuelve
  los selectores requeridos). En ese caso `GET /health` con credencial válida
  responde `503` con un diagnóstico sin secretos.
- Conservar la URL pública hasta el fin del demo day.
- No escalar a más réplicas ni activar Serverless: el estado vive en memoria y
  el set habla a un solo proceso.
