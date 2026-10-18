import { crear, getJson, limpiar, mostrarError } from "./utilidades.mjs";
export function iniciarSeguimiento() {
  const lista = document.getElementById("seg-lista");
  const error = document.getElementById("seg-error");
  async function cargar() { try { const d = await getJson("/api/agente/seguimiento");
    limpiar(lista);
    if ((d.solicitudes||[]).length === 0) { lista.appendChild(crear("p","texto-ayuda","Sin solicitudes.")); return; }
    d.solicitudes.forEach(s => { const f = crear("div","fila-seguimiento");
      f.appendChild(crear("span","",`Manifiesto ${s.manifiesto_id}: ${s.estado}${s.canal?" canal="+s.canal:""}${s.motivo?" motivo="+s.motivo:""}`));
      lista.appendChild(f); });
  } catch(e) { mostrarError(error, e.message); } }
  cargar();
}
