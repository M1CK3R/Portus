// Causas de rechazo de comandos con su texto legible (SPECS §6.5): §6.2 regla 2
// exige mostrar la causa exacta. Espejo de web/modelos/comando.py; la prueba
// test_comandos_etapa9 verifica que estén todos los códigos.

import { crear, limpiar } from "./utilidades.mjs";

const TEXTO_CAUSA = {
  VEH_BAJO_TALANQUERA: "Hay un vehículo detectado bajo la talanquera",
  VEH_BAJO_PUERTA: "Hay un vehículo detectado bajo la puerta de salida",
  VEH_SOBRE_AGUJA: "Hay un vehículo sobre la aguja",
  PARQUEO_VACIO: "No hay vehículo en el parqueo",
  GRUA_CON_CARGA: "La grúa tiene carga adherida",
  GRUA_EN_TRABAJO: "Hay un trabajo de grúa en ejecución",
  GRUA_EN_FALLA: "La grúa está en falla sin rearme",
  POS_EN_TRABAJO: "La posición es origen o destino de un trabajo en ejecución",
  INCONSISTENCIA_PERSISTE: "La inconsistencia física que originó el bloqueo persiste",
  VEH_EN_TRANSFERENCIA: "Hay un vehículo en transferencia",
  SIN_RESPUESTA: "El controlador no respondió (generado por el puente)",
};

export function textoCausa(codigo) {
  // Código desconocido: se muestra tal cual para que la discrepancia se vea.
  if (!codigo) return "sin causa informada";
  return TEXTO_CAUSA[codigo] ? `${TEXTO_CAUSA[codigo]} (${codigo})` : codigo;
}

export function textoRespuesta(datos) {
  // «Nombre: aceptado» o «Nombre: rechazado · causa exacta» (§6.2 reglas 1 y 2).
  const nombre = datos.nombre || "Comando";
  if (datos.estado === "ACK") {
    return datos.tardia ? `${nombre}: aceptado (respuesta tardía)` : `${nombre}: aceptado`;
  }
  return `${nombre}: rechazado · ${textoCausa(datos.causa)}`;
}

export function mostrarRespuesta(contenedor, datos) {
  // Aviso en la pestaña que emitió el comando (Patio, Alarmas); JS-3: textContent.
  if (!contenedor) return;
  limpiar(contenedor);
  const clase = datos.estado === "ACK" ? "aviso-ok" : "error";
  contenedor.appendChild(crear("p", clase, textoRespuesta(datos)));
}
