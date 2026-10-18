# PORTUS

Plataforma de supervisión y control remoto de la maqueta de la terminal portuaria (Fase 1) sobre un **computador de placa única (SBC)**.

> **Estado:** Etapas 3 a 12 del ROADMAP implementadas en el servidor.
>
> - Puente serial ↔ MQTT.
> - Núcleo web con roles y permisos.
> - Lógica del turno.
> - Pestañas de los 4 roles web.
> - Retenciones y parqueo.
> - Alarmas y los 13 comandos remotos.
> - Bot de Telegram del transportista.
> - Citas con control de ventana.
> - Métricas y reportes.
>
> El firmware del controlador (Etapa 2) lo mantiene otro carril del equipo en `src/`.

---

## Contenido

1. [Arquitectura](#1-arquitectura)
2. [Estructura del repositorio](#2-estructura-del-repositorio)
3. [Despliegue en el SBC desde cero](#3-despliegue-en-el-sbc-desde-cero) (con Docker: [`docs/docker.md`](docs/docker.md))
4. [Configuración (`portus.env`)](#4-configuración-portusenv)
5. [Verificación y acceso desde la red local](#5-verificación-y-acceso-desde-la-red-local)
6. [Operación diaria](#6-operación-diaria)
7. [Solución de problemas](#7-solución-de-problemas)
8. [Desarrollo y pruebas sin maqueta](#8-desarrollo-y-pruebas-sin-maqueta)
9. [Documentación](#9-documentación)

---

## 1. Arquitectura

```
                    serial ^SEQ|TIPO|CAMPOS#CRC
Controlador (maqueta) ─────────────────────────▶ portus-puente ──┐
                                                                  │ MQTT (TCP 1883)
                         ┌──────────── Mosquitto ◀────────────────┘
                         │     1883 (servicios) · 9001 (WebSocket del navegador)
          ┌──────────────┼──────────────────────┐
     portus-web     navegador (sinóptico)    portus-msg ──HTTPS──▶ Bot API de Telegram ──▶ teléfono
   HTTP :8000 + lógica    MQTT/WS :9001                                                  del transportista
          │
     db/portus.db (SQLite WAL, compartida)
```

Cada enlace usa un protocolo distinto:

- **Serial** con el controlador.
- **MQTT** entre servicios y hacia el sinóptico.
- **HTTP** para la interfaz web.
- **Telegram** (HTTPS saliente) solo para el transportista.

Los servicios y su orden de arranque son `mosquitto` → `portus-web` → `portus-puente` → `portus-msg`:

| Servicio | Qué hace |
|---|---|
| `mosquitto` | Broker MQTT con usuarios y ACL por servicio |
| `portus-web` | Interfaz web (Flask + waitress), lógica del turno, retenciones, alarmas, citas y reportes. **Aplica las migraciones de la base al arrancar** |
| `portus-puente` | Enlace serial con el controlador: tramas, CRC, secuencia, ACK/NAK, latido y AL01 |
| `portus-msg` | Bot de Telegram: vinculación, 7 comandos, 9 avisos y recordatorios. Único servicio con salida a internet |

---

## 2. Estructura del repositorio

```
portus/
├── src/            # firmware Arduino del controlador (carril del firmware)
├── puente/         # puente serial <-> MQTT                     (python -m puente)
├── web/            # núcleo web, lógica del turno e interfaz   (python -m web)
│   ├── rutas/  servicios/  repositorios/  modelos/  seguridad/  interfaz/
├── mensajeria/     # bot de Telegram                            (python -m mensajeria)
├── db/             # migraciones 001–008 y esquema.sql (regenerado, no se edita a mano)
├── config/         # mosquitto.conf, acl_portus, portus.env.ejemplo, systemd/
├── docker/         # broker para Docker (Dockerfile y docker-compose.yml van en la raíz)
├── herramientas/   # semillas, simulador del controlador, regenerar_esquema, reproducir_captura
├── pruebas/        # pytest (405 pruebas)
└── docs/           # SPECS, ROADMAP, CODESTYLE, protocolo, tópicos y guías por tema
```

---

## 3. Despliegue en el SBC desde cero

> **¿Con Docker?** Hay una alternativa que levanta los 4 servicios con `docker compose up -d --build`, sin venv, sin usuario `portus` y sin `mosquitto_passwd`: ver [`docs/docker.md`](docs/docker.md). Los pasos 3.3 (configuración), 3.5 (semillas) y 3.6 (bot) aplican igual; cambian los comandos.

Procedimiento del punto 19.3 de SPECS.md. Está probado sobre Debian/Ubuntu y Raspberry Pi OS Bookworm (Python 3.11+). Los comandos asumen que se clona en **`/opt/portus`** y que los servicios corren con el usuario de sistema **`portus`**, que es lo que esperan las unidades de `config/systemd/`.

### 3.1 Paquetes y reloj

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip mosquitto mosquitto-clients sqlite3 ufw
python3 --version          # debe ser 3.11 o superior
sudo timedatectl set-ntp true
timedatectl                # "System clock synchronized: yes"
```

- Todas las marcas se guardan en **UTC**. La hora de la terminal (franjas, reportes) es **UTC-6 fija**, así que la zona horaria del SBC da igual.
- **El reloj sí debe estar sincronizado.** Sin NTP, las ventanas de cita, las alarmas por tiempo y las métricas salen mal.

### 3.2 Usuario de servicio y código

```bash
sudo useradd --system --create-home --home-dir /var/lib/portus --shell /usr/sbin/nologin portus
sudo usermod -aG dialout portus           # acceso al puerto serie del controlador
sudo git clone <URL-del-repositorio> /opt/portus
sudo chown -R portus:portus /opt/portus
cd /opt/portus
sudo -u portus python3 -m venv venv
sudo -u portus venv/bin/pip install -r requirements.txt
```

`requirements.txt` fija las versiones (A-8): `pyserial`, `paho-mqtt`, `flask`, `bcrypt`, `waitress`, `python-telegram-bot`, más `ruff`, `mypy` y `pytest` para verificar.

### 3.3 Configuración

```bash
sudo -u portus cp config/portus.env.ejemplo config/portus.env
sudo chmod 600 config/portus.env
sudo -u portus nano config/portus.env     # ver §4: puerto serie, contraseñas, clave web, token
ls /dev/ttyUSB* /dev/ttyACM*              # el puerto del controlador va en PUERTO_SERIE
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # valor para WEB_CLAVE_SECRETA
```

`config/portus.env` está en `.gitignore`. **Nunca se sube al repositorio** (S-1).

### 3.4 Mosquitto (usuarios, ACL y WebSocket)

El broker corre como el usuario `mosquitto`, así que los archivos que lee deben ser suyos. Las contraseñas deben coincidir con las de `portus.env`:

| Usuario MQTT | Lo usa | Clave en `portus.env` | Permisos (`config/acl_portus`) |
|---|---|---|---|
| `portus-puente` | puente y web | `MQTT_USUARIO` / `MQTT_CONTRASENA` | lectura y escritura `portus/#` |
| `portus-tablero` | navegador (sinóptico) | `MQTT_TABLERO_USUARIO` / `MQTT_TABLERO_CONTRASENA` | **solo lectura** |
| `portus-msg` | bot | `MSG_MQTT_USUARIO` / `MSG_MQTT_CONTRASENA` | solo lectura de `portus/srv/*` |

```bash
sudo mosquitto_passwd -c /opt/portus/config/passwd_mosquitto portus-puente    # -c SOLO en el primero
sudo mosquitto_passwd -b /opt/portus/config/passwd_mosquitto portus-tablero '<clave-tablero>'
sudo mosquitto_passwd -b /opt/portus/config/passwd_mosquitto portus-msg '<clave-msg>'
sudo chown mosquitto:mosquitto /opt/portus/config/passwd_mosquitto /opt/portus/config/acl_portus
sudo chmod 600 /opt/portus/config/passwd_mosquitto
sudo chmod 640 /opt/portus/config/acl_portus
sudo cp config/mosquitto.conf /etc/mosquitto/conf.d/portus.conf
sudo systemctl restart mosquitto && systemctl status mosquitto --no-pager
```

- `config/mosquitto.conf` abre **1883** (servicios) y **9001** (WebSocket del navegador), exige usuario y aplica la ACL.
- `-c` crea el archivo: con otro `-c` se borran los usuarios anteriores.
- `config/passwd_mosquitto` también está en `.gitignore`.

### 3.5 Base de datos y usuarios semilla

```bash
cd /opt/portus
sudo -u portus venv/bin/python -m herramientas.crear_usuarios_semilla --bd db/portus.db
sudo -u portus venv/bin/python -m herramientas.crear_datos_semilla --ruta-bd db/portus.db
```

- El primero crea el esquema (migraciones 001–008) y los **7 usuarios mínimos**: `terminal01`, `naviera01`, `naviera02`, `agente01`, `autoridad01`, `transportista01` y `transportista02`.
- Imprime **una sola vez** las contraseñas generadas. Guárdelas para la entrega («credenciales de prueba»).
- Para fijarlas en lugar de generarlas: `--contrasena-terminal …`, `--contrasena-naviera …`, etc., o las variables `PORTUS_SEMILLA_<ROL>`.
- El segundo carga el catálogo de contenedores de la maqueta, los vehículos (con tara) y las posiciones del patio P1–P4. Las plazas de parqueo 1–3 nacen con el esquema.
- **No se precargan operaciones** (barrera 🔴 4): manifiestos, levantes y citas se crean desde la plataforma durante la demostración.

### 3.6 Bot de Telegram (una sola vez)

1. En Telegram, abrir **@BotFather** → `/newbot` → nombre (p. ej. «PORTUS Terminal») → usuario que termine en `bot`.
2. Pegar el token en `config/portus.env` → `TELEGRAM_BOT_TOKEN=…`. Si se filtra, `/revoke` en @BotFather.
3. El menú de comandos lo registra el propio servicio al arrancar.

El SBC necesita **salida HTTPS a internet** para el bot (Wi-Fi o hotspot del teléfono como plan B). Sin internet, el resto de la plataforma funciona igual y los avisos quedan pendientes hasta que vuelva la conexión. Detalle en [`docs/mensajeria.md`](docs/mensajeria.md).

### 3.7 Servicios systemd

```bash
sudo cp config/systemd/portus-web.service config/systemd/portus-puente.service \
        config/systemd/portus-msg.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now portus-web portus-puente portus-msg
systemctl status portus-web portus-puente portus-msg --no-pager
```

Las unidades usan `WorkingDirectory=/opt/portus`, `User=portus` y `Restart=always`, y respetan el orden del punto 19.2 de SPECS.md. `portus-web` aplica las migraciones y el bot abre la base sin reaplicarlas, por eso arranca después.

### 3.8 Firewall (red local)

```bash
sudo ufw allow OpenSSH
sudo ufw allow from 192.168.0.0/16 to any port 8000 proto tcp   # web
sudo ufw allow from 192.168.0.0/16 to any port 9001 proto tcp   # sinóptico (MQTT/WebSocket)
sudo ufw enable
```

Ajuste el rango a la red del laboratorio. El puerto **1883 no se abre**: solo lo usan los servicios del propio SBC. El bot solo necesita salida, no puertos de entrada: usa *long polling*, no webhook.

---

## 4. Configuración (`portus.env`)

| Clave | Servicio | Valor |
|---|---|---|
| `PUERTO_SERIE`, `BAUDIOS` | puente | p. ej. `/dev/ttyUSB0`, `115200` |
| `MQTT_HOST`, `MQTT_PUERTO` | todos | `127.0.0.1`, `1883` |
| `MQTT_USUARIO`, `MQTT_CONTRASENA` | puente y web | `portus-puente` y su clave |
| `MQTT_WS_PUERTO`, `MQTT_TABLERO_USUARIO`, `MQTT_TABLERO_CONTRASENA` | web → navegador | `9001`, `portus-tablero` y su clave (solo lectura) |
| `RUTA_BD` | todos | `db/portus.db` (relativa a `/opt/portus`) |
| `TIEMPO_LIMITE_COMANDO_S`, `PERIODO_LATIDO_S`, `PERIODOS_SIN_LATIDO`, `PERIODO_PING_S` | puente | `2`, `5`, `3`, `3` |
| `WEB_PUERTO` | web | `8000` |
| `WEB_CLAVE_SECRETA` | web | **obligatoria en el SBC**: firma la cookie de sesión |
| `WEB_EXPIRACION_INACTIVIDAD_MIN`, `WEB_VIDA_MAXIMA_SESION_H` | web | `30`, `12` |
| `POLITICA_ASIGNACION` | web | `FASE1`: la línea base; queda registrada en cada reporte |
| `TELEGRAM_BOT_TOKEN` | bot | token de @BotFather (sin él, `portus-msg` no arranca) |
| `MSG_MQTT_USUARIO`, `MSG_MQTT_CONTRASENA` | bot | `portus-msg` y su clave |
| `NOMBRE_TERMINAL` | bot | nombre que muestra `/inicio` |
| `NIVEL_REGISTRO` | todos | `INFO` (`DEBUG` para diagnóstico) |

---

## 5. Verificación y acceso desde la red local

Con los servicios arriba, compruebe (pasos 6–8 del punto 19.3 del SPECS.md):

```bash
hostname -I                                         # IP del SBC en la red local
mosquitto_sub -h 127.0.0.1 -u portus-tablero -P '<clave-tablero>' -t 'portus/#' -v
#   esperado: portus/srv/enlace … "puente":"activo" y el latido portus/evt/estado cada ≤ 5 s
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/login   # 200
journalctl -u portus-msg -n 20 --no-pager           # "Bot @… listo: webhook eliminado y menú registrado"
```

Desde otra computadora de la misma red:

- **Web:** `http://<IP-del-SBC>:8000/`. Si el SBC anuncia mDNS (`avahi-daemon`), también `http://<hostname>.local:8000/`.
- **Roles:** TERMINAL, NAVIERA, AGENTE y AUTORIDAD entran con su usuario. TRANSPORTISTA no tiene acceso web: opera por el bot.
- **Sinóptico:** se actualiza en vivo por MQTT/WebSocket al puerto 9001 del mismo SBC. Si aparece «enlace perdido», revise el paso 3.4 y el firewall.
- **Bot:** en el teléfono, abrir el bot y escribir `/inicio`. Luego TERMINAL genera el código en *Citas → Vinculación de transportistas* y el transportista escribe `/vincular CODIGO`.

**Condición inicial para la demostración:**

- Controlador conectado y latiendo.
- Grúa referenciada (`GruaReferenciar` desde la pestaña Operación).
- Inventario de la pestaña Patio igual a la disposición física.
- Bot vinculado en los dos teléfonos de prueba.

---

## 6. Operación diaria

| Tarea | Comando |
|---|---|
| Ver registros en vivo | `journalctl -u portus-web -u portus-puente -u portus-msg -f` |
| Reiniciar todo | `sudo systemctl restart mosquitto portus-web portus-puente portus-msg` |
| Actualizar el código | `cd /opt/portus && sudo -u portus git pull && sudo -u portus venv/bin/pip install -r requirements.txt && sudo systemctl restart portus-web portus-puente portus-msg` |
| Respaldo de la base | `sudo -u portus sqlite3 /opt/portus/db/portus.db ".backup '/var/lib/portus/portus-$(date +%F).db'"` |
| Reporte de la corrida de evaluación | Pestaña **Reportes** → rango en hora de la terminal + etiqueta → exportar los dos CSV ([`docs/metricas.md`](docs/metricas.md) ) |

Las migraciones nuevas se aplican solas al reiniciar `portus-web`: son idempotentes, así que no hace falta ningún paso manual.

---

## 7. Solución de problemas

| Síntoma | Causa probable / arreglo |
|---|---|
| `mosquitto` no arranca («Unable to open pwfile») | `passwd_mosquitto` o `acl_portus` no son del usuario `mosquitto` o la ruta no existe. Ver el error real con `sudo /usr/sbin/mosquitto -c /etc/mosquitto/mosquitto.conf -v` |
| `portus-puente` reinicia en bucle | Puerto serie equivocado o sin permiso: revise `PUERTO_SERIE` y que `portus` esté en `dialout` (reinicie el servicio tras `usermod`) |
| Alarma **AL01** al arrancar | El controlador no late: cable, baudios o firmware. Si el servidor estuvo apagado, es la AL01 retroactiva (A14) y se reconoce en *Alarmas* |
| El sinóptico dice «enlace perdido» | El navegador no llega al 9001: firewall, o `MQTT_TABLERO_*` no coincide con `passwd_mosquitto` |
| Login responde 403 | Usuario TRANSPORTISTA (sin web por diseño) o rol sin permiso para esa acción (queda en la auditoría) |
| `portus-msg` termina al arrancar | Falta `TELEGRAM_BOT_TOKEN`, el token es inválido o no hay internet. systemd lo reintenta cada 10 s |
| El bot no manda avisos | Transportista sin vincular, o sin internet: los avisos quedan pendientes en `notificacion` y salen al volver |
| El reporte sale vacío | Revise que el rango esté en **hora de la terminal** y que el reloj del SBC esté sincronizado |
| Métrica 6 (fila de espera) en 0 | El firmware no llena `espera` en el latido `EST` (A15, [`docs/metricas.md`](docs/metricas.md)) |

---

## 8. Desarrollo y pruebas sin maqueta

En una PC o WSL, sin sudo ni systemd:

```bash
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cp config/portus.env.ejemplo config/portus.env              # PUERTO_SERIE=/tmp/portus_b
mosquitto_passwd -c config/passwd_mosquitto portus-puente   # y -b para portus-tablero y portus-msg
mosquitto -c config/mosquitto_dev.conf -v                   # broker en primer plano (localhost)
```

Controlador simulado sobre un par de PTY:

```bash
socat pty,raw,echo=0,link=/tmp/portus_a pty,raw,echo=0,link=/tmp/portus_b &
python -m herramientas.simulador_controlador --puerto /tmp/portus_a --interactivo
python -m web --config config/portus.env
python -m puente --config config/portus.env
```

- **Consola del simulador:** órdenes `gar V01`, `pes V01 38600`, `trf V01`, `grua`, `sal V01 CONFIRMADO`, `alm AL02 CRITICA`, `sensor espera 3`, `estado`, `ayuda`.
- **Probar AL01:** usar `--modo sin_latido`.
- **Operación de desarrollo:**
  ```bash
  python -m herramientas.crear_operacion_demo --ruta-bd db/portus.db
  ```
  Crea el manifiesto y el levante, sin cita: la cita se pide con `/cita`.
- **Solo en desarrollo, sin bot:** `--con-cita` escribe la cita directo en la base. (barrera 🔴 4, [`docs/citas.md`](docs/citas.md) ).

Verificación antes de cada commit:

```bash
ruff check . && ruff format --check .
mypy puente web herramientas mensajeria          # --strict desde pyproject.toml
python -m pytest                                  # 405 pruebas
python -m herramientas.regenerar_esquema --verificar   # esquema.sql al día con las migraciones
```

Tras agregar una migración en `db/migraciones/`, regenere `db/esquema.sql` con `python -m herramientas.regenerar_esquema`. Una prueba verifica que coincidan.

---

## 9. Documentación

| Tema | Documento |
|---|---|
| Requisitos, decisiones y ambigüedades | [`docs/SPECS.md`](docs/SPECS.md), [`docs/ROADMAP.md`](docs/ROADMAP.md), [`docs/CODESTYLE.md`](docs/CODESTYLE.md) |
| Protocolo serial (tramas, CRC, secuencia, enclavamientos) | [`docs/protocolo_serial.md`](docs/protocolo_serial.md), [`docs/constantes_protocolo.json`](docs/constantes_protocolo.json) |
| Tópicos MQTT, envoltorio y ACL | [`docs/topicos_mqtt.md`](docs/topicos_mqtt.md) |
| Alarmas AL01–AL14 | [`docs/alarmas.md`](docs/alarmas.md) |
| Bot de Telegram: alta, vinculación, comandos y avisos | [`docs/mensajeria.md`](docs/mensajeria.md) |
| Citas, ventana y ciclo de vida | [`docs/citas.md`](docs/citas.md) |
| Métricas, reportes y línea base de la Fase 3 | [`docs/metricas.md`](docs/metricas.md) |
| Núcleo web: permisos y decisiones de la Etapa 4 | [`docs/despliegue_web.md`](docs/despliegue_web.md) |
| Despliegue con Docker en la Raspberry Pi 4B | [`docs/docker.md`](docs/docker.md) |

**Calidad (CODESTYLE):**

- Formato y lint con `ruff` (100 columnas).
- `mypy --strict`.
- Pruebas deterministas con reloj inyectable.
- Identificadores y textos en español.
- Marcas ISO 8601 UTC.
- Secretos solo en `config/portus.env`.
- Commits `tipo(ámbito): resumen` en imperativo (G-5).
