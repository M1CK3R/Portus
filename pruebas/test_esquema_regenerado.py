"""BD-2: ``db/esquema.sql`` es exactamente la concatenación de ``db/migraciones/``."""

from herramientas.regenerar_esquema import RUTA_ESQUEMA, generar


def test_esquema_versionado_coincide_con_las_migraciones() -> None:
    versionado = RUTA_ESQUEMA.read_bytes().decode("utf-8").replace("\r\n", "\n")

    assert versionado == generar(), "regenere con: python -m herramientas.regenerar_esquema"
