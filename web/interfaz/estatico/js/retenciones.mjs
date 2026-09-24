// Pestaña Retenciones de TERMINAL (SPECS §14.3, §10): bandeja completa con las
// seis causas; los botones de cada fila dependen del rol facultado (§10.2).

import { iniciarBandeja } from "./bandeja_retenciones.mjs";

export function iniciarRetenciones() {
  if (!document.getElementById("retenciones")) return;
  iniciarBandeja("ret");
}
