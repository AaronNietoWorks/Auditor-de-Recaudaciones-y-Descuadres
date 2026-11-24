"""
database.py
-----------
Persistencia ligera en SQLite (gestor_contratos.db).

* contratos / prestamos : la última cartera cargada. Cada exportación de IPS-Maq+ es la foto
  completa de la cartera, así que una nueva carga sustituye a la anterior. Así la oficina
  abre la app cada día y ve los vencimientos recalculados sin volver a subir nada.
* recaudacion_mensual   : histórico acumulado por mes y establecimiento (clave única mes + bar),
  sin duplicados aunque se suba varias veces el mismo listado.
* seguimiento           : la gestión de cada renovación (Contactado, En negociación, Renovado...)
  y una nota libre. Se conserva entre cargas porque se enlaza por establecimiento + contrato.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent / "gestor_contratos.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contratos (
    bar TEXT NOT NULL, clave_bar TEXT NOT NULL, contrato TEXT, ruta TEXT,
    fecha_alta TEXT, fecha_fin TEXT NOT NULL, prorroga INTEGER, preaviso REAL, maquinas REAL
);
CREATE TABLE IF NOT EXISTS prestamos (
    bar TEXT NOT NULL, clave_bar TEXT NOT NULL, prestamo TEXT, fecha TEXT NOT NULL,
    importe REAL NOT NULL, cuota REAL, n_cuotas REAL, amortizado REAL, pendiente REAL
);
CREATE TABLE IF NOT EXISTS recaudacion_mensual (
    mes TEXT NOT NULL, clave_bar TEXT NOT NULL, bar TEXT NOT NULL,
    recaudacion REAL NOT NULL, liquidacion_bar REAL,
    UNIQUE (mes, clave_bar)
);
CREATE TABLE IF NOT EXISTS seguimiento (
    id_contrato TEXT PRIMARY KEY, gestion TEXT, nota TEXT, actualizado TEXT
);
CREATE TABLE IF NOT EXISTS cargas (
    tabla TEXT PRIMARY KEY, origen TEXT, filas INTEGER, cargado_en TEXT
);
"""

_FECHAS = {"contratos": ["fecha_alta", "fecha_fin"], "prestamos": ["fecha"]}
_COLUMNAS = {
    "contratos": ["bar", "clave_bar", "contrato", "ruta", "fecha_alta", "fecha_fin", "prorroga",
                  "preaviso", "maquinas"],
    "prestamos": ["bar", "clave_bar", "prestamo", "fecha", "importe", "cuota", "n_cuotas",
                  "amortizado", "pendiente"],
}


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


def guardar_cartera(tabla: str, df: pd.DataFrame, origen: str = "",
                    db_path: Path | str = DB_PATH) -> int:
    """Sustituye la cartera de `contratos` o `prestamos` por la recién cargada."""
    init_db(db_path)
    datos = df[_COLUMNAS[tabla]].copy()
    for c in _FECHAS[tabla]:
        datos[c] = pd.to_datetime(datos[c]).dt.strftime("%Y-%m-%d")
    if "prorroga" in datos:
        datos["prorroga"] = datos["prorroga"].astype(int)
    datos = datos.astype(object).where(datos.notna(), None)
    with _conexion(db_path) as conn:
        conn.execute(f"DELETE FROM {tabla}")
        conn.executemany(
            f"INSERT INTO {tabla} ({', '.join(datos.columns)}) VALUES ({', '.join('?' * len(datos.columns))})",
            datos.itertuples(index=False, name=None),
        )
        _registrar_carga(conn, tabla, origen, len(datos))
    return len(datos)


def cargar_cartera(tabla: str, db_path: Path | str = DB_PATH) -> pd.DataFrame:
    init_db(db_path)
    with _conexion(db_path) as conn:
        df = pd.read_sql_query(f"SELECT * FROM {tabla}", conn)
    for c in _FECHAS[tabla]:
        df[c] = pd.to_datetime(df[c])
    for c in ("contrato", "prestamo", "ruta"):
        if c in df:
            df[c] = df[c].fillna("")
    if "prorroga" in df:
        df["prorroga"] = df["prorroga"].fillna(0).astype(bool)
    return df


