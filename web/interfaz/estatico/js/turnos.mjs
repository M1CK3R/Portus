// Pestaña Turnos (SPECS §14.2): activos/históricos, filtros, línea de tiempo,
// Retener (RT06) y Anular. Render con textContent (JS-3).

import { ESTADOS_RETENIBLES } from "./config.mjs";
import { crear, getJson, limpiar, mostrarError, postJson, texto } from "./utilidades.mjs";

// §8.1: Anulado no sale de EnSalida ni de un final; un Retenido se anula con
// Rechazar desde la bandeja (lo resuelve el rol facultado, §10.3).
const ESTADOS_ANULABLES = new Set([
  "Programado",
  "EnGarita",
  "EnPesajeEntrada",
  "EnRuta",
  "EnTransferencia",
  "EnPesajeSalida",
]);

export function iniciarTurnos() {
  const raiz = document.getElementById("turnos");
  if (!raiz) return;
  const listaActivos = document.getElementById("turnos-activos");
  const listaHistoricos = document.getElementById("turnos-historicos");
  const detalle = document.getElementById("turno-detalle");
  const error = document.getElementById("turnos-error");

  async function cargar() {
    try {
      const [activos, historicos] = await Promise.all([
        getJson("/api/turnos?alcance=activos"),
        getJson("/api/turnos?alcance=historicos"),
      ]);
      pintar(listaActivos, activos.turnos || []);
      pintar(listaHistoricos, historicos.turnos || []);
    } catch (e) {
      mostrarError(error, `No se pudieron cargar los turnos: ${e.message}`);
    }
  }

  function pintar(cont, filas) {
    if (!cont) return;
    limpiar(cont);
    if (filas.length === 0) {
      cont.appendChild(crear("p", "texto-ayuda", "Sin turnos."));
      return;
    }
    const tabla = crear("table", "tabla-datos");
    tabla.appendChild(encabezado(["#", "Vehículo", "Contenedor", "Tipo", "Estado", "Creado", ""]));
    const cuerpo = crear("tbody");
    filas.forEach((t) => {
      const fila = crear("tr");
      fila.appendChild(crear("td", "", String(t.id)));
      fila.appendChild(crear("td", "", t.identificador_vehiculo));
      fila.appendChild(crear("td", "", t.contenedor_id));
      fila.appendChild(crear("td", "", t.tipo_op));
      fila.appendChild(crear("td", `estado estado-${t.estado.toLowerCase()}`, t.estado));
      fila.appendChild(crear("td", "", t.creado_en));
      const accion = crear("td");
      const ver = crear("button", "boton boton-chico", "Detalle");
      ver.addEventListener("click", () => verDetalle(t.id));
      accion.appendChild(ver);
      if (ESTADOS_RETENIBLES.has(t.estado)) {
        const ret = crear("button", "boton boton-chico", "Retener (RT06)");
        ret.addEventListener("click", () => retener(t.id));
        accion.appendChild(ret);
      }
      if (ESTADOS_ANULABLES.has(t.estado)) {
        const anu = crear("button", "boton boton-chico peligro", "Anular");
        anu.addEventListener("click", () => anular(t.id));
        accion.appendChild(anu);
      }
      fila.appendChild(accion);
      cuerpo.appendChild(fila);
    });
    tabla.appendChild(cuerpo);
    cont.appendChild(tabla);
  }

  function encabezado(textos) {
    const t = crear("thead");
    const f = crear("tr");
    textos.forEach((tx) => f.appendChild(crear("th", "", tx)));
    t.appendChild(f);
    return t;
  }

  async function verDetalle(id) {
    try {
      const datos = await getJson(`/api/turnos/${id}`);
      limpiar(detalle);
      detalle.appendChild(crear("h3", "", `Turno ${id}`));
      const tabla = crear("table", "tabla-datos");
      const cuerpo = crear("tbody");
      (datos.linea_de_tiempo || []).forEach((ev) => {
        const f = crear("tr");
        f.appendChild(crear("td", "", ev.ts));
        f.appendChild(crear("td", "", ev.origen));
        f.appendChild(crear("td", "", ev.descripcion));
        f.appendChild(crear("td", "", JSON.stringify(ev.valores)));
        cuerpo.appendChild(f);
      });
      tabla.appendChild(cuerpo);
      detalle.appendChild(tabla);
    } catch (e) {
      mostrarError(detalle, `No se pudo cargar el detalle: ${e.message}`);
    }
  }

  async function retener(id) {
    const observacion = window.prompt(`Retención manual RT06 del turno ${id}. Observación (opcional):`);
    if (observacion === null) return;
    try {
      await postJson(`/api/turnos/${id}/retener`, { observacion });
      cargar();
    } catch (e) {
      mostrarError(error, `Retener: ${e.message}`);
    }
  }

  async function anular(id) {
    const motivo = window.prompt("Motivo de anulación:") || "";
    if (!motivo.trim()) return;
    try {
      await postJson(`/api/turnos/${id}/anular`, { motivo });
      cargar();
    } catch (e) {
      mostrarError(error, `Anular: ${e.message}`);
    }
  }

  document.getElementById("turnos-buscar")?.addEventListener("click", cargar);
  cargar();
}
