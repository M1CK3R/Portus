// Pestaña Consulta de carga de AUTORIDAD (SPECS §14.9): cualquier contenedor
// del patio y los turnos en curso, con «Retener turno» para ordenar RT05 (A9).
// Se actualiza por evento MQTT (JS-2). Render con textContent (JS-3).

import { ClienteMqtt } from "./mqtt.mjs";
import {
  crear,
  credencialesMqtt,
  fechaLocal,
  getJson,
  limpiar,
  mostrarError,
  postJson,
  texto,
  tipoDeMensaje,
  urlWs,
} from "./utilidades.mjs";

const TIPOS_QUE_CAMBIAN_TURNOS = new Set(["turno.cambio", "retencion.abierta", "retencion.resuelta"]);
const TIPOS_QUE_CAMBIAN_PATIO = new Set(["patio.actualizado", "patio.estado"]);

export function iniciarConsultaCarga() {
  const lista = document.getElementById("cc-lista");
  const turnos = document.getElementById("cc-turnos");
  const error = document.getElementById("cc-error");
  const buscar = document.getElementById("cc-buscar");

  function busqueda() {
    return buscar?.value.trim() || "";
  }

  async function cargarInventario() {
    const q = busqueda() ? `?contenedor_id=${encodeURIComponent(busqueda())}` : "";
    try {
      const datos = await getJson(`/api/autoridad/consulta-carga${q}`);
      pintarInventario(datos.contenedores || []);
    } catch (e) {
      mostrarError(error, `No se pudo consultar la carga: ${e.message}`);
    }
  }

  async function cargarTurnos() {
    const q = busqueda() ? `?busqueda=${encodeURIComponent(busqueda())}` : "";
    try {
      const datos = await getJson(`/api/autoridad/turnos${q}`);
      pintarTurnos(datos.turnos || []);
    } catch (e) {
      mostrarError(error, `No se pudieron cargar los turnos en curso: ${e.message}`);
    }
  }

  function pintarInventario(filas) {
    limpiar(lista);
    if (filas.length === 0) {
      lista.appendChild(crear("p", "texto-ayuda", "Sin contenedores en el patio."));
      return;
    }
    const tabla = crear("table", "tabla-datos");
    tabla.appendChild(
      encabezado(["Contenedor", "Naviera", "Pos/N", "Peso decl.", "Autorización", "Ingreso", "Remociones"])
    );
    const cuerpo = crear("tbody");
    filas.forEach((c) => {
      const f = crear("tr");
      f.appendChild(crear("td", "", c.contenedor_id));
      f.appendChild(crear("td", "", c.naviera));
      f.appendChild(crear("td", "", `${c.posicion}/N${c.nivel}`));
      f.appendChild(crear("td", "", `${c.peso_declarado_g} g`));
      f.appendChild(crear("td", "", c.autorizacion));
      f.appendChild(crear("td", "", fechaLocal(c.ingreso_en)));
      f.appendChild(crear("td", "", String(c.remociones)));
      cuerpo.appendChild(f);
    });
    tabla.appendChild(cuerpo);
    lista.appendChild(tabla);
  }

  function pintarTurnos(filas) {
    limpiar(turnos);
    if (filas.length === 0) {
      turnos.appendChild(crear("p", "texto-ayuda", "Sin turnos en curso."));
      return;
    }
    const tabla = crear("table", "tabla-datos");
    tabla.appendChild(encabezado(["Turno", "Contenedor", "Vehículo", "Operación", "Estado", "Inicio", ""]));
    const cuerpo = crear("tbody");
    filas.forEach((t) => {
      const f = crear("tr");
      f.appendChild(crear("td", "", `T${t.id}`));
      f.appendChild(crear("td", "", t.contenedor_id));
      f.appendChild(crear("td", "", t.vehiculo));
      f.appendChild(crear("td", "", t.tipo_op));
      f.appendChild(crear("td", `estado estado-${t.estado.toLowerCase()}`, t.estado));
      f.appendChild(crear("td", "", fechaLocal(t.creado_en)));
      const accion = crear("td");
      if (t.retenible) {
        const boton = crear("button", "boton boton-chico peligro", "Retener turno (RT05)");
        boton.addEventListener("click", () => retener(t));
        accion.appendChild(boton);
      } else {
        // §8.1: Retenido solo desde garita, pesajes o salida; el servidor lo impone igual.
        const motivo = t.estado === "Retenido" ? "Ya retenido" : "No retenible en este tramo";
        accion.appendChild(crear("span", "texto-ayuda", motivo));
      }
      f.appendChild(accion);
      cuerpo.appendChild(f);
    });
    tabla.appendChild(cuerpo);
    turnos.appendChild(tabla);
  }

  async function retener(t) {
    const motivo = window.prompt(
      `Retención documental RT05 del turno ${t.id} (contenedor ${t.contenedor_id}). Motivo:`
    );
    if (!motivo || !motivo.trim()) return;
    try {
      await postJson(`/api/autoridad/turnos/${t.id}/retener`, { motivo: motivo.trim() });
      texto(error, "");
      cargarTurnos();
    } catch (e) {
      mostrarError(error, `Retener turno: ${e.message}`);
    }
  }

  function suscribir() {
    const cred = credencialesMqtt();
    const cliente = new ClienteMqtt({
      url: urlWs(),
      usuario: cred.usuario,
      contrasena: cred.contrasena,
      alMensaje: (_topico, carga) => {
        const tipo = tipoDeMensaje(carga);
        if (TIPOS_QUE_CAMBIAN_TURNOS.has(tipo)) cargarTurnos();
        if (TIPOS_QUE_CAMBIAN_PATIO.has(tipo)) cargarInventario();
      },
    });
    cliente.iniciar();
    window.addEventListener("beforeunload", () => cliente.detener());
  }

  function cargarTodo() {
    cargarTurnos();
    cargarInventario();
  }

  document.getElementById("cc-btn")?.addEventListener("click", cargarTodo);
  buscar?.addEventListener("keydown", (evento) => {
    if (evento.key === "Enter") cargarTodo();
  });
  cargarTodo();
  suscribir();
}

function encabezado(textos) {
  const t = crear("thead");
  const f = crear("tr");
  textos.forEach((tx) => f.appendChild(crear("th", "", tx)));
  t.appendChild(f);
  return t;
}
