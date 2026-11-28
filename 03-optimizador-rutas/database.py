"""
database.py
-----------
Persistencia ligera en SQLite (optimizador_rutas.db).

* parque      : el último parque de máquinas / establecimientos cargado. Cada exportación de IPS-Maq+ es la
                foto completa, así que una nueva carga sustituye a la anterior.
* averias     : histórico acumulado de avisos técnicos (clave única por fecha + máquina + bar + tipo +
                descripción), sin duplicados aunque se suba varias veces el mismo listado. Si un aviso
                que estaba abierto llega cerrado en una carga posterior, se actualiza.
* ubicaciones : coordenadas corregidas a mano para cada bar. Se conservan entre cargas porque se enlazan
                por el nombre normalizado del establecimiento.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent / "optimizador_rutas.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS parque (
    bar TEXT NOT NULL, clave_bar TEXT NOT NULL, poblacion TEXT, direccion TEXT, lat REAL, lon REAL,
    ruta TEXT, orden REAL, maquina TEXT, modelo TEXT, ultima_visita TEXT, frecuencia REAL, rec_media REAL
);
CREATE TABLE IF NOT EXISTS averias (
    id TEXT PRIMARY KEY, fecha TEXT NOT NULL, maquina TEXT, modelo TEXT, bar TEXT, clave_bar TEXT,
    tipo TEXT, descripcion TEXT, fecha_resolucion TEXT, estado TEXT, abierta INTEGER, coste REAL, tecnico TEXT
);
CREATE TABLE IF NOT EXISTS ubicaciones (
    clave_bar TEXT PRIMARY KEY, bar TEXT, lat REAL NOT NULL, lon REAL NOT NULL, actualizado TEXT
);
CREATE TABLE IF NOT EXISTS cargas (
    tabla TEXT PRIMARY KEY, origen TEXT, filas INTEGER, cargado_en TEXT
);
"""

_COL_PARQUE = ["bar", "clave_bar", "poblacion", "direccion", "lat", "lon", "ruta", "orden", "maquina", "modelo",
               "ultima_visita", "frecuencia", "rec_media"]
_COL_AVERIAS = ["id", "fecha", "maquina", "modelo", "bar", "clave_bar", "tipo", "descripcion", "fecha_resolucion",
                "estado", "abierta", "coste", "tecnico"]


@contextmanager
def _conexion(db_path: Path | str = DB_PATH):
    conn = sqlite3.connect(str(db_path))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | str = DB_PATH) -> None:
    with _conexion(db_path) as conn:
        conn.executescript(_SCHEMA)


def _registrar_carga(conn, tabla: str, origen: str, filas: int) -> None:
    conn.execute("INSERT OR REPLACE INTO cargas VALUES (?, ?, ?, ?)",
                 (tabla, origen, filas, datetime.now().isoformat(timespec="seconds")))


def _a_sql(df: pd.DataFrame, columnas: list[str], fechas: list[str]) -> pd.DataFrame:
    datos = df[columnas].copy()
    for c in fechas:
        datos[c] = pd.to_datetime(datos[c]).dt.strftime("%Y-%m-%d")
    return datos.astype(object).where(datos.notna(), None)


def guardar_parque(df: pd.DataFrame, origen: str = "", db_path: Path | str = DB_PATH) -> int:
    init_db(db_path)
    datos = _a_sql(df, _COL_PARQUE, ["ultima_visita"])
    with _conexion(db_path) as conn:
        conn.execute("DELETE FROM parque")
        conn.executemany(f"INSERT INTO parque ({', '.join(_COL_PARQUE)}) VALUES ({', '.join('?' * len(_COL_PARQUE))})",
                         datos.itertuples(index=False, name=None))
        _registrar_carga(conn, "parque", origen, len(datos))
    return len(datos)


