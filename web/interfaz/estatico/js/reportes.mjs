// Pestaña Reportes (SPECS §14.6, §16.1, §16.3): rango + etiqueta, generar las 8
// métricas y exportar CSV con el detalle de cada turno. Render con textContent (JS-3).

import { crear, getJson, limpiar, mostrarError, postJson } from "./utilidades.mjs";

const ETIQUETAS = {
  remociones_por_contenedor_retirado: "Remociones por contenedor retirado",
  ciclos_grua_por_operacion: "Ciclos de grúa por operación",
  distancia_total_recorrida: "Distancia total recorrida",
  tiempo_promedio_camion_terminal_min: "Tiempo promedio de camión en terminal (min)",
  tiempo_promedio_retencion_min: "Tiempo promedio de retención (min)",
  longitud_maxima_fila_espera: "Longitud máxima de la fila de espera",
  porcentaje_citas_cumplidas_en_ventana: "% citas cumplidas en ventana",
  retenciones_por_causa_y_resolucion: "Retenciones por causa y resolución",
};

export function iniciarReportes() {
  const raiz = document.getElementById("reportes");
  if (!raiz) return;
  const cont = document.getElementById("reportes-resultado");
  const error = document.getElementById("reportes-error");

  async function generar() {
    const etiqueta = document.getElementById("reportes-etiqueta")?.value || "corrida";
    const inicio = document.getElementById("reportes-inicio")?.value;
    const fin = document.getElementById("reportes-fin")?.value;
    if (!inicio || !fin) {
      mostrarError(error, "Seleccione inicio y fin del rango.");
      return;
    }
    try {
      const datos = await postJson("/api/reportes", { etiqueta, inicio: inicio, fin: fin });
      pintar(cont, datos.reporte);
    } catch (e) {
      mostrarError(error, `Generar: ${e.message}`);
    }
  }

  function pintar(cont, reporte) {
    if (!cont) return;
    limpiar(cont);
    cont.appendChild(crear("h3", "", `${reporte.etiqueta} · ${reporte.inicio} → ${reporte.fin}`));
    cont.appendChild(crear("p", "texto-ayuda", `Política activa: ${reporte.politica}`));
    const tabla = crear("table", "tabla-datos");
    tabla.appendChild(encabezado(["Métrica", "Valor"]));
    const cuerpo = crear("tbody");
    Object.keys(ETIQUETAS).forEach((clave) => {
      const f = crear("tr");
      f.appendChild(crear("td", "", ETIQUETAS[clave]));
      const valor = reporte.resultado[clave];
      const textoValor = typeof valor === "object" ? JSON.stringify(valor) : String(valor);
      f.appendChild(crear("td", "", textoValor));
      cuerpo.appendChild(f);
    });
    tabla.appendChild(cuerpo);
    cont.appendChild(tabla);
    const exportar = crear("button", "boton", "Exportar CSV");
    exportar.addEventListener("click", () => {
      window.location.href = `/api/reportes/${reporte.id}/exportar`;
    });
    cont.appendChild(exportar);
  }

  function encabezado(textos) {
    const t = crear("thead");
    const f = crear("tr");
    textos.forEach((tx) => f.appendChild(crear("th", "", tx)));
    t.appendChild(f);
    return t;
  }

  document.getElementById("reportes-generar")?.addEventListener("click", generar);
}
