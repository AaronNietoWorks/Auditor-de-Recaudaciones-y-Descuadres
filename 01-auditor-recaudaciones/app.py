"""
app.py — TRUSS & CYTILAND · Auditoría de Recaudaciones y Descuadres (IPS-Maq+)
==========================================================
Interfaz Streamlit. Ejecuta:  streamlit run app.py
"""
from __future__ import annotations

import hashlib
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import analyzer as az
import database as db
import sample_data

EMPRESA = "TRUSS & CYTILAND"
NOMBRE_APP = "Auditoría de Recaudaciones y Descuadres"

st.set_page_config(
    page_title=f"{NOMBRE_APP} · {EMPRESA}",
    page_icon="🎰",
    layout="wide",
    initial_sidebar_state="expanded",
)

SIN_ASIGNAR = "— Sin asignar —"

# --------------------------------------------------------------------------- #
# Tema claro / oscuro
# --------------------------------------------------------------------------- #
# Streamlit aplica el tema nativo (config.toml define [theme.light] y [theme.dark])
# según el sistema o lo elegido en el menú ⋮ (System / Light / Dark). Aquí detectamos cuál está activo
# para adaptar las tarjetas HTML, las tablas y los gráficos Plotly.
PALETAS = {
    "light": {
        "texto": "#0F2A4A", "texto_sec": "#64748B", "tarjeta": "#FFFFFF", "borde": "#E2E8F0",
        "sombra": "rgba(15, 42, 74, .06)", "acento": "#0F4C81",
        "hero": "linear-gradient(135deg, #0F4C81 0%, #1E6FB8 100%)", "hero_txt": "#E0ECF8",
        "ok_bg": "#DCFCE7", "ok_tx": "#166534", "rev_bg": "#FEF3C7", "rev_tx": "#92400E",
        "crit_bg": "#FDE2E2", "crit_tx": "#991B1B", "plotly": "plotly_white", "rejilla": "#E5E7EB",
        "neutro": "#94A3B8",
    },
    "dark": {
        "texto": "#E6EDF5", "texto_sec": "#94A3B8", "tarjeta": "#16202E", "borde": "#26344A",
        "sombra": "rgba(0, 0, 0, .35)", "acento": "#4C9BE8",
        "hero": "linear-gradient(135deg, #12355C 0%, #1B5288 100%)", "hero_txt": "#C9DDF2",
        "ok_bg": "rgba(34,197,94,.16)", "ok_tx": "#86EFAC", "rev_bg": "rgba(245,158,11,.18)",
        "rev_tx": "#FCD34D", "crit_bg": "rgba(239,68,68,.18)", "crit_tx": "#FCA5A5",
        "plotly": "plotly_dark", "rejilla": "#26344A", "neutro": "#64748B",
    },
}
try:
    _tipo_tema = st.context.theme.type or "light"
except AttributeError:  # versiones antiguas de Streamlit
    _tipo_tema = "light"
OSCURO = _tipo_tema == "dark"
P = PALETAS["dark" if OSCURO else "light"]
AZUL = P["acento"]


def estilo_fig(fig, **kw):
    """Aplica el tema (claro/oscuro) a una figura Plotly con fondo transparente."""
    fig.update_layout(template=P["plotly"], paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font_color=P["texto"], **kw)
    fig.update_xaxes(gridcolor=P["rejilla"], zerolinecolor=P["rejilla"])
    fig.update_yaxes(gridcolor=P["rejilla"], zerolinecolor=P["rejilla"])
    return fig


# --------------------------------------------------------------------------- #
# Estilos
# --------------------------------------------------------------------------- #
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
      .kpi .lbl {{font-size: .80rem; color: {P["texto_sec"]}; text-transform: uppercase;
                 letter-spacing: .04em; font-weight: 600;}}
      .kpi .val {{font-size: 1.75rem; font-weight: 750; color: {P["texto"]}; margin-top: 4px;
                 white-space: nowrap;}}
      .kpi .det {{font-size: .82rem; color: {P["texto_sec"]}; margin-top: 2px;}}
      .kpi.azul  {{border-left: 5px solid {P["acento"]};}}
      .kpi.rojo  {{border-left: 5px solid #DC2626;}}
      .kpi.ambar {{border-left: 5px solid #F59E0B;}}
      .kpi.verde {{border-left: 5px solid #16A34A;}}
      .chip {{display:inline-block; padding: 3px 12px; border-radius: 999px; font-weight: 600;
             font-size: .85rem; margin-right: 6px;}}
      .chip.ok {{background:{P["ok_bg"]}; color:{P["ok_tx"]};}}
      .chip.rev {{background:{P["rev_bg"]}; color:{P["rev_tx"]};}}
      .chip.crit {{background:{P["crit_bg"]}; color:{P["crit_tx"]};}}
      .hero {{background: {P["hero"]}; color: #fff;
             border-radius: 16px; padding: 28px 32px; margin-bottom: 1rem;}}
      .hero h3 {{color: #fff; margin: 0 0 .4rem 0;}}
      .hero p {{color: {P["hero_txt"]}; margin: 0;}}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Utilidades de formato
# --------------------------------------------------------------------------- #
def eur(x: float, decimales: int = 2) -> str:
    if x is None or pd.isna(x):
        return "—"
    txt = f"{x:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{txt} €"


def num(x: float, decimales: int = 0) -> str:
    return f"{x:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x: float) -> str:
    return "—" if pd.isna(x) else f"{x * 100:+.1f} %".replace(".", ",")


def tarjeta(col, etiqueta: str, valor: str, detalle: str = "", color: str = "azul") -> None:
    col.markdown(
        f'<div class="kpi {color}"><div class="lbl">{etiqueta}</div>'
        f'<div class="val">{valor}</div><div class="det">{detalle}</div></div>',
        unsafe_allow_html=True,
    )


def firma_df(df: pd.DataFrame, nombre: str) -> str:
    return hashlib.md5((nombre + "|".join(map(str, df.columns)) + str(len(df))).encode()).hexdigest()[:10]


# --------------------------------------------------------------------------- #
# Estado de sesión
# --------------------------------------------------------------------------- #
db.init_db()
for clave, defecto in {
    "raw_df": None, "raw_nombre": None, "lote_base": None,
    "avisos": [], "mensaje": None, "plantilla_aplicada": None,
}.items():
    st.session_state.setdefault(clave, defecto)


def _mapeo_desde_widgets(firma: str) -> dict:
    mapeo = {}
    for campo in az.CAMPOS:
        v = st.session_state.get(f"map_{campo}_{firma}")
        mapeo[campo] = None if v in (None, SIN_ASIGNAR) else v
    return mapeo


def procesar(df_raw: pd.DataFrame, mapeo: dict, origen: str) -> None:
    """Aplica el mapeo, clasifica y guarda en el histórico SQLite."""
    try:
        base, avisos = az.aplicar_mapeo(df_raw, mapeo)
    except ValueError as e:
        st.session_state.mensaje = ("error", str(e))
        return
    if base.empty:
        st.session_state.mensaje = ("error", "No hay filas válidas tras aplicar el mapeo.")
        return
    clasificado = az.clasificar_descuadres(
        base, st.session_state.get("margen_ok", 2.0), st.session_state.get("umbral_critico", 15.0))
    res = db.guardar_registros(clasificado, origen=origen)
    st.session_state.lote_base = base
    st.session_state.avisos = avisos
    st.session_state.mensaje = (
        "success",
        f"**{origen}** analizado: {num(len(base))} operaciones. Histórico actualizado "
        f"({res['nuevos']} nuevas, {res['actualizados']} ya existentes actualizadas).",
    )


def cb_subida() -> None:
    archivo = st.session_state.get("uploader")
    if archivo is None:
        return
    try:
        df = az.leer_archivo(archivo)
    except Exception as e:  # noqa: BLE001 - se muestra al usuario
        st.session_state.mensaje = ("error", f"No se pudo leer el archivo: {e}")
        return
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    st.session_state.raw_df, st.session_state.raw_nombre = df, archivo.name
    st.session_state.lote_base = None
    st.session_state.plantilla_aplicada = None
    nombre, mapeo = az.plantilla_compatible(list(df.columns))
    if nombre and st.session_state.get("auto_plantilla", True):
        st.session_state.plantilla_aplicada = nombre
        procesar(df, mapeo, archivo.name)
    else:
        st.session_state.mensaje = ("info", "Archivo cargado. Revisa el mapeo de columnas y pulsa **Validar y analizar**.")


def cb_demo() -> None:
    df = sample_data.generar_datos()
    nombre = "Datos de demostración"
    st.session_state.raw_df, st.session_state.raw_nombre = df, nombre
    st.session_state.plantilla_aplicada = None
    procesar(df, az.sugerir_mapeo(list(df.columns)), nombre)


def cb_validar(firma: str) -> None:
    procesar(st.session_state.raw_df, _mapeo_desde_widgets(firma), st.session_state.raw_nombre)


def cb_guardar_plantilla(firma: str) -> None:
    nombre = (st.session_state.get("nombre_plantilla") or "").strip() or "IPS-Maq+ por defecto"
    mapeo = _mapeo_desde_widgets(firma)
    faltan = [d["etiqueta"] for c, d in az.CAMPOS.items() if d["obligatorio"] and not mapeo[c]]
    if faltan:
        st.session_state.mensaje = ("warning", "Asigna antes las columnas obligatorias: " + ", ".join(faltan))
        return
    try:
        az.guardar_plantilla(nombre, mapeo)
        st.session_state.mensaje = ("success", f"Plantilla **{nombre}** guardada en `config_columnas.json`. "
                                               "Las próximas subidas con estas columnas se analizarán solas.")
    except OSError as e:
        st.session_state.mensaje = ("error", f"No se pudo guardar la plantilla: {e}")


def cb_vaciar() -> None:
    db.vaciar_historico()
    st.session_state.lote_base = None
    st.session_state.mensaje = ("info", "Histórico vaciado.")


# --------------------------------------------------------------------------- #
# Barra lateral: parámetros
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown(f"### 🎰 {EMPRESA}")
    st.caption(f"{NOMBRE_APP} · exportaciones de IPS-Maq+")
    st.caption("🌓 **Modo oscuro**: menú ⋮ (arriba a la derecha) → *Dark*. Por defecto sigue el tema de tu sistema.")

    st.markdown("#### 🚦 Semáforo de descuadres")
    margen_ok = st.number_input("Margen OK (± €)", 0.0, 50.0, 2.0, 0.5, key="margen_ok",
                                help="Diferencias dentro de este margen se consideran cambio/monedas.")
    umbral_critico = st.number_input("Umbral crítico (€)", 1.0, 500.0, 15.0, 1.0, key="umbral_critico",
                                     help="Por encima de esta desviación la operación es una alerta crítica.")
    if umbral_critico <= margen_ok:
        st.warning("El umbral crítico debe ser mayor que el margen OK.")

    st.markdown("#### 📉 Caídas de rendimiento")
    umbral_caida = st.slider("Alerta si cae más de…", 5, 80, 25, 5, format="%d %%",
                             help="Caída de la última recaudación respecto a su media móvil.")
    ventana = st.slider("Ventana de la media móvil (recaudaciones)", 3, 20, 8,
                        help="Nº de recaudaciones anteriores usadas para calcular la media habitual.")

    st.markdown("#### ⏱️ Ahorro de tiempo")
    minutos = st.number_input("Minutos de revisión manual por operación", 0.5, 10.0, 1.5, 0.5)

    st.markdown("#### ⚙️ Carga")
    st.toggle("Analizar automáticamente si hay plantilla", value=True, key="auto_plantilla")

    st.divider()
    st.markdown("#### 🗄️ Histórico (SQLite)")
    info = db.resumen_db()
    if info["registros"]:
        st.caption(
            f"**{num(info['registros'])}** registros · {info['bares']} bares · {info['maquinas']} máquinas  \n"
            f"Del {pd.to_datetime(info['desde']):%d/%m/%Y} al {pd.to_datetime(info['hasta']):%d/%m/%Y}"
        )
        with st.popover("Vaciar histórico", icon="🗑️"):
            st.write("Se borrarán todos los registros guardados. Esta acción no se puede deshacer.")
            st.button("Sí, vaciar", type="primary", on_click=cb_vaciar)
    else:
        st.caption("Aún no hay registros guardados.")

# --------------------------------------------------------------------------- #
# Cabecera
# --------------------------------------------------------------------------- #
st.markdown(f'<div class="marca">{EMPRESA}</div><div class="titulo">{NOMBRE_APP}</div>',
            unsafe_allow_html=True)
st.markdown(
    '<div class="subtitulo">Detecta descuadres entre contadores y efectivo, vigila caídas de recaudación '
    'por bar y máquina y genera el informe ejecutivo en segundos.</div>',
    unsafe_allow_html=True,
)

if st.session_state.mensaje:
    tipo, texto = st.session_state.mensaje
    getattr(st, tipo)(texto)
    st.session_state.mensaje = None
for aviso in st.session_state.avisos:
    st.warning(aviso)

# --------------------------------------------------------------------------- #
# Cálculos principales
# --------------------------------------------------------------------------- #
lote = None
hist = db.cargar_historico()
caidas = pd.DataFrame()
kpis = None
if st.session_state.lote_base is not None:
    lote = az.clasificar_descuadres(st.session_state.lote_base, margen_ok, umbral_critico)
if not hist.empty:
    caidas = az.detectar_caidas(hist, umbral_caida / 100, "bar", ventana)
    caidas_maq = az.detectar_caidas(hist, umbral_caida / 100, "maquina", ventana)
if lote is not None:
    kpis = az.calcular_kpis(lote, caidas, minutos)

# --------------------------------------------------------------------------- #
# Tarjetas KPI
# --------------------------------------------------------------------------- #
if kpis:
    c1, c2, c3, c4 = st.columns(4)
    tarjeta(c1, "Total recaudado", eur(kpis["total_recaudado"], 0),
            f"{num(kpis['registros'])} operaciones · {kpis['desde']:%d/%m/%y}–{kpis['hasta']:%d/%m/%y}", "azul")
    tarjeta(c2, "Descuadres detectados", eur(kpis["total_descuadres"]),
            f"{kpis['n_critico']} críticos · {kpis['n_revisar']} a revisar",
            "rojo" if kpis["n_critico"] else ("ambar" if kpis["n_revisar"] else "verde"))
    tarjeta(c3, "Bares en alerta de caída", str(kpis["bares_en_alerta"]),
            f"Caída > {umbral_caida} % vs media móvil", "rojo" if kpis["bares_en_alerta"] else "verde")
    tarjeta(c4, "Ahorro estimado", f"{num(kpis['horas_ahorradas'], 1)} h",
            f"de auditoría manual ({num(minutos, 1)} min/operación)", "verde")
    st.write("")
else:
    st.markdown(
        '<div class="hero"><h3>👋 Empieza en 10 segundos</h3>'
        '<p>Sube un listado de recaudaciones exportado de IPS-Maq+ (Excel o CSV) o pulsa '
        '<b>Cargar datos de demostración</b> para ver la herramienta en acción con datos ficticios.</p></div>',
        unsafe_allow_html=True,
    )

tab_carga, tab_desc, tab_caidas, tab_inf = st.tabs(
    ["📥 Carga y mapeo", "🚦 Descuadres", "📉 Caídas de rendimiento", "📊 Informe ejecutivo"])

# --------------------------------------------------------------------------- #
# TAB 1 · Carga inteligente
# --------------------------------------------------------------------------- #
with tab_carga:
    col_up, col_demo = st.columns([3, 1.3], gap="large")
    with col_up:
        st.file_uploader(
            "Sube el listado de recaudaciones / arqueos (.xlsx, .xls, .csv)",
            type=["xlsx", "xls", "csv"], key="uploader", on_change=cb_subida,
        )
    with col_demo:
        st.markdown("**¿No tienes un Excel a mano?**")
        st.button("🎲 Cargar datos de demostración", type="primary", on_click=cb_demo, width="stretch")
        st.caption("15 bares · 30 máquinas · 3 meses ficticios con descuadres y caídas provocadas.")

    raw = st.session_state.raw_df
    if raw is not None:
        nombre = st.session_state.raw_nombre
        firma = firma_df(raw, nombre)
        st.markdown(f"#### Archivo: `{nombre}`  ·  {num(len(raw))} filas × {len(raw.columns)} columnas")
        with st.expander("👀 Vista previa del archivo original", expanded=False):
            st.dataframe(raw.head(50), hide_index=True)

        columnas = list(raw.columns)
        if st.session_state.plantilla_aplicada:
            _, mapeo_ini = az.plantilla_compatible(columnas)
            st.success(f"Plantilla **{st.session_state.plantilla_aplicada}** reconocida y aplicada automáticamente.")
        else:
            mapeo_ini = az.sugerir_mapeo(columnas)

        st.markdown("#### 🧭 Mapeo de columnas")
        st.caption("Indica qué columna de tu exportación corresponde a cada dato. "
                   "Se propone una asignación automática a partir de los nombres habituales de IPS-Maq+.")
        opciones = [SIN_ASIGNAR] + columnas
        cols = st.columns(3)
        for i, (campo, meta) in enumerate(az.CAMPOS.items()):
            actual = (mapeo_ini or {}).get(campo)
            cols[i % 3].selectbox(
                meta["etiqueta"] + (" *" if meta["obligatorio"] else ""),
                opciones,
                index=opciones.index(actual) if actual in opciones else 0,
                key=f"map_{campo}_{firma}",
            )

        b1, b2, b3 = st.columns([1.2, 1.6, 1])
        b1.button("✅ Validar y analizar", type="primary", on_click=cb_validar, args=(firma,), width="stretch")
        b2.text_input("Nombre de la plantilla", value="IPS-Maq+ Recaudaciones", key="nombre_plantilla",
                      label_visibility="collapsed", placeholder="Nombre de la plantilla")
        b3.button("💾 Guardar como plantilla", on_click=cb_guardar_plantilla, args=(firma,), width="stretch")

        plantillas = az.cargar_plantillas()
        if plantillas:
            st.caption("Plantillas guardadas: " + ", ".join(f"`{p}`" for p in plantillas))

# --------------------------------------------------------------------------- #
# TAB 2 · Descuadres
# --------------------------------------------------------------------------- #
ESTILO_FILA = {
    az.ESTADO_CRITICO: f"background-color: {P['crit_bg']}; color: {P['crit_tx']};",
    az.ESTADO_REVISAR: f"background-color: {P['rev_bg']}; color: {P['rev_tx']};",
    az.ESTADO_OK: "",
}

with tab_desc:
    if lote is None:
        st.info("Carga un archivo o los datos de demostración para ver el análisis de descuadres.")
    else:
        st.markdown(
            f'<span class="chip crit">🔴 Crítico: {kpis["n_critico"]}</span>'
            f'<span class="chip rev">🟠 Revisar: {kpis["n_revisar"]}</span>'
            f'<span class="chip ok">🟢 OK: {kpis["n_ok"]}</span>'
            f'&nbsp; Descuadre neto del periodo: <b>{eur(kpis["descuadre_neto"])}</b>',
            unsafe_allow_html=True,
        )
        st.write("")

        g1, g2 = st.columns([2.2, 1])
        inc = lote[lote["estado"] != az.ESTADO_OK]
        with g1:
            if inc.empty:
                st.success("Sin descuadres fuera de margen. ✔")
            else:
                por_bar = (inc.assign(importe=inc["diferencia"].abs())
                              .groupby(["bar", "estado"], as_index=False)["importe"].sum())
                orden = por_bar.groupby("bar")["importe"].sum().sort_values().index.tolist()
                fig = px.bar(por_bar, x="importe", y="bar", color="estado", orientation="h",
                             color_discrete_map=az.COLOR_ESTADO, category_orders={"bar": orden},
                             labels={"importe": "Importe descuadrado (€)", "bar": "", "estado": "Estado"},
                             title="Importe en descuadre por establecimiento")
                estilo_fig(fig, height=360, margin=dict(l=10, r=10, t=50, b=10),
                                  legend=dict(orientation="h", y=-0.2), yaxis=dict(categoryorder="array",
                                                                                     categoryarray=orden))
                st.plotly_chart(fig, width="stretch")
        with g2:
            dist = lote["estado"].value_counts().reindex(
                [az.ESTADO_OK, az.ESTADO_REVISAR, az.ESTADO_CRITICO]).fillna(0)
            fig = go.Figure(go.Pie(labels=dist.index, values=dist.values, hole=.62, sort=False,
                                   marker=dict(colors=[az.COLOR_ESTADO[e] for e in dist.index]),
                                   textinfo="none",
                                   hovertemplate="%{label}: %{value} (%{percent})<extra></extra>"))
            estilo_fig(fig, height=360, margin=dict(l=10, r=10, t=50, b=10),
                              title="Distribución del semáforo", showlegend=True,
                              legend=dict(orientation="h", y=-0.1),
                              annotations=[dict(text=f"<b>{len(lote)}</b><br>operaciones",
                                                showarrow=False, font_size=14)])
            st.plotly_chart(fig, width="stretch")

        f1, f2 = st.columns([1.3, 2])
        estados = f1.multiselect("Estado", [az.ESTADO_CRITICO, az.ESTADO_REVISAR, az.ESTADO_OK],
                                 default=[az.ESTADO_CRITICO, az.ESTADO_REVISAR])
        bares = f2.multiselect("Establecimiento", sorted(lote["bar"].unique()), placeholder="Todos")
        vista = lote[lote["estado"].isin(estados)]
        if bares:
            vista = vista[vista["bar"].isin(bares)]
        orden_estado = {az.ESTADO_CRITICO: 0, az.ESTADO_REVISAR: 1, az.ESTADO_OK: 2}
        vista = (vista.assign(_o=vista["estado"].map(orden_estado), _a=-vista["diferencia"].abs())
                      .sort_values(["_o", "_a", "fecha"]))
        tabla = pd.DataFrame({
            "Fecha": vista["fecha"].dt.strftime("%d/%m/%Y"), "Bar": vista["bar"], "Máquina": vista["maquina"],
            "Teórico": vista["teorico"], "Real": vista["real"], "Diferencia": vista["diferencia"],
            "Liquidación bar": vista["liquidacion_bar"], "Estado": vista["estado"], "Motivo": vista["motivo"],
        })
        if lote["liquidacion_bar"].isna().all():
            tabla = tabla.drop(columns="Liquidación bar")
        estilo = (tabla.style
                  .apply(lambda fila: [ESTILO_FILA.get(fila["Estado"], "")] * len(fila), axis=1)
                  .format({c: eur for c in ["Teórico", "Real", "Diferencia", "Liquidación bar"]
                           if c in tabla}))
        st.caption(f"{num(len(tabla))} operaciones mostradas")
        st.dataframe(estilo, hide_index=True, height=min(38 + 35 * max(len(tabla), 1), 520))

# --------------------------------------------------------------------------- #
# TAB 3 · Caídas de rendimiento
# --------------------------------------------------------------------------- #
with tab_caidas:
    if hist.empty:
        st.info("El histórico está vacío. Carga datos para empezar a calcular medias móviles.")
    else:
        nivel = st.segmented_control("Nivel de análisis", ["Por bar", "Por máquina"], default="Por bar",
                                     required=True)
        tabla_c = caidas if nivel == "Por bar" else caidas_maq
        alertas = tabla_c[tabla_c["alerta"] == True]
        st.caption(f"Se compara la última recaudación (contadores) de cada "
                   f"{'bar' if nivel == 'Por bar' else 'máquina'} con la media de sus {ventana} recaudaciones "
                   f"anteriores. Histórico: {num(len(hist))} registros.")

        if alertas.empty:
            st.success(f"Ninguna caída superior al {umbral_caida} %. ✔")
        else:
            st.error(f"**{len(alertas)}** {'bares' if nivel == 'Por bar' else 'máquinas'} con caída "
                     f"superior al {umbral_caida} % respecto a su media habitual.")

        validos = tabla_c.dropna(subset=["variacion"]).copy()
        validos["entidad"] = validos["bar"] if nivel == "Por bar" else validos["maquina"] + " · " + validos["bar"]
        validos = validos.sort_values("variacion")
        col_g, col_t = st.columns([1, 1.3])
        with col_g:
            fig = go.Figure(go.Bar(
                x=validos["variacion"] * 100, y=validos["entidad"], orientation="h",
                marker_color=["#DC2626" if a else P["neutro"] for a in validos["alerta"]],
                hovertemplate="%{y}<br>Variación: %{x:.1f} %<extra></extra>",
            ))
            fig.add_vline(x=-umbral_caida, line_dash="dash", line_color="#DC2626",
                          annotation_text=f"-{umbral_caida} %", annotation_position="top")
            estilo_fig(fig, title="Última recaudación vs media móvil (%)",
                              height=max(360, 22 * len(validos) + 80), margin=dict(l=10, r=10, t=50, b=10),
                              xaxis_title="Variación (%)", yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width="stretch")
        with col_t:
            t = pd.DataFrame({
                "Bar": tabla_c["bar"], "Máquina": tabla_c["maquina"],
                "Última": tabla_c["fecha_ultima"].dt.strftime("%d/%m/%Y"),
                "Importe": tabla_c["ultima_recaudacion"], "Media": tabla_c["media_historica"],
                "Variación": tabla_c["variacion"], "Diagnóstico": tabla_c["diagnostico"],
                "_alerta": tabla_c["alerta"],
            })
            if nivel == "Por bar":
                t = t.drop(columns="Máquina")
            estilo = (t.style
                      .apply(lambda f: [ESTILO_FILA[az.ESTADO_CRITICO] if f["_alerta"] else ""]
                             * len(f), axis=1)
                      .format({"Importe": eur, "Media": eur, "Variación": pct})
                      .hide(["_alerta"], axis="columns"))
            st.dataframe(estilo, hide_index=True, height=max(360, 22 * len(validos) + 80))

        st.markdown("#### 🔎 Evolución detallada")
        nivel_cod = "bar" if nivel == "Por bar" else "maquina"
        serie = az.serie_con_media_movil(hist, nivel_cod, ventana)
        if nivel_cod == "bar":
            serie["entidad"] = serie["bar"]
        else:
            serie["entidad"] = serie["maquina"] + " · " + serie["bar"]
        opciones = validos["entidad"].tolist() or sorted(serie["entidad"].unique())
        elegido = st.selectbox("Selecciona bar / máquina (ordenados de peor a mejor)", opciones)
        s = serie[serie["entidad"] == elegido]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=s["fecha"], y=s["media_movil"] * (1 - umbral_caida / 100),
                                 name=f"Umbral de alerta (-{umbral_caida} %)",
                                 line=dict(color="#DC2626", dash="dot", width=1.5)))
        fig.add_trace(go.Scatter(x=s["fecha"], y=s["media_movil"], name=f"Media móvil ({ventana})",
                                 line=dict(color="#F59E0B", width=2.5)))
        fig.add_trace(go.Scatter(x=s["fecha"], y=s["recaudacion"], name="Recaudación (contadores)",
                                 mode="lines+markers", line=dict(color=AZUL, width=2.5)))
        estilo_fig(fig, height=380, margin=dict(l=10, r=10, t=30, b=10),
                          yaxis_title="€", legend=dict(orientation="h", y=-0.2), hovermode="x unified")
        st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------- #
# TAB 4 · Informe ejecutivo
# --------------------------------------------------------------------------- #
with tab_inf:
    if lote is None:
        st.info("Carga datos para generar el informe ejecutivo.")
    else:
        parametros = {
            "Archivo analizado": st.session_state.raw_nombre,
            "Margen OK (€)": num(margen_ok, 2),
            "Umbral crítico (€)": num(umbral_critico, 2),
            "Umbral de caída": f"{umbral_caida} %",
            "Ventana media móvil": ventana,
            "Nivel de análisis de caídas": "Por bar",
        }
        informe = az.exportar_informe_excel(lote, caidas, kpis, parametros)
        c1, c2 = st.columns([1.4, 1])
        with c1:
            st.markdown("#### 📊 Informe para gerencia")
            st.markdown(
                "Excel con tres pestañas listo para presentar:\n"
                "- **Resumen_Ejecutivo**: KPIs, parámetros y resumen por establecimiento.\n"
                "- **Descuadres_Criticos**: operaciones en rojo y ámbar, ordenadas por gravedad.\n"
                "- **Bares_En_Riesgo**: establecimientos con caída frente a su media móvil.\n\n"
                "Cabeceras corporativas, columnas autoajustadas, formato moneda € y filtros."
            )
            st.download_button(
                "⬇️ Descargar informe Excel", data=informe, type="primary",
                file_name=f"Informe_Auditoria_{datetime.now():%Y%m%d_%H%M}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with c2:
            st.markdown("#### Resumen")
            st.markdown(
                f"- Periodo: **{kpis['desde']:%d/%m/%Y} – {kpis['hasta']:%d/%m/%Y}**\n"
                f"- Recaudado: **{eur(kpis['total_recaudado'])}** (teórico {eur(kpis['total_teorico'])})\n"
                f"- Descuadres: **{kpis['n_critico']} críticos** y **{kpis['n_revisar']} a revisar** "
                f"({eur(kpis['total_descuadres'])})\n"
                f"- Bares en riesgo: **{kpis['bares_en_alerta']}**\n"
                f"- Ahorro estimado: **{num(kpis['horas_ahorradas'], 1)} h** de revisión manual"
            )

st.divider()
st.caption(f"{EMPRESA} · {NOMBRE_APP} · Python, Streamlit, Pandas, Plotly y SQLite · "
           "Los datos se procesan localmente; los datos de demostración son ficticios.")
