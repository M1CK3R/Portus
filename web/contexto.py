"""Contexto inyectado a las rutas: dueño único de los servicios (CODESTYLE PY-7)."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import flask

from web.configuracion.configuracion_web import ConfiguracionWeb
from web.repositorios.repositorio_auditoria import RepositorioAuditoria
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.repositorios.repositorio_vinculos import RepositorioVinculos
from web.servicios.servicio_auth import ServicioAuth
from web.servicios.servicio_vinculacion import ServicioVinculacion


@dataclass(frozen=True)
class ContextoWeb:
    """Todo lo que una ruta puede usar; vive en ``app.extensions`` (PY-7)."""

    usuarios: RepositorioUsuarios
    manifiestos: RepositorioManifiestos
    vinculos: RepositorioVinculos
    auditoria: RepositorioAuditoria
    servicio_auth: ServicioAuth
    servicio_vinculacion: ServicioVinculacion
    configuracion: ConfiguracionWeb
    reloj_epoch: Callable[[], float]


def fabrica_instante_utc() -> datetime:
    """Instante UTC por omisión para los servicios (PY-5; pruebas inyectan el suyo)."""
    return datetime.now(UTC)


def contexto() -> ContextoWeb:
    """Recupera el contexto de la aplicación en curso (rutas y decoradores)."""
    return cast(ContextoWeb, flask.current_app.extensions[CLAVE_CONTEXTO])


CLAVE_CONTEXTO = "contexto_portus"
CLAVE_AUDITORIA = "repositorio_auditoria"
RELOJ_EPOCH_POR_OMISION = time.time
