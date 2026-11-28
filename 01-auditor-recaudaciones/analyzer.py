"""
analyzer.py
-----------
Lógica de negocio del Auditor de Recaudaciones (sin dependencias de Streamlit):

* Lectura robusta de Excel/CSV exportados desde IPS-Maq+.
* Mapeo de columnas (sugerencia automática + plantillas en config_columnas.json).
* Motor de descuadres (semáforo Real - Teórico).
* Motor de caídas de rendimiento frente a la media móvil histórica.
* KPIs y exportación del informe ejecutivo a Excel multi-pestaña.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

CONFIG_PATH = Path(__file__).resolve().parent / "config_columnas.json"

# --------------------------------------------------------------------------- #
# 1. Definición de campos y mapeo de columnas
# --------------------------------------------------------------------------- #
CAMPOS = {
    "fecha":           {"etiqueta": "Fecha",                              "obligatorio": True},
    "bar":             {"etiqueta": "Código/Nombre Bar",                  "obligatorio": True},
    "maquina":         {"etiqueta": "Código/Modelo Máquina",              "obligatorio": True},
    "teorico":         {"etiqueta": "Recaudación Contadores (Teórica)",   "obligatorio": True},
    "real":            {"etiqueta": "Efectivo Contado (Real)",            "obligatorio": True},
    "liquidacion_bar": {"etiqueta": "Liquidación Bar (opcional)",         "obligatorio": False},
}

# Sinónimos habituales en los listados de IPS-Maq+ y hojas de arqueo.
_SINONIMOS = {
    "fecha": ["fecha recaudacion", "f recaudacion", "fecha", "f.rec", "fec", "dia", "date"],
    "bar": ["establecimiento", "nombre bar", "cod bar", "bar", "local", "cliente", "salon"],
    "maquina": ["maquina", "n maquina", "modelo", "terminal", "n serie", "serie", "aparato"],
    "teorico": ["recaudacion contadores", "rec contadores", "contadores", "teorica",
                "teorico", "recaudacion teorica", "bruto", "recaudacion"],
    "real": ["efectivo contado", "efectivo", "contado", "arqueo", "real", "caja", "dinero"],
    "liquidacion_bar": ["liquidacion bar", "liquidacion", "liq bar", "parte bar", "liq"],
}


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z0-9]+", " ", texto.lower())
    return texto.strip()


def sugerir_mapeo(columnas: list[str]) -> dict[str, str | None]:
    """Propone qué columna del archivo corresponde a cada campo interno."""
    candidatos = []
    for campo, sinonimos in _SINONIMOS.items():
        for col in columnas:
            ncol = _normalizar(col)
            for s in sinonimos:
                ns = _normalizar(s)
                if ns and (ncol == ns or re.search(rf"\b{re.escape(ns)}\b", ncol)):
                    # Puntuación: coincidencia exacta > sinónimo más largo
                    candidatos.append((100 if ncol == ns else len(ns), campo, col))
    mapeo: dict[str, str | None] = {c: None for c in CAMPOS}
    usadas: set[str] = set()
    for _, campo, col in sorted(candidatos, key=lambda x: -x[0]):
        if mapeo[campo] is None and col not in usadas:
            mapeo[campo] = col
            usadas.add(col)
    return mapeo


def cargar_plantillas(path: Path = CONFIG_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("plantillas", {})
    except (json.JSONDecodeError, OSError):
        return {}


def guardar_plantilla(nombre: str, mapeo: dict, path: Path = CONFIG_PATH) -> None:
    plantillas = cargar_plantillas(path)
    plantillas[nombre] = {k: v for k, v in mapeo.items() if v}
    path.write_text(
        json.dumps({"plantillas": plantillas}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def plantilla_compatible(columnas: list[str], path: Path = CONFIG_PATH):
    """Devuelve (nombre, mapeo) de la primera plantilla cuyas columnas existan en el archivo."""
    cols = set(columnas)
    for nombre, mapeo in cargar_plantillas(path).items():
        obligatorias = [mapeo.get(c) for c, d in CAMPOS.items() if d["obligatorio"]]
        if all(obligatorias) and set(v for v in mapeo.values() if v) <= cols:
            return nombre, mapeo
    return None, None


# --------------------------------------------------------------------------- #
# 2. Lectura de archivos y limpieza
# --------------------------------------------------------------------------- #
def leer_archivo(archivo, nombre: str | None = None) -> pd.DataFrame:
    """Lee .xlsx, .xls o .csv (separador y codificación autodetectados)."""
    if isinstance(archivo, (str, Path)):
        nombre = nombre or str(archivo)
    nombre = (nombre or getattr(archivo, "name", "")).lower()
    if nombre.endswith((".xlsx", ".xlsm")):
        return pd.read_excel(archivo, engine="openpyxl")
    if nombre.endswith(".xls"):
        return pd.read_excel(archivo, engine="xlrd")
    if nombre.endswith((".csv", ".txt")):
        crudo = archivo.read() if hasattr(archivo, "read") else Path(archivo).read_bytes()
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                texto = crudo.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        return pd.read_csv(io.StringIO(texto), sep=None, engine="python", dtype=str)
    raise ValueError("Formato no soportado. Usa .xlsx, .xls o .csv")


def a_numero(serie: pd.Series) -> pd.Series:
    """Convierte importes con formato español ('1.234,56 €') o anglosajón a float."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie.astype(float)

    def _conv(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        s = str(v).strip().replace("€", "").replace(" ", "").replace(" ", "")
        if s in ("", "-", "nan", "None"):
            return np.nan
        negativo = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        if "," in s and "." in s:
            # El último separador es el decimal
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
            s = s.replace(".", "")                 # '1.234' = mil doscientos...
        try:
            n = float(s)
        except ValueError:
            return np.nan
        return -n if negativo else n

    return serie.map(_conv).astype(float)


def aplicar_mapeo(df: pd.DataFrame, mapeo: dict) -> tuple[pd.DataFrame, list[str]]:
    """
    Renombra y tipa las columnas según el mapeo. Devuelve (df_limpio, avisos).
    """
    faltan = [CAMPOS[c]["etiqueta"] for c, d in CAMPOS.items()
              if d["obligatorio"] and not mapeo.get(c)]
    if faltan:
        raise ValueError("Faltan columnas obligatorias: " + ", ".join(faltan))

    avisos: list[str] = []
    out = pd.DataFrame({
        "fecha": pd.to_datetime(df[mapeo["fecha"]], dayfirst=True, errors="coerce"),
        "bar": df[mapeo["bar"]].astype(str).str.strip(),
        "maquina": df[mapeo["maquina"]].astype(str).str.strip(),
        "teorico": a_numero(df[mapeo["teorico"]]),
        "real": a_numero(df[mapeo["real"]]),
    })
    out["liquidacion_bar"] = (a_numero(df[mapeo["liquidacion_bar"]])
                              if mapeo.get("liquidacion_bar") else np.nan)
    out["fecha"] = out["fecha"].dt.normalize()

    invalidas = out["fecha"].isna() | out["bar"].isna() | out["maquina"].isna() \
        | out["bar"].isin(["", "nan", "None"]) | out["maquina"].isin(["", "nan", "None"])
    if invalidas.any():
        avisos.append(f"Se descartaron {int(invalidas.sum())} filas sin fecha, bar o máquina válidos "
                      "(totales, subtotales o filas vacías).")
        out = out[~invalidas]

    sin_importe = out["teorico"].isna() & out["real"].isna()
    if sin_importe.any():
        avisos.append(f"Se descartaron {int(sin_importe.sum())} filas sin importes.")
        out = out[~sin_importe]
    out[["teorico", "real"]] = out[["teorico", "real"]].fillna(0.0)

    dup = out.duplicated(["fecha", "bar", "maquina"], keep="last")
    if dup.any():
        avisos.append(f"{int(dup.sum())} filas duplicadas (misma fecha, bar y máquina): "
                      "se conserva la última.")
        out = out[~dup]

    return out.reset_index(drop=True), avisos


# --------------------------------------------------------------------------- #
# 3. Motor de detección de descuadres
# --------------------------------------------------------------------------- #
ESTADO_OK, ESTADO_REVISAR, ESTADO_CRITICO = "OK", "Revisar", "Crítico"
COLOR_ESTADO = {ESTADO_OK: "#16A34A", ESTADO_REVISAR: "#F59E0B", ESTADO_CRITICO: "#DC2626"}


def clasificar_descuadres(df: pd.DataFrame, margen_ok: float = 2.0,
                          umbral_critico: float = 15.0) -> pd.DataFrame:
    """
    Calcula diferencia = Real - Teórico y asigna el semáforo:
      * OK      : |dif| <= margen_ok (cambio / monedas)
      * Revisar : margen_ok < |dif| <= umbral_critico
      * Crítico : |dif| > umbral_critico, o recaudación (teórica o real) igual a 0 €
    """
    out = df.copy()
    out["diferencia"] = (out["real"] - out["teorico"]).round(2)
    absdif = out["diferencia"].abs()
    cero = (out["teorico"].round(2) == 0) | (out["real"].round(2) == 0)
    out["estado"] = np.select(
        [cero | (absdif > umbral_critico), absdif > margen_ok],
        [ESTADO_CRITICO, ESTADO_REVISAR],
        default=ESTADO_OK,
    )
    out["motivo"] = np.select(
        [cero, absdif > umbral_critico, absdif > margen_ok],
        ["Recaudación a 0 €", "Desviación > %.0f €" % umbral_critico,
         "Desviación moderada"],
        default="",
    )
    return out


# --------------------------------------------------------------------------- #
# 4. Motor de detección de caídas de rendimiento
# --------------------------------------------------------------------------- #
def serie_con_media_movil(hist: pd.DataFrame, nivel: str = "maquina",
                          ventana: int = 8, metrica: str = "teorico") -> pd.DataFrame:
    """
    Agrega el histórico por entidad (máquina o bar) y fecha y añade la media móvil
    de las `ventana` recaudaciones ANTERIORES (la actual no cuenta en su media).
    """
    claves = ["bar", "maquina"] if nivel == "maquina" else ["bar"]
    serie = (hist.groupby(claves + ["fecha"], as_index=False)[metrica].sum()
                 .rename(columns={metrica: "recaudacion"})
                 .sort_values(claves + ["fecha"]))
    serie["media_movil"] = (serie.groupby(claves)["recaudacion"]
                                 .transform(lambda s: s.shift(1).rolling(ventana, min_periods=3).mean()))
    return serie


def detectar_caidas(hist: pd.DataFrame, umbral: float = 0.25, nivel: str = "maquina",
                    ventana: int = 8, metrica: str = "teorico") -> pd.DataFrame:
    """
    Compara la ÚLTIMA recaudación de cada entidad con su media móvil histórica.
    Marca alerta si cae más de `umbral` (0.25 = 25 %).
    """
    columnas = ["bar", "maquina", "fecha_ultima", "ultima_recaudacion", "media_historica",
                "variacion", "registros", "alerta", "diagnostico"]
    if hist.empty:
        return pd.DataFrame(columns=columnas)

    claves = ["bar", "maquina"] if nivel == "maquina" else ["bar"]
    serie = serie_con_media_movil(hist, nivel, ventana, metrica)
    ultimos = serie.groupby(claves).tail(1).copy()
    ultimos["registros"] = serie.groupby(claves)["recaudacion"].transform("size").loc[ultimos.index]
    ultimos = ultimos.rename(columns={"fecha": "fecha_ultima",
                                      "recaudacion": "ultima_recaudacion",
                                      "media_movil": "media_historica"})
    ultimos["variacion"] = np.where(
        ultimos["media_historica"] > 0,
        ultimos["ultima_recaudacion"] / ultimos["media_historica"] - 1,
        np.nan,
    )
    ultimos["alerta"] = ultimos["variacion"] <= -umbral

    def _diag(r):
        if pd.isna(r["variacion"]):
            return "Histórico insuficiente"
        if r["ultima_recaudacion"] <= 0:
            return "Sin recaudación: posible máquina apagada o retirada"
        if r["variacion"] <= -0.5:
            return "Caída severa: revisar avería oculta o desconexión"
        if r["alerta"]:
            return "Caída significativa: posible cambio de tendencia"
        return "Dentro de lo habitual"

    ultimos["diagnostico"] = ultimos.apply(_diag, axis=1)
    if nivel == "bar":
        ultimos["maquina"] = "(todas)"
    return (ultimos[columnas]
            .sort_values(["alerta", "variacion"], ascending=[False, True])
            .reset_index(drop=True))


# --------------------------------------------------------------------------- #
# 5. KPIs
# --------------------------------------------------------------------------- #
def calcular_kpis(lote: pd.DataFrame, caidas: pd.DataFrame,
                  minutos_por_registro: float = 1.5) -> dict:
    incidencias = lote[lote["estado"] != ESTADO_OK]
    return {
        "total_recaudado": float(lote["real"].sum()),
        "total_teorico": float(lote["teorico"].sum()),
        "total_descuadres": float(incidencias["diferencia"].abs().sum()),
        "descuadre_neto": float(lote["diferencia"].sum()),
        "n_ok": int((lote["estado"] == ESTADO_OK).sum()),
        "n_revisar": int((lote["estado"] == ESTADO_REVISAR).sum()),
        "n_critico": int((lote["estado"] == ESTADO_CRITICO).sum()),
        "bares_en_alerta": int(caidas.loc[caidas["alerta"] == True, "bar"].nunique())
        if not caidas.empty else 0,
        "registros": int(len(lote)),
        "horas_ahorradas": len(lote) * minutos_por_registro / 60,
        "desde": lote["fecha"].min(),
        "hasta": lote["fecha"].max(),
    }


# --------------------------------------------------------------------------- #
# 6. Exportación del informe ejecutivo
# --------------------------------------------------------------------------- #
def exportar_informe_excel(lote: pd.DataFrame, caidas: pd.DataFrame, kpis: dict,
                           parametros: dict) -> bytes:
    """Genera el Excel multi-pestaña con formato profesional y lo devuelve en bytes."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter",
                        datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy") as writer:
        wb = writer.book
        f_titulo = wb.add_format({"bold": True, "font_size": 16, "font_color": "#0F2A4A"})
        f_sub = wb.add_format({"italic": True, "font_color": "#6B7280"})
        f_head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#0F4C81",
                                "border": 1, "align": "center", "valign": "vcenter",
                                "text_wrap": True})
        f_eur = wb.add_format({"num_format": "#,##0.00 €", "border": 1})
        f_eur_b = wb.add_format({"num_format": "#,##0.00 €", "border": 1, "bold": True})
        f_pct = wb.add_format({"num_format": "0.0%", "border": 1})
        f_int = wb.add_format({"num_format": "#,##0", "border": 1})
        f_num1 = wb.add_format({"num_format": "#,##0.0", "border": 1})
        f_txt = wb.add_format({"border": 1})
        f_txt_b = wb.add_format({"border": 1, "bold": True})
        f_fecha = wb.add_format({"num_format": "dd/mm/yyyy", "border": 1})
        f_rojo = wb.add_format({"bg_color": "#FDE2E2", "font_color": "#991B1B"})
        f_ambar = wb.add_format({"bg_color": "#FEF3C7", "font_color": "#92400E"})

        def tabla(ws, df: pd.DataFrame, fila0: int, formatos: dict[str, object]):
            """Escribe un DataFrame con cabecera coloreada y formatos por columna."""
            for j, col in enumerate(df.columns):
                ws.write(fila0, j, col, f_head)
                fmt = formatos.get(col, f_txt)
                for i, v in enumerate(df[col].tolist(), start=fila0 + 1):
                    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
                        ws.write_blank(i, j, None, fmt)
                    elif isinstance(v, (pd.Timestamp, datetime)):
                        ws.write_datetime(i, j, pd.Timestamp(v).to_pydatetime(), fmt)
                    elif isinstance(v, (bool, np.bool_)):
                        ws.write(i, j, "Sí" if v else "No", fmt)
                    elif isinstance(v, (int, float, np.integer, np.floating)):
                        ws.write_number(i, j, float(v), fmt)
                    else:
                        ws.write(i, j, str(v), fmt)
            # Autoajuste de columnas
            for j, col in enumerate(df.columns):
                muestras = [str(col)] + [
                    (f"{v:,.2f} €" if isinstance(v, (float, np.floating)) else str(v))
                    for v in df[col].head(500).tolist()
                ]
                ancho = min(max(len(s) for s in muestras) + 3, 60)
                ws.set_column(j, j, max(ancho, 10))
            ws.set_row(fila0, 30)
            return fila0 + len(df) + 1

        # ---------------- Resumen_Ejecutivo ---------------- #
        ws = wb.add_worksheet("Resumen_Ejecutivo")
        writer.sheets["Resumen_Ejecutivo"] = ws
        ws.hide_gridlines(2)
        ws.write(0, 0, "TRUSS & CYTILAND · Auditoría de Recaudaciones y Descuadres", f_titulo)
        periodo = (f"Periodo analizado: {kpis['desde']:%d/%m/%Y} – {kpis['hasta']:%d/%m/%Y}"
                   if pd.notna(kpis["desde"]) else "")
        ws.write(1, 0, f"Generado el {datetime.now():%d/%m/%Y %H:%M}.  {periodo}", f_sub)

        indicadores = [
            ("Total recaudado (efectivo real)", kpis["total_recaudado"], f_eur_b),
            ("Total teórico (contadores)", kpis["total_teorico"], f_eur),
            ("Descuadre neto (Real - Teórico)", kpis["descuadre_neto"], f_eur),
            ("Importe en descuadres detectados (|dif|)", kpis["total_descuadres"], f_eur_b),
            ("Operaciones analizadas", kpis["registros"], f_int),
            ("Operaciones OK", kpis["n_ok"], f_int),
            ("Operaciones a revisar (ámbar)", kpis["n_revisar"], f_int),
            ("Alertas críticas (rojo)", kpis["n_critico"], f_int),
            ("Bares en alerta de caída", kpis["bares_en_alerta"], f_int),
            ("Horas de auditoría manual ahorradas (est.)", kpis["horas_ahorradas"], f_num1),
        ]
        ws.write(3, 0, "Indicador", f_head)
        ws.write(3, 1, "Valor", f_head)
        for i, (indicador, valor, fmt) in enumerate(indicadores, start=4):
            ws.write(i, 0, indicador, f_txt_b)
            ws.write_number(i, 1, float(valor), fmt)
        fila = 4 + len(indicadores) + 1

        ws.write(fila, 0, "Parámetros de auditoría", f_txt_b)
        fila += 1
        for k, v in parametros.items():
            ws.write(fila, 0, k, f_txt)
            ws.write(fila, 1, str(v), f_txt)
            fila += 1
        fila += 1

        ws.write(fila, 0, "Resumen por establecimiento", f_titulo)
        fila += 1
        por_bar = (lote.assign(incid=lote["estado"] != ESTADO_OK,
                               crit=lote["estado"] == ESTADO_CRITICO)
                   .groupby("bar", as_index=False)
                   .agg(Maquinas=("maquina", "nunique"), Operaciones=("maquina", "size"),
                        Teorico=("teorico", "sum"), Real=("real", "sum"),
                        Diferencia=("diferencia", "sum"), Incidencias=("incid", "sum"),
                        Criticas=("crit", "sum"))
                   .sort_values("Real", ascending=False))
        por_bar.columns = ["Bar", "Máquinas", "Operaciones", "Teórico (€)", "Real (€)",
                           "Diferencia (€)", "Incidencias", "Críticas"]
        fin = tabla(ws, por_bar, fila, {"Máquinas": f_int, "Operaciones": f_int,
                                        "Teórico (€)": f_eur, "Real (€)": f_eur,
                                        "Diferencia (€)": f_eur, "Incidencias": f_int,
                                        "Críticas": f_int})
        ws.conditional_format(fila + 1, 7, fin - 1, 7,
                              {"type": "cell", "criteria": ">", "value": 0, "format": f_rojo})
        ws.set_column(0, 0, 44)
        ws.set_column(1, 1, 22)

        # ---------------- Descuadres_Criticos ---------------- #
        inc = lote[lote["estado"] != ESTADO_OK].copy()
        inc["orden"] = inc["estado"].map({ESTADO_CRITICO: 0, ESTADO_REVISAR: 1})
        inc["absdif"] = inc["diferencia"].abs()
        inc = inc.sort_values(["orden", "absdif"], ascending=[True, False])
        desc = pd.DataFrame({
            "Fecha": inc["fecha"], "Bar": inc["bar"], "Máquina": inc["maquina"],
            "Teórico (€)": inc["teorico"], "Real (€)": inc["real"],
            "Diferencia (€)": inc["diferencia"], "Liquidación Bar (€)": inc["liquidacion_bar"],
            "Estado": inc["estado"], "Motivo": inc.get("motivo", ""),
        })
        ws2 = wb.add_worksheet("Descuadres_Criticos")
        writer.sheets["Descuadres_Criticos"] = ws2
        ws2.write(0, 0, "Operaciones con descuadre (Crítico y Revisar)", f_titulo)
        ws2.write(1, 0, f"Margen OK ±{parametros.get('Margen OK (€)', 2)} € · "
                        f"Crítico > {parametros.get('Umbral crítico (€)', 15)} € o recaudación 0 €", f_sub)
        if desc.empty:
            ws2.write(3, 0, "No se han detectado descuadres en el periodo. ✔", f_txt_b)
        else:
            fin = tabla(ws2, desc, 3, {"Fecha": f_fecha, "Teórico (€)": f_eur, "Real (€)": f_eur,
                                       "Diferencia (€)": f_eur, "Liquidación Bar (€)": f_eur})
            for texto, fmt in ((ESTADO_CRITICO, f_rojo), (ESTADO_REVISAR, f_ambar)):
                ws2.conditional_format(4, 0, fin - 1, len(desc.columns) - 1, {
                    "type": "formula", "criteria": f'=$H5="{texto}"', "format": fmt})
            ws2.autofilter(3, 0, fin - 1, len(desc.columns) - 1)
            ws2.freeze_panes(4, 0)

        # ---------------- Bares_En_Riesgo ---------------- #
        riesgo = caidas[caidas["alerta"] == True] if not caidas.empty else caidas
        ws3 = wb.add_worksheet("Bares_En_Riesgo")
        writer.sheets["Bares_En_Riesgo"] = ws3
        ws3.write(0, 0, "Caídas de recaudación frente a la media móvil", f_titulo)
        ws3.write(1, 0, f"Alerta si la última recaudación cae más de un "
                        f"{parametros.get('Umbral de caída', '25 %')} respecto a su media "
                        f"({parametros.get('Ventana media móvil', 8)} recaudaciones previas).", f_sub)
        if riesgo.empty:
            ws3.write(3, 0, "No hay establecimientos en riesgo con los parámetros actuales. ✔", f_txt_b)
        else:
            tr = pd.DataFrame({
                "Bar": riesgo["bar"], "Máquina": riesgo["maquina"],
                "Última recaudación": riesgo["fecha_ultima"],
                "Importe último (€)": riesgo["ultima_recaudacion"],
                "Media histórica (€)": riesgo["media_historica"],
                "Variación": riesgo["variacion"],
                "Pérdida vs media (€)": riesgo["ultima_recaudacion"] - riesgo["media_historica"],
                "Diagnóstico": riesgo["diagnostico"],
            })
            fin = tabla(ws3, tr, 3, {"Última recaudación": f_fecha, "Importe último (€)": f_eur,
                                     "Media histórica (€)": f_eur, "Variación": f_pct,
                                     "Pérdida vs media (€)": f_eur})
            ws3.conditional_format(4, 5, fin - 1, 5, {"type": "data_bar", "bar_color": "#F87171",
                                                      "bar_negative_color": "#F87171"})
            ws3.conditional_format(4, 6, fin - 1, 6, {"type": "cell", "criteria": "<",
                                                      "value": 0, "format": f_rojo})
            ws3.freeze_panes(4, 0)

        for hoja in (ws, ws2, ws3):
            hoja.set_landscape()
            hoja.fit_to_pages(1, 0)

    return buffer.getvalue()