def guardar_recaudacion(df: pd.DataFrame, origen: str = "", db_path: Path | str = DB_PATH) -> dict:
    """Agrega por mes y establecimiento y hace UPSERT en el histórico."""
    init_db(db_path)
    if df.empty:
        return {"nuevos": 0, "actualizados": 0}
    m = (df.assign(mes=df["fecha"].dt.to_period("M").dt.to_timestamp().dt.strftime("%Y-%m-%d"))
           .groupby(["mes", "clave_bar"], as_index=False)
           .agg(bar=("bar", "first"), recaudacion=("recaudacion", "sum"),
                liquidacion_bar=("liquidacion_bar", lambda s: s.sum(min_count=1))))
    m = m.astype(object).where(m.notna(), None)
    with _conexion(db_path) as conn:
        antes = conn.execute("SELECT COUNT(*) FROM recaudacion_mensual").fetchone()[0]
        conn.executemany(
            """INSERT INTO recaudacion_mensual (mes, clave_bar, bar, recaudacion, liquidacion_bar)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (mes, clave_bar) DO UPDATE SET
                   bar = excluded.bar, recaudacion = excluded.recaudacion,
                   liquidacion_bar = excluded.liquidacion_bar""",
            m[["mes", "clave_bar", "bar", "recaudacion", "liquidacion_bar"]].itertuples(index=False, name=None),
        )
        despues = conn.execute("SELECT COUNT(*) FROM recaudacion_mensual").fetchone()[0]
        _registrar_carga(conn, "recaudacion_mensual", origen, despues)
    return {"nuevos": despues - antes, "actualizados": len(m) - (despues - antes)}


def cargar_recaudacion(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    init_db(db_path)
    with _conexion(db_path) as conn:
        df = pd.read_sql_query("SELECT mes AS fecha, clave_bar, bar, recaudacion, liquidacion_bar "
                               "FROM recaudacion_mensual ORDER BY mes", conn)
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["liquidacion_bar"] = pd.to_numeric(df["liquidacion_bar"], errors="coerce")
    return df


def cargar_seguimiento(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    init_db(db_path)
    with _conexion(db_path) as conn:
        return pd.read_sql_query("SELECT id_contrato, gestion, nota, actualizado FROM seguimiento", conn)


def guardar_seguimiento(filas: list[tuple[str, str, str]], db_path: Path | str = DB_PATH) -> int:
    """filas = [(id_contrato, gestion, nota), ...]"""
    init_db(db_path)
    ahora = datetime.now().isoformat(timespec="seconds")
    with _conexion(db_path) as conn:
        conn.executemany(
            """INSERT INTO seguimiento (id_contrato, gestion, nota, actualizado) VALUES (?, ?, ?, ?)
               ON CONFLICT (id_contrato) DO UPDATE SET gestion = excluded.gestion,
                   nota = excluded.nota, actualizado = excluded.actualizado""",
            [(i, g, n, ahora) for i, g, n in filas],
        )
    return len(filas)


def resumen_db(db_path: Path | str = DB_PATH) -> dict:
    init_db(db_path)
    with _conexion(db_path) as conn:
        cargas = {t: (o, n, f) for t, o, n, f in conn.execute("SELECT * FROM cargas")}
        n_seg = conn.execute("SELECT COUNT(*) FROM seguimiento WHERE gestion != 'Sin gestionar' "
                             "OR (nota IS NOT NULL AND nota != '')").fetchone()[0]
    return {"cargas": cargas, "seguimientos": n_seg}


def vaciar_todo(db_path: Path | str = DB_PATH) -> None:
    init_db(db_path)
    with _conexion(db_path) as conn:
        for t in ("contratos", "prestamos", "recaudacion_mensual", "seguimiento", "cargas"):
            conn.execute(f"DELETE FROM {t}")
