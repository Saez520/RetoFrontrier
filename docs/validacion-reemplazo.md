# Informe de validación del reemplazo

## Propósito y alcance

Este informe organiza la evidencia de validación disponible para el reemplazo y
separa los resultados locales de los smoke checks remotos anteriores. No
certifica equivalencia integral con el servicio original. Las cifras aquí
citadas describen ejecuciones ya registradas; no se ejecutaron pruebas nuevas
para elaborar este documento.

## Validación local

| Comprobación | Entorno | Resultado registrado | Fuente |
| --- | --- | --- | --- |
| Validación del reemplazo | Validador del reto | APPROVED, 100/100 | Engram #8300 |
| Suite completa | Python 3.12 | 209 tests pasaron | Engram #8300 |
| Pruebas HTTP | Python 3.12 | 48 pruebas pasaron | Engram #8300 |
| Compilación de módulos | `compileall` | Pasó | Engram #8300 |
| Higiene del diff | `git diff --check` | Pasó | Engram #8300 |

Estos resultados son locales. No demuestran que los cambios más recientes se
hayan desplegado o comprobado remotamente.

## Smoke checks remotos previos

| Comprobación | Contexto registrado | Resultado | Fuente |
| --- | --- | --- | --- |
| Smoke checks de Railway | Contexto de `origin/master` en `b82ca61`; el SHA efectivo servido por Railway no fue confirmado desde la plataforma | 18/18 pasaron | Engram #8294; resumen #8295 |

La referencia a `b82ca61` describe el contexto observado durante la ejecución,
no una confirmación del commit realmente servido por Railway. Estos checks son
anteriores a los cambios locales posteriores. En particular, no se afirma que
PING/E103 ni los cambios asociados a `affd952` hayan sido probados remotamente.

## Artefactos y fuentes de evidencia

El README define tres entregables distintos: el reemplazo desplegado, la
especificación y el log de experimentos (`README.md`, líneas 38–50). El log
`experimentos.jsonl` conserva evidencia cruda de requests, respuestas e
hipótesis; es un entregable separado y no se sustituye por este informe. Este
documento no modifica ese log.

Fuentes relacionadas:

- `README.md`, líneas 38–50: lista de entregables.
- `docs/especificacion.md`, secciones 5 y 8: método, evidencia y estado de
  verificación documentados.
- `docs/operacion-reemplazo.md`: alcance operativo y procedimiento de smoke
  checks, que no implica que se hayan ejecutado en esta tarea.
- Engram #8294 y #8295: resultados remotos previos y su contexto.
- Engram #8300: validación local.
- Engram #8309: inspección del tercer entregable.

## Límites y estado no verificado

- El SHA efectivo ejecutado por Railway durante los smoke checks 18/18 no está
  confirmado.
- No consta una validación remota posterior a los cambios locales recientes;
  en particular, no se atribuyen pruebas remotas a `affd952`.
- `TRANSFER` continúa provisionalmente indisponible (HTTP 503) tras validar la
  entrada, según `docs/especificacion.md` y `docs/operacion-reemplazo.md`.
- E506 y el tercer delta V2 siguen abiertos y sin regla general confirmada.
- La cobertura registrada no es prueba de equivalencia integral ni exhaustiva
  con el servicio original.
