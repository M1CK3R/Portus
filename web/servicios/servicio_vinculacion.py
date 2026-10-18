"""Código de vinculación de transportistas (SPECS §15.1, §14.5, A17).

TERMINAL genera, por cada transportista, un código de 6 caracteres de un
solo uso con vigencia de 60 minutos; generar uno nuevo invalida los activos
anteriores del mismo transportista. El alfabeto excluye los caracteres
ambiguos ``0/O`` y ``1/I/L`` y la generación usa fuente criptográfica
(``secrets``, PY-8). El bot de mensajería (Etapa 10) lo consume con
``/vincular CODIGO``: comparación en tiempo constante y asociación del chat
en la misma transacción que marca el código como usado.
"""

import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from web.modelos.usuario import Rol, Usuario
from web.modelos.vinculacion import CodigoVinculacion
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.repositorios.repositorio_vinculos import RepositorioVinculos
from web.tiempo import marca_utc

LONGITUD_CODIGO = 6
VIGENCIA_CODIGO_MIN = 60
ALFABETO_CODIGO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
"""31 caracteres sin ``0/O`` y sin ``1/I/L`` (§15.1 [PROP]): 31^6 ≈ 887M combinaciones."""


class ServicioVinculacion:
    """Genera y consume códigos de vinculación con su ciclo completo (§15.1)."""

    def __init__(
        self,
        vinculos: RepositorioVinculos,
        usuarios: RepositorioUsuarios,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._vinculos = vinculos
        self._usuarios = usuarios
        self._fabrica_instante = fabrica_instante

    def generar(self, transportista_id: int) -> CodigoVinculacion | None:
        """Crea un código nuevo para el transportista; None si el id no es válido.

        ``None`` significa que no existe un usuario con ese id o que su rol
        no es TRANSPORTISTA; la ruta lo responde con 404 para no revelar
        cuál de las dos cosas pasó (§7.5.2).
        """
        transportista = self._usuarios.buscar_por_id(transportista_id)
        if transportista is None or transportista.rol is not Rol.TRANSPORTISTA:
            return None
        ahora = self._fabrica_instante()
        codigo = "".join(secrets.choice(ALFABETO_CODIGO) for _ in range(LONGITUD_CODIGO))
        creado = CodigoVinculacion(
            codigo=codigo,
            transportista_id=transportista_id,
            creado_en=marca_utc(ahora),
            expira_en=marca_utc(ahora + timedelta(minutes=VIGENCIA_CODIGO_MIN)),
        )
        self._vinculos.reemplazar_activo(creado, marca_utc(ahora))
        return creado

    def consumir(self, codigo_texto: str) -> Usuario | None:
        """Consume un código vigente y devuelve su transportista, sin asociar cuenta (§15.1).

        La comparación contra los códigos activos es en tiempo constante
        (PY-8); el texto se normaliza para tolerar minúsculas y espacios.
        """
        ahora = marca_utc(self._fabrica_instante())
        objetivo = self._buscar_activo(codigo_texto, ahora)
        if objetivo is None:
            return None
        self._vinculos.marcar_usado(objetivo.codigo, ahora)
        return self._usuarios.buscar_por_id(objetivo.transportista_id)

    def vincular_cuenta(self, codigo_texto: str, id_chat: int) -> Usuario | None:
        """``/vincular CODIGO``: consume el código y asocia el chat (§15.1 pasos 2-4).

        Devuelve el transportista para confirmar con su nombre, o None si el
        código es inválido, ya se usó o venció (la respuesta no distingue
        cuál, para no orientar a quien prueba códigos al azar).
        """
        ahora = marca_utc(self._fabrica_instante())
        objetivo = self._buscar_activo(codigo_texto, ahora)
        if objetivo is None:
            return None
        transportista_id = self._vinculos.consumir_y_vincular(objetivo.codigo, id_chat, ahora)
        if transportista_id is None:
            return None
        return self._usuarios.buscar_por_id(transportista_id)

    def _buscar_activo(self, codigo_texto: str, ahora: str) -> CodigoVinculacion | None:
        """Código vigente que coincide, comparado en tiempo constante (PY-8)."""
        codigo_normalizado = codigo_texto.strip().upper()
        objetivo: CodigoVinculacion | None = None
        for candidato in self._vinculos.activos(ahora):
            if hmac.compare_digest(candidato.codigo, codigo_normalizado):
                objetivo = candidato
        return objetivo

    def listar_panel_vinculacion(self) -> list["TransportistaPanel"]:
        """Lista de transportistas con su estado de vinculación (§14.5, A17).

        ``vinculado`` indica que ya consumió un código (la cuenta de mensajería
        quedó asociada); ``codigo_activo`` trae el código vigente y su expiración
        para mostrar el tiempo restante e invalidar el anterior al generar uno.
        """
        ahora = self._fabrica_instante()
        ts = marca_utc(ahora)
        activos = {c.transportista_id: c for c in self._vinculos.activos(ts)}
        vinculados = self._vinculos.vinculados()
        return [
            TransportistaPanel(
                id=t.id,
                nombre_mostrado=t.nombre_mostrado,
                username=t.username,
                vinculado=t.id in vinculados,
                codigo_activo=activos[t.id].codigo if t.id in activos else None,
                expira_en=activos[t.id].expira_en if t.id in activos else None,
            )
            for t in self._usuarios.listar_por_rol(Rol.TRANSPORTISTA)
        ]


@dataclass(frozen=True)
class TransportistaPanel:
    """Fila del panel de vinculación de transportistas (§14.5, A17)."""

    id: int
    nombre_mostrado: str
    username: str
    vinculado: bool
    codigo_activo: str | None
    expira_en: str | None
