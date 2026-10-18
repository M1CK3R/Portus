import { crear, getJson, limpiar, mostrarError } from "./utilidades.mjs";
export function iniciarMisContenedores() {
  const lista = document.getElementById("mc-lista");
  const error = document.getElementById("mc-error");
  async function cargar() { try { const d = await getJson("/api/naviera/contenedores");
    limpiar(lista);
    if ((d.contenedores||[]).length === 0) { lista.appendChild(crear("p","texto-ayuda","Sin contenedores en patio.")); return; }
    const tabla = crear("table","tabla-datos");
    tabla.appendChild(_enc(["Contenedor","Pos/N","Estado","Autorización","Ingreso","Remociones"]));
    const cuerpo = crear("tbody");
    d.contenedores.forEach(c => { const f = crear("tr");
      f.appendChild(crear("td","",c.contenedor_id)); f.appendChild(crear("td","",`${c.posicion}/N${c.nivel}`));
      f.appendChild(crear("td","",c.estado_operativo)); f.appendChild(crear("td","",c.autorizacion));
      f.appendChild(crear("td","",c.ingreso_en)); f.appendChild(crear("td","",String(c.remociones)));
      cuerpo.appendChild(f); });
    tabla.appendChild(cuerpo); lista.appendChild(tabla);
  } catch(e) { mostrarError(error, e.message); } }
  function _enc(ts){const t=crear("thead");const f=crear("tr");ts.forEach(x=>f.appendChild(crear("th","",x)));t.appendChild(f);return t;}
  cargar();
}
