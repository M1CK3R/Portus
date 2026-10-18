# Tópicos MQTT y envoltorio de mensajes — PORTUS Fase 2

**Versión 1.0** · Referencia única del espacio de tópicos y del formato del mensaje (CODESTYLE P-1). Fuente: `SPECS.md` §5. Implementación: `puente/mensajes_mqtt.py`, `puente/publicador_eventos.py`.

---

## 1. Espacio de tópicos

El prefijo `portus` es obligatorio y **exacto** (SPECS §5.1): sin sufijos de grupo (`portus_g11` está prohibido) porque un suscriptor a `portus/#` no recibiría tópicos con otro primer nivel. El prefijo vive en `TOPIC_PREFIX` y todos los tópicos se construyen con `topico()`, nunca concatenando texto a mano (CODESTYLE A-6).

| Tópico | Dirección | Contenido | QoS | Retain |
|---|---|---|:-:|:-:|
| `portus/evt/garita` | Del controlador | Identificación de vehículo, resultado de validación y causa de rechazo | 1 | no |
| `portus/evt/pesaje` | Del controlador | Peso medido, muestras de la meseta, resultado de la comparación | 1 | no |
| `portus/evt/aguja` | Del controlador | Estado de la aguja desviadora | 1 | no |
| `portus/evt/transferencia` | Del controlador | Alineación, inicio, aborto y fin de la transferencia | 1 | no |
| `portus/evt/grua` | Del controlador | Cada paso del ciclo de grúa | 1 | no |
| `portus/evt/patio` | Del controlador | Cambio de estado de una posición, nivel y contenedor | 1 | no |
| `portus/evt/salida` | Del controlador | Identificación de vehículo y verificación de salida | 1 | no |
| `portus/evt/alarma` | Del controlador | Código de alarma, severidad y datos | 1 | no |
| `portus/evt/estado` | Del controlador | **Latido** con el estado general (periodo ≤ 5 s) | **0** | **sí** |
| `portus/cmd/solicitud` | Hacia el controlador | Comando remoto emitido desde la plataforma | 1 | no |
| `portus/cmd/respuesta` | Del controlador | ACK/NAK del comando con su causa | 1 | no |
| `portus/srv/turno` | Del servidor | Autorización AUT, trabajos JOB, cambios de estado, patio e inventario del turno (Etapa 5) | 1 | no |
| `portus/srv/retencion` | Del servidor | `retencion.abierta` / `retencion.resuelta`, avisos 5 y 6 al transportista (`notificacion.vehiculo_retenido`, `notificacion.retencion_resuelta`) y `parqueo.plaza` (plaza ocupada al retener; liberada al resolver sin ramal o tras el ACK de `AgujaLiberar`). Ver §7 | 1 | no |
| `portus/srv/patio` | Del servidor | `patio.estado`: posición bloqueada o liberada tras el ACK de `PosicionBloquear`/`PosicionLiberar`, o reserva liberada al anular un turno (§12.3) | 1 | no |
| `portus/srv/alarma` | Del servidor | `alarma.servidor` (AL01 del puente; AL09–AL14 de la web), `alarma.resumen` (`{"activas": n}` tras cada alta o reconocimiento) y `alarma.reconocida`. Ver §8 y `docs/alarmas.md` | 1 | no |
| `portus/srv/cita` | Del servidor | Avisos de la agenda y de la cadena documental: `notificacion.cita_cancelada`, `notificacion.cita_reprogramada`, `notificacion.levante_otorgado`, `notificacion.levante_retenido` (el levante habilita la cita, §11.1 regla 3), y `cita.vencida` (`cita`, `contenedor`, `fecha`, `inicio`, `fin`) cuando la tarea de vencimiento cierra una cita no atendida (`docs/citas.md`). Ver §9 | 1 | no |
| `portus/srv/enlace` | Del puente | Estado del enlace, saltos de secuencia, Last Will | 1 | **sí** |

## 2. Envoltorio del mensaje (SPECS §5.2)

Un único formato en todos los tópicos, con las claves obligatorias `id`, `ts`, `origen`, `tipo`, `seq` y `datos`:

```json
{
  "id": "6c51bdf1-ee85-52a2-8d28-027631c90485",
  "ts": "2026-09-20T14:03:22.418Z",
  "origen": "controlador",
  "tipo": "pesaje.medicion",
  "seq": 1042,
  "datos": { "veh": "V02", "peso_g": 38500, "muestras": 12, "meseta": true }
}
```

| Clave | Contenido |
|---|---|
| `id` | Identificador único del mensaje (ver §3). |
| `ts` | Marca de tiempo ISO 8601 en UTC con milisegundos y sufijo `Z` (CODESTYLE I-8). |
| `origen` | `controlador` (eventos C→S y RSP reales) · `puente` (diagnósticos y NAK sintéticos) · `servidor` (lógica web y AL01). |
| `tipo` | Tipo de evento (`garita.identificacion`, `pesaje.medicion`, `aguja.estado`, `transferencia.evento`, `grua.paso`, `patio.cambio`, `salida.verificacion`, `alarma.controlador`, `estado.latido`, `comando.solicitud`, `comando.respuesta`, `enlace.estado`, `enlace.salto_secuencia`, `alarma.servidor`). |
| `seq` | Número de secuencia serial; `null` cuando el mensaje no viene de una trama. |
| `datos` | Datos propios del evento; claves en `snake_case` con unidad (`peso_g`, `tol_pct`) (CODESTYLE P-3). |

**Comandos.** En `portus/cmd/solicitud`, `datos` incluye `cmd_id` (correlación con la respuesta), `nombre` (uno de los 13 del catálogo), `parametros` (objeto) y `usuario` que lo emitió:

```json
{
  "id": "…", "ts": "…", "origen": "servidor", "tipo": "comando.solicitud", "seq": null,
  "datos": { "cmd_id": "9f8b…", "nombre": "AbrirTalanquera", "parametros": {}, "usuario": "terminal" }
}
```

**Respuestas.** `portus/cmd/respuesta` repite el `cmd_id` con `estado: "ACK" | "NAK"`, `causa` (nula si ACK), `sintetica` (true en el NAK `SIN_RESPUESTA` generado por el puente) y `tardia: true` cuando la respuesta real llegó después del NAK sintético.

## 3. Identificadores y deduplicación (SPECS §5.5)

QoS 1 entrega *al menos una vez*: el broker puede duplicar, y la reconciliación tras `SYN` reenvía eventos ya publicados. Por eso:

- **Eventos del controlador:** `id = UUIDv5(NAMESPACE_PORTUS, "controlador:{seq}:{tipo}")` — **determinista**. Una retransmisión del mismo evento produce el mismo `id` y la deduplicación de cada consumidor lo elimina.
- **Respuestas de comando:** `id = UUIDv5(NAMESPACE_PORTUS, "rsp:{cmd_id}:{estado}:{causa}")` — el reintento idempotente del mismo comando no duplica la respuesta.
- **NAK sintético:** `id` derivado del `cmd_id` y la causa `SIN_RESPUESTA`.
- **Last Will del puente:** `id` determinista `UUIDv5(NAMESPACE_PORTUS, "puente:caido")`; como el payload del Last Will es estático, su `ts` corresponde al momento de conexión (limitación documentada).
- **Otros mensajes del puente** (estado del enlace, salto de secuencia, AL01): `UUIDv4` aleatorio.
- Todo consumidor (persistencia, lógica, bot) **deduplica por `id`**: la persistencia usa `INSERT OR IGNORE` sobre la clave primaria `evento.id`.

`NAMESPACE_PORTUS` es un UUID fijo del proyecto (`5e0f2c58-6f9b-4d1e-9a77-2b1c8d3a9f01`) compartido por todas las piezas que generen identificadores deterministas.

## 4. Last Will y estado del puente (SPECS §5.5)

- El cliente `portus-puente` registra su Last Will en `portus/srv/enlace` con `datos: {"puente": "caido", "enlace": "perdido"}`, QoS 1 y **retain**.
- Al conectar, el puente publica su estado con `datos: {"puente": "activo", "enlace": "activo"|"perdido", "ultimo_latido_ts": …, "tramas_validas": …, "tramas_invalidas": …, "bytes_descartados": …, "saltos_secuencia": …, "latidos_recibidos": …, "comandos_sin_respuesta": …}` con retain, para que un navegador nuevo conozca el último estado sin consultar la base de datos.

## 5. Consumidores por tópico (SPECS §5.7)

| Consumidor | Qué escucha | Qué hace |
|---|---|---|
| Sinóptico (navegador, MQTT sobre WebSocket 9001) | `portus/evt/#`, `portus/srv/#`, `portus/cmd/respuesta` | Actualiza la vista sin consultar la base de datos (prohibido el polling) |
| Persistencia (puente, suscripción interna a `portus/#`) | `portus/#` | Guarda eventos, telemetría y comandos con deduplicación por `id` |
| Lógica de negocio (Etapa 5) | Eventos del controlador | Máquina de estados del turno, retenciones y alarmas |
| Servicio de mensajería (`portus-msg`, Etapa 10) | `portus/srv/turno`, `portus/srv/retencion`, `portus/srv/cita` | Toma los `notificacion.*`, relee la fila por su id y la entrega por Telegram solo al transportista propietario (§9) |
| Vigilante de enlace (puente) | Latido `EST` (recepción serial directa) | Declara AL01 tras 3 periodos sin latido |

> Nota de diseño: en la Etapa 3 la persistencia corre dentro del puente y persiste todo lo que él publica más lo recibido del broker. Cuando la web y el bot publiquen sus propios `srv/*` (Etapas 5+), o bien pasan sus mensajes por los mismos tópicos (la persistencia los recibe por la suscripción `portus/#`) o se extrae el consumidor a un servicio propio; el formato no cambia.

## 6. Seguridad del broker (SPECS §5.5, CODESTYLE S-4)

- Listener TCP 1883 **y** listener MQTT sobre WebSocket 9001 (`config/mosquitto.conf`).
- Autenticación por usuario/servicio con `mosquitto_passwd`; `allow_anonymous false`.
- ACL por servicio en `config/acl_portus`: el puente es el único `readwrite portus/#`; la web escribe `cmd/solicitud` y `srv/#`; el bot solo lee los `srv/*` de notificaciones; **el navegador es solo lectura**.

## 7. Retenciones y parqueo (SPECS §10, Etapa 8)

`datos` de `retencion.abierta` y `retencion.resuelta` en `portus/srv/retencion`:

```json
{ "retencion": 7, "turno": 12, "causa": "RT01", "estacion": "pesaje_entrada", "plaza": 1,
  "estado": "abierta", "peso_declarado_g": 38500, "peso_medido_g": 44050,
  "resolucion": null, "motivo": null, "creada_en": "2026-09-20T14:03:22.418Z", "resuelta_en": null }
```

- `estacion` ∈ `garita`, `pesaje_entrada` (el vehículo entra al ramal: sale `AgujaParqueo`), `pesaje_salida`, `salida` (plaza lógica, A3 [DEC]). `plaza` es `null` si el parqueo estaba lleno (AL11).
- RT01 aclarada o corregida en un turno de canal rojo **no** libera la plaza: abre de inmediato una `retencion.abierta` RT03 con la misma plaza (§9.2).
- `parqueo.plaza`: `{ "plaza": 1, "turno": 12 }` al ocupar y `{ "plaza": 1, "turno": null }` al liberar.
- `notificacion.vehiculo_retenido`: `vehiculo`, `contenedor`, `causa` y, en RT01/RT02, `peso_declarado_g`, `peso_medido_g`, `diferencia_g`, `diferencia_pct` (§10.7). `notificacion.retencion_resuelta`: `vehiculo`, `contenedor`, `resolucion`, `nuevo_peso_declarado_g` (Corregir) o `motivo` (Rechazar). Ambos llevan `transportista`.
- Rechazar anula el turno: además sale `notificacion.turno_anulado` con `resultado: "anulado"` y `motivo` en `portus/srv/turno` (aviso 9).
- AL12 en `portus/srv/alarma` (`tipo: alarma.servidor`): `{ "codigo": "AL12", "severidad": "MEDIA", "retencion": 7, "turno": 12, "causa": "RT01", "plaza": 1, "creada_en": "…", "limite_min": 30 }`. Se emite **una vez por retención** (tabla `alerta_emitida`); si varias se exceden, la alarma activa acumula `repeticiones` (§13.4 [DEC]).

## 8. Alarmas (SPECS §13, Etapa 9)

Detalle completo en `docs/alarmas.md`. Lo que circula por MQTT:

| Tipo | Tópico | `datos` |
|---|---|---|
| `alarma.controlador` | `portus/evt/alarma` | `codigo`, `severidad` y datos del `ALM`; la web lo persiste con la severidad del **catálogo** |
| `alarma.servidor` | `portus/srv/alarma` | `codigo`, `severidad`, `descripcion`, `alarma` (id) y datos propios. El de AL01 lo publica el puente y la web lo persiste; los demás los publica la web tras persistirlos |
| `alarma.resumen` | `portus/srv/alarma` | `{"activas": n}`: cantidad exacta de alarmas activas (filas, no repeticiones) para el sinóptico |
| `alarma.reconocida` | `portus/srv/alarma` | `alarma` (id; 0 en el reconocimiento en lote), `codigo`, `usuario` |

AL14 (`alarma.servidor`) lleva `cmd_id`, `nombre`, `causa`, `texto_causa` (§6.5) y `sintetica` (true si fue el NAK `SIN_RESPUESTA` del puente).

## 9. Notificaciones al transportista (SPECS §15.3, Etapa 10)

La web **persiste** cada aviso en `notificacion` y luego publica `notificacion.<tipo>` con el id de la fila (`web/servicios/notificador.py`). El bot relee la fila por ese id, así que el mensaje MQTT solo dispara la entrega: si el bot o internet están caídos, el aviso queda pendiente en la BD y sale después (§15.4). Todos los `datos` llevan `notificacion` (id), `transportista` (propietario) y los campos del aviso:

| # §15.3 | `tipo` | Tópico | Campos propios de `datos` |
|---|---|---|---|
| 1 | `notificacion.levante_otorgado` | `portus/srv/cita` | `manifiesto`, `contenedor`, `canal` (`verde`/`rojo`) |
| 2 | `notificacion.levante_retenido` | `portus/srv/cita` | `manifiesto`, `contenedor`, `motivo` |
| 3 | `cita_asignada` | — | Es la confirmación de `/cita`: el bot la guarda ya entregada y no se publica |
| 4 | `recordatorio_cita` | — | La genera el propio bot 1 h antes (§11.5): `cita`, `contenedor`, `fecha`, `inicio`, `fin` |
| 5 | `notificacion.vehiculo_retenido` | `portus/srv/retencion` | ver §7 |
| 6 | `notificacion.retencion_resuelta` | `portus/srv/retencion` | ver §7 |
| 7 | `notificacion.cita_cancelada` / `notificacion.cita_reprogramada` | `portus/srv/cita` | `cita`, `contenedor`, `fecha`, `inicio`, `fin` (la ventana nueva si se reprogramó) |
| 8 | `notificacion.turno_completado` | `portus/srv/turno` | `turno`, `vehiculo`, `contenedor`, `tipo_op`, `resultado: "completado"`, `tiempo_total_s` |
| 9 | `notificacion.turno_anulado` | `portus/srv/turno` | `turno`, `vehiculo`, `contenedor`, `tipo_op`, `resultado: "anulado"`, `motivo` |

- Idempotencia (P-4): el bot descarta un envoltorio con `id` ya visto (reentrega de QoS 1), no encola dos veces la misma fila y omite la que ya está `entregado`.
- `portus-msg` solo **lee** (ACL); nunca publica.
