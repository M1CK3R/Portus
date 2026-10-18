// Configuración compartida del lado del navegador (CODESTYLE JS-4: el prefijo
// de tópicos y los umbrales vienen de aquí, no de cadenas repetidas).

// Prefijo exacto del SPECS §5.1; el broker publica bajo este espacio.
export const TOPIC_PREFIX = "portus";

// Umbral de permanencia excesiva (SPECS §12.2, §13.1: 2 horas → AL13).
export const PERMANENCIA_EXCESIVA_HORAS = 2;

// Rol facultado por causa (SPECS §10.2; docs/constantes_protocolo.json).
export const ROL_FACULTADO = {
  RT01: "TERMINAL",
  RT02: "TERMINAL",
  RT03: "AUTORIDAD",
  RT04: "TERMINAL",
  RT05: "AUTORIDAD",
  RT06: "TERMINAL",
};

// AL12: una retención abierta más de 30 min se resalta en la bandeja (§13.1).
export const LIMITE_RETENCION_MIN = 30;

// Estados desde los que §8.1 admite Retenido (web/modelos/turno.py:puede_retenerse).
export const ESTADOS_RETENIBLES = new Set(["EnGarita", "EnPesajeEntrada", "EnPesajeSalida", "EnSalida"]);

// Corregir solo aplica a las causas de peso y solo para TERMINAL (§10.3, A12).
export const CAUSAS_DE_PESO = new Set(["RT01", "RT02"]);

// Espejo en la interfaz de web/modelos/retencion.py:puede_resolver. El
// servidor rechaza igual; aquí solo se ocultan los botones (enunciado 4.3 regla 2).
export function puedeResolver(rol, causa, resolucion) {
  if (ROL_FACULTADO[causa] !== rol) return false;
  if (resolucion === "corregir") return rol === "TERMINAL" && CAUSAS_DE_PESO.has(causa);
  return true;
}
