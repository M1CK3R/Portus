"""Repositorio de usuarios (SPECS §7.1 a §7.3, §17.1). SQL siempre parametrizado (BD-1)."""

import sqlite3

from web.modelos.usuario import Rol, Usuario, rol_de_texto
from web.repositorios.conexion_bd import ConexionBd

COLUMNAS_USUARIO = "id, username, rol, nombre_mostrado, activo"
# Nunca SELECT * (BD-4): la lista de columnas es explícita.


class RepositorioUsuarios:
    """Consultas y altas de la tabla ``usuario``."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def con_hash_por_username(self, username: str) -> tuple[Usuario, str] | None:
        """Devuelve el usuario junto a su hash para verificar la contraseña (S-3)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_USUARIO}, password_hash FROM usuario WHERE username = ?",
                (username,),
            ).fetchone()
        if fila is None:
            return None
        return _usuario_de_fila(fila), str(fila["password_hash"])

    def buscar_por_id(self, id_usuario: int) -> Usuario | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_USUARIO} FROM usuario WHERE id = ?", (id_usuario,)
            ).fetchone()
        return None if fila is None else _usuario_de_fila(fila)

    def listar_por_rol(self, rol: Rol) -> list[Usuario]:
        """Lista los usuarios de un rol (§7.1); el panel A17 lista transportistas."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_USUARIO} FROM usuario WHERE rol = ? ORDER BY id",
                (rol.value,),
            ).fetchall()
        return [_usuario_de_fila(fila) for fila in filas]

    def cambiar_activo(self, username: str, activo: bool) -> None:
        """Habilita o deshabilita un usuario; lo usa la administración y las pruebas."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "UPDATE usuario SET activo = ? WHERE username = ?",
                (1 if activo else 0, username),
            )
            self._bd.conexion.commit()

    def crear(
        self,
        username: str,
        password_hash: str,
        rol: Rol,
        nombre_mostrado: str,
        creado_en: str,
    ) -> bool:
        """Inserta un usuario; devuelve False si el username ya existía."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT OR IGNORE INTO usuario "
                "(username, password_hash, rol, nombre_mostrado, activo, creado_en) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (username, password_hash, rol.value, nombre_mostrado, creado_en),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0


def _usuario_de_fila(fila: sqlite3.Row) -> Usuario:
    """Convierte una fila tipada de la consulta en el modelo del dominio (PY-2)."""
    return Usuario(
        id=int(fila["id"]),
        username=str(fila["username"]),
        rol=rol_de_texto(str(fila["rol"])),
        nombre_mostrado=str(fila["nombre_mostrado"]),
        activo=bool(fila["activo"]),
    )
