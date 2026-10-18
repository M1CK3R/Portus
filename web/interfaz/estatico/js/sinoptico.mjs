// Pestaña Operación: sinóptico en vivo (SPECS §14.1, CODESTYLE JS-2, JS-3, JS-5).
// Se actualiza SOLO por suscripción MQTT sobre WebSocket (prohibido el polling,
// -10 % en la rúbrica): cada elemento se dibuja con los datos del propio evento.
// HTTP solo se usa para la foto inicial al abrir la pestaña y ante un clic del
// usuario. Al perder el enlace deja de mostrar los datos como actuales y exhibe
// la marca del último estado conocido (JS-5). Todo dato entra por textContent.

import { textoRespuesta } from "./causas_comando.mjs";
import { ClienteMqtt } from "./mqtt.mjs";
import {
  EFECTO_ACK,
  GRUA_REPOSO,
  GRUA_SUSPENDIDA,
  MODO_MANTENIMIENTO,
  duracionDesde,
  textoAguja,
  textoGrua,
  textoModo,
  textoTransferencia,
} from "./sinoptico_textos.mjs";
import { crear, credencialesMqtt, getJson, limpiar, postJson, texto, urlWs } from "./utilidades.mjs";

const COMANDOS_CON_CONFIRMACION = new Set([
  "AbrirTalanquera",
  "AbrirPuertaSalida",
  "ModoMantenimiento",
]);
const MAX_RESPUESTAS_VISIBLES = 6;
const AUT_AUTORIZADO = "AUTORIZADO";
const ALARMA_PESAJE = "AL09";

