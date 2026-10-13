# Despliegue con Docker en la Raspberry Pi 4B

Alternativa a la instalación manual con systemd del [README §3](../README.md#3-despliegue-en-el-sbc-desde-cero). Levanta todo PORTUS con un solo comando:

```bash
docker compose up -d --build
```

| Contenedor | Imagen | Qué corre |
|---|---|---|
| `portus-mosquitto` | `eclipse-mosquitto:2` (oficial) | Broker MQTT: 1883 (servicios, solo localhost) y 9001 (WebSocket del navegador) |
| `portus-web` | `portus` (de este `Dockerfile`) | `python -m web`: interfaz en el puerto 8000; aplica las migraciones al arrancar |
| `portus-puente` | `portus` | `python -m puente`: enlace serial con el Arduino |
| `portus-msg` | `portus` | `python -m mensajeria`: bot de Telegram |

Los tres servicios de Python comparten una sola imagen. Arrancan en el orden de §19.2: `mosquitto` → `portus-web` → `portus-puente` → `portus-msg`. Cada uno espera a que el anterior esté sano, se reinicia solo si falla y vuelve a levantar al encender la Raspberry.

**Archivos:**

| Archivo | Para qué |
|---|---|
| [`Dockerfile`](../Dockerfile) | Imagen de Python 3.11 con las dependencias de ejecución y el código |
| [`docker-compose.yml`](../docker-compose.yml) | Los 4 servicios, el orden de arranque, los volúmenes y el puerto serie |
| [`docker/mosquitto.conf`](../docker/mosquitto.conf) | Configuración del broker para Docker |
| [`docker/iniciar_mosquitto.sh`](../docker/iniciar_mosquitto.sh) | Genera los usuarios MQTT desde `portus.env` y arranca el broker |
| [`.dockerignore`](../.dockerignore) | Deja fuera de la imagen los secretos, la base y el firmware |

**Qué va dentro de la imagen y qué no:** el código va dentro. `config/` (secretos) y `db/` (la base) se montan desde la Raspberry, así que:

- **Si cambia `config/portus.env`**, basta reiniciar: `docker compose restart`.
- **Si cambia el código** (`git pull`), hay que recompilar la imagen: `docker compose up -d --build`.

---

## 1. Requisitos de la Raspberry

### 1.1 Sistema operativo de 64 bits

Use **Raspberry Pi OS (64-bit) Bookworm** o más reciente. Compruébelo:

```bash
uname -m              # debe decir aarch64
getconf LONG_BIT      # debe decir 64
```

En un sistema de 32 bits (`armv7l`), `bcrypt` no tiene paquete precompilado. `pip` intentaría compilarlo con Rust dentro de la Raspberry, lo que tarda mucho y suele fallar. Si sale `armv7l`, reinstale el sistema en 64 bits con Raspberry Pi Imager.

### 1.2 Reloj sincronizado

```bash
sudo timedatectl set-ntp true
timedatectl           # "System clock synchronized: yes"
```

Los contenedores usan el reloj de la Raspberry, que no tiene batería. Sin NTP, las citas, alarmas y métricas salen mal (README §3.1). La zona horaria no importa: todo se guarda en UTC.

### 1.3 Instalar Docker y Docker Compose

```bash
curl -fsSL https://get.docker.com -o instalar-docker.sh
sudo sh instalar-docker.sh
sudo usermod -aG docker $USER
sudo systemctl enable docker
```

Después del `usermod`, **cierre la sesión y vuelva a entrar**, o reinicie, para usar `docker` sin `sudo`. Compruebe:

```bash
docker compose version
docker run --rm hello-world
```

### 1.4 Si ya estaba instalado sin Docker

Docker y la instalación con systemd **no pueden correr a la vez**: usan los mismos puertos (1883, 9001, 8000) y el mismo puerto serie. Desactive los servicios nativos:

```bash
sudo systemctl disable --now portus-msg portus-puente portus-web mosquitto
```

Si ya tenía una base en `db/portus.db` creada por el usuario `portus`, cámbiele el dueño, porque los contenedores corren con su usuario:

```bash
sudo chown -R $(id -u):$(id -g) db
```

---

## 2. Código y configuración

### 2.1 Clonar en su carpeta de usuario

```bash
cd ~
git clone <URL-del-repositorio> portus
cd ~/portus
```

Clónelo **con su usuario, sin `sudo`**. Los contenedores escriben `db/portus.db` con su mismo UID: si la carpeta es de root, la web no puede crear la base.

Si su usuario no es el 1000 (el primero de Raspberry Pi OS), dígaselo a Compose:

```bash
id -u; id -g
printf 'PORTUS_UID=%s\nPORTUS_GID=%s\n' "$(id -u)" "$(id -g)" > .env
```

Este `.env` de la raíz solo guarda esos dos números y está en `.gitignore`. No es el `config/portus.env`.

### 2.2 `config/portus.env`

```bash
cp config/portus.env.ejemplo config/portus.env
chmod 600 config/portus.env
nano config/portus.env
```

Es el **mismo archivo** que en la instalación con systemd (README §4). Valores a revisar:

| Clave | Valor con Docker |
|---|---|
| `PUERTO_SERIE` | La ruta estable del Arduino (§3). Ejemplo: `/dev/serial/by-id/usb-Arduino__www.arduino.cc__0042_…-if00` |
| `BAUDIOS` | La misma del `Serial.begin(...)` del firmware: **9600** para `Estacion1_2_3_Combinado.ino` |
| `MQTT_HOST` | `127.0.0.1`, sin cambios: los contenedores usan la red de la Raspberry |
| `MQTT_CONTRASENA`, `MQTT_TABLERO_CONTRASENA`, `MSG_MQTT_CONTRASENA` | Contraseñas nuevas. **No** hace falta `mosquitto_passwd`: el broker crea los usuarios con estos valores en cada arranque |
| `WEB_CLAVE_SECRETA` | Una nueva: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `TELEGRAM_BOT_TOKEN` | Token de @BotFather (README §3.6) |

`config/portus.env` nunca se sube al repositorio ni entra en la imagen.

### 2.3 Usuarios MQTT: se crean solos

`docker/iniciar_mosquitto.sh` lee `config/portus.env` y crea estos usuarios en memoria cada vez que arranca el broker:

| Usuario | Contraseña (en `portus.env`) | Lo usa |
|---|---|---|
| `MQTT_USUARIO` (`portus-puente`) | `MQTT_CONTRASENA` | puente y web |
| `MQTT_TABLERO_USUARIO` (`portus-tablero`) | `MQTT_TABLERO_CONTRASENA` | navegador (solo lectura) |
| `MSG_MQTT_USUARIO` (`portus-msg`) | `MSG_MQTT_CONTRASENA` | bot |

Los permisos de cada usuario salen de `config/acl_portus`, igual que sin Docker. Si cambia una contraseña, reinicie todo (`docker compose restart`), porque cada servicio la lee al arrancar.

---

## 3. El Arduino (puerto serie)

Conecte el Arduino por USB y busque su ruta estable:

```bash
ls -l /dev/serial/by-id/
#   usb-Arduino__www.arduino.cc__0042_5573…-if00 -> ../../ttyACM0
```

- Ponga en `PUERTO_SERIE` la ruta completa `/dev/serial/by-id/…`, no `/dev/ttyACM0`. El número `ACM0`/`ACM1`/`USB0` puede cambiar al reconectar; la ruta `by-id` no.
- El Mega original aparece como `ttyACM*`. Los clones con chip CH340 aparecen como `ttyUSB*`. `docker-compose.yml` permite ambos.
- **Se puede desconectar y reconectar** sin tocar Docker. El contenedor ve todo `/dev`, y el puente reintenta abrir el puerto cada 2 s hasta que el Arduino vuelve.
- El puente abre el puerto como el grupo `dialout`. Compruebe que el dispositivo es de ese grupo, con número 20:

  ```bash
  stat -c '%G %g' /dev/ttyACM0      # esperado: dialout 20
  ```

  Si muestra otro número, cambie `dialout` por ese número en `group_add` de `portus-puente`.
- Recuerde que el Mega **se reinicia cada vez que el puente abre el puerto**: al arrancar el contenedor o al reconectar. Es normal; el firmware guarda la secuencia en EEPROM para no repetirla.

---

## 4. Compilar y levantar

Desde `~/portus`:

```bash
docker compose build
```

- La primera vez tarda **varios minutos** en la Pi 4B: descarga Python y las dependencias.
- Las siguientes compilaciones reutilizan lo ya descargado y solo copian el código.

Cree la base y los datos semilla. Es **una sola vez**, antes del primer arranque:

```bash
docker compose run --rm --no-deps portus-web python -m herramientas.crear_usuarios_semilla --bd db/portus.db
docker compose run --rm --no-deps portus-web python -m herramientas.crear_datos_semilla --ruta-bd db/portus.db
```

- El primero crea el esquema y los 7 usuarios. **Muestra las contraseñas una sola vez**: guárdelas.
- El segundo carga contenedores, vehículos y posiciones del patio (README §3.5).

Levante todo:

```bash
docker compose up -d
docker compose ps
```

Espere a que `portus-mosquitto` y `portus-web` digan `healthy`. Toma unos 20 s.

```
NAME               STATUS
portus-mosquitto   Up 40 seconds (healthy)
portus-msg         Up 25 seconds
portus-puente      Up 26 seconds
portus-web         Up 33 seconds (healthy)
```

**Atajo:** si ya existe la base, `docker compose up -d --build` compila y levanta en un paso.

---

## 5. Verificación

```bash
docker compose logs -f                        # todo junto; Ctrl+C para salir
docker compose logs portus-puente --tail 20   # "Evento del controlador publicado: tipo=EST …"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/login   # 200
docker compose exec mosquitto mosquitto_sub -h 127.0.0.1 -u portus-tablero -P '<clave-tablero>' -t 'portus/#' -v
```

Para el último comando, use la clave de `MQTT_TABLERO_CONTRASENA`. Debe mostrar el latido `portus/evt/estado` cada pocos segundos.

Desde otra computadora de la red:

- Web: `http://<IP-de-la-Raspberry>:8000/`. La IP se ve con `hostname -I`.
- Sinóptico en vivo: va por el puerto 9001 de la misma IP.
- El resto de la verificación y la condición inicial de la demostración son las del README §5.

---

## 6. Operación diaria

| Tarea | Comando |
|---|---|
| Ver registros en vivo | `docker compose logs -f` (o `… logs -f portus-puente`) |
| Estado de los servicios | `docker compose ps` |
| Reiniciar todo | `docker compose restart` |
| Reiniciar solo uno | `docker compose restart portus-puente` |
| Detener todo | `docker compose stop`. Queda detenido aun tras reiniciar la Raspberry |
| Volver a levantar | `docker compose up -d` |
| Actualizar el código | `git pull && docker compose up -d --build` |
| Aplicar cambios de `portus.env` | `docker compose restart` |
| Correr una herramienta | `docker compose run --rm --no-deps portus-web python -m herramientas.<nombre> …` |
| Respaldo de la base | `sqlite3 db/portus.db ".backup 'respaldo-$(date +%F).db'"` (`sudo apt install sqlite3`) |
| Liberar espacio de imágenes viejas | `docker image prune -f` |
| Quitar todo (la base queda en `db/`) | `docker compose down` |

Las migraciones nuevas se aplican solas cuando `portus-web` arranca con el código nuevo.

---

## 7. Lo que hay que tener en cuenta

1. **Red del host.** Los contenedores usan la red de la Raspberry (`network_mode: host`), sin red propia de Docker. Por eso:
   - `MQTT_HOST=127.0.0.1` funciona igual que sin Docker.
   - Las reglas de `ufw` del README §3.8 **siguen aplicando**. Con puertos publicados (`ports:`), Docker se las saltaría.
   - El puerto 1883 solo escucha en localhost. A la red se abren el 8000 (web) y el 9001 (sinóptico).
2. **Un solo despliegue a la vez.** Si `mosquitto` o los servicios systemd siguen activos, Docker falla con «Address already in use» (§1.4).
3. **La base vive en `db/` de la Raspberry**, no dentro del contenedor. `docker compose down`, recompilar o actualizar no la borran. Para empezar de cero hay que borrar `db/portus.db*` a mano.
4. **Arranque al encender.** Docker está habilitado (`systemctl enable docker`) y cada servicio tiene `restart: unless-stopped`, así que al encender la Raspberry todo vuelve solo, en orden. La excepción es si lo detuvo con `docker compose stop`.
5. **El bot necesita internet.** Sin `TELEGRAM_BOT_TOKEN` o sin conexión, `portus-msg` se reinicia en bucle, cada vez más espaciado. El resto de la plataforma no se ve afectado; los avisos esperan en la base.
6. **Tarjeta SD.** Los registros de Docker se limitan a 3 archivos de 10 MB por servicio. Para la demostración conviene una SD de buena calidad o un SSD por USB 3.
7. **Archivos con fin de línea de Windows.** `.gitattributes` obliga a usar LF en `docker/`, `*.sh`, `Dockerfile` y `docker-compose.yml`. Si copia el proyecto a la Raspberry desde Windows por USB, en vez de `git clone`, revise el §8.
8. **Compilar en la PC para la Raspberry.** Es opcional, si la Pi no tiene internet al momento de compilar:

   ```bash
   docker buildx build --platform linux/arm64 -t portus:latest --load .
   docker save portus:latest eclipse-mosquitto:2 | gzip > portus-imagenes.tar.gz
   ```

   Para `eclipse-mosquitto:2`, haga antes `docker pull --platform linux/arm64 eclipse-mosquitto:2`. Copie el `.tar.gz` y, en la Raspberry:

   ```bash
   gunzip -c portus-imagenes.tar.gz | docker load
   docker compose up -d --no-build
   ```

---

## 8. Solución de problemas

| Síntoma | Causa probable / arreglo |
|---|---|
| `portus-mosquitto` se reinicia con `set: illegal option -` o `\r` | `docker/iniciar_mosquitto.sh` tiene fin de línea de Windows: `sed -i 's/\r$//' docker/iniciar_mosquitto.sh` |
| `portus-mosquitto` termina con «Address already in use» | Hay un `mosquitto` nativo corriendo: `sudo systemctl disable --now mosquitto` |
| `iniciar_mosquitto: falta config/portus.env` | No se copió la plantilla (§2.2) |
| Un servicio dice «not authorised» al conectarse a MQTT | Se cambió una contraseña en `portus.env` sin reiniciar todo: `docker compose restart` |
| `portus-puente`: «No se pudo abrir /dev/…; nuevo intento en 2» | Arduino desconectado o `PUERTO_SERIE` equivocado: `ls -l /dev/serial/by-id/`. Al conectarlo, el puente lo toma solo |
| `portus-puente`: «Permission denied» en el puerto | El grupo del dispositivo no es 20: vea `stat -c '%G %g' …` y ajuste `group_add` (§3) |
| Alarma AL01 o sin latido, con el puerto abierto | `BAUDIOS` distinto al del firmware (9600 en el `.ino` combinado) |
| `portus-web` no llega a `healthy`: «unable to open database file» o «readonly database» | `db/` no es de su usuario o el UID no coincide: `sudo chown -R $(id -u):$(id -g) db` y revise `.env` (§2.1) |
| `portus-msg` reinicia en bucle | Falta el token, es inválido o no hay internet: `docker compose logs portus-msg` |
| El sinóptico dice «enlace perdido» | El navegador no llega al 9001: `sudo ufw allow from 192.168.0.0/16 to any port 9001 proto tcp` |
| `docker compose build` falla compilando `bcrypt` | Sistema de 32 bits (§1.1) |
| `permission denied … docker.sock` | Falta cerrar sesión tras `usermod -aG docker` (§1.3) |
