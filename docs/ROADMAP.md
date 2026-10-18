# PORTUS — Fase 2 · Ruta de trabajo (ROADMAP)

Ruta derivada de `SPECS.md` v0.3. Cada punto es accionable y cita entre paréntesis la sección del SPECS de referencia. Marca `[ ]` al completar.

> Para no confundir las **fases del proyecto** (Fase 1, 2 y 3 de PORTUS) con los bloques de este plan, aquí se usan **Etapas**.

**Leyenda:** 🔴 requisito eliminatorio · ⚠️ penalización si se hace mal · 🎯 concentra puntos de rúbrica · ⏩ puede correr en paralelo

---

## Barreras y penalizaciones (leer primero)

**Requisitos para optar a calificación (§23.2).** Incumplir cualquiera implica no ser calificado:

- 🔴 1. La maqueta de la Fase 1 sigue operativa; perder funcionalidad anterior invalida la entrega.
- 🔴 2. El control determinista vive en el microcontrolador (pulsos, pesaje, paro de emergencia).
- 🔴 3. La maqueta opera de forma segura con el servidor apagado.
- 🔴 4. La operación demostrada se origina desde la plataforma, no desde registros precargados.
- 🔴 5. Las 8 pestañas del rol TERMINAL existen y funcionan.
- 🔴 6. El canal de mensajería (bot de Telegram) se demuestra desde un teléfono.
- 🔴 7. Se entrega el código fuente completo (firmware y plataforma).
- 🔴 8. Se entrega la evidencia de fabricación 3D actualizada.
- 🔴 9. **Todos** los integrantes participan en la presentación y responden sobre **cualquier** parte del sistema.

**Penalizaciones (§23.3):**

- ⚠️ −10 %: tablero por polling · un solo protocolo para todo · permisos solo ocultando botones · retención resuelta por un rol no facultado · comando ejecutado pese a su condición de rechazo · inventario inconsistente tras aborto o rechazo.
- ⚠️ −15 %: esperas bloqueantes en tareas críticas del controlador · plataforma sobre PC sin autorización expresa.

---

## Organización del equipo

**Carriles de responsabilidad** (la bitácora exige registrar integrantes responsables; enunciado §7 y §5.8):

- **Control** — firmware del controlador, enclavamientos, modo degradado, pantallas físicas. Responsable: `________`
- **Comunicación** — protocolo serial, puente, broker Mosquitto, tópicos, despliegue en el SBC. Responsable: `________`
- **Aplicación** — servicios web, lógica del turno, interfaces por rol, bot de Telegram, métricas. Responsable: `________`
- **Pruebas, fabricación y documentación** — plan de pruebas, impresión 3D, bitácora, documento técnico, ensayo de demo. Responsable: `________`

> Todos rotan al menos una vez por la integración: la barrera 🔴 9 exige que cualquier integrante responda sobre cualquier módulo.

**Qué corre en paralelo desde el día 1 (⏩):**

- Firmware (carril Control) tras cerrar el diseño del protocolo.
- Infraestructura del SBC (carril Comunicación): SO, Mosquitto, servicios, datos semilla.
- Impresión 3D (carril Fabricación): imprimir toma tiempo y no depende del software.
- Alta del bot en @BotFather y pruebas de long polling (carril Aplicación).

**Fechas internas.** El cronograma oficial está "por definir" (§23.5). Llenar al publicarse:

| Hito | Etapas | Fecha interna |
|---|---|---|
| H1 · Diseño congelado | 0–1 | `__/__` |
| H2 · Enlace serial + broker + sinóptico básico + prueba mínima de servidor apagado | 2–3 | `__/__` |
| H3 · Happy path de depósito desde la plataforma (E01–E05); la cita se crea con un endpoint de pruebas **temporal** hasta tener el bot | 4–7 y 11 | `__/__` |
| H4 · Retenciones, comandos y alarmas | 8–9 | `__/__` |
| H5 · Bot de Telegram y métricas; retirar el endpoint de pruebas | 10 y 12 | `__/__` |
| H6 · Integración, E01–E15 en continuo, piezas 3D terminadas | 13–14 | `__/__` |
| H7 · Entrega y ensayo final | 15 | `__/__` |

---

## Etapa 0 · Investigación y preparación

- [ ] Estudiar los temas exigidos: serial micro↔SBC, protocolo delimitado con verificación y secuencia, publicación/suscripción, servicios web con control de acceso por rol, persistencia, sinópticos en tiempo real, reparto borde/servidor, reconciliación, servicios sobre mensajería (Bot API de Telegram) y cadena documental de levante y selectivo (§24.5).
- [ ] Verificar y reparar toda la funcionalidad conservada de la Fase 1: garita, pesaje con meseta, aguja y señalización, transferencia con guía y detección de movimiento, grúa con referenciado y agarre, patio a 2 niveles, concurrencia de 3 vehículos, paro con rearme (§1.3).
- [ ] Aprovisionar herramientas: Arduino IDE, SO del SBC, Mosquitto, Python + pySerial, Flask/FastAPI, SQLite/PostgreSQL, `python-telegram-bot` v20+, software de diseño paramétrico, Fritzing, GitHub, gestor de tareas (§24.6).
- [ ] Abrir repositorio, bitácora y tablero de tareas desde el día 1, con responsables asignados.

