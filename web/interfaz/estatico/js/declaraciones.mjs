import { crear, getJson, limpiar, mostrarError, postJson } from "./utilidades.mjs";
export function iniciarDeclaraciones() {
  const lista = document.getElementById("dec-lista");
  const form = document.getElementById("dec-form");
  const error = document.getElementById("dec-error");
  async function cargar() { try { const d = await getJson("/api/declaraciones");
    limpiar(lista);
    if ((d.manifiestos||[]).length === 0) { lista.appendChild(crear("p","texto-ayuda","Sin manifiestos pendientes.")); return; }
    d.manifiestos.forEach(m => { const f = crear("div","fila-manifiesto");
      f.appendChild(crear("span","",`#${m.id} ${m.contenedor_id} ${m.tipo_op} ${m.peso_declarado_g}g ${m.estado_documental}`));
      // Sin declaración solo se ofrece declarar; el levante exige declaración (§9.1).
      if (m.estado_documental === "declaracion_presentada") {
        const sol = crear("button","boton boton-chico","Solicitar levante");
        sol.addEventListener("click", () => solicitarLevante(m.id));
        f.appendChild(sol);
      } else {
        const dec = crear("button","boton boton-chico","Declarar");
        dec.addEventListener("click", () => { form.elements.manifiesto_id.value = m.id; form.elements.numero.focus(); });
        f.appendChild(dec);
      }
      const obs = crear("button","boton boton-chico","Observación");
      obs.addEventListener("click", () => adjuntarObs(m.id));
      f.appendChild(obs); lista.appendChild(f); });
  } catch(e) { mostrarError(error, e.message); } }
  async function solicitarLevante(id) { try { await postJson(`/api/manifiestos/${id}/solicitar-levante`,{}); cargar();
  } catch(e) { mostrarError(error, e.message); } }
  async function adjuntarObs(id) { const obs = window.prompt("Observación:") || "";
    if(!obs.trim()) return; try { await postJson(`/api/manifiestos/${id}/observacion`,{observacion:obs});
  } catch(e) { mostrarError(error, e.message); } }
  form?.addEventListener("submit", async (ev) => { ev.preventDefault();
    const d = new FormData(form); const body = {};
    d.forEach((v,k) => body[k] = k.includes("manifiesto") || k.includes("valor") ? parseInt(v) : v);
    try { await postJson("/api/declaraciones/presentar", body); form.reset(); cargar();
    } catch(e) { mostrarError(error, e.message); } });
  cargar();
}
