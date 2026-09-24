# Protocolo serial PORTUS — Fase 2

**Versión 1.0** · Referencia única del protocolo (CODESTYLE P-1). Cualquier cambio al protocolo actualiza este documento **en el mismo commit**. Constantes compartidas con el firmware: `docs/constantes_protocolo.json` (verificadas por `pruebas/test_paridad_constantes.py`).

Fuente: `SPECS.md` §4 (enlace serial), §3.4 (vigilancia), §6.4 (flujo del comando). Implementación lado servidor: `puente/`.

---

## 1. Trama

Formato de una línea ASCII legible con un monitor serial, resincronizable en el siguiente delimitador (SPECS §4.2):

```
^ SEQ | TIPO | CAMPOS # CRC \n
```

| Elemento | Descripción |
|---|---|
| `^` | Delimitador de inicio. Al verlo, el receptor descarta lo acumulado y reinicia el análisis. |
| `SEQ` | Entero decimal sin signo de 32 bits. Controlador→servidor: secuencia creciente de eventos. Servidor→controlador: identificador del comando (se repite en la respuesta). |
| `TIPO` | Código de 3 a 4 letras (ver §3). |
| `CAMPOS` | Pares `clave=valor` separados por `,`. Los caracteres reservados `^ \| # , \n \r %` se escapan como `%HH`. Puede quedar vacío (`^57|PING|#…`). |
| `#` | Separador antes del CRC. |
| `CRC` | CRC-16/CCITT-FALSE (polinomio `0x1021`, valor inicial `0xFFFF`, sin reflexión ni XOR final) sobre **los bytes entre `^` y `#` exclusivos**. 4 dígitos hexadecimales en mayúscula. |
| `\n` | Delimitador de fin. |

**Verificación de los ejemplos del SPECS** (todos reproducidos por `pruebas/test_protocolo_crc.py`):

```
^1042|PES|veh=V02,g=38500,n=12,meseta=1#58B2            evento de pesaje (C→S)
^2210|EST|modo=NORMAL,grua=REPOSO,link=1#A60E           latido de estado (C→S)
^57|CMD|nombre=AbrirTalanquera#9F98                     comando (S→C)
^57|RSP|estado=ACK#C4D8                                 comando aceptado
^58|RSP|estado=NAK,causa=VEH_BAJO_TALANQUERA#3B92       comando rechazado con causa
```

Vector estándar del CRC: `123456789` → `29B1`.

**Nota de diseño [DEC].** El SPECS §4.2 indica «TIPO: código de 3 letras», pero §4.3 define `PING` con 4 letras. El analizador acepta de 3 a 4 letras mayúsculas y rechaza cualquier otro TIPO.

## 2. Reglas de recepción (lado servidor)

Implementadas en `puente/protocolo.AnalizadorTramas` (analizador incremental no bloqueante):

1. Resincronización: cualquier byte antes de `^` se descarta y se cuenta (`bytes_sin_inicio`).
2. Trama abandonada a medio camino: si llega un nuevo `^` antes del `\n` de la trama en curso, los bytes ya acumulados se descartan y se cuentan (`trama_incompleta`), igual que cualquier otra trama inválida.
3. Búfer acotado a **256 bytes**; si se desborda sin `\n` se descarta y se espera el siguiente `^` (`trama_excede_longitud`).
4. Trama con CRC inválido, longitud fuera de rango (13–256 bytes), `SEQ` no numérica o fuera de 32 bits, `TIPO` desconocido o campos mal formados → **se descarta y se incrementa el contador de errores** (visible en `portus/srv/enlace`, campo `tramas_invalidas`).
5. Campos duplicados: la última aparición gana.
6. Escape: `%` → `%25`, `^` → `%5E`, `|` → `%7C`, `#` → `%23`, `,` → `%2C`, `\n` → `%0A`, `\r` → `%0D`. Un `%` sin dos dígitos hexadecimales válidos invalida la trama.

> Los cuatro motivos posibles de `TramaDescartada` (`bytes_sin_inicio`, `trama_incompleta`, `trama_excede_longitud`, `trama_invalida`) incrementan siempre el contador `tramas_invalidas`; `bytes_sin_inicio` además suma a `bytes_descartados` (`puente/nucleo_puente._registrar_descarte`). En una misma resincronización solo se produce uno de los tres primeros, nunca varios a la vez.

## 3. Tipos de mensaje

| Tipo | Dirección | Uso | Tópico MQTT asociado |
|---|---|---|---|
| `GAR` | C→S | Identificación de vehículo, resultado de validación, causa de rechazo | `portus/evt/garita` |
| `PES` | C→S | Peso medido, muestras de la meseta, resultado de la comparación | `portus/evt/pesaje` |
| `AGU` | C→S | Estado de la aguja (recta / parqueo / liberando) | `portus/evt/aguja` |
| `TRF` | C→S | Alineación, inicio, aborto, fin de transferencia | `portus/evt/transferencia` |
| `GRU` | C→S | Cada paso del ciclo de grúa: posición, agarre, resultado | `portus/evt/grua` |
| `PAT` | C→S | Cambio de estado de una posición: nivel y contenedor | `portus/evt/patio` |
| `SAL` | C→S | Identificación de vehículo y resultado de verificación de salida | `portus/evt/salida` |
| `ALM` | C→S | Código de alarma, severidad, datos | `portus/evt/alarma` |
| `EST` | C→S | Latido con estado general (periodo ≤ 5 s) | `portus/evt/estado` |
| `CMD` | S→C | Comando remoto (los 13 del SPECS §6.1) | ← `portus/cmd/solicitud` |
| `RSP` | C→S | Aceptación (`ACK`) o rechazo (`NAK`) con causa | `portus/cmd/respuesta` |
| `AUT` | S→C | Resultado de la validación de garita con los datos del turno o la causa (SPECS §4.4; habilitado en la Etapa 5) | ← `portus/srv/turno` (tipo `turno.autorizacion`) |
| `JOB` | S→C | Trabajo de grúa: tipo, origen, destino, nivel (SPECS §4.4; habilitado en la Etapa 5) | ← `portus/srv/turno` (tipo `turno.trabajo`) |
| `PING` | S→C | Vigilancia del servidor hacia el controlador (SPECS §3.4, A13) | — (interno) |
| `SYN` | S→C | Pide reenviar desde un `SEQ` y/o volcar estado actual | — (interno) |

### 3.1 Campos por tipo de evento [PROP]

El SPECS §5.2 fija la conversión de `PES` (`veh` → `veh`, `g` → `peso_g`, `n` → `muestras`, `meseta=1` → `true`). El resto se propone aquí y la tabla vive en `puente/mensajes_mqtt.CAMPOS_JSON_POR_TIPO`; una clave de trama no listada pasa al JSON con su nombre serial. Si el firmware (Etapa 2) define otros campos, se actualiza la tabla y este documento en el mismo commit.

| Tipo | Campos serial → JSON |
|---|---|
| `GAR` | `veh`→`veh` (texto), `res`→`resultado`, `causa`→`causa` |
| `PES` | `veh`→`veh`, `g`→`peso_g` (entero), `n`→`muestras` (entero), `meseta`→`meseta` (bool) |
| `AGU` | `estado`→`estado` |
| `TRF` | `evento`→`evento`, `veh`→`veh` |
| `GRU` | `paso`→`paso`, `pos`→`posicion`, `nivel`→`nivel` (entero), `cont`→`contenedor`, `res`→`resultado` |
| `PAT` | `pos`→`posicion`, `nivel`→`nivel` (entero), `cont`→`contenedor`, `estado`→`estado` |
| `SAL` | `veh`→`veh`, `res`→`resultado`, `causa`→`causa`. Valores de `res` [DEC]: `DETECTADO` (vehículo identificado en el punto de salida; el servidor compara con el turno en `EnSalida`) y `CONFIRMADO` (el controlador confirma que el vehículo pasó la puerta; cierra el turno, §8.6) |
| `ALM` | `cod`→`codigo`, `sev`→`severidad` |
| `EST` | `modo`→`modo`, `grua`→`grua`, `aguja`→`aguja`, `cola`→`trabajos_en_cola` (entero), `espera`→`vehiculos_en_espera` (entero), `err`→`errores_trama` (entero), `dif`→`eventos_diferidos` (entero), `link`→`enlace` (bool) |
| `RSP` | `estado`→`estado` (`ACK`\|`NAK`), `causa`→`causa` |

Los enteros se convierten solo si el texto es numérico; si no, el valor viaja como texto y la anomalía queda en el registro (CODESTYLE D-10).

Uso en las métricas (docs/metricas.md): `EST.espera` es la **fuente de la fila de espera** (A15, métrica 6) y el firmware debe informarla con el conteo real de la zona de espera. `GRU` no lleva distancia: la distancia de traslación (métrica 3) la deriva el servidor en posiciones del patio (A16).

#### 3.1.1 Vocabulario de valores [DEC]

Valores que el sinóptico (SPECS §14.1) traduce a sus estados; viven en `web/interfaz/estatico/js/sinoptico_textos.mjs`. Un valor fuera de la lista se muestra tal cual, para que la discrepancia con el firmware se vea en pantalla. El firmware (Etapa 2) debe emitir exactamente estos:

| Campo | Valores |
|---|---|
| `EST.modo` | `NORMAL` · `MANTENIMIENTO` · `DEGRADADO` |
| `EST.grua`, `GRU.paso` | `REPOSO` · `REFERENCIANDO` · `DESPLAZANDO` · `IZANDO` · `TRASLADANDO` · `DEPOSITANDO` · `SUSPENDIDA` · `FALLA` (`GRU.paso` también admite `FIN`, con `res` = `OK` o `ABORTADO`) |
| `EST.aguja`, `AGU.estado` | `RECTA` · `PARQUEO` · `LIBERANDO` |
| `TRF.evento` | `POSICIONANDO` · `ALINEADO` · `INICIO` · `ABORTO` · `FIN` |
| `GAR.res` | `ESPERA_AUT` (vehículo presente, validando) |
| `PAT.estado` | `OCUPADA` · `LIBRE` |

La talanquera y la puerta de salida no tienen evento propio: el sinóptico las deriva de `AUT AUTORIZADO` (abre), del `PES` siguiente (cerró), de `SAL CONFIRMADO` (puerta cerrada) y del `ACK` de `AbrirTalanquera`, `CerrarTalanquera` y `AbrirPuertaSalida`. El estado «en movimiento» exige que el firmware lo reporte (p. ej. campos `tal`/`pue` en `EST`).

#### 3.1.2 Parámetros de `CMD` [DEC]

`portus/cmd/solicitud` lleva `parametros`; el puente los agrega a la trama después de `nombre` (`^SEQ|CMD|nombre=PosicionBloquear,pos=P3#CRC`):

| Comando | Parámetro | Valores |
|---|---|---|
| `PosicionBloquear`, `PosicionLiberar` | `pos` | ID de la posición (`P1`…`P4`) |
| `AgujaLiberar` | `plaza` | `1` · `2` · `3`; sin plaza el controlador responde `NAK PARQUEO_VACIO` |
| `ModoMantenimiento` | `valor` | `ACTIVAR` · `DESACTIVAR` |
| Resto | — | Sin parámetros |

La BD solo refleja un bloqueo de posición o la liberación de una plaza cuando llega el `ACK`: el controlador es quien evalúa la condición de rechazo (SPECS §6.1, §23.3).

### 3.2 Campos de `AUT` y `JOB` [PROP, habilitado en la Etapa 5]

La lógica del servidor publica en `portus/srv/turno` y el puente convierte el mensaje en trama serial (`puente/nucleo_puente._reenviar_aut`/`._reenviar_job`). El envoltorio JSON usa las claves del SPECS §4.4; la trama serial usa claves cortas [DEC]:

| `AUT` JSON → serial | Contenido |
|---|---|
| `resultado`→`res` | `AUTORIZADO` \| `RECHAZADO` |
| `turno`, `veh`, `tipo_op`→`tipo`, `peso_decl_g`→`decl`, `tol_pct`→`tol`, `canal`, `pos_asignada`→`pos`, `nivel` | Datos del turno; solo van en `AUTORIZADO` |
| `causa` | Código de §9.4; solo va en `RECHAZADO` (el controlador lo muestra en la pantalla de garita) |

Ejemplos:

```
^…|AUT|res=AUTORIZADO,turno=1,veh=V01,tipo=DEPOSITO,decl=38500,tol=5,canal=verde,pos=P1,nivel=1#CRC
^…|AUT|res=RECHAZADO,causa=PARQUEO_LLENO#CRC
^…|JOB|id=1,tipo=DEPOSITO,origen=VEH,destino=P1,nivel=1,cont=C01,turno=1#CRC
```

El marcador `VEH` en `JOB.origen/destino` designa al vehículo [DEC]. El puente deduplica por el `id` del mensaje (§5.5): una reentrega de QoS 1 no reabre la talanquera.

> La `SEQ` de `AUT`/`JOB` sale del mismo contador S→C de `CMD` (§4.2).

## 4. Secuencia

### 4.1 Controlador → servidor

- `SEQ` creciente módulo 2³², empieza en cualquier valor.
- El puente compara cada `SEQ` con la anterior (`puente/secuencia.RastreadorSecuencia`):
  - `SEQ == SEQ_anterior + 1` → nueva.
  - Salto hacia adelante de `k` → **evento de diagnóstico** en `portus/srv/enlace` (tipo `enlace.salto_secuencia`, con `seq_esperada`, `seq_recibida` y `faltantes`) + **solicitud `SYN`** con `desde=SEQ_anterior+1` (SPECS §4.2, prueba P02).
  - `SEQ` repetida o hacia atrás → se publica igualmente (la deduplicación por `id` protege a los consumidores) y se registra en el registro.
- Los eventos reenviados por `SYN` conservan el mismo `id` MQTT determinista (ver `docs/topicos_mqtt.md` §3), por lo que ningún consumidor los procesa dos veces (SPECS §5.5).

### 4.2 Servidor → controlador

- `SEQ` creciente módulo 2³² compartida por `CMD`, `AUT`, `JOB`, `PING` y `SYN` (una trama, un número).
- El valor inicial deriva de los segundos desde época módulo 2³¹, de modo que tras un reinicio del puente no se reutilizan secuencias ya atendidas por el controlador (idempotencia §4.5).
- `RSP` repite la `SEQ` del comando que confirma.

### 4.3 `PING` y `SYN`

```
^…|PING|#CRC                    vigilancia: el puente la emite cada PERIODO_PING_S (2–5 s; por omisión 3 s)
^…|SYN|desde=1043#CRC           retransmitir los eventos con SEQ >= 1043
^…|SYN|estado=1#CRC             volcar el estado actual (EST)
^…|SYN|desde=1043,estado=1#CRC  ambos
```

El puente envía `SYN estado=1` al abrir el enlace (volcado inicial, SPECS §19.3) y `SYN desde=…,estado=1` al recuperar el enlace tras una pérdida (reconciliación, SPECS §3.3). El controlador no responde `PING` ni `SYN` con `RSP`: responde reenviando eventos o actualizando su estado.

## 5. Comandos: flujo y tiempos (SPECS §6.4, §4.5)

```
portus/cmd/solicitud  → puente → trama CMD (SEQ asignada) → controlador
controlador           → RSP con la misma SEQ (ACK | NAK,causa) → puente
puente                → portus/cmd/respuesta {cmd_id, estado, causa}
```

