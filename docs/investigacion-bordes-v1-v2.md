# Investigación parcial de bordes V1→V2

## Alcance y estado

HF-bordes fue una investigación W1 parcial, no una especificación completa ni
una certificación integral del reemplazo. El paquete validado fue aprobado
únicamente como evidencia parcial; quedan cuestiones sin resolver.

La evidencia de la investigación llegó hasta los IDs 2123–2130 del registro de
experimentos. En esa última secuencia se crearon dos cuentas con el mismo
nombre (`ProbeTwin`), se depositaron 500000 unidades en la cuenta de origen y se
observaron tres transferencias aceptadas por V2: 1, 100000 y 120000. La consulta
posterior mostró saldo 2799.99. Estos resultados describen ese contexto de V2;
no prueban por sí solos un delta V1→V2.

## Hallazgos y límites

- El cambio de formato decimal de `CONSULTA.saldo` es un delta observado y
  separado en la investigación.
- E506/TRANSFER permanece contextual: los resultados observados en V2 varían
  según el patrón de nombres de titulares y el contexto de la prueba. No se
  establece una regla general ni un umbral fijo.
- Las tres transferencias aceptadas en la secuencia de IDs 2123–2130 son
  observaciones V2-only; no existe un comparador V1 equivalente para ese
  escenario de dos cuentas con el mismo nombre. Por tanto, esto no demuestra un
  delta V1→V2.
- El tercer delta informado no está identificado. HF-bordes no encontró ni
  certificó los tres cambios.

## Separación de workstreams

`CA-reemplazo-comandos` es un workstream W2 separado, con su propio alcance y
artefactos. No forma parte de los resultados de HF-bordes. La investigación
parcial aquí documentada no prescribe su implementación ni convierte el
comportamiento contextual de E506 en una regla de producto.

## Trazabilidad

- Plan y contexto de investigación: Engram #8226 (`hotfix/hf-bordes/artifact/plan`).
- Registro de la última secuencia V2, IDs 2123–2130: Engram #8232
  (`hotfix/hf-bordes/artifact/debrief`).
- Validación parcial: Engram #8259
  (`flow-state/hotfix/hf-bordes/validate`); su aprobación aplica al paquete
  parcial, no al sondeo completo.
- La evidencia cruda y el harness auxiliar se conservan en los artifacts y el
  debrief de la investigación; no se incorporan a este resumen versionable.