def cargar_parque(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    init_db(db_path)
    with _conexion(db_path) as conn:
        df = pd.read_sql_query("SELECT * FROM parque", conn)
    df["ultima_visita"] = pd.to_datetime(df["ultima_visita"])
    for c in ("poblacion", "direccion", "ruta", "maquina", "modelo"):
        df[c] = df[c].fillna("")
    for c in ("lat", "lon", "orden", "frecuencia", "rec_media"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def guardar_averias(df: pd.DataFrame, origen: str = "", db_path: Path | str = DB_PATH) -> dict:
    """UPSERT por id: añade avisos nuevos y actualiza los existentes (p. ej. una avería que se ha cerrado)."""
    init_db(db_path)
    datos = _a_sql(df.assign(abierta=df["abierta"].astype(int)), _COL_AVERIAS, ["fecha", "fecha_resolucion"])
    with _conexion(db_path) as conn:
        antes = conn.execute("SELECT COUNT(*) FROM averias").fetchone()[0]
        actualiza = ", ".join(f"{c} = excluded.{c}" for c in _COL_AVERIAS if c != "id")
        conn.executemany(
            f"INSERT INTO averias ({', '.join(_COL_AVERIAS)}) VALUES ({', '.join('?' * len(_COL_AVERIAS))}) "
            f"ON CONFLICT (id) DO UPDATE SET {actualiza}",
            datos.itertuples(index=False, name=None))
        despues = conn.execute("SELECT COUNT(*) FROM averias").fetchone()[0]
        _registrar_carga(conn, "averias", origen, despues)
    return {"nuevos": despues - antes, "actualizados": len(datos) - (despues - antes)}


def cargar_averias(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    init_db(db_path)
    with _conexion(db_path) as conn:
        df = pd.read_sql_query("SELECT * FROM averias ORDER BY fecha", conn)
    for c in ("fecha", "fecha_resolucion"):
        df[c] = pd.to_datetime(df[c])
    for c in ("maquina", "modelo", "bar", "clave_bar", "tipo", "descripcion", "estado", "tecnico"):
        df[c] = df[c].fillna("")
    df["abierta"] = df["abierta"].fillna(0).astype(bool)
    df["coste"] = pd.to_numeric(df["coste"], errors="coerce")
    return df


def cargar_ubicaciones(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    init_db(db_path)
    with _conexion(db_path) as conn:
        return pd.read_sql_query("SELECT clave_bar, bar, lat, lon, actualizado FROM ubicaciones", conn)


def guardar_ubicaciones(filas: list[tuple[str, str, float, float]], db_path: Path | str = DB_PATH) -> int:
    """filas = [(clave_bar, bar, lat, lon), ...]"""
    init_db(db_path)
    ahora = datetime.now().isoformat(timespec="seconds")
    with _conexion(db_path) as conn:
        conn.executemany(
            """INSERT INTO ubicaciones (clave_bar, bar, lat, lon, actualizado) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (clave_bar) DO UPDATE SET bar = excluded.bar, lat = excluded.lat, lon = excluded.lon,
                   actualizado = excluded.actualizado""",
            [(c, b, la, lo, ahora) for c, b, la, lo in filas])
    return len(filas)


def borrar_ubicaciones(claves: list[str], db_path: Path | str = DB_PATH) -> None:
    init_db(db_path)
    with _conexion(db_path) as conn:
        conn.executemany("DELETE FROM ubicaciones WHERE clave_bar = ?", [(c,) for c in claves])


def resumen_db(db_path: Path | str = DB_PATH) -> dict:
    init_db(db_path)
    with _conexion(db_path) as conn:
        cargas = {t: (o, n, f) for t, o, n, f in conn.execute("SELECT * FROM cargas")}
        n_ubi = conn.execute("SELECT COUNT(*) FROM ubicaciones").fetchone()[0]
    return {"cargas": cargas, "ubicaciones": n_ubi}


def vaciar_todo(db_path: Path | str = DB_PATH) -> None:
    init_db(db_path)
    with _conexion(db_path) as conn:
        for t in ("parque", "averias", "ubicaciones", "cargas"):
            conn.execute(f"DELETE FROM {t}")
