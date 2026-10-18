"""AUTORIDAD: levantes y consulta de carga (SPECS §14.9, §9.1, Etapa 7).

Otorga el levante con canal verde/rojo o lo retiene con motivo; la bandeja
trae la identidad del manifiesto, contenedor, naviera, agente, declaración y
peso. Consulta de carga: cualquier contenedor sin restricción de propietario.
Otorgar y retener avisan al transportista de la carga (§15.3 avisos 1 y 2).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.declaracion import Declaracion, SolicitudLevante
from web.modelos.notificacion import TipoNotificacion
from web.repositorios.repositorio_declaraciones import RepositorioDeclaraciones
from web.repositorios.repositorio_inventario import FilaInventario, RepositorioInventario
from web.repositorios.repositorio_levantes import RepositorioLevantes
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.servicios.notificador import Notificador
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

TOPICO_SRV_CITA = "portus/srv/cita"
"""Los avisos del levante viajan con los de citas: el levante habilita la cita (§11.1 regla 3)."""


class ServicioLevantes:
    """Operaciones de AUTORIDAD en la cadena documental (§14.9)."""

    def __init__(
        self,
        levantes: RepositorioLevantes,
        manifiestos: RepositorioManifiestos,
        declaraciones: RepositorioDeclaraciones,
        inventario: RepositorioInventario,
        usuarios: RepositorioUsuarios,
        notificador: Notificador,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._levantes = levantes
        self._manifiestos = manifiestos
        self._declaraciones = declaraciones
        self._inventario = inventario
        self._usuarios = usuarios
        self._notificador = notificador
        self._fabrica_instante = fabrica_instante

    def pendientes(self) -> list[SolicitudLevante]:
        """Bandeja de solicitudes de levante pendientes (§14.9)."""
        levantes = self._levantes.listar_pendientes()
        resultado: list[SolicitudLevante] = []
        for lev in levantes:
            m = self._manifiestos.buscar_por_id(lev.manifiesto_id)
            if m is None:
                continue
            naviera = self._buscar_nombre_usuario(m.naviera_id)
            agente = self._buscar_nombre_usuario(lev.agente_id) if lev.agente_id else "—"
            decl = self._declaraciones.de_manifiesto(m.id)
            numero = decl.numero if decl else "—"
            resultado.append(
                SolicitudLevante(
                    levante_id=lev.id,
                    manifiesto_id=m.id,
                    contenedor_id=m.contenedor_id,
                    naviera=naviera,
                    agente=agente,
                    numero_declaracion=numero,
                    peso_declarado_g=m.peso_declarado_g,
                    estado=lev.estado,
                )
            )
        return resultado

    def otorgar(self, levante_id: int, canal: str, autoridad_id: int) -> tuple[bool, str]:
        """Otorga el levante con canal verde/rojo (§9.1, §9.2)."""
        if canal not in ("verde", "rojo"):
            return (False, "CANAL_INVALIDO")
        ts = marca_utc(self._fabrica_instante())
        lev = self._levantes.buscar_por_id(levante_id)
        if lev is None:
            return (False, "LEVANTE_INEXISTENTE")
        ok = self._levantes.otorgar(levante_id, canal, autoridad_id, ts)
        if not ok:
            return (False, "LEVANTE_NO_PENDIENTE")
        self._manifiestos.marcar_documental(lev.manifiesto_id, "levante_otorgado")
        self._notificar(lev.manifiesto_id, TipoNotificacion.LEVANTE_OTORGADO, {"canal": canal})
        REGISTRO.info("Levante %d otorgado (canal %s)", levante_id, canal)
        return (True, "")

    def retener(self, levante_id: int, motivo: str, autoridad_id: int) -> tuple[bool, str]:
        """Retiene el levante con motivo (§9.1, §9.2)."""
        if not motivo.strip():
            return (False, "MOTIVO_REQUERIDO")
        ts = marca_utc(self._fabrica_instante())
        lev = self._levantes.buscar_por_id(levante_id)
        if lev is None:
            return (False, "LEVANTE_INEXISTENTE")
        ok = self._levantes.retener(levante_id, motivo, autoridad_id, ts)
        if not ok:
            return (False, "LEVANTE_NO_PENDIENTE")
        self._manifiestos.marcar_documental(lev.manifiesto_id, "levante_retenido")
        self._notificar(
            lev.manifiesto_id, TipoNotificacion.LEVANTE_RETENIDO, {"motivo": motivo.strip()}
        )
        REGISTRO.info("Levante %d retenido: %s", levante_id, motivo)
        return (True, "")

    def ver_declaracion(self, levante_id: int) -> Declaracion | None:
        """Devuelve la declaración del manifiesto del levante (§14.9)."""
        lev = self._levantes.buscar_por_id(levante_id)
        if lev is None:
            return None
        return self._declaraciones.de_manifiesto(lev.manifiesto_id)

    def consulta_carga(self, contenedor_id: str | None = None) -> list["FilaInventario"]:
        """Consulta de carga: cualquier contenedor en el patio (§14.9)."""
        filas = self._inventario.inventario_completo()
        if contenedor_id:
            filas = [f for f in filas if contenedor_id.lower() in f.contenedor_id.lower()]
        return filas

    def _notificar(
        self, manifiesto_id: int, tipo: TipoNotificacion, extra: dict[str, object]
    ) -> None:
        """Avisos 1 y 2 al transportista del manifiesto, con su contenedor (§15.3)."""
        manifiesto = self._manifiestos.buscar_por_id(manifiesto_id)
        if manifiesto is None:
            return
        payload: dict[str, object] = {
            "manifiesto": manifiesto.id,
            "contenedor": manifiesto.contenedor_id,
            **extra,
        }
        self._notificador.notificar(TOPICO_SRV_CITA, manifiesto.transportista_id, tipo, payload)

    def _buscar_nombre_usuario(self, usuario_id: int) -> str:
        u = self._usuarios.buscar_por_id(usuario_id)
        return u.nombre_mostrado if u else f"usuario {usuario_id}"
