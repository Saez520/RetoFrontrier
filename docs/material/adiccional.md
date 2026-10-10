ruta servidor: https://caja-negra-production-c64f.up.railway.app

CONTRATO DEL ENTRYPOINT
Desplegado por tu equipo, accesible desde internet desde las 20:00 hasta que termine el demo day. Todas las llamadas llevan Authorization: Bearer <token>. Despliégalo donde quieras.
Authorization: Bearer <token>
Todas las llamadas incluyen el token del equipo en este header.
GET /health
Responde 200 cuando el servicio está listo.
/* (URL base)
Acepta exactamente los mismos requests que el servicio original, incluidas las rutas que no existen.
POST /__reset
Vuelve el reemplazo a su estado inicial. Lo llamamos antes de cada test. Con otro token o sin token, responde como el original.