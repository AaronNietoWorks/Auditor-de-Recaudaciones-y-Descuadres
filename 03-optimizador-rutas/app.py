"""
app.py — TRUSS & CYTILAND · Optimizador de Rutas y Averías (IPS-Maq+)
======================================================================
Interfaz Streamlit. Ejecuta:  streamlit run app.py
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analyzer as az
import database as db
import sample_data

EMPRESA = "TRUSS & CYTILAND"
NOMBRE_APP = "Optimizador de Rutas y Averías"

st.set_page_config(
    page_title=f"{NOMBRE_APP} · {EMPRESA}",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

SIN_ASIGNAR = "— Sin asignar —"
PERSONALIZADA = "📌 Coordenadas personalizadas…"

# --------------------------------------------------------------------------- #
# Tema claro / oscuro (igual que el Auditor de Recaudaciones)
# --------------------------------------------------------------------------- #
PALETAS = {
    "light": {
        "texto": "#0F2A4A", "texto_sec": "#64748B", "tarjeta": "#FFFFFF", "borde": "#E2E8F0",
        "sombra": "rgba(15, 42, 74, .06)", "acento": "#0F4C81",
        "hero": "linear-gradient(135deg, #0F4C81 0%, #1E6FB8 100%)", "hero_txt": "#E0ECF8",
        "ok_bg": "#DCFCE7", "ok_tx": "#166534", "rev_bg": "#FEF3C7", "rev_tx": "#92400E",
        "crit_bg": "#FDE2E2", "crit_tx": "#991B1B", "plan_bg": "#DBEAFE", "plan_tx": "#1E3A8A",
        "gris_bg": "#F1F5F9", "gris_tx": "#475569",
        "plotly": "plotly_white", "rejilla": "#E5E7EB", "neutro": "#94A3B8", "mapa": "carto-positron",
    },
    "dark": {
        "texto": "#E6EDF5", "texto_sec": "#94A3B8", "tarjeta": "#16202E", "borde": "#26344A",
        "sombra": "rgba(0, 0, 0, .35)", "acento": "#4C9BE8",
        "hero": "linear-gradient(135deg, #12355C 0%, #1B5288 100%)", "hero_txt": "#C9DDF2",
        "ok_bg": "rgba(34,197,94,.16)", "ok_tx": "#86EFAC", "rev_bg": "rgba(245,158,11,.18)",
        "rev_tx": "#FCD34D", "crit_bg": "rgba(239,68,68,.18)", "crit_tx": "#FCA5A5",
        "plan_bg": "rgba(76,155,232,.18)", "plan_tx": "#93C5FD", "gris_bg": "rgba(148,163,184,.14)",
        "gris_tx": "#CBD5E1",
        "plotly": "plotly_dark", "rejilla": "#26344A", "neutro": "#64748B", "mapa": "carto-darkmatter",
    },
}
try:
    _tipo_tema = st.context.theme.type or "light"
except AttributeError:  # versiones antiguas de Streamlit
    _tipo_tema = "light"
OSCURO = _tipo_tema == "dark"
P = PALETAS["dark" if OSCURO else "light"]
AZUL = P["acento"]
COLOR_MOTIVO = {"Recaudar": AZUL, "Recaudar + avería": "#DC2626", "Avería": "#F97316",
                "Recaudar (adelantada)": "#64748B"}
COLORES_DIA = ["#0F4C81", "#16A34A", "#F59E0B", "#DC2626", "#7C3AED", "#0891B2", "#DB2777"]
COLOR_PRECISION = {az.EXACTA: "#16A34A", az.MANUAL: "#0F4C81", az.POBLACION: "#F59E0B", az.SIN_UBICAR: "#DC2626"}
ICONO_MODELO = {az.PROBLEMATICO: "🔴", az.VIGILAR: "🟠", az.FIABLE: "🟢", az.POCOS_DATOS: "⚪"}


def estilo_fig(fig, **kw):
    """Aplica el tema (claro/oscuro) a una figura Plotly con fondo transparente."""
    fig.update_layout(template=P["plotly"], paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font_color=P["texto"], **kw)
    fig.update_xaxes(gridcolor=P["rejilla"], zerolinecolor=P["rejilla"])
    fig.update_yaxes(gridcolor=P["rejilla"], zerolinecolor=P["rejilla"])
    return fig


st.markdown(
    f"""
    <style>
      .block-container {{padding-top: 3.2rem; padding-bottom: 3rem; max-width: 1400px;}}
      .marca {{font-size: .78rem; font-weight: 700; letter-spacing: .18em; color: {P["acento"]};
               text-transform: uppercase; margin-bottom: .1rem;}}
      .titulo {{font-size: 1.9rem; font-weight: 750; color: {P["texto"]}; margin-bottom: 0;}}
      .subtitulo {{color: {P["texto_sec"]}; margin-top: .15rem; margin-bottom: 1.2rem;}}
      .kpi {{background: {P["tarjeta"]}; border: 1px solid {P["borde"]}; border-radius: 14px;
            padding: 18px 20px; box-shadow: 0 1px 3px {P["sombra"]}; height: 100%;}}
      .kpi .lbl {{font-size: .78rem; color: {P["texto_sec"]}; text-transform: uppercase;
                 letter-spacing: .04em; font-weight: 600;}}
      .kpi .val {{font-size: 1.6rem; font-weight: 750; color: {P["texto"]}; margin-top: 4px;
                 white-space: nowrap;}}
      .kpi .det {{font-size: .80rem; color: {P["texto_sec"]}; margin-top: 2px;}}
      .kpi.azul  {{border-left: 5px solid {P["acento"]};}}
      .kpi.rojo  {{border-left: 5px solid #DC2626;}}
      .kpi.ambar {{border-left: 5px solid #F59E0B;}}
      .kpi.verde {{border-left: 5px solid #16A34A;}}
      .chip {{display:inline-block; padding: 3px 12px; border-radius: 999px; font-weight: 600;
             font-size: .85rem; margin: 0 6px 6px 0;}}
      .chip.ok {{background:{P["ok_bg"]}; color:{P["ok_tx"]};}}
      .chip.rev {{background:{P["rev_bg"]}; color:{P["rev_tx"]};}}
      .chip.crit {{background:{P["crit_bg"]}; color:{P["crit_tx"]};}}
      .chip.plan {{background:{P["plan_bg"]}; color:{P["plan_tx"]};}}
      .chip.gris {{background:{P["gris_bg"]}; color:{P["gris_tx"]};}}
      .hero {{background: {P["hero"]}; color: #fff; border-radius: 16px; padding: 28px 32px; margin-bottom: 1rem;}}
      .hero h3 {{color: #fff; margin: 0 0 .4rem 0;}}
      .hero p {{color: {P["hero_txt"]}; margin: 0;}}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Utilidades de formato
# --------------------------------------------------------------------------- #
def eur(x, decimales: int = 2) -> str:
    if x is None or pd.isna(x):
        return "—"
    txt = f"{x:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{txt} €"


def num(x, decimales: int = 0) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def horas(minutos) -> str:
    if minutos is None or pd.isna(minutos):
        return "—"
    m = int(round(minutos))
    return f"{m // 60} h {m % 60:02d} min"


def tarjeta(col, etiqueta: str, valor: str, detalle: str = "", color: str = "azul") -> None:
    col.markdown(
        f'<div class="kpi {color}"><div class="lbl">{etiqueta}</div>'
        f'<div class="val">{valor}</div><div class="det">{detalle}</div></div>',
        unsafe_allow_html=True,
    )


def chips(items: list[tuple[str, str]]) -> None:
    st.markdown("".join(f'<span class="chip {c}">{t}</span>' for c, t in items), unsafe_allow_html=True)


def firma(df: pd.DataFrame, nombre: str) -> str:
    return hashlib.md5((nombre + "|".join(map(str, df.columns)) + str(len(df))).encode()).hexdigest()[:10]


def encuadre(lats, lons) -> tuple[dict, float]:
    lats, lons = np.asarray(lats, float), np.asarray(lons, float)
    centro = {"lat": float((lats.min() + lats.max()) / 2), "lon": float((lons.min() + lons.max()) / 2)}
    ancho = max(float(lons.max() - lons.min()), float(lats.max() - lats.min()) * 1.25, 0.02)
    return centro, float(np.clip(math.log2(360 / ancho) - 0.2, 7, 15))


def fig_mapa(altura: int = 520):
    fig = go.Figure()
    fig.update_layout(height=altura, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      font_color=P["texto"], legend=dict(orientation="h", y=0.01, x=0.01,
                                                         bgcolor="rgba(255,255,255,.75)" if not OSCURO
                                                         else "rgba(14,22,33,.75)"))
    return fig


def centrar(fig, lats, lons) -> None:
    centro, zoom = encuadre(lats, lons)
    fig.update_layout(map=dict(style=P["mapa"], center=centro, zoom=zoom))


# --------------------------------------------------------------------------- #
# Estado de sesión y callbacks
# --------------------------------------------------------------------------- #
db.init_db()
for ds in az.DATASETS:
    st.session_state.setdefault(f"raw_{ds}", None)
    st.session_state.setdefault(f"nombre_{ds}", None)
    st.session_state.setdefault(f"hojas_{ds}", [])
    st.session_state.setdefault(f"plantilla_{ds}", None)
st.session_state.setdefault("mensajes", [])
st.session_state.setdefault("avisos", [])


def avisar(tipo: str, texto: str) -> None:
    st.session_state.mensajes.append((tipo, texto))


def _mapeo_widgets(ds: str, fm: str) -> dict:
    mapeo = {}
    for campo in az.campos(ds):
        v = st.session_state.get(f"map_{ds}_{campo}_{fm}")
        mapeo[campo] = None if v in (None, SIN_ASIGNAR) else v
    return mapeo


def procesar(ds: str, df_raw: pd.DataFrame, mapeo: dict, origen: str) -> bool:
    try:
        limpio, avisos = az.aplicar_mapeo(ds, df_raw, mapeo)
    except ValueError as e:
        avisar("error", f"**{az.DATASETS[ds]['titulo']}**: {e}")
        return False
    if limpio.empty:
        avisar("error", f"**{az.DATASETS[ds]['titulo']}**: no hay filas válidas tras aplicar el mapeo.")
        return False
    st.session_state.avisos += [f"{az.DATASETS[ds]['titulo']}: {a}" for a in avisos]
    if ds == "averias":
        r = db.guardar_averias(limpio, origen)
        avisar("success", f"**Averías** de `{origen}` guardadas: {r['nuevos']} avisos nuevos y "
                          f"{r['actualizados']} actualizados en el histórico.")
    else:
        n = db.guardar_parque(limpio, origen)
        avisar("success", f"**Parque de máquinas**: {num(n)} filas cargadas desde `{origen}` "
                          f"({limpio['clave_bar'].nunique()} establecimientos; sustituyen al parque anterior).")
    return True


def _leer(ds: str, archivo, hoja) -> None:
    try:
        df = az.leer_archivo(archivo, hoja)
    except Exception as e:  # noqa: BLE001 - se muestra al usuario
        avisar("error", f"No se pudo leer el archivo: {e}")
        return
    st.session_state[f"raw_{ds}"] = df
    st.session_state[f"plantilla_{ds}"] = None
    nombre, mapeo = az.plantilla_compatible(ds, list(df.columns))
    if nombre and st.session_state.get("auto_plantilla", True):
        st.session_state[f"plantilla_{ds}"] = nombre
        procesar(ds, df, mapeo, st.session_state[f"nombre_{ds}"])


def cb_subida(ds: str) -> None:
    archivo = st.session_state.get(f"up_{ds}")
    if archivo is None:
        return
    st.session_state[f"nombre_{ds}"] = archivo.name
    try:
        hojas = az.hojas_excel(archivo)
    except Exception as e:  # noqa: BLE001
        avisar("error", f"No se pudo abrir el archivo: {e}")
        return
    st.session_state[f"hojas_{ds}"] = hojas
    hoja = hojas[az.hoja_sugerida(ds, hojas)] if hojas else None
    st.session_state[f"hoja_{ds}"] = hoja
    _leer(ds, archivo, hoja)


def cb_hoja(ds: str) -> None:
    archivo = st.session_state.get(f"up_{ds}")
    if archivo is not None:
        _leer(ds, archivo, st.session_state.get(f"hoja_{ds}"))


def cb_validar(ds: str, fm: str) -> None:
    procesar(ds, st.session_state[f"raw_{ds}"], _mapeo_widgets(ds, fm), st.session_state[f"nombre_{ds}"])


def cb_plantilla(ds: str, fm: str) -> None:
    nombre = (st.session_state.get(f"nombre_plantilla_{ds}") or "").strip() or "IPS-Maq+ por defecto"
    mapeo = _mapeo_widgets(ds, fm)
    faltan = [d["etiqueta"] for c, d in az.campos(ds).items() if d["obligatorio"] and not mapeo[c]]
    if faltan:
        avisar("warning", "Asigna antes las columnas obligatorias: " + ", ".join(faltan))
        return
    try:
        az.guardar_plantilla(ds, nombre, mapeo)
        avisar("success", f"Plantilla **{nombre}** guardada en `config_columnas.json`. Las próximas subidas "
                          "con estas columnas se cargarán solas.")
    except OSError as e:
        avisar("error", f"No se pudo guardar la plantilla: {e}")


def cb_demo() -> None:
    datos = sample_data.generar_datos(hoy=st.session_state.get("fecha_ref") or date.today())
    db.vaciar_todo()
    for ds, hoja in (("parque", "Parque_Maquinas"), ("averias", "Averias")):
        df = datos[hoja]
        procesar(ds, df, az.sugerir_mapeo(ds, list(df.columns)), "Datos de demostración")
    n_bares = datos["Parque_Maquinas"]["Establecimiento"].nunique()
    st.session_state.mensajes = [("success", f"**Datos de demostración cargados**: {n_bares} bares de la Vega Baja, "
                                             f"Elche, Santa Pola y Alicante, {len(datos['Parque_Maquinas'])} "
                                             f"máquinas y {len(datos['Averias'])} averías ficticias.")]


def cb_vaciar() -> None:
    db.vaciar_todo()
    avisar("info", "Base de datos vaciada.")


# --------------------------------------------------------------------------- #
# Barra lateral: parámetros
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown(f"### 🗺️ {NOMBRE_APP}")
    st.caption(f"{EMPRESA} · Rutas de recaudación y averías · IPS-Maq+")

    fecha_ref = st.date_input("Fecha de la ruta", value=date.today(), format="DD/MM/YYYY", key="fecha_ref",
                              help="Día que se planifica. Los días sin visitar se cuentan hasta esta fecha.")

    st.markdown("#### 🏁 Salida")
    municipios = sorted(az.MUNICIPIOS)
    base_sel = st.selectbox("Base / almacén", [PERSONALIZADA] + municipios,
                            index=1 + municipios.index(az.BASE_DEFECTO),
                            help="Punto de salida y regreso del recaudador.")
    base = az.MUNICIPIOS.get(base_sel, az.MUNICIPIOS[az.BASE_DEFECTO])
    if base_sel == PERSONALIZADA:
        txt = st.text_input("Coordenadas de la base «lat, lon»", "38.0880, -0.7246",
                            help="Cópialas de Google Maps: clic derecho sobre el almacén → copiar coordenadas.")
        la, lo = az.separar_coordenadas(pd.Series([txt]))
        if az.coords_validas(la.iloc[0], lo.iloc[0]):
            base = (float(la.iloc[0]), float(lo.iloc[0]))
        else:
            st.warning("Coordenadas no válidas: se usa " + az.BASE_DEFECTO)
    volver = st.toggle("Volver a la base al terminar", value=True)
    hora_salida = st.time_input("Hora de salida", value=pd.Timestamp("08:00").time(), step=900)

    st.markdown("#### ⏱️ Jornada")
    jornada_h = st.number_input("Jornada máxima (horas)", 2.0, 12.0, 7.5, 0.5)
    max_paradas = st.number_input("Máximo de paradas por día", 1, 60, 18)
    min_parada = st.number_input("Minutos por parada (recaudar)", 5, 120, 20, 5)
    min_averia = st.number_input("Minutos extra si hay avería", 0, 240, 30, 5)
    velocidad = st.number_input("Velocidad media (km/h)", 15, 100, 45, 5,
                                help="Media puerta a puerta, incluidos semáforos y aparcar.")
    margen = st.number_input("Adelantar visitas que vencen en… (días)", 0, 14, 1,
                             help="Incluye bares a los que les toca recaudar en los próximos días.")

    st.markdown("#### 💶 Costes")
    coste_km = st.number_input("Coste por km (€)", 0.05, 2.0, 0.26, 0.01,
                               help="Combustible + desgaste. 0,26 €/km es la cifra exenta de IRPF por uso de "
                                    "vehículo propio.")
    dias_anio = st.number_input("Días de ruta al año", 50, 365, 250, 10)
    min_plan = st.number_input("Minutos para planificar la ruta a mano", 0, 180, 30, 5,
                               help="Para estimar el tiempo de oficina que se ahorra.")

    st.markdown("#### 🔧 Averías")
    meses_av = st.number_input("Periodo de análisis (meses)", 1, 36, 12)
    ventana_rein = st.number_input("Reincidencia: ventana (días)", 15, 365, 90, 15)
    min_rein = st.number_input("Reincidencia: nº mínimo de averías", 2, 10, 3)

    with st.expander("Avanzado"):
        factor = st.number_input("Factor carretera (km reales / línea recta)", 1.0, 2.0, az.FACTOR_CARRETERA, 0.05,
                                 help="1,30 es típico en la Vega Baja (autovía + red local).")
        frecuencia_def = st.number_input("Frecuencia de visita por defecto (días)", 1, 60, az.FRECUENCIA_DEFECTO,
                                         help="Si el listado no trae frecuencia.")
        st.toggle("Cargar automáticamente si hay plantilla", value=True, key="auto_plantilla")

    st.divider()
    st.markdown("#### 🗄️ Base de datos (SQLite)")
    info = db.resumen_db()
    nombres = {"parque": "Parque (máquinas)", "averias": "Averías (histórico)"}
    if info["cargas"]:
        lineas = [f"**{e}**: {num(info['cargas'][t][1])} · {pd.Timestamp(info['cargas'][t][2]):%d/%m %H:%M}"
                  for t, e in nombres.items() if t in info["cargas"]]
        lineas.append(f"**Ubicaciones corregidas**: {info['ubicaciones']}")
        st.caption("  \n".join(lineas))
        with st.popover("Vaciar base de datos", icon="🗑️"):
            st.write("Se borrarán el parque, el histórico de averías y las ubicaciones corregidas. "
                     "Esta acción no se puede deshacer.")
            st.button("Sí, vaciar", type="primary", on_click=cb_vaciar)
    else:
        st.caption("Aún no hay datos guardados.")

# --------------------------------------------------------------------------- #
# Cabecera y mensajes
# --------------------------------------------------------------------------- #
st.markdown(f'<div class="marca">{EMPRESA}</div>', unsafe_allow_html=True)
st.markdown(f'<div class="titulo">{NOMBRE_APP}</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitulo">Planifica la ruta de recaudación del día en segundos, ahorra kilómetros y '
            'descubre qué modelos de máquina te cuestan dinero en averías.</div>', unsafe_allow_html=True)
for tipo, texto in st.session_state.mensajes:
    getattr(st, tipo)(texto)
for aviso in st.session_state.avisos:
    st.warning(aviso)
st.session_state.mensajes, st.session_state.avisos = [], []
caja_kpis = st.container()

# --------------------------------------------------------------------------- #
# Cálculos principales
# --------------------------------------------------------------------------- #
parque = db.cargar_parque()
averias_db = db.cargar_averias()
ubicaciones = db.cargar_ubicaciones()
est = az.establecimientos(parque, ubicaciones, fecha_ref, frecuencia_def) if not parque.empty else None
av = az.completar_averias(averias_db, parque if not parque.empty else None, fecha_ref) \
    if not averias_db.empty else None
desde_av = (pd.Timestamp(fecha_ref) - pd.DateOffset(months=int(meses_av)) + pd.Timedelta(days=1)).date()
av_periodo = av[(av["fecha"] >= pd.Timestamp(desde_av)) & (av["fecha"] <= pd.Timestamp(fecha_ref))] \
    if av is not None else None
abiertas = av[av["abierta"] & (av["fecha"] <= pd.Timestamp(fecha_ref))] if av is not None else None
modelos = az.analizar_modelos(av, parque if not parque.empty else None, desde_av, fecha_ref) \
    if av is not None else None
reincidentes = az.maquinas_reincidentes(av, fecha_ref, ventana_rein, min_rein) if av is not None else None
rutas_disp = sorted(est["ruta"].unique()) if est is not None else []
hora_txt = f"{hora_salida:%H:%M}"

tab_carga, tab_ruta, tab_semana, tab_av, tab_ubi, tab_inf = st.tabs(
    ["📥 Carga y mapeo", "🗺️ Ruta del día", "📆 Reparto semanal", "🔧 Averías por modelo", "📍 Ubicaciones",
     "📊 Informe ejecutivo"])

# --------------------------------------------------------------------------- #
# TAB 1 · Carga inteligente
# --------------------------------------------------------------------------- #
with tab_carga:
    col_txt, col_demo = st.columns([3, 1.3], gap="large")
    with col_txt:
        st.markdown(
            "Sube cada listado exportado de IPS-Maq+ en su apartado. **El parque de máquinas / establecimientos** "
            "es la base de las rutas (basta con el bar y su población); **las averías** activan el análisis por "
            "modelo y añaden las reparaciones pendientes a la ruta. Si tienes un único Excel con varias hojas, "
            "súbelo en los dos apartados y elige la hoja en cada uno."
        )
    with col_demo:
        st.markdown("**¿No tienes un Excel a mano?**")
        st.button("🎲 Cargar datos de demostración", type="primary", on_click=cb_demo, width="stretch")
        st.caption("42 bares ficticios de la Vega Baja, Elche, Santa Pola y Alicante · 12 meses de averías.")

    iconos = {"parque": "🎰", "averias": "🔧"}
    for ds, meta in az.DATASETS.items():
        cargado = {"parque": not parque.empty, "averias": not averias_db.empty}[ds]
        with st.expander(f"{iconos[ds]} {meta['titulo']}" + ("  ✅" if cargado else ""),
                         expanded=(ds == "parque" and not cargado) or st.session_state[f"raw_{ds}"] is not None):
            st.file_uploader("Archivo (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"], key=f"up_{ds}",
                             on_change=cb_subida, args=(ds,))
            raw = st.session_state[f"raw_{ds}"]
            if raw is None or st.session_state.get(f"up_{ds}") is None:
                continue
            hojas = st.session_state[f"hojas_{ds}"]
            if len(hojas) > 1:
                st.selectbox("Hoja del Excel", hojas, key=f"hoja_{ds}", on_change=cb_hoja, args=(ds,))
            nombre = st.session_state[f"nombre_{ds}"]
            fm = firma(raw, f"{nombre}|{st.session_state.get(f'hoja_{ds}')}")
            st.caption(f"`{nombre}` · {num(len(raw))} filas × {len(raw.columns)} columnas")
            vista = raw.head(8).copy()
            for c in vista.select_dtypes(include="datetime").columns:
                vista[c] = vista[c].dt.strftime("%d/%m/%Y")
            st.dataframe(vista, hide_index=True)

            columnas = list(raw.columns)
            if st.session_state[f"plantilla_{ds}"]:
                _, mapeo_ini = az.plantilla_compatible(ds, columnas)
                st.success(f"Plantilla **{st.session_state[f'plantilla_{ds}']}** reconocida y aplicada.")
            else:
                mapeo_ini = az.sugerir_mapeo(ds, columnas)
            st.markdown("**🧭 Mapeo de columnas** · propuesto a partir de los nombres habituales de IPS-Maq+. "
                        "Revisa cada desplegable y deja en *Sin asignar* lo que tu listado no tenga.")
            opciones = [SIN_ASIGNAR] + columnas
            cols = st.columns(4)
            for i, (campo, d) in enumerate(az.campos(ds).items()):
                actual = (mapeo_ini or {}).get(campo)
                cols[i % 4].selectbox(d["etiqueta"] + (" *" if d["obligatorio"] else ""), opciones,
                                      index=opciones.index(actual) if actual in opciones else 0,
                                      key=f"map_{ds}_{campo}_{fm}")
            b1, b2, b3 = st.columns([1.2, 1.6, 1])
            b1.button("✅ Validar y guardar", type="primary", on_click=cb_validar, args=(ds, fm),
                      width="stretch", key=f"val_{ds}")
            b2.text_input("Nombre de la plantilla", value=f"IPS-Maq+ {'Parque' if ds == 'parque' else 'Averías'}",
                          key=f"nombre_plantilla_{ds}", label_visibility="collapsed")
            b3.button("💾 Guardar como plantilla", on_click=cb_plantilla, args=(ds, fm), width="stretch",
                      key=f"pl_{ds}")
            plantillas = az.cargar_plantillas(ds)
            if plantillas:
                st.caption("Plantillas guardadas: " + ", ".join(f"`{p}`" for p in plantillas))

    with st.expander("ℹ️ Qué columnas hacen falta y cómo se interpretan (supuestos)"):
        st.markdown(
            "**Parque de máquinas / establecimientos** (una fila por máquina o por bar):\n"
            "- Imprescindible: **establecimiento** y algo para situarlo: **coordenadas** (lat/lon o «38.08, -0.72» "
            "copiado de Google Maps) o, si no hay, la **población**. Sin coordenadas, el bar se sitúa en el centro "
            "de su municipio (tabla interna de la provincia de Alicante) y se puede corregir en 📍 *Ubicaciones*.\n"
            "- Recomendado: **ruta**, **fecha de la última recaudación** y **frecuencia** (días entre visitas; "
            f"{frecuencia_def} por defecto) para saber a quién le toca hoy; **recaudación media semanal** para "
            "estimar el efectivo acumulado; **nº de serie y modelo** para cruzar con las averías.\n"
            "- Si un bar tiene varias máquinas, se agrupan en una sola parada.\n\n"
            "**Averías**: imprescindibles la **fecha del aviso** y la **máquina o el modelo**. Si falta el modelo "
            "se toma del parque por el nº de serie. Una avería está **abierta** si su estado dice «pendiente/"
            "abierta/en curso» o, si no hay estado, si no tiene fecha de resolución.\n\n"
            "**Rutas**: distancia en línea recta × factor carretera "
            f"({num(factor, 2)}), con un mínimo de {num(az.SALTO_URBANO_KM, 1)} km entre paradas. Orden óptimo con "
            "vecino más cercano + mejoras 2-opt y or-opt. Se compara con seguir el **orden del listado** (o la "
            "columna «Orden de visita» si existe). No se usa ningún servicio externo: ningún dato sale del equipo."
        )

# --------------------------------------------------------------------------- #
# Plan del día (se calcula aquí para alimentar KPIs e informe)
# --------------------------------------------------------------------------- #
plan = comp = det = None
with tab_ruta:
    if est is None:
        st.info("Carga el parque de máquinas (o los datos de demostración) para planificar la ruta.")
    else:
        c1, c2 = st.columns([2.2, 1])
        rutas_sel = c1.multiselect("Rutas / zonas a planificar", rutas_disp, default=rutas_disp[:1],
                                   placeholder="Todas las rutas", key="rutas_dia")
        incluir_todas = c2.toggle("Visitar todos los bares de la ruta", value=False,
                                  help="Ignora la fecha de la última recaudación y mete todos los bares.")
        cands = az.candidatas(est, abiertas, rutas_sel or None, margen, incluir_todas)
        if cands.empty:
            st.success("Hoy no le toca recaudar a ningún bar de esta selección y no hay averías abiertas. ✔")
        else:
            plan = az.planificar_dia(cands, base, jornada_h * 60, velocidad, min_parada, min_averia,
                                     int(max_paradas), volver, factor)
            comp = az.comparar_con_listado(plan, volver)
            if plan["paradas"].empty:
                st.warning("Ninguna parada tiene ubicación. Revisa la pestaña 📍 Ubicaciones.")
                plan = comp = None
            else:
                det = az.ruta_detallada(plan["paradas"], base, plan["orden"], plan["d"], velocidad, min_parada,
                                        min_averia, hora_txt, volver)
                n_av = int((det["averias_abiertas"] > 0).sum())
                chips([("plan", f"📍 {len(det)} paradas"), ("plan", f"🚗 {num(plan['km'], 1)} km"),
                       ("plan", f"⏱️ {horas(plan['minutos'])} · salida {hora_txt} → regreso {det.attrs['regreso']}"),
                       ("crit" if n_av else "ok", f"🔧 {n_av} con avería abierta"),
                       ("ok", f"✂️ −{num(comp['ahorro_km'], 1)} km ({num(comp['ahorro_pct'] * 100, 0)} %) vs. "
                              "orden del listado")]
                      + ([("rev", f"⏳ {len(plan['no_caben'])} no caben en la jornada")]
                         if len(plan["no_caben"]) else [])
                      + ([("crit", f"❓ {len(plan['sin_ubicar'])} sin ubicar")] if len(plan["sin_ubicar"]) else []))

                g1, g2 = st.columns([1.75, 1], gap="medium")
                with g1:
                    fig = fig_mapa(560)
                    lats = [base[0]] + det["lat"].tolist() + ([base[0]] if volver else [])
                    lons = [base[1]] + det["lon"].tolist() + ([base[1]] if volver else [])
                    fig.add_trace(go.Scattermap(lat=lats, lon=lons, mode="lines", line=dict(width=3, color=AZUL),
                                                hoverinfo="skip", showlegend=False))
                    for motivo, g in det.groupby("motivo"):
                        fig.add_trace(go.Scattermap(
                            lat=g["lat"], lon=g["lon"], mode="markers+text", name=motivo,
                            text=g["parada"].astype(str), textfont=dict(color="#FFFFFF", size=11),
                            marker=dict(size=19, color=COLOR_MOTIVO.get(motivo, AZUL)),
                            customdata=np.stack([g["bar"], g["poblacion"], g["llegada"],
                                                 g["modelos"].replace("", "—")], axis=1),
                            hovertemplate="<b>%{text}. %{customdata[0]}</b><br>%{customdata[1]}<br>"
                                          "Llegada estimada: %{customdata[2]}<br>Máquinas: %{customdata[3]}"
                                          "<extra></extra>"))
                    fig.add_trace(go.Scattermap(lat=[base[0]], lon=[base[1]], mode="markers", name="Base",
                                                marker=dict(size=16, color="#111827" if not OSCURO else "#F8FAFC"),
                                                hovertemplate=f"<b>Base</b> · {base_sel}<extra></extra>"))
                    centrar(fig, lats, lons)
                    st.plotly_chart(fig, width="stretch", config={"scrollZoom": True})
                with g2:
                    st.markdown("**🧭 Navegación**")
                    enlaces = az.enlaces_google_maps(base, det, volver)
                    for i, url in enumerate(enlaces, start=1):
                        st.link_button(f"Abrir en Google Maps" + (f" · tramo {i}/{len(enlaces)}"
                                                                  if len(enlaces) > 1 else ""),
                                       url, icon="🗺️", width="stretch")
                    st.caption("Google Maps admite hasta 10 paradas por enlace; las rutas largas se dividen en "
                               "tramos. Al abrirlo, las coordenadas se envían a Google.")
                    tarjeta(st, "Ahorro frente al listado", f"{num(comp['ahorro_km'], 1)} km",
                            f"{eur(comp['ahorro_km'] * coste_km)} hoy · "
                            f"{eur(comp['ahorro_km'] * coste_km * dias_anio, 0)} al año si se repite", "verde")
                    st.write("")
                    if det["efectivo_estimado"].notna().any():
                        tarjeta(st, "Efectivo estimado a recoger", eur(det["efectivo_estimado"].sum(), 0),
                                "recaudación media × días desde la última visita", "azul")

                tabla = pd.DataFrame({
                    "Nº": det["parada"], "Llegada": det["llegada"], "Establecimiento": det["bar"],
                    "Población": det["poblacion"], "Dirección": det["direccion"], "Motivo": det["motivo"],
                    "Días sin visitar": det["dias_sin_visita"], "Máquinas": det["n_maquinas"],
                    "Averías abiertas": det["averias_abiertas"], "Efectivo estimado (€)": det["efectivo_estimado"],
                    "Km tramo": det["km_tramo"], "Ubicación": det["precision"],
                })
                st.dataframe(tabla, hide_index=True, width="stretch", column_config={
                    "Efectivo estimado (€)": st.column_config.NumberColumn(format="%.0f €"),
                    "Km tramo": st.column_config.NumberColumn(format="%.1f"),
                    "Días sin visitar": st.column_config.NumberColumn(format="%d"),
                })
                hoja = az.exportar_excel(
                    {"Hoja_de_ruta": tabla.assign(**{"Google Maps": [
                        f"https://www.google.com/maps/search/?api=1&query={la:.6f},{lo:.6f}"
                        for la, lo in zip(det["lat"], det["lon"])]}),
                     "No_caben": plan["no_caben"][["bar", "poblacion", "ruta", "motivo", "dias_sin_visita"]]
                     .rename(columns={"bar": "Establecimiento", "poblacion": "Población", "ruta": "Ruta",
                                      "motivo": "Motivo", "dias_sin_visita": "Días sin visitar"})},
                    [("Fecha", f"{fecha_ref:%d/%m/%Y}", "txt"), ("Rutas", ", ".join(rutas_sel) or "Todas", "txt"),
                     ("Paradas", len(det), "int"), ("Kilómetros", plan["km"], "num1"),
                     ("Duración (min)", plan["minutos"], "int"), ("Salida", hora_txt, "txt"),
                     ("Regreso estimado", det.attrs["regreso"], "txt"),
                     ("Km ahorrados vs. listado", comp["ahorro_km"], "num1")],
                    {"Base": base_sel, "Velocidad media": f"{velocidad} km/h",
                     "Minutos por parada": min_parada, "Minutos extra avería": min_averia},
                    f"Hoja de ruta · {fecha_ref:%d/%m/%Y}")
                st.download_button("📥 Descargar hoja de ruta (Excel)", hoja,
                                   file_name=f"hoja_de_ruta_{fecha_ref:%Y%m%d}.xlsx", type="primary",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                if len(plan["no_caben"]):
                    with st.expander(f"⏳ {len(plan['no_caben'])} paradas pendientes que no caben hoy"):
                        st.caption("Se han dejado fuera las de menor prioridad (nunca antes que una avería). "
                                   "Amplía la jornada o el máximo de paradas, o pásalas a mañana.")
                        st.dataframe(plan["no_caben"][["bar", "poblacion", "ruta", "motivo", "dias_sin_visita"]]
                                     .rename(columns={"bar": "Establecimiento", "poblacion": "Población",
                                                      "ruta": "Ruta", "motivo": "Motivo",
                                                      "dias_sin_visita": "Días sin visitar"}),
                                     hide_index=True, width="stretch")
                if len(plan["sin_ubicar"]):
                    st.warning(f"{len(plan['sin_ubicar'])} paradas sin ubicación no se han podido incluir: "
                               + ", ".join(plan["sin_ubicar"]["bar"]) + ". Corrígelas en 📍 Ubicaciones.")

# --------------------------------------------------------------------------- #
# TAB 3 · Reparto semanal
# --------------------------------------------------------------------------- #
reparto = None
with tab_semana:
    if est is None:
        st.info("Carga el parque de máquinas (o los datos de demostración) para repartir la semana.")
    else:
        st.markdown("Reparte **todos** los bares en días (o recaudadores) de forma que cada ruta sea compacta y "
                    "con una carga de trabajo parecida. Útil para rehacer las rutas fijas o cuando se incorpora "
                    "un recaudador.")
        c1, c2, c3 = st.columns([1, 2, 1])
        n_dias = c1.number_input("Nº de días / recaudadores", 1, 7, 5)
        rutas_sem = c2.multiselect("Rutas a repartir", rutas_disp, default=[], placeholder="Todas las rutas",
                                   key="rutas_semana")
        etiqueta = c3.radio("Llamar a cada grupo", ["Día de la semana", "Recaudador"], horizontal=False)
        reparto = az.reparto_semanal(est, base, int(n_dias), velocidad, min_parada, volver, factor, rutas_sem or None)
        if reparto.empty:
            st.warning("No hay bares con ubicación en esta selección.")
            reparto = None
        else:
            nombre_dia = (lambda d: az.DIAS_SEMANA[d - 1]) if etiqueta == "Día de la semana" \
                else (lambda d: f"Recaudador {d}")
            reparto["grupo"] = reparto["dia"].map(nombre_dia)
            res = (reparto.groupby(["dia", "grupo"], as_index=False)
                   .agg(bares=("bar", "size"), maquinas=("n_maquinas", "sum"), km=("km_dia", "first"),
                        km_listado=("km_listado_dia", "first"), minutos=("min_dia", "first"),
                        poblaciones=("poblacion", lambda s: ", ".join(dict.fromkeys(s)))))
            km_t, km_lt = res["km"].sum(), res["km_listado"].sum()
            chips([("plan", f"📍 {len(reparto)} bares en {len(res)} grupos"),
                   ("plan", f"🚗 {num(km_t, 0)} km a la semana"),
                   ("ok", f"✂️ −{num(km_lt - km_t, 0)} km/semana vs. seguir el listado en cada grupo"),
                   ("gris", f"⏱️ de {horas(res['minutos'].min())} a {horas(res['minutos'].max())} por día")])
            g1, g2 = st.columns([1.6, 1], gap="medium")
            with g1:
                fig = fig_mapa(560)
                for dia, g in reparto.groupby("dia"):
                    color = COLORES_DIA[(dia - 1) % len(COLORES_DIA)]
                    la = [base[0]] + g["lat"].tolist() + ([base[0]] if volver else [])
                    lo = [base[1]] + g["lon"].tolist() + ([base[1]] if volver else [])
                    fig.add_trace(go.Scattermap(lat=la, lon=lo, mode="lines", line=dict(width=2.5, color=color),
                                                hoverinfo="skip", showlegend=False, opacity=.75))
                    fig.add_trace(go.Scattermap(
                        lat=g["lat"], lon=g["lon"], mode="markers", name=g["grupo"].iloc[0],
                        marker=dict(size=12, color=color),
                        customdata=np.stack([g["bar"], g["poblacion"], g["parada"]], axis=1),
                        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]} · parada %{customdata[2]}"
                                      "<extra></extra>"))
                fig.add_trace(go.Scattermap(lat=[base[0]], lon=[base[1]], mode="markers", name="Base",
                                            marker=dict(size=15, color="#111827" if not OSCURO else "#F8FAFC")))
                centrar(fig, reparto["lat"].tolist() + [base[0]], reparto["lon"].tolist() + [base[1]])
                st.plotly_chart(fig, width="stretch", config={"scrollZoom": True})
            with g2:
                st.dataframe(res.drop(columns=["dia"]).rename(columns={
                    "grupo": "Grupo", "bares": "Bares", "maquinas": "Máquinas", "km": "Km", "km_listado": "Km listado",
                    "minutos": "Minutos", "poblaciones": "Poblaciones"}), hide_index=True, width="stretch",
                    column_config={"Km": st.column_config.NumberColumn(format="%.0f"),
                                   "Km listado": st.column_config.NumberColumn(format="%.0f"),
                                   "Minutos": st.column_config.NumberColumn(format="%.0f")})
            excesos = res[res["minutos"] > jornada_h * 60]
            if not excesos.empty:
                st.warning("Superan la jornada de " + num(jornada_h, 1) + " h: "
                           + ", ".join(f"{g} ({horas(m)})" for g, m in zip(excesos["grupo"], excesos["minutos"]))
                           + ". Sube el nº de días o reduce los minutos por parada.")
            st.caption("El reparto agrupa por zonas alrededor de la base y equilibra el tiempo (servicio + "
                       "desplazamiento). Supone una visita por bar en el ciclo; los bares de visita quincenal "
                       "pueden ir en semanas alternas.")

# --------------------------------------------------------------------------- #
# TAB 4 · Averías por modelo
# --------------------------------------------------------------------------- #
with tab_av:
    if av is None:
        st.info("Carga el listado de averías (o los datos de demostración) para ver el análisis por modelo.")
    elif modelos is None or modelos.empty:
        st.info("No hay averías en el periodo seleccionado.")
    else:
        st.caption(f"Periodo: {desde_av:%d/%m/%Y} – {fecha_ref:%d/%m/%Y} · tasa media del parque: "
                   f"{num(modelos.attrs['tasa_media'], 2)} averías por máquina y año")
        chips([({az.PROBLEMATICO: "crit", az.VIGILAR: "rev", az.FIABLE: "ok", az.POCOS_DATOS: "gris"}[e],
                 f"{ICONO_MODELO[e]} {e}: {int((modelos['estado'] == e).sum())}") for e in az.ESTADOS_MODELO]
              + [("crit" if len(abiertas) else "ok", f"🔧 {len(abiertas)} averías abiertas"),
                 ("rev" if len(reincidentes) else "ok", f"🔁 {len(reincidentes)} máquinas reincidentes")])
        g1, g2 = st.columns([1.3, 1], gap="medium")
        with g1:
            m = modelos.sort_values("tasa_anual")
            fig = go.Figure(go.Bar(
                x=m["tasa_anual"], y=m["modelo"], orientation="h",
                marker_color=[az.COLOR_MODELO[e] for e in m["estado"]],
                text=[f"{num(t, 2)} · {e}" for t, e in zip(m["tasa_anual"], m["estado"])], textposition="outside",
                customdata=np.stack([m["n_maquinas"], m["averias"], m["mtbf_dias"].fillna(0)], axis=1),
                hovertemplate="<b>%{y}</b><br>%{x:.2f} averías/máquina/año<br>%{customdata[0]} máquinas · "
                              "%{customdata[1]} averías<br>Una avería cada %{customdata[2]:.0f} días por máquina"
                              "<extra></extra>"))
            fig.add_vline(x=modelos.attrs["tasa_media"], line_dash="dot", line_color=P["neutro"])
            fig.add_annotation(x=modelos.attrs["tasa_media"], y=1.04, yref="paper", text="media del parque",
                               showarrow=False, font=dict(size=11, color=P["texto_sec"]))
            estilo_fig(fig, height=max(300, 46 * len(m) + 100), title="Averías por máquina y año",
                       margin=dict(l=10, r=40, t=60, b=10),
                       xaxis=dict(range=[0, float(m["tasa_anual"].max()) * 1.45]))
            st.plotly_chart(fig, width="stretch")
        with g2:
            a = av_periodo.copy()
            pv = a.pivot_table(index="modelo", columns="tipo", values="fecha", aggfunc="count", fill_value=0)
            pv = pv.loc[[x for x in modelos["modelo"] if x in pv.index]]
            fig = go.Figure(go.Heatmap(z=pv.values, x=pv.columns, y=pv.index, colorscale="Reds",
                                       text=pv.values, texttemplate="%{text}", showscale=False,
                                       hovertemplate="%{y} · %{x}: %{z} averías<extra></extra>"))
            estilo_fig(fig, height=max(300, 46 * len(pv) + 140), title="¿Qué falla en cada modelo?",
                       margin=dict(l=10, r=10, t=60, b=10), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width="stretch")

        tabla_m = pd.DataFrame({
            "Estado": [f"{ICONO_MODELO[e]} {e}" for e in modelos["estado"]], "Modelo": modelos["modelo"],
            "Máquinas": modelos["n_maquinas"], "Averías": modelos["averias"], "Abiertas": modelos["abiertas"],
            "Averías/máquina/año": modelos["tasa_anual"], "vs. media": modelos["vs_media"],
            "Días entre averías (MTBF)": modelos["mtbf_dias"], "Días medios de resolución": modelos["dias_resolucion"],
            "Días de parada": modelos["dias_parada"], "Coste (€)": modelos["coste"],
            "Coste por máquina (€)": modelos["coste_por_maquina"], "Recaudación perdida (€)": modelos["rec_perdida"],
            "Fallo más común": modelos["tipo_principal"],
        })
        st.dataframe(tabla_m, hide_index=True, width="stretch", column_config={
            "Averías/máquina/año": st.column_config.NumberColumn(format="%.2f"),
            "vs. media": st.column_config.NumberColumn(format="%.2f×"),
            "Días entre averías (MTBF)": st.column_config.NumberColumn(format="%.0f"),
            "Días medios de resolución": st.column_config.NumberColumn(format="%.1f"),
            "Días de parada": st.column_config.NumberColumn(format="%.0f"),
            "Coste (€)": st.column_config.NumberColumn(format="%.0f €"),
            "Coste por máquina (€)": st.column_config.NumberColumn(format="%.0f €"),
            "Recaudación perdida (€)": st.column_config.NumberColumn(format="%.0f €"),
        })
        st.caption("**Problemático** ≥ 1,5× la media del parque · **Vigilar** ≥ 1,15× · **Pocos datos**: menos de 2 "
                   "máquinas del modelo. Recaudación perdida = días de parada × recaudación media diaria del modelo "
                   "(supone la máquina parada desde el aviso hasta la resolución).")

        mens = az.averias_mensuales(av, desde_av, fecha_ref)
        if not mens.empty:
            fig = go.Figure()
            pal = ["#DC2626", "#0F4C81", "#F59E0B", "#16A34A", "#7C3AED", "#0891B2", P["neutro"]]
            for i, (mod, g) in enumerate(mens.groupby("modelo", sort=False)):
                fig.add_trace(go.Bar(x=g["mes"], y=g["averias"], name=mod,
                                     marker_color=pal[i % len(pal)] if mod != "Otros" else P["neutro"]))
            estilo_fig(fig, barmode="stack", height=330, title="Averías por mes y modelo",
                       margin=dict(l=10, r=10, t=60, b=10), legend=dict(orientation="h", y=-0.2),
                       xaxis=dict(tickformat="%m/%Y"))
            st.plotly_chart(fig, width="stretch")

        r1, r2 = st.columns(2, gap="medium")
        with r1:
            st.markdown(f"**🔁 Máquinas reincidentes** · ≥ {min_rein} averías en {ventana_rein} días")
            if reincidentes.empty:
                st.success("Ninguna máquina reincidente. ✔")
            else:
                st.dataframe(reincidentes.rename(columns={
                    "maquina": "Máquina", "modelo": "Modelo", "bar": "Establecimiento", "averias": "Averías",
                    "tipos": "Tipos", "ultima": "Última", "coste": "Coste (€)", "abiertas": "Abiertas"}),
                    hide_index=True, width="stretch",
                    column_config={"Última": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                   "Coste (€)": st.column_config.NumberColumn(format="%.0f €")})
                st.caption("Candidatas a revisión a fondo o a cambiar de ubicación/modelo.")
        with r2:
            st.markdown("**🔧 Averías abiertas** · se añaden como parada prioritaria en la ruta del día")
            if abiertas.empty:
                st.success("No hay averías abiertas. ✔")
            else:
                ab = abiertas.sort_values("fecha")
                if est is not None:
                    ab = ab.merge(est[["clave_bar", "ruta", "poblacion"]], on="clave_bar", how="left")
                else:
                    ab = ab.assign(ruta="", poblacion="")
                st.dataframe(pd.DataFrame({
                    "Aviso": ab["fecha"], "Días abierta": ab["dias_abierta"], "Establecimiento": ab["bar"],
                    "Población": ab["poblacion"], "Ruta": ab["ruta"], "Máquina": ab["maquina"],
                    "Modelo": ab["modelo"], "Tipo": ab["tipo"], "Descripción": ab["descripcion"]}),
                    hide_index=True, width="stretch",
                    column_config={"Aviso": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                   "Días abierta": st.column_config.NumberColumn(format="%d")})

# --------------------------------------------------------------------------- #
# TAB 5 · Ubicaciones
# --------------------------------------------------------------------------- #
with tab_ubi:
    if est is None:
        st.info("Carga el parque de máquinas (o los datos de demostración) para revisar las ubicaciones.")
    else:
        cuenta = est["precision"].value_counts()
        chips([("ok", f"🟢 {az.EXACTA}: {int(cuenta.get(az.EXACTA, 0))}"),
               ("plan", f"🔵 {az.MANUAL}: {int(cuenta.get(az.MANUAL, 0))}"),
               ("rev", f"🟠 {az.POBLACION}: {int(cuenta.get(az.POBLACION, 0))}"),
               ("crit", f"🔴 {az.SIN_UBICAR}: {int(cuenta.get(az.SIN_UBICAR, 0))}")])
        st.markdown("Los bares en **centro de la población** o **sin ubicar** hacen que la ruta sea aproximada. "
                    "Para corregir uno: en Google Maps, clic derecho sobre el local → copia las coordenadas y "
                    "pégalas en la columna *Coordenadas*. Se guardan y se conservan aunque vuelvas a cargar el parque. "
                    "Deja la celda vacía para quitar una corrección.")
        g1, g2 = st.columns([1.5, 1], gap="medium")
        with g2:
            ubic = est[est[["lat", "lon"]].notna().all(axis=1)]
            fig = fig_mapa(520)
            for prec, g in ubic.groupby("precision"):
                fig.add_trace(go.Scattermap(lat=g["lat"], lon=g["lon"], mode="markers", name=prec,
                                            marker=dict(size=11, color=COLOR_PRECISION[prec]),
                                            text=g["bar"], hovertemplate="%{text}<extra></extra>"))
            if not ubic.empty:
                centrar(fig, ubic["lat"], ubic["lon"])
                st.plotly_chart(fig, width="stretch", config={"scrollZoom": True})
        with g1:
            orden_p = {az.SIN_UBICAR: 0, az.POBLACION: 1, az.MANUAL: 2, az.EXACTA: 3}
            e = est.sort_values(["precision", "ruta", "bar"], key=lambda s: s.map(orden_p) if s.name == "precision"
                                else s).reset_index(drop=True)
            coords_txt = [f"{la:.5f}, {lo:.5f}" if p in (az.EXACTA, az.MANUAL) and pd.notna(la) else ""
                          for la, lo, p in zip(e["lat"], e["lon"], e["precision"])]
            editor = pd.DataFrame({"Establecimiento": e["bar"], "Población": e["poblacion"],
                                   "Coordenadas": coords_txt, "Ubicación": e["precision"], "Ruta": e["ruta"]})
            editado = st.data_editor(editor, hide_index=True, width="stretch", height=520,
                                     disabled=["Establecimiento", "Población", "Ruta", "Ubicación"],
                                     column_config={"Coordenadas": st.column_config.TextColumn(
                                         help="Formato «38.08491, -0.94402» (como lo copia Google Maps)")},
                                     key=f"editor_ubi_{len(e)}_{db.resumen_db()['ubicaciones']}")
            if st.button("💾 Guardar ubicaciones", type="primary"):
                guardar, borrar, malas = [], [], []
                for i in editado.index[editado["Coordenadas"] != editor["Coordenadas"]]:
                    txt = (editado.at[i, "Coordenadas"] or "").strip()
                    clave = e.at[i, "clave_bar"]
                    if not txt:
                        if e.at[i, "precision"] == az.MANUAL:
                            borrar.append(clave)
                        continue
                    la, lo = az.separar_coordenadas(pd.Series([txt]))
                    la, lo = float(la.iloc[0]), float(lo.iloc[0])
                    if not az.coords_validas(la, lo) and az.coords_validas(lo, la):
                        la, lo = lo, la
                    if az.coords_validas(la, lo):
                        guardar.append((clave, e.at[i, "bar"], la, lo))
                    else:
                        malas.append(e.at[i, "bar"])
                if guardar:
                    db.guardar_ubicaciones(guardar)
                if borrar:
                    db.borrar_ubicaciones(borrar)
                if malas:
                    avisar("warning", "Coordenadas no válidas (fuera de la provincia de Alicante): " + ", ".join(malas))
                if guardar or borrar:
                    avisar("success", f"Ubicaciones guardadas: {len(guardar)} corregidas, {len(borrar)} restauradas.")
                elif not malas:
                    avisar("info", "No había cambios que guardar.")
                st.rerun()

# --------------------------------------------------------------------------- #
# KPIs (arriba) e informe ejecutivo
# --------------------------------------------------------------------------- #
kpis = az.calcular_kpis(est, plan, comp, modelos, av_periodo, reincidentes, coste_km, dias_anio, min_plan)
with caja_kpis:
    if est is not None or av is not None:
        c1, c2, c3, c4, c5 = st.columns(5)
        if est is not None:
            tarjeta(c1, "Parque", f"{num(kpis['n_bares'])} bares",
                    f"{num(kpis['n_maquinas'])} máquinas · {kpis['n_rutas']} rutas · "
                    f"{kpis['n_atrasados']} con la visita atrasada", "azul")
        else:
            tarjeta(c1, "Parque", "—", "Carga el parque de máquinas", "azul")
        if plan is not None:
            tarjeta(c2, "Ruta del día", f"{kpis['paradas_dia']} paradas",
                    f"{num(kpis['km_dia'], 0)} km · {horas(kpis['min_dia'])}"
                    + (f" · {kpis['no_caben']} no caben" if kpis["no_caben"] else ""),
                    "ambar" if kpis["no_caben"] else "azul")
            tarjeta(c3, "Ahorro en km", f"{eur(kpis['ahorro_eur_anio'], 0)}/año",
                    f"−{num(kpis['ahorro_km'], 1)} km hoy ({num(kpis['ahorro_pct'] * 100, 0)} %) vs. el listado",
                    "verde")
        else:
            tarjeta(c2, "Ruta del día", "—", "Elige una ruta en 🗺️ Ruta del día", "azul")
            tarjeta(c3, "Ahorro en km", "—", "Se calcula con la ruta del día", "verde")
        if av_periodo is not None and not av_periodo.empty:
            tarjeta(c4, "Averías", f"{num(kpis['n_averias'])} en {meses_av} m",
                    f"{kpis['n_abiertas']} abiertas · {kpis.get('n_problematicos', 0)} modelos problemáticos · "
                    f"{eur(kpis['coste_averias'], 0)}",
                    "rojo" if kpis.get("n_problematicos") or kpis["n_abiertas"] else "verde")
        else:
            tarjeta(c4, "Averías", "—", "Carga el listado de averías", "azul")
        tarjeta(c5, "Tiempo de oficina", f"{num(kpis['horas_planificacion_anio'], 0)} h/año",
                f"planificación automática ({min_plan} min/día × {dias_anio} días)", "verde")
        st.write("")
    else:
        st.markdown(
            '<div class="hero"><h3>👋 Empieza en 10 segundos</h3>'
            '<p>Sube el parque de máquinas (y, si quieres, las averías) exportado de IPS-Maq+, o pulsa '
            '<b>Cargar datos de demostración</b> para verlo funcionar con datos ficticios de la Vega Baja.</p></div>',
            unsafe_allow_html=True)

with tab_inf:
    if est is None and av is None:
        st.info("Carga datos para generar el informe.")
    else:
        st.markdown("### 📊 Resumen para dirección")
        lineas = []
        if est is not None:
            lineas.append(f"- **Parque**: {kpis['n_bares']} establecimientos y {kpis['n_maquinas']} máquinas en "
                          f"{kpis['n_rutas']} rutas; {num(kpis['pct_ubicados'] * 100, 0)} % ubicados en el mapa "
                          f"({kpis['n_exactas']} con coordenadas exactas).")
        if plan is not None:
            lineas.append(f"- **Ruta del {fecha_ref:%d/%m/%Y}**: {kpis['paradas_dia']} paradas, "
                          f"{num(kpis['km_dia'], 1)} km y {horas(kpis['min_dia'])}. Frente a seguir el listado se "
                          f"ahorran **{num(kpis['ahorro_km'], 1)} km ({num(kpis['ahorro_pct'] * 100, 0)} %)**, "
                          f"unos **{eur(kpis['ahorro_eur_anio'], 0)} al año** a {num(coste_km, 2)} €/km si el ahorro "
                          "se repite cada día de ruta.")
        if reparto is not None:
            lineas.append(f"- **Reparto semanal**: {reparto['dia'].nunique()} grupos, "
                          f"{num(reparto.groupby('dia')['km_dia'].first().sum(), 0)} km a la semana.")
        if modelos is not None and not modelos.empty:
            prob = modelos[modelos["estado"] == az.PROBLEMATICO]
            lineas.append(f"- **Averías ({meses_av} meses)**: {kpis['n_averias']} avisos, {kpis['n_abiertas']} abiertos, "
                          f"{eur(kpis['coste_averias'], 0)} en reparaciones y {num(kpis['dias_resolucion'], 1)} días "
                          "de media hasta resolver"
                          + (f"; recaudación perdida estimada {eur(kpis['rec_perdida'], 0)}" if
                             not pd.isna(kpis.get("rec_perdida", np.nan)) else "") + ".")
            if not prob.empty:
                lineas.append("- **Modelos problemáticos**: " + "; ".join(
                    f"{r.modelo} ({num(r.tasa_anual, 2)} averías/máquina/año, {num(r.vs_media, 1)}× la media, "
                    f"sobre todo {r.tipo_principal.lower()})" for r in prob.itertuples())
                    + ". Valorar sustituirlos o negociar con el fabricante.")
            if reincidentes is not None and not reincidentes.empty:
                lineas.append(f"- **{len(reincidentes)} máquinas reincidentes**: " + ", ".join(
                    f"{r.maquina} en {r.bar}" for r in reincidentes.head(5).itertuples()) + ".")
        lineas.append(f"- **Tiempo de oficina**: ~{num(kpis['horas_planificacion_anio'], 0)} h/año que no se dedican a "
                      "planificar rutas a mano.")
        st.markdown("\n".join(lineas))

        hojas = {}
        if det is not None:
            hojas["Hoja_de_ruta"] = det[["parada", "llegada", "bar", "poblacion", "direccion", "motivo",
                                         "dias_sin_visita", "n_maquinas", "averias_abiertas", "km_tramo"]].rename(
                columns={"parada": "Nº", "llegada": "Llegada", "bar": "Establecimiento", "poblacion": "Población",
                         "direccion": "Dirección", "motivo": "Motivo", "dias_sin_visita": "Días sin visitar",
                         "n_maquinas": "Máquinas", "averias_abiertas": "Averías abiertas", "km_tramo": "Km tramo"})
        if reparto is not None:
            hojas["Reparto_semanal"] = reparto[["grupo", "parada", "bar", "poblacion", "ruta", "n_maquinas",
                                                "km_tramo"]].rename(columns={
                "grupo": "Grupo", "parada": "Nº", "bar": "Establecimiento", "poblacion": "Población",
                "ruta": "Ruta actual", "n_maquinas": "Máquinas", "km_tramo": "Km tramo"})
        if modelos is not None and not modelos.empty:
            hojas["Averias_por_modelo"] = tabla_m.assign(Estado=modelos["estado"].values)
        if reincidentes is not None and not reincidentes.empty:
            hojas["Maquinas_reincidentes"] = reincidentes.rename(columns={
                "maquina": "Máquina", "modelo": "Modelo", "bar": "Establecimiento", "averias": "Averías",
                "tipos": "Tipos", "ultima": "Última", "coste": "Coste (€)", "abiertas": "Abiertas"})
        if abiertas is not None and not abiertas.empty:
            hojas["Averias_abiertas"] = abiertas[["fecha", "dias_abierta", "bar", "maquina", "modelo", "tipo",
                                                  "descripcion"]].rename(columns={
                "fecha": "Aviso", "dias_abierta": "Días abierta", "bar": "Establecimiento", "maquina": "Máquina",
                "modelo": "Modelo", "tipo": "Tipo", "descripcion": "Descripción"})
        if est is not None:
            hojas["Establecimientos"] = est[["bar", "poblacion", "ruta", "n_maquinas", "modelos", "ultima_visita",
                                             "dias_sin_visita", "frecuencia", "precision", "lat", "lon"]].rename(
                columns={"bar": "Establecimiento", "poblacion": "Población", "ruta": "Ruta",
                         "n_maquinas": "Máquinas", "modelos": "Modelos", "ultima_visita": "Última recaudación",
                         "dias_sin_visita": "Días sin visitar", "frecuencia": "Frecuencia (días)",
                         "precision": "Ubicación", "lat": "Latitud", "lon": "Longitud"})
        resumen = [
            ("Fecha de la ruta", f"{fecha_ref:%d/%m/%Y}", "txt"),
            ("Establecimientos", kpis.get("n_bares"), "int"), ("Máquinas", kpis.get("n_maquinas"), "int"),
            ("Paradas de la ruta del día", kpis.get("paradas_dia"), "int"),
            ("Km de la ruta del día", kpis.get("km_dia"), "num1"),
            ("Km ahorrados hoy vs. listado", kpis.get("ahorro_km"), "num1"),
            ("Ahorro anual estimado en km (€)", kpis.get("ahorro_eur_anio"), "eur"),
            ("Averías en el periodo", kpis.get("n_averias"), "int"), ("Averías abiertas", kpis.get("n_abiertas"), "int"),
            ("Coste de reparaciones (€)", kpis.get("coste_averias"), "eur"),
            ("Recaudación perdida estimada (€)", kpis.get("rec_perdida"), "eur"),
            ("Modelos problemáticos", kpis.get("n_problematicos"), "int"),
            ("Máquinas reincidentes", kpis.get("n_reincidentes"), "int"),
            ("Horas de planificación ahorradas al año", kpis.get("horas_planificacion_anio"), "num1"),
        ]
        parametros = {"Base": base_sel, "Volver a la base": "Sí" if volver else "No", "Hora de salida": hora_txt,
                      "Jornada": f"{jornada_h} h", "Velocidad media": f"{velocidad} km/h",
                      "Minutos por parada": min_parada, "Minutos extra avería": min_averia,
                      "Factor carretera": factor, "Coste por km": f"{coste_km} €",
                      "Periodo de averías": f"{desde_av:%d/%m/%Y} – {fecha_ref:%d/%m/%Y}"}
        st.download_button("📥 Descargar informe completo (Excel)",
                           az.exportar_excel(hojas, resumen, parametros, f"{EMPRESA} · {NOMBRE_APP}"),
                           file_name=f"informe_rutas_averias_{fecha_ref:%Y%m%d}.xlsx", type="primary",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption("Incluye: resumen, hoja de ruta del día, reparto semanal, averías por modelo, máquinas "
                   "reincidentes, averías abiertas y establecimientos con su ubicación.")
