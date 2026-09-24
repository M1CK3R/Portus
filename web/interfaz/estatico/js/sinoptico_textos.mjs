// Traducción de los valores del controlador a los estados del sinóptico
// (SPECS §14.1, enunciado 4.1). Los valores de entrada están fijados en
// docs/protocolo_serial.md §3.1.1; uno desconocido se muestra tal cual en vez
// de ocultarse, para que una discrepancia con el firmware sea visible.

const TEXTO_GRUA = {
  REPOSO: "en reposo",
  REFERENCIANDO: "referenciando",
  DESPLAZANDO: "desplazándose",
  IZANDO: "izando",
  TRASLADANDO: "trasladando",
  DEPOSITANDO: "depositando",
  SUSPENDIDA: "suspendida",
  FALLA: "en falla",
};

const TEXTO_AGUJA = {
  RECTA: "recta",
  PARQUEO: "hacia parqueo",
  LIBERANDO: "liberando parqueo",
};

const TEXTO_TRANSFERENCIA = {
  POSICIONANDO: "vehículo posicionándose",
  ALINEADO: "vehículo alineado",
  INICIO: "transferencia en curso",
  ABORTO: "operación abortada",
  FIN: "libre",
};

const TEXTO_MODO = {
  NORMAL: "operación normal",
  MANTENIMIENTO: "mantenimiento",
  DEGRADADO: "degradado",
};

// Efecto físico que confirma el ACK de cada comando sobre un elemento.
export const EFECTO_ACK = {
  AbrirTalanquera: ["op-talanquera", "abierta"],
  CerrarTalanquera: ["op-talanquera", "cerrada"],
  AbrirPuertaSalida: ["op-puerta", "abierta"],
  AgujaRecta: ["op-aguja", "recta"],
  AgujaParqueo: ["op-aguja", "hacia parqueo"],
  AgujaLiberar: ["op-aguja", "liberando parqueo"],
};

export const GRUA_SUSPENDIDA = "SUSPENDIDA";
export const GRUA_REPOSO = "REPOSO";
export const MODO_MANTENIMIENTO = "MANTENIMIENTO";

function traducir(tabla, valor) {
  const clave = String(valor ?? "").toUpperCase();
  return tabla[clave] || String(valor ?? "—");
}

export const textoGrua = (valor) => traducir(TEXTO_GRUA, valor);
export const textoAguja = (valor) => traducir(TEXTO_AGUJA, valor);
export const textoTransferencia = (valor) => traducir(TEXTO_TRANSFERENCIA, valor);
export const textoModo = (valor) => traducir(TEXTO_MODO, valor);

export function duracionDesde(iso, ahoraMs) {
  // Tiempo de retención de la plaza en «h:mm» o «m min» (§14.1).
  const inicio = Date.parse(iso || "");
  if (Number.isNaN(inicio)) return "";
  const minutos = Math.max(0, Math.floor((ahoraMs - inicio) / 60000));
  return minutos >= 60
    ? `${Math.floor(minutos / 60)} h ${String(minutos % 60).padStart(2, "0")} min`
    : `${minutos} min`;
}
