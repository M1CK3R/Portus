// Pestaña Citas (SPECS §14.5, §11.4): agenda del día por franjas, cancelar,
// reprogramar, bloquear franja, cumplimiento y panel de vinculación (A17).
// Cada cita muestra su estado (§11.2); solo la programada que ningún turno
// usó admite cancelar o reprogramar. La ocupación cuenta solo programadas
// (§11.1 regla 2). Render con textContent (JS-3).

import { crear, getJson, limpiar, mostrarError, postJson } from "./utilidades.mjs";

export function iniciarCitas() {
  const raiz = document.getElementById("citas");
  if (!raiz) return;
  const contFranjas = document.getElementById("citas-franjas");
  const contCumpl = document.getElementById("citas-cumplimiento");
  const contVinc = document.getElementById("citas-vinculacion");
  const error = document.getElementById("citas-error");
  const fechaSel = document.getElementById("citas-fecha");
  const formBloquear = document.getElementById("citas-bloquear");
  const horaBloquear = document.getElementById("citas-bloquear-hora");

  async function cargar() {
    const fecha = fechaSel?.value || hoyLocal();
    try {
      const datos = await getJson(`/api/citas?fecha=${fecha}`);
      pintarFranjas(datos.franjas || []);
      contCumpl.replaceChildren(
        crear(
          "p",
          "",
          `Cumplimiento: ${datos.cumplimiento.porcentaje}% (${datos.cumplimiento.cumplidas_en_ventana}/${datos.cumplimiento.total})`
        )
      );
      cargarVinculacion();
    } catch (e) {
      mostrarError(error, `No se pudo cargar la agenda: ${e.message}`);
    }
  }

  function pintarFranjas(franjas) {
    if (!contFranjas) return;
    limpiar(contFranjas);
    if (franjas.length === 0) {
      contFranjas.appendChild(crear("p", "texto-ayuda", "Sin franjas para este día."));
      return;
    }
    franjas.forEach((fr) => {
      const tarjeta = crear("div", `franja ${fr.bloqueada ? "bloqueada" : ""}`);
      const ocupadas = fr.citas.filter((c) => c.estado === "programada").length;
      tarjeta.appendChild(crear("h4", "", `${fr.inicio}–${fr.fin} · ${ocupadas}/${fr.capacidad}`));
      if (fr.bloqueada) tarjeta.appendChild(crear("p", "etiqueta-bloqueada", "BLOQUEADA"));
      const lista = crear("ul", "lista-citas");
      fr.citas.forEach((c) => lista.appendChild(itemCita(c)));
      tarjeta.appendChild(lista);
      const bloquear = crear("button", "boton boton-chico", "Bloquear franja");
      bloquear.addEventListener("click", () => bloquearFranja(fr.fecha, fr.inicio));
      tarjeta.appendChild(bloquear);
      contFranjas.appendChild(tarjeta);
    });
  }

  function itemCita(c) {
    const item = crear("li", "", `${c.transportista} · ${c.contenedor} · ${c.vehiculo || "—"}`);
    item.appendChild(crear("span", `estado-cita estado-${c.estado}`, textoEstado(c)));
    if (c.estado === "programada" && !c.en_uso) {
      const cancelar = crear("button", "boton boton-chico", "Cancelar");
      cancelar.addEventListener("click", () => cancelarCita(c.id));
      const repro = crear("button", "boton boton-chico", "Reprogramar");
      repro.addEventListener("click", () => reprogramarCita(c.id));
      item.appendChild(cancelar);
      item.appendChild(repro);
    }
    return item;
  }

  async function cargarVinculacion() {
    try {
      const datos = await getJson("/api/transportistas");
      if (!contVinc) return;
      limpiar(contVinc);
      const tabla = crear("table", "tabla-datos");
      tabla.appendChild(encabezado(["Transportista", "Estado", "Código activo", "Expira", ""]));
      const cuerpo = crear("tbody");
      (datos.transportistas || []).forEach((t) => {
        const fila = crear("tr");
        fila.appendChild(crear("td", "", t.nombre_mostrado));
        fila.appendChild(crear("td", t.vinculado ? "vinculado" : "sin vincular"));
        fila.appendChild(crear("td", "", t.codigo_activo || "—"));
        fila.appendChild(crear("td", "", t.expira_en || "—"));
        const accion = crear("td");
        const gen = crear("button", "boton boton-chico", "Generar código");
        gen.addEventListener("click", () => generarCodigo(t.id));
        accion.appendChild(gen);
        fila.appendChild(accion);
        cuerpo.appendChild(fila);
      });
      tabla.appendChild(cuerpo);
      contVinc.appendChild(tabla);
    } catch (e) {
      mostrarError(contVinc, `Vinculación: ${e.message}`);
    }
  }

  function encabezado(textos) {
    const t = crear("thead");
    const f = crear("tr");
    textos.forEach((tx) => f.appendChild(crear("th", "", tx)));
    t.appendChild(f);
    return t;
  }

  async function cancelarCita(id) {
    try {
      await postJson(`/api/citas/${id}/cancelar`, {});
      cargar();
    } catch (e) {
      mostrarError(error, `Cancelar: ${e.message}`);
    }
  }

  async function reprogramarCita(id) {
    const fecha = window.prompt("Nueva fecha (aaaa-mm-dd):") || "";
    const inicio = window.prompt("Nueva hora de inicio (HH:MM):") || "";
    if (!fecha || !inicio) return;
    try {
      await postJson(`/api/citas/${id}/reprogramar`, { fecha, inicio });
      cargar();
    } catch (e) {
      mostrarError(error, `Reprogramar: ${e.message}`);
    }
  }

  async function bloquearFranja(fecha, inicio) {
    try {
      await postJson(`/api/franjas/${fecha}/${inicio}/bloquear`, {});
      cargar();
    } catch (e) {
      mostrarError(error, `Bloquear franja: ${e.message}`);
    }
  }

  async function generarCodigo(transportistaId) {
    try {
      const r = await postJson(`/api/transportistas/${transportistaId}/codigo-vinculacion`, {});
      window.alert(`Código: ${r.codigo} (expira ${r.expira_en})`);
      cargarVinculacion();
    } catch (e) {
      mostrarError(error, `Generar código: ${e.message}`);
    }
  }

  formBloquear?.addEventListener("submit", (evento) => {
    evento.preventDefault();
    if (horaBloquear?.value) bloquearFranja(fechaSel?.value || hoyLocal(), horaBloquear.value);
  });
  fechaSel?.addEventListener("change", cargar);
  if (fechaSel && !fechaSel.value) fechaSel.value = hoyLocal();
  cargar();
}

function textoEstado(c) {
  // Estado exacto de §11.2 más el cumplimiento de ventana cuando ya se registró (A11).
  if (c.estado === "programada" && c.en_uso) return "en terminal";
  if (c.cumplida_en_ventana === true) return `${c.estado} · en ventana`;
  if (c.cumplida_en_ventana === false) return `${c.estado} · fuera de ventana`;
  return c.estado;
}

function hoyLocal() {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}
