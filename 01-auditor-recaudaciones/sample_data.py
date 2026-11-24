"""
sample_data.py
--------------
Genera un listado FICTICIO con la estructura típica de una exportación de
recaudaciones de IPS-Maq+: 15 bares, 30 máquinas y ~3 meses de histórico semanal.

Incluye a propósito:
  * 3 descuadres críticos (efectivo contado muy distinto de los contadores).
  * 4 desviaciones moderadas (ámbar) para ver el semáforo completo.
  * 2 bares con caída brusca de recaudación en su última visita.

Uso:  python sample_data.py   ->  crea datos_ejemplo_ips.xlsx
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ARCHIVO_SALIDA = Path(__file__).resolve().parent / "datos_ejemplo_ips.xlsx"

BARES = [
    "Bar El Rincón", "Cafetería La Plaza", "Bar Los Arcos", "Mesón El Puerto",
    "Bar La Estación", "Cervecería Central", "Bar Avenida", "Taberna El Olivo",
    "Bar Las Palmeras", "Cafetería Sol", "Bar El Cruce", "Bodega San Juan",
    "Bar La Ribera", "Bar Dos Hermanas", "Café Bar Nuevo",
]
MODELOS = [
    "Fénix Deluxe", "Rueda Dorada", "Triple Siete", "Tesoro Real", "Diamante Azul",
    "Gran Bonanza", "Estrella Plus", "Frutas Locas",
]
RUTAS = ["Ruta 1 - Centro", "Ruta 2 - Norte", "Ruta 3 - Costa"]

BARES_CON_CAIDA = {4: 0.42, 10: 0.55}        # índice de bar -> factor de su última recaudación
DESCUADRES_CRITICOS = [(-46.50, 2, 0), (-23.80, 7, 1), (31.20, 13, 0)]  # (dif €, bar, máquina)
DESCUADRES_MODERADOS = [(-6.40, 1, 1), (8.20, 5, 0), (-11.70, 9, 1), (4.90, 14, 0)]


def generar_datos(semanas: int = 13, semilla: int = 42,
                  fecha_fin: date | None = None) -> pd.DataFrame:
    """Devuelve el DataFrame con las columnas tal y como saldrían del ERP."""
    rng = np.random.default_rng(semilla)
    fecha_fin = fecha_fin or date.today() - timedelta(days=1)
    filas = []
    n_maquina = 0
    for b, bar in enumerate(BARES):
        cod_bar = f"B{b + 1:03d}"
        ruta = RUTAS[b % len(RUTAS)]
        # Cada bar se recauda un día fijo de la semana (lunes a sábado)
        dia_visita = b % 6
        ultima = fecha_fin - timedelta(days=(fecha_fin.weekday() - dia_visita) % 7)
        fechas = [ultima - timedelta(weeks=w) for w in range(semanas)][::-1]
        for m in range(2):
            n_maquina += 1
            cod_maq = f"M{n_maquina:04d}"
            modelo = MODELOS[(b * 2 + m) % len(MODELOS)]
            serie = f"{rng.integers(10, 99)}-{rng.integers(100000, 999999)}"
            base = float(rng.uniform(260, 880))
            for k, f in enumerate(fechas):
                factor = float(np.clip(rng.normal(1, 0.05), 0.90, 1.10))
                teorico = round(base * factor / 0.2) * 0.2          # múltiplos de 20 cént.
                if k == len(fechas) - 1 and b in BARES_CON_CAIDA:
                    teorico = round(base * BARES_CON_CAIDA[b] * (1 - 0.06 * m), 2)
                real = teorico + float(rng.choice([0, 0, 0, 0.10, -0.10, 0.50, -0.50, 1.00, -1.20]))
                filas.append({
                    "Fecha Recaudación": pd.Timestamp(f),
                    "Ruta": ruta,
                    "Establecimiento": f"{cod_bar} - {bar}",
                    "Máquina": f"{cod_maq} - {modelo}",
                    "Nº Serie": serie,
                    "Rec. Contadores": round(teorico, 2),
                    "Efectivo Contado": round(real, 2),
                    "_bar": b, "_maq": m, "_k": k,
                })
    df = pd.DataFrame(filas)

    # Descuadres intencionados (a mitad del periodo, fuera de la última visita)
    for i, (dif, b, m) in enumerate(DESCUADRES_CRITICOS + DESCUADRES_MODERADOS):
        k = 3 + (i * 2) % (semanas - 5)
        sel = (df["_bar"] == b) & (df["_maq"] == m) & (df["_k"] == k)
        df.loc[sel, "Efectivo Contado"] = (df.loc[sel, "Rec. Contadores"] + dif).round(2)

    # Liquidación al bar: 50 % del efectivo tras la tasa semanal estimada (ficticia)
    df["Liquidación Bar"] = ((df["Efectivo Contado"] - 25) * 0.5).clip(lower=0).round(2)
    df["Neto Empresa"] = (df["Efectivo Contado"] - df["Liquidación Bar"]).round(2)
    return (df.drop(columns=["_bar", "_maq", "_k"])
              .sort_values(["Fecha Recaudación", "Establecimiento", "Máquina"])
              .reset_index(drop=True))


def guardar_excel(df: pd.DataFrame, ruta: Path = ARCHIVO_SALIDA) -> Path:
    """Guarda el listado imitando el aspecto de una exportación del ERP."""
    with pd.ExcelWriter(ruta, engine="xlsxwriter", datetime_format="dd/mm/yyyy") as w:
        df.to_excel(w, sheet_name="Recaudaciones", index=False)
        ws = w.sheets["Recaudaciones"]
        eur = w.book.add_format({"num_format": "#,##0.00"})
        ws.set_column(0, 0, 18)
        ws.set_column(1, 1, 16)
        ws.set_column(2, 3, 30)
        ws.set_column(4, 4, 14)
        ws.set_column(5, 8, 16, eur)
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, len(df), len(df.columns) - 1)
    return ruta


if __name__ == "__main__":
    datos = generar_datos()
    salida = guardar_excel(datos)
    print(f"[OK] {salida.name} generado: {len(datos)} filas, "
          f"{datos['Establecimiento'].nunique()} bares, {datos['Máquina'].nunique()} máquinas, "
          f"{datos['Fecha Recaudación'].min():%d/%m/%Y} - {datos['Fecha Recaudación'].max():%d/%m/%Y}")