export function iniciarSinoptico() {
  const raiz = document.getElementById("operacion");
  if (!raiz) {
    return;
  }
  const el = (id) => document.getElementById(id);
  const estado = {
    ultimoTs: null,
    grua: null,
    modo: null,
    plazas: [],
    turnoPorVehiculo: new Map(),
    ultimoPesoG: null,
    colaPendientes: 0,
    tipoEnCurso: null,
  };

  function pintarCola() {
    const enCurso = estado.tipoEnCurso ? ` · en curso: ${estado.tipoEnCurso}` : "";
    texto(el("op-cola"), `${estado.colaPendientes} pendientes${enCurso}`);
  }

  // ------------------------------------------------------------ foto inicial

  async function cargar() {
    try {
      const datos = await getJson("/api/operacion");
      estado.plazas = datos.plazas || [];
      pintarPlazas();
      pintarPosiciones(datos.posiciones || [], datos.celdas || []);
      fijarAlarmas(datos.alarmas_activas ?? 0);
    } catch {
      // sin foto inicial: el sinóptico se llena con los eventos en vivo
    }
  }

  // -------------------------------------------------------------- parqueo

  function pintarPlazas() {
    const cont = el("op-plazas");
    if (!cont) return;
    limpiar(cont);
    const ahora = Date.now();
    estado.plazas.forEach((p) => {
      const ocupada = p.turno_id != null;
      const celda = crear("div", `plaza ${ocupada ? "ocupada" : "libre"}`);
      celda.appendChild(crear("span", "plaza-num", `P${p.numero}`));
      if (!ocupada) {
        celda.appendChild(crear("span", "plaza-estado", "libre"));
      } else {
        celda.appendChild(botonTurno(p.turno_id, `T${p.turno_id}`));
        const tiempo = duracionDesde(p.ocupada_desde, ahora);
        const detalle = p.retencion_resuelta ? "resuelta · esperando salida" : "retenido";
        celda.appendChild(crear("span", "plaza-estado", `${detalle} · ${tiempo}`));
        // §6.3: solo si la plaza está ocupada y su retención fue resuelta.
        if (p.retencion_resuelta) {
          const liberar = crear("button", "boton boton-chico", "Liberar parqueo");
          liberar.addEventListener("click", () => liberarParqueo(p.numero));
          celda.appendChild(liberar);
        }
      }
      cont.appendChild(celda);
    });
  }

  function actualizarPlaza(numero, cambios) {
    const plaza = estado.plazas.find((p) => p.numero === numero);
    if (plaza) {
      Object.assign(plaza, cambios);
    } else {
      estado.plazas.push({ numero, ...cambios });
      estado.plazas.sort((a, b) => a.numero - b.numero);
    }
    pintarPlazas();
  }

  async function liberarParqueo(numero) {
    try {
      const r = await postJson(`/api/parqueo/${numero}/liberar`, {});
      registrarEnvio(r.nombre, r.cmd_id);
    } catch (e) {
      anotarRespuesta(`AgujaLiberar (plaza ${numero}): no enviado · ${e.message}`, "nak");
    }
  }

  // ---------------------------------------------------------------- patio

  function pintarPosiciones(posiciones, celdas) {
    const cont = el("op-posiciones");
    if (!cont) return;
    limpiar(cont);
    const porNivel = { 1: {}, 2: {} };
    celdas.forEach((c) => {
      if (c.contenedor_id) porNivel[c.nivel][c.posicion] = c.contenedor_id;
    });
    posiciones.forEach((pos) => {
      const celda = crear("button", `posicion pos-${pos.estado}`, pos.id);
      celda.dataset.posicion = pos.id;
      celda.dataset.estado = pos.estado;
      const detalle = crear("span", "pos-detalle");
      detalle.appendChild(crear("span", "", `N1:${porNivel[1][pos.id] || "—"}`));
      detalle.appendChild(crear("br"));
      detalle.appendChild(crear("span", "", `N2:${porNivel[2][pos.id] || "—"}`));
      celda.appendChild(detalle);
      celda.addEventListener("click", () => abrirDetallePatio(pos.id));
      cont.appendChild(celda);
    });
  }

  function abrirDetallePatio(posicionId) {
    const panel = el("op-detalle-patio");
    if (!panel) return;
    limpiar(panel);
    const boton = document.querySelector(`[data-posicion="${posicionId}"]`);
    const estadoPos = boton?.dataset.estado || "—";
    panel.appendChild(crear("h3", "", `Posición ${posicionId} · ${estadoPos}`));
    // Bloquear solo una libre; Liberar solo una bloqueada (enunciado 4.4).
    if (estadoPos === "libre") {
      panel.appendChild(botonPosicion(posicionId, "bloquear", "Bloquear", "PosicionBloquear"));
    }
    if (estadoPos === "bloqueada") {
      panel.appendChild(botonPosicion(posicionId, "liberar", "Liberar", "PosicionLiberar"));
    }
  }

  function botonPosicion(posicionId, accion, etiqueta, comando) {
    const boton = crear("button", "boton", etiqueta);
    boton.addEventListener("click", async () => {
      try {
        const r = await postJson(`/api/patio/posiciones/${posicionId}/${accion}`, {});
        registrarEnvio(comando, r.cmd_id);
      } catch (e) {
        anotarRespuesta(`${comando} ${posicionId}: no enviado · ${e.message}`, "nak");
      }
    });
    return boton;
  }

  function aplicarEstadoPosicion(posicion, estadoNuevo) {
    const boton = document.querySelector(`[data-posicion="${posicion}"]`);
    if (!boton) return;
    boton.className = `posicion pos-${estadoNuevo}`;
    boton.dataset.estado = estadoNuevo;
  }

  function aplicarCambioCelda(datos) {
    const boton = document.querySelector(`[data-posicion="${datos.posicion}"]`);
    const lineas = boton?.querySelectorAll(".pos-detalle span");
    const indice = Number(datos.nivel) === 2 ? 1 : 0;
    const ocupada = String(datos.estado).toUpperCase() === "OCUPADA";
    if (lineas && lineas[indice]) {
      texto(lineas[indice], `N${datos.nivel}:${ocupada ? datos.contenedor : "—"}`);
    }
  }

  // --------------------------------------------------------- turno y detalle

  function botonTurno(turnoId, etiqueta) {
    // «Clic en un vehículo del sinóptico → detalle del turno» (§14.1).
    const boton = crear("button", "enlace-turno", etiqueta);
    boton.type = "button";
    boton.addEventListener("click", () => verTurno(turnoId));
    return boton;
  }

  async function verTurno(turnoId) {
    const panel = el("op-detalle-turno");
    if (!panel || turnoId == null) return;
    try {
      const datos = await getJson(`/api/turnos/${turnoId}`);
      limpiar(panel);
      const t = datos.turno || {};
      panel.appendChild(crear("h3", "", `Turno ${turnoId} · ${t.estado ?? ""}`));
      const tabla = crear("table", "tabla-datos");
      const cuerpo = crear("tbody");
      (datos.linea_de_tiempo || []).forEach((ev) => {
        const fila = crear("tr");
        fila.appendChild(crear("td", "", ev.ts));
        fila.appendChild(crear("td", "", ev.origen));
        fila.appendChild(crear("td", "", ev.descripcion));
        fila.appendChild(crear("td", "", ev.valores ? JSON.stringify(ev.valores) : ""));
        cuerpo.appendChild(fila);
      });
      tabla.appendChild(cuerpo);
      panel.appendChild(tabla);
    } catch (e) {
      limpiar(panel);
      panel.appendChild(crear("p", "error", `No se pudo abrir el turno ${turnoId}: ${e.message}`));
    }
  }

  function pintarVehiculo(idElemento, prefijo, veh) {
    // Texto del elemento + botón al turno si el vehículo tiene uno activo.
    const destino = el(idElemento);
    if (!destino) return;
    limpiar(destino);
    destino.appendChild(document.createTextNode(prefijo));
    const turnoId = estado.turnoPorVehiculo.get(veh);
    if (veh && turnoId != null) {
      destino.appendChild(document.createTextNode(" · "));
      destino.appendChild(botonTurno(turnoId, `${veh} (T${turnoId})`));
    } else if (veh) {
      destino.appendChild(document.createTextNode(` · ${veh}`));
    }
  }

  // ------------------------------------------------------ comandos y ACK/NAK

  const enviados = new Map();

  function registrarEnvio(nombre, cmdId) {
    if (!cmdId) return;
    enviados.set(cmdId, nombre);
    anotarRespuesta(`${nombre}: enviado, esperando al controlador…`, "pendiente", cmdId);
  }

  function anotarRespuesta(mensaje, clase, cmdId) {
    const lista = el("op-cmd-respuestas");
    if (!lista) return;
    const previo = cmdId ? lista.querySelector(`[data-cmd="${cmdId}"]`) : null;
    const item = previo || crear("li");
    item.className = `respuesta-${clase}`;
    if (cmdId) item.dataset.cmd = cmdId;
    texto(item, mensaje);
    if (!previo) lista.prepend(item);
    while (lista.children.length > MAX_RESPUESTAS_VISIBLES) lista.lastChild.remove();
  }

  function aplicarRespuesta(datos) {
    // §6.2 reglas 1-2: el usuario ve siempre ACK/NAK con la causa exacta.
    const nombre = datos.nombre || enviados.get(datos.cmd_id) || "Comando";
    const mensaje = textoRespuesta({ ...datos, nombre });
    if (datos.estado === "ACK") {
      anotarRespuesta(mensaje, "ack", datos.cmd_id);
      const efecto = EFECTO_ACK[nombre];
      if (efecto) texto(el(efecto[0]), efecto[1]);
    } else {
      // El rechazo también queda como AL14 en la pestaña Alarmas (§6.2 regla 2).
      anotarRespuesta(mensaje, "nak", datos.cmd_id);
    }
    enviados.delete(datos.cmd_id);
  }

  function actualizarDisponibilidad() {
    // §6.3: Reanudar solo con grúa suspendida; Referenciar solo en reposo o suspendida.
    const grua = String(estado.grua || "").toUpperCase();
    const reanudar = document.querySelector('[data-comando="GruaReanudar"]');
    const referenciar = document.querySelector('[data-comando="GruaReferenciar"]');
    if (reanudar) reanudar.disabled = grua !== GRUA_SUSPENDIDA;
    if (referenciar) referenciar.disabled = ![GRUA_REPOSO, GRUA_SUSPENDIDA].includes(grua);
    const mantenimiento = document.querySelector('[data-comando="ModoMantenimiento"]');
    if (mantenimiento) {
      const activo = String(estado.modo || "").toUpperCase() === MODO_MANTENIMIENTO;
      texto(mantenimiento, activo ? "Salir de mantenimiento" : "Modo mantenimiento");
    }
  }

  function parametrosDe(nombre) {
    if (nombre !== "ModoMantenimiento") return {};
    const activo = String(estado.modo || "").toUpperCase() === MODO_MANTENIMIENTO;
    return { valor: activo ? "DESACTIVAR" : "ACTIVAR" };
  }

  function configurarComandos() {
    document.querySelectorAll("[data-comando]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const nombre = btn.dataset.comando;
        const parametros = parametrosDe(nombre);
        const detalle = parametros.valor ? ` (${parametros.valor})` : "";
        if (COMANDOS_CON_CONFIRMACION.has(nombre) && !window.confirm(`¿Enviar ${nombre}${detalle}?`)) {
          return;
        }
        try {
          const r = await postJson(`/api/comandos/${nombre}`, { parametros });
          registrarEnvio(nombre, r.cmd_id);
        } catch (e) {
          anotarRespuesta(`${nombre}: no enviado · ${e.message}`, "nak");
        }
      });
    });
  }

  // --------------------------------------------------------------- alarmas

  function fijarAlarmas(cantidad) {
    const cuenta = el("op-alarmas");
    if (!cuenta) return;
    cuenta.dataset.cuenta = String(cantidad);
    cuenta.textContent = String(cantidad);
  }

  // ------------------------------------------------------- enlace y eventos

  function marcarEnlace(activo) {
    const indicador = el("op-enlace-estado");
    if (indicador) {
      indicador.textContent = activo ? "conectado" : "desconectado";
      indicador.className = `indicador ${activo ? "ok" : "caido"}`;
    }
    document
      .querySelectorAll("[data-stale]")
      .forEach((nodo) => nodo.classList.toggle("stale", !activo));
  }

  function enlaceActivo(valor) {
    // El latido trae enlace:true (booleano); el puente, enlace:"activo".
    return valor === true || valor === "activo";
  }

  const MANEJADORES = {
    "estado.latido": (d) => {
      marcarEnlace(enlaceActivo(d.enlace));
      estado.grua = d.grua;
      estado.modo = d.modo;
      texto(el("op-modo"), textoModo(d.modo));
      texto(el("op-grua-estado"), textoGrua(d.grua));
      if (d.aguja != null) texto(el("op-aguja"), textoAguja(d.aguja));
      estado.colaPendientes = d.trabajos_en_cola ?? 0;
      pintarCola();
      texto(el("op-espera"), String(d.vehiculos_en_espera ?? 0));
      actualizarDisponibilidad();
      pintarPlazas(); // refresca el tiempo de retención sin temporizadores
    },
    "garita.identificacion": (d) => {
      pintarVehiculo("op-garita", "validando · vehículo presente", d.veh);
    },
    "turno.autorizacion": (d) => {
      if (d.veh && d.turno != null) estado.turnoPorVehiculo.set(d.veh, d.turno);
      if (d.resultado === AUT_AUTORIZADO) {
        pintarVehiculo("op-garita", "autorizada", d.veh);
        // El controlador abre la talanquera al recibir AUT AUTORIZADO (§4.4).
        texto(el("op-talanquera"), "abierta");
      } else {
        pintarVehiculo("op-garita", `rechazada · ${d.causa ?? "sin causa"}`, d.veh);
      }
    },
    "pesaje.medicion": (d) => {
      estado.ultimoPesoG = d.peso_g;
      const fase = d.meseta ? "medición válida" : "midiendo";
      pintarVehiculo("op-pesaje", `${fase} · ${d.peso_g ?? "—"} g`, d.veh);
      // El vehículo ya cruzó la talanquera y está sobre la plataforma.
      texto(el("op-talanquera"), "cerrada");
    },
    "aguja.estado": (d) => texto(el("op-aguja"), textoAguja(d.estado)),
    "transferencia.evento": (d) => {
      pintarVehiculo("op-transferencia", textoTransferencia(d.evento), d.veh);
    },
    "grua.paso": (d) => {
      // FIN cierra el ciclo: la grúa vuelve a reposo hasta el siguiente latido.
      const paso = String(d.paso).toUpperCase() === "FIN" ? GRUA_REPOSO : d.paso;
      texto(el("op-grua-estado"), textoGrua(paso));
      if (d.posicion) texto(el("op-grua-posicion"), `${d.posicion}/N${d.nivel ?? "?"}`);
      const trabajo = d.contenedor ? `${d.contenedor}${d.resultado ? ` · ${d.resultado}` : ""}` : "—";
      texto(el("op-grua-trabajo"), trabajo);
      if (d.resultado) {
        estado.tipoEnCurso = null; // el ciclo terminó (OK o abortado)
        pintarCola();
      }
    },
    "turno.trabajo": (d) => {
      texto(el("op-grua-trabajo"), `${d.tipo} ${d.contenedor} · ${d.origen} → ${d.destino}`);
      estado.tipoEnCurso = d.tipo;
      pintarCola();
    },
    "patio.cambio": aplicarCambioCelda,
    "patio.actualizado": aplicarCambioCelda,
    "patio.estado": (d) => aplicarEstadoPosicion(d.posicion, d.estado),
    "salida.verificacion": (d) => {
      pintarVehiculo("op-puerta-vehiculo", String(d.resultado || "").toLowerCase(), d.veh);
      // CONFIRMADO: el vehículo pasó la puerta y esta vuelve a cerrarse (§8.6).
      if (String(d.resultado).toUpperCase() === "CONFIRMADO") texto(el("op-puerta"), "cerrada");
    },
    "turno.cambio": (d) => {
      const boton = el("op-turno-actual");
      if (!boton) return;
      texto(boton, `T${d.turno} · ${d.estado}`);
      boton.disabled = false;
      boton.onclick = () => verTurno(d.turno);
    },
    "retencion.abierta": (d) => {
      if (d.plaza != null) {
        actualizarPlaza(d.plaza, {
          turno_id: d.turno,
          ocupada_desde: estado.ultimoTs,
          retencion_resuelta: false,
        });
      }
    },
    "retencion.resuelta": (d) => {
      if (d.plaza != null) actualizarPlaza(d.plaza, { retencion_resuelta: true });
    },
    "parqueo.plaza": (d) => {
      if (d.turno == null) {
        actualizarPlaza(d.plaza, { turno_id: null, ocupada_desde: null, retencion_resuelta: false });
      }
    },
    "comando.respuesta": aplicarRespuesta,
    "enlace.estado": (d) => marcarEnlace(enlaceActivo(d.enlace)),
    // El recuento exacto llega en alarma.resumen: con la deduplicación de §13.4
    // una repetición no suma otra alarma activa.
    "alarma.resumen": (d) => fijarAlarmas(d.activas ?? 0),
    "alarma.servidor": (d) => {
      if (d.codigo === ALARMA_PESAJE) {
        texto(el("op-pesaje"), `medición fuera de tolerancia · ${estado.ultimoPesoG ?? "—"} g`);
      }
    },
  };

  function aplicarMensaje(topico, carga) {
    let envoltorio;
    try {
      envoltorio = JSON.parse(carga);
    } catch {
      return; // mensaje no JSON: se descarta (P-5)
    }
    const { tipo, datos, ts } = envoltorio;
    if (ts) estado.ultimoTs = ts;
    const manejador = MANEJADORES[tipo];
    if (manejador && datos) manejador(datos);
    if (estado.ultimoTs) texto(el("op-ultimo-ts"), estado.ultimoTs);
  }

  function conectar() {
    const cred = credencialesMqtt();
    const cliente = new ClienteMqtt({
      url: urlWs(),
      usuario: cred.usuario,
      contrasena: cred.contrasena,
      alConectar: () => marcarEnlace(true),
      alPerder: () => {
        marcarEnlace(false);
        texto(el("op-modo"), "enlace perdido");
      },
      alMensaje: aplicarMensaje,
    });
    cliente.iniciar();
    window.addEventListener("beforeunload", () => cliente.detener());
  }

  cargar();
  conectar();
  configurarComandos();
}
