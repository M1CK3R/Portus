// Bandeja de retenciones compartida (SPECS §14.3 TERMINAL, §14.9 AUTORIDAD).
// Campos de §14.3, filtros por causa y estado, resoluciones que el rol puede
// usar (§10.2, §10.3) y recarga por evento MQTT sobre WebSocket (JS-2). El
// servidor aplica igual todas las reglas; ocultar botones no es el permiso.
// Render con textContent (JS-3).

import { ClienteMqtt } from "./mqtt.mjs";
import { CAUSAS_DE_PESO, LIMITE_RETENCION_MIN, puedeResolver } from "./config.mjs";
import { duracionDesde } from "./sinoptico_textos.mjs";
import {
  crear,
  credencialesMqtt,
  fechaLocal,
  getJson,
  limpiar,
  mostrarError,
  postJson,
  texto,
  tipoDeMensaje,
  urlWs,
} from "./utilidades.mjs";

const TIPOS_QUE_CAMBIAN_BANDEJA = new Set([
  "retencion.abierta",
  "retencion.resuelta",
  "parqueo.plaza",
]);

// Solo recalcula el tiempo transcurrido con el reloj del navegador; no consulta
// al servidor (JS-2 prohíbe el polling, no un reloj local).
const PERIODO_RELOJ_MS = 30_000;
const MS_POR_MINUTO = 60_000;

const TEXTO_ESTACION = {
  garita: "Garita",
  pesaje_entrada: "Pesaje de entrada",
  pesaje_salida: "Pesaje de salida",
  salida: "Salida",
};

const RESOLUCIONES = [
  ["aclarar", "Aclarar", "boton boton-chico"],
  ["corregir", "Corregir", "boton boton-chico"],
  ["rechazar", "Rechazar", "boton boton-chico peligro"],
];

const COLUMNAS_ABIERTAS = [
  "#",
  "Turno · vehículo",
  "Contenedor",
  "Causa",
  "Momento",
  "Plaza",
  "Tiempo retenido",
  "Evidencia de peso",
  "Rol facultado",
  "",
];
const COLUMNAS_RESUELTAS = [
  "#",
  "Turno · vehículo",
  "Contenedor",
  "Causa",
  "Momento",
  "Plaza",
  "Duración",
  "Evidencia de peso",
  "Resolución",
  "Motivo",
];

