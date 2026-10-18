// Pestaña Reportes (SPECS §14.6, §16.1, §16.3): rango en hora de la terminal +
// etiqueta, las 8 métricas con su unidad (A16), la política activa y los dos
// CSV (detalle por turno y resumen). Lista los reportes guardados para
// recuperarlos y compararlos (línea base de la Fase 3). Render con textContent (JS-3).

import { crear, fechaLocal, getJson, limpiar, mostrarError, postJson } from "./utilidades.mjs";

const ETIQUETAS = {
  remociones_por_contenedor_retirado: "1. Remociones por contenedor retirado",
  ciclos_grua_por_operacion: "2. Ciclos de grúa por operación completada",
  distancia_total_recorrida: "3. Distancia total recorrida por la grúa",
  tiempo_promedio_camion_terminal_min: "4. Tiempo promedio de camión en la terminal",
  tiempo_promedio_retencion_min: "5. Tiempo promedio de retención",
  longitud_maxima_fila_espera: "6. Longitud máxima de la fila de espera",
  porcentaje_citas_cumplidas_en_ventana: "7. Citas cumplidas en ventana",
  retenciones_por_causa_y_resolucion: "8. Retenciones por causa y resolución",
};

export function iniciarReportes() {
  const raiz = document.getElementById("reportes");
  if (!raiz) return;
  const cont = document.getElementById("reportes-resultado");
  const lista = document.getElementById("reportes-guardados");
  const error = document.getElementById("reportes-error");

  async function generar() {
    limpiar(error);
    const etiqueta = document.getElementById("reportes-etiqueta")?.value || "corrida";
    const inicio = document.getElementById("reportes-inicio")?.value;
    const fin = document.getElementById("reportes-fin")?.value;
    if (!inicio || !fin) {
      mostrarError(error, "Seleccione inicio y fin del rango.");
      return;
    }
    try {
      // El servidor interpreta el rango en hora de la terminal (UTC-6).
      const datos = await postJson("/api/reportes", { etiqueta, inicio, fin });
      pintar(datos.reporte);
      cargarGuardados();
    } catch (e) {
      mostrarError(error, `Generar: ${e.message}`);
    }
  }

  function pintar(reporte) {
    if (!cont) return;
    limpiar(cont);
    const rango = `${fechaLocal(reporte.inicio)} → ${fechaLocal(reporte.fin)}`;
    cont.appendChild(crear("h3", "", `${reporte.etiqueta} · ${rango}`));
    cont.appendChild(
      crear("p", "texto-ayuda", `Política de asignación: ${reporte.politica} · reporte #${reporte.id}`)
    );
    const unidades = reporte.resultado.unidades || {};
    const tabla = crear("table", "tabla-datos");
    tabla.appendChild(encabezado(["Métrica", "Valor", "Unidad"]));
    const cuerpo = crear("tbody");
    Object.keys(ETIQUETAS).forEach((clave) => {
      const fila = crear("tr");
      fila.appendChild(crear("td", "", ETIQUETAS[clave]));
      fila.appendChild(crear("td", "", textoValor(reporte.resultado[clave])));
      fila.appendChild(crear("td", "", unidades[clave] || ""));
      cuerpo.appendChild(fila);
    });
    tabla.appendChild(cuerpo);
    cont.appendChild(tabla);
    cont.appendChild(botonesCsv(reporte.id));
  }

  async function cargarGuardados() {
    if (!lista) return;
    try {
      const datos = await getJson("/api/reportes");
      limpiar(lista);
      const reportes = datos.reportes || [];
      if (reportes.length === 0) {
        lista.appendChild(crear("p", "texto-ayuda", "Todavía no hay reportes guardados."));
        return;
      }
      const tabla = crear("table", "tabla-datos");
      tabla.appendChild(encabezado(["#", "Etiqueta", "Rango", "Política", "Generado", ""]));
      const cuerpo = crear("tbody");
      reportes.forEach((r) => {
        const fila = crear("tr");
        fila.appendChild(crear("td", "", String(r.id)));
        fila.appendChild(crear("td", "", r.etiqueta));
        fila.appendChild(crear("td", "", `${fechaLocal(r.inicio)} → ${fechaLocal(r.fin)}`));
        fila.appendChild(crear("td", "", r.politica));
        fila.appendChild(crear("td", "", fechaLocal(r.generado_en)));
        const acciones = crear("td");
        const ver = crear("button", "boton boton-chico", "Ver");
        ver.addEventListener("click", () => pintar(r));
        acciones.appendChild(ver);
        fila.appendChild(acciones);
        cuerpo.appendChild(fila);
      });
      tabla.appendChild(cuerpo);
      lista.appendChild(tabla);
    } catch (e) {
      mostrarError(error, `Reportes guardados: ${e.message}`);
    }
  }

  function botonesCsv(id) {
    const caja = crear("div", "acciones-reporte");
    [
      ["Exportar CSV (detalle por turno)", "detalle"],
      ["Exportar CSV (métricas)", "metricas"],
    ].forEach(([rotulo, contenido]) => {
      const boton = crear("button", "boton", rotulo);
      boton.addEventListener("click", () => {
        window.location.href = `/api/reportes/${id}/exportar?contenido=${contenido}`;
      });
      caja.appendChild(boton);
    });
    return caja;
  }

  function encabezado(textos) {
    const t = crear("thead");
    const f = crear("tr");
    textos.forEach((tx) => f.appendChild(crear("th", "", tx)));
    t.appendChild(f);
    return t;
  }

  document.getElementById("reportes-generar")?.addEventListener("click", generar);
  cargarGuardados();
}

function textoValor(valor) {
  if (valor === null || valor === undefined) return "—";
  if (typeof valor !== "object") return String(valor);
  const grupos = Object.entries(valor);
  if (grupos.length === 0) return "sin retenciones resueltas";
  return grupos.map(([grupo, cantidad]) => `${grupo}: ${cantidad}`).join(" · ");
}