**Recursos físicos para la demostración** (enunciado §2 y requerimientos técnicos):

- [ ] Al menos **4 vehículos** con RFID propio: E11 requiere 3 retenidos ocupando las plazas y un 4.º con canal rojo que es rechazado.
- [ ] Vehículos adicionales si se quiere demostrar concurrencia sin desarmar el parqueo.
- [ ] Suficientes **contenedores identificados** (registrados en el catálogo) para dejar pilas de 2 niveles y forzar una **remoción** en E15, más el de E06–E08.
- [ ] **Dos teléfonos** (o teléfono + Telegram Web/Desktop) con cuentas de Telegram distintas para los 2 transportistas.
- [ ] Salida a internet para el SBC durante la demo, con **hotspot móvil** como plan B (§15.4).
- [ ] 🎯 **Cableado ordenado y asegurado**, sin conexiones expuestas ni elementos que interfieran con el camión o la grúa: es requisito evaluable (§20).

## Etapa 1 · Diseño previo (obligatorio antes de programar) 🎯

> No iniciar implementación sin comprobar que la arquitectura **conserva el control determinista en el micro** y **permite operar sin servidor** (§24.1).

- [ ] Diagrama de despliegue con dispositivos, servicios y enlaces, incluyendo la salida HTTPS hacia la Bot API (§2.1).
- [ ] Protocolo serial: trama, delimitación, CRC, número de secuencia, tipos de mensaje incluidos `AUT`, `JOB`, `PING`, `SYN` (§4).
- [ ] Espacio de tópicos `portus/evt/*`, `portus/cmd/*` y `portus/srv/*`, con el prefijo **`portus` exacto** (sin sufijos de grupo; lo exige el enunciado) guardado en una constante `TOPIC_PREFIX` compartida por puente, web, bot, sinóptico y ACL, y con envoltorio JSON único (§5.1–5.3).
- [ ] Modelo de datos: usuarios, manifiestos (con historial), declaraciones, turnos, línea de tiempo, citas, franjas, retenciones, plazas, alarmas, eventos, telemetría, intentos de ingreso, códigos de vinculación, vínculos de mensajería, notificaciones (§17).
- [ ] Matriz de permisos por rol y acción (§7.4).
- [ ] Máquina de estados del turno con 10 estados, transiciones y mapa de regreso tras retención (§8).
- [ ] Catálogo de los 13 comandos con condiciones de rechazo y dónde se expone cada uno en la UI (§6).
- [ ] Tabla de reparto controlador/servidor (§3.1).
- [ ] Procedimiento ante pérdida de comunicación y reconciliación (§3.3).
- [ ] Bosquejo de cada pestaña con sus controles (§14).
- [ ] Flujos del bot: vinculación, `/cita` multipaso y notificaciones (§15).
- [ ] Cerrar por escrito con el catedrático/auxiliar las ambigüedades A1–A17, en especial: A1 (`Programado`), A2 (regreso de `Retenido`), A3 (ubicación física del retenido), A4/A5 (fórmula de peso con tara), A9 (cómo ordena AUTORIDAD un RT05), A15 (fuente de vehículos en espera), A17 (dónde se genera el código de vinculación) y si `/inicio` responde distinto a un usuario no vinculado (§25, §15.4).

## Etapa ⏩ A · Fabricación 3D (en paralelo desde el inicio) 🔴

> Imprimir y reimprimir toma tiempo; esta etapa corre durante todo el proyecto y termina antes del hito H6 (§20.1).

- [ ] Inventariar los componentes constructivos y mecánicos identificables y calcular el porcentaje actual impreso.
- [ ] Si no se alcanza el **40 % diseñado o adaptado por el grupo**, planificar las piezas faltantes. Si ya se alcanzó en la Fase 1, solo documentar y entregar archivos.
- [ ] Priorizar las piezas de las que depende la confiabilidad:
  - [ ] Contenedores con alojamiento integrado para la placa ferrosa en la cara superior.
  - [ ] Guías de autocentrado de cada celda del patio.
  - [ ] Vehículos con distancia entre ejes consistente y base estable para el pesaje (sirven también para los 4 vehículos de E11).
  - [ ] Soporte del cabezal de la grúa y alojamiento del mecanismo de agarre.
  - [ ] Soportes de sensores, marcas ópticas del riel y alojamientos de lectores.
  - [ ] Estructura de señalización y soportes de pantallas.
