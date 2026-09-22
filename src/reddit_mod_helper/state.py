"""Estado persistente entre corridas: qué posts ya se evaluaron o describieron.

Usa SQLite (librería estándar de Python, sin dependencias nuevas) en vez de
un archivo plano porque necesitamos poder purgar por fecha de forma atómica
en cada corrida, no solo llevar una lista de IDs.

Alternativa considerada y descartada: guardar solo el "cursor" del último
post visto (el parámetro `before` que soporta la API de Reddit) en vez de
una tabla con historial. Es más liviano en disco, pero más frágil — si un
post se elimina o el orden de `new()` cambia entre llamadas, se pueden
saltar posts sin darse cuenta, y no queda rastro de qué se evaluó. La tabla
con purga es más fácil de razonar y es prácticamente del mismo tamaño en
disco de todas formas (unos IDs cortos por 3 días de posts).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "estado.db"
DIAS_DE_RETENCION = 3

TABLA_POSTS_EVALUADOS = "posts_evaluados"
TABLA_IMAGENES_DESCRITAS = "imagenes_descritas"


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLA_POSTS_EVALUADOS} (
            id TEXT PRIMARY KEY,
            procesado_en TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLA_IMAGENES_DESCRITAS} (
            id TEXT PRIMARY KEY,
            descripcion TEXT NOT NULL,
            procesado_en TEXT NOT NULL
        )
        """
    )
    return conn


def purgar_antiguos(conn: sqlite3.Connection, tabla: str = TABLA_POSTS_EVALUADOS, dias: int = DIAS_DE_RETENCION) -> int:
    """Borra registros con más de `dias` de antigüedad. Devuelve cuántos borró.

    `tabla` solo recibe los nombres definidos arriba (nunca texto externo),
    así que interpolarlo en el SQL es seguro aquí.
    """
    limite = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    cursor = conn.execute(f"DELETE FROM {tabla} WHERE procesado_en < ?", (limite,))  # noqa: S608
    conn.commit()
    return cursor.rowcount


def ya_procesado(conn: sqlite3.Connection, post_id: str) -> bool:
    fila = conn.execute(f"SELECT 1 FROM {TABLA_POSTS_EVALUADOS} WHERE id = ?", (post_id,)).fetchone()
    return fila is not None


def marcar_procesado(conn: sqlite3.Connection, post_id: str) -> None:
    conn.execute(
        f"INSERT OR REPLACE INTO {TABLA_POSTS_EVALUADOS} (id, procesado_en) VALUES (?, ?)",
        (post_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def descripcion_guardada(conn: sqlite3.Connection, post_id: str) -> str | None:
    fila = conn.execute(
        f"SELECT descripcion FROM {TABLA_IMAGENES_DESCRITAS} WHERE id = ?", (post_id,)
    ).fetchone()
    return fila[0] if fila else None


def guardar_descripcion(conn: sqlite3.Connection, post_id: str, descripcion: str) -> None:
    conn.execute(
        f"INSERT OR REPLACE INTO {TABLA_IMAGENES_DESCRITAS} (id, descripcion, procesado_en) VALUES (?, ?, ?)",
        (post_id, descripcion, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
