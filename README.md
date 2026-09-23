# PORTUS — Fase 2

Plataforma de supervisión y control remoto de la maqueta de la terminal portuaria (Fase 1) sobre un **computador de placa única (SBC)**. Proyecto de *Arquitectura de Computadoras y Ensambladores 2* — USAC, Facultad de Ingeniería.

> **Estado:** Etapas 3, 4, 5 y 6 del ROADMAP implementadas — **puente serial ↔ MQTT** (SPECS §4 recepción/secuencia/PING/SYN, §5 publicación MQTT, §5.4 vigilancia del latido y AL01, §6.4 flujo del comando), **núcleo de la aplicación web** (SPECS §7 autenticación/sesión/matriz de permisos, §18 API, §15.1 código de vinculación), **lógica del turno en el servidor** (SPECS §8 máquina de estados, §9.4 garita, §10 retenciones, §12 patio/trabajos, §13 alarmas, AUT/JOB hacia el controlador) y **las 8 pestañas del rol TERMINAL** (SPECS §14.1-§14.6: sinóptico por suscripción MQTT sobre WebSocket, Turnos con línea de tiempo, Retenciones con bandeja, Patio con inventario, Grúa con ciclos y CSV, Alarmas con reconocimiento, Citas con agenda y vinculación A17, Reportes con las 8 métricas y exportación CSV), con configuración de despliegue del broker, del servicio systemd y de la web. Las demás etapas están pendientes y mantienen su estructura lista.

## Arquitectura (SPECS §2)

```
Controlador (maqueta) ──serial (^SEQ|TIPO|CAMPOS#CRC)──▶ Puente (Python + pySerial)
Puente ──MQTT──▶ Mosquitto (TCP 1883 / WebSocket 9001) ──▶ Web, bot, navegador
```

Un protocolo distinto por enlace (SPECS §2.3): **serial** con el controlador, **MQTT** entre servicios, **HTTP** para las interfaces. Un solo protocolo para todo se evalúa como incumplimiento.

## Estructura del repositorio (CODESTYLE A-1)

```
portus/
├── src/            # código Arduino del controlador (Etapa 2 — pendiente)
├── puente/         # puente serial <-> MQTT (Etapa 3 — IMPLEMENTADO)
├── web/            # núcleo web + lógica del turno (Etapas 4 y 5 — IMPLEMENTADO)
├── mensajeria/     # bot de Telegram (Etapa 10 — pendiente)
├── db/             # esquema.sql + migraciones numeradas (001 puente, 002 web, 003 turno)
├── config/         # mosquitto.conf, acl_portus, portus.env.ejemplo, systemd/
├── pruebas/        # pytest con reloj inyectable y prueba E2E sobre PTY
├── herramientas/   # simulador del controlador, reproducir_captura.py, semilla de usuarios
└── docs/           # protocolo_serial.md, topicos_mqtt.md, despliegue_web.md
```

> **Desviación puntual de A-1 [DEC]:** el CODESTYLE nombra `firmware/` a la
> carpeta del controlador; el equipo usa **`src/`** para conservar la
> integridad con el proyecto Arduino ya existente de la Fase 1. El contenido,
> las reglas (A-1: sketch delega en módulos, FW-1 sin esperas bloqueantes) y
> el contrato (`docs/constantes_protocolo.json`) no cambian.

## El puente (Etapa 3)

| Módulo | Responsabilidad |
|---|---|
| `puente/protocolo.py` | Trama `^SEQ\|TIPO\|CAMPOS#CRC`, CRC-16/CCITT-FALSE, escape `%HH`, analizador incremental no bloqueante |
| `puente/secuencia.py` | Rastreo de SEQ del controlador (saltos → SYN), emisor de tramas S→C |
| `puente/mensajes_mqtt.py` | Envoltorio JSON único `{id, ts, origen, tipo, seq, datos}`, tópicos con `TOPIC_PREFIX`, conversión de campos |
| `puente/gestor_comandos.py` | Flujo §6.4: correlación `cmd_id`↔`SEQ`, timeout de 2 s con NAK sintético `SIN_RESPUESTA`, idempotencia |
| `puente/vigilante_latido.py` | 3 periodos sin latido → AL01; AL01 retroactiva al arrancar (A14) |
| `puente/persistencia_sqlite.py` | Eventos, telemetría y comandos con deduplicación por `id` (§5.5, §5.7) |
| `puente/publicador_mqtt.py` | paho-mqtt: Last Will `puente=caido`, suscripción `portus/#`, QoS/retain |
| `puente/puente.py` | Orquestación multihilo sin bloqueo cruzado, reconexión serial, PING periódico |