1. **Correlación:** cada solicitud trae un `cmd_id` único; el puente lo enlaza con la `SEQ` serial asignada. La respuesta repite el `cmd_id` (CODESTYLE D-8).
2. **Timeout:** 2 s desde el envío (SPECS §4.5). Sin `RSP` → el puente publica un **NAK sintético** con `causa=SIN_RESPUESTA`, `origen=puente`, `sintetica=true` y lo trata como comando fallido.
3. **Respuesta tardía:** si la `RSP` real llega después del NAK sintético, se publica con `tardia=true` (no se oculta: el servidor decide qué hacer con ella).
4. **Idempotencia:** si el servidor reenvía el mismo `cmd_id` (reintento), el puente **reutiliza la misma `SEQ`**, de modo que el controlador responde con el mismo resultado sin volver a actuar (SPECS §4.5). Un `cmd_id` duplicado mientras está en vuelo se ignora (QoS 1 puede duplicar la entrega).
5. **Comando desconocido** (fuera de los 13 del catálogo): NAK inmediato `COMANDO_DESCONOCIDO` sin tocar el serial [DEC; causa añadida a la lista PROP de §6.5].
6. **Causas de rechazo** (SPECS §6.5): `VEH_BAJO_TALANQUERA`, `VEH_BAJO_PUERTA`, `VEH_SOBRE_AGUJA`, `PARQUEO_VACIO`, `GRUA_CON_CARGA`, `GRUA_EN_TRABAJO`, `GRUA_EN_FALLA`, `POS_EN_TRABAJO`, `INCONSISTENCIA_PERSISTE`, `VEH_EN_TRANSFERENCIA`, `SIN_RESPUESTA` (generada por el puente).
7. **AL14:** el servidor genera AL14 con la causa y su texto legible ante **todo** NAK, incluido el sintético `SIN_RESPUESTA` (comando fallido, SPECS §4.5); ver `docs/alarmas.md`.

### 5.1 Enclavamientos que debe aplicar el firmware (SPECS §6.1) [referencia]

`herramientas/enclavamientos_simulados.py` implementa esta tabla para el simulador y es la **referencia del firmware** (Etapa 2): con la condición presente se responde `NAK` con la causa y **no se actúa**; sin ella, `ACK` y el efecto. Un `CMD` con `SEQ` repetida recibe la misma respuesta y no vuelve a actuar. `pruebas/test_comandos_etapa9.py` recorre los 13 comandos con y sin su condición.

| Comando | Rechazo (causa) | Efecto con ACK |
|---|---|---|
| `AbrirTalanquera` / `CerrarTalanquera` | vehículo bajo la talanquera (`VEH_BAJO_TALANQUERA`) | abre / cierra |
| `AbrirPuertaSalida` | vehículo bajo la puerta (`VEH_BAJO_PUERTA`) | abre |
| `AgujaRecta` / `AgujaParqueo` | vehículo sobre la aguja (`VEH_SOBRE_AGUJA`) | aguja recta / hacia el parqueo |
| `AgujaLiberar` (`plaza`) | vehículo sobre la aguja (`VEH_SOBRE_AGUJA`) o parqueo vacío (`PARQUEO_VACIO`) | aguja de liberación |
| `GruaReferenciar` | carga adherida (`GRUA_CON_CARGA`) o trabajo en ejecución (`GRUA_EN_TRABAJO`) | referenciado |
| `GruaSuspender` | **nunca** | termina el movimiento en curso y no toma trabajos |
| `GruaReanudar` | falla sin rearme (`GRUA_EN_FALLA`) | vuelve a tomar trabajos |
| `PosicionBloquear` (`pos`) | origen o destino del trabajo en ejecución (`POS_EN_TRABAJO`) | posición bloqueada |
| `PosicionLiberar` (`pos`) | la inconsistencia física persiste (`INCONSISTENCIA_PERSISTE`) | posición liberada |
| `ModoMantenimiento` (`valor`) | trabajo en ejecución (`GRUA_EN_TRABAJO`) o vehículo en transferencia (`VEH_EN_TRANSFERENCIA`) | activa/desactiva; en mantenimiento no se admiten trabajos de turnos pero sí `GruaReferenciar` (§6.2 regla 4) |
| `AlarmaSilenciar` | **nunca** | silencia la sirena sin reconocer alarmas |

