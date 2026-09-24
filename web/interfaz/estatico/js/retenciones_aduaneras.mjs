// Pestaña Retenciones aduaneras de AUTORIDAD (SPECS §14.9): solo RT03 y RT05
// (el servidor filtra), con Aclarar y Rechazar con motivo y sin Corregir.

import { iniciarBandeja } from "./bandeja_retenciones.mjs";

export function iniciarRetencionesAduaneras() {
  if (!document.getElementById("retenciones_aduaneras")) return;
  iniciarBandeja("ra");
}
