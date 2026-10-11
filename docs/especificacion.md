# Especificación de comportamiento respaldado

## 1. Propósito, alcance y límites

Este documento describe el comportamiento actualmente implementado y
respaldado; no afirma equivalencia integral con el servicio original ni
sustituye el registro de evidencia. Las reglas se limitan
a autenticación, disponibilidad, reset, comandos de cuenta disponibles y el
rechazo provisional de transferencias.

## 2. Reglas verificadas

- `GET /health` y las rutas de referencia requieren la autenticación que
  corresponda al selector del catálogo. La aplicación debe estar lista; si no,
  responde HTTP 503 con diagnóstico de base no lista sin secretos.
- `POST /__reset` autenticado reinicia el estado temporal y sus contadores; es
  idempotente.
- `POST /msg` requiere JSON con un campo `m` de tipo string, credencial válida
  y base lista. `PING` exactamente, sin `;` ni control, responde HTTP 400 con
  `{"error":"E103","mensaje":"falta control"}` antes del despacho y sin
  efectos. `PING;64`, `ping;64` y `Ping;64` responden HTTP 200 con
  `{"pong":true}`.
- Para PING se conserva la precedencia observada: segmento vacío E104; aridad
  extra E302; control no numérico o de más de dos cifras E201; control numérico
  de una o dos cifras responde pong.
- `ALTA`, `CONSULTA`, `DEPOSITO` y `ANULA` operan sobre estado temporal por
  aplicación. Las cuentas usan `AC-%04d` y los depósitos aceptados `OP-%04d`.
  `CONSULTA.saldo` es texto decimal con dos posiciones (centavos enteros
  convertidos a unidades), por ejemplo 0 → `"0.00"`, 1 → `"0.01"` y 500000
  → `"5000.00"`.
- La primera anulación de un depósito revierte el importe; repetirla devuelve
  `{"ok":false,"motivo":"ya anulada"}` sin una segunda reversión. Se
  preservan los campos y literales respaldados, incluidos `cuentaId`,
  `cuenta_id`, `operacionId` y `recieved`.
- Un TRANSFER que supera la validación de entrada responde HTTP 503 con el
  cuerpo literal `aún no disponible`, sin efectos ni consumo de identificador.
  No se ejecuta lógica de negocio de transferencia.

## 3. Contrato observable relevante

| Entrada | Resultado |
| --- | --- |
| JSON inválido | HTTP 400, E100 `JSON inválido` |
| `m` ausente o no string | HTTP 400, E102 `falta mensaje` |
| PING sin separador/control | HTTP 400, E103 `falta control` |
| PING con segmento vacío | HTTP 400, E104 `segmento vacío` |
| PING con control no numérico o de más de 2 cifras | HTTP 400, E201 `control mal formado` |
| PING con aridad adicional | HTTP 400, E302 `aridad inválida` |
| PING con control numérico de 1–2 cifras | HTTP 200, JSON `{"pong":true}` |
| TRANSFER tras validar entrada | HTTP 503, texto exacto `aún no disponible` |

Los objetos JSON se comparan por campos y valores, no por orden de claves. El
cuerpo de texto de TRANSFER es literal. La autenticación, validación HTTP y
disponibilidad preceden al procesamiento del mensaje.

## 4. Estado y efectos

| Solicitud | Efecto en estado |
| --- | --- |
| PING con o sin control | Ninguno; PING sin control se rechaza antes del despacho |
| Entrada rechazada | Ninguno; no consume identificadores |
| ALTA | Crea una cuenta y consume un identificador de cuenta |
| DEPOSITO aceptado | Aumenta saldo, crea operación y consume identificador |
| CONSULTA | Ninguno |
| Primera ANULA válida | Revierte una operación de depósito una sola vez |
| TRANSFER validada | Ninguno; continúa provisionalmente indisponible |
| Reset autenticado | Borra cuentas, operaciones, anulaciones y reinicia secuencias |

El estado vive en memoria en un proceso. No se garantiza recuperación durable
tras reinicio ni consistencia entre réplicas.

## 5. Evidencia y método

La corrección del PING sin control está respaldada por los casos del registro
principal `experimentos.jsonl` identificados como 357 y 367 y por el contrato
de entrada asociado. La conversión de `CONSULTA.saldo` desde entero de
centavos a texto decimal de dos posiciones se trata como cambio confirmado
V1→V2 según la evidencia previa documentada. La suite local cubre regresiones
HTTP y secuencia de estado; no equivale a un sondeo remoto del cambio nuevo.

El método es observacional: cada regla debe asociarse a evidencia reproducible
y mantenerse separada de inferencias o correlaciones. El archivo de evidencia
es de solo lectura para esta implementación.

## 6. Observaciones parciales

Se observaron respuestas E506 de TRANSFER en algunos contextos y éxito en
contextos con nombres duplicados. La correlación no demuestra una regla general
ni causa suficiente; estos resultados son contextuales y no están
generalizados en el servicio implementado. No utilizar E506 como regla
financiera deducida de este documento.

## 7. Hipótesis, exclusiones y límites

- No se implementan ejecución financiera, umbrales, movimientos, anulaciones
  de transferencias ni excepciones de TRANSFER por monto o titular.
- El comportamiento asociado a E506 y nombres duplicados es hipótesis/observación
  parcial, no contrato general.
- Existe una pista de un tercer cambio V2, pero no está identificado ni
  respaldado aquí; no se atribuye a un comando o regla.
- No se afirma equivalencia completa V2, cobertura exhaustiva de entradas,
  persistencia durable, escalado horizontal ni uso del servicio original como
  fallback.

Estas exclusiones no autorizan a incorporar las hipótesis como reglas de
negocio.

## 8. Estado de verificación

- **Resultados previos:** se registraron 18 comprobaciones remotas satisfactorias
  del alcance parcial anterior; no prueban la corrección nueva de PING ni
  identifican por SHA lo desplegado.
- **Verificación local de esta entrega:** ejecutar las pruebas de integración
  (`tests/test_app.py`) y la suite completa. Los resultados deben reportarse
  con el commit inspeccionado.
- **Publicación:** no se infiere del resultado de pruebas locales; requiere
  despliegue y registro separado.
- **Pruebas remotas nuevas:** quedan a cargo del desarrollador en otra sesión.
  Los smoke tests están descritos en `docs/operacion-reemplazo.md`; no se
  presentan como ya ejecutados.