El latido `EST` refleja el efecto: `grua=SUSPENDIDA|REPOSO|FALLA` y `modo=MANTENIMIENTO`. El servidor usa ese latido para la disponibilidad de §6.3 (Reanudar solo con grúa suspendida; Referenciar solo en reposo o suspendida) y responde **409 `COMANDO_NO_DISPONIBLE`** sin enviar el comando; sin latido todavía, decide el controlador.

En la consola del simulador (`--interactivo`), `sensor NOMBRE VALOR` fija la condición física (`talanquera|puerta|aguja|transferencia|carga|falla 1/0`, `parqueo N`, `trabajo P3|0`, `inconsistencia P2|0`) y `estado` la muestra.

## 6. Vigilancia del latido (SPECS §5.4, §3.4)

- El latido `EST` viaja por `portus/evt/estado` con periodo ≤ 5 s.
- Tres periodos consecutivos sin latido (umbral por omisión 15 s, `PERIODO_LATIDO_S × PERIODOS_SIN_LATIDO`) → el puente declara el enlace perdido, publica **AL01** (crítica, origen `servidor`) en `portus/srv/alarma` y el estado `enlace=perdido` en `portus/srv/enlace`.
- AL01 no se retira sola: permanece activa hasta que TERMINAL la reconoce (SPECS §13.2, E14).
- Al llegar un latido tras la pérdida, el puente publica `enlace=activo` y envía `SYN desde=…,estado=1` para pedir la reconciliación.
- **AL01 retroactiva (A14):** al arrancar, el puente compara el último latido guardado en `estado_enlace` con la hora de arranque; si el hueco supera el umbral, registra AL01 con `retroactiva=true`, `desde` y `hasta`.
- Emisor `PING` hacia el controlador cada `PERIODO_PING_S` (por omisión 3 s): mantiene vivo su vigilante (SPECS §3.4, A13).

## 7. Parámetros de configuración

Todos en `config/portus.env` (ver `config/portus.env.ejemplo`): `PUERTO_SERIE`, `BAUDIOS` (115200 sugerido), `TIEMPO_LIMITE_COMANDO_S` (2), `PERIODO_LATIDO_S` (5), `PERIODOS_SIN_LATIDO` (3), `PERIODO_PING_S` (3). Ninguno vive en el código (CODESTYLE A-5, A-7).

## 8. Pruebas de referencia

| Prueba | Qué verifica |
|---|---|
| `pruebas/test_protocolo_crc.py` | Vector `29B1` y los cinco ejemplos del SPECS byte a byte |
| `pruebas/test_protocolo_tramas.py` | Delimitación, escape, resincronización, descartes |
| `pruebas/test_secuencia.py` | Saltos, duplicados, envoltura 2³², emisor S→C |
| `pruebas/test_gestor_comandos.py` | Correlación cmd_id↔SEQ, timeout 2 s, idempotencia |
| `pruebas/test_vigilante_latido.py` | Umbral de 3 periodos, AL01, retroactiva A14 |
| `pruebas/test_paridad_constantes.py` | Paridad firmware–puente (P-2) |
| `pruebas/test_integracion_simulador.py` | Ciclo completo sobre PTY sin maqueta ni broker |
| `pruebas/test_comandos_etapa9.py` | Los 13 comandos: NAK sin efecto con su condición, ACK sin ella, idempotencia por SEQ, AL14 y disponibilidad §6.3 |
