# web/ — núcleo de la aplicación web (Etapa 4 · completa)

Servicio `portus-web` (SPECS §19.2): HTTP con Flask, ejecutado con waitress
(``python -m web --config config/portus.env``). Implementa el núcleo de la
Etapa 4 del ROADMAP:

- **Autenticación** con usuario y contraseña; hashes bcrypt con sal (§7.3).
- **Sesión** con cookie firmada `HttpOnly`, `SameSite=Lax`, expiración por
  inactividad y cierre explícito (§7.3).
- **Usuario y rol visibles de forma permanente** en la cabecera (§7.3.3).
- **Matriz de permisos aplicada en el servidor** en cada endpoint con
  `@requiere_rol(...)`, `403` explícito y auditoría de rechazos (§7.4, §7.5).
  En la Etapa 4 se aplican **2 de las 16 filas** de §7.4 (ver manifiestos y
  generar código de vinculación); las 14 restantes corresponden a las Etapas
  6–10 según el mapa de `docs/despliegue_web.md` §6, no son un faltante.
- **Filtros de propiedad en SQL**: NAVIERA solo ve lo suyo (§7.5.2).
- **Pestañas por rol** exactas del §7.6, construidas en el servidor.
- **Endpoint del código de vinculación** de transportista, solo TERMINAL
  (§15.1, A17); la pantalla llega en la Etapa 6 y el bot en la Etapa 10.

## Capas (CODESTYLE A-2)

```
web/
├── rutas/          # HTTP: valida la entrada en la frontera; sin lógica ni SQL
├── servicios/      # lógica de negocio; no importan Flask
├── repositorios/   # único lugar con SQL; no conocen HTTP
├── modelos/        # Rol, Usuario, pestañas por rol, código de vinculación
├── seguridad/      # hash bcrypt, sesión, matriz de permisos (@requiere_rol)
├── configuracion/  # lectura de config/portus.env (WEB_*)
├── contexto.py     # contexto inyectado a las rutas (PY-7)
├── aplicacion.py   # fábrica de la app Flask + control de inactividad (T-3)
├── tiempo.py       # marcas de tiempo UTC (PY-5, BD-5)
├── __main__.py     # arranque con waitress (producción en el SBC)
└── interfaz/       # plantillas Jinja y CSS (sin frameworks, A-8)
```

El sinóptico y el tiempo real (Etapa 5/6) se actualizarán **solo por
suscripción MQTT sobre WebSocket** (listener 9001 de `config/mosquitto.conf`);
el polling está prohibido (−10 %, SPECS §14.1, JS-2).

Despliegue y credenciales de demostración: `docs/despliegue_web.md`.

## Prueba manual mínima (solo el núcleo web, sin broker ni controlador)

No hace falta mosquitto, ni el puente, ni el controlador: la web arranca sola
sobre su SQLite (§19.3 paso 4 del despliegue). Desde la raíz del repositorio:

```bash
python -m venv venv && . venv/bin/activate           # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp config/portus.env.ejemplo config/portus.env       # la web exige el archivo (S-1)
python -m herramientas.crear_usuarios_semilla --contrasena-terminal terminal123 \
       --contrasena-naviera naviera123 --contrasena-agente agente123 \
       --contrasena-autoridad autoridad123 --contrasena-transportista transportista123
python -m web                                        # http://127.0.0.1:8000/
```

- `crear_usuarios_semilla` crea `db/portus.db` con los 7 usuarios de §7.2 si
  no existe (solo quedan hashes bcrypt, S-3); sin `--contrasena-*` genera una
  aleatoria por usuario y la **imprime una vez**. Las del bloque arriba son
  las de demostración de `docs/despliegue_web.md` §3 (red local aislada).
- La clave de desarrollo de `portus.env.ejemplo` dispara una advertencia y
  vale solo para esta prueba; en el SBC defina una `WEB_CLAVE_SECRETA` propia
  (S-1: `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
- Qué verificar a mano: login con `terminal01` → 8 pestañas (§7.6) y usuario
  + rol permanentes en la cabecera (§7.3.3); `naviera01` → 2 pestañas y solo
  sus manifiestos; `transportista01` → 403 `SIN_ACCESO_WEB`; una pestaña
  ajena escrita a mano en la URL → 404; sin sesión, `/api/manifiestos` → 401.
