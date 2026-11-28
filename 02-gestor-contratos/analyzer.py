"""
analyzer.py
-----------
Lógica de negocio del Gestor de Contratos y Préstamos (sin dependencias de Streamlit):

* Lectura robusta de Excel (con selección de hoja) y CSV exportados desde IPS-Maq+.
* Mapeo de columnas para tres listados (contratos, préstamos, recaudación) con
  sugerencia automática y plantillas reutilizables en config_columnas.json.
* Semáforo de vencimientos de contratos (vencido / urgente / próximo / planificar / vigente)
  con prórrogas tácitas y fecha límite de preaviso.
* Seguimiento de préstamos a hosteleros: saldo pendiente, cuotas atrasadas, fecha prevista
  de amortización y riesgo de que el contrato termine antes de recuperar el dinero.
* Cruce opcional con la recaudación mensual para priorizar renovaciones.
* KPIs y exportación del informe ejecutivo a Excel multi-pestaña.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

CONFIG_PATH = Path(__file__).resolve().parent / "config_columnas.json"

# --------------------------------------------------------------------------- #
# 1. Definición de los tres listados y mapeo de columnas
# --------------------------------------------------------------------------- #
DATASETS: dict[str, dict] = {
    "contratos": {
        "titulo": "Contratos con establecimientos",
        "hoja": "contrat",
        "campos": {
            "bar":        {"etiqueta": "Establecimiento (código/nombre)", "obligatorio": True},
            "fecha_fin":  {"etiqueta": "Fecha de vencimiento",            "obligatorio": False},
            "contrato":   {"etiqueta": "Código de contrato",              "obligatorio": False},
            "fecha_alta": {"etiqueta": "Fecha de alta / firma",           "obligatorio": False},
            "duracion":   {"etiqueta": "Duración (meses)",                "obligatorio": False},
            "prorroga":   {"etiqueta": "Prórroga automática (Sí/No)",     "obligatorio": False},
            "preaviso":   {"etiqueta": "Preaviso (días)",                 "obligatorio": False},
            "ruta":       {"etiqueta": "Ruta / zona",                     "obligatorio": False},
            "maquinas":   {"etiqueta": "Nº de máquinas",                  "obligatorio": False},
        },
        "sinonimos": {
            "bar": ["establecimiento", "nombre bar", "cod bar", "bar", "local", "cliente", "salon",
                    "hostelero", "titular"],
            "fecha_fin": ["fecha vencimiento", "f vencimiento", "vencimiento", "fecha fin", "fin contrato",
                          "fecha baja", "caducidad", "vence", "fin"],
            "contrato": ["cod contrato", "codigo contrato", "n contrato", "num contrato", "contrato",
                         "referencia", "ref"],
            "fecha_alta": ["fecha alta", "f alta", "fecha inicio", "inicio", "fecha firma", "alta", "firma"],
            "prorroga": ["prorroga automatica", "prorroga", "renovacion automatica", "renovacion",
                         "tacita", "auto renovacion"],
            "preaviso": ["preaviso dias", "preaviso", "dias preaviso", "aviso"],
            "duracion": ["duracion meses", "duracion", "plazo meses", "vigencia meses", "meses"],
            "ruta": ["ruta", "zona", "recaudador", "comercial"],
            "maquinas": ["n maquinas", "num maquinas", "maquinas", "unidades", "n terminales"],
        },
    },
    "prestamos": {
        "titulo": "Préstamos / anticipos a hosteleros",
        "hoja": "prest",
        "campos": {
            "bar":        {"etiqueta": "Establecimiento (código/nombre)", "obligatorio": True},
            "importe":    {"etiqueta": "Importe concedido",               "obligatorio": True},
            "fecha":      {"etiqueta": "Fecha de concesión",              "obligatorio": True},
            "prestamo":   {"etiqueta": "Nº de préstamo",                  "obligatorio": False},
            "cuota":      {"etiqueta": "Cuota (semanal o mensual)",       "obligatorio": False},
            "n_cuotas":   {"etiqueta": "Nº de cuotas",                    "obligatorio": False},
            "amortizado": {"etiqueta": "Importe amortizado / devuelto",   "obligatorio": False},
            "pendiente":  {"etiqueta": "Saldo pendiente",                 "obligatorio": False},
        },
        "sinonimos": {
            "bar": ["establecimiento", "nombre bar", "cod bar", "bar", "local", "cliente", "hostelero",
                    "titular"],
            "importe": ["importe concedido", "importe prestamo", "importe anticipo", "capital", "importe",
                        "principal", "concedido"],
            "fecha": ["fecha concesion", "f concesion", "fecha prestamo", "fecha anticipo", "fecha alta",
                      "fecha entrega", "fecha"],
            "prestamo": ["n prestamo", "num prestamo", "cod prestamo", "prestamo", "anticipo", "referencia"],
            "cuota": ["cuota semanal", "cuota mensual", "cuota", "retencion semanal", "retencion mensual",
                      "descuento semanal", "descuento mensual", "retencion", "descuento", "mensualidad"],
            "n_cuotas": ["n cuotas", "num cuotas", "numero cuotas", "cuotas", "plazo semanas", "plazo meses",
                         "semanas", "plazo"],
            "amortizado": ["importe amortizado", "amortizado", "devuelto", "cobrado", "descontado",
                           "retenido"],
            "pendiente": ["saldo pendiente", "pendiente", "saldo", "deuda", "resto"],
        },
    },
    "recaudacion": {
        "titulo": "Recaudación por establecimiento (opcional)",
        "hoja": "recaud",
        "campos": {
            "fecha":           {"etiqueta": "Fecha / mes",                     "obligatorio": True},
            "bar":             {"etiqueta": "Establecimiento (código/nombre)", "obligatorio": True},
            "recaudacion":     {"etiqueta": "Recaudación",                     "obligatorio": True},
            "liquidacion_bar": {"etiqueta": "Liquidación bar (opcional)",      "obligatorio": False},
        },
        "sinonimos": {
            "fecha": ["mes", "periodo", "fecha recaudacion", "f recaudacion", "fecha", "date"],
            "bar": ["establecimiento", "nombre bar", "cod bar", "bar", "local", "cliente", "salon"],
            "recaudacion": ["recaudacion bruta", "recaudacion", "rec contadores", "efectivo contado",
                            "bruto", "neto empresa", "importe", "total"],
            "liquidacion_bar": ["liquidacion bar", "liquidacion", "liq bar", "parte bar"],
        },
    },
}


def campos(dataset: str) -> dict:
    return DATASETS[dataset]["campos"]


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z0-9]+", " ", texto.lower())
    return texto.strip()


def sugerir_mapeo(dataset: str, columnas: list[str]) -> dict[str, str | None]:
    """Propone qué columna del archivo corresponde a cada campo interno."""
    candidatos = []
    for campo, sinonimos in DATASETS[dataset]["sinonimos"].items():
        for col in columnas:
            ncol = _normalizar(col)
            for s in sinonimos:
                ns = _normalizar(s)
                if ns and (ncol == ns or re.search(rf"\b{re.escape(ns)}\b", ncol)):
                    candidatos.append((100 if ncol == ns else len(ns), campo, col))
    mapeo: dict[str, str | None] = {c: None for c in campos(dataset)}
    usadas: set[str] = set()
    for _, campo, col in sorted(candidatos, key=lambda x: -x[0]):
        if mapeo[campo] is None and col not in usadas:
            mapeo[campo] = col
            usadas.add(col)
    return mapeo


def cargar_plantillas(dataset: str, path: Path = CONFIG_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(dataset, {})
    except (json.JSONDecodeError, OSError):
        return {}


def guardar_plantilla(dataset: str, nombre: str, mapeo: dict, path: Path = CONFIG_PATH) -> None:
    todo = {}
    if path.exists():
        try:
            todo = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            todo = {}
    todo.setdefault(dataset, {})[nombre] = {k: v for k, v in mapeo.items() if v}
    path.write_text(json.dumps(todo, ensure_ascii=False, indent=2), encoding="utf-8")


def plantilla_compatible(dataset: str, columnas: list[str], path: Path = CONFIG_PATH):
    """Devuelve (nombre, mapeo) de la primera plantilla cuyas columnas existan en el archivo."""
    cols = set(columnas)
    for nombre, mapeo in cargar_plantillas(dataset, path).items():
        obligatorias = [mapeo.get(c) for c, d in campos(dataset).items() if d["obligatorio"]]
        if all(obligatorias) and set(v for v in mapeo.values() if v) <= cols:
            return nombre, {c: mapeo.get(c) for c in campos(dataset)}
    return None, None


# --------------------------------------------------------------------------- #
# 2. Lectura de archivos y conversión de tipos
# --------------------------------------------------------------------------- #
def hojas_excel(archivo) -> list[str]:
    """Nombres de las hojas de un Excel (lista vacía si es CSV)."""
    nombre = str(getattr(archivo, "name", archivo)).lower()
    if not nombre.endswith((".xlsx", ".xlsm", ".xls")):
        return []
    if hasattr(archivo, "seek"):
        archivo.seek(0)
    engine = "xlrd" if nombre.endswith(".xls") else "openpyxl"
    hojas = pd.ExcelFile(archivo, engine=engine).sheet_names
    if hasattr(archivo, "seek"):
        archivo.seek(0)
    return hojas


def hoja_sugerida(dataset: str, hojas: list[str]) -> int:
    clave = DATASETS[dataset]["hoja"]
    for i, h in enumerate(hojas):
        if clave in _normalizar(h):
            return i
    return 0


def leer_archivo(archivo, hoja: str | int | None = 0) -> pd.DataFrame:
    """Lee .xlsx, .xls o .csv (separador y codificación autodetectados)."""
    nombre = str(getattr(archivo, "name", archivo)).lower()
    if hasattr(archivo, "seek"):
        archivo.seek(0)
    if nombre.endswith((".xlsx", ".xlsm")):
        df = pd.read_excel(archivo, sheet_name=hoja or 0, engine="openpyxl")
    elif nombre.endswith(".xls"):
        df = pd.read_excel(archivo, sheet_name=hoja or 0, engine="xlrd")
    elif nombre.endswith((".csv", ".txt")):
        crudo = archivo.read() if hasattr(archivo, "read") else Path(archivo).read_bytes()
        texto = None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                texto = crudo.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        df = pd.read_csv(io.StringIO(texto), sep=None, engine="python", dtype=str)
    else:
        raise ValueError("Formato no soportado. Usa .xlsx, .xls o .csv")
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def a_numero(serie: pd.Series) -> pd.Series:
    """Convierte importes con formato español ('1.234,56 €') o anglosajón a float."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie.astype(float)

    def _conv(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        s = str(v).strip().replace("€", "").replace("%", "").replace(" ", "").replace(" ", "")
        if s in ("", "-", "nan", "None"):
            return np.nan
        negativo = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
            s = s.replace(".", "")
        try:
            n = float(s)
        except ValueError:
            return np.nan
        return -n if negativo else n

    return serie.map(_conv).astype(float)


def a_fecha(serie: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(serie):
        return pd.to_datetime(serie).dt.normalize()
    return pd.to_datetime(serie, dayfirst=True, errors="coerce").dt.normalize()


_SI = {"si", "s", "x", "1", "true", "verdadero", "yes", "y", "tacita", "automatica", "auto"}


def a_booleano(serie: pd.Series) -> pd.Series:
    return serie.map(lambda v: _normalizar(v) in _SI if pd.notna(v) else False).astype(bool)


def clave_bar(texto) -> str:
    """
    Clave para cruzar establecimientos entre listados distintos.
    Quita un código inicial tipo 'B001 - ' y normaliza acentos y mayúsculas, de modo que
    'B001 - Bar El Rincón' y 'BAR EL RINCON' se reconocen como el mismo establecimiento.
    """
    t = str(texto).strip()
    t = re.sub(r"^\s*[A-Za-z]{0,4}\d+\s*[-–·|:]\s*", "", t)
    return _normalizar(t)


def _texto(serie: pd.Series) -> pd.Series:
    # astype(object) primero: con pandas 3 (dtype «str») un NaN sobrevive a astype(str) y no se detectaba vacío.
    # Códigos numéricos leídos de Excel (12345.0) se muestran como 12345.
    obj = serie.astype(object).where(serie.notna(), "")
    obj = obj.map(lambda v: str(int(v)) if isinstance(v, float) and v.is_integer() else v)
    return obj.astype(str).str.strip().replace({"nan": "", "None": "", "<NA>": "", "NaT": ""})


DURACION_CONTRATO_MESES = 60      # contratos de instalación habituales: 5 años
MAX_MAQUINAS_B_HOSTELERIA = 2     # Comunitat Valenciana: máximo de 2 máquinas tipo B por establecimiento de hostelería


def aplicar_mapeo(dataset: str, df: pd.DataFrame, mapeo: dict,
                  duracion_defecto: int = DURACION_CONTRATO_MESES) -> tuple[pd.DataFrame, list[str]]:
    """
    Renombra y tipa las columnas según el mapeo. Devuelve (df_limpio, avisos).

    En contratos, si no hay fecha de vencimiento se calcula como fecha de alta + duración
    (columna «Duración (meses)» o, si falta, `duracion_defecto` meses).
    """
    defin = campos(dataset)
    faltan = [d["etiqueta"] for c, d in defin.items() if d["obligatorio"] and not mapeo.get(c)]
    if dataset == "contratos" and not mapeo.get("fecha_fin") and not mapeo.get("fecha_alta"):
        faltan.append("Fecha de vencimiento (o, en su defecto, Fecha de alta)")
    if faltan:
        raise ValueError("Faltan columnas obligatorias: " + ", ".join(faltan))

    def col(campo):
        return df[mapeo[campo]] if mapeo.get(campo) else pd.Series([np.nan] * len(df), index=df.index)

    avisos: list[str] = []
    if dataset == "contratos":
        out = pd.DataFrame({
            "bar": _texto(col("bar")),
            "contrato": _texto(col("contrato")) if mapeo.get("contrato") else "",
            "ruta": _texto(col("ruta")) if mapeo.get("ruta") else "",
            "fecha_alta": a_fecha(col("fecha_alta")),
            "fecha_fin": a_fecha(col("fecha_fin")),
            "prorroga": a_booleano(col("prorroga")) if mapeo.get("prorroga") else False,
            "preaviso": a_numero(col("preaviso")),
            "maquinas": a_numero(col("maquinas")),
        })
        duracion = a_numero(col("duracion")).where(lambda x: x > 0).fillna(duracion_defecto)
        calcular = out["fecha_fin"].isna() & out["fecha_alta"].notna()
        if calcular.any():
            out.loc[calcular, "fecha_fin"] = [
                a + pd.DateOffset(months=int(m)) for a, m in zip(out.loc[calcular, "fecha_alta"],
                                                                  duracion[calcular])]
            avisos.append(f"{int(calcular.sum())} contratos sin fecha de vencimiento: se calcula como fecha de "
                          f"alta + duración ({duracion_defecto} meses si no se indica).")
        invalidas = (out["bar"] == "") | out["fecha_fin"].isna()
        motivo = "sin establecimiento o fecha de vencimiento válida"
        unica = ["bar", "contrato"]
    elif dataset == "prestamos":
        out = pd.DataFrame({
            "bar": _texto(col("bar")),
            "prestamo": _texto(col("prestamo")) if mapeo.get("prestamo") else "",
            "fecha": a_fecha(col("fecha")),
            "importe": a_numero(col("importe")),
            "cuota": a_numero(col("cuota")),
            "n_cuotas": a_numero(col("n_cuotas")),
            "amortizado": a_numero(col("amortizado")),
            "pendiente": a_numero(col("pendiente")),
        })
        invalidas = (out["bar"] == "") | out["fecha"].isna() | ~(out["importe"] > 0)
        motivo = "sin establecimiento, fecha o importe válido"
        unica = ["bar", "prestamo", "fecha"]
        sin_plazo = out["cuota"].isna() & out["n_cuotas"].isna() & ~invalidas
        if sin_plazo.any():
            avisos.append(f"{int(sin_plazo.sum())} préstamos sin cuota ni nº de cuotas: se asume un plazo "
                          "de 36 meses para calcular su calendario.")
        if not mapeo.get("amortizado") and not mapeo.get("pendiente"):
            avisos.append("No se ha indicado ni el importe amortizado ni el saldo pendiente: se asume que "
                          "todos los préstamos van al día y no se pueden detectar cuotas atrasadas.")
    else:  # recaudacion
        out = pd.DataFrame({
            "fecha": a_fecha(col("fecha")),
            "bar": _texto(col("bar")),
            "recaudacion": a_numero(col("recaudacion")),
            "liquidacion_bar": a_numero(col("liquidacion_bar")),
        })
        invalidas = (out["bar"] == "") | out["fecha"].isna() | out["recaudacion"].isna()
        motivo = "sin fecha, establecimiento o importe válido"
        unica = None

    if invalidas.any():
        avisos.append(f"Se descartaron {int(invalidas.sum())} filas {motivo} (totales, subtotales o "
                      "filas vacías).")
        out = out[~invalidas]

    if unica:
        dup = out.duplicated(unica, keep="last")
        if dup.any():
            avisos.append(f"{int(dup.sum())} filas duplicadas: se conserva la última.")
            out = out[~dup]

    out = out.copy()
    out["clave_bar"] = out["bar"].map(clave_bar)
    return out.reset_index(drop=True), avisos


# --------------------------------------------------------------------------- #
# 3. Motor de vencimientos de contratos
# --------------------------------------------------------------------------- #
VENCIDO, URGENTE, PROXIMO, PLANIFICAR, VIGENTE = "Vencido", "Urgente", "Próximo", "Planificar", "Vigente"
ESTADOS_CONTRATO = [VENCIDO, URGENTE, PROXIMO, PLANIFICAR, VIGENTE]
COLOR_CONTRATO = {VENCIDO: "#7F1D1D", URGENTE: "#DC2626", PROXIMO: "#F59E0B",
                  PLANIFICAR: "#3B82F6", VIGENTE: "#16A34A"}
GESTIONES = ["Sin gestionar", "Contactado", "En negociación", "Renovado", "No renueva"]


def evaluar_contratos(contratos: pd.DataFrame, fecha_ref: date,
                      umbrales: tuple[int, int, int] = (30, 60, 90),
                      meses_prorroga: int = 0) -> pd.DataFrame:
    """
    Añade a cada contrato su vencimiento efectivo, días restantes y semáforo:

    * Vencido    : la fecha de vencimiento ya ha pasado y el contrato no se prorroga solo.
    * Urgente    : vence en <= umbrales[0] días.
    * Próximo    : vence en <= umbrales[1] días.
    * Planificar : vence en <= umbrales[2] días.
    * Vigente    : vence más adelante.

    Los contratos con prórroga automática que ya pasaron su fecha original se consideran
    prorrogados tácitamente por periodos de `meses_prorroga` meses.
    """
    ref = pd.Timestamp(fecha_ref).normalize()
    out = contratos.copy()
    fin_ef, prorrogado = [], []
    for fin, auto in zip(out["fecha_fin"], out["prorroga"]):
        f = pd.Timestamp(fin)
        n = 0
        if auto and meses_prorroga > 0:
            while f < ref and n < 100:
                f = f + pd.DateOffset(months=meses_prorroga)
                n += 1
        fin_ef.append(f)
        prorrogado.append(n > 0)
    out["fin_efectivo"] = pd.to_datetime(fin_ef)
    # Con prórroga tácita desactivada (meses_prorroga = 0) ningún contrato se renueva solo
    out["prorroga_efectiva"] = out["prorroga"].astype(bool) & (meses_prorroga > 0)
    out["prorrogado"] = prorrogado
    out["dias_restantes"] = (out["fin_efectivo"] - ref).dt.days
    out["limite_preaviso"] = out["fin_efectivo"] - pd.to_timedelta(out["preaviso"].fillna(0), unit="D")
    out.loc[out["preaviso"].isna(), "limite_preaviso"] = pd.NaT

    d = out["dias_restantes"]
    u1, u2, u3 = umbrales
    out["estado"] = np.select([d < 0, d <= u1, d <= u2, d <= u3],
                              [VENCIDO, URGENTE, PROXIMO, PLANIFICAR], default=VIGENTE)
    out["orden"] = out["estado"].map({e: i for i, e in enumerate(ESTADOS_CONTRATO)})
    out["id_contrato"] = out["clave_bar"] + "|" + out["contrato"].astype(str)
    return out.sort_values(["orden", "dias_restantes"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 4. Motor de préstamos a hosteleros
# --------------------------------------------------------------------------- #
P_AMORTIZADO, P_AL_DIA, P_RIESGO, P_CRITICO = "Amortizado", "Al día", "Riesgo", "Crítico"
ESTADOS_PRESTAMO = [P_CRITICO, P_RIESGO, P_AL_DIA, P_AMORTIZADO]
COLOR_PRESTAMO = {P_CRITICO: "#DC2626", P_RIESGO: "#F59E0B", P_AL_DIA: "#16A34A", P_AMORTIZADO: "#94A3B8"}


SEMANAL, MENSUAL = "Semanal", "Mensual"
PERIODICIDADES = [SEMANAL, MENSUAL]
CUOTAS_AL_MES = {SEMANAL: 52 / 12, MENSUAL: 1.0}


def _meses_entre(desde: pd.Timestamp, hasta: pd.Timestamp) -> int:
    """Meses completos transcurridos."""
    if pd.isna(desde) or pd.isna(hasta) or hasta < desde:
        return 0
    m = (hasta.year - desde.year) * 12 + (hasta.month - desde.month)
    if hasta.day < desde.day:
        m -= 1
    return max(m, 0)


def periodos_entre(desde: pd.Timestamp, hasta: pd.Timestamp, periodicidad: str = SEMANAL) -> int:
    """Cuotas completas devengadas entre dos fechas (semanas o meses)."""
    if periodicidad == MENSUAL:
        return _meses_entre(desde, hasta)
    if pd.isna(desde) or pd.isna(hasta) or hasta < desde:
        return 0
    return int((hasta - desde).days // 7)


def sumar_periodos(fecha: pd.Timestamp, n: int, periodicidad: str = SEMANAL) -> pd.Timestamp:
    if periodicidad == MENSUAL:
        return fecha + pd.DateOffset(months=int(n))
    return fecha + pd.Timedelta(weeks=int(n))


def evaluar_prestamos(prestamos: pd.DataFrame, contratos_ev: pd.DataFrame | None, fecha_ref: date,
                      tolerancia_cuotas: float = 1.0, critico_cuotas: float = 3.0,
                      periodicidad: str = SEMANAL, plazo_defecto_meses: int = 36) -> pd.DataFrame:
    """
    Calcula para cada préstamo: cuota, cuotas devengadas, importe que debería estar devuelto,
    saldo pendiente, retraso (en € y en cuotas), fecha prevista de amortización y el cruce con
    el contrato del establecimiento.

    Supuesto: el préstamo se devuelve en cuotas iguales descontadas de la recaudación de la
    máquina con la `periodicidad` indicada (semanal por defecto: se descuenta en cada recaudación
    semanal). La primera cuota se devenga un periodo después de la concesión. Las cuotas y el
    nº de cuotas del listado se interpretan en esa misma periodicidad.

    Semáforo:
    * Crítico : retraso >= `critico_cuotas` cuotas, o contrato vencido con saldo pendiente.
    * Riesgo  : retraso >= `tolerancia_cuotas`, o el contrato termina antes de amortizarse.
    * Al día  : sin incidencias.
    * Amortizado : saldo pendiente 0.
    """
    ref = pd.Timestamp(fecha_ref).normalize()
    p = prestamos.copy()
    plazo_defecto = max(1, round(plazo_defecto_meses * CUOTAS_AL_MES[periodicidad]))
    plazo = p["n_cuotas"].where(p["n_cuotas"] > 0)
    cuota = p["cuota"].where(p["cuota"] > 0)
    cuota = cuota.fillna(p["importe"] / plazo).fillna(p["importe"] / plazo_defecto)
    plazo = plazo.fillna(np.ceil((p["importe"] / cuota).round(6)))
    p["cuota"], p["n_cuotas"] = cuota.round(2), plazo.astype(int)
    p["cuota_mensual_eq"] = (p["cuota"] * CUOTAS_AL_MES[periodicidad]).round(2)

    p["cuotas_devengadas"] = [min(periodos_entre(f, ref, periodicidad), n)
                              for f, n in zip(p["fecha"], p["n_cuotas"])]
    p["esperado"] = np.minimum(p["importe"], p["cuotas_devengadas"] * p["cuota"]).round(2)
    amort = p["amortizado"].copy()
    amort = amort.fillna(p["importe"] - p["pendiente"])
    p["sin_dato_cobro"] = amort.isna()
    amort = amort.fillna(p["esperado"])
    p["amortizado"] = amort.clip(lower=0).round(2)
    p["pendiente"] = (p["importe"] - p["amortizado"]).clip(lower=0).round(2)
    p["retraso_eur"] = (p["esperado"] - p["amortizado"]).clip(lower=0).round(2)
    p["retraso_cuotas"] = (p["retraso_eur"] / p["cuota"]).round(1)
    p["pct_amortizado"] = (p["amortizado"] / p["importe"]).clip(0, 1)
    p["cuotas_restantes"] = np.ceil((p["pendiente"] / p["cuota"]).round(6)).astype(int)
    p["fin_previsto"] = [sumar_periodos(ref, n, periodicidad) if n > 0 else pd.NaT
                         for n in p["cuotas_restantes"]]

    # Cruce con contratos
    p["fin_contrato"] = pd.NaT
    p["estado_contrato"] = "—"          # sin listado de contratos: no se puede cruzar
    p["prorroga"] = False
    if contratos_ev is not None and not contratos_ev.empty:
        c = (contratos_ev.sort_values("fin_efectivo", ascending=False)
                         .drop_duplicates("clave_bar")
                         .set_index("clave_bar"))
        p["fin_contrato"] = p["clave_bar"].map(c["fin_efectivo"])
        p["estado_contrato"] = p["clave_bar"].map(c["estado"]).fillna("Sin contrato")
        p["prorroga"] = p["clave_bar"].map(c["prorroga_efectiva"]).fillna(False).astype(bool)

    expuesto = []
    for pend, cuo, fin, auto in zip(p["pendiente"], p["cuota"], p["fin_contrato"], p["prorroga"]):
        if pd.isna(fin) or auto or pend <= 0:
            expuesto.append(0.0)
        else:
            n = periodos_entre(ref, fin, periodicidad)
            expuesto.append(round(max(0.0, pend - cuo * n), 2))
    p["expuesto_fin_contrato"] = expuesto

    activo = p["pendiente"] > 0.01
    contrato_vencido = p["estado_contrato"].eq(VENCIDO)
    critico = activo & ((p["retraso_cuotas"] >= critico_cuotas) | contrato_vencido)
    riesgo = activo & ((p["retraso_cuotas"] >= tolerancia_cuotas) | (p["expuesto_fin_contrato"] > 0)
                       | p["estado_contrato"].eq("Sin contrato"))
    p["estado"] = np.select([~activo, critico, riesgo], [P_AMORTIZADO, P_CRITICO, P_RIESGO], default=P_AL_DIA)

    unidad = "semanas" if periodicidad == SEMANAL else "cuotas mensuales"
    motivos = []
    for r in p.itertuples():
        m = []
        if r.pendiente <= 0.01:
            motivos.append("Préstamo devuelto")
            continue
        if r.estado_contrato == VENCIDO:
            m.append("Contrato vencido con saldo pendiente")
        elif r.estado_contrato == "Sin contrato":
            m.append("No se encuentra su contrato")
        if r.retraso_cuotas >= tolerancia_cuotas:
            m.append(f"{str(r.retraso_cuotas).replace('.', ',')} {unidad} sin descontar")
        if r.expuesto_fin_contrato > 0 and r.estado_contrato != VENCIDO:
            m.append(f"El contrato vence antes de amortizar ({r.expuesto_fin_contrato:,.0f} € pendientes)"
                     .replace(",", "."))
        if r.sin_dato_cobro:
            m.append("Sin dato de cobros: se asume al día")
        motivos.append(" · ".join(m))
    p["motivo"] = motivos
    p["orden"] = p["estado"].map({e: i for i, e in enumerate(ESTADOS_PRESTAMO)})
    return p.sort_values(["orden", "pendiente"], ascending=[True, False]).reset_index(drop=True)


def calendario_amortizacion(prestamos_ev: pd.DataFrame, fecha_ref: date, meses: int = 24,
                            periodicidad: str = SEMANAL) -> pd.DataFrame:
    """
    Proyección de cobros pendientes cuota a cuota durante los próximos `meses` meses.
    Devuelve una fila por cuota con su fecha y el mes al que pertenece (para agregar).
    """
    ref = pd.Timestamp(fecha_ref).normalize()
    limite = ref + pd.DateOffset(months=meses)
    filas = []
    for r in prestamos_ev[prestamos_ev["pendiente"] > 0.01].itertuples():
        saldo = float(r.pendiente)
        k = 1
        while saldo > 0.01:
            f = sumar_periodos(ref, k, periodicidad)
            if f > limite:
                break
            pago = round(min(float(r.cuota), saldo), 2)
            saldo = round(saldo - pago, 2)
            filas.append({"fecha": f, "mes": f.to_period("M").to_timestamp(), "bar": r.bar,
                          "prestamo": r.prestamo, "cuota": pago, "saldo": saldo})
            k += 1
    return pd.DataFrame(filas, columns=["fecha", "mes", "bar", "prestamo", "cuota", "saldo"])


# --------------------------------------------------------------------------- #
# 5. Cruce con la recaudación
# --------------------------------------------------------------------------- #
def recaudacion_mensual(rec: pd.DataFrame, fecha_ref: date, meses: int = 12) -> pd.DataFrame:
    """Media mensual de recaudación (y liquidación al bar) de los últimos `meses` meses."""
    if rec is None or rec.empty:
        return pd.DataFrame(columns=["clave_bar", "rec_mensual", "liq_mensual", "meses_con_datos"])
    ref = pd.Timestamp(fecha_ref)
    desde = (ref.to_period("M") - meses).to_timestamp()
    r = rec[(rec["fecha"] >= desde) & (rec["fecha"] <= ref)].copy()
    if r.empty:
        r = rec.copy()
    r["mes"] = r["fecha"].dt.to_period("M")
    m = (r.groupby(["clave_bar", "mes"], as_index=False)
          .agg(rec=("recaudacion", "sum"), liq=("liquidacion_bar", lambda s: s.sum(min_count=1))))
    return (m.groupby("clave_bar", as_index=False)
             .agg(rec_mensual=("rec", "mean"), liq_mensual=("liq", "mean"), meses_con_datos=("mes", "nunique")))


def cruzar_recaudacion(contratos_ev: pd.DataFrame, prestamos_ev: pd.DataFrame | None,
                       rec_mes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    c = contratos_ev.merge(rec_mes[["clave_bar", "rec_mensual", "liq_mensual"]], on="clave_bar", how="left")
    c["rec_anual"] = c["rec_mensual"] * 12
    p = prestamos_ev
    if p is not None and not p.empty:
        p = p.merge(rec_mes[["clave_bar", "rec_mensual", "liq_mensual"]], on="clave_bar", how="left")
        p["meses_recaudacion"] = p["pendiente"] / p["rec_mensual"]
        p["peso_cuota_liq"] = p["cuota_mensual_eq"] / p["liq_mensual"]
    return c, p


# --------------------------------------------------------------------------- #
# 6. KPIs
# --------------------------------------------------------------------------- #
def calcular_kpis(contratos_ev: pd.DataFrame | None, prestamos_ev: pd.DataFrame | None,
                  minutos_por_contrato: float = 3.0) -> dict:
    k = {"n_contratos": 0, "n_vencidos": 0, "n_urgentes": 0, "n_proximos": 0, "n_planificar": 0,
         "n_vigentes": 0, "n_prorrogados": 0, "en_ventana": 0, "rec_en_juego": np.nan,
         "n_prestamos": 0, "n_activos": 0, "capital_concedido": 0.0, "capital_pendiente": 0.0,
         "capital_riesgo": 0.0, "retraso_total": 0.0, "n_retraso": 0, "n_criticos": 0,
         "n_riesgo": 0, "expuesto_total": 0.0, "horas_ahorradas": 0.0}
    if contratos_ev is not None and not contratos_ev.empty:
        e = contratos_ev["estado"]
        k.update(n_contratos=len(contratos_ev), n_vencidos=int((e == VENCIDO).sum()),
                 n_urgentes=int((e == URGENTE).sum()), n_proximos=int((e == PROXIMO).sum()),
                 n_planificar=int((e == PLANIFICAR).sum()), n_vigentes=int((e == VIGENTE).sum()),
                 n_prorrogados=int(contratos_ev["prorrogado"].sum()))
        k["en_ventana"] = k["n_vencidos"] + k["n_urgentes"] + k["n_proximos"] + k["n_planificar"]
        if "rec_anual" in contratos_ev and contratos_ev["rec_anual"].notna().any():
            k["rec_en_juego"] = float(contratos_ev.loc[e != VIGENTE, "rec_anual"].sum())
    if prestamos_ev is not None and not prestamos_ev.empty:
        p = prestamos_ev
        act = p[p["pendiente"] > 0.01]
        mal = act[act["estado"].isin([P_CRITICO, P_RIESGO])]
        k.update(n_prestamos=len(p), n_activos=len(act),
                 capital_concedido=float(p["importe"].sum()), capital_pendiente=float(act["pendiente"].sum()),
                 capital_riesgo=float(mal["pendiente"].sum()), retraso_total=float(act["retraso_eur"].sum()),
                 n_retraso=int((act["retraso_eur"] > 0.01).sum()),
                 n_criticos=int((act["estado"] == P_CRITICO).sum()),
                 n_riesgo=int((act["estado"] == P_RIESGO).sum()),
                 expuesto_total=float(act["expuesto_fin_contrato"].sum()))
    k["horas_ahorradas"] = (k["n_contratos"] + k["n_prestamos"]) * minutos_por_contrato / 60
    return k


# --------------------------------------------------------------------------- #
# 7. Exportación del informe ejecutivo
# --------------------------------------------------------------------------- #
def exportar_informe_excel(contratos_ev: pd.DataFrame | None, prestamos_ev: pd.DataFrame | None,
                           calendario: pd.DataFrame | None, kpis: dict, parametros: dict) -> bytes:
    """Genera el Excel multi-pestaña con formato profesional y lo devuelve en bytes."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter",
                        datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy") as writer:
        wb = writer.book
        f_titulo = wb.add_format({"bold": True, "font_size": 16, "font_color": "#0F2A4A"})
        f_sub = wb.add_format({"italic": True, "font_color": "#6B7280"})
        f_head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#0F4C81",
                                "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True})
        f_eur = wb.add_format({"num_format": "#,##0.00 €", "border": 1})
        f_eur_b = wb.add_format({"num_format": "#,##0.00 €", "border": 1, "bold": True})
        f_pct = wb.add_format({"num_format": "0%", "border": 1})
        f_int = wb.add_format({"num_format": "#,##0", "border": 1})
        f_num1 = wb.add_format({"num_format": "#,##0.0", "border": 1})
        f_txt = wb.add_format({"border": 1})
        f_txt_b = wb.add_format({"border": 1, "bold": True})
        f_fecha = wb.add_format({"num_format": "dd/mm/yyyy", "border": 1})
        f_mes = wb.add_format({"num_format": "mmm yyyy", "border": 1})
        f_granate = wb.add_format({"bg_color": "#F5D0D0", "font_color": "#7F1D1D", "bold": True})
        f_rojo = wb.add_format({"bg_color": "#FDE2E2", "font_color": "#991B1B"})
        f_ambar = wb.add_format({"bg_color": "#FEF3C7", "font_color": "#92400E"})
        f_azul = wb.add_format({"bg_color": "#DBEAFE", "font_color": "#1E3A8A"})

        def tabla(ws, df: pd.DataFrame, fila0: int, formatos: dict[str, object]) -> int:
            for j, col in enumerate(df.columns):
                ws.write(fila0, j, col, f_head)
                fmt = formatos.get(col, f_txt)
                for i, v in enumerate(df[col].tolist(), start=fila0 + 1):
                    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
                        ws.write_blank(i, j, None, fmt)
                    elif isinstance(v, (pd.Timestamp, datetime, date)):
                        ws.write_datetime(i, j, pd.Timestamp(v).to_pydatetime(), fmt)
                    elif isinstance(v, (bool, np.bool_)):
                        ws.write(i, j, "Sí" if v else "No", fmt)
                    elif isinstance(v, (int, float, np.integer, np.floating)):
                        ws.write_number(i, j, float(v), fmt)
                    else:
                        ws.write(i, j, str(v), fmt)
            for j, col in enumerate(df.columns):
                muestras = [str(col)] + [
                    (f"{v:,.2f} €" if isinstance(v, (float, np.floating)) else
                     ("00/00/0000" if isinstance(v, (pd.Timestamp, datetime, date)) else str(v)))
                    for v in df[col].head(500).tolist()
                ]
                ws.set_column(j, j, max(min(max(len(s) for s in muestras) + 3, 60), 10))
            ws.set_row(fila0, 30)
            return fila0 + len(df) + 1

        def semaforo(ws, fila_ini, fila_fin, ncols, col_letra, colores):
            for texto, fmt in colores:
                ws.conditional_format(fila_ini, 0, fila_fin, ncols - 1, {
                    "type": "formula", "criteria": f'=${col_letra}{fila_ini + 1}="{texto}"', "format": fmt})

        # ---------------- Resumen_Ejecutivo ---------------- #
        ws = wb.add_worksheet("Resumen_Ejecutivo")
        ws.hide_gridlines(2)
        ws.write(0, 0, "Gestión de Contratos y Préstamos a Hosteleros", f_titulo)
        ws.write(1, 0, f"Generado el {datetime.now():%d/%m/%Y %H:%M}.  Fecha de referencia: "
                       f"{parametros.get('Fecha de referencia', '')}", f_sub)
        ind = [
            ("Contratos en cartera", kpis["n_contratos"], f_int),
            ("Contratos vencidos", kpis["n_vencidos"], f_int),
            ("Vencen en la ventana urgente", kpis["n_urgentes"], f_int),
            ("Vencen en la ventana próxima", kpis["n_proximos"], f_int),
            ("Vencen en la ventana de planificación", kpis["n_planificar"], f_int),
            ("Contratos prorrogados tácitamente", kpis["n_prorrogados"], f_int),
            ("Préstamos activos", kpis["n_activos"], f_int),
            ("Capital concedido (total histórico)", kpis["capital_concedido"], f_eur),
            ("Capital pendiente de recuperar", kpis["capital_pendiente"], f_eur_b),
            ("Capital pendiente en préstamos Crítico/Riesgo", kpis["capital_riesgo"], f_eur_b),
            ("Cuotas atrasadas (importe)", kpis["retraso_total"], f_eur),
            ("Saldo que quedaría al vencer el contrato", kpis["expuesto_total"], f_eur),
            ("Horas de revisión manual ahorradas (est.)", kpis["horas_ahorradas"], f_num1),
        ]
        if not pd.isna(kpis.get("rec_en_juego", np.nan)):
            ind.insert(6, ("Recaudación anual de contratos por renovar", kpis["rec_en_juego"], f_eur_b))
        ws.write(3, 0, "Indicador", f_head)
        ws.write(3, 1, "Valor", f_head)
        for i, (t, v, fmt) in enumerate(ind, start=4):
            ws.write(i, 0, t, f_txt_b)
            ws.write_number(i, 1, float(v), fmt)
        fila = 4 + len(ind) + 1
        ws.write(fila, 0, "Parámetros", f_txt_b)
        fila += 1
        for kk, v in parametros.items():
            ws.write(fila, 0, kk, f_txt)
            ws.write(fila, 1, str(v), f_txt)
            fila += 1
        ws.set_column(0, 0, 48)
        ws.set_column(1, 1, 22)

        # ---------------- Vencimientos ---------------- #
        ws2 = wb.add_worksheet("Vencimientos")
        ws2.write(0, 0, "Contratos vencidos y próximos a vencer", f_titulo)
        ws2.write(1, 0, parametros.get("Ventanas de aviso", ""), f_sub)
        if contratos_ev is None or contratos_ev.empty:
            ws2.write(3, 0, "No se ha cargado el listado de contratos.", f_txt_b)
        else:
            c = contratos_ev[contratos_ev["estado"] != VIGENTE]
            t = pd.DataFrame({
                "Estado": c["estado"], "Establecimiento": c["bar"], "Contrato": c["contrato"],
                "Ruta": c["ruta"], "Vencimiento": c["fin_efectivo"], "Días restantes": c["dias_restantes"],
                "Prórroga automática": c["prorroga"], "Prorrogado tácitamente": c["prorrogado"],
                "Límite preaviso": c["limite_preaviso"],
            })
            fmts = {"Vencimiento": f_fecha, "Días restantes": f_int, "Límite preaviso": f_fecha}
            if "rec_mensual" in c:
                t["Recaudación media mensual (€)"] = c["rec_mensual"]
                fmts["Recaudación media mensual (€)"] = f_eur
            for extra in ("gestion", "nota"):
                if extra in c:
                    t["Gestión" if extra == "gestion" else "Nota"] = c[extra]
            if t.empty:
                ws2.write(3, 0, "Ningún contrato vence en las ventanas de aviso. ✔", f_txt_b)
            else:
                fin = tabla(ws2, t, 3, fmts)
                semaforo(ws2, 4, fin - 1, len(t.columns), "A",
                         [(VENCIDO, f_granate), (URGENTE, f_rojo), (PROXIMO, f_ambar), (PLANIFICAR, f_azul)])
                ws2.autofilter(3, 0, fin - 1, len(t.columns) - 1)
                ws2.freeze_panes(4, 0)

        # ---------------- Prestamos ---------------- #
        ws3 = wb.add_worksheet("Prestamos")
        ws3.write(0, 0, "Préstamos a hosteleros: saldo, retrasos y riesgo", f_titulo)
        ws3.write(1, 0, parametros.get("Criterio préstamos", ""), f_sub)
        if prestamos_ev is None or prestamos_ev.empty:
            ws3.write(3, 0, "No se ha cargado el listado de préstamos.", f_txt_b)
        else:
            p = prestamos_ev
            t = pd.DataFrame({
                "Estado": p["estado"], "Establecimiento": p["bar"], "Préstamo": p["prestamo"],
                "Concesión": p["fecha"], "Importe (€)": p["importe"], "Cuota (€)": p["cuota"],
                "Nº cuotas": p["n_cuotas"], "Amortizado (€)": p["amortizado"], "% devuelto": p["pct_amortizado"],
                "Pendiente (€)": p["pendiente"], "Retraso (€)": p["retraso_eur"],
                "Cuotas atrasadas": p["retraso_cuotas"], "Fin previsto": p["fin_previsto"],
                "Vence contrato": p["fin_contrato"], "Saldo al vencer contrato (€)": p["expuesto_fin_contrato"],
                "Motivo": p["motivo"],
            })
            fmts = {"Concesión": f_fecha, "Importe (€)": f_eur, "Cuota (€)": f_eur, "Nº cuotas": f_int,
                    "Amortizado (€)": f_eur, "% devuelto": f_pct, "Pendiente (€)": f_eur_b,
                    "Retraso (€)": f_eur, "Cuotas atrasadas": f_num1, "Fin previsto": f_fecha,
                    "Vence contrato": f_fecha, "Saldo al vencer contrato (€)": f_eur}
            fin = tabla(ws3, t, 3, fmts)
            semaforo(ws3, 4, fin - 1, len(t.columns), "A",
                     [(P_CRITICO, f_rojo), (P_RIESGO, f_ambar)])
            ws3.conditional_format(4, 8, fin - 1, 8, {"type": "data_bar", "bar_color": "#60A5FA",
                                                      "min_type": "num", "min_value": 0,
                                                      "max_type": "num", "max_value": 1})
            ws3.autofilter(3, 0, fin - 1, len(t.columns) - 1)
            ws3.freeze_panes(4, 2)

        # ---------------- Calendario_Cobros ---------------- #
        ws4 = wb.add_worksheet("Calendario_Cobros")
        ws4.write(0, 0, "Previsión mensual de cuotas pendientes de cobro", f_titulo)
        if calendario is None or calendario.empty:
            ws4.write(3, 0, "No hay préstamos con saldo pendiente.", f_txt_b)
        else:
            piv = (calendario.pivot_table(index="mes", columns="bar", values="cuota", aggfunc="sum")
                             .fillna(0.0))
            piv.insert(0, "TOTAL MES", piv.sum(axis=1))
            piv = piv.reset_index().rename(columns={"mes": "Mes"})
            fmts = {c: f_eur for c in piv.columns if c != "Mes"}
            fmts["Mes"] = f_mes
            fmts["TOTAL MES"] = f_eur_b
            tabla(ws4, piv, 3, fmts)
            ws4.freeze_panes(4, 2)
            ws4.write(1, 0, "Suma por mes de las cuotas previstas (proyección a cuota constante desde la fecha "
                            "de referencia).", f_sub)

        for hoja in (ws, ws2, ws3, ws4):
            hoja.set_landscape()
            hoja.fit_to_pages(1, 0)

    return buffer.getvalue()

