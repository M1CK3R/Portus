"""Utilidades de prueba del bot de mensajería (T-3, T-5; Etapa 10).

``crear_bot`` arma el servicio del bot sobre la BD temporal de
``crear_logica`` (misma base que la lógica del turno, reloj falso) con dos
transportistas y sus vehículos. ``vincular`` hace el ciclo real: TERMINAL
genera el código y el chat lo consume con ``/vincular``. ``CanalFalso``
captura los envíos y puede simular 429, caída de red o chat bloqueado.
"""

from dataclasses import dataclass, field
from pathlib import Path

from mensajeria.conversaciones import LimitadorVinculacion, RegistroConversaciones
from mensajeria.flujo_cita import FlujoCita
from mensajeria.modelos import (
    ErrorCanal,
    MensajeEntrante,
    PulsacionBoton,
    Respuesta,
)
from mensajeria.servicio_bot import DependenciasBot, ServicioBot
from pruebas.utilidades_logica import CREADO_EN, TARA_G, LogicaPrueba, crear_logica
from web.modelos.usuario import Rol
from web.repositorios.repositorio_citas import RepositorioCitas
from web.repositorios.repositorio_consultas_transportista import (
    RepositorioConsultasTransportista,
)
from web.repositorios.repositorio_notificaciones import RepositorioNotificaciones
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos
from web.repositorios.repositorio_vinculos import RepositorioVinculos
from web.servicios.servicio_vinculacion import ServicioVinculacion

NOMBRE_TERMINAL = "Terminal de Prueba"
CHAT_1 = 1001
CHAT_2 = 2002
PESO_G = 20_000


@dataclass
class BotPrueba:
    """Bot con acceso directo a sus piezas para preparar y verificar escenarios."""

    logica: LogicaPrueba
    bot: ServicioBot
    vinculacion: ServicioVinculacion
    vinculos: RepositorioVinculos
    citas: RepositorioCitas
    notificaciones: RepositorioNotificaciones
    conversaciones: RegistroConversaciones
    transportista_1: int
    transportista_2: int
    naviera: int

    def escribir(self, id_chat: int, texto: str) -> Respuesta:
        return self.bot.atender_mensaje(MensajeEntrante(id_chat=id_chat, texto=texto))

    def pulsar(self, id_chat: int, dato: str) -> Respuesta:
        return self.bot.atender_pulsacion(PulsacionBoton(id_chat=id_chat, dato=dato))

    def vincular(self, id_chat: int, transportista_id: int) -> Respuesta:
        codigo = self.vinculacion.generar(transportista_id)
        assert codigo is not None
        return self.escribir(id_chat, f"/vincular {codigo.codigo}")

    def manifiesto(self, contenedor: str, transportista_id: int, tipo_op: str = "DEPOSITO") -> int:
        """Manifiesto declarado, sin levante ni turno; crea el contenedor si falta."""
        with self.logica.bd.candado:
            self.logica.bd.conexion.execute(
                "INSERT OR IGNORE INTO contenedor (id, descripcion) VALUES (?, 'prueba')",
                (contenedor,),
            )
            self.logica.bd.conexion.commit()
        self.logica.manifiestos.crear_demo(
            contenedor, self.naviera, transportista_id, tipo_op, PESO_G, CREADO_EN
        )
        return self.logica.manifiestos.vigentes_de_transportista(transportista_id)[-1].id

    def manifiesto_con_levante(
        self, contenedor: str, transportista_id: int, canal: str = "verde"
    ) -> int:
        """Manifiesto sin turno, con levante otorgado y sin cita (citable, §11.1)."""
        manifiesto_id = self.manifiesto(contenedor, transportista_id)
        self.logica.manifiestos.marcar_documental(manifiesto_id, "levante_otorgado")
        self.logica.levantes.crear(manifiesto_id, "otorgada", canal)
        return manifiesto_id


def crear_bot(tmp_path: Path) -> BotPrueba:
    logica = crear_logica(tmp_path)
    bd = logica.bd
    usuarios = RepositorioUsuarios(bd)
    transportista_1 = _usuario(usuarios, "transportista01", "Transportes Uno", Rol.TRANSPORTISTA)
    transportista_2 = _usuario(usuarios, "transportista02", "Transportes Dos", Rol.TRANSPORTISTA)
    naviera = _usuario(usuarios, "naviera01", "Naviera A", Rol.NAVIERA)
    vehiculos = RepositorioVehiculos(bd)
    vehiculos.crear("V01", transportista_1, TARA_G)
    vehiculos.crear("V03", transportista_2, TARA_G)
    vinculos = RepositorioVinculos(bd)
    citas = RepositorioCitas(bd)
    notificaciones = RepositorioNotificaciones(bd)
    reloj = logica.reloj
    conversaciones = RegistroConversaciones(reloj)
    vinculacion = ServicioVinculacion(vinculos, usuarios, reloj)
    bot = ServicioBot(
        DependenciasBot(
            vinculacion=vinculacion,
            vinculos=vinculos,
            usuarios=usuarios,
            citas=citas,
            consultas=RepositorioConsultasTransportista(bd),
            flujo_cita=FlujoCita(citas, notificaciones, conversaciones, reloj),
            conversaciones=conversaciones,
            limitador=LimitadorVinculacion(reloj),
            nombre_terminal=NOMBRE_TERMINAL,
            fabrica_instante=reloj,
        )
    )
    return BotPrueba(
        logica=logica,
        bot=bot,
        vinculacion=vinculacion,
        vinculos=vinculos,
        citas=citas,
        notificaciones=notificaciones,
        conversaciones=conversaciones,
        transportista_1=transportista_1,
        transportista_2=transportista_2,
        naviera=naviera,
    )


@dataclass
class CanalFalso:
    """Canal de prueba: registra (id_chat, texto) y lanza los errores programados."""

    enviados: list[tuple[int, str]] = field(default_factory=list)
    errores: list[ErrorCanal] = field(default_factory=list)

    async def enviar(self, id_chat: int, texto: str) -> None:
        if self.errores:
            raise self.errores.pop(0)
        self.enviados.append((id_chat, texto))


@dataclass
class TiempoFalso:
    """Reloj monotónico y ``dormir`` que avanzan sin esperar de verdad (T-3)."""

    ahora_s: float = 1000.0
    esperas: list[float] = field(default_factory=list)

    def reloj(self) -> float:
        return self.ahora_s

    async def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)
        self.ahora_s += segundos


def _usuario(usuarios: RepositorioUsuarios, username: str, nombre: str, rol: Rol) -> int:
    usuarios.crear(username, "x", rol, nombre, CREADO_EN)
    encontrado = usuarios.con_hash_por_username(username)
    assert encontrado is not None
    return encontrado[0].id
