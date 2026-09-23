// Pestaña Operación: sinóptico en vivo (SPECS §14.1, CODESTYLE JS-2, JS-3, JS-5).
// Se actualiza SOLO por suscripción MQTT sobre WebSocket (prohibido el polling,
// -10 % en la rúbrica). Al perder el enlace deja de mostrar los datos como
// actuales y exhibe la marca del último estado conocido (JS-5). Todo dato
// entra por textContent (JS-3).

import { ClienteMqtt } from "./mqtt.mjs";
import { crear, credencialesMqtt, getJson, limpiar, postJson, texto, urlWs } from "./utilidades.mjs";

const TIPO_ESTADO_LATIDO = "estado.latido";
const TIPO_TURNO_CAMBIO = "turno.cambio";
const TIPO_PATIO_ESTADO = "patio.estado";
const TIPO_PATIO_ACTUALIZADO = "patio.actualizado";
const TIPO_ENLACE_ESTADO = "enlace.estado";
const TIPO_ALARMA_SERVIDOR = "alarma.servidor";

const COMANDOS_CON_CONFIRMACION = new Set([
  "AbrirTalanquera",
  "AbrirPuertaSalida",
  "ModoMantenimiento",
]);

export function iniciarSinoptico() {
  const raiz = document.getElementById("operacion");
  if (!raiz) {
    return;
  }
  let ultimoTs = null;
  const indicadorEnlace = document.getElementById("op-enlace-estado");
  const indicadorModo = document.getElementById("op-modo");

  function pintarPlazas(plazas) {
    const cont = document.getElementById("op-plazas");
    if (!cont) return;
    limpiar(cont);
    plazas.forEach((p) => {
      const celda = crear("div", `plaza ${p.turno_id ? "ocupada" : "libre"}`);
      celda.appendChild(crear("span", "plaza-num", `P${p.numero}`));
      celda.appendChild(
        crear("span", "plaza-estado", p.turno_id ? `T${p.turno_id}` : "libre")
      );
      cont.appendChild(celda);
    });
  }

  function pintarPosiciones(posiciones, celdas) {
    const cont = document.getElementById("op-posiciones");
    if (!cont) return;
    limpiar(cont);
    const porNivel = { 1: {}, 2: {} };
    celdas.forEach((c) => {
      if (c.contenedor_id) porNivel[c.nivel][c.posicion] = c.contenedor_id;
    });
    posiciones.forEach((pos) => {
      const n1 = porNivel[1][pos.id] || "—";
      const n2 = porNivel[2][pos.id] || "—";
      const celda = crear("button", `posicion pos-${pos.estado}`, pos.id);
      celda.dataset.posicion = pos.id;
      const detalle = crear("span", "pos-detalle");
      detalle.appendChild(crear("span", "", `N1:${n1}`));
      detalle.appendChild(crear("br"));
      detalle.appendChild(crear("span", "", `N2:${n2}`));
      celda.appendChild(detalle);
      celda.addEventListener("click", () => abrirDetallePatio(pos.id));
      cont.appendChild(celda);
    });
  }

  function abrirDetallePatio(posicionId) {
    const panel = document.getElementById("op-detalle-patio");
    if (!panel) return;
    limpiar(panel);
    panel.appendChild(crear("h3", "", `Posición ${posicionId}`));
    const btnBloquear = crear("button", "boton", "Bloquear");
    btnBloquear.addEventListener("click", () => postJson(`/api/patio/posiciones/${posicionId}/bloquear`).then(cargar).catch(() => {}));
    const btnLiberar = crear("button", "boton", "Liberar");
    btnLiberar.addEventListener("click", () => postJson(`/api/patio/posiciones/${posicionId}/liberar`).then(cargar).catch(() => {}));
    panel.appendChild(btnBloquear);
    panel.appendChild(btnLiberar);
  }

  async function cargar() {
    try {
      const datos = await getJson("/api/operacion");
      pintarPlazas(datos.plazas || []);
      pintarPosiciones(datos.posiciones || [], datos.celdas || []);
    } catch {
      // sin snapshot inicial: el sinóptico se llena con los eventos en vivo
    }
  }

  function marcarEnlace(activo) {
    if (indicadorEnlace) {
      indicadorEnlace.textContent = activo ? "conectado" : "desconectado";
      indicadorEnlace.className = `indicador ${activo ? "ok" : "caido"}`;
    }
    if (!activo) {
      document.querySelectorAll("[data-stale]").forEach((el) => el.classList.add("stale"));
    } else {
      document.querySelectorAll("[data-stale]").forEach((el) => el.classList.remove("stale"));
    }
  }

  function enlaceActivo(valor) {
    // El latido trae enlace:true (booleano); el puente, enlace:"activo".
    return valor === true || valor === "activo";
  }

  function aplicarMensaje(topico, carga) {
    let envoltorio;
    try {
      envoltorio = JSON.parse(carga);
    } catch {
      return; // mensaje no JSON: se descarta (P-5)
    }
    const { tipo, datos, ts } = envoltorio;
    if (ts) ultimoTs = ts;
    if (tipo === TIPO_ESTADO_LATIDO && datos) {
      // Latido del controlador: llena el sinóptico (§14.1: modo, grúa, aguja,
      // cola, espera y enlace).
      marcarEnlace(enlaceActivo(datos.enlace));
      texto(indicadorModo, String(datos.modo ?? "—"));
      texto(document.getElementById("op-grua-trabajo"), String(datos.grua ?? "—"));
      texto(document.getElementById("op-aguja"), String(datos.aguja ?? "—"));
      texto(document.getElementById("op-cola"), `${datos.trabajos_en_cola ?? 0} pendientes`);
      texto(document.getElementById("op-espera"), String(datos.vehiculos_en_espera ?? 0));
    } else if (tipo === TIPO_TURNO_CAMBIO && datos) {
      texto(document.getElementById("op-turno-actual"), `T${datos.turno} · ${datos.estado}`);
    } else if (tipo === TIPO_PATIO_ESTADO && datos) {
      const pos = document.querySelector(`[data-posicion="${datos.posicion}"]`);
      if (pos) pos.className = `posicion pos-${datos.estado}`;
    } else if (tipo === TIPO_PATIO_ACTUALIZADO && datos) {
      texto(
        document.getElementById("op-grua-trabajo"),
        `${datos.contenedor} → ${datos.posicion}/N${datos.nivel}`
      );
    } else if (tipo === TIPO_ENLACE_ESTADO && datos) {
      marcarEnlace(enlaceActivo(datos.enlace));
    } else if (tipo === TIPO_ALARMA_SERVIDOR && datos) {
      const cuenta = document.getElementById("op-alarmas");
      if (cuenta) {
        const n = (parseInt(cuenta.dataset.cuenta || "0", 10) || 0) + 1;
        cuenta.dataset.cuenta = String(n);
        cuenta.textContent = String(n);
      }
    }
    if (ultimoTs) texto(document.getElementById("op-ultimo-ts"), ultimoTs);
  }

  function conectar() {
    const cred = credencialesMqtt();
    const cliente = new ClienteMqtt({
      url: urlWs(),
      usuario: cred.usuario,
      contrasena: cred.contrasena,
      alConectar: () => {
        marcarEnlace(true);
        texto(indicadorModo, "suscripción activa");
      },
      alPerder: () => {
        marcarEnlace(false);
        texto(indicadorModo, "enlace perdido");
      },
      alMensaje: aplicarMensaje,
    });
    cliente.iniciar();
    window.addEventListener("beforeunload", () => cliente.detener());
  }

  function configurarComandos() {
    document.querySelectorAll("[data-comando]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const nombre = btn.dataset.comando;
        const confirma = COMANDOS_CON_CONFIRMACION.has(nombre);
        if (confirma && !window.confirm(`¿Enviar ${nombre}?`)) {
          return;
        }
        postJson(`/api/comandos/${nombre}`, { parametros: {} })
          .then((r) => texto(document.getElementById("op-cmd-respuesta"), `${nombre}: enviado (cmd ${r.cmd_id})`))
          .catch((e) => texto(document.getElementById("op-cmd-respuesta"), `${nombre}: error ${e.message}`));
      });
    });
  }

  cargar();
  conectar();
  configurarComandos();
}
