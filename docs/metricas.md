# Métricas y reportes de corrida

SPECS §16 · A15 · A16 · ROADMAP Etapa 12. Código: `web/servicios/servicio_reportes.py`, `exportacion_reportes.py`, `web/rutas/rutas_reportes.py`, pestaña **Reportes** (TERMINAL).

## 1. Rango

- El formulario pide **desde / hasta en hora de la terminal** (UTC-6, sin horario de verano). El servidor lo convierte a UTC antes de consultar y guarda el reporte con las marcas UTC.
- Antes el rango se comparaba tal cual contra marcas UTC y el periodo quedaba desplazado 6 horas. Esto está corregido y cubierto por `test_el_reporte_toma_el_periodo_local_y_no_seis_horas_antes`.
- Acepta también marcas ISO con zona (`…Z`, `-06:00`).
- Un rango ilegible responde `422 RANGO_INVALIDO`; uno invertido o vacío, `422 RANGO_INVERTIDO`.
- La exportación de la pestaña Grúa usa la misma conversión.

## 2. Las 8 métricas (§16.1)

| # | Clave en el JSON | Cálculo sobre el periodo | Unidad |
|---|---|---|---|
| 1 | `remociones_por_contenedor_retirado` | Remociones **completadas** ÷ retiros cerrados | remociones por retiro |
| 2 | `ciclos_grua_por_operacion` | Ciclos de grúa completados ÷ turnos cerrados | ciclos por turno cerrado |
| 3 | `distancia_total_recorrida` | Suma de la distancia de todos los ciclos (completados y abortados) | **posiciones** (A16) |
| 4 | `tiempo_promedio_camion_terminal_min` | Promedio creación → cierre de los turnos cerrados | min |
| 5 | `tiempo_promedio_retencion_min` | Promedio generación → resolución de las retenciones resueltas | min |
| 6 | `longitud_maxima_fila_espera` | Máximo de vehículos en espera (A15) | vehículos |
| 7 | `porcentaje_citas_cumplidas_en_ventana` | Citas con ventana cumplida ÷ citas con resultado, por la hora de su franja (`docs/citas.md` §4) | % |
| 8 | `retenciones_por_causa_y_resolucion` | Conteo de retenciones resueltas por `causa/resolución` | retenciones |

Qué cae en el periodo:

- Los ciclos, por su **inicio real**: el envío del `JOB` al controlador, guardado en `inicio_trabajo_grua` (migración 008). Antes se usaba la hora de planificación, que ocurre al autorizar en garita.
- Los turnos cerrados, por `cerrado_en`.
- Las retenciones, por `resuelta_en`.

El JSON guarda también `unidades` con el rótulo de cada métrica. La serie conocida de §16.2 da 1.0 · 1.25 · 6 min · 6 min · 3 · 80 % · {RT01/CORREGIR: 1, RT03/RECHAZAR: 1}; la verifica `pruebas/test_servicio_reportes.py`.

## 3. Decisiones [DEC]

| Ambigüedad | Decisión |
|---|---|
| **A15** · fuente de «vehículos en espera» | El campo `espera` del latido `EST` (`vehiculos_en_espera`), el mismo que muestra el sinóptico. La web guarda una muestra `fila_espera` en `telemetria` **cada vez que el valor cambia**. La métrica toma el máximo del periodo más la muestra vigente al empezar. El servidor no puede deducir la fila por su cuenta: un vehículo que espera aún no se identificó en garita. Por eso **el firmware debe llenar `espera`**; si siempre envía 0, la métrica da 0. En el simulador: `sensor espera N` |
| **A16** · unidad de la distancia | La trama `GRU` no trae distancia, así que el servidor la deriva del plan en **posiciones del patio lineal**. La zona de transferencia (el vehículo) es la posición 0 junto a P1 y P1…Pn siguen en orden. Un ciclo suma la aproximación en vacío desde donde terminó el anterior hasta su origen y, si se completó, el traslado cargado hasta su destino. Uno abortado suma solo la aproximación. Si el controlador llegara a informar pasos o mm, se agregaría como otra métrica, sin mezclar unidades |
| Remociones abortadas | No cuentan en la métrica 1: no movieron el contenedor. Sí suman distancia |
| Turnos «del periodo» en el CSV | Los creados antes del fin y no cerrados antes del inicio: incluye los que ya estaban en la terminal al empezar |

## 4. Exportación CSV (§16.3)

Cada reporte guardado se exporta en dos archivos. Ambos llevan `politica_asignacion` **en cada fila**, para poder juntar corridas de políticas distintas en la Fase 3:

- `GET /api/reportes/{id}/exportar?contenido=detalle`: una fila por turno del periodo. Columnas:
  - Identificación: `reporte`, `etiqueta`, `politica_asignacion`, `turno`, `vehiculo`, `transportista`, `contenedor`, `tipo_op`, `estado`.
  - Condiciones del ingreso: `canal`, `dentro_de_ventana`, `peso_entrada_g`, `peso_salida_g`, `posicion_patio`, `nivel`.
  - Grúa: `ciclos_grua`, `remociones`, `distancia_grua_posiciones`.
  - Retenciones: `retenciones`, con el formato `RT01:CORREGIR RT03:abierta`.
  - Tiempos: `creado_en_utc`, `cerrado_en_utc`, `tiempo_terminal_min`.
  - Cierre: `motivo_anulacion`.
- `GET /api/reportes/{id}/exportar?contenido=metricas`: una fila por métrica (la 8, una fila por grupo) con `valor` y `unidad`, además del rango y la política.

Las celdas de texto libre que empiezan con `= + - @` se anteponen con `'` para que una hoja de cálculo no las ejecute como fórmula. Los reportes guardados se listan con `GET /api/reportes` (los 20 más recientes) y se recuperan con `GET /api/reportes/{id}`.

## 5. Reporte de la corrida de evaluación (línea base de la Fase 3)

1. Antes de E01, anotar la hora de inicio y confirmar la política activa (`POLITICA_ASIGNACION=FASE1` en `portus.env`).
2. Al terminar los escenarios, ir a **Reportes** y generar con la etiqueta `evaluación AAAA-MM-DD` y el rango desde el inicio anotado hasta la hora actual.
3. Exportar los dos CSV y guardarlos junto con una captura de la tabla en `docs/evidencias/`. Son el entregable y la línea base contra la que se comparará la política optimizada de la Fase 3.
4. El reporte también queda guardado en la tabla `reporte` y se puede volver a abrir y exportar desde *Reportes guardados*.
