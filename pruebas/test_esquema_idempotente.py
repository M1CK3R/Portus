"""Idempotencia del esquema: aplicarlo dos veces (web + puente) no debe fallar.

La migración 003 recrea ``manifiesto`` en cada arranque (CREATE+INSERT+DROP+
RENAME) y siembra ``plaza_parqueo``; si una corrida se interrumpe a mitad
queda un ``manifiesto_etapa5`` huérfano que bloquea el próximo arranque. Esta
prueba simula ese escenario y verifica que el esquema se auto-repara.
"""

import sqlite3

from db import migraciones  # noqa: F401 — asegura que el paquete existe
from herramientas.crear_datos_semilla import crear as crear_datos
from herramientas.crear_operacion_demo import OpcionesDemo
from herramientas.crear_operacion_demo import crear as crear_operacion
from web.modelos.usuario import Rol
from web.repositorios.conexion_bd import RUTA_ESQUEMA_POR_OMISION, ConexionBd
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.tiempo import marca_utc


def test_esquema_aplicado_dos_veces_no_falla(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ruta = tmp_path / "idem.db"
    esquema = (RUTA_ESQUEMA_POR_OMISION).read_text(encoding="utf-8")

    # 1. Aplicación limpia (como el primer arranque de la web).
    con = sqlite3.connect(ruta)
    con.executescript(esquema)
    # 2. Simula una corrida interrumpida: deja un manifiesto_etapa5 huérfano.
    con.execute("CREATE TABLE manifiesto_etapa5 (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()

    # 3. Segundo arranque (el puente): debe limpiar el huérfano y no fallar.
    con = sqlite3.connect(ruta)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(esquema)  # no lanza IntegrityError ni OperationalError
    assert con.execute("SELECT name FROM sqlite_master WHERE name='manifiesto'").fetchone()
    assert (
        con.execute("SELECT name FROM sqlite_master WHERE name='manifiesto_etapa5'").fetchone()
        is None
    )
    # plaza_parqueo sigue con sus 3 plazas (INSERT OR IGNORE idempotente).
    assert con.execute("SELECT COUNT(*) FROM plaza_parqueo").fetchone()[0] == 3
    con.close()


def test_reaplica_esquema_con_levante_y_cita_no_rompe_fk(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Reproducir el arranque de la web sobre una BD ya sembrada (Etapa 6).

    La semilla deja ``solicitud_levante`` y ``cita`` referenciando a
    ``manifiesto``; al reabrir la BD la web vuelve a aplicar el esquema, que
    recrea ``manifiesto`` (DROP+RENAME). Con FK ON eso rompía; ahora la
    migración se aplica con FK OFF y se reactiva para el runtime.
    """
    ruta = str(tmp_path / "reaplica.db")
    bd = ConexionBd(ruta, RUTA_ESQUEMA_POR_OMISION)
    usuarios = RepositorioUsuarios(bd)
    usuarios.crear("transportista01", "x", Rol.TRANSPORTISTA, "T1", marca_utc())
    usuarios.crear("naviera01", "x", Rol.NAVIERA, "N1", marca_utc())
    bd.cerrar()
    crear_datos(ruta)
    crear_operacion(
        ruta, OpcionesDemo(con_cita=True)
    )  # crea manifiesto + levante + cita (hijas de manifiesto)

    # Reabrir la BD como hace `python -m web` al arrancar: vuelve a aplicar el
    # esquema. Antes del arreglo esto levantaba FOREIGN KEY constraint failed.
    bd2 = ConexionBd(ruta, RUTA_ESQUEMA_POR_OMISION)
    with bd2.candado:
        filas = bd2.conexion.execute(
            "SELECT (SELECT COUNT(*) FROM manifiesto), "
            "(SELECT COUNT(*) FROM solicitud_levante), "
            "(SELECT COUNT(*) FROM cita)"
        ).fetchone()
        fk = bd2.conexion.execute("PRAGMA foreign_keys").fetchone()[0]
    bd2.cerrar()
    # 2 manifiestos (C01 operativo + C02 para el AGENTE) + levante + cita intactos
    assert tuple(int(x) for x in filas) == (2, 1, 1)
    assert fk == 1  # FK reactivada para el runtime (BD-3)
