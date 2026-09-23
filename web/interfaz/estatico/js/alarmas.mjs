// Pestaña Alarmas (SPECS §13.3): activas/históricas, reconocer (comentario
// opcional), reconocer todas (solo baja/media), filtro por severidad, Silenciar.
// Render con textContent (JS-3).

import { crear, getJson, limpiar, mostrarError, postJson } from "./utilidades.mjs";

export function iniciarAlarmas() {
  const raiz = document.getElementById("alarmas");
  if (!raiz) return;
  const contActivas = document.getElementById("alarmas-activas");
  const contHistoricas = document.getElementById("alarmas-historicas");
  const error = document.getElementById("alarmas-error");
  const severidad = document.getElementById("alarmas-filtro-severidad");

  async function cargar() {
    try {
      const params = severidad && severidad.value ? `?severidad=${severidad.value}` : "";
      const datos = await getJson(`/api/alarmas${params}`);
      pintar(contActivas, datos.activas || [], true);
      pintar(contHistoricas, datos.historicas || [], false);
    } catch (e) {
      mostrarError(error, `No se pudieron cargar las alarmas: ${e.message}`);
    }
  }

  function pintar(cont, filas, activas) {
    if (!cont) return;
    limpiar(cont);
    if (filas.length === 0) {
      cont.appendChild(crear("p", "texto-ayuda", "Sin alarmas."));
      return;
    }
    const tabla = crear("table", "tabla-datos");
    tabla.appendChild(encabezado(["#", "Código", "Severidad", "Origen", "Descripción", "Rep.", "Marca", ""]));
    const cuerpo = crear("tbody");
    filas.forEach((a) => {
      const fila = crear("tr", `sev-${a.severidad.toLowerCase()}`);
      fila.appendChild(crear("td", "", String(a.id)));
      fila.appendChild(crear("td", "", a.codigo));
      fila.appendChild(crear("td", "", a.severidad));
      fila.appendChild(crear("td", "", a.origen));
      fila.appendChild(crear("td", "", a.descripcion));
      fila.appendChild(crear("td", "", String(a.repeticiones)));
      fila.appendChild(crear("td", "", a.ts));
      const accion = crear("td");
      if (activas) {
        const rec = crear("button", "boton boton-chico", "Reconocer");
        rec.addEventListener("click", () => reconocer(a.id));
        accion.appendChild(rec);
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

  async function reconocer(id) {
    const comentario = window.prompt("Comentario (opcional):") || "";
    try {
      await postJson(`/api/alarmas/${id}/reconocer`, { comentario });
      cargar();
    } catch (e) {
      mostrarError(error, `Reconocer: ${e.message}`);
    }
  }

  document.getElementById("alarmas-reconocer-todas")?.addEventListener("click", async () => {
    try {
      await postJson("/api/alarmas/reconocer-todas", {});
      cargar();
    } catch (e) {
      mostrarError(error, `Reconocer todas: ${e.message}`);
    }
  });

  document.getElementById("alarmas-silenciar")?.addEventListener("click", async () => {
    try {
      await postJson("/api/comandos/AlarmaSilenciar", { parametros: {} });
    } catch (e) {
      mostrarError(error, `Silenciar: ${e.message}`);
    }
  });

  severidad?.addEventListener("change", cargar);
  cargar();
}
