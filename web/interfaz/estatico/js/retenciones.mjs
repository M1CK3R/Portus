// Pestaña Retenciones (SPECS §14.3, §10): abiertas/resueltas, Aclarar,
// Corregir, Rechazar, filtro por causa. Render con textContent (JS-3).

import { crear, getJson, limpiar, mostrarError, postJson, texto } from "./utilidades.mjs";

const ROLES = { RT01: "TERMINAL", RT02: "TERMINAL", RT03: "AUTORIDAD", RT04: "TERMINAL", RT05: "AUTORIDAD", RT06: "TERMINAL" };

export function iniciarRetenciones() {
  const raiz = document.getElementById("retenciones");
  if (!raiz) return;
  const contAbiertas = document.getElementById("ret-abiertas");
  const contResueltas = document.getElementById("ret-resueltas");
  const error = document.getElementById("ret-error");
  const causa = document.getElementById("ret-filtro-causa");

  async function cargar() {
    try {
      const params = causa && causa.value ? `?causa=${causa.value}` : "";
      const datos = await getJson(`/api/retenciones${params}`);
      pintar(contAbiertas, (datos.retenciones || []).filter((r) => r.estado === "abierta"));
      pintar(contResueltas, (datos.retenciones || []).filter((r) => r.estado === "resuelta"));
    } catch (e) {
      mostrarError(error, `No se pudieron cargar las retenciones: ${e.message}`);
    }
  }

  function pintar(cont, filas) {
    if (!cont) return;
    limpiar(cont);
    if (filas.length === 0) {
      cont.appendChild(crear("p", "texto-ayuda", "Sin retenciones."));
      return;
    }
    const tabla = crear("table", "tabla-datos");
    tabla.appendChild(encabezado(["#", "Turno/Veh.", "Causa", "Plaza", "Peso decl./med.", "Rol", "Resolución", ""]));
    const cuerpo = crear("tbody");
    filas.forEach((r) => {
      const fila = crear("tr");
      fila.appendChild(crear("td", "", String(r.id)));
      fila.appendChild(crear("td", "", `T${r.turno_id}`));
      fila.appendChild(crear("td", "", r.causa));
      fila.appendChild(crear("td", "", r.plaza ? String(r.plaza) : "—"));
      const peso = r.peso_declarado_g != null ? `${r.peso_declarado_g}/${r.peso_medido_g ?? "—"}` : "—";
      fila.appendChild(crear("td", "", peso));
      fila.appendChild(crear("td", "", ROLES[r.causa] || "—"));
      fila.appendChild(crear("td", "", r.resolucion || "—"));
      const accion = crear("td");
      if (r.estado === "abierta") {
        const aclarar = crear("button", "boton boton-chico", "Aclarar");
        aclarar.addEventListener("click", () => resolver(r.id, "aclarar"));
        const corregir = crear("button", "boton boton-chico", "Corregir");
        corregir.addEventListener("click", () => resolver(r.id, "corregir"));
        const rechazar = crear("button", "boton boton-chico peligro", "Rechazar");
        rechazar.addEventListener("click", () => resolver(r.id, "rechazar"));
        accion.appendChild(aclarar);
        accion.appendChild(corregir);
        accion.appendChild(rechazar);
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

  async function resolver(id, resolucion) {
    try {
      const cuerpo = {};
      if (resolucion === "rechazar") {
        const motivo = window.prompt("Motivo (obligatorio):") || "";
        if (!motivo.trim()) return;
        cuerpo.motivo = motivo;
      }
      await postJson(`/api/retenciones/${id}/${resolucion}`, cuerpo);
      cargar();
    } catch (e) {
      mostrarError(error, `${resolucion}: ${e.message}`);
    }
  }

  causa?.addEventListener("change", cargar);
  texto(error, "");
  cargar();
}
