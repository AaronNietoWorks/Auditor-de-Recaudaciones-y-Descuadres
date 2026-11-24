"""
sample_data.py
--------------
Genera un archivo FICTICIO con la estructura típica de tres listados de IPS-Maq+:

  * Contratos          -> 25 establecimientos con su contrato de instalación.
  * Prestamos          -> 12 préstamos / anticipos concedidos a hosteleros.
  * Recaudacion_Mensual -> 12 meses de recaudación por establecimiento (opcional).

Incluye a propósito (siempre respecto a la fecha de hoy):
  * 2 contratos vencidos sin prórroga y 2 con prórroga automática ya vencidos.
  * 3 contratos que vencen en <= 30 días, 3 entre 31 y 60 y 2 entre 61 y 90.
  * 3 préstamos con semanas sin descontar (1 de ellos crítico).
  * 3 préstamos cuyo contrato termina antes de terminar de amortizarse.
  * 1 préstamo ya amortizado.
  * 1 bar con 3 máquinas (por encima del máximo de 2 tipo B en hostelería valenciana).

Uso:  python sample_data.py   ->  crea datos_ejemplo_contratos.xlsx
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ARCHIVO_SALIDA = Path(__file__).resolve().parent / "datos_ejemplo_contratos.xlsx"

BARES = [
    "Bar El Rincón", "Cafetería La Plaza", "Bar Los Arcos", "Mesón El Puerto",
    "Bar La Estación", "Cervecería Central", "Bar Avenida", "Taberna El Olivo",
    "Bar Las Palmeras", "Cafetería Sol", "Bar El Cruce", "Bodega San Juan",
    "Bar La Ribera", "Bar Dos Hermanas", "Café Bar Nuevo", "Bar El Molino",
    "Cervecería La Fuente", "Bar Casa Paco", "Mesón La Encina", "Bar Los Pinos",
    "Cafetería Atlántico", "Bar El Faro", "Taberna La Parra", "Bar Miramar",
    "Bar La Glorieta",
]
RUTAS = ["Ruta 1 - Centro", "Ruta 2 - Norte", "Ruta 3 - Costa"]

# Días que faltan hasta el vencimiento ORIGINAL del contrato (negativo = ya vencido)
VENCIMIENTOS = {
    3: -12, 17: -40,                     # vencidos sin prórroga
    0: 9, 8: 21, 14: 28,                 # <= 30 días
    5: 38, 11: 52, 20: 57,               # 31-60 días
    2: 66, 22: 84,                       # 61-90 días
}
# Contratos con prórroga automática anual ya vencidos en origen: (días desde el vencimiento)
PRORROGADOS = {6: 345, 12: 200}          # 6 -> el nuevo vencimiento cae en ~20 días
# Vencimientos fijos (días) sin prórroga para que el escenario de préstamos sea reproducible
FIN_FIJO = {4: 1500, 9: 900, 13: 700, 15: 1200, 19: 1000, 21: 400, 24: 1400}

# Préstamos (se descuentan de la recaudación SEMANAL de la máquina):
# índice de bar -> (importe, nº de cuotas semanales, semanas desde la concesión, semanas sin descontar)
PRESTAMOS = {
    1:  (6000, 156, 60, 0),
    3:  (4500, 130, 113, 0),             # contrato vencido con saldo pendiente -> crítico
    4:  (9000, 208, 87, 3),              # 3 semanas sin descontar -> riesgo
    8:  (12000, 208, 78, 0),             # contrato vence en 21 días con mucho saldo
    9:  (3000, 104, 39, 0),
    11: (15000, 260, 95, 0),             # contrato vence en 52 días
    13: (7200, 156, 130, 0),
    15: (5000, 173, 69, 2),              # 2 semanas sin descontar -> riesgo
    19: (8000, 173, 104, 9),             # 9 semanas sin descontar -> crítico
    21: (10000, 260, 48, 0),             # contrato vence en ~13 meses, quedan ~4 años de cuotas
    23: (3600, 104, 108, 0),             # ya amortizado
    24: (6000, 208, 26, 0),
}


def _sumar_meses(f: date, meses: int) -> date:
    return (pd.Timestamp(f) + pd.DateOffset(months=meses)).date()


def generar_datos(semilla: int = 7, hoy: date | None = None) -> dict[str, pd.DataFrame]:
    """Devuelve {'Contratos': df, 'Prestamos': df, 'Recaudacion_Mensual': df}."""
    rng = np.random.default_rng(semilla)
    hoy = hoy or date.today()

    # ------------------------------------------------------------------ Contratos
    contratos = []
    for b, nombre in enumerate(BARES):
        cod = f"B{b + 1:03d}"
        duracion = 60                     # contratos de instalación a 5 años
        prorroga = b in PRORROGADOS or b % 4 == 1
        if b in VENCIMIENTOS:
            fin = hoy + timedelta(days=VENCIMIENTOS[b])
            prorroga = False
        elif b in PRORROGADOS:
            fin = hoy - timedelta(days=PRORROGADOS[b])
        elif b in FIN_FIJO:
            fin = hoy + timedelta(days=FIN_FIJO[b])
            prorroga = False
        else:
            fin = hoy + timedelta(days=int(rng.integers(120, 1500)))
        inicio = _sumar_meses(fin, -duracion)
        contratos.append({
            "Cód. Contrato": f"CT-{2000 + b * 7}",
            "Establecimiento": f"{cod} - {nombre}",
            "Ruta": RUTAS[b % len(RUTAS)],
            "Fecha Alta": pd.Timestamp(inicio),
            "Fecha Vencimiento": pd.Timestamp(fin),
            "Duración (meses)": duracion,
            "Prórroga Automática": "Sí" if prorroga else "No",
            "Preaviso (días)": int(rng.choice([30, 60, 90])) if prorroga else None,
            "Nº Máquinas": 3 if b == 10 else int(rng.choice([1, 2, 2])),   # B011 supera el máximo de 2
            "% Reparto Bar": 50,
        })
    df_contratos = pd.DataFrame(contratos)

    # ------------------------------------------------------------------ Préstamos
    prestamos = []
    for b, (importe, n_cuotas, semanas, atraso) in PRESTAMOS.items():
        cuota = round(importe / n_cuotas, 2)
        concesion = hoy - timedelta(weeks=semanas, days=int(rng.integers(0, 6)))
        devengadas = min(semanas, n_cuotas)
        amortizado = round(min(importe, max(0.0, (devengadas - atraso) * cuota)), 2)
        if devengadas >= n_cuotas and atraso == 0:
            amortizado = float(importe)
        prestamos.append({
            "Nº Préstamo": f"PR-{300 + b}",
            "Establecimiento": f"B{b + 1:03d} - {BARES[b]}",
            "Fecha Concesión": pd.Timestamp(concesion),
            "Importe Concedido": float(importe),
            "Cuota Semanal": cuota,
            "Nº Cuotas (semanas)": n_cuotas,
            "Importe Amortizado": amortizado,
            "Saldo Pendiente": round(importe - amortizado, 2),
        })
    df_prestamos = pd.DataFrame(prestamos)

    # ------------------------------------------------------------------ Recaudación mensual
    meses = [pd.Timestamp(_sumar_meses(hoy.replace(day=1), -k)) for k in range(12, 0, -1)]
    rec = []
    for b, nombre in enumerate(BARES):
        base = float(rng.uniform(900, 4200))
        for m in meses:
            bruto = round(base * float(np.clip(rng.normal(1, 0.08), 0.75, 1.25)), 2)
            rec.append({
                "Mes": m,
                "Establecimiento": f"B{b + 1:03d} - {nombre}",
                "Recaudación Bruta": bruto,
                "Liquidación Bar": round(bruto * 0.5, 2),
            })
    df_rec = pd.DataFrame(rec)

    return {"Contratos": df_contratos, "Prestamos": df_prestamos, "Recaudacion_Mensual": df_rec}


def guardar_excel(datos: dict[str, pd.DataFrame], ruta: Path = ARCHIVO_SALIDA) -> Path:
    """Guarda las tres hojas imitando el aspecto de una exportación del ERP."""
    with pd.ExcelWriter(ruta, engine="xlsxwriter", datetime_format="dd/mm/yyyy") as w:
        eur = w.book.add_format({"num_format": "#,##0.00"})
        for hoja, df in datos.items():
            df.to_excel(w, sheet_name=hoja, index=False)
            ws = w.sheets[hoja]
            for j, col in enumerate(df.columns):
                ancho = max(len(str(col)), int(df[col].astype(str).str.len().max())) + 2
                fmt = eur if pd.api.types.is_float_dtype(df[col]) else None
                ws.set_column(j, j, min(ancho, 32), fmt)
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, len(df), len(df.columns) - 1)
    return ruta


if __name__ == "__main__":
    datos = generar_datos()
    salida = guardar_excel(datos)
    print(f"[OK] {salida.name} generado: {len(datos['Contratos'])} contratos, "
          f"{len(datos['Prestamos'])} préstamos, {len(datos['Recaudacion_Mensual'])} filas de recaudación mensual")