- [ ] Piezas **funcionales**, no decorativas.
- [ ] Conservar archivos **editables** (fuente del diseño paramétrico) y de **fabricación** (STL/3MF/OBJ) en el repositorio.
- [ ] Documentar **procedencia y adaptaciones** de todo modelo de terceros.
- [ ] ⚠️ No dividir piezas en elementos pequeños solo para inflar el conteo.
- [ ] Fotografiar cada pieza instalada y registrar su ubicación en la maqueta; marcar cuáles se refabricaron en esta fase.

## Etapa 2 · Extensión del firmware (carril Control) 🔴

> Extender el firmware de la Fase 1 **sin alterar** su estructura de control ni su determinismo (§3.2, §24.4).

**Origen de datos**

- [ ] **Retirar los registros precargados** de camiones, manifiestos y operaciones; el controlador opera solo con lo que recibe del servidor (barrera 🔴 4).
- [ ] Recibir y almacenar los datos del turno mediante `AUT` (turno, vehículo, tipo de operación, peso declarado, tolerancia, canal, posición asignada) (§4.4, A6).
- [ ] Recibir trabajos de grúa mediante `JOB` (tipo, origen, destino, nivel) y encolarlos en la cola del controlador (§4.4, §12.5.1).

**Comunicación**

- [ ] Tramas con delimitación, CRC-16 y `SEQ` creciente; descarte de tramas inválidas con contador de errores (§4.2).
- [ ] Cola circular de salida; escribir solo cuando haya espacio en el UART (§4.2).
- [ ] ACK/NAK con causa para cada comando; idempotencia ante `SEQ` repetido (§4.5).
- [ ] Atender `SYN` (reenviar desde un `SEQ` y/o volcar estado) (§4.3).
- [ ] Latido `EST` con periodo ≤ 5 s: modo, grúa, aguja, cola, vehículos en espera, contadores (§5.4).
- [ ] Emitir los **9 tipos de evento**: `GAR`, `PES`, `AGU`, `TRF`, `GRU`, `PAT`, `SAL`, `ALM`, `EST` (§4.3).
- [ ] Generar las alarmas propias del controlador: **AL02** paro, **AL03** pérdida de referencia, **AL04** pérdida de carga, **AL05** agarre no confirmado, **AL06** trabajo abortado, **AL07** altura vs inventario, **AL08** movimiento en transferencia, **AL10** vehículo incorrecto en salida (reporta; el servidor genera) (§13.1).

**Seguridad y comandos**

- [ ] Validar los 13 comandos contra los enclavamientos vigentes (§6.1).
- [ ] En modo mantenimiento rechazar trabajos de turnos pero aceptar `GruaReferenciar` (§6.2).
- [ ] Parqueo de 3 plazas y tercer estado de la aguja (recta / parqueo / liberar) (§10).
- [ ] Paro de emergencia solo local; no accionable ni rearmable por comando (§6.2).

**Autonomía**

- [ ] **Vigilancia del servidor**: si no llega `PING` ni mensaje válido durante 3 periodos, entrar en modo degradado (§3.4, A13).
- [ ] **Modo degradado explícito** (§3.3):
  - [ ] Terminar de forma segura el trabajo de grúa en curso.
  - [ ] Completar los turnos que ya están dentro con la última información recibida (`AUT`/`JOB`).
  - [ ] Rechazar todo ingreso nuevo.
  - [ ] Mostrar **«modo degradado»** en la pantalla de garita.
  - [ ] Guardar eventos en búfer circular local, sin descartar nunca confirmaciones de inventario, alarmas ni cambios de turno (§3.5).
- [ ] Al reconectar, transmitir estado real y eventos acumulados para reconciliación (§3.3).

**Pantallas físicas**

- [ ] Mostrar en la pantalla de garita la **causa del rechazo** recibida del servidor en `AUT` con `resultado=RECHAZADO` y `causa` (E03 levante retenido, E11 parqueo lleno) (§4.4, §9.4).

**Revisión**

- [ ] ⚠️ Revisión de código: **cero esperas bloqueantes** (`delay()`, lecturas bloqueantes, `while` de espera) en tareas críticas; el envío serial no bloquea pulsos, pesaje ni paro (§3.2).

## Etapa 3 · Infraestructura del SBC (carril Comunicación) ⏩

> Serial + MQTT + HTTP (+ Telegram para el transportista). Un solo protocolo para todo penaliza (§2.3).

