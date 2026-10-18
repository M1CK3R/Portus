"""Consultas del transportista por el canal de mensajería (SPECS §15.2, §7.4; Etapa 10).

Cada método recibe el ``transportista_id`` ligado al chat y lo aplica **en el
SQL** (CODESTYLE PY-3, S-2): un contenedor que no es suyo no se distingue de
uno inexistente, así el bot nunca revela carga ajena (§15.2 reglas).
"""

from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd


@dataclass(frozen=True)
class EstadoContenedor:
    """Lo que ``/estado CONTENEDOR`` muestra de un contenedor propio (§15.2)."""

    contenedor_id: str
    tipo_op: str
    estado_documental: str
    estado_operativo: str
    estado_levante: str | None
    canal: str | None
    posicion: str | None
    nivel: int | None
    ingreso_en: str | None
    estado_turno: str | None


@dataclass(frozen=True)
class TurnoActivo:
    """Fila de ``/misturnos``: turno no cerrado ni anulado del transportista (§15.2)."""

    id: int
    vehiculo: str
    contenedor_id: str
    tipo_op: str
    estado: str
    plaza: int | None


class RepositorioConsultasTransportista:
    """Lecturas filtradas por propietario para el bot (§7.4 fila TRANSPORTISTA)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def estado_contenedor(
        self, transportista_id: int, contenedor_id: str
    ) -> EstadoContenedor | None:
        """Estado del contenedor si su manifiesto **más reciente** es del transportista.

        Tomar el último manifiesto evita que un transportista que ya entregó
        el contenedor siga viendo su estado cuando otra operación lo usa.
        """
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT manifiesto.contenedor_id, manifiesto.tipo_op, "
                "manifiesto.estado_documental, manifiesto.estado_operativo, "
                "solicitud_levante.estado, solicitud_levante.canal, "
                "inventario.posicion, inventario.nivel, inventario.ingreso_en, "
                "(SELECT turno.estado FROM turno WHERE turno.manifiesto_id = manifiesto.id "
                "AND turno.estado NOT IN ('Cerrado', 'Anulado') "
                "ORDER BY turno.id DESC LIMIT 1) "
                "FROM manifiesto "
                "LEFT JOIN solicitud_levante ON solicitud_levante.manifiesto_id = manifiesto.id "
                "LEFT JOIN inventario ON inventario.contenedor_id = manifiesto.contenedor_id "
                "WHERE manifiesto.transportista_id = ? "
                "AND manifiesto.id = (SELECT MAX(ultimo.id) FROM manifiesto AS ultimo "
                "WHERE ultimo.contenedor_id = ? COLLATE NOCASE)",
                (transportista_id, contenedor_id),
            ).fetchone()
        if fila is None:
            return None
        return EstadoContenedor(
            contenedor_id=str(fila[0]),
            tipo_op=str(fila[1]),
            estado_documental=str(fila[2]),
            estado_operativo=str(fila[3]),
            estado_levante=None if fila[4] is None else str(fila[4]),
            canal=None if fila[5] is None else str(fila[5]),
            posicion=None if fila[6] is None else str(fila[6]),
            nivel=None if fila[7] is None else int(fila[7]),
            ingreso_en=None if fila[8] is None else str(fila[8]),
            estado_turno=None if fila[9] is None else str(fila[9]),
        )

    def turnos_activos(self, transportista_id: int) -> list[TurnoActivo]:
        """Turnos en curso de la carga del transportista, con la plaza si está retenido."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT turno.id, vehiculo.identificador, manifiesto.contenedor_id, "
                "turno.tipo_op, turno.estado, "
                "(SELECT retencion.plaza FROM retencion WHERE retencion.turno_id = turno.id "
                "AND retencion.estado = 'abierta' ORDER BY retencion.id DESC LIMIT 1) "
                "FROM turno JOIN manifiesto ON manifiesto.id = turno.manifiesto_id "
                "JOIN vehiculo ON vehiculo.id = turno.vehiculo_id "
                "WHERE manifiesto.transportista_id = ? "
                "AND turno.estado NOT IN ('Cerrado', 'Anulado') "
                "ORDER BY turno.id",
                (transportista_id,),
            ).fetchall()
        return [
            TurnoActivo(
                id=int(fila[0]),
                vehiculo=str(fila[1]),
                contenedor_id=str(fila[2]),
                tipo_op=str(fila[3]),
                estado=str(fila[4]),
                plaza=None if fila[5] is None else int(fila[5]),
            )
            for fila in filas
        ]
