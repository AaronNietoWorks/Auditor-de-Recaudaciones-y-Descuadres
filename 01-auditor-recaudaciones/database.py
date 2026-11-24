"""
database.py
-----------
Persistencia ligera en SQLite para el histórico de recaudaciones.

La tabla `recaudaciones` usa como clave única (fecha, bar, maquina), de modo que
volver a subir el mismo listado de IPS-Maq+ no duplica registros: las filas ya
existentes se actualizan con los últimos valores validados.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent / "auditoria.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recaudaciones (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha            TEXT    NOT NULL,          -- ISO yyyy-mm-dd
    bar              TEXT    NOT NULL,
    maquina          TEXT    NOT NULL,
    teorico          REAL    NOT NULL,          -- Recaudación según contadores
    real             REAL    NOT NULL,          -- Efectivo contado
    liquidacion_bar  REAL,                      -- Parte liquidada al bar (opcional)
    diferencia       REAL    NOT NULL,          -- real - teorico
    estado           TEXT    NOT NULL,          -- OK / Revisar / Crítico
    origen           TEXT,                      -- Nombre del archivo de origen
    cargado_en       TEXT    NOT NULL,
    UNIQUE (fecha, bar, maquina)
);
CREATE INDEX IF NOT EXISTS idx_rec_bar_maq ON recaudaciones (bar, maquina, fecha);
"""

COLUMNAS = [
    "fecha", "bar", "maquina", "teorico", "real",
    "liquidacion_bar", "diferencia", "estado", "origen",
]


@contextmanager
def _conexion(db_path: Path | str = DB_PATH):
    conn = sqlite3.connect(str(db_path))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | str = DB_PATH) -> None:
    """Crea la base de datos y la tabla si no existen."""
    with _conexion(db_path) as conn:
        conn.executescript(_SCHEMA)


def guardar_registros(df: pd.DataFrame, origen: str = "",
                      db_path: Path | str = DB_PATH) -> dict:
    """
    Inserta o actualiza (UPSERT) los registros validados.

    Devuelve un resumen {'nuevos': n, 'actualizados': m}.
    """
    init_db(db_path)
    if df.empty:
        return {"nuevos": 0, "actualizados": 0}

    datos = df.copy()
    datos["fecha"] = pd.to_datetime(datos["fecha"]).dt.strftime("%Y-%m-%d")
    datos["origen"] = origen
    if "liquidacion_bar" not in datos:
        datos["liquidacion_bar"] = None
    ahora = datetime.now().isoformat(timespec="seconds")

    filas = [
        (
            r.fecha, str(r.bar), str(r.maquina), float(r.teorico), float(r.real),
            None if pd.isna(r.liquidacion_bar) else float(r.liquidacion_bar),
            float(r.diferencia), str(r.estado), r.origen, ahora,
        )
        for r in datos[COLUMNAS].itertuples(index=False)
    ]

    with _conexion(db_path) as conn:
        antes = conn.execute("SELECT COUNT(*) FROM recaudaciones").fetchone()[0]
        conn.executemany(
            """
            INSERT INTO recaudaciones
                (fecha, bar, maquina, teorico, real, liquidacion_bar,
                 diferencia, estado, origen, cargado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (fecha, bar, maquina) DO UPDATE SET
                teorico         = excluded.teorico,
                real            = excluded.real,
                liquidacion_bar = excluded.liquidacion_bar,
                diferencia      = excluded.diferencia,
                estado          = excluded.estado,
                origen          = excluded.origen,
                cargado_en      = excluded.cargado_en
            """,
            filas,
        )
        despues = conn.execute("SELECT COUNT(*) FROM recaudaciones").fetchone()[0]

    nuevos = despues - antes
    return {"nuevos": nuevos, "actualizados": len(filas) - nuevos}


def cargar_historico(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    """Devuelve todo el histórico ordenado por fecha."""
    init_db(db_path)
    with _conexion(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT fecha, bar, maquina, teorico, real, liquidacion_bar, "
            "diferencia, estado, origen FROM recaudaciones ORDER BY fecha, bar, maquina",
            conn,
        )
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def resumen_db(db_path: Path | str = DB_PATH) -> dict:
    """Pequeño resumen del contenido para la barra lateral."""
    init_db(db_path)
    with _conexion(db_path) as conn:
        n, fmin, fmax, bares, maqs = conn.execute(
            "SELECT COUNT(*), MIN(fecha), MAX(fecha), COUNT(DISTINCT bar), "
            "COUNT(DISTINCT bar || '|' || maquina) FROM recaudaciones"
        ).fetchone()
    return {"registros": n, "desde": fmin, "hasta": fmax,
            "bares": bares, "maquinas": maqs}


def vaciar_historico(db_path: Path | str = DB_PATH) -> None:
    """Elimina todos los registros (no borra el archivo)."""
    init_db(db_path)
    with _conexion(db_path) as conn:
        conn.execute("DELETE FROM recaudaciones")
