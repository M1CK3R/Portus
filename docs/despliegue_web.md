# Despliegue del núcleo web — Etapa 4

Servicio `portus-web`: HTTP + lógica de negocio sobre el SBC (SPECS §19.1–19.2).
Este documento cubre el núcleo de la Etapa 4: autenticación, sesión, matriz de
permisos, pestañas por rol y código de vinculación.

## 1. Decisiones de diseño [DEC]

| Decisión | Elección | Justificación |
|---|---|---|
| Framework web | **Flask** (de «Flask o FastAPI», §19.2) | Sincrónico y liviano para el SBC; Jinja en el servidor para renderizar solo las pestañas del rol (§7.6); coincide con el estilo multihilo del puente. |
| Servidor WSGI | **waitress** (pinned) | El servidor de desarrollo de Flask no es apto para producción; waitress es puro Python, multihilo y sin bloqueo cruzado (PY-4). |
| Sesión | **Cookie firmada** por Flask (§7.3 [PROP] literal) | `HttpOnly`, `SameSite=Lax`, `PERMANENT_SESSION_LIFETIME` como tope absoluto y expiración por inactividad controlada con reloj inyectable (T-3). El cierre explícito borra la cookie del navegador; el estado vive firmado en el cliente, sin tabla de sesiones. |
| Hash de contraseñas | **bcrypt** con sal y 12 rondas (§7.3, S-3) | Propuesta del SPECS/ROADMAP; el servicio de mensajería y la creación de usuarios comparten el mismo módulo. |
| Acceso web de TRANSPORTISTA | **Rechazado con 403 explícito** (§7.1) | «Cuatro operan en la web; uno solo por mensajería»: el login del transportista no abre sesión; es una denegación de rol auditada. |
| Base de datos | `db/portus.db` compartida con el puente, **WAL** activado | Layout único de §19.2; WAL permite que el puente escriba eventos mientras la web lee, sin bloquearse. |
| Auditoría | Tabla `auditoria_rechazo` (§7.5.5) | Cada 403, cada login fallido **y también el 404 de transportista inexistente en vinculación** registra usuario, acción, recurso, motivo y momento: evidencia de P10 y E12/R13, y trazabilidad del sondeo de ids (D-6: ningún rechazo en silencio). |
| Código de vinculación | 6 caracteres, alfabeto sin `0/O` ni `1/I/L`, `secrets`, un solo uso, 60 min, invalida el anterior (§15.1) | Generación criptográfica (PY-8); el consumo (Etapa 10) compara en tiempo constante con `hmac.compare_digest`. |
| Recurso ajeno | **404** en lugar de 403 (§7.5.2, decidido y documentado) | No revela la existencia de recursos de otra naviera/transportista. |

## 2. Estructura y despliegue

```
/opt/portus/
├── web/                  # este servicio (python -m web)
├── db/portus.db          # SQLite compartida con el puente (WAL)
├── config/portus.env     # WEB_PUERTO, WEB_CLAVE_SECRETA, WEB_EXPIRACION_INACTIVIDAD_MIN...
└── venv/                 # dependencias fijadas de requirements.txt
```

1. `pip install -r requirements.txt` en el venv del SBC (flask, bcrypt, waitress
   con versión fija, A-8).
2. `cp config/portus.env.ejemplo config/portus.env` y definir **`WEB_CLAVE_SECRETA`**
   (S-1: `python -c "import secrets; print(secrets.token_urlsafe(32))"`), `WEB_PUERTO`
   y los tiempos de sesión.
3. Crear la base y aplicar el esquema: la primera ejecución lo hace sola
   (`db/esquema.sql`, migraciones 001 + 002).
4. Crear los **7 usuarios mínimos** (§7.2): `python -m herramientas.crear_usuarios_semilla`
   (contraseñas por argumento, por entorno o aleatorias impresas una vez; solo
   quedan hashes bcrypt en la base, S-3).
5. Instalar el servicio: `config/systemd/portus-web.service` (`After=mosquitto`,
   `Before=portus-bridge`, orden §19.2: mosquitto → portus-web → portus-bridge → portus-msg).
6. Verificar desde otro equipo de la red local: `http://<ip-del-sbc>:8000/`.

## 3. Usuarios y credenciales de la demostración (§7.2)

Deben entregarse «creados y funcionales, con credenciales en la documentación».
Las de esta tabla son **de demostración en red local aislada**; en
`config/portus.env` solo vive `WEB_CLAVE_SECRETA` (S-1), nunca estas contraseñas
(en la base van solo sus hashes bcrypt).

| Usuario | Rol | Contraseña demo | Acceso |
|---|---|---|---|
| `terminal01` | TERMINAL | `terminal123` | Web, 8 pestañas (§7.6) |
| `naviera01` | NAVIERA | `naviera123` | Web, 2 pestañas, solo lo suyo (§7.5.2) |
| `naviera02` | NAVIERA | `naviera123` | Web, 2 pestañas, solo lo suyo |
| `agente01` | AGENTE | `agente123` | Web, 2 pestañas |
| `autoridad01` | AUTORIDAD | `autoridad123` | Web, 3 pestañas |
| `transportista01` | TRANSPORTISTA | `transportista123` | **Sin web** (403); canal de mensajería (Etapa 10) |
| `transportista02` | TRANSPORTISTA | `transportista123` | **Sin web** (403); canal de mensajería (Etapa 10) |

