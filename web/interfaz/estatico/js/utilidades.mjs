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
      detalle = cuerpo.mensaje || cuerpo.error || "";
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
    throw new Error(data?.mensaje || data?.error || `${resp.status}`);
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

export function urlWs() {
  // El broker WebSocket (mosquitto, §19.2). La web inyecta la URL completa en
  // data-mqtt-ws (con host/puerto de config); sin ese atributo se arma con
  // el hostname del navegador en el puerto 9001 por omisión (JS-4).
  const override = document.body.dataset.mqttWs;
  if (override) {
    return override;
  }
  return `ws://${window.location.hostname}:9001/`;
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