- [ ] Instalar SO y paquetes en el SBC; nunca usar PC en la evaluación sin autorización (§19.1). ⚠️
- [ ] Puente serial (pySerial): parseo de tramas, CRC, detección de saltos de `SEQ` y solicitud `SYN`, timeout de 2 s con NAK sintético `SIN_RESPUESTA` (§4.2, §4.5).
- [ ] Mosquitto con listener TCP 1883 **y listener MQTT sobre WebSocket**: sin él el navegador no puede suscribirse y el sinóptico caería en polling (§5.5). ⚠️
- [ ] Credenciales por servicio y **ACL**: cada cliente solo en sus tópicos, con patrones basados en `TOPIC_PREFIX`; el navegador en solo lectura (§5.5).
- [ ] QoS 1 en eventos, comandos y respuestas; QoS 0 en latido; `retain` en `portus/evt/estado`; Last Will del puente en `portus/srv/enlace` (§5.5).
- [ ] **Deduplicación por `id`** en todos los consumidores (persistencia, lógica, bot) (§5.5).
- [ ] Persistencia de eventos y telemetría suscrita a `portus/#` (§5.7).
- [ ] Vigilante de enlace: 3 latidos ausentes → AL01; AL01 retroactiva al arrancar si hubo caída del servidor (§5.4, A14).
- [ ] Emisor de `PING` hacia el controlador (§3.4).
- [ ] 🔴 **Prueba temprana (H2):** apagar el servidor a mitad de un trabajo de grúa y comprobar modo degradado y reconciliación, aunque sea en versión mínima. Es la barrera 3 y condiciona el firmware desde la Etapa 2.
- [ ] Esquema de BD (`esquema.sql`) y **datos semilla**: catálogo de contenedores, franjas, plazas 1–3, posiciones del patio, vehículos con su RFID y tara, y los **7 usuarios** (§19.3, A10).
- [ ] Servicios systemd con **arranque y reinicio automático**, en orden `mosquitto` → `portus-web` → `portus-bridge` → `portus-msg` (§19.2).
- [ ] `config/portus.env` con puerto serie, credenciales, `TELEGRAM_BOT_TOKEN` y `politica_asignacion`; excluido del repo por `.gitignore` (§19.2).

## Etapa 4 · Núcleo de la aplicación web

- [ ] Autenticación con usuario y contraseña; contraseñas con hash (bcrypt/argon2), nunca en texto plano (§7.3).
- [ ] Usuario en sesión y rol visibles de forma permanente (§7.3).
- [ ] ⚠️ Matriz de permisos aplicada **en el servidor** en cada endpoint, con error explícito al rechazar (§7.4, §7.5).
- [ ] Filtros de propiedad en servidor: naviera solo ve lo suyo, transportista solo su carga (§7.4).
- [ ] Mostrar solo las pestañas del rol, sin eliminar ni fusionar las exigidas (§7.6).
- [ ] Endpoint del **código de vinculación** de transportista (solo TERMINAL); la pantalla va en la Etapa 6, pestaña Citas (§15.1, §14.5, A17).

## Etapa 5 · Lógica del turno en el servidor (carril Aplicación) 🔴 🎯

> Es lo que hace que la operación **se origine desde la plataforma**. Sin esta etapa no se cumplen la barrera 4 ni la mayoría de escenarios (§8, §9.4, §12).

**Validación de garita (§9.4)**

- [ ] Al recibir `GAR`, validar en orden: vehículo registrado → manifiesto vigente → levante otorgado (no retenido) → cita vigente → riesgo de retención (canal rojo o fuera de ventana) con plaza disponible.
- [ ] Causas: `VEHICULO_DESCONOCIDO`, `SIN_MANIFIESTO`, `SIN_LEVANTE` / `LEVANTE_RETENIDO`, `SIN_CITA`, `PARQUEO_LLENO` (+ AL11).
- [ ] Un rechazo **no crea turno** pero **registra el intento** con su causa (§8.2 regla 1).
- [ ] Responder **siempre** al controlador con `AUT`: `resultado=AUTORIZADO` con los datos del turno, o `resultado=RECHAZADO` con la `causa` para la pantalla de garita (§4.4).
- [ ] Fuera de ventana con plaza disponible no es rechazo: genera RT04 (§9.4, §11.1).

**Máquina de estados (§8)**

- [ ] Implementar los **10 estados** exactos y rechazar transiciones no permitidas.
- [ ] Crear el turno al autorizar (decisión A1 documentada).
- [ ] Guardar `estado_previo_retencion` y aplicar el mapa de regreso tras Aclarar/Corregir (A2).
- [ ] Conservar pesajes y datos al pasar a `Retenido` (§8.2 regla 3).
- [ ] Registrar cada evento en la **línea de tiempo** (segundo, origen, descripción, valores).
- [ ] Publicar cada cambio en `portus/srv/turno`.

**Pesaje y ruta**

- [ ] Comparar peso contra tolerancia con la fórmula documentada (tara, entrada, salida; A4) y revalidar el resultado del controlador (A5).
- [ ] RT01 si la entrada excede tolerancia; RT02 si la salida excede; AL09 en ambos.
- [ ] Canal rojo → RT03 inmediatamente después del pesaje de entrada (§9.2).

**Patio, plazas y grúa**