Documentación: [`docs/protocolo_serial.md`](docs/protocolo_serial.md) y [`docs/topicos_mqtt.md`](docs/topicos_mqtt.md).

## El núcleo web (Etapa 4)

Servicio `portus-web` (Flask + waitress, `python -m web`): capas `rutas → servicios → repositorios` (CODESTYLE A-2).

| Módulo | Responsabilidad |
|---|---|
| `web/seguridad/permisos.py` | Matriz §7.4 aplicada en el servidor con `@requiere_rol`: 403 explícito + auditoría de rechazos (§7.5) |
| `web/seguridad/hash_contrasenas.py` | bcrypt con sal por usuario; nunca texto plano (§7.3, S-3) |
| `web/seguridad/sesion.py` | Cookie firmada `HttpOnly`/`SameSite=Lax`; expiración por inactividad y cierre explícito (§7.3) |
| `web/servicios/servicio_auth.py` | Login: existe → hash → activo → rol con acceso web; TRANSPORTISTA se rechaza con 403 (§7.1) |
| `web/servicios/servicio_vinculacion.py` | Código de vinculación: 6 caracteres sin ambiguos, un uso, 60 min, invalida el anterior (§15.1, A17) |
| `web/repositorios/repositorio_manifiestos.py` | Filtro de propiedad `WHERE naviera_id = ?` dentro de la consulta SQL (§7.5.2, P11) |
| `web/modelos/pestanas.py` | Pestañas exactas por rol (§7.6): 8 TERMINAL · 2 NAVIERA · 2 AGENTE · 3 AUTORIDAD · 0 TRANSPORTISTA |
| `web/aplicacion.py` | Fábrica de la app + control de inactividad con reloj inyectable (T-3) |

Despliegue, credenciales de demostración (7 usuarios mínimos §7.2) y decisiones [DEC]: [`docs/despliegue_web.md`](docs/despliegue_web.md).

## La lógica del turno (Etapa 5)

La operación **se origina desde la plataforma**: el servidor valida cada evento del controlador contra la máquina de estados, decide y responde. El puente convierte `portus/srv/turno` en las tramas serial `AUT` (§4.4) y `JOB`; el flujo GAR → AUT, TRF/GRU/PAT → JOB y SAL → cierre queda completo.

| Módulo | Responsabilidad |
|---|---|
| `web/servicios/nucleo_logica.py` | Consumidor de `portus/#`: valida el envoltorio, deduplica por `id` (§5.5), enruta los eventos y registra la reconciliación (§3.3); fábrica única `crear()` (PY-7) |
| `web/servicios/servicio_turnos.py` | Máquina de estados §8.1 (10 estados, transiciones exactas), línea de tiempo §14.2 y publicación `portus/srv/turno` |
| `web/servicios/servicio_garita.py` | Cadena §9.4 exacta (vehículo → manifiesto → levante → cita → riesgo/plaza), AUT con causa, RT04 fuera de ventana y AL11 con parqueo lleno |
| `web/servicios/servicio_pesajes.py` | Revalidación A5 con la fórmula A4 (tara por vehículo), RT01/RT02/RT03 y AL09 (§9.2, §10.4) |
| `web/servicios/servicio_retenciones.py` | §10: retener/resolver (Aclarar/Corregir/Rechazar) con rol facultado, plaza de menor número, AgujaParqueo/AgujaLiberar y notificaciones §10.7 |
| `web/servicios/servicio_trabajos.py` | Plan §12.5 (depósito, retiro con remociones), JOB y confirmaciones GRU/PAT; aborto devuelve a la cola sin tocar inventario |
| `web/servicios/servicio_salida.py` | §8.6: SAL con verificación del vehículo (AL10 si no coincide), cierre del turno y salida sin completar en anulación |
| `web/servicios/servicio_patio.py` | PAT confirmado → inventario y estado de posiciones (§12.3, §8.2 regla 2) |
| `web/servicios/politica_asignacion.py` | Política de la Fase 1 como modo seleccionable detrás de `asignar_posicion(...)` (§12.4, FASE1 por omisión) |
| `db/migraciones/003_tablas_del_turno.sql` | Turno, retenciones, plaza_parqueo (semilla 1-3), trabajo_grua, inventario, alarmas, notificaciones y dedup del consumidor |

Tópicos del servidor: [`docs/topicos_mqtt.md`](docs/topicos_mqtt.md) (`portus/srv/turno`, `portus/srv/retencion`, `portus/srv/alarma`).

## La interfaz del rol TERMINAL (Etapa 6)