Para otra contraseña por rol al poblar:
`python -m herramientas.crear_usuarios_semilla --contrasena-terminal <nueva> ...`.

## 4. API implementada en la Etapa 4 (§18)

| Método y ruta | Rol(es) | Notas |
|---|---|---|
| `POST /api/login` | Todos (web) | Única ruta pública; TRANSPORTISTA → 403 `SIN_ACCESO_WEB`. |
| `POST /api/logout` | Cualquier sesión | Cierre explícito (§7.3). |
| `GET /api/sesion` | Cualquier sesión | Nombre y rol para mostrarlos de forma permanente (§7.3.3). |
| `POST /api/transportistas/{id}/codigo-vinculacion` | **TERMINAL** | 6 caracteres, un uso, 60 min, invalida el anterior; 404 si el id no es transportista, **quedando auditado** con motivo `transportista_inexistente` (§15.1, A17). La pantalla va en la Etapa 6, pestaña Citas. |
| `GET /api/manifiestos` | TERMINAL, NAVIERA (propios), AGENTE, AUTORIDAD | El filtro `WHERE naviera_id = ?` viaja en la consulta SQL (§7.5.2); demostración del aislamiento P11. |

Códigos de estado (§18): `401` sin sesión o sesión expirada · `403` rol no
permitido (`ACCION_NO_PERMITIDA`, con mensaje explícito) o sin acceso web ·
`404` inexistente · `422` validación de campos. Toda la API responde errores
JSON uniformes `{"error", "mensaje"}` sin detalles internos (S-5).

## 5. Pruebas

`pytest pruebas/test_autenticacion_web.py pruebas/test_matriz_permisos.py
pruebas/test_propiedad_navieras.py pruebas/test_vinculacion.py
pruebas/test_pestanas_por_rol.py pruebas/test_configuracion_web.py`

Cubren: login/logout y banderas de cookie, hash bcrypt en la base (S-3),
expiración por inactividad con reloj inyectado (T-3), la matriz completa por
rol y endpoint (P10), aislamiento entre navieras (P11), ciclo completo del
código de vinculación —incluido que el 404 por transportista inexistente
queda auditado (D-6)— y pestañas exactas por rol (§7.6).

## 6. Alcance de la matriz §7.4 en esta etapa (2 de las 16 filas)

De las 16 acciones de la matriz §7.4, la Etapa 4 aplica en el servidor estas
dos: **Ver manifiesto completo** (`ACCION_VER_MANIFIESTOS`) y **Generar código
de vinculación** (`ACCION_GENERAR_CODIGO_VINCULACION`). Las 14 restantes **no
son un faltante de esta etapa**: el ROADMAP las asigna a etapas posteriores y
cada una se declara como `Accion` en `web/seguridad/permisos.py` cuando su
endpoint existe.

| Acción pendiente (§7.4) | Etapa que la implementa |
|---|---|
| Ver sinóptico · agenda completa de citas · reporte de corrida | 6 (paneles de comandos, alarmas y retenciones completan su lógica en 8–9) |
| Crear manifiesto · declaración y solicitar levante · otorgar o retener levante · canal de selectivo · consultar ubicación (NAVIERA/AGENTE/AUTORIDAD) | 7 |
| Retención operativa (TERMINAL) · retención aduanera (AUTORIDAD) · corregir peso declarado | 8 |
| Emitir comandos remotos · reconocer alarmas | 9 |
| Solicitar cita · consultar ubicación «solo los propios» de TRANSPORTISTA | 10 (vía bot, §7.5.6) |

## 7. Pendientes que cruzan etapas (no perder de vista)

- **Filtro de propiedad de TRANSPORTISTA.** La fila «Consultar ubicación de un
  contenedor» dice «Solo los propios» también para TRANSPORTISTA, y §7.5.6
  exige que el mismo control de propiedad aplique al servicio de mensajería
  («cada consulta se filtra por el transportista vinculado a la cuenta»).
  Como TRANSPORTISTA no tiene web, ese filtro **se implementa con el bot en la
  Etapa 10**, dentro de cada handler que consulte carga: el ROADMAP no lo
  repite explícitamente en la Etapa 10, así que este punto es el recordatorio
  contractual. Lo mismo aplica al consumo del código de vinculación
  (`consumir`, ya implementado y probado en el servicio) y a cualquier
  consulta futura por `transportista_id`.
- **Traducción de la frontera (I-4).** Cuando llegue la Etapa 10, los nombres
  en inglés de la Bot API de Telegram (`chat_id`, `callback_data`,
  `retry_after`) se aceptan solo en la capa que los lee y se convierten a
  español al entrar (`id_chat`, etc.). En el código de las Etapas 1–4 no
  existe ningún identificador de frontera en inglés.
