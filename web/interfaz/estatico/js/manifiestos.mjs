import { crear, getJson, limpiar, mostrarError, postJson } from "./utilidades.mjs";
export function iniciarManifiestos() {
  const lista = document.getElementById("man-lista");
  const form = document.getElementById("man-form");
  const error = document.getElementById("man-error");
  async function cargar() {
    try { const datos = await getJson("/api/manifiestos");
      limpiar(lista);
      (datos.manifiestos || []).forEach(m => { const f = crear("div","fila-manifiesto");
        f.appendChild(crear("span","",`#${m.id} ${m.contenedor_id} ${m.tipo_op} ${m.peso_declarado_g}g ${m.estado_documental}/${m.estado_operativo}`));
        const ver = crear("button","boton boton-chico","Detalle");
        ver.addEventListener("click", () => verDetalle(m.id));
        const anu = crear("button","boton boton-chico peligro","Anular");
        anu.addEventListener("click", () => anular(m.id));
        f.appendChild(ver); f.appendChild(anu); lista.appendChild(f); });
    } catch(e) { mostrarError(error, e.message); }
  }
  async function verDetalle(id) { try { const d = await getJson(`/api/manifiestos/${id}/detalle`);
    const cont = document.getElementById("man-detalle"); limpiar(cont);
    cont.appendChild(crear("h3","",`Manifiesto ${id}`));
    const m = d.manifiesto || {};
    [["Contenedor",m.contenedor_id],["Tipo",m.tipo_op],["Peso declarado",`${m.peso_declarado_g} g`],
     ["Tolerancia",`${m.tolerancia_pct} %`],["Transportista ID",m.transportista_id],
     ["Estado documental",m.estado_documental],["Estado operativo",m.estado_operativo]]
      .forEach(([k,v]) => cont.appendChild(crear("p","",`${k}: ${v ?? "—"}`)));
    cont.appendChild(crear("h4","","Historial de cambios"));
    if ((d.historial||[]).length === 0) cont.appendChild(crear("p","texto-ayuda","Sin cambios registrados."));
    (d.historial||[]).forEach(h => cont.appendChild(crear("p","",`${h.ts} ${h.campo}: ${h.valor_anterior} → ${h.valor_nuevo} (${h.motivo})`)));
  } catch(e) { mostrarError(error, e.message); } }
  async function anular(id) { try { await postJson(`/api/manifiestos/${id}/anular`,{}); cargar();
  } catch(e) { mostrarError(error, e.message); } }
  form?.addEventListener("submit", async (ev) => { ev.preventDefault();
    const d = new FormData(form); const body = {};
    d.forEach((v,k) => body[k] = k.includes("peso") || k.includes("tolerancia") || k.includes("transportista") ? parseInt(v) : v);
    try { await postJson("/api/manifiestos", body); form.reset(); cargar();
    } catch(e) { mostrarError(error, e.message); } });
  cargar();
}