Las **8 pestañas** del rol TERMINAL (SPECS §14, §6.3, §12.2, §12.6, §13.3, §11.4,
§15.1, §16). El sinóptico se actualiza **solo por suscripción MQTT sobre
WebSocket** (CODESTYLE JS-2: prohibido el polling, −10 % en la rúbrica); el
resto consume la API REST de la Etapa 5 ampliada. Toda inserción de datos en
el navegador se hace con `textContent` (JS-3: sin `innerHTML`).

| Pestaña | §14 | Implementación |
|---|---|---|
| Operación | §14.1 | Sinóptico de los 13 elementos; `mqtt.mjs` (cliente MQTT 3.1.1 mínimo sobre WS) + `sinoptico.mjs`; botones de comandos §6.3 con confirmación (AbrirTalanquera/AbrirPuertaSalida/ModoMantenimiento) y panel de comandos manuales (CerrarTalanquera/AgujaRecta/AgujaParqueo) |
| Turnos | §14.2 | Activos/históricos, filtros (estado/tipo/fecha/búsqueda), línea de tiempo, Retener (RT06) y Anular |
| Retenciones | §14.3 | Bandeja abiertas/resueltas con los 9 campos, Aclarar/Corregir/Rechazar, filtro por causa |
| Patio | §12.2/§14.4 | Posiciones por nivel + tabla de inventario (8 campos), Bloquear/Liberar, indicador de permanencia > 2 h |
| Grúa | §12.6 | Trabajo en curso, cola pendiente, historial de fallas (AL03-AL06) y exportación CSV del rango |
| Alarmas | §13.3 | Activas/históricas, reconocer (comentario), reconocer todas (solo baja/media), filtro por severidad, `AlarmaSilenciar` |
| Citas | §14.5/§11.4 | Agenda del día por franjas, cancelar/reprogramar (notifican), bloquear franja, indicador de cumplimiento y **panel de vinculación A17** (Generar código) |
| Reportes | §14.6/§16 | Rango + etiqueta, las **8 métricas** de §16.1 y exportación CSV con el detalle de cada turno + política activa |

| Módulo | Responsabilidad |
|---|---|
| `web/servicios/servicio_alarmas.py` | Reconocimiento (uno a uno y en lote baja/media), `AlarmaSilenciar` (§13.3, §13.4) |
| `web/servicios/servicio_citas.py` | Agenda, cancelar/reprogramar con notificación (§11.4), bloquear franja, cumplimiento |
| `web/servicios/servicio_grua.py` | Estado de la grúa, ciclos, fallas y CSV (§12.6) |
| `web/servicios/servicio_reportes.py` | Las 8 métricas de §16.1 + persistencia + CSV (§16.3) |
| `web/servicios/servicio_comandos.py` | Emisión de comandos remotos del catálogo §6.1 hacia el puente (§6.4) |
| `web/servicios/servicio_vinculacion.py` | Panel de transportistas vinculados (§14.5, A17) |
| `db/migraciones/004_tablas_de_etapa6.sql` | `ciclo_grua` (§12.6) y `reporte` (§16.3) |
| `web/interfaz/estatico/js/mqtt.mjs` | Cliente MQTT 3.1.1 mínimo sobre WebSocket (sin dependencias) |

## Requisitos

- Python ≥ 3.11 (SBC) con `pyserial==3.5`, `paho-mqtt==2.1.0`, `flask==3.1.3`, `bcrypt==5.0.0`, `waitress==3.0.2`
- Mosquitto 2.x con soporte de WebSocket
- Desarrollo: `pytest`, `ruff`, `mypy` (todo en `requirements.txt`)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Ejecución

