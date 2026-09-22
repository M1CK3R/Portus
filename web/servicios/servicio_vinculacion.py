"""Código de vinculación de transportistas (SPECS §15.1, §14.5, A17).

TERMINAL genera, por cada transportista, un código de 6 caracteres de un
solo uso con vigencia de 60 minutos; generar uno nuevo invalida los activos
anteriores del mismo transportista. El alfabeto excluye los caracteres
ambiguos ``0/O`` y ``1/I/L`` y la generación usa fuente criptográfica
(``secrets``, PY-8). El consumo lo hará el bot de mensajería (Etapa 10) con
comparación en tiempo constante; el método ya existe para fijar el ciclo.
"""

import hmac
import secrets
from collections.abc import Callable
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
        """Consume un código vigente y devuelve su transportista (§15.1).

        Es la operación que la Etapa 10 invocará desde ``/vincular CODIGO``.
        La comparación contra los códigos activos es en tiempo constante
        (PY-8); el texto se normaliza para tolerar minúsculas y espacios.
        """
        codigo_normalizado = codigo_texto.strip().upper()
        ahora = self._fabrica_instante()
        objetivo: CodigoVinculacion | None = None
        for candidato in self._vinculos.activos(marca_utc(ahora)):
            if hmac.compare_digest(candidato.codigo, codigo_normalizado):
                objetivo = candidato
                break
        if objetivo is None:
            return None
        self._vinculos.marcar_usado(objetivo.codigo, marca_utc(ahora))
        return self._usuarios.buscar_por_id(objetivo.transportista_id)
