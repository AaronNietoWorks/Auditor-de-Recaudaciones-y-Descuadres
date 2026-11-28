"""
analyzer.py
-----------
Lógica de negocio del Optimizador de Rutas y Averías (sin dependencias de Streamlit):

* Lectura robusta de Excel (con selección de hoja) y CSV exportados desde IPS-Maq+.
* Mapeo de columnas para dos listados (parque de máquinas / establecimientos y averías) con
  sugerencia automática y plantillas reutilizables en config_columnas.json.
* Geolocalización sin servicios externos: coordenadas del listado (lat/lon o «38.08, -0.72»),
  coordenadas corregidas a mano (SQLite) o, en su defecto, el centro de la población
  (tabla interna de municipios de la provincia de Alicante).
* Rutas: selección de paradas pendientes (días desde la última recaudación y averías abiertas),
  orden óptimo con vecino más cercano + 2-opt, ajuste a la jornada, comparación con el orden
  del listado (km, tiempo y € ahorrados) y reparto semanal por días/recaudadores.
* Averías por modelo: tasa anual por máquina, MTBF, tiempo de resolución, coste, días de
  parada, recaudación perdida, máquinas reincidentes y averías abiertas.
* KPIs y exportación del informe y la hoja de ruta a Excel multi-pestaña.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

CONFIG_PATH = Path(__file__).resolve().parent / "config_columnas.json"

# --------------------------------------------------------------------------- #
# 1. Definición de los listados y mapeo de columnas
# --------------------------------------------------------------------------- #
DATASETS: dict[str, dict] = {
    "parque": {
        "titulo": "Parque de máquinas / establecimientos",
        "hoja": "parque",
        "campos": {
            "bar":          {"etiqueta": "Establecimiento (código/nombre)", "obligatorio": True},
            "poblacion":    {"etiqueta": "Población / municipio",           "obligatorio": False},
            "direccion":    {"etiqueta": "Dirección",                       "obligatorio": False},
            "coordenadas":  {"etiqueta": "Coordenadas «lat, lon»",          "obligatorio": False},
            "lat":          {"etiqueta": "Latitud",                         "obligatorio": False},
            "lon":          {"etiqueta": "Longitud",                        "obligatorio": False},
            "ruta":         {"etiqueta": "Ruta / zona / recaudador",        "obligatorio": False},
            "orden":        {"etiqueta": "Orden de visita actual",          "obligatorio": False},
            "maquina":      {"etiqueta": "Máquina (nº serie / código)",     "obligatorio": False},
            "modelo":       {"etiqueta": "Modelo de máquina",               "obligatorio": False},
            "ultima_visita": {"etiqueta": "Fecha última recaudación",       "obligatorio": False},
            "frecuencia":   {"etiqueta": "Frecuencia de visita (días)",     "obligatorio": False},
            "rec_media":    {"etiqueta": "Recaudación media semanal (€)",   "obligatorio": False},
        },
        "sinonimos": {
            "bar": ["establecimiento", "nombre bar", "cod bar", "bar", "local", "cliente", "salon",
                    "hostelero", "nombre comercial"],
            "poblacion": ["poblacion", "municipio", "localidad", "ciudad", "pueblo", "plaza"],
            "direccion": ["direccion", "domicilio", "calle", "direccion establecimiento", "via"],
            "coordenadas": ["coordenadas", "coords", "gps", "ubicacion", "geolocalizacion", "lat lon",
                            "latlon"],
            "lat": ["latitud", "lat", "latitude", "coord y", "y"],
            "lon": ["longitud", "lon", "lng", "long", "longitude", "coord x", "x"],
            "ruta": ["ruta", "zona", "recaudador", "ruta recaudacion", "comercial", "sector"],
            "orden": ["orden ruta", "orden visita", "orden", "secuencia", "n orden", "posicion"],
            "maquina": ["n serie", "num serie", "numero serie", "serie", "cod maquina", "codigo maquina",
                        "maquina", "terminal", "n maquina", "matricula", "guia"],
            "modelo": ["modelo maquina", "modelo", "tipo maquina", "juego", "nombre maquina"],
            "ultima_visita": ["ultima recaudacion", "fecha ultima recaudacion", "f ultima recaudacion",
                              "ultima visita", "fecha ultima visita", "ult recaudacion", "ultima"],
            "frecuencia": ["frecuencia dias", "frecuencia visita", "frecuencia", "periodicidad", "cada dias",
                           "dias entre visitas"],
            "rec_media": ["recaudacion media semanal", "media semanal", "rec media", "recaudacion media",
                          "media recaudacion", "recaudacion semanal", "promedio"],
        },
    },
    "averias": {
        "titulo": "Averías / incidencias técnicas",
        "hoja": "aver",
        "campos": {
            "fecha":            {"etiqueta": "Fecha del aviso",                  "obligatorio": True},
            "maquina":          {"etiqueta": "Máquina (nº serie / código)",      "obligatorio": False},
            "modelo":           {"etiqueta": "Modelo de máquina",                "obligatorio": False},
            "bar":              {"etiqueta": "Establecimiento",                  "obligatorio": False},
            "tipo":             {"etiqueta": "Tipo de avería / pieza",           "obligatorio": False},
            "descripcion":      {"etiqueta": "Descripción",                      "obligatorio": False},
            "fecha_resolucion": {"etiqueta": "Fecha de resolución / cierre",     "obligatorio": False},
            "estado":           {"etiqueta": "Estado (abierta/cerrada)",         "obligatorio": False},
            "coste":            {"etiqueta": "Coste reparación (€)",             "obligatorio": False},
            "tecnico":          {"etiqueta": "Técnico",                          "obligatorio": False},
        },
        "sinonimos": {
            "fecha": ["fecha aviso", "f aviso", "fecha averia", "fecha incidencia", "fecha alta", "fecha entrada",
                      "fecha apertura", "fecha"],
            "maquina": ["n serie", "num serie", "numero serie", "serie", "cod maquina", "codigo maquina",
                        "maquina", "terminal", "n maquina", "matricula", "guia"],
            "modelo": ["modelo maquina", "modelo", "tipo maquina", "juego", "nombre maquina"],
            "bar": ["establecimiento", "nombre bar", "cod bar", "bar", "local", "cliente", "salon"],
            "tipo": ["tipo averia", "tipo incidencia", "averia", "pieza", "componente", "categoria", "motivo",
                     "tipo"],
            "descripcion": ["descripcion", "observaciones", "detalle", "comentario", "notas"],
            "fecha_resolucion": ["fecha resolucion", "f resolucion", "fecha cierre", "f cierre", "fecha reparacion",
                                 "fecha solucion", "resuelta", "cierre"],
            "estado": ["estado", "situacion", "estado averia"],
            "coste": ["coste reparacion", "coste", "importe reparacion", "importe", "precio", "total"],
            "tecnico": ["tecnico", "operario", "reparado por", "mecanico"],
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
                if ns and (ncol == ns or (len(ns) > 2 and re.search(rf"\b{re.escape(ns)}\b", ncol))):
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


def a_coordenada(serie: pd.Series) -> pd.Series:
    """Latitud/longitud: acepta '38,0849', '38.0849' o '-0.944'. No trata el punto como miles."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie.astype(float)
    return pd.to_numeric(serie.astype(str).str.strip().str.replace(",", ".", regex=False)
                         .str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")


def separar_coordenadas(serie: pd.Series) -> tuple[pd.Series, pd.Series]:
    """'38.0849, -0.9440' (formato que copia Google Maps) -> (lat, lon)."""
    def _par(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return (np.nan, np.nan)
        nums = re.findall(r"-?\d+(?:[.,]\d+)?", str(v))
        if len(nums) == 4:            # '38,08, -0,94' con coma decimal
            nums = [f"{nums[0]}.{nums[1]}", f"{nums[2]}.{nums[3]}"]
        if len(nums) < 2:
            return (np.nan, np.nan)
        try:
            return (float(nums[0].replace(",", ".")), float(nums[1].replace(",", ".")))
        except ValueError:
            return (np.nan, np.nan)
    pares = serie.map(_par)
    return pares.map(lambda p: p[0]).astype(float), pares.map(lambda p: p[1]).astype(float)


def a_fecha(serie: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(serie):
        return pd.to_datetime(serie).dt.normalize()
    return pd.to_datetime(serie, dayfirst=True, errors="coerce").dt.normalize()


def clave_bar(texto) -> str:
    """
    Clave para cruzar establecimientos entre listados distintos.
    Quita un código inicial tipo 'B001 - ' y normaliza acentos y mayúsculas.
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


# --------------------------------------------------------------------------- #
# 3. Municipios de la provincia de Alicante (centro aproximado, WGS84)
# --------------------------------------------------------------------------- #
# Se usan cuando el listado no trae coordenadas: todas las paradas de una población se sitúan en
# su centro y entre ellas se aplica un salto urbano mínimo. Para afinar, corrige las coordenadas
# de cada bar en la pestaña de ubicaciones (se guardan en SQLite y se conservan entre cargas).
MUNICIPIOS: dict[str, tuple[float, float]] = {
    # Vega Baja del Segura
    "Orihuela": (38.0849, -0.9440), "Orihuela Costa": (37.9330, -0.7280), "Torrevieja": (37.9787, -0.6822),
    "Rojales": (38.0880, -0.7246), "Ciudad Quesada": (38.0700, -0.7180), "Guardamar del Segura": (38.0897, -0.6550),
    "Almoradí": (38.1100, -0.7920), "Callosa de Segura": (38.1250, -0.8780), "Cox": (38.1420, -0.8880),
    "Catral": (38.1600, -0.8050), "Dolores": (38.1400, -0.7700), "Pilar de la Horadada": (37.8650, -0.7920),
    "San Miguel de Salinas": (37.9800, -0.7900), "Benejúzar": (38.0790, -0.8380), "Bigastro": (38.0620, -0.8980),
    "Jacarilla": (38.0590, -0.8640), "Redován": (38.1160, -0.9080), "Rafal": (38.1050, -0.8490),
    "Benijófar": (38.0790, -0.7370), "Formentera del Segura": (38.0860, -0.7460), "Algorfa": (38.0610, -0.7930),
    "Daya Nueva": (38.1100, -0.7600), "Daya Vieja": (38.1050, -0.7400), "San Fulgencio": (38.1050, -0.6990),
    "Los Montesinos": (38.0270, -0.7450), "Granja de Rocamora": (38.1500, -0.8960), "Albatera": (38.1790, -0.8700),
    "San Isidro": (38.1730, -0.8220), "Benferri": (38.1430, -0.9590), "La Mata": (38.0230, -0.6550),
    "Torremendo": (37.9900, -0.8900), "La Murada": (38.1850, -0.9550),
    # Bajo Vinalopó / Elche y litoral
    "Elche": (38.2669, -0.6983), "Elx": (38.2669, -0.6983), "Santa Pola": (38.1916, -0.5658),
    "Gran Alacant": (38.2260, -0.5200), "Crevillent": (38.2490, -0.8090), "Torrellano": (38.2950, -0.5870),
    "La Marina": (38.1450, -0.6400), "El Altet": (38.2680, -0.5490), "Arenales del Sol": (38.2490, -0.5170),
    # Alacantí
    "Alicante": (38.3452, -0.4810), "Alacant": (38.3452, -0.4810), "San Vicente del Raspeig": (38.3960, -0.5250),
    "Sant Joan d'Alacant": (38.4010, -0.4360), "El Campello": (38.4290, -0.3970), "Mutxamel": (38.4140, -0.4450),
    "Jijona": (38.5400, -0.5040), "Agost": (38.4400, -0.6380),
    # Vinalopó y otras comarcas
    "Aspe": (38.3450, -0.7670), "Novelda": (38.3850, -0.7680), "Monforte del Cid": (38.3800, -0.7290),
    "Elda": (38.4780, -0.7920), "Petrer": (38.4840, -0.7680), "Villena": (38.6350, -0.8650),
    "Sax": (38.5390, -0.8170), "Monóvar": (38.4380, -0.8400), "Pinoso": (38.4010, -1.0420),
    "Benidorm": (38.5410, -0.1220), "Villajoyosa": (38.5070, -0.2330), "Alcoy": (38.6980, -0.4740),
    "Altea": (38.5990, -0.0510), "Calp": (38.6440, 0.0450), "Dénia": (38.8400, 0.1060), "Jávea": (38.7890, 0.1660),
}
_MUNI_NORM = {_normalizar(k): v for k, v in MUNICIPIOS.items()}
_ALIAS_MUNI = {"elche elx": "elche", "alicante alacant": "alicante", "orihuela costa playa flamenca": "orihuela costa",
               "playa flamenca": "orihuela costa", "quesada": "ciudad quesada", "guardamar": "guardamar del segura",
               "callosa": "callosa de segura", "pilar horadada": "pilar de la horadada", "san vicente": "san vicente del raspeig",
               "sant vicent del raspeig": "san vicente del raspeig", "san juan de alicante": "sant joan d alacant",
               "la vila joiosa": "villajoyosa", "xabia": "javea", "denia": "denia", "calpe": "calp", "alcoi": "alcoy",
               "crevillente": "crevillent", "almoradi": "almoradi"}

# Límites amplios de la provincia para descartar coordenadas imposibles (lat/lon cambiadas, ceros...).
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 37.6, 39.1, -1.4, 0.4
BASE_DEFECTO = "Rojales"


def coords_poblacion(poblacion) -> tuple[float, float] | None:
    n = _normalizar(poblacion)
    if not n:
        return None
    n = _ALIAS_MUNI.get(n, n)
    if n in _MUNI_NORM:
        return _MUNI_NORM[n]
    for k, v in _MUNI_NORM.items():          # 'Orihuela (Alicante)', 'Torrevieja 03181'...
        if re.search(rf"\b{re.escape(k)}\b", n):
            return v
    return None


def coords_validas(lat, lon) -> bool:
    return (pd.notna(lat) and pd.notna(lon) and LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX)


# --------------------------------------------------------------------------- #
# 4. Aplicación del mapeo
# --------------------------------------------------------------------------- #
FRECUENCIA_DEFECTO = 7        # una recaudación por semana


def id_averia(fecha, maquina, bar, tipo, descripcion) -> str:
    base = "|".join(str(x) for x in (pd.Timestamp(fecha).date() if pd.notna(fecha) else "", maquina, clave_bar(bar),
                                      _normalizar(tipo), _normalizar(descripcion)))
    return hashlib.md5(base.encode()).hexdigest()[:16]


_ABIERTA = {"abierta", "abierto", "pendiente", "en curso", "en reparacion", "sin resolver", "activa", "nueva",
            "en espera", "esperando pieza", "pte"}


def aplicar_mapeo(dataset: str, df: pd.DataFrame, mapeo: dict) -> tuple[pd.DataFrame, list[str]]:
    """Renombra y tipa las columnas según el mapeo. Devuelve (df_limpio, avisos)."""
    defin = campos(dataset)
    faltan = [d["etiqueta"] for c, d in defin.items() if d["obligatorio"] and not mapeo.get(c)]
    if dataset == "parque" and not any(mapeo.get(c) for c in ("poblacion", "direccion", "coordenadas", "lat")):
        faltan.append("Población, Dirección o Coordenadas (al menos una, para situar el bar en el mapa)")
    if dataset == "parque" and mapeo.get("lat") and not mapeo.get("lon"):
        faltan.append("Longitud (has indicado la latitud)")
    if dataset == "averias" and not mapeo.get("maquina") and not mapeo.get("modelo"):
        faltan.append("Máquina o Modelo (al menos una)")
    if faltan:
        raise ValueError("Faltan columnas obligatorias: " + ", ".join(faltan))

    def col(campo):
        return df[mapeo[campo]] if mapeo.get(campo) else pd.Series([np.nan] * len(df), index=df.index)

    avisos: list[str] = []
    if dataset == "parque":
        lat, lon = a_coordenada(col("lat")), a_coordenada(col("lon"))
        if mapeo.get("coordenadas"):
            clat, clon = separar_coordenadas(col("coordenadas"))
            lat, lon = lat.fillna(clat), lon.fillna(clon)
        # Lat/lon intercambiadas (error típico al exportar): 38 está en lon y -0,7 en lat.
        cambiadas = lat.between(LON_MIN, LON_MAX) & lon.between(LAT_MIN, LAT_MAX) & ~lat.between(LAT_MIN, LAT_MAX)
        if cambiadas.any():
            lat, lon = lat.where(~cambiadas, lon), lon.where(~cambiadas, lat)
            avisos.append(f"{int(cambiadas.sum())} filas con latitud y longitud intercambiadas: corregidas.")
        fuera = (lat.notna() | lon.notna()) & ~pd.Series([coords_validas(a, b) for a, b in zip(lat, lon)],
                                                        index=df.index)
        if fuera.any():
            avisos.append(f"{int(fuera.sum())} coordenadas fuera de la provincia de Alicante: se ignoran y se usa la "
                          "población.")
            lat, lon = lat.mask(fuera), lon.mask(fuera)
        out = pd.DataFrame({
            "bar": _texto(col("bar")),
            "poblacion": _texto(col("poblacion")) if mapeo.get("poblacion") else "",
            "direccion": _texto(col("direccion")) if mapeo.get("direccion") else "",
            "lat": lat, "lon": lon,
            "ruta": _texto(col("ruta")) if mapeo.get("ruta") else "",
            "orden": a_numero(col("orden")),
            "maquina": _texto(col("maquina")) if mapeo.get("maquina") else "",
            "modelo": _texto(col("modelo")) if mapeo.get("modelo") else "",
            "ultima_visita": a_fecha(col("ultima_visita")),
            "frecuencia": a_numero(col("frecuencia")),
            "rec_media": a_numero(col("rec_media")),
        })
        out["ruta"] = out["ruta"].replace("", "Sin ruta")
        invalidas = out["bar"] == ""
        motivo = "sin establecimiento"
        unica = ["bar", "maquina"] if mapeo.get("maquina") else None
        if not mapeo.get("ultima_visita"):
            avisos.append("Sin «Fecha última recaudación»: todos los bares se consideran pendientes de visita.")
    else:  # averias
        out = pd.DataFrame({
            "fecha": a_fecha(col("fecha")),
            "maquina": _texto(col("maquina")) if mapeo.get("maquina") else "",
            "modelo": _texto(col("modelo")) if mapeo.get("modelo") else "",
            "bar": _texto(col("bar")) if mapeo.get("bar") else "",
            "tipo": _texto(col("tipo")) if mapeo.get("tipo") else "",
            "descripcion": _texto(col("descripcion")) if mapeo.get("descripcion") else "",
            "fecha_resolucion": a_fecha(col("fecha_resolucion")),
            "estado": _texto(col("estado")) if mapeo.get("estado") else "",
            "coste": a_numero(col("coste")),
            "tecnico": _texto(col("tecnico")) if mapeo.get("tecnico") else "",
        })
        out["tipo"] = out["tipo"].replace("", "Sin clasificar")
        est = out["estado"].map(_normalizar)
        out["abierta"] = np.where(out["estado"] != "", est.isin(_ABIERTA) | est.str.contains("pend"),
                                  out["fecha_resolucion"].isna())
        out.loc[out["abierta"].astype(bool), "fecha_resolucion"] = pd.NaT
        out["abierta"] = out["abierta"].astype(bool)
        invalidas = out["fecha"].isna() | ((out["maquina"] == "") & (out["modelo"] == ""))
        motivo = "sin fecha o sin máquina/modelo"
        unica = None
        if not mapeo.get("fecha_resolucion") and not mapeo.get("estado"):
            avisos.append("Sin fecha de resolución ni estado: todas las averías se consideran abiertas.")

    if invalidas.any():
        avisos.append(f"Se descartaron {int(invalidas.sum())} filas {motivo} (totales, subtotales o filas vacías).")
        out = out[~invalidas]
    if unica:
        dup = out.duplicated(unica, keep="last")
        if dup.any():
            avisos.append(f"{int(dup.sum())} filas duplicadas: se conserva la última.")
            out = out[~dup]
    out = out.copy()
    if dataset == "averias":
        out["id"] = [id_averia(*r) for r in out[["fecha", "maquina", "bar", "tipo", "descripcion"]]
                     .itertuples(index=False, name=None)]
        dup = out.duplicated("id", keep="last")
        if dup.any():
            avisos.append(f"{int(dup.sum())} averías repetidas en el archivo: se conserva la última.")
            out = out[~dup]
    out["clave_bar"] = out["bar"].map(clave_bar)
    return out.reset_index(drop=True), avisos


# --------------------------------------------------------------------------- #
# 5. Establecimientos: agregación por bar y geolocalización
# --------------------------------------------------------------------------- #
EXACTA, MANUAL, POBLACION, SIN_UBICAR = "Exacta (listado)", "Corregida a mano", "Centro de la población", "Sin ubicar"


def establecimientos(parque: pd.DataFrame, ubicaciones: pd.DataFrame | None = None,
                     fecha_ref: date | None = None, frecuencia_defecto: int = FRECUENCIA_DEFECTO) -> pd.DataFrame:
    """Una fila por bar con su ubicación, máquinas, modelos, frecuencia y días desde la última visita."""
    if parque is None or parque.empty:
        return pd.DataFrame()
    p = parque.copy()
    p["_orden_fila"] = np.arange(len(p))
    g = p.groupby("clave_bar", sort=False)
    est = g.agg(
        bar=("bar", "first"), poblacion=("poblacion", "first"), direccion=("direccion", "first"),
        lat=("lat", "first"), lon=("lon", "first"), ruta=("ruta", "first"), orden=("orden", "min"),
        n_maquinas=("maquina", lambda s: max(int((s != "").sum()), 1)),
        modelos=("modelo", lambda s: ", ".join(sorted({m for m in s if m}))),
        ultima_visita=("ultima_visita", "max"), frecuencia=("frecuencia", "min"),
        rec_media=("rec_media", lambda s: s.sum(min_count=1)), orden_fila=("_orden_fila", "min"),
    ).reset_index()
    est["frecuencia"] = est["frecuencia"].where(est["frecuencia"] > 0).fillna(frecuencia_defecto)
    est["precision"] = np.where(est[["lat", "lon"]].notna().all(axis=1), EXACTA, SIN_UBICAR)

    if ubicaciones is not None and not ubicaciones.empty:
        u = ubicaciones.set_index("clave_bar")
        man = est["clave_bar"].isin(u.index)
        est.loc[man, "lat"] = est.loc[man, "clave_bar"].map(u["lat"]).values
        est.loc[man, "lon"] = est.loc[man, "clave_bar"].map(u["lon"]).values
        est.loc[man, "precision"] = MANUAL

    sin = est["precision"] == SIN_UBICAR
    for i in est.index[sin]:
        c = coords_poblacion(est.at[i, "poblacion"]) or coords_poblacion(est.at[i, "direccion"])
        if c:
            est.at[i, "lat"], est.at[i, "lon"] = c
            est.at[i, "precision"] = POBLACION
    if fecha_ref is not None:
        ref = pd.Timestamp(fecha_ref)
        est["dias_sin_visita"] = (ref - est["ultima_visita"]).dt.days
    else:
        est["dias_sin_visita"] = np.nan
    est["retraso"] = est["dias_sin_visita"] - est["frecuencia"]
    return est


# --------------------------------------------------------------------------- #
# 6. Distancias y optimización de rutas
# --------------------------------------------------------------------------- #
FACTOR_CARRETERA = 1.30       # km por carretera / km en línea recta (comarca con autovía y red local)
SALTO_URBANO_KM = 0.8         # distancia mínima entre dos paradas distintas (misma calle o mismo pueblo)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def matriz_distancias(lats, lons, factor: float = FACTOR_CARRETERA, salto: float = SALTO_URBANO_KM) -> np.ndarray:
    lats, lons = np.asarray(lats, float), np.asarray(lons, float)
    d = haversine_km(lats[:, None], lons[:, None], lats[None, :], lons[None, :]) * factor
    d = np.maximum(d, salto)
    np.fill_diagonal(d, 0.0)
    return d


def longitud_ruta(orden: list[int], d: np.ndarray, cerrar: bool = True) -> float:
    """orden incluye el nodo 0 (base) al principio."""
    total = sum(d[orden[i], orden[i + 1]] for i in range(len(orden) - 1))
    if cerrar and len(orden) > 1:
        total += d[orden[-1], orden[0]]
    return float(total)


def _vecino_mas_cercano(d: np.ndarray) -> list[int]:
    n = len(d)
    ruta, libres = [0], set(range(1, n))
    while libres:
        ult = ruta[-1]
        sig = min(libres, key=lambda j: d[ult, j])
        ruta.append(sig)
        libres.remove(sig)
    return ruta


def _dos_opt(ruta: list[int], d: np.ndarray, cerrar: bool = True) -> list[int]:
    """Mejora 2-opt: invierte tramos mientras acorte la ruta. El nodo 0 (base) queda fijo al inicio."""
    mejor = ruta[:]
    n = len(mejor)
    if n < 4:
        return mejor
    mejora = True
    while mejora:
        mejora = False
        for i in range(1, n - 1):
            for k in range(i + 1, n):
                a, b = mejor[i - 1], mejor[i]
                c = mejor[k]
                e = mejor[(k + 1) % n] if (cerrar or k + 1 < n) else None
                antes = d[a, b] + (d[c, e] if e is not None else 0.0)
                despues = d[a, c] + (d[b, e] if e is not None else 0.0)
                if despues < antes - 1e-9:
                    mejor[i:k + 1] = mejor[i:k + 1][::-1]
                    mejora = True
    return mejor


def _or_opt(ruta: list[int], d: np.ndarray, cerrar: bool = True) -> list[int]:
    """Mueve segmentos de 1-3 paradas a otra posición si acorta la ruta."""
    mejor = ruta[:]
    coste = longitud_ruta(mejor, d, cerrar)
    mejora = True
    while mejora:
        mejora = False
        for tam in (1, 2, 3):
            for i in range(1, len(mejor) - tam + 1):
                seg = mejor[i:i + tam]
                resto = mejor[:i] + mejor[i + tam:]
                for j in range(1, len(resto) + 1):
                    if j == i:
                        continue
                    for s in (seg, seg[::-1]):
                        cand = resto[:j] + s + resto[j:]
                        c = longitud_ruta(cand, d, cerrar)
                        if c < coste - 1e-9:
                            mejor, coste, mejora = cand, c, True
                            break
                    if mejora:
                        break
                if mejora:
                    break
            if mejora:
                break
    return mejor


def optimizar_orden(d: np.ndarray, cerrar: bool = True) -> list[int]:
    """Vecino más cercano + 2-opt + or-opt. Devuelve índices empezando por 0 (base)."""
    if len(d) <= 2:
        return list(range(len(d)))
    ruta = _vecino_mas_cercano(d)
    ruta = _dos_opt(ruta, d, cerrar)
    if len(d) <= 45:              # or-opt es más lento; con rutas diarias normales sobra
        ruta = _or_opt(ruta, d, cerrar)
        ruta = _dos_opt(ruta, d, cerrar)
    return ruta


def ruta_detallada(paradas: pd.DataFrame, base: tuple[float, float], orden: list[int], d: np.ndarray,
                   velocidad: float, min_parada: float, min_averia: float, hora_salida: str = "08:00",
                   cerrar: bool = True) -> pd.DataFrame:
    """Tabla parada a parada con km, minutos y hora estimada de llegada. `orden` incluye el 0."""
    h, m = (int(x) for x in hora_salida.split(":"))
    t = h * 60 + m
    filas, km_acum = [], 0.0
    for pos, nodo in enumerate(orden[1:], start=1):
        prev = orden[pos - 1]
        km = float(d[prev, nodo])
        km_acum += km
        t += km / velocidad * 60
        p = paradas.iloc[nodo - 1]
        servicio = min_parada + (min_averia if p.get("averias_abiertas", 0) > 0 else 0)
        filas.append({**p.to_dict(), "parada": pos, "km_tramo": km, "km_acum": km_acum,
                      "llegada": f"{int(t // 60) % 24:02d}:{int(t % 60):02d}", "min_servicio": servicio})
        t += servicio
    det = pd.DataFrame(filas)
    if cerrar and len(orden) > 1:
        km = float(d[orden[-1], 0])
        km_acum += km
        t += km / velocidad * 60
    det.attrs["km_total"] = km_acum
    det.attrs["regreso"] = f"{int(t // 60) % 24:02d}:{int(t % 60):02d}"
    det.attrs["minutos_total"] = t - (h * 60 + m)
    return det


def minutos_ruta(km: float, paradas: pd.DataFrame, velocidad: float, min_parada: float, min_averia: float) -> float:
    con_averia = int((paradas.get("averias_abiertas", pd.Series(0, index=paradas.index)) > 0).sum())
    return km / velocidad * 60 + len(paradas) * min_parada + con_averia * min_averia


def candidatas(est: pd.DataFrame, averias_abiertas: pd.DataFrame | None, rutas: list[str] | None,
               margen_dias: int = 0, incluir_todas: bool = False) -> pd.DataFrame:
    """Paradas del día: bares con la recaudación vencida (o a `margen_dias` de vencer) y bares con averías abiertas."""
    e = est.copy()
    if rutas:
        e = e[e["ruta"].isin(rutas)]
    if averias_abiertas is not None and not averias_abiertas.empty:
        cnt = averias_abiertas.groupby("clave_bar").size()
        e["averias_abiertas"] = e["clave_bar"].map(cnt).fillna(0).astype(int)
    else:
        e["averias_abiertas"] = 0
    sin_fecha = e["dias_sin_visita"].isna()
    toca = sin_fecha | (e["retraso"] >= -margen_dias)
    e["motivo"] = np.select(
        [toca & (e["averias_abiertas"] > 0), e["averias_abiertas"] > 0, sin_fecha, toca],
        ["Recaudar + avería", "Avería", "Recaudar", "Recaudar"], default="Recaudar (adelantada)")
    if not incluir_todas:
        e = e[toca | (e["averias_abiertas"] > 0)]
    # Prioridad: averías (máquina parada = dinero perdido), luego retraso y dinero acumulado.
    acumulado = (e["rec_media"].fillna(0) / 7 * e["dias_sin_visita"].fillna(e["frecuencia"]))
    e["efectivo_estimado"] = acumulado.where(e["rec_media"].notna())
    e["prioridad"] = (e["averias_abiertas"] * 1000 + e["retraso"].fillna(0).clip(lower=-30) * 10
                      + acumulado / 100)
    return e.sort_values("prioridad", ascending=False).reset_index(drop=True)


def planificar_dia(cands: pd.DataFrame, base: tuple[float, float], jornada_min: float, velocidad: float,
                   min_parada: float, min_averia: float, max_paradas: int, cerrar: bool = True,
                   factor: float = FACTOR_CARRETERA) -> dict:
    """
    Elige y ordena las paradas del día. Si no caben en la jornada, se quitan las de menor prioridad
    (nunca antes que una con avería) y se vuelve a optimizar.
    """
    ubic = cands[cands[["lat", "lon"]].notna().all(axis=1)].copy()
    sin_ubicar = cands[cands[["lat", "lon"]].isna().any(axis=1)].copy()
    elegidas = ubic.head(max_paradas).copy()
    fuera = ubic.iloc[max_paradas:].copy()
    while True:
        lats = [base[0]] + elegidas["lat"].tolist()
        lons = [base[1]] + elegidas["lon"].tolist()
        d = matriz_distancias(lats, lons, factor)
        orden = optimizar_orden(d, cerrar)
        km = longitud_ruta(orden, d, cerrar)
        minutos = minutos_ruta(km, elegidas, velocidad, min_parada, min_averia)
        if minutos <= jornada_min or len(elegidas) <= 1:
            break
        # Quita la parada de menor prioridad (la última, ya que están ordenadas por prioridad)
        fuera = pd.concat([elegidas.tail(1), fuera])
        elegidas = elegidas.iloc[:-1]
    return {"paradas": elegidas.reset_index(drop=True), "orden": orden, "d": d, "km": km, "minutos": minutos,
            "no_caben": fuera.reset_index(drop=True), "sin_ubicar": sin_ubicar.reset_index(drop=True)}


def orden_listado(paradas: pd.DataFrame) -> list[int]:
    """Orden en que aparecen en el listado de IPS-Maq+ (o la columna «Orden de visita»), con la base al inicio."""
    clave = paradas["orden"].fillna(1e9) * 1e5 + paradas["orden_fila"]
    return [0] + [int(i) + 1 for i in np.argsort(clave.to_numpy(), kind="stable")]


def comparar_con_listado(plan: dict, cerrar: bool = True) -> dict:
    p, d = plan["paradas"], plan["d"]
    if p.empty:
        return {"km_listado": 0.0, "km_optimo": 0.0, "ahorro_km": 0.0, "ahorro_pct": 0.0}
    km_l = longitud_ruta(orden_listado(p), d, cerrar)
    km_o = plan["km"]
    return {"km_listado": km_l, "km_optimo": km_o, "ahorro_km": max(km_l - km_o, 0.0),
            "ahorro_pct": max(km_l - km_o, 0.0) / km_l if km_l else 0.0}


def reparto_semanal(est: pd.DataFrame, base: tuple[float, float], n_dias: int, velocidad: float,
                    min_parada: float, cerrar: bool = True, factor: float = FACTOR_CARRETERA,
                    rutas: list[str] | None = None) -> pd.DataFrame:
    """
    Reparte todos los bares en `n_dias` rutas compactas (barrido angular desde la base, equilibrado por tiempo de
    trabajo) y optimiza el orden de cada día. Devuelve una fila por bar con `dia` y `parada`.
    """
    e = est[est[["lat", "lon"]].notna().all(axis=1)].copy()
    if rutas:
        e = e[e["ruta"].isin(rutas)]
    if e.empty or n_dias < 1:
        return pd.DataFrame()
    dist_base = haversine_km(base[0], base[1], e["lat"].to_numpy(), e["lon"].to_numpy()) * factor
    # Tiempo de cada parada = servicio + ida/vuelta prorrateada (los lejanos pesan más).
    e["_peso"] = min_parada + dist_base / velocidad * 60 * 0.5
    ang = np.arctan2(e["lat"].to_numpy() - base[0], (e["lon"].to_numpy() - base[1]) * math.cos(math.radians(base[0])))
    e["_ang"] = ang
    # Empezar el barrido en el mayor hueco angular, para no partir un grupo de pueblos vecinos.
    orden_ang = np.sort(ang)
    huecos = np.diff(np.concatenate([orden_ang, [orden_ang[0] + 2 * np.pi]]))
    inicio = orden_ang[(int(np.argmax(huecos)) + 1) % len(orden_ang)]
    e["_ang"] = (ang - inicio) % (2 * np.pi)
    e = e.sort_values(["_ang", "_peso"]).reset_index(drop=True)
    objetivo = e["_peso"].sum() / n_dias
    acum = e["_peso"].cumsum() - e["_peso"] / 2
    e["dia"] = np.minimum((acum // objetivo).astype(int), n_dias - 1) + 1
    filas = []
    for dia, grupo in e.groupby("dia"):
        grupo = grupo.reset_index(drop=True)
        d = matriz_distancias([base[0]] + grupo["lat"].tolist(), [base[1]] + grupo["lon"].tolist(), factor)
        orden = optimizar_orden(d, cerrar)
        km = longitud_ruta(orden, d, cerrar)
        km_l = longitud_ruta(orden_listado(grupo), d, cerrar)
        for pos, nodo in enumerate(orden[1:], start=1):
            fila = grupo.iloc[nodo - 1].to_dict()
            fila.update({"parada": pos, "km_dia": km, "km_listado_dia": km_l,
                         "km_tramo": float(d[orden[pos - 1], nodo]),
                         "min_dia": km / velocidad * 60 + len(grupo) * min_parada})
            filas.append(fila)
    r = pd.DataFrame(filas).drop(columns=["_peso", "_ang"])
    return r.sort_values(["dia", "parada"]).reset_index(drop=True)


DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def enlaces_google_maps(base: tuple[float, float], paradas: pd.DataFrame, cerrar: bool = True,
                        max_por_tramo: int = 9) -> list[str]:
    """Enlaces de Google Maps (navegación) en tramos de 9 paradas, el máximo de waypoints de la versión web."""
    puntos = [f"{la:.6f},{lo:.6f}" for la, lo in zip(paradas["lat"], paradas["lon"])]
    origen = f"{base[0]:.6f},{base[1]:.6f}"
    enlaces, i = [], 0
    while i < len(puntos):
        tramo = puntos[i:i + max_por_tramo + 1]
        ultimo = i + len(tramo) >= len(puntos)
        destino = origen if (ultimo and cerrar) else tramo[-1]
        intermedios = tramo if (ultimo and cerrar) else tramo[:-1]
        url = ("https://www.google.com/maps/dir/?api=1&travelmode=driving"
               f"&origin={quote(origen)}&destination={quote(destino)}")
        if intermedios:
            url += "&waypoints=" + quote("|".join(intermedios))
        enlaces.append(url)
        origen = tramo[-1]
        i += len(tramo)
    return enlaces


# --------------------------------------------------------------------------- #
# 7. Averías por modelo
# --------------------------------------------------------------------------- #
FIABLE, VIGILAR, PROBLEMATICO, POCOS_DATOS = "Fiable", "Vigilar", "Problemático", "Pocos datos"
ESTADOS_MODELO = [PROBLEMATICO, VIGILAR, FIABLE, POCOS_DATOS]
COLOR_MODELO = {PROBLEMATICO: "#DC2626", VIGILAR: "#F59E0B", FIABLE: "#16A34A", POCOS_DATOS: "#94A3B8"}
SIN_MODELO = "Sin modelo"


def completar_averias(av: pd.DataFrame, parque: pd.DataFrame | None, fecha_ref: date) -> pd.DataFrame:
    """Rellena modelo y establecimiento desde el parque (por nº de máquina) y calcula días de resolución."""
    a = av.copy()
    if parque is not None and not parque.empty and (parque["maquina"] != "").any():
        pm = parque[parque["maquina"] != ""].drop_duplicates("maquina", keep="last").set_index("maquina")
        falta_mod = (a["modelo"] == "") & a["maquina"].isin(pm.index)
        a.loc[falta_mod, "modelo"] = a.loc[falta_mod, "maquina"].map(pm["modelo"])
        falta_bar = (a["bar"] == "") & a["maquina"].isin(pm.index)
        a.loc[falta_bar, "bar"] = a.loc[falta_bar, "maquina"].map(pm["bar"])
        a.loc[falta_bar, "clave_bar"] = a.loc[falta_bar, "bar"].map(clave_bar)
    a["modelo"] = a["modelo"].replace("", SIN_MODELO).fillna(SIN_MODELO)
    ref = pd.Timestamp(fecha_ref)
    fin = a["fecha_resolucion"].where(~a["abierta"], ref)
    a["dias_resolucion"] = (fin - a["fecha"]).dt.days.clip(lower=0)
    a["dias_abierta"] = np.where(a["abierta"], (ref - a["fecha"]).dt.days, np.nan)
    return a


def analizar_modelos(av: pd.DataFrame, parque: pd.DataFrame | None, desde: date, hasta: date,
                     umbral_vigilar: float = 1.15, umbral_problema: float = 1.5, min_maquinas: int = 2) -> pd.DataFrame:
    """Tabla por modelo: parque, averías, tasa anual por máquina, MTBF, resolución, coste y recaudación perdida."""
    a = av[(av["fecha"] >= pd.Timestamp(desde)) & (av["fecha"] <= pd.Timestamp(hasta))].copy()
    dias = max((pd.Timestamp(hasta) - pd.Timestamp(desde)).days + 1, 1)
    if parque is not None and not parque.empty and (parque["modelo"] != "").any():
        pq = parque[parque["modelo"] != ""]
        n_maq = (pq.assign(_m=np.where(pq["maquina"] != "", pq["maquina"], pq["clave_bar"]))
                 .groupby("modelo")["_m"].nunique())
        rec_dia = pq.groupby("modelo")["rec_media"].mean() / 7
    else:
        n_maq = a[a["maquina"] != ""].groupby("modelo")["maquina"].nunique()
        rec_dia = pd.Series(dtype=float)
    if a.empty and n_maq.empty:
        return pd.DataFrame()
    g = a.groupby("modelo")
    t = pd.DataFrame({
        "averias": g.size(), "abiertas": g["abierta"].sum(),
        "dias_resolucion": g["dias_resolucion"].mean(), "dias_parada": g["dias_resolucion"].sum(),
        "coste": g["coste"].sum(min_count=1),
        "tipo_principal": g["tipo"].agg(lambda s: s.value_counts().index[0] if len(s) else ""),
        "maquinas_con_averia": g["maquina"].agg(lambda s: s[s != ""].nunique()),
    })
    t = t.reindex(t.index.union(n_maq.index))
    t["averias"] = t["averias"].fillna(0).astype(int)
    t["abiertas"] = t["abiertas"].fillna(0).astype(int)
    t["n_maquinas"] = n_maq.reindex(t.index)
    t["n_maquinas"] = t["n_maquinas"].fillna(t["maquinas_con_averia"]).fillna(0).astype(int)
    anios = dias / 365.0
    t["tasa_anual"] = np.where(t["n_maquinas"] > 0, t["averias"] / t["n_maquinas"].clip(lower=1) / anios, np.nan)
    t["mtbf_dias"] = np.where(t["averias"] > 0, t["n_maquinas"] * dias / t["averias"].clip(lower=1), np.nan)
    t["coste_por_maquina"] = t["coste"] / t["n_maquinas"].replace(0, np.nan)
    t["rec_perdida"] = t["dias_parada"].fillna(0) * rec_dia.reindex(t.index)
    media = t["averias"].sum() / max(t["n_maquinas"].sum(), 1) / anios
    t["vs_media"] = t["tasa_anual"] / media if media > 0 else np.nan
    t["estado"] = np.select(
        [t["n_maquinas"] < min_maquinas, t["vs_media"] >= umbral_problema, t["vs_media"] >= umbral_vigilar],
        [POCOS_DATOS, PROBLEMATICO, VIGILAR], default=FIABLE)
    t.attrs["tasa_media"] = media
    t.attrs["dias"] = dias
    t = t.reset_index().rename(columns={"index": "modelo"})
    orden = {e: i for i, e in enumerate(ESTADOS_MODELO)}
    return t.sort_values(["estado", "tasa_anual"], key=lambda s: s.map(orden) if s.name == "estado" else -s
                         ).reset_index(drop=True)


def maquinas_reincidentes(av: pd.DataFrame, fecha_ref: date, ventana_dias: int = 90, minimo: int = 3) -> pd.DataFrame:
    a = av[(av["maquina"] != "") & (av["fecha"] > pd.Timestamp(fecha_ref) - pd.Timedelta(days=ventana_dias))
           & (av["fecha"] <= pd.Timestamp(fecha_ref))]
    if a.empty:
        return pd.DataFrame(columns=["maquina", "modelo", "bar", "averias", "tipos", "ultima", "coste", "abiertas"])
    g = a.sort_values("fecha").groupby("maquina")
    r = pd.DataFrame({
        "modelo": g["modelo"].last(), "bar": g["bar"].last(), "averias": g.size(),
        "tipos": g["tipo"].agg(lambda s: ", ".join(f"{k} ×{v}" if v > 1 else k
                                                   for k, v in s.value_counts().items())),
        "ultima": g["fecha"].max(), "coste": g["coste"].sum(min_count=1), "abiertas": g["abierta"].sum(),
    }).reset_index()
    return r[r["averias"] >= minimo].sort_values(["averias", "ultima"], ascending=False).reset_index(drop=True)


def averias_mensuales(av: pd.DataFrame, desde: date, hasta: date, top: int = 6) -> pd.DataFrame:
    a = av[(av["fecha"] >= pd.Timestamp(desde)) & (av["fecha"] <= pd.Timestamp(hasta))].copy()
    if a.empty:
        return pd.DataFrame(columns=["mes", "modelo", "averias"])
    principales = a["modelo"].value_counts().head(top).index
    a["modelo"] = np.where(a["modelo"].isin(principales), a["modelo"], "Otros")
    a["mes"] = a["fecha"].dt.to_period("M").dt.to_timestamp()
    return a.groupby(["mes", "modelo"]).size().rename("averias").reset_index()


# --------------------------------------------------------------------------- #
# 8. KPIs y exportación
# --------------------------------------------------------------------------- #
def calcular_kpis(est: pd.DataFrame | None, plan: dict | None, comp: dict | None, modelos: pd.DataFrame | None,
                  av_periodo: pd.DataFrame | None, reincidentes: pd.DataFrame | None, coste_km: float,
                  dias_ruta_anio: int, min_planificacion: float) -> dict:
    k: dict = {}
    if est is not None and not est.empty:
        k["n_bares"] = len(est)
        k["n_maquinas"] = int(est["n_maquinas"].sum())
        k["n_rutas"] = est["ruta"].nunique()
        k["pct_ubicados"] = float(est[["lat", "lon"]].notna().all(axis=1).mean())
        k["n_exactas"] = int(est["precision"].isin([EXACTA, MANUAL]).sum())
        k["n_atrasados"] = int((est["retraso"] > 0).sum())
    if plan is not None:
        k["paradas_dia"] = len(plan["paradas"])
        k["km_dia"] = plan["km"]
        k["min_dia"] = plan["minutos"]
        k["no_caben"] = len(plan["no_caben"])
    if comp is not None:
        k.update(comp)
        k["ahorro_eur_dia"] = comp["ahorro_km"] * coste_km
        k["ahorro_km_anio"] = comp["ahorro_km"] * dias_ruta_anio
        k["ahorro_eur_anio"] = comp["ahorro_km"] * coste_km * dias_ruta_anio
    k["horas_planificacion_anio"] = min_planificacion * dias_ruta_anio / 60
    if av_periodo is not None and not av_periodo.empty:
        k["n_averias"] = len(av_periodo)
        k["n_abiertas"] = int(av_periodo["abierta"].sum())
        k["coste_averias"] = float(av_periodo["coste"].sum())
        k["dias_resolucion"] = float(av_periodo.loc[~av_periodo["abierta"], "dias_resolucion"].mean())
    if modelos is not None and not modelos.empty:
        k["n_modelos"] = len(modelos)
        k["n_problematicos"] = int((modelos["estado"] == PROBLEMATICO).sum())
        k["rec_perdida"] = float(modelos["rec_perdida"].sum(min_count=1)) if modelos["rec_perdida"].notna().any() \
            else np.nan
        k["tasa_media"] = modelos.attrs.get("tasa_media", np.nan)
    if reincidentes is not None:
        k["n_reincidentes"] = len(reincidentes)
    return k


def exportar_excel(hojas: dict[str, pd.DataFrame], resumen: list[tuple[str, object, str]], parametros: dict,
                   titulo: str) -> bytes:
    """Excel con una hoja de resumen (indicador, valor) y una hoja por tabla."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter", datetime_format="dd/mm/yyyy") as w:
        wb = w.book
        f_tit = wb.add_format({"bold": True, "font_size": 15, "font_color": "#0F4C81"})
        f_sub = wb.add_format({"italic": True, "font_color": "#64748B"})
        f_head = wb.add_format({"bold": True, "bg_color": "#0F4C81", "font_color": "#FFFFFF", "border": 1,
                                "text_wrap": True, "valign": "vcenter"})
        f_txt = wb.add_format({"border": 1})
        f_b = wb.add_format({"border": 1, "bold": True})
        fmts = {"eur": wb.add_format({"border": 1, "num_format": "#,##0.00 €"}),
                "int": wb.add_format({"border": 1, "num_format": "#,##0"}),
                "num1": wb.add_format({"border": 1, "num_format": "#,##0.0"}),
                "pct": wb.add_format({"border": 1, "num_format": "0.0 %"}),
                "txt": f_txt}
        ws = wb.add_worksheet("Resumen")
        ws.hide_gridlines(2)
        ws.write(0, 0, titulo, f_tit)
        ws.write(1, 0, f"Generado el {datetime.now():%d/%m/%Y %H:%M}", f_sub)
        ws.write(3, 0, "Indicador", f_head)
        ws.write(3, 1, "Valor", f_head)
        fila = 4
        for etiqueta, valor, tipo in resumen:
            ws.write(fila, 0, etiqueta, f_b)
            if valor is None or (isinstance(valor, float) and np.isnan(valor)):
                ws.write(fila, 1, "—", f_txt)
            elif tipo == "txt":
                ws.write(fila, 1, str(valor), f_txt)
            else:
                ws.write_number(fila, 1, float(valor), fmts[tipo])
            fila += 1
        fila += 1
        ws.write(fila, 0, "Parámetros", f_b)
        for kk, v in parametros.items():
            fila += 1
            ws.write(fila, 0, kk, f_txt)
            ws.write(fila, 1, str(v), f_txt)
        ws.set_column(0, 0, 50)
        ws.set_column(1, 1, 24)
        for nombre, df in hojas.items():
            if df is None or df.empty:
                continue
            df = df.copy()
            df.to_excel(w, sheet_name=nombre[:31], index=False, startrow=0)
            wsh = w.sheets[nombre[:31]]
            for j, c in enumerate(df.columns):
                wsh.write(0, j, c, f_head)
                serie = df[c]
                if pd.api.types.is_float_dtype(serie):
                    fmt = fmts["eur"] if "€" in c else fmts["num1"]
                elif pd.api.types.is_integer_dtype(serie):
                    fmt = fmts["int"]
                else:
                    fmt = None
                ancho = max(len(str(c)), int(serie.astype(str).str.len().quantile(.9)) if len(serie) else 0) + 3
                if str(c).startswith("Google Maps"):
                    ancho = 18
                wsh.set_column(j, j, min(max(ancho, 9), 48), fmt)
            wsh.set_row(0, 30)
            wsh.freeze_panes(1, 0)
            wsh.autofilter(0, 0, len(df), len(df.columns) - 1)
    return buf.getvalue()