1. **Broker** (ver `config/mosquitto.conf` para el detalle completo).

   **En desarrollo (máquina local / WSL) — sin sudo ni systemd:**

   ```bash
   sudo apt install mosquitto mosquitto-clients     # el broker y las herramientas
   mosquitto_passwd -c config/passwd_mosquitto portus-puente      # -c SOLO el primero
   mosquitto_passwd -b config/passwd_mosquitto portus-tablero <clave-tablero>
   mosquitto -c config/mosquitto_dev.conf -v        # en primer plano, desde la raíz del repo
   # Ctrl+C para pararlo; prueba rápida en otra terminal:
   mosquitto_sub -h 127.0.0.1 -u portus-tablero -P <clave-tablero> -t 'portus/#' -v
   mosquitto_pub -h 127.0.0.1 -u portus-puente -P <clave-puente> -t portus/evt/prueba -m hola
   ```

   **En producción (SBC)** — el servicio corre como usuario `mosquitto`, así
   que los archivos que lee deben ser suyos; si quedan de root sin lectura
   para él, muere con «Unable to open pwfile» (probado con mosquitto 2.0):

   ```bash
   sudo mkdir -p /opt/portus/config
   sudo mosquitto_passwd -c /opt/portus/config/passwd_mosquitto portus-puente
   sudo mosquitto_passwd -b /opt/portus/config/passwd_mosquitto portus-web <contrasena-web>
   sudo mosquitto_passwd -b /opt/portus/config/passwd_mosquitto portus-msg <contrasena-msg>
   sudo mosquitto_passwd -b /opt/portus/config/passwd_mosquitto portus-tablero <contrasena-tablero>
   sudo cp config/acl_portus /opt/portus/config/
   sudo chown mosquitto:mosquitto /opt/portus/config/passwd_mosquitto /opt/portus/config/acl_portus
   sudo chmod 600 /opt/portus/config/passwd_mosquitto
   sudo chmod 640 /opt/portus/config/acl_portus
   sudo cp config/mosquitto.conf /etc/mosquitto/conf.d/portus.conf
   sudo systemctl restart mosquitto
   ```

   Notas: la `-c` **solo va en el primer usuario** (crea el archivo; con
   otro `-c` se borra lo anterior). Para los demás se usa `-b` con la
   contraseña en el comando. Si `systemctl restart` falla, corra el broker
   en primer plano para ver el error real: `sudo /usr/sbin/mosquitto -c
   /etc/mosquitto/mosquitto.conf -v` (o revise `journalctl -xeu
   mosquitto.service`): casi siempre es una ruta de `password_file`/
   `acl_file` que no existe, o un archivo que el usuario `mosquitto` no
   puede leer (quedó de root con `0700`).

2. **Configuración del puente:**

   ```bash
   cp config/portus.env.ejemplo config/portus.env   # editar credenciales y puerto serie
   # ls /dev/ttyUSB* /dev/ttyACM*  para identificar el puerto del controlador
   sudo usermod -aG dialout $USER   # permisos del puerto serie
   ```

3. **Servicios:**

   ```bash
   python -m puente --config config/portus.env   # puente serial <-> MQTT
   python -m web --config config/portus.env      # núcleo web (http://0.0.0.0:8000/)
   # o como servicios systemd (SPECS §19.2: mosquitto → web → bridge):
   sudo cp config/systemd/portus-web.service config/systemd/portus-puente.service /etc/systemd/system/
   sudo systemctl enable --now portus-web portus-puente
   ```

4. **Verificación**:

   ```bash
   mosquitto_sub -h 127.0.0.1 -u portus-tablero -P … -t 'portus/#' -v
   # esperado: portus/srv/enlace … "puente":"activo"  y los latidos portus/evt/estado
   ```

## Pruebas y simulación sin maqueta

```bash
python -m pytest                      # 279 pruebas: puente, lógica del turno, web (Etapas 4-6), integración y E2E
ruff check . && ruff format --check . # formato y lint (CODESTYLE §4)
mypy puente herramientas web          # tipado estricto (PY-1)
```

Con par de PTY para enlazar dos procesos sin hardware:

```bash
socat -d -d pty,raw,echo=0 pty,raw,echo=0     # anota los /dev/pts/N que imprime
python -m herramientas.simulador_controlador --puerto /dev/pts/3 --intervalo-latido-s 2
python -m puente --config config/portus.env   # con PUERTO_SERIE=/dev/pts/4
```

Para probar AL01: `--modo sin_latido` detiene los latidos del simulador y el puente genera AL01 a los 15 s. Para la prueba temprana H2 del ROADMAP (barrera 3): apagar el servidor a mitad de un trabajo de grúa, comprobar modo degradado en el simulador y reconciliar al reconectar (los `SYN` del puente piden el historial al controlador).

`herramientas/reproducir_captura.py --analizar captura.txt` valida una captura de tramas y muestra el envoltorio JSON que se publicaría (CODESTYLE D-11).

## Calidad

- Formato con `ruff format`, lint con `ruff check` (línea de 100 columnas), tipado `mypy --strict`, pruebas `pytest` con reloj inyectable y sin `sleep` en lógica (T-3).
- Identificadores en español sin tildes ni `ñ`; textos y registros en español, fechas ISO 8601 UTC (I-1, I-2, I-8).
- Secretos solo en `config/portus.env` (excluido por `.gitignore`); `portus.env.ejemplo` sin valores reales (S-1, G-6).
- Commits en español, imperativo, con tipo y ámbito (G-5): `nuevo(puente): …`, `correccion(puente): …`.
