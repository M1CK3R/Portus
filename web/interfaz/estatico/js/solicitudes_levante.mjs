import { crear, getJson, limpiar, mostrarError, postJson } from "./utilidades.mjs";
export function iniciarSolicitudesLevante() {
  const lista = document.getElementById("lev-lista");
  const error = document.getElementById("lev-error");
  async function cargar() { try { const d = await getJson("/api/levantes");
    limpiar(lista);
    if ((d.solicitudes||[]).length === 0) { lista.appendChild(crear("p","texto-ayuda","Sin solicitudes pendientes.")); return; }
    d.solicitudes.forEach(s => { const f = crear("div","fila-levante");
      f.appendChild(crear("span","",`#${s.levante_id} M${s.manifiesto_id} ${s.contenedor_id} ${s.naviera} ag:${s.agente} decl:${s.numero_declaracion} ${s.peso_declarado_g}g`));
      const otg = crear("button","boton boton-chico","Otorgar");
      otg.addEventListener("click", () => otorgar(s.levante_id));
      const ret = crear("button","boton boton-chico peligro","Retener");
      ret.addEventListener("click", () => retener(s.levante_id));
      f.appendChild(otg); f.appendChild(ret); lista.appendChild(f); });
  } catch(e) { mostrarError(error, e.message); } }
  async function otorgar(id) { const canal = window.prompt("Canal (verde/rojo):") || "";
    if(!["verde","rojo"].includes(canal)) { mostrarError(error,"Canal inválido"); return; }
    try { await postJson(`/api/levantes/${id}/otorgar`,{canal}); cargar();
  } catch(e) { mostrarError(error, e.message); } }
  async function retener(id) { const motivo = window.prompt("Motivo:") || "";
    if(!motivo.trim()) return; try { await postJson(`/api/levantes/${id}/retener`,{motivo}); cargar();
  } catch(e) { mostrarError(error, e.message); } }
  cargar();
}