- [ ] 🎯 Conservar la **política de asignación de la Fase 1 como modo seleccionable** (`politica_asignacion = FASE1` por defecto) detrás de una interfaz `asignar_posicion(contenedor, inventario)`; sin ella no hay línea base para la Fase 3 (§12.4).
- [ ] Reservar la posición en depósitos; solo pasa a ocupada con confirmación física (§12.3).
- [ ] Asignar la **plaza libre de menor número** al retener y liberarla al resolver; enviar `AgujaParqueo` al retener y `AgujaLiberar` al resolver; hacerlo en **transacción con bloqueo** para que dos retenciones simultáneas no tomen la misma plaza (§10.1, §10.6, P08).
- [ ] Generar trabajos `JOB`: depósito, retiro y **remociones** necesarias (destino libre para el removido; el retiro no inicia hasta completar las remociones) (§12.5).
- [ ] Actualizar inventario y contador de remociones solo con `PAT`/`GRU` confirmados (§8.2 regla 2).

**Salida, cierre y anulación**

- [ ] Verificar con `SAL` que el vehículo en salida sea el del turno: si coincide, enviar `AbrirPuertaSalida` y cerrar el turno al confirmarse la salida; si no, AL10 y no autorizar (§8.6, §13.1).
- [ ] Cerrar el turno (`Cerrado`), marcar cumplimiento de la cita y notificar.
- [ ] Anular con inventario reflejando la posición física real y autorizar la salida sin completar con `AbrirPuertaSalida` (§8.2 regla 4, §8.6).
- [ ] Ningún turno queda abierto si el vehículo ya salió (§8.2 regla 5).

**Reconciliación**

- [ ] Al reconectar, aplicar eventos acumulados en orden de `SEQ`, ajustar inventario y turnos al estado real, y registrar el resultado en la bitácora de eventos (§3.3).

## Etapa 6 · Interfaz del rol TERMINAL (8 pestañas) 🔴 🎯

> Sub-checklist por pestaña según §14 y §6.3. Los controles listados son los que se evalúan.

**1. Operación (§14.1, §6.3)**

- [ ] Sinóptico con los 13 elementos: zona de espera, garita, talanquera, pesaje, aguja, parqueo (3 plazas con vehículo y tiempo), transferencia, grúa, cola, patio por nivel, puerta de salida, enlace, modo.
- [ ] ⚠️ Actualización por **suscripción MQTT sobre WebSocket**, sin polling; retardo ≤ 2 s.
- [ ] Enlace perdido visible, datos dejan de mostrarse como actuales y se muestra el **timestamp del último estado**.
- [ ] Botones Suspender, Reanudar (solo si suspendida), Referenciar (solo en reposo o suspendida).
- [ ] **Confirmación del usuario** en `AbrirTalanquera`, `AbrirPuertaSalida` y `ModoMantenimiento`.
- [ ] Liberar parqueo solo si la plaza está ocupada y su retención fue resuelta.
- [ ] Panel de comandos manuales para `CerrarTalanquera`, `AgujaRecta`, `AgujaParqueo` (A8).
- [ ] Mostrar la respuesta ACK/NAK de cada comando con su causa.
- [ ] Clic en posición del patio → detalle con Bloquear/Liberar; clic en vehículo → detalle del turno.

**2. Turnos (§14.2)**

- [ ] Secciones separadas de activos e históricos con todas las columnas exigidas.
- [ ] Filtros por estado, tipo y fecha; búsqueda por contenedor o vehículo.
- [ ] Ver detalle → línea de tiempo completa, también para turnos cerrados o anulados.
- [ ] **Retener** (RT06) con observación opcional.
- [ ] **Anular** turno y autorizar salida.

**3. Retenciones (§14.3, §10)**

- [ ] Listas de abiertas y resueltas con los 9 campos, incluida la evidencia de peso.
- [ ] Aclarar, Corregir (solo TERMINAL, solo RT01/RT02 según A12), Rechazar con motivo obligatorio.
- [ ] Filtros por causa y estado; botones ocultos para roles no facultados y rechazo en servidor.

**4. Patio (§12.2)**

- [ ] Representación por posición y nivel + tabla de inventario con los 8 campos.
- [ ] Bloquear y Liberar posición (Liberar solo si está bloqueada).
- [ ] Ordenamiento por permanencia e indicador de permanencia > 2 h.

**5. Grúa (§12.6)**

- [ ] Posición, trabajo en curso y cola con tipo y orden.
- [ ] Gráfica de tiempo de ciclo con selector 50/100/200; ciclos completados y promedio.
- [ ] Historial de fallas.
- [ ] **Exportar historial en CSV** del rango seleccionado.

**6. Alarmas (§13.3)**

- [ ] Listas de activas e históricas; ninguna desaparece sola.
- [ ] Reconocer con comentario opcional.
- [ ] **Reconocer todas solo para baja y media**; críticas y altas una por una.
- [ ] Filtro por severidad; botón Silenciar (`AlarmaSilenciar`, A8).

