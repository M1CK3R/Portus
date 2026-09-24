// Utilidades compartidas de la interfaz (CODESTYLE JS-1, JS-3).
// Todo dato que viene del servidor o del broker se inserta con textContent,
// nunca con innerHTML (JS-3: previene inyección).

export function texto(elemento, valor) {
  if (elemento) {
    elemento.textContent = valor ?? "";
  }
}

export function limpiar(elemento) {
  if (elemento) {
    while (elemento.firstChild) {
      elemento.removeChild(elemento.firstChild);
    }
  }
}

export function crear(tag, clase, contenido) {
  const el = document.createElement(tag);
  if (clase) {
    el.className = clase;
  }
  if (contenido !== undefined && contenido !== null) {
    el.textContent = String(contenido);
  }
  return el;
}

export async function getJson(url) {
  const resp = await fetch(url, { headers: { Accept: "application/json" } });
  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("sin sesion");
  }
  if (!resp.ok) {
    let detalle = "";
    try {
      const cuerpo = await resp.json();
      detalle = cuerpo.error || cuerpo.mensaje || "";
    } catch {
      // respuesta sin JSON (p. ej. CSV); se ignora
    }
    throw new Error(`${resp.status}: ${detalle}`);
  }
  return resp.json();
}

export async function postJson(url, cuerpo) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(cuerpo || {}),
  });
  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("sin sesion");
  }
  let data = null;
  try {
    data = await resp.json();
  } catch {
    // respuesta sin cuerpo
  }
  if (!resp.ok) {
    throw new Error(data?.error || data?.mensaje || `${resp.status}`);
  }
  return data;
}

export function mostrarError(contenedor, mensaje) {
  if (!contenedor) {
    return;
  }
  limpiar(contenedor);
  contenedor.appendChild(crear("p", "error", mensaje));
}

export function tipoDeMensaje(carga) {
  // «tipo» del envoltorio §5.2; un mensaje mal formado se ignora (P-5).
  try {
    return JSON.parse(carga)?.tipo || "";
  } catch {
    return "";
  }
}

// Hora local de Guatemala: UTC−6 fijo, sin horario de verano (CODESTYLE I-8).
const DESFASE_LOCAL_MS = -6 * 60 * 60 * 1000;

export function fechaLocal(iso) {
  // Marca ISO UTC del servidor → «dd/mm/aaaa HH:MM» local (I-8).
  const ms = Date.parse(iso || "");
  if (Number.isNaN(ms)) return "—";
  const local = new Date(ms + DESFASE_LOCAL_MS);
  const dos = (n) => String(n).padStart(2, "0");
  return (
    `${dos(local.getUTCDate())}/${dos(local.getUTCMonth() + 1)}/${local.getUTCFullYear()} ` +
    `${dos(local.getUTCHours())}:${dos(local.getUTCMinutes())}`
  );
}

const PUERTO_WS_POR_OMISION = "9001";

export function urlWs() {
  // El broker WebSocket vive en el mismo SBC que sirvió la página (§19.2):
  // se usa el hostname con el que el navegador llegó, así funciona desde
  // cualquier equipo de la red local. La web solo inyecta el puerto.
  const puerto = document.body.dataset.mqttWsPuerto || PUERTO_WS_POR_OMISION;
  return `ws://${window.location.hostname}:${puerto}/`;
}

export function credencialesMqtt() {
  // Usuario/contraseña de solo lectura del tablero (§5.5); la web los inyecta
  // en <body> porque el broker rechaza conexiones anónimas.
  const body = document.body.dataset;
  if (body.mqttUsuario && body.mqttContrasena) {
    return { usuario: body.mqttUsuario, contrasena: body.mqttContrasena };
  }
  return { usuario: "", contrasena: "" };
}
