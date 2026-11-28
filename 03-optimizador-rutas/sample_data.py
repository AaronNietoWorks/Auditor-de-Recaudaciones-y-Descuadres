"""
sample_data.py
--------------
Genera un archivo FICTICIO con la estructura típica de dos listados de IPS-Maq+:

  * Parque_Maquinas -> 42 establecimientos de la Vega Baja, Elche, Santa Pola y Alicante con 1-2 máquinas
                       cada uno (máx. 2 tipo B por bar), su ruta, última recaudación y recaudación media.
  * Averias         -> 12 meses de avisos técnicos por máquina y modelo.

Incluye a propósito (siempre respecto a la fecha de hoy):
  * El listado ordenado por código de bar (como suele salir del ERP), no por geografía: la ruta
    optimizada ahorra kilómetros frente a seguir el listado tal cual.
  * 6 bares sin coordenadas (solo población) para ver la ubicación aproximada.
  * Un modelo claramente problemático («Tritón 3», sobre todo billetero) y uno con una sola máquina.
  * 2 máquinas reincidentes (4 averías en los últimos 90 días) y 5 averías abiertas.

Nombres de bares, direcciones, modelos y números de serie son inventados.

Uso:  python sample_data.py   ->  crea datos_ejemplo_rutas.xlsx
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from analyzer import MUNICIPIOS

ARCHIVO_SALIDA = Path(__file__).resolve().parent / "datos_ejemplo_rutas.xlsx"

R1, R2, R3 = "R1 Vega Baja interior", "R2 Litoral sur", "R3 Elche-Santa Pola-Alicante"
# (nombre, población, ruta)
BARES = [
    ("Bar El Rincón", "Orihuela", R1), ("Cafetería La Plaza", "Orihuela", R1), ("Bar Los Arcos", "Callosa de Segura", R1),
    ("Mesón El Huerto", "Cox", R1), ("Bar La Estación", "Almoradí", R1), ("Cervecería Central", "Almoradí", R1),
    ("Bar Avenida", "Redován", R1), ("Taberna El Olivo", "Bigastro", R1), ("Bar Las Palmeras", "Benejúzar", R1),
    ("Cafetería Sol", "Catral", R1), ("Bar El Cruce", "Dolores", R1), ("Bodega San Juan", "Rafal", R1),
    ("Bar La Huerta", "Albatera", R1), ("Bar Paco", "Orihuela", R1),
    ("Bar El Puerto", "Torrevieja", R2), ("Cafetería Marina", "Torrevieja", R2), ("Bar Las Salinas", "Torrevieja", R2),
    ("Pub La Ola", "Torrevieja", R2), ("Bar Quesada", "Ciudad Quesada", R2), ("Bar El Puente", "Rojales", R2),
    ("Cafetería Dunas", "Guardamar del Segura", R2), ("Bar El Faro", "Guardamar del Segura", R2),
    ("Bar Flamenca", "Orihuela Costa", R2), ("Cervecería Zenia", "Orihuela Costa", R2),
    ("Bar La Torre", "Pilar de la Horadada", R2), ("Bar Salinas", "San Miguel de Salinas", R2),
    ("Bar La Mata", "La Mata", R2), ("Cafetería Montesinos", "Los Montesinos", R2),
    ("Bar El Palmeral", "Elche", R3), ("Cafetería Altabix", "Elche", R3), ("Bar Carrús", "Elche", R3),
    ("Bar La Glorieta", "Elche", R3), ("Bar Tamarit", "Santa Pola", R3), ("Cafetería El Varadero", "Santa Pola", R3),
    ("Bar Gran Alacant", "Gran Alacant", R3), ("Bar Benalúa", "Alicante", R3), ("Cervecería Postiguet", "Alicante", R3),
    ("Bar San Blas", "Alicante", R3), ("Bar Carolinas", "Alicante", R3), ("Bar El Molí", "Crevillent", R3),
    ("Bar Aeropuerto", "Torrellano", R3), ("Bar Las Bayas", "Elche", R3),
]
CALLES = ["C/ Mayor", "Avda. de la Constitución", "C/ San Pascual", "Plaza de España", "C/ Ramón y Cajal",
          "Avda. del Mar", "C/ Huertos", "C/ Doctor Gómez", "C/ Calvario", "Avda. Libertad", "C/ Santa Ana"]
# modelo: (averías por máquina y año, pesos por tipo de avería)
TIPOS = ["Billetero", "Monedero / hopper", "Pantalla táctil", "Placa / software", "Pulsadores", "Alimentación",
         "Cerradura / vandalismo"]
MODELOS = {
    "Tritón 3":     (4.6, [0.42, 0.18, 0.12, 0.12, 0.08, 0.04, 0.04]),
    "Aurora Plus":  (1.4, [0.20, 0.30, 0.15, 0.10, 0.15, 0.05, 0.05]),
    "Fénix Deluxe": (1.1, [0.20, 0.25, 0.20, 0.15, 0.10, 0.05, 0.05]),
    "Mistral B":    (2.8, [0.15, 0.40, 0.10, 0.15, 0.10, 0.05, 0.05]),
    "Delta Max":    (0.9, [0.20, 0.25, 0.20, 0.15, 0.10, 0.05, 0.05]),
    "Cometa 2":     (2.5, [0.20, 0.20, 0.20, 0.20, 0.10, 0.05, 0.05]),
}
REPARTO_MODELOS = ["Tritón 3"] * 13 + ["Aurora Plus"] * 16 + ["Fénix Deluxe"] * 14 + ["Mistral B"] * 12 + \
                  ["Delta Max"] * 9
DESCRIPCIONES = {
    "Billetero": ["No acepta billetes de 20", "Atasco de billete", "Billetero rechaza todo", "Error lector billetes"],
    "Monedero / hopper": ["Hopper no paga", "Monedas atascadas", "Monedero no valida 2 €", "Hopper vacío sin aviso"],
    "Pantalla táctil": ["Táctil descalibrado", "Pantalla en negro", "Rayas en pantalla"],
    "Placa / software": ["Error de memoria", "Reinicios continuos", "Actualización de juego", "Contadores no suben"],
    "Pulsadores": ["Pulsador de juego roto", "Botón cobrar no responde"],
    "Alimentación": ["No enciende", "Salta el diferencial del bar"],
    "Cerradura / vandalismo": ["Cerradura forzada", "Golpe en el frontal"],
}
TECNICOS = ["Técnico 1", "Técnico 2", "Técnico 3"]
SIN_COORDENADAS = {3, 9, 12, 25, 27, 39}
REINCIDENTES = {"M-1007": "Billetero", "M-1041": "Monedero / hopper"}


def generar_datos(semilla: int = 11, hoy: date | None = None) -> dict[str, pd.DataFrame]:
    """Devuelve {'Parque_Maquinas': df, 'Averias': df}."""
    rng = np.random.default_rng(semilla)
    hoy = hoy or date.today()

    # El código de bar sigue el orden alfabético: el listado del ERP queda «desordenado» geográficamente.
    orden_cod = sorted(range(len(BARES)), key=lambda i: BARES[i][0])
    codigo = {b: f"B{n + 1:03d}" for n, b in enumerate(orden_cod)}

    # ------------------------------------------------------------------ Parque de máquinas
    filas, n_serie = [], 1001
    modelos = list(rng.permutation(REPARTO_MODELOS))
    for b, (nombre, pob, ruta) in enumerate(BARES):
        lat0, lon0 = MUNICIPIOS[pob]
        lat = lat0 + float(rng.normal(0, 0.0045))
        lon = lon0 + float(rng.normal(0, 0.0055))
        n_maq = 2 if rng.random() < 0.55 else 1
        rec_bar = float(rng.uniform(180, 950)) * (1.25 if ruta == R2 else 1.0)
        frecuencia = 14 if rec_bar < 260 else 7
        ultima = hoy - timedelta(days=int(rng.integers(1, frecuencia + 6)))
        for m in range(n_maq):
            modelo = "Cometa 2" if b == 30 and m == 0 else (modelos.pop() if modelos else "Aurora Plus")
            filas.append({
                "Nº Serie": f"M-{n_serie}",
                "Modelo": modelo,
                "Establecimiento": f"{codigo[b]} - {nombre}",
                "Población": pob,
                "Dirección": f"{CALLES[int(rng.integers(0, len(CALLES)))]}, {int(rng.integers(1, 90))}",
                "Coordenadas GPS": None if b in SIN_COORDENADAS else f"{lat:.5f}, {lon:.5f}",
                "Ruta": ruta,
                "Últ. Recaudación": pd.Timestamp(ultima),
                "Frecuencia (días)": frecuencia,
                "Recaudación Media Semanal": round(rec_bar / n_maq * float(rng.uniform(0.8, 1.2)), 2),
            })
            n_serie += 1
    parque = pd.DataFrame(filas).sort_values(["Ruta", "Establecimiento", "Nº Serie"]).reset_index(drop=True)

    # ------------------------------------------------------------------ Averías
    inicio = hoy - timedelta(days=365)
    averias = []

    def aviso(maq, fecha_av: date, tipo: str, abierta: bool = False):
        dur = int(rng.choice([0, 0, 1, 1, 1, 2, 2, 3, 4, 6, 9, 14]))
        if tipo == "Billetero" and maq["Modelo"] == "Tritón 3":
            dur += int(rng.integers(0, 3))       # pieza con poco stock
        fin = None if abierta else min(fecha_av + timedelta(days=dur), hoy)
        coste = round(float(rng.uniform(25, 90)) + (float(rng.uniform(60, 220)) if tipo in
                      ("Billetero", "Pantalla táctil", "Placa / software") and rng.random() < .5 else 0), 2)
        averias.append({
            "Fecha Aviso": pd.Timestamp(fecha_av),
            "Nº Serie": maq["Nº Serie"],
            "Modelo": maq["Modelo"],
            "Establecimiento": maq["Establecimiento"],
            "Tipo Avería": tipo,
            "Descripción": str(rng.choice(DESCRIPCIONES[tipo])),
            "Fecha Resolución": pd.Timestamp(fin) if fin else None,
            "Estado": "Pendiente" if abierta else "Cerrada",
            "Coste Reparación": None if abierta else coste,
            "Técnico": str(rng.choice(TECNICOS)),
        })

    for _, maq in parque.iterrows():
        tasa, pesos = MODELOS[maq["Modelo"]]
        n = int(rng.poisson(tasa))
        for _ in range(n):
            f = inicio + timedelta(days=int(rng.integers(0, 358)))
            aviso(maq, f, str(rng.choice(TIPOS, p=pesos)))
    for serie, tipo in REINCIDENTES.items():
        maq = parque[parque["Nº Serie"] == serie].iloc[0]
        for dias in (80, 52, 27, 9):
            aviso(maq, hoy - timedelta(days=dias + int(rng.integers(0, 4))), tipo)
    # Averías abiertas recientes (aparecen como paradas prioritarias en la ruta del día)
    abiertas = parque.sample(5, random_state=semilla)
    for _, maq in abiertas.iterrows():
        tasa, pesos = MODELOS[maq["Modelo"]]
        aviso(maq, hoy - timedelta(days=int(rng.integers(0, 5))), str(rng.choice(TIPOS, p=pesos)), abierta=True)
    df_av = pd.DataFrame(averias).sort_values("Fecha Aviso").reset_index(drop=True)
    df_av.insert(0, "Nº Aviso", [f"AV-{5000 + i}" for i in range(len(df_av))])
    return {"Parque_Maquinas": parque, "Averias": df_av}


def guardar_excel(datos: dict[str, pd.DataFrame], ruta: Path = ARCHIVO_SALIDA) -> Path:
    """Guarda las hojas imitando el aspecto de una exportación del ERP."""
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
    print(f"[OK] {salida.name} generado: {len(datos['Parque_Maquinas'])} máquinas en "
          f"{datos['Parque_Maquinas']['Establecimiento'].nunique()} establecimientos, "
          f"{len(datos['Averias'])} averías")