**7. Citas (§14.5, §11.4)**

- [ ] Agenda del día por franjas con capacidad, asignadas y lista de citas; selector de fecha.
- [ ] **Cancelar** y **reprogramar** cita (ambas notifican al transportista).
- [ ] **Bloquear franja**.
- [ ] Indicador de cumplimiento del día.
- [ ] Panel **Vinculación de transportistas** (A17): lista con estado vinculado / sin vincular y botón **Generar código** (6 caracteres, un uso, vence a los 60 min, muestra el tiempo restante e invalida el anterior) (§14.5, §15.1).

**8. Reportes (§14.6)**

- [ ] Selector de rango, botón Generar con las 8 métricas.
- [ ] **Campo Etiqueta de corrida**.
- [ ] Exportar CSV con el detalle de cada turno del periodo.

## Etapa 7 · Cadena documental: NAVIERA, AGENTE y AUTORIDAD 🎯

> Objetivo: una decisión en pantalla produce un efecto físico verificable en la talanquera (§9).

**NAVIERA · Manifiestos (§14.7, §9.3)**

- [ ] Lista con ID, contenedor, tipo, peso, tolerancia, estado documental y operativo.
- [ ] Formulario con validaciones: contenedor **existente en el catálogo**, tipo obligatorio, peso entero > 0, **tolerancia 5 % por omisión**, transportista registrado, observaciones opcionales.
- [ ] Rechazar con causa si el contenedor ya tiene **un manifiesto pendiente**.
- [ ] Ver detalle con **historial** del manifiesto (incluye el peso anterior tras *Corregir*).
- [ ] **Anular manifiesto** solo si aún no tiene turno.

**NAVIERA · Mis contenedores (§14.7)**

- [ ] Solo contenedores de esa naviera, con ubicación, estado, autorización y reloj de permanencia; búsqueda y filtro, sin acciones.
- [ ] Aislamiento entre las dos navieras aplicado en el servidor.

**AGENTE · Declaraciones (§14.8, §9.3)**

- [ ] Manifiestos de cualquier naviera sin levante.
- [ ] Presentar declaración: número **único**, régimen, descripción **≥ 10 caracteres**, valor > 0.
- [ ] Solicitar levante solo con declaración presentada.
- [ ] Adjuntar observación visible para la autoridad.

**AGENTE · Seguimiento (§14.8)**

- [ ] Estado de todas sus solicitudes (pendiente, autorizada, retenida), canal y motivo; filtro y búsqueda por número de declaración, sin acciones.

**AUTORIDAD · Solicitudes de levante (§14.9)**

- [ ] Lista con manifiesto, contenedor, naviera, agente, declaración y peso.
- [ ] Otorgar levante obligando a elegir canal verde o rojo.
- [ ] Retener con causa; Ver declaración.

**AUTORIDAD · Retenciones aduaneras (§14.9)**

- [ ] Solo RT03 y RT05; Aclarar y Rechazar con motivo, **sin** Corregir.

**AUTORIDAD · Consulta de carga (§14.9)**

- [ ] Cualquier contenedor, con ubicación, estado, autorización y permanencia; búsqueda por ID, naviera y estado de autorización, sin acciones.
- [ ] Mecanismo para ordenar un RT05 sobre un turno en curso (A9).

**Efectos físicos (§9.2)**

- [ ] Sin levante o con levante retenido: la talanquera no abre y la pantalla indica la causa.
- [ ] Canal rojo: ingresa y va al parqueo tras el pesaje de entrada.

## Etapa 8 · Retenciones y parqueo 🎯

- [ ] Las 6 causas RT01–RT06 con su momento y rol facultado (§10.2).
- [ ] Asignación y liberación de las 3 plazas con `AgujaParqueo` / `AgujaLiberar` y transacción con bloqueo; tiempo de retención en sinóptico y bandeja (§10.1, §10.6).
- [ ] ⚠️ Tres resoluciones con restricción por rol en el servidor; motivo obligatorio solo en Rechazar (§10.3).
- [ ] Una retención resuelta no puede volver a resolverse.
- [ ] *Corregir* sustituye el peso declarado y conserva el anterior en el historial.
- [ ] Toda resolución notifica al transportista (§10.7).
- [ ] Parqueo lleno + riesgo de retención → rechazo en garita + AL11 (§10.1).
- [ ] AL12 cuando una retención supera 30 min (tarea periódica) (§13.1).
- [ ] ⚠️ Inventario con estado físico real tras Rechazar o aborto (§12.3).

## Etapa 9 · Comandos remotos y alarmas

