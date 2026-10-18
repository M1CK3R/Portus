"""La BD sigue al controlador: patio y plazas cambian solo con su ACK (SPECS §6.1-§6.3, §23.3).

Un comando que se ejecuta pese a su condición de rechazo penaliza -10 %. Por
eso PosicionBloquear/PosicionLiberar y AgujaLiberar viajan al controlador y el
servidor solo aplica el efecto cuando este responde ACK; un NAK no toca la BD.
"""

import json
from datetime import UTC, datetime

import pytest

from web.modelos.retencion import CausaRetencion, ResolucionRetencion
from web.modelos.usuario import Rol
from web.repositorios.conexion_bd import RUTA_ESQUEMA_POR_OMISION, ConexionBd
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.servicios.nucleo_logica import NucleoLogica
from web.servicios.nucleo_logica import crear as crear_nucleo
from web.servicios.servicio_comandos import ErrorComando
from web.servicios.servicio_parqueo import ErrorPlazaParqueo
from web.servicios.servicio_patio import ErrorPosicion

INSTANTE = datetime(2026, 9, 20, 14, 0, tzinfo=UTC)


class PublicadorCapturado:
    """Duplicado del puerto MQTT: guarda publicaciones y comandos (T-5)."""

    def __init__(self) -> None:
        self.publicados: list[tuple[str, str, dict[str, object]]] = []
        self.comandos: list[tuple[str, str, dict[str, str]]] = []

    def publicar(self, topico: str, tipo: str, datos: dict[str, object]) -> None:
        self.publicados.append((topico, tipo, datos))

    def publicar_comando(self, nombre: str, parametros: dict[str, str], usuario: str) -> str:
        cmd_id = f"cmd-{len(self.comandos) + 1}"
        self.comandos.append((cmd_id, nombre, parametros))
        return cmd_id

    def ultimo_comando(self, nombre: str) -> tuple[str, dict[str, str]]:
        cmd_id, _, parametros = next(c for c in reversed(self.comandos) if c[1] == nombre)
        return cmd_id, parametros


@pytest.fixture()
def entorno(tmp_path):
    bd = ConexionBd(str(tmp_path / "comandos.db"), RUTA_ESQUEMA_POR_OMISION)
    usuarios = RepositorioUsuarios(bd)
    usuarios.crear("terminal01", "x", Rol.TERMINAL, "Terminal", "2026-09-20T13:00:00.000Z")
    usuarios.crear("naviera01", "x", Rol.NAVIERA, "Naviera", "2026-09-20T13:00:00.000Z")
    usuarios.crear("transp01", "x", Rol.TRANSPORTISTA, "Transp", "2026-09-20T13:00:00.000Z")
    with bd.candado:
        bd.conexion.executemany(
            "INSERT OR IGNORE INTO posicion_patio (id, estado) VALUES (?, 'libre')",
            (("P1",), ("P2",)),
        )
        bd.conexion.commit()
    publicador = PublicadorCapturado()
    nucleo = crear_nucleo(bd, publicador, lambda: INSTANTE)
    yield bd, usuarios, publicador, nucleo
    bd.cerrar()


def _responder(nucleo: NucleoLogica, cmd_id: str, estado: str, causa: str | None = None) -> None:
    """Simula el RSP del controlador tal como lo publica el puente (§6.4)."""
    envoltorio = {
        "id": f"rsp-{cmd_id}-{estado}",
        "ts": "2026-09-20T14:00:01.000Z",
        "origen": "controlador",
        "tipo": "comando.respuesta",
        "seq": 7,
        "datos": {"cmd_id": cmd_id, "estado": estado, "causa": causa, "sintetica": False},
    }
    nucleo.atender_mensaje("portus/cmd/respuesta", json.dumps(envoltorio).encode("utf-8"))


def _estado_posicion(nucleo: NucleoLogica, posicion_id: str) -> str:
    return next(p.estado for p in nucleo.patio.posiciones() if p.id == posicion_id)


# ------------------------------------------------------------------ patio


def test_bloquear_posicion_envia_comando_y_solo_aplica_con_ack(entorno) -> None:
    _, _, publicador, nucleo = entorno

    cmd_id = nucleo.patio.solicitar_bloqueo("P1", "terminal01")

    assert publicador.ultimo_comando("PosicionBloquear") == (cmd_id, {"pos": "P1"})
    assert _estado_posicion(nucleo, "P1") == "libre"  # aún sin respuesta
    _responder(nucleo, cmd_id, "ACK")
    assert _estado_posicion(nucleo, "P1") == "bloqueada"


def test_bloqueo_rechazado_por_el_controlador_no_cambia_la_bd(entorno) -> None:
    _, _, _, nucleo = entorno

    cmd_id = nucleo.patio.solicitar_bloqueo("P2", "terminal01")
    _responder(nucleo, cmd_id, "NAK", "POS_EN_TRABAJO")

    assert _estado_posicion(nucleo, "P2") == "libre"
    assert any(a.codigo == "AL14" for a in nucleo.alarmas_svc.activas())


