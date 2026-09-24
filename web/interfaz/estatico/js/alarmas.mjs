// Pestaña Alarmas (SPECS §13.2, §13.3): activas e históricas, filtro por
// severidad, Reconocer (comentario opcional; CRITICA y ALTA una por una),
// Reconocer todas (solo BAJA y MEDIA), Silenciar (AlarmaSilenciar, no reconoce)
// y el catálogo AL01-AL14. Se refresca por evento MQTT (JS-2); textContent (JS-3).

import { mostrarRespuesta, textoCausa } from "./causas_comando.mjs";
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

const TIPOS_QUE_CAMBIAN_ALARMAS = new Set([
  "alarma.resumen",
  "alarma.reconocida",
  "alarma.servidor",
  "alarma.controlador",
]);
const SEVERIDADES_EN_LOTE = new Set(["BAJA", "MEDIA"]);

export function iniciarAlarmas() {
  const raiz = document.getElementById("alarmas");
  if (!raiz) return;
  const contActivas = document.getElementById("alarmas-activas");
  const contHistoricas = document.getElementById("alarmas-historicas");
  const contCatalogo = document.getElementById("alarmas-catalogo");
  const error = document.getElementById("alarmas-error");
  const aviso = document.getElementById("alarmas-aviso");
  const severidad = document.getElementById("alarmas-filtro-severidad");
  let silencioPendiente = null;

  async function cargar() {
    try {
      const params = severidad?.value ? `?severidad=${severidad.value}` : "";
      const datos = await getJson(`/api/alarmas${params}`);
      pintarActivas(datos.activas || []);
      pintarHistoricas(datos.historicas || []);
      pintarCatalogo(datos.catalogo || []);
      texto(error, "");
    } catch (e) {
      mostrarError(error, `No se pudieron cargar las alarmas: ${e.message}`);
    }
  }

  function pintarActivas(filas) {
    const cuerpo = tabla(contActivas, filas, [
      "#", "Código", "Severidad", "Origen", "Descripción", "Detalle", "Rep.", "Aparición", "",
    ]);
    filas.forEach((a) => {
      const fila = filaBase(a);
      fila.appendChild(crear("td", "", String(a.repeticiones)));
      fila.appendChild(crear("td", "", fechaLocal(a.ts)));
      const accion = crear("td");
      const boton = crear("button", "boton boton-chico", "Reconocer");
      boton.addEventListener("click", () => reconocer(a));
      accion.appendChild(boton);
      if (!SEVERIDADES_EN_LOTE.has(a.severidad)) {
        accion.appendChild(crear("span", "texto-ayuda", " una por una"));
      }
      fila.appendChild(accion);
      cuerpo?.appendChild(fila);
    });
  }

  function pintarHistoricas(filas) {
    const cuerpo = tabla(contHistoricas, filas, [
      "#", "Código", "Severidad", "Origen", "Descripción", "Detalle", "Aparición", "Reconocida",
      "Comentario",
    ]);
    filas.forEach((a) => {
      const fila = filaBase(a);
      fila.appendChild(crear("td", "", fechaLocal(a.ts)));
      const quien = a.reconocida_por_usuario ? ` · ${a.reconocida_por_usuario}` : "";
      fila.appendChild(crear("td", "", `${fechaLocal(a.reconocida_ts)}${quien}`));
      fila.appendChild(crear("td", "", a.comentario || "—"));
      cuerpo?.appendChild(fila);
    });
  }

  function pintarCatalogo(filas) {
    const cuerpo = tabla(contCatalogo, filas, ["Código", "Severidad", "Origen", "Descripción"]);
    filas.forEach((c) => {
      const fila = crear("tr", `sev-${c.severidad.toLowerCase()}`);
      [c.codigo, c.severidad, c.origen, c.descripcion].forEach((v) => fila.appendChild(crear("td", "", v)));
      cuerpo?.appendChild(fila);
    });
  }

  function filaBase(a) {
    const fila = crear("tr", `sev-${a.severidad.toLowerCase()}`);
    [String(a.id), a.codigo, a.severidad, a.origen, a.descripcion, detalle(a)].forEach((v) =>
      fila.appendChild(crear("td", "", v))
    );
    return fila;
  }

  async function reconocer(a) {
    const comentario = window.prompt(`Reconocer ${a.codigo} (${a.descripcion}). Comentario (opcional):`);
    if (comentario === null) return;
    try {
      await postJson(`/api/alarmas/${a.id}/reconocer`, { comentario });
      cargar();
    } catch (e) {
      mostrarError(error, `Reconocer: ${e.message}`);
    }
  }

  async function reconocerTodas() {
    if (!window.confirm("¿Reconocer todas las alarmas de severidad baja y media?")) return;
    try {
      const r = await postJson("/api/alarmas/reconocer-todas", {});
      texto(aviso, `${r.reconocidas} alarma(s) reconocidas; las críticas y altas siguen pendientes.`);
      cargar();
    } catch (e) {
      mostrarError(error, `Reconocer todas: ${e.message}`);
    }
  }

  async function silenciar() {
    try {
      const r = await postJson("/api/comandos/AlarmaSilenciar", { parametros: {} });
      silencioPendiente = r.cmd_id;
      texto(aviso, "AlarmaSilenciar: enviado, esperando al controlador…");
    } catch (e) {
      mostrarError(error, `Silenciar: ${e.message}`);
    }
  }

  function aplicarMensaje(_topico, carga) {
    const tipo = tipoDeMensaje(carga);
    if (tipo === "comando.respuesta" && silencioPendiente) {
      const datos = JSON.parse(carga).datos || {};
      if (datos.cmd_id === silencioPendiente) {
        mostrarRespuesta(aviso, { ...datos, nombre: "AlarmaSilenciar" });
        silencioPendiente = null;
      }
    }
    if (TIPOS_QUE_CAMBIAN_ALARMAS.has(tipo)) cargar();
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

  document.getElementById("alarmas-reconocer-todas")?.addEventListener("click", reconocerTodas);
  document.getElementById("alarmas-silenciar")?.addEventListener("click", silenciar);
  severidad?.addEventListener("change", cargar);
  cargar();
  suscribir();
}

function detalle(a) {
  // Resumen legible de los datos propios de cada alarma (JS-3: solo texto).
  const d = a.datos || {};
  switch (a.codigo) {
    case "AL14":
      return `${d.nombre ?? "comando"} · ${textoCausa(d.causa)}`;
    case "AL12":
      return `retención ${d.retencion} (${d.causa}) · turno ${d.turno}`;
    case "AL13":
      return `${d.contenedor} en ${d.posicion}/N${d.nivel} · ${d.permanencia_h} h`;
    case "AL09":
      return `${d.comparado_g} g contra ${d.referencia_g} g (${d.diferencia_pct} %)`;
    case "AL10":
    case "AL11":
      return [d.vehiculo, d.detalle ?? d.causa].filter(Boolean).join(" · ");
    case "AL01":
      return d.retroactiva ? `pérdida previa desde ${fechaLocal(d.desde)}` : `${d.ms_sin_latido ?? "—"} ms sin latido`;
    default:
      return Object.keys(d).length ? JSON.stringify(d) : "—";
  }
}

function tabla(contenedor, filas, columnas) {
  if (!contenedor) return null;
  limpiar(contenedor);
  if (filas.length === 0) {
    contenedor.appendChild(crear("p", "texto-ayuda", "Sin alarmas."));
    return null;
  }
  const t = crear("table", "tabla-datos");
  const cabeza = crear("thead");
  const f = crear("tr");
  columnas.forEach((c) => f.appendChild(crear("th", "", c)));
  cabeza.appendChild(f);
  t.appendChild(cabeza);
  const cuerpo = crear("tbody");
  t.appendChild(cuerpo);
  contenedor.appendChild(t);
  return cuerpo;
}