- [ ] Los 13 comandos con ACK/NAK, causa exacta visible y AL14 al rechazar (§6).
- [ ] ⚠️ Probar que ningún comando se ejecuta cuando se cumple su condición de rechazo.
- [ ] Catálogo AL01–AL14 con severidad y origen; alarmas del servidor: AL01, AL09, AL11, AL12, AL13, AL14 (§13.1).
- [ ] Solo TERMINAL reconoce; AL01 permanece activa hasta reconocerse (§13.4).
- [ ] Decidir y documentar la deduplicación de alarmas repetidas (§13.4).

## Etapa 10 · Canal de mensajería: bot de Telegram 🔴 🎯

> Único componente con salida a internet (HTTPS hacia la Bot API) (§15, §15.4).

**Alta y configuración**

- [ ] Crear el bot con **@BotFather** (`/newbot`) y guardar el token solo en `portus.env`; regenerarlo si se filtra.
- [ ] Registrar el menú con `/setcommands`: `inicio`, `vincular`, `cita`, `miscitas`, `estado`, `misturnos`, `ayuda`.
- [ ] Recepción por **long polling** (`getUpdates`); ejecutar `deleteWebhook` si alguna vez hubo webhook.
- [ ] Servicio `portus-msg` asíncrono (`python-telegram-bot` v20+ o `aiogram`): polling, escucha MQTT y planificador en paralelo sin bloquearse.

**Vinculación (§15.1)**

- [ ] Código de **6 caracteres**, alfabeto sin ambiguos (`0/O`, `1/I/L`), generado con fuente criptográfica.
- [ ] **Un solo uso** y **expira a los 60 min**; invalidar códigos previos del mismo transportista.
- [ ] Guardar el `chat_id` en `vinculo_mensajeria.telegram_chat_id`.
- [ ] Usuario **no vinculado**: todo comando distinto de `/vincular` (incluidos `/start` e `/inicio`) recibe **siempre la misma respuesta** de solicitud de vinculación (confirmar con el auxiliar).
- [ ] Opcional: enlace `t.me/<bot>?start=CODIGO`.

**Los 7 comandos (§15.2)**

- [ ] `/inicio` (y `/start`): saludo, nombre de la terminal y lista de comandos.
- [ ] `/vincular CODIGO`: confirma con el nombre del transportista o error por inválido/vencido.
- [ ] `/cita`: **conversación multipaso** (`esperando_contenedor` → `esperando_franja`) con teclado en línea, `callback_data` corto y `answerCallbackQuery`; expira por inactividad y se cancela si llega otro comando.
  - [ ] Solo contenedores propios con levante y sin cita.
  - [ ] Próximas franjas con capacidad, omitiendo llenas y bloqueadas.
  - [ ] Revalidar propiedad y capacidad al confirmar, en transacción.
  - [ ] Confirmación con contenedor, fecha, inicio y fin.
- [ ] `/miscitas`: contenedor, fecha, ventana y estado.
- [ ] `/estado CONTENEDOR`: datos completos o «no tiene carga asociada a ese identificador» si no es suyo.
- [ ] `/misturnos`: vehículo, contenedor, tipo, estado y estación de cada turno activo.
- [ ] `/ayuda`: lista completa.
- [ ] Handler genérico **después** de los comandos: texto inválido → «comando no reconocido» + `/ayuda`. **Nunca queda sin respuesta.**

**Las 9 notificaciones (§15.3)**

- [ ] Levante otorgado (con aviso de verificación si canal rojo) · levante retenido · cita asignada · recordatorio 1 h antes · vehículo retenido (con pesos si aplica) · retención resuelta (nuevo peso o motivo) · cita cancelada/reprogramada · turno cerrado · turno anulado.
- [ ] Disparadas desde `portus/srv/*`, solo al transportista **propietario**.
- [ ] **Planificador** para el recordatorio de 1 h.
- [ ] Tabla `notificacion` con `entregado` y reintentos; sin internet, quedan pendientes.
- [ ] Cola de envío respetando `429` / `retry_after`; mensajes ≤ 4096 caracteres; escapar texto libre si se usa HTML.
- [ ] Idempotencia por `id` del evento MQTT.

**Aislamiento**

- [ ] Toda consulta se filtra por el `transportista_id` del `chat_id`; nunca confiar en un ID escrito por el usuario sin verificar propiedad.

## Etapa 11 · Citas y control de ventana

- [ ] Franjas de 15 min, máximo 2 citas, respetando bloqueos (§11.1).
- [ ] Solo contenedores con levante; sin dos citas vigentes por contenedor.
- [ ] Ventana válida: inicio de franja hasta 5 min después del fin; fuera → RT04.
- [ ] Estados de cita (programada, cumplida, vencida, cancelada) y `cumplida_en_ventana` (A11).
- [ ] Tarea periódica que vence citas no atendidas.
- [ ] Endpoint de pruebas **temporal** para crear citas antes de tener el bot (hito H3). 🔴 Se elimina antes de E01–E15: la operación debe originarse desde la plataforma (barrera 4).