def test_liberar_posicion_solo_si_esta_bloqueada(entorno) -> None:
    _, _, _, nucleo = entorno

    with pytest.raises(ErrorPosicion) as error:
        nucleo.patio.solicitar_liberacion("P1", "terminal01")

    assert error.value.codigo == "POSICION_NO_BLOQUEADA"


# ---------------------------------------------------------------- parqueo


def _retencion_en_garita(bd: ConexionBd, usuarios: RepositorioUsuarios, nucleo: NucleoLogica):
    """Turno en EnGarita retenido con RT06: el vehículo entra al ramal y toma plaza."""
    naviera = usuarios.con_hash_por_username("naviera01")[0].id
    transportista = usuarios.con_hash_por_username("transp01")[0].id
    with bd.candado:
        bd.conexion.execute("INSERT INTO contenedor (id, descripcion) VALUES ('C01', 'prueba')")
        bd.conexion.execute(
            "INSERT INTO vehiculo (identificador, transportista_id, tara_g) VALUES ('V01', ?, 900)",
            (transportista,),
        )
        bd.conexion.commit()
    RepositorioManifiestos(bd).crear_demo(
        "C01", naviera, transportista, "DEPOSITO", 30000, "2026-09-20T13:30:00.000Z"
    )
    turno_id = nucleo.turnos_repo.crear(1, 1, None, "DEPOSITO", "verde", True, "2026-09-20T13:59Z")
    turno = nucleo.turnos_repo.buscar_por_id(turno_id)
    return nucleo.retenciones_svc.retener(turno, CausaRetencion.RT06, "garita")


def test_aclarar_libera_la_plaza_solo_cuando_el_controlador_confirma(entorno) -> None:
    bd, usuarios, publicador, nucleo = entorno
    retencion = _retencion_en_garita(bd, usuarios, nucleo)
    terminal = usuarios.buscar_por_id(usuarios.con_hash_por_username("terminal01")[0].id)

    nucleo.retenciones_svc.resolver(retencion.id, ResolucionRetencion.ACLARAR, terminal)
    cmd_id, parametros = publicador.ultimo_comando("AgujaLiberar")

    assert parametros == {"plaza": str(retencion.plaza)}
    plaza = nucleo.parqueo_svc.estado()[retencion.plaza - 1]
    assert plaza["turno_id"] is not None and plaza["retencion_resuelta"] is True
    _responder(nucleo, cmd_id, "ACK")
    assert nucleo.parqueo_svc.estado()[retencion.plaza - 1]["turno_id"] is None


def test_liberar_parqueo_manual_tras_nak_y_no_con_retencion_abierta(entorno) -> None:
    bd, usuarios, publicador, nucleo = entorno
    retencion = _retencion_en_garita(bd, usuarios, nucleo)
    terminal = usuarios.buscar_por_id(usuarios.con_hash_por_username("terminal01")[0].id)

    with pytest.raises(ErrorPlazaParqueo) as abierta:
        nucleo.parqueo_svc.liberar_parqueo(retencion.plaza, "terminal01")
    nucleo.retenciones_svc.resolver(retencion.id, ResolucionRetencion.ACLARAR, terminal)
    cmd_automatico, _ = publicador.ultimo_comando("AgujaLiberar")
    _responder(nucleo, cmd_automatico, "NAK", "VEH_SOBRE_AGUJA")
    cmd_manual = nucleo.parqueo_svc.liberar_parqueo(retencion.plaza, "terminal01")
    _responder(nucleo, cmd_manual, "ACK")

    assert abierta.value.codigo == "RETENCION_ABIERTA"
    assert nucleo.parqueo_svc.estado()[retencion.plaza - 1]["turno_id"] is None


# --------------------------------------------------------------- catálogo


@pytest.mark.parametrize(
    ("nombre", "parametros", "codigo"),
    [
        ("BorrarTodo", {}, "COMANDO_DESCONOCIDO"),
        ("PosicionBloquear", {"pos": "P1"}, "COMANDO_CON_RUTA_PROPIA"),
        ("ModoMantenimiento", {}, "PARAMETRO_INVALIDO"),
    ],
)
def test_emitir_rechaza_comandos_fuera_de_regla(entorno, nombre, parametros, codigo) -> None:
    _, _, publicador, nucleo = entorno

    with pytest.raises(ErrorComando) as error:
        nucleo.comandos_svc.emitir(nombre, parametros, "terminal01")

    assert error.value.codigo == codigo
    assert publicador.comandos == []


def test_modo_mantenimiento_viaja_con_su_valor(entorno) -> None:
    _, _, publicador, nucleo = entorno

    nucleo.comandos_svc.emitir("ModoMantenimiento", {"valor": "ACTIVAR"}, "terminal01")

    assert publicador.ultimo_comando("ModoMantenimiento")[1] == {"valor": "ACTIVAR"}
