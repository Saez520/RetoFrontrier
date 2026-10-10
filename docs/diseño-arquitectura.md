# Diseño: Reemplazo de la caja negra

## 0. Contexto y objetivo

El original es un servicio HTTP en producción desde hace 10 años, sin código ni documentación. Recibe mensajes en `POST /msg` con cuerpo `{"m": "..."}` y responde. También expone `POST /__reset` y `GET /health`.

**Objetivo**

- Un reemplazo desplegado en internet que devuelva el mismo status y el mismo cuerpo que el original ante cualquier request, errores y rutas inexistentes incluidos.
- Una especificación que permita reimplementarlo sin acceso al original.
- El log de experimentos (`experimentos.jsonl`) que sustenta cada afirmación de la especificación.

## 1. Método de descubrimiento

Caja negra observacional: el único oráculo es el original en vivo. El ciclo es:

```
hipótesis → request → registro → conclusión → codificación
```

- Cada request al original queda registrado en `experimentos.jsonl` con `id, seq, x_req, hipotesis, request, status, response, conclusion`.
- Toda secuencia arranca con `POST /__reset`.
- Las respuestas con header `X-Frontier-Infra` se descartan y el request se reintenta.
- Rate limit: 10 req/s y 8000/día por token. Los tokens del equipo exploran en paralelo con estados separados.

**Dimensiones del sondeo** (cada una produce líneas del log citables desde la especificación):

1. **Entrada**
   - Rutas y métodos distintos de los tres conocidos.
   - Cuerpo no JSON.
   - Campo `m` ausente o con tipo distinto de string.
   - Claves adicionales en el cuerpo.
   - Longitud máxima del mensaje.
   - Token ausente o ajeno.

2. **Integridad**
   - Separador `;`.
   - Aridad por comando.
   - Campo `control`. Los ejemplos distinguen dos errores: E201 "control mal formado" con valor no numérico (n=17, `5X`) y E202 "control inválido" con valor numérico (n=2 con `83` frente a n=3 con `82`, mismo mensaje).
   - El sondeo varía un carácter por vez para derivar la función que produce el control.

3. **Comandos**
   - Catálogo: los ejemplos muestran PING, ALTA, CONSULTA, DEPOSITO, TRANSFER y ANULA; SALDOS responde E301 (n=12).
   - Argumentos, efecto sobre el estado y cuerpo exacto de cada uno.
   - Sensibilidad a mayúsculas: `CONSULTa` responde 200 con el mismo control 14 que `CONSULTA` (n=11 frente a n=5).

4. **Memoria**
   - Identificadores secuenciales: AC-0001, AC-0002; OP-0001 a OP-0004 (n=3, 4, 6, 7, 10, 18).
   - Saldos y su evolución.
   - Anulación repetida (n=13 `ok:true`, n=14 `ok:false "ya anulada"`).
   - Límites (E506 n=9, E507 n=16).

5. **Errores**
   - Status y cuerpo literal de cada uno.
   - Orden de evaluación, obtenido provocando pares de errores en un mismo request.

6. **Cambios durante el día**
   - La secuencia de 20 ejemplos se reenvía al original cada hora.
   - Una divergencia frente a la grabación de la mañana marca un cambio, con hora y línea del log.

## 2. Arquitectura del reemplazo

Servicio web en Python, un solo proceso, estado en memoria. Pipeline de un request:

1. **Entrada HTTP**: acepta cualquier ruta y método.
2. **Autenticación**: lee `Authorization: Bearer <token>`. El token del equipo opera el estado; con otro token o sin token, responde lo medido en el original.
3. **Ruteo**: `GET /health`, `POST /__reset`, `POST /msg` y catch-all para el resto.
4. **Validación de `/msg`**: separa `m` por `;`, identifica comando, aridad y control, en el orden de evaluación medido.
5. **Despacho**: ejecuta el manejador del comando sobre el estado.
6. **Estado**: cuentas, operaciones y contadores de ID en memoria; `/__reset` lo vacía.
7. **Respuesta**: status y cuerpo literal.

**Reglas fijadas por el diseño**

- Las respuestas se guardan como literales copiados del original, incluido `"recieved"` (n=6, 7, 10, 18) y el espacio final de `"comando desconocido "` (n=12). Ninguna constante se corrige.
- Los cuerpos no JSON se devuelven byte a byte; el framework no genera páginas de error propias.
- Toda ruta o método no sondeado responde con lo medido en el original para una ruta inexistente; queda anotado como supuesto en la especificación.
- Si a las 20:00 la función del control no está derivada, el reemplazo acepta todo control numérico y responde E201 ante los no numéricos; queda anotado como supuesto. En los 20 ejemplos, 2 requests fallan por control (n=2, n=17), 2 fallan por comando o aridad (n=12, n=20) y 16 reciben una respuesta que no es de control.
- `GET /health` y `POST /__reset` devuelven el status y el cuerpo medidos en el original.