export function iniciarBandeja(prefijo) {
  const contAbiertas = document.getElementById(`${prefijo}-abiertas`);
  const contResueltas = document.getElementById(`${prefijo}-resueltas`);
  const error = document.getElementById(`${prefijo}-error`);
  const filtroCausa = document.getElementById(`${prefijo}-filtro-causa`);
  const filtroEstado = document.getElementById(`${prefijo}-filtro-estado`);
  const rol = document.body.dataset.rol || "";
  const relojes = [];

  async function cargar() {
    const params = new URLSearchParams();
    if (filtroCausa?.value) params.set("causa", filtroCausa.value);
    try {
      const datos = await getJson(`/api/retenciones?${params}`);
      const filas = datos.retenciones || [];
      const estado = filtroEstado?.value || "";
      relojes.length = 0;
      pintar(contAbiertas, estado === "resuelta" ? [] : filas.filter((r) => r.estado === "abierta"), true);
      pintar(contResueltas, estado === "abierta" ? [] : filas.filter((r) => r.estado === "resuelta"), false);
      texto(error, "");
    } catch (e) {
      mostrarError(error, `No se pudieron cargar las retenciones: ${e.message}`);
    }
  }

  function pintar(cont, filas, abiertas) {
    if (!cont) return;
    limpiar(cont);
    if (filas.length === 0) {
      cont.appendChild(crear("p", "texto-ayuda", "Sin retenciones."));
      return;
    }
    const tabla = crear("table", "tabla-datos");
    tabla.appendChild(encabezado(abiertas ? COLUMNAS_ABIERTAS : COLUMNAS_RESUELTAS));
    const cuerpo = crear("tbody");
    filas.forEach((r) => cuerpo.appendChild(abiertas ? filaAbierta(r) : filaResuelta(r)));
    tabla.appendChild(cuerpo);
    cont.appendChild(tabla);
  }

  function celdasComunes(fila, r) {
    fila.appendChild(crear("td", "", String(r.id)));
    fila.appendChild(crear("td", "", `T${r.turno_id} · ${r.vehiculo}`));
    fila.appendChild(crear("td", "", r.contenedor_id));
    fila.appendChild(crear("td", "", r.causa));
    const momento = `${TEXTO_ESTACION[r.estacion] || r.estacion} · ${fechaLocal(r.creada_en)}`;
    fila.appendChild(crear("td", "", momento));
    fila.appendChild(crear("td", "", r.plaza ? String(r.plaza) : "sin plaza"));
  }

  function filaAbierta(r) {
    const fila = crear("tr");
    celdasComunes(fila, r);
    const tiempo = crear("td");
    relojes.push({ celda: tiempo, fila, desde: r.creada_en });
    actualizarReloj(relojes[relojes.length - 1], Date.now());
    fila.appendChild(tiempo);
    fila.appendChild(crear("td", "", textoEvidencia(r)));
    fila.appendChild(crear("td", "", r.rol_facultado));
    const acciones = crear("td");
    RESOLUCIONES.filter(([clave]) => puedeResolver(rol, r.causa, clave))
      .filter(([clave]) => clave !== "corregir" || r.corregible)
      .forEach(([clave, etiqueta, clase]) => {
        const boton = crear("button", clase, etiqueta);
        boton.addEventListener("click", () => resolver(r, clave));
        acciones.appendChild(boton);
      });
    if (acciones.childElementCount === 0) {
      acciones.appendChild(crear("span", "texto-ayuda", `Resuelve ${r.rol_facultado}`));
    }
    fila.appendChild(acciones);
    return fila;
  }

  function filaResuelta(r) {
    const fila = crear("tr");
    celdasComunes(fila, r);
    const duracion = duracionDesde(r.creada_en, Date.parse(r.resuelta_en || ""));
    fila.appendChild(crear("td", "", duracion || "—"));
    fila.appendChild(crear("td", "", textoEvidencia(r)));
    fila.appendChild(crear("td", "", `${r.resolucion || "—"} · ${fechaLocal(r.resuelta_en)}`));
    fila.appendChild(crear("td", "", r.motivo || r.observacion || "—"));
    return fila;
  }

  function actualizarReloj(reloj, ahoraMs) {
    texto(reloj.celda, duracionDesde(reloj.desde, ahoraMs));
    const minutos = (ahoraMs - Date.parse(reloj.desde || "")) / MS_POR_MINUTO;
    reloj.fila.classList.toggle("excedida", minutos > LIMITE_RETENCION_MIN);
  }

  async function resolver(r, resolucion) {
    const cuerpo = {};
    if (resolucion === "rechazar") {
      const motivo = window.prompt(`Rechazar ${r.causa} del turno ${r.turno_id}. Motivo (obligatorio):`);
      if (!motivo || !motivo.trim()) return;
      cuerpo.motivo = motivo.trim();
    } else {
      if (resolucion === "corregir" && r.evidencia) {
        const aviso =
          `El peso declarado del manifiesto pasará de ${r.evidencia.peso_declarado_g} g ` +
          `a ${r.evidencia.peso_medido_g} g (queda en el historial). ¿Confirmar?`;
        if (!window.confirm(aviso)) return;
      }
      const observacion = window.prompt("Observación (opcional):");
      if (observacion === null) return;
      if (observacion.trim()) cuerpo.observacion = observacion.trim();
    }
    try {
      await postJson(`/api/retenciones/${r.id}/${resolucion}`, cuerpo);
      cargar();
    } catch (e) {
      mostrarError(error, `${resolucion}: ${e.message}`);
    }
  }

  function suscribir() {
    const cred = credencialesMqtt();
    const cliente = new ClienteMqtt({
      url: urlWs(),
      usuario: cred.usuario,
      contrasena: cred.contrasena,
      alMensaje: (_topico, carga) => {
        if (TIPOS_QUE_CAMBIAN_BANDEJA.has(tipoDeMensaje(carga))) cargar();
      },
    });
    cliente.iniciar();
    window.addEventListener("beforeunload", () => cliente.detener());
  }

  filtroCausa?.addEventListener("change", cargar);
  filtroEstado?.addEventListener("change", cargar);
  window.setInterval(() => {
    const ahora = Date.now();
    relojes.forEach((reloj) => actualizarReloj(reloj, ahora));
  }, PERIODO_RELOJ_MS);
  cargar();
  suscribir();
}

function textoEvidencia(r) {
  // §10.4: solo para causas de peso; diferencia absoluta y porcentual.
  if (!CAUSAS_DE_PESO.has(r.causa) || !r.evidencia) return "—";
  const e = r.evidencia;
  return `decl. ${e.peso_declarado_g} g · med. ${e.peso_medido_g} g · Δ ${e.diferencia_abs_g} g (${e.diferencia_pct} %)`;
}

function encabezado(textos) {
  const t = crear("thead");
  const f = crear("tr");
  textos.forEach((tx) => f.appendChild(crear("th", "", tx)));
  t.appendChild(f);
  return t;
}