## Etapa 12 · Métricas y reportes

- [ ] Las 8 métricas para el rango seleccionado (§16.1).
- [ ] Probar el cálculo con la serie conocida de §16.2.
- [ ] Definir la fuente de "vehículos en espera" (A15) y la unidad de distancia (A16), rotulada en el reporte.
- [ ] Registrar la política de asignación activa en cada corrida (campo `politica_asignacion` en `reporte` y en el CSV) para la comparación de la Fase 3 (§12.4, §16.3, §17).
- [ ] Exportación CSV; el reporte de la corrida de evaluación es la línea base de la Fase 3.

## Etapa 13 · Integración progresiva

> La integración no termina hasta operar seguro con el servidor apagado y reconciliar al reconectar (§24.3).

- [ ] 1. Enlace controlador ↔ servidor.
- [ ] 2. Publicación de eventos y visualización en el sinóptico por WebSocket.
- [ ] 3. Operación completa originada desde la plataforma (happy path de depósito, §22.2).
- [ ] 4. Cadena de autorización con levante y canal.
- [ ] 5. Citas y control de ventana.
- [ ] 6. Retención, parqueo y resolución en sus tres formas.
- [ ] 7. Comandos remotos y alarmas con reconocimiento.
- [ ] 8. Bot de Telegram con sus notificaciones.
- [ ] 9. Métricas y reportes.
- [ ] 10. Pérdida y restablecimiento de comunicación.

## Etapa 14 · Pruebas y validación

- [ ] Pruebas individuales de §21.1, cada una con condición, resultado esperado, obtenido y correcciones.
- [ ] Prueba específica de rechazo de cada comando en su condición.
- [ ] Prueba de aislamiento con las 2 navieras y las 2 cuentas de Telegram.
- [ ] Prueba del bot sin internet (notificaciones pendientes que salen al volver).
- [ ] Validación final: E01–E15 en continuo y en orden, siguiendo el guion de 4 bloques (§22.1).
- [ ] Tras cada escenario: inventario = disposición física, turno en el estado esperado, métricas coherentes (§21.2).
- [ ] Ensayo con el hotspot de respaldo.
- [ ] 🔴 Confirmar que no queda ningún endpoint ni dato de prueba temporal en la plataforma (barrera 4).

## Etapa 15 · Documentación y entrega 🎯

**Entregables (§23.1)**

- [ ] **Documento técnico**: propósito, alcance, arquitectura, comunicación controlador–servidor, protocolo serial, tópicos, modelo de datos, usuarios y permisos, cálculo de métricas, comportamiento ante pérdida de comunicación y decisiones sobre A1–A17.
- [ ] **Código fuente** organizado, identificado y comentado: firmware, puente, **definición del protocolo serial**, **esquema de BD**, lógica, web y bot.
- [ ] Instrucciones para **compilar, cargar, configurar y ejecutar** el firmware y la plataforma.
- [ ] **Plataforma desplegada** con instrucciones de despliegue, **arranque desde cero** (§19.3) y credenciales de los 7 usuarios.
- [ ] **Canal de mensajería**: usuario del bot (`@...`), **procedimiento de vinculación** y las **2 cuentas de Telegram de prueba**.
- [ ] **Bitácora** con responsables, fotos, capturas, problemas, decisiones, correcciones y resultados.
- [ ] **Evidencia 3D**: inventario (impresas vs refabricadas), fotos, ubicación, archivos editables y de fabricación, procedencia de modelos ajenos.
- [ ] **Reporte de la corrida de evaluación** exportado desde Reportes.

**Condición inicial de la demo (§19.3)**

- [ ] Controlador y SBC encendidos y comunicados; broker y servicios web disponibles.
- [ ] Sinóptico mostrando el estado real.
- [ ] **Grúa referenciada**.
- [ ] **Inventario inicial coincidiendo con la disposición física**, con pilas preparadas para la remoción de E15.
- [ ] Bot respondiendo y ambas cuentas de prueba vinculadas o con código listo.

**Presentación**

- [ ] 🔴 Ensayo en el que cada integrante explique módulos que no programó (barrera 9).

---

## Prioridades por peso de rúbrica

Si el tiempo aprieta, atender primero las barreras 🔴 y luego lo que más pesa:

- **20 %** Integración y arquitectura de comunicación → Etapas 2, 3, 5, 13.
- **20 %** Tablero de supervisión y control remoto → Etapas 6, 9.
- **15 %** Roles, permisos y cadena de autorización → Etapas 4, 7.
- **15 %** Retenciones y parqueo → Etapa 8.
- **10 %** Canal de mensajería y citas → Etapas 10, 11.
- **10 %** Métricas y reportes → Etapa 12.
- **10 %** Documentación, evidencias y presentación → Etapas A, 15.

> Los puntos extra del alcance opcional (hasta 10) **no compensan** rubros obligatorios incompletos (§23.4).