**Despliegue**

Railway, un servicio, una réplica, Serverless desactivado (valor por defecto), despliegue desde el repositorio de GitHub con detección automática de Python. El servicio escucha en el puerto `PORT` que asigna la plataforma.

## 3. Harness de validación

El harness de validación es diferencial: el oráculo es el original en vivo, y compara la salida del reemplazo contra la del original caso por caso.

Por cada caso:

1. `POST /__reset` en ambos servicios.
2. Mismo request al original y al reemplazo.
3. Captura de status, cuerpo y `X-Req`.
4. Comparación con las reglas del evaluador:
   - Status igual.
   - Si ambos cuerpos son JSON: claves en cualquier orden, arrays en orden, strings y números idénticos.
   - Si alguno no es JSON: texto exacto carácter por carácter.

Casos:

- Los 20 ejemplos conocidos.
- El generador combinatorio: comandos, aridad, controles y secuencias con estado de 2 a 12 pasos.
- Las líneas del log.

Salida: reporte de divergencias que alimenta la corrección del reemplazo y nuevas líneas del log. Después de cada despliegue se valida el entrypoint en `/evento` y se lee `/evento/resultados`.

## 4. Tradeoffs

| Decisión | Alternativa | Motivo |
| --- | --- | --- |
| Python | Lenguaje compilado | Velocidad de iteración; el rendimiento no pesa con 5 s por paso. |
| Estado en memoria | Base de datos externa | El set habla a un solo proceso; una base agrega latencia y un modo de fallo sin beneficio. |
| Validación diferencial automatizada | Muestreo manual | El oráculo vive hasta las 20:00; cada minuto de comparación manual es un experimento menos. |
| Railway, un servicio y una réplica | Plataforma con auto-escalado o apagado por inactividad | El estado vive en memoria y el set habla a un solo proceso; varias instancias o el apagado entre pasos rompen la continuidad de una secuencia. |
| Respuestas como literales copiados | Plantillas o constantes propias | Una corrección ortográfica (`"recieved"`) o un espacio de menos hace fallar la comparación carácter a carácter. |
| Default de ruta desconocida: respuesta medida de ruta inexistente | 404 del framework | El cuerpo del framework difiere del original y resta en el set. |
| Fallback del control: aceptar numéricos | Rechazar todo control no derivado | 16 de 20 ejemplos reciben respuesta que no es de control; aceptar maximiza pasos correctos si la función no se deriva a tiempo. |
| Orden de errores por defecto: comando, aridad, control | Orden arbitrario del framework | Es el orden del pipeline; se reemplaza por el medido en cuanto el sondeo lo fija. |

## 5. Gaps controlados

| Gap | Tratamiento | Default si no se cierra a las 20:00 |
| --- | --- | --- |
| Función del control | Sondeo variando un carácter por vez sobre mensajes con control conocido (n=1, 3, 4, 5, 6, 7, 8, 10, 11, 13, 15, 16, 18, 19) | Aceptar numéricos, E201 ante no numéricos; supuesto. |
| Rutas y métodos no previstos | Sondeo de rutas y métodos sobre el original | Respuesta medida de ruta inexistente; supuesto. |
| Orden de evaluación de errores | Pares de errores en un mismo request | Comando, aridad, control; supuesto. |
| Token ajeno o ausente | Request con token inválido y request sin header al original | Última medición registrada en el log. |
| Umbral de E506 "límite excedido" | Transferencias con montos crecientes; n=10 pasa con 100000 y n=9 falla con 120000 | Límite por operación de 100000 inclusive; supuesto. |

## 6. Riesgos

- **Cambio del original durante el día**: re-sondeo horario y versionado del log; la especificación fecha cada cambio y la línea que lo detectó.
- **Fidelidad de serialización**: enteros frente a decimales, literales exactos; el harness compara carácter a carácter.
- **Rate limit**: presupuesto por token (8000/día) repartido entre sondeo y harness; las respuestas con `X-Frontier-Infra` se descartan y se reintentan.
- **Múltiples instancias**: una réplica y Serverless desactivado; escalar a 2 réplicas dividiría el estado entre procesos.
- **Despliegue tardío**: cuenta el último entrypoint validado a tiempo; se valida en `/evento` después de cada despliegue.

