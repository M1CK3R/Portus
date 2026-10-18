# PORTUS Fase 2 · Alarmas (SPECS §13, Etapa 9)

Referencia única de cómo nace, se guarda, se muestra y se reconoce cada alarma. El catálogo vive en código en `web/modelos/alarma.py` y, para el firmware, en `docs/constantes_protocolo.json` (`alarmas`); `pruebas/test_paridad_constantes.py` verifica que coincidan.

## 1. Catálogo (SPECS §13.1)

| Código | Descripción | Severidad | Origen | Cómo llega a la plataforma |
|---|---|---|---|---|
| AL01 | Enlace con el controlador perdido | Crítica | Servidor (vigilante de latido del puente) | `alarma.servidor` del puente en `portus/srv/alarma`; la web la persiste |
| AL02 | Paro de emergencia accionado | Crítica | Controlador | Trama `ALM` → `alarma.controlador` en `portus/evt/alarma` |
| AL03 | Pérdida de referencia de posición de la grúa | Crítica | Controlador | `ALM` |
| AL04 | Pérdida de carga durante el traslado | Crítica | Controlador | `ALM` |
| AL05 | Agarre de contenedor no confirmado | Alta | Controlador | `ALM` |
| AL06 | Trabajo de grúa abortado | Alta | Controlador | `ALM` |
| AL07 | Inconsistencia entre altura física e inventario | Alta | Controlador | `ALM` |
| AL08 | Movimiento del vehículo durante la transferencia | Alta | Controlador | `ALM` |
| AL09 | Pesaje fuera de tolerancia | Media | Servidor | Revalidación del `PES` (`servicio_pesajes`) |
| AL10 | Vehículo incorrecto en la salida | Media | Servidor | `SAL` sin turno en `EnSalida` (`servicio_salida`) |
| AL11 | Parqueo de retención lleno | Media | Servidor | Garita con riesgo y 3/3 plazas, o retención sin plaza |
| AL12 | Retención que supera treinta minutos | Media | Servidor | Tarea periódica cada 15 s (`vigilante_retenciones`) |
| AL13 | Permanencia de contenedor superior a dos horas | Baja | Servidor | Tarea periódica cada 60 s (`vigilante_permanencia`) |
| AL14 | Comando remoto rechazado por el controlador | Baja | Servidor | Todo `NAK` en `portus/cmd/respuesta`, también el sintético `SIN_RESPUESTA` |

La **severidad y la descripción salen siempre del catálogo**: si una trama `ALM` trae otra severidad, se registra la del catálogo y queda un `WARNING` en el log. Un `ALM` con código fuera de AL01–AL14 se descarta con `WARNING` (P-5).

## 2. Un solo punto de alta

Todas pasan por `web/servicios/emisor_alarmas.py` (`EmisorAlarmas.emitir`), que:

1. Toma severidad, descripción y origen del catálogo.
2. Persiste en la tabla `alarma` con la deduplicación del §4.
3. Publica en `portus/srv/alarma`:
   - `alarma.servidor` con `codigo`, `severidad`, `descripcion`, `alarma` (id) y los datos propios, **solo** si la alarma no circuló ya por MQTT (las de `ALM` y AL01 ya lo hicieron desde su origen).
   - `alarma.resumen` con `{"activas": n}`: el sinóptico muestra ese número exacto en vez de contar mensajes.
4. Al reconocer, publica `alarma.reconocida` (`alarma`, `codigo`, `usuario`) y un nuevo `alarma.resumen`.

## 3. Ciclo de vida (SPECS §13.2, §13.3)

- Una alarma **no desaparece sola** al cesar la condición: queda `activa` hasta que un usuario **TERMINAL** la reconoce (`@requiere_rol(ACCION_RECONOCER_ALARMA)`; cualquier otro rol recibe 403 y queda en la auditoría).
- **AL01 sigue activa aunque el enlace se restablezca** (E14: «AL01 con su reconocimiento»).
- Reconocer admite comentario opcional y registra quién y cuándo; reconocer una ya reconocida → 409.
- **Reconocer todas** solo afecta a BAJA y MEDIA; CRITICA y ALTA se reconocen una por una.
- `AlarmaSilenciar` (comando 13) acalla la sirena del controlador **sin** reconocer nada; su ACK se muestra en la pestaña.

## 4. Deduplicación de alarmas repetidas [DEC §13.4]

**Decisión:** si ya existe una alarma **activa** con el mismo `codigo` y `origen`, una nueva ocurrencia **no crea otra fila**: incrementa `repeticiones`, actualiza `ts` y reemplaza `datos` por los de la última ocurrencia. Una vez reconocida, la siguiente ocurrencia abre una fila nueva.

**Por qué:** la pestaña Alarmas debe servir para decidir, no para desplazarse; una grúa que aborta cinco veces seguidas es **una** situación que atender (AL06 ×5), no cinco. El detalle de cada ocurrencia no se pierde: los eventos del controlador quedan en la tabla `evento` del puente, cada comando rechazado en `comando` y cada retención en `retencion`.

**Consecuencias:**

- AL12 y AL13 se emiten **una sola vez por objeto** vigilado (una retención, una estadía de un contenedor), marcado en `alerta_emitida`; si varios objetos se exceden a la vez, la AL12/AL13 activa acumula repeticiones y guarda el último.
- El contador del sinóptico cuenta **filas activas**, no repeticiones.

## 5. Alarmas perdidas mientras la web estaba caída (E14)

El puente persiste en `evento` todo lo que circula por `portus/#`. Al arrancar, la web ejecuta `NucleoLogica.reconciliar_alarmas` sobre las últimas 24 h de `alarma.controlador` y `alarma.servidor` y las reinyecta en el consumidor. La deduplicación por `id` (P-4) descarta las que ya había atendido; así, la AL01 retroactiva que publica el puente al volver (A14) llega a la pestaña aunque la web haya arrancado después.
