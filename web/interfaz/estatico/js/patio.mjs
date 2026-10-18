// Pestaña Patio (SPECS §12.2): posiciones por nivel + tabla de inventario
// (8 campos), Bloquear/Liberar, permanencia. Render con textContent (JS-3).

import { mostrarRespuesta } from "./causas_comando.mjs";
import { ClienteMqtt } from "./mqtt.mjs";
import {
  crear,
  credencialesMqtt,
  getJson,
  limpiar,
  mostrarError,
  postJson,
  texto,
  urlWs,
} from "./utilidades.mjs";
import { PERMANENCIA_EXCESIVA_HORAS } from "./config.mjs";

// Eventos tras los que la foto del patio cambió: se recarga al recibirlos
// (actualización por suscripción, nunca por temporizador; JS-2).
const TIPOS_QUE_CAMBIAN_PATIO = new Set(["patio.estado", "patio.actualizado"]);

export function iniciarPatio() {
  const raiz = document.getElementById("patio");
  if (!raiz) return;
  const contPos = document.getElementById("patio-posiciones");
  const contInv = document.getElementById("patio-inventario");
  const error = document.getElementById("patio-error");

  async function cargar() {
    try {
      const datos = await getJson("/api/patio");
      pintarPosiciones(datos.posiciones || [], datos.celdas || []);
      pintarInventario(datos.inventario || []);
    } catch (e) {
      mostrarError(error, `No se pudo cargar el patio: ${e.message}`);
    }
  }

  function pintarPosiciones(posiciones, celdas) {
    if (!contPos) return;
    limpiar(contPos);
    const porNivel = { 1: {}, 2: {} };
    celdas.forEach((c) => {
      if (c.contenedor_id) porNivel[c.nivel][c.posicion] = c.contenedor_id;
    });
    posiciones.forEach((pos) => {
      const n1 = porNivel[1][pos.id] || "—";
      const n2 = porNivel[2][pos.id] || "—";
      const celda = crear("div", `posicion pos-${pos.estado}`);
      celda.appendChild(crear("h4", "", pos.id));
      celda.appendChild(crear("p", "", `Estado: ${pos.estado}`));
      celda.appendChild(crear("p", "", `N1: ${n1}`));
      celda.appendChild(crear("p", "", `N2: ${n2}`));
      // Bloquear solo una libre; Liberar solo una bloqueada (enunciado 4.4).
      if (pos.estado === "libre") celda.appendChild(botonComando(pos.id, "bloquear", "Bloquear"));
      if (pos.estado === "bloqueada") celda.appendChild(botonComando(pos.id, "liberar", "Liberar"));
      contPos.appendChild(celda);
    });
  }

  function botonComando(posicionId, accion, etiqueta) {
    const boton = crear("button", "boton boton-chico", etiqueta);
    boton.addEventListener("click", async () => {
      try {
        await postJson(`/api/patio/posiciones/${posicionId}/${accion}`, {});
        // 202: el cambio se aplica cuando el controlador responde ACK (§6.2).
        texto(error, `${etiqueta} ${posicionId}: enviado al controlador, esperando respuesta…`);
      } catch (e) {
        mostrarError(error, e.message);
      }
    });
    return boton;
  }

  function aplicarMensaje(_topico, carga) {
    let envoltorio;
    try {
      envoltorio = JSON.parse(carga);
    } catch {
      return;
    }
    if (envoltorio.tipo === "comando.respuesta" && envoltorio.datos?.nombre?.startsWith("Posicion")) {
      mostrarRespuesta(error, envoltorio.datos);
    }
    if (TIPOS_QUE_CAMBIAN_PATIO.has(envoltorio.tipo)) cargar();
  }

  function suscribir() {
    const cred = credencialesMqtt();
    const cliente = new ClienteMqtt({
      url: urlWs(),
      usuario: cred.usuario,
      contrasena: cred.contrasena,
      alMensaje: aplicarMensaje,
    });
    cliente.iniciar();
    window.addEventListener("beforeunload", () => cliente.detener());
  }

  function pintarInventario(filas) {
    if (!contInv) return;
    limpiar(contInv);
    if (filas.length === 0) {
      contInv.appendChild(crear("p", "texto-ayuda", "Patio vacío."));
      return;
    }
    const tabla = crear("table", "tabla-datos");
    tabla.appendChild(encabezado(["Contenedor", "Naviera", "Pos/Nivel", "Peso decl.", "Autorización", "Ingreso", "Permanencia", "Remociones"]));
    const cuerpo = crear("tbody");
    filas.forEach((f) => {
      const horas = permanenciaHoras(f.ingreso_en);
      const fila = crear("tr", horas > PERMANENCIA_EXCESIVA_HORAS ? "excesivo" : "");
      fila.appendChild(crear("td", "", f.contenedor_id));
      fila.appendChild(crear("td", "", f.naviera));
      fila.appendChild(crear("td", "", `${f.posicion}/N${f.nivel}`));
      fila.appendChild(crear("td", "", String(f.peso_declarado_g)));
      fila.appendChild(crear("td", "", f.autorizacion));
      fila.appendChild(crear("td", "", f.ingreso_en));
      fila.appendChild(crear("td", "", `${horas.toFixed(1)} h`));
      fila.appendChild(crear("td", "", String(f.remociones)));
      cuerpo.appendChild(fila);
    });
    tabla.appendChild(cuerpo);
    contInv.appendChild(tabla);
  }

  function encabezado(textos) {
    const t = crear("thead");
    const f = crear("tr");
    textos.forEach((tx) => f.appendChild(crear("th", "", tx)));
    t.appendChild(f);
    return t;
  }

  cargar();
  suscribir();
}

function permanenciaHoras(iso) {
  if (!iso) return 0;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 0;
  return (Date.now() - t) / 3600000;
}
