"""Utilidades de prueba de la lógica del turno: publicador capturado y siembra (T-3, T-5).

``crear_logica`` arma el núcleo sobre una BD temporal con reloj falso y un
publicador que captura todo lo que iría al broker. ``sembrar_operacion`` deja
lo mínimo para que una identificación en garita sea autorizada (§9.4):
vehículo con tara, manifiesto vigente, levante otorgado y cita programada en
la franja que contiene al reloj falso (2026-09-20 08:00 local = 14:03 UTC).
``enviar`` entrega un evento del controlador con el envoltorio §5.2.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from pruebas.utilidades_pruebas import RelojUtcFalso
from web.modelos.usuario import Rol
from web.repositorios.conexion_bd import RUTA_ESQUEMA_POR_OMISION, ConexionBd
from web.repositorios.repositorio_citas import RepositorioCitas
from web.repositorios.repositorio_levantes import RepositorioLevantes
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_plazas import RepositorioPlazas
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos
from web.servicios.nucleo_logica import NucleoLogica
from web.servicios.nucleo_logica import crear as crear_nucleo

FECHA_FRANJA = "2026-09-20"
INICIO_FRANJA = "08:00"
"""Franja local que contiene el instante fijo del reloj falso (08:03 en UTC-6)."""
PESO_DECLARADO_G = 38_500
TARA_G = 950
CREADO_EN = "2026-09-20T13:00:00.000Z"
POSICIONES_PATIO = ("P1", "P2", "P3", "P4")


class PublicadorCapturado:
    """Duplicado del puerto MQTT de la lógica: guarda publicaciones y comandos (T-5)."""

    def __init__(self) -> None:
        self.publicados: list[tuple[str, str, dict[str, object]]] = []
        self.comandos: list[tuple[str, str, dict[str, str]]] = []

    def publicar(self, topico: str, tipo: str, datos: dict[str, object]) -> None:
        self.publicados.append((topico, tipo, datos))

    def publicar_comando(self, nombre: str, parametros: dict[str, str], usuario: str) -> str:
        cmd_id = f"cmd-{len(self.comandos) + 1}"
        self.comandos.append((cmd_id, nombre, parametros))
        return cmd_id

    def nombres_de_comandos(self) -> list[str]:
        return [nombre for _, nombre, _ in self.comandos]

    def ultimo_comando(self, nombre: str) -> tuple[str, dict[str, str]]:
        """(cmd_id, parámetros) del último comando con ese nombre."""
        cmd_id, _, parametros = next(c for c in reversed(self.comandos) if c[1] == nombre)
        return cmd_id, parametros

    def datos_de(self, tipo: str) -> list[dict[str, object]]:
        """Bloques ``datos`` publicados con ese ``tipo``, en orden."""
        return [datos for _, tipo_publicado, datos in self.publicados if tipo_publicado == tipo]


@dataclass
class LogicaPrueba:
    """Núcleo de prueba con sus dependencias a mano para preparar escenarios."""

    nucleo: NucleoLogica
    bd: ConexionBd
    reloj: RelojUtcFalso
    publicador: PublicadorCapturado
    plazas: RepositorioPlazas
    manifiestos: RepositorioManifiestos
    levantes: RepositorioLevantes


def crear_logica(tmp_path: Path) -> LogicaPrueba:
    """Núcleo completo sobre una BD temporal con el patio P1-P4 (BD-2 real)."""
    bd = ConexionBd(str(tmp_path / "logica.db"), RUTA_ESQUEMA_POR_OMISION)
    with bd.candado:
        bd.conexion.executemany(
            "INSERT OR IGNORE INTO posicion_patio (id, estado) VALUES (?, 'libre')",
            [(posicion,) for posicion in POSICIONES_PATIO],
        )
        bd.conexion.commit()
    reloj = RelojUtcFalso()
    publicador = PublicadorCapturado()
    return LogicaPrueba(
        nucleo=crear_nucleo(bd, publicador, reloj),
        bd=bd,
        reloj=reloj,
        publicador=publicador,
        plazas=RepositorioPlazas(bd),
        manifiestos=RepositorioManifiestos(bd),
        levantes=RepositorioLevantes(bd),
    )


def sembrar_operacion(
    logica: LogicaPrueba,
    vehiculo: str = "V01",
    contenedor: str = "C01",
    tipo_op: str = "DEPOSITO",
    canal: str = "verde",
    inicio_franja: str = INICIO_FRANJA,
) -> int:
    """Siembra una operación autorizable en garita y devuelve el id del manifiesto.

    Cada vehículo tiene su propio transportista (``tr-v01`` para V01) para
    que la garita elija sin ambigüedad el manifiesto de ese vehículo.
    """
    bd = logica.bd
    usuarios = RepositorioUsuarios(bd)
    naviera_id = _usuario(usuarios, "naviera-op", Rol.NAVIERA)
    transportista_id = _usuario(usuarios, f"tr-{vehiculo.lower()}", Rol.TRANSPORTISTA)
    with bd.candado:
        bd.conexion.execute(
            "INSERT OR IGNORE INTO contenedor (id, descripcion) VALUES (?, 'prueba')",
            (contenedor,),
        )
        bd.conexion.commit()
    vehiculos = RepositorioVehiculos(bd)
    if vehiculos.buscar_por_identificador(vehiculo) is None:
        vehiculos.crear(vehiculo, transportista_id, TARA_G)
    logica.manifiestos.crear_demo(
        contenedor, naviera_id, transportista_id, tipo_op, PESO_DECLARADO_G, CREADO_EN
    )
    manifiesto_id = logica.manifiestos.vigentes_de_transportista(transportista_id)[-1].id
    logica.manifiestos.marcar_documental(manifiesto_id, "levante_otorgado")
    logica.levantes.crear(manifiesto_id, "otorgada", canal)
    RepositorioCitas(bd).crear(
        manifiesto_id, transportista_id, FECHA_FRANJA, inicio_franja, CREADO_EN
    )
    return manifiesto_id


def enviar(
    logica: LogicaPrueba, tipo: str, datos: dict[str, object], seq: int, id_evento: str = ""
) -> None:
    """Entrega un evento del controlador como si llegara por MQTT (envoltorio §5.2)."""
    contenido = {
        "id": id_evento or f"evt-{tipo}-{seq}-{json.dumps(datos, sort_keys=True)}",
        "ts": "2026-09-20T14:03:22.418Z",
        "origen": "controlador",
        "tipo": tipo,
        "seq": seq,
        "datos": datos,
    }
    topico = "portus/evt/" + tipo.split(".")[0]
    logica.nucleo.atender_mensaje(topico, json.dumps(contenido).encode("utf-8"))


def _usuario(usuarios: RepositorioUsuarios, username: str, rol: Rol) -> int:
    existente = usuarios.con_hash_por_username(username)
    if existente is None:
        usuarios.crear(username, "x", rol, username, CREADO_EN)
        existente = usuarios.con_hash_por_username(username)
    if existente is None:
        mensaje = f"no se pudo crear el usuario de prueba {username}"
        raise RuntimeError(mensaje)
    return existente[0].id
