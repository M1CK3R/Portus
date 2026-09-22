# PORTUS — Fase 2

Plataforma de supervisión y control remoto de la maqueta de la terminal portuaria (Fase 1) sobre un **computador de placa única (SBC)**. Proyecto de *Arquitectura de Computadoras y Ensambladores 2* — USAC, Facultad de Ingeniería.

> **Estado:** Etapas 3 y 4 del ROADMAP implementadas — **puente serial ↔ MQTT** (recepción/secuencia/PING/SYN, publicación MQTT, vigilancia del latido y AL01, flujo del comando) y **núcleo de la aplicación web** (SPECS autenticación/sesión/matriz de permisos, API, código de vinculación), con configuración de despliegue del broker, del servicio systemd y de la web. Las demás etapas están pendientes y mantienen su estructura lista.

## Arquitectura

```
Controlador (maqueta) ──serial (^SEQ|TIPO|CAMPOS#CRC)──▶ Puente (Python + pySerial)
Puente ──MQTT──▶ Mosquitto (TCP 1883 / WebSocket 9001) ──▶ Web, bot, navegador
```

Un protocolo distinto por enlace: **serial** con el controlador, **MQTT** entre servicios, **HTTP** para las interfaces. Un solo protocolo para todo se evalúa como incumplimiento.

## Estructura del repositorio

```
portus/
├── firmware/       # extensión del firmware de la Fase 1 (Etapa 2 — pendiente)
├── puente/         # puente serial <-> MQTT (Etapa 3 — IMPLEMENTADO)
├── web/            # núcleo web: auth, permisos, API, interfaz (Etapa 4 — IMPLEMENTADO)
├── mensajeria/     # bot de Telegram (Etapa 10 — pendiente)
├── db/             # esquema.sql + migraciones numeradas (001 puente, 002 web)
├── config/         # mosquitto.conf, acl_portus, portus.env.ejemplo, systemd/
├── pruebas/        # pytest con reloj inyectable y prueba E2E sobre PTY
├── herramientas/   # simulador del controlador, reproducir_captura.py, semilla de usuarios
└── docs/           # protocolo_serial.md, topicos_mqtt.md, despliegue_web.md
```

## El puente (Etapa 3)

| Módulo | Responsabilidad |
|---|---|
| `puente/protocolo.py` | Trama `^SEQ\|TIPO\|CAMPOS#CRC`, CRC-16/CCITT-FALSE, escape `%HH`, analizador incremental no bloqueante |
| `puente/secuencia.py` | Rastreo de SEQ del controlador (saltos → SYN), emisor de tramas S→C |
| `puente/mensajes_mqtt.py` | Envoltorio JSON único `{id, ts, origen, tipo, seq, datos}`, tópicos con `TOPIC_PREFIX`, conversión de campos |
| `puente/gestor_comandos.py` | Flujo: correlación `cmd_id`↔`SEQ`, timeout de 2 s con NAK sintético `SIN_RESPUESTA`, idempotencia |
| `puente/vigilante_latido.py` | 3 periodos sin latido → AL01; AL01 retroactiva al arrancar (A14) |
| `puente/persistencia_sqlite.py` | Eventos, telemetría y comandos con deduplicación por `id` |
| `puente/publicador_mqtt.py` | paho-mqtt: Last Will `puente=caido`, suscripción `portus/#`, QoS/retain |
| `puente/puente.py` | Orquestación multihilo sin bloqueo cruzado, reconexión serial, PING periódico |

Documentación: [`docs/protocolo_serial.md`](docs/protocolo_serial.md) y [`docs/topicos_mqtt.md`](docs/topicos_mqtt.md).

## El núcleo web (Etapa 4)

Servicio `portus-web` (Flask + waitress, `python -m web`): capas `rutas → servicios → repositorios` (CODESTYLE A-2).

| Módulo | Responsabilidad |
|---|---|
| `web/seguridad/permisos.py` | Matriz aplicada en el servidor con `@requiere_rol`: 403 explícito + auditoría de rechazos |
| `web/seguridad/hash_contrasenas.py` | bcrypt con sal por usuario; nunca texto plano |
| `web/seguridad/sesion.py` | Cookie firmada `HttpOnly`/`SameSite=Lax`; expiración por inactividad y cierre explícito |
| `web/servicios/servicio_auth.py` | Login: existe → hash → activo → rol con acceso web; TRANSPORTISTA se rechaza con 403 |
| `web/servicios/servicio_vinculacion.py` | Código de vinculación: 6 caracteres sin ambiguos, un uso, 60 min, invalida el anterior |
| `web/repositorios/repositorio_manifiestos.py` | Filtro de propiedad `WHERE naviera_id = ?` dentro de la consulta SQL |
| `web/modelos/pestanas.py` | Pestañas exactas por rol: 8 TERMINAL · 2 NAVIERA · 2 AGENTE · 3 AUTORIDAD · 0 TRANSPORTISTA |
| `web/aplicacion.py` | Fábrica de la app + control de inactividad con reloj inyectable (T-3) |

Despliegue, credenciales de demostración (7 usuarios mínimos) y decisiones [DEC]: [`docs/despliegue_web.md`](docs/despliegue_web.md).

## Requisitos

- Python ≥ 3.11 (SBC) con `pyserial==3.5`, `paho-mqtt==2.1.0`, `flask==3.1.3`, `bcrypt==5.0.0`, `waitress==3.0.2`
- Mosquitto 2.x con soporte de WebSocket
- Desarrollo: `pytest`, `ruff`, `mypy` (todo en `requirements.txt`)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Ejecución

1. **Broker** (ver `config/mosquitto.conf` para el detalle completo):

   ```bash
   sudo apt install mosquitto
   sudo mosquitto_passwd -c config/passwd_mosquitto portus-puente   # y los demás usuarios
   sudo cp config/mosquitto.conf /etc/mosquitto/conf.d/portus.conf
   sudo systemctl restart mosquitto
   ```

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
   # o como servicios systemd (mosquitto → web → bridge):
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
python -m pytest                      # 144 pruebas: puente, web, integración y E2E
ruff check . && ruff format --check . # formato y lint
mypy puente herramientas web          # tipado estricto
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
