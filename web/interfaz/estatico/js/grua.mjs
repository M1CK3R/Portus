// Pestaña Grúa (SPECS §12.6): trabajo en curso, cola, fallas y exportación CSV.
// Render con textContent (JS-3).

import { crear, getJson, limpiar, mostrarError } from "./utilidades.mjs";

export function iniciarGrua() {
  const raiz = document.getElementById("grua");
  if (!raiz) return;
  const contCurso = document.getElementById("grua-curso");
  const contCola = document.getElementById("grua-cola");
  const contFallas = document.getElementById("grua-fallas");
  const error = document.getElementById("grua-error");

  async function cargar() {
    try {
      const datos = await getJson("/api/grua");
      pintarCurso(datos.en_curso);
      pintarCola(datos.cola_pendiente || []);
      pintarFallas(datos.fallas || []);
    } catch (e) {
      mostrarError(error, `No se pudo cargar la grúa: ${e.message}`);
    }
  }

  function pintarCurso(curso) {
    if (!contCurso) return;
    limpiar(contCurso);
    if (!curso) {
      contCurso.appendChild(crear("p", "texto-ayuda", "Grúa en reposo."));
      return;
    }
    contCurso.appendChild(crear("p", "", `Trabajo #${curso.id} · ${curso.tipo} · contenedor ${curso.contenedor}`));
    contCurso.appendChild(crear("p", "", `Turno ${curso.turno} · ${curso.origen} → ${curso.destino} · nivel ${curso.nivel}`));
  }

  function pintarCola(cola) {
    if (!contCola) return;
    limpiar(contCola);
    if (cola.length === 0) {
      contCola.appendChild(crear("p", "texto-ayuda", "Cola vacía."));
      return;
    }
    const lista = crear("ol", "cola-grua");
    cola.forEach((t) => {
      const item = crear("li", "", `#${t.id} ${t.tipo} ${t.contenedor} → ${t.destino} (T${t.turno})`);
      lista.appendChild(item);
    });
    contCola.appendChild(lista);
  }

  function pintarFallas(fallas) {
    if (!contFallas) return;
    limpiar(contFallas);
    if (fallas.length === 0) {
      contFallas.appendChild(crear("p", "texto-ayuda", "Sin fallas registradas."));
      return;
    }
    const tabla = crear("table", "tabla-datos");
    tabla.appendChild(encabezado(["Código", "Descripción", "Marca"]));
    const cuerpo = crear("tbody");
    fallas.forEach((f) => {
      const fila = crear("tr");
      fila.appendChild(crear("td", "", f.codigo));
      fila.appendChild(crear("td", "", f.descripcion));
      fila.appendChild(crear("td", "", f.ts));
      cuerpo.appendChild(fila);
    });
    tabla.appendChild(cuerpo);
    contFallas.appendChild(tabla);
  }

  function encabezado(textos) {
    const t = crear("thead");
    const f = crear("tr");
    textos.forEach((tx) => f.appendChild(crear("th", "", tx)));
    t.appendChild(f);
    return t;
  }

  document.getElementById("grua-exportar")?.addEventListener("click", () => {
    const inicio = document.getElementById("grua-inicio")?.value;
    const fin = document.getElementById("grua-fin")?.value;
    if (inicio && fin) {
      window.location.href = `/api/grua/exportar?inicio=${encodeURIComponent(inicio)}&fin=${encodeURIComponent(fin)}`;
    }
  });

  cargar();
}
