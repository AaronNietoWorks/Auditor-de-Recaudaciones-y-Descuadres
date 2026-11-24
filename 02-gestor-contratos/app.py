"""
app.py — Gestor de Contratos y Préstamos a Hosteleros (IPS-Maq+)
=================================================================
Interfaz Streamlit. Ejecuta:  streamlit run app.py
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analyzer as az
import database as db
import sample_data

st.set_page_config(
    page_title="Gestor de Contratos",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded",
)

SIN_ASIGNAR = "— Sin asignar —"
AZUL = "#0F4C81"
ICONO_CONTRATO = {az.VENCIDO: "⛔", az.URGENTE: "🔴", az.PROXIMO: "🟠", az.PLANIFICAR: "🔵", az.VIGENTE: "🟢"}
ICONO_PRESTAMO = {az.P_CRITICO: "🔴", az.P_RIESGO: "🟠", az.P_AL_DIA: "🟢", az.P_AMORTIZADO: "⚪"}

# --------------------------------------------------------------------------- #
# Estilos (mismos que el Auditor de Recaudaciones)
# --------------------------------------------------------------------------- #
st.markdown(
    """
    <style>
      .block-container {padding-top: 3.2rem; padding-bottom: 3rem; max-width: 1400px;}
      .titulo {font-size: 1.9rem; font-weight: 750; color: #0F2A4A; margin-bottom: 0;}
      .subtitulo {color: #64748B; margin-top: .15rem; margin-bottom: 1.2rem;}
      .kpi {background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 14px;
            padding: 18px 20px; box-shadow: 0 1px 3px rgba(15, 42, 74, .06); height: 100%;}
      .kpi .lbl {font-size: .78rem; color: #64748B; text-transform: uppercase;
                 letter-spacing: .04em; font-weight: 600;}
      .kpi .val {font-size: 1.6rem; font-weight: 750; color: #0F2A4A; margin-top: 4px;
                 white-space: nowrap;}
      .kpi .det {font-size: .80rem; color: #64748B; margin-top: 2px;}
      .kpi.azul  {border-left: 5px solid #0F4C81;}
      .kpi.rojo  {border-left: 5px solid #DC2626;}
      .kpi.ambar {border-left: 5px solid #F59E0B;}
      .kpi.verde {border-left: 5px solid #16A34A;}
      .chip {display:inline-block; padding: 3px 12px; border-radius: 999px; font-weight: 600;
             font-size: .85rem; margin: 0 6px 6px 0;}
      .chip.venc {background:#F5D0D0; color:#7F1D1D;}
      .chip.crit {background:#FDE2E2; color:#991B1B;}
      .chip.rev {background:#FEF3C7; color:#92400E;}
      .chip.plan {background:#DBEAFE; color:#1E3A8A;}
      .chip.ok {background:#DCFCE7; color:#166534;}
      .chip.gris {background:#F1F5F9; color:#475569;}
      .hero {background: linear-gradient(135deg, #0F4C81 0%, #1E6FB8 100%); color: #fff;
             border-radius: 16px; padding: 28px 32px; margin-bottom: 1rem;}
      .hero h3 {color: #fff; margin: 0 0 .4rem 0;}
      .hero p {color: #E0ECF8; margin: 0;}
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


def fecha(x) -> str:
    return "—" if x is None or pd.isna(x) else f"{pd.Timestamp(x):%d/%m/%Y}"


def tarjeta(col, etiqueta: str, valor: str, detalle: str = "", color: str = "azul") -> None:
    col.markdown(
        f'<div class="kpi {color}"><div class="lbl">{etiqueta}</div>'
        f'<div class="val">{valor}</div><div class="det">{detalle}</div></div>',
        unsafe_allow_html=True,
    )


def firma(df: pd.DataFrame, nombre: str) -> str:
    return hashlib.md5((nombre + "|".join(map(str, df.columns)) + str(len(df))).encode()).hexdigest()[:10]


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
    """Aplica el mapeo y guarda el listado en SQLite."""
    try:
        limpio, avisos = az.aplicar_mapeo(ds, df_raw, mapeo,
                                          duracion_defecto=st.session_state.get("duracion_contrato", 60))
    except ValueError as e:
        avisar("error", f"**{az.DATASETS[ds]['titulo']}**: {e}")
        return False
    if limpio.empty:
        avisar("error", f"**{az.DATASETS[ds]['titulo']}**: no hay filas válidas tras aplicar el mapeo.")
        return False
    st.session_state.avisos += [f"{az.DATASETS[ds]['titulo']}: {a}" for a in avisos]
    if ds == "recaudacion":
        r = db.guardar_recaudacion(limpio, origen)
        avisar("success", f"**Recaudación** de `{origen}` guardada: {r['nuevos']} meses nuevos y "
                          f"{r['actualizados']} actualizados en el histórico.")
    else:
        n = db.guardar_cartera(ds, limpio, origen)
        avisar("success", f"**{az.DATASETS[ds]['titulo']}**: {num(n)} registros cargados desde `{origen}` "
                          "(sustituyen a la cartera anterior).")
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
    for ds, hoja in (("contratos", "Contratos"), ("prestamos", "Prestamos"),
                     ("recaudacion", "Recaudacion_Mensual")):
        df = datos[hoja]
        procesar(ds, df, az.sugerir_mapeo(ds, list(df.columns)), "Datos de demostración")
    st.session_state.mensajes = [("success", "**Datos de demostración cargados**: 25 contratos, 12 préstamos y "
                                             "12 meses de recaudación ficticios.")]


def cb_guardar_seguimiento(filas: list[tuple[str, str, str]]) -> None:
    n = db.guardar_seguimiento(filas)
    st.session_state.ver_seg = st.session_state.get("ver_seg", 0) + 1
    avisar("success", f"Seguimiento guardado ({n} contratos actualizados).")


def cb_vaciar() -> None:
    db.vaciar_todo()
    avisar("info", "Base de datos vaciada.")


# --------------------------------------------------------------------------- #
# Barra lateral: parámetros
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### 📑 Gestor de Contratos")
    st.caption("Vencimientos y préstamos a hosteleros · IPS-Maq+")

    fecha_ref = st.date_input("Fecha de referencia", value=date.today(), format="DD/MM/YYYY", key="fecha_ref",
                              help="Normalmente hoy. Cámbiala para ver cómo estará la cartera en otra fecha.")

    st.markdown("#### 🚦 Ventanas de aviso (días)")
    u1 = st.number_input("🔴 Urgente si vence en menos de…", 1, 365, 30, 5)
    u2 = st.number_input("🟠 Próximo si vence en menos de…", 1, 730, 60, 5)
    u3 = st.number_input("🔵 Planificar si vence en menos de…", 1, 1095, 90, 5)
    if not u1 < u2 < u3:
        st.warning("Las ventanas deben ser crecientes: Urgente < Próximo < Planificar.")
    st.number_input("Duración del contrato (meses)", 6, 240, az.DURACION_CONTRATO_MESES, 6,
                    key="duracion_contrato",
                    help="Se usa solo si el listado no trae fecha de vencimiento: vencimiento = alta + duración.")
    meses_prorroga = st.number_input("Prórroga tácita (meses, 0 = no se aplica)", 0, 120, 0,
                                     help="Por defecto 0: en la Comunitat Valenciana la autorización de instalación "
                                          "no se renueva sola (hay que solicitarla), así que un contrato vencido se "
                                          "trata como vencido aunque diga «prórroga automática». Pon 12, 60… si "
                                          "vuestros contratos con el bar sí se prorrogan solos.")
    st.caption("⚖️ Normativa: Comunitat Valenciana (Vega Baja). Máx. "
               f"{az.MAX_MAQUINAS_B_HOSTELERIA} máquinas tipo B por bar.")

    st.markdown("#### 💶 Préstamos")
    periodicidad = st.radio("Descuento de la cuota", az.PERIODICIDADES, horizontal=True,
                            format_func=lambda x: f"{x} (de la recaudación)" if x == az.SEMANAL else x,
                            help="Cada cuánto se descuenta la cuota de la recaudación de la máquina. "
                                 "La cuota y el nº de cuotas del listado se interpretan en esta periodicidad.")
    unidad = "semanas" if periodicidad == az.SEMANAL else "cuotas mensuales"
    tolerancia = st.number_input(f"Riesgo a partir de… ({unidad} sin descontar)", 0.5, 52.0,
                                 2.0 if periodicidad == az.SEMANAL else 1.0, 0.5)
    critico = st.number_input(f"Crítico a partir de… ({unidad} sin descontar)", 1.0, 104.0,
                              6.0 if periodicidad == az.SEMANAL else 3.0, 0.5)

    st.markdown("#### ⏱️ Ahorro de tiempo")
    minutos = st.number_input("Minutos de revisión manual por contrato/préstamo", 0.5, 15.0, 3.0, 0.5)

    st.markdown("#### ⚙️ Carga")
    st.toggle("Cargar automáticamente si hay plantilla", value=True, key="auto_plantilla")

    st.divider()
    st.markdown("#### 🗄️ Base de datos (SQLite)")
    info = db.resumen_db()
    nombres = {"contratos": "Contratos", "prestamos": "Préstamos", "recaudacion_mensual": "Recaudación (meses)"}
    if info["cargas"]:
        lineas = []
        for t, etiqueta in nombres.items():
            if t in info["cargas"]:
                origen, n, cuando = info["cargas"][t]
                lineas.append(f"**{etiqueta}**: {num(n)} · {pd.Timestamp(cuando):%d/%m %H:%M}")
        lineas.append(f"**Seguimientos anotados**: {info['seguimientos']}")
        st.caption("  \n".join(lineas))
        with st.popover("Vaciar base de datos", icon="🗑️"):
            st.write("Se borrarán contratos, préstamos, recaudación y notas de seguimiento. "
                     "Esta acción no se puede deshacer.")
            st.button("Sí, vaciar", type="primary", on_click=cb_vaciar)
    else:
        st.caption("Aún no hay datos guardados.")

# --------------------------------------------------------------------------- #
# Cabecera y mensajes
# --------------------------------------------------------------------------- #
st.markdown('<div class="titulo">Gestor de Contratos y Préstamos a Hosteleros</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitulo">Anticipa los vencimientos de contratos, controla lo que te deben los '
    'establecimientos y detecta a tiempo el dinero en riesgo.</div>',
    unsafe_allow_html=True,
)
for tipo, texto in st.session_state.mensajes:
    getattr(st, tipo)(texto)
for aviso in st.session_state.avisos:
    st.warning(aviso)
st.session_state.mensajes, st.session_state.avisos = [], []

# --------------------------------------------------------------------------- #
# Cálculos principales
# --------------------------------------------------------------------------- #
umbrales = (u1, u2, u3) if u1 < u2 < u3 else (30, 60, 90)
contratos_db = db.cargar_cartera("contratos")
prestamos_db = db.cargar_cartera("prestamos")
rec_db = db.cargar_recaudacion()

cont = az.evaluar_contratos(contratos_db, fecha_ref, umbrales, meses_prorroga) if not contratos_db.empty else None
prest = (az.evaluar_prestamos(prestamos_db, cont, fecha_ref, tolerancia, critico, periodicidad)
         if not prestamos_db.empty else None)
hay_rec = not rec_db.empty
if cont is not None and hay_rec:
    cont, prest = az.cruzar_recaudacion(cont, prest, az.recaudacion_mensual(rec_db, fecha_ref))
elif prest is not None and hay_rec:
    _, prest = az.cruzar_recaudacion(pd.DataFrame(columns=["clave_bar"]), prest,
                                     az.recaudacion_mensual(rec_db, fecha_ref))
if cont is not None:
    seg = db.cargar_seguimiento()
    cont = cont.merge(seg[["id_contrato", "gestion", "nota"]], on="id_contrato", how="left")
    cont["gestion"] = cont["gestion"].fillna("Sin gestionar")
    cont["nota"] = cont["nota"].fillna("")
calendario = az.calendario_amortizacion(prest, fecha_ref, 24, periodicidad) if prest is not None else None
kpis = az.calcular_kpis(cont, prest, minutos)
hay_datos = cont is not None or prest is not None

# --------------------------------------------------------------------------- #
# Tarjetas KPI
# --------------------------------------------------------------------------- #
if hay_datos:
    c1, c2, c3, c4, c5 = st.columns(5)
    tarjeta(c1, "Por renovar", num(kpis["en_ventana"]),
            f"{kpis['n_vencidos']} vencidos · {kpis['n_urgentes']} en ≤ {umbrales[0]} d · "
            f"de {kpis['n_contratos']}",
            "rojo" if kpis["n_vencidos"] or kpis["n_urgentes"] else ("ambar" if kpis["en_ventana"] else "verde"))
    if not pd.isna(kpis["rec_en_juego"]):
        tarjeta(c2, "Recaudación en juego", eur(kpis["rec_en_juego"], 0),
                f"al año, de los contratos a renovar (≤ {umbrales[2]} d)", "ambar")
    else:
        tarjeta(c2, "Contratos vigentes", num(kpis["n_vigentes"]),
                "Carga la recaudación para valorar cada renovación", "azul")
    tarjeta(c3, "Capital pendiente", eur(kpis["capital_pendiente"], 0),
            f"{kpis['n_activos']} préstamos activos de {kpis['n_prestamos']}", "azul")
    tarjeta(c4, "Capital en riesgo", eur(kpis["capital_riesgo"], 0),
            f"{kpis['n_criticos']} críticos · {kpis['n_riesgo']} en riesgo · {eur(kpis['retraso_total'], 0)} atrasado",
            "rojo" if kpis["n_criticos"] else ("ambar" if kpis["n_riesgo"] else "verde"))
    tarjeta(c5, "Ahorro estimado", f"{num(kpis['horas_ahorradas'], 1)} h",
            f"por revisión ({num(minutos, 1)} min por registro)", "verde")
    st.write("")
else:
    st.markdown(
        '<div class="hero"><h3>👋 Empieza en 10 segundos</h3>'
        '<p>Sube el listado de contratos (y, si quieres, el de préstamos y la recaudación) exportado de '
        'IPS-Maq+, o pulsa <b>Cargar datos de demostración</b> para verlo funcionar con datos ficticios.</p></div>',
        unsafe_allow_html=True,
    )

tab_carga, tab_venc, tab_prest, tab_inf = st.tabs(
    ["📥 Carga y mapeo", "📅 Vencimientos", "💶 Préstamos", "📊 Informe ejecutivo"],
    key="pestana", on_change="rerun")

# --------------------------------------------------------------------------- #
# TAB 1 · Carga inteligente
# --------------------------------------------------------------------------- #
with tab_carga:
    col_txt, col_demo = st.columns([3, 1.3], gap="large")
    with col_txt:
        st.markdown(
            "Sube cada listado exportado de IPS-Maq+ en su apartado. **Solo el de contratos es imprescindible**; "
            "los préstamos y la recaudación añaden el control de deudas y el valor de cada renovación. "
            "Si tienes un único Excel con varias hojas, súbelo en los tres apartados y elige la hoja en cada uno."
        )
    with col_demo:
        st.markdown("**¿No tienes un Excel a mano?**")
        st.button("🎲 Cargar datos de demostración", type="primary", on_click=cb_demo, width="stretch")
        st.caption("25 contratos · 12 préstamos · 12 meses de recaudación ficticios.")

    iconos = {"contratos": "📄", "prestamos": "💶", "recaudacion": "💰"}
    for ds, meta in az.DATASETS.items():
        cargado = {"contratos": not contratos_db.empty, "prestamos": not prestamos_db.empty,
                   "recaudacion": hay_rec}[ds]
        with st.expander(f"{iconos[ds]} {meta['titulo']}" + ("  ✅" if cargado else ""),
                         expanded=(ds == "contratos" and not cargado) or st.session_state[f"raw_{ds}"] is not None):
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
            vista_previa = raw.head(8).copy()
            for c in vista_previa.select_dtypes(include="datetime").columns:
                vista_previa[c] = vista_previa[c].dt.strftime("%d/%m/%Y")
            st.dataframe(vista_previa, hide_index=True)

            columnas = list(raw.columns)
            if st.session_state[f"plantilla_{ds}"]:
                _, mapeo_ini = az.plantilla_compatible(ds, columnas)
                st.success(f"Plantilla **{st.session_state[f'plantilla_{ds}']}** reconocida y aplicada.")
            else:
                mapeo_ini = az.sugerir_mapeo(ds, columnas)
            st.markdown("**🧭 Mapeo de columnas** · propuesto a partir de los nombres habituales de IPS-Maq+")
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
            b2.text_input("Nombre de la plantilla", value=f"IPS-Maq+ {meta['titulo'].split(' ')[0]}",
                          key=f"nombre_plantilla_{ds}", label_visibility="collapsed")
            b3.button("💾 Guardar como plantilla", on_click=cb_plantilla, args=(ds, fm), width="stretch",
                      key=f"pl_{ds}")
            plantillas = az.cargar_plantillas(ds)
            if plantillas:
                st.caption("Plantillas guardadas: " + ", ".join(f"`{p}`" for p in plantillas))

    with st.expander("ℹ️ Cómo se interpretan los datos (supuestos)"):
        st.markdown(
            (f"- **Vencimiento efectivo**: si el contrato tiene prórroga automática y su fecha ya pasó, se "
               f"considera prorrogado tácitamente por periodos de {meses_prorroga} meses.\n" if meses_prorroga else
               "- **Sin prórroga tácita**: un contrato cuya fecha ya pasó figura como vencido aunque tenga prórroga "
               "automática, porque en la Comunitat Valenciana la renovación de la autorización de instalación "
               "hay que solicitarla.\n")
            + f"- **Máquinas por bar**: se avisa si un contrato tiene más de {az.MAX_MAQUINAS_B_HOSTELERIA} "
              "máquinas (máximo de tipo B en hostelería en la Comunitat Valenciana).\n"
            + f"- **Ventanas**: vencido (< 0 días), urgente (≤ {umbrales[0]}), próximo (≤ {umbrales[1]}), "
            f"planificar (≤ {umbrales[2]}), vigente (resto).\n"
            f"- **Contratos**: duración estándar de {st.session_state.get('duracion_contrato', 60)} meses "
            "(solo se usa si falta la fecha de vencimiento). En la Comunitat Valenciana rigen la Ley 1/2020 "
            "de juego y el Reglamento de máquinas (Decreto 115/2006); detalles y fuentes en el README.\n"
            f"- **Préstamos**: se devuelven en cuotas iguales descontadas de la recaudación "
            f"**{periodicidad.lower()}** de la máquina; la primera cuota se devenga un periodo después de la "
            "concesión. Si falta la cuota se calcula con el nº de cuotas, y si faltan ambos se asumen 36 meses.\n"
            "- **Retraso** = lo que debería estar devuelto a la fecha de referencia − lo realmente amortizado.\n"
            "- **Saldo al vencer contrato**: lo que quedaría por devolver el día que vence el contrato si se "
            "sigue cobrando la cuota actual (0 si el contrato se prorroga solo).\n"
            "- **Cruce entre listados**: por nombre del establecimiento, ignorando un código inicial tipo "
            "`B001 - `, acentos y mayúsculas."
        )

# --------------------------------------------------------------------------- #
# TAB 2 · Vencimientos
# --------------------------------------------------------------------------- #
CHIP_C = {az.VENCIDO: "venc", az.URGENTE: "crit", az.PROXIMO: "rev", az.PLANIFICAR: "plan", az.VIGENTE: "ok"}

with tab_venc:
    if cont is None:
        st.info("Carga el listado de contratos (o los datos de demostración) para ver los vencimientos.")
    else:
        etiquetas = {az.VENCIDO: "", az.URGENTE: f" ≤ {umbrales[0]} d", az.PROXIMO: f" ≤ {umbrales[1]} d",
                     az.PLANIFICAR: f" ≤ {umbrales[2]} d", az.VIGENTE: ""}
        st.markdown("".join(
            f'<span class="chip {CHIP_C[e]}">{ICONO_CONTRATO[e]} {e}{etiquetas[e]}: '
            f'{int((cont["estado"] == e).sum())}</span>' for e in az.ESTADOS_CONTRATO)
            + (f'<span class="chip gris">🔁 Prorrogados tácitamente: {kpis["n_prorrogados"]}</span>'
               if kpis["n_prorrogados"] else ""),
            unsafe_allow_html=True)

        exceso = cont[cont["maquinas"] > az.MAX_MAQUINAS_B_HOSTELERIA]
        if not exceso.empty:
            st.warning(f"**{len(exceso)} {'establecimiento' if len(exceso) == 1 else 'establecimientos'} con más de {az.MAX_MAQUINAS_B_HOSTELERIA} máquinas** "
                       "(máximo de tipo B en hostelería en la Comunitat Valenciana). Comprueba si alguna es de otro "
                       "tipo: " + ", ".join(f"{b} ({int(m)})" for b, m in zip(exceso["bar"], exceso["maquinas"])))

        g1, g2 = st.columns([2.2, 1])
        with g1:
            horizonte = cont[cont["dias_restantes"] <= 365].sort_values("fin_efectivo")
            if horizonte.empty:
                st.success("Ningún contrato vence en los próximos 12 meses. ✔")
            else:
                fig = go.Figure()
                tam = (horizonte["rec_mensual"] if "rec_mensual" in horizonte else pd.Series(dtype=float))
                for e in az.ESTADOS_CONTRATO:
                    h = horizonte[horizonte["estado"] == e]
                    if h.empty:
                        continue
                    t = tam.reindex(h.index) if not tam.empty else None
                    size = (8 + 22 * (t / tam.max())).fillna(10) if t is not None and tam.max() > 0 else 12
                    fig.add_trace(go.Scatter(
                        x=h["fin_efectivo"], y=h["bar"], mode="markers", name=e,
                        marker=dict(color=az.COLOR_CONTRATO[e], size=size, line=dict(width=1, color="#fff")),
                        customdata=list(zip(h["dias_restantes"], h["contrato"],
                                            [eur(v, 0) for v in (t if t is not None else [None] * len(h))])),
                        hovertemplate="<b>%{y}</b><br>Vence: %{x|%d/%m/%Y} (%{customdata[0]} días)<br>"
                                      "Contrato: %{customdata[1]}<br>Recaudación media: %{customdata[2]}/mes"
                                      "<extra></extra>"))
                ref_ts = pd.Timestamp(fecha_ref)
                for d, txt in [(0, "Hoy")] + [(u, f"{u} d") for u in umbrales]:
                    fig.add_vline(x=ref_ts + pd.Timedelta(days=d), line_dash="dot" if d else "solid",
                                  line_color="#94A3B8" if d else "#0F2A4A", line_width=1)
                    fig.add_annotation(x=ref_ts + pd.Timedelta(days=d), y=1.02, yref="paper", text=txt,
                                       showarrow=False, font=dict(size=11, color="#475569"))
                fig.update_layout(template="plotly_white", height=max(360, 24 * len(horizonte) + 110),
                                  title="Vencimientos de los próximos 12 meses"
                                        + (" (tamaño = recaudación mensual)" if not tam.empty else ""),
                                  margin=dict(l=10, r=10, t=60, b=10), legend=dict(orientation="h", y=-0.12),
                                  xaxis=dict(tickformat="%m/%Y"),
                                  yaxis=dict(categoryorder="array", categoryarray=horizonte["bar"].tolist()[::-1]))
                st.plotly_chart(fig, width="stretch")
        with g2:
            dist = cont["estado"].value_counts().reindex(az.ESTADOS_CONTRATO).fillna(0)
            fig = go.Figure(go.Pie(labels=dist.index, values=dist.values, hole=.62, sort=False,
                                   marker=dict(colors=[az.COLOR_CONTRATO[e] for e in dist.index]),
                                   textinfo="none", hovertemplate="%{label}: %{value} (%{percent})<extra></extra>"))
            fig.update_layout(template="plotly_white", height=360, margin=dict(l=10, r=10, t=50, b=10),
                              title="Cartera de contratos", legend=dict(orientation="h", y=-0.1),
                              annotations=[dict(text=f"<b>{len(cont)}</b><br>contratos", showarrow=False,
                                                font_size=14)])
            st.plotly_chart(fig, width="stretch")
            if "rec_anual" in cont and kpis["en_ventana"]:
                top = cont[cont["estado"] != az.VIGENTE].nlargest(3, "rec_anual")
                st.markdown("**💡 Prioriza estas renovaciones** (más recaudación):")
                for r in top.itertuples():
                    st.markdown(f"- {ICONO_CONTRATO[r.estado]} {r.bar}: **{eur(r.rec_anual, 0)}/año** · "
                                f"{'vencido' if r.dias_restantes < 0 else f'{r.dias_restantes} d'}")

        st.markdown("#### 📋 Seguimiento de renovaciones")
        st.caption("Anota en qué punto está cada renovación (columna **Gestión**) y una nota libre. "
                   "Se guarda en la base de datos y se conserva aunque vuelvas a cargar el listado.")
        f1, f2, f3 = st.columns([1.6, 1.4, 1.4])
        estados = f1.multiselect("Estado", az.ESTADOS_CONTRATO,
                                 default=[e for e in az.ESTADOS_CONTRATO if e != az.VIGENTE])
        rutas = sorted(r for r in cont["ruta"].unique() if r)
        sel_rutas = f2.multiselect("Ruta", rutas, placeholder="Todas") if rutas else []
        gestiones = f3.multiselect("Gestión", az.GESTIONES, placeholder="Todas")
        vista = cont[cont["estado"].isin(estados)]
        if sel_rutas:
            vista = vista[vista["ruta"].isin(sel_rutas)]
        if gestiones:
            vista = vista[vista["gestion"].isin(gestiones)]

        tabla = pd.DataFrame({
            "id": vista["id_contrato"],
            "Estado": vista["estado"].map(lambda e: f"{ICONO_CONTRATO[e]} {e}"),
            "Establecimiento": vista["bar"], "Días": vista["dias_restantes"],
            "Vence": vista["fin_efectivo"].map(fecha),
            "Gestión": vista["gestion"], "Nota": vista["nota"],
        })
        if "rec_mensual" in vista:
            tabla["Recaudación/mes"] = vista["rec_mensual"].round(0)
        tabla["Contrato"] = vista["contrato"]
        tabla["Ruta"] = vista["ruta"]
        tabla["Prórroga"] = [("🔁 Tácita" if t else "Sí") if a else "No"
                             for a, t in zip(vista["prorroga"], vista["prorrogado"])]
        tabla["Límite preaviso"] = vista["limite_preaviso"].map(lambda x: "" if pd.isna(x) else fecha(x))
        for vacia in ("Ruta", "Contrato"):
            if (tabla[vacia] == "").all():
                tabla = tabla.drop(columns=vacia)
        if (tabla["Límite preaviso"] == "").all():
            tabla = tabla.drop(columns="Límite preaviso")

        editado = st.data_editor(
            tabla, hide_index=True, width="stretch",
            key=f"editor_{st.session_state.setdefault('ver_seg', 0)}_{firma(tabla, '|'.join(tabla['id']))}",
            height=min(38 + 35 * max(len(tabla), 1), 560),
            disabled=[c for c in tabla.columns if c not in ("Gestión", "Nota")],
            column_config={
                "id": None,
                "Días": st.column_config.NumberColumn(format="%d"),
                "Recaudación/mes": st.column_config.NumberColumn(format="%.0f €"),
                "Gestión": st.column_config.SelectboxColumn("Gestión", options=az.GESTIONES, required=True,
                                                            width="medium"),
                "Nota": st.column_config.TextColumn("Nota", width="medium"),
            },
        )
        cambios = editado.merge(tabla[["id", "Gestión", "Nota"]], on="id", suffixes=("", "_antes"))
        cambios = cambios[(cambios["Gestión"] != cambios["Gestión_antes"])
                          | (cambios["Nota"].fillna("") != cambios["Nota_antes"].fillna(""))]
        cg1, cg2 = st.columns([1, 3])
        cg1.button(f"💾 Guardar seguimiento ({len(cambios)} cambios)", type="primary",
                   disabled=cambios.empty, width="stretch", on_click=cb_guardar_seguimiento,
                   args=(list(zip(cambios["id"], cambios["Gestión"], cambios["Nota"].fillna(""))),))
        cg2.caption(f"{num(len(tabla))} contratos mostrados")

# --------------------------------------------------------------------------- #
# TAB 3 · Préstamos
# --------------------------------------------------------------------------- #
ESTILO_P = {az.P_CRITICO: "background-color: #FDE2E2; color: #7F1D1D;",
            az.P_RIESGO: "background-color: #FEF3C7; color: #78350F;",
            az.P_AMORTIZADO: "color: #64748B;", az.P_AL_DIA: ""}
CHIP_P = {az.P_CRITICO: "crit", az.P_RIESGO: "rev", az.P_AL_DIA: "ok", az.P_AMORTIZADO: "gris"}

with tab_prest:
    if prest is None:
        st.info("Carga el listado de préstamos / anticipos (o los datos de demostración) para controlar lo "
                "que te deben los establecimientos.")
    else:
        st.markdown("".join(
            f'<span class="chip {CHIP_P[e]}">{ICONO_PRESTAMO[e]} {e}: {int((prest["estado"] == e).sum())}</span>'
            for e in az.ESTADOS_PRESTAMO)
            + f'&nbsp; Pendiente de cobro: <b>{eur(kpis["capital_pendiente"])}</b> · '
              f'Cuotas atrasadas: <b>{eur(kpis["retraso_total"])}</b>',
            unsafe_allow_html=True)
        if cont is None:
            st.caption("Carga también los contratos para detectar préstamos cuyo contrato vence antes de "
                       "terminar de devolverse.")

        g1, g2 = st.columns([1.3, 1])
        with g1:
            act = prest[prest["pendiente"] > 0.01].sort_values("pendiente")
            fig = go.Figure()
            fig.add_trace(go.Bar(y=act["bar"], x=act["amortizado"], orientation="h", name="Devuelto",
                                 marker_color="#CBD5E1",
                                 hovertemplate="%{y}<br>Devuelto: %{x:,.0f} €<extra></extra>"))
            fig.add_trace(go.Bar(y=act["bar"], x=act["pendiente"], orientation="h", name="Pendiente",
                                 marker_color=[az.COLOR_PRESTAMO[e] for e in act["estado"]],
                                 customdata=act["motivo"],
                                 hovertemplate="%{y}<br>Pendiente: %{x:,.0f} €<br>%{customdata}<extra></extra>"))
            if (act["expuesto_fin_contrato"] > 0).any():
                ex = act[act["expuesto_fin_contrato"] > 0]
                fig.add_trace(go.Scatter(y=ex["bar"], x=ex["importe"], mode="markers", name="⚠ Contrato vence antes",
                                         marker=dict(symbol="diamond", size=11, color="#7F1D1D"),
                                         customdata=ex["expuesto_fin_contrato"],
                                         hovertemplate="%{y}<br>Quedarían %{customdata:,.0f} € al vencer el "
                                                       "contrato<extra></extra>"))
            fig.update_layout(template="plotly_white", barmode="stack", title="Préstamos activos: devuelto vs pendiente",
                              height=max(360, 28 * len(act) + 110), margin=dict(l=10, r=10, t=50, b=10),
                              legend=dict(orientation="h", y=-0.12), xaxis=dict(ticksuffix=" €"))
            st.plotly_chart(fig, width="stretch")
        with g2:
            if calendario is not None and not calendario.empty:
                mes = calendario.groupby("mes", as_index=False)["cuota"].sum()
                fig = go.Figure(go.Bar(x=mes["mes"], y=mes["cuota"], marker_color=AZUL,
                                       hovertemplate="%{x|%m/%Y}: %{y:,.0f} €<extra></extra>"))
                fig.update_layout(template="plotly_white", title="Previsión de cobro de cuotas (24 meses)",
                                  height=360, margin=dict(l=10, r=10, t=50, b=10), yaxis=dict(ticksuffix=" €"),
                                  xaxis=dict(tickformat="%m/%Y"))
                st.plotly_chart(fig, width="stretch")
                st.caption(f"Si todos pagan su cuota, en 12 meses recuperarías "
                           f"**{eur(mes.head(12)['cuota'].sum(), 0)}** de los {eur(kpis['capital_pendiente'], 0)} "
                           "pendientes.")

        st.markdown("#### 📋 Detalle de préstamos")
        f1, f2 = st.columns([1.5, 2])
        est_p = f1.multiselect("Estado", az.ESTADOS_PRESTAMO,
                               default=[e for e in az.ESTADOS_PRESTAMO if e != az.P_AMORTIZADO], key="f_est_p")
        bares_p = f2.multiselect("Establecimiento", sorted(prest["bar"].unique()), placeholder="Todos")
        vp = prest[prest["estado"].isin(est_p)]
        if bares_p:
            vp = vp[vp["bar"].isin(bares_p)]
        tp = pd.DataFrame({
            "Estado": vp["estado"], "Establecimiento": vp["bar"], "Motivo": vp["motivo"],
            "Pendiente": vp["pendiente"], "Atrasado": vp["retraso_eur"], "% devuelto": vp["pct_amortizado"],
            "Importe": vp["importe"], f"Cuota {periodicidad.lower()}": vp["cuota"], "Préstamo": vp["prestamo"],
            "Concesión": vp["fecha"].dt.strftime("%d/%m/%Y"),
            "Fin previsto": vp["fin_previsto"].dt.strftime("%m/%Y"),
            "Vence contrato": vp["fin_contrato"].dt.strftime("%d/%m/%Y"),
            "Saldo al vencer contrato": vp["expuesto_fin_contrato"],
        })
        formatos = {c: eur for c in ["Importe", f"Cuota {periodicidad.lower()}", "Pendiente", "Atrasado", "Saldo al vencer contrato"]}
        formatos["% devuelto"] = lambda x: f"{x * 100:.0f} %"
        if "meses_recaudacion" in vp:
            tp["% liquidación retenida"] = vp["peso_cuota_liq"]
            formatos["% liquidación retenida"] = lambda x: "—" if pd.isna(x) else f"{x * 100:.0f} %"
        if (tp["Préstamo"] == "").all():
            tp = tp.drop(columns="Préstamo")
        if cont is None:
            tp = tp.drop(columns=["Vence contrato", "Saldo al vencer contrato"])
            formatos.pop("Saldo al vencer contrato")
        estilo = (tp.style.apply(lambda f: [ESTILO_P.get(f["Estado"], "")] * len(f), axis=1)
                          .format(formatos, na_rep="—"))
        st.dataframe(estilo, hide_index=True, height=min(38 + 35 * max(len(tp), 1), 520))

        if calendario is not None and not calendario.empty:
            with st.expander("🗓️ Calendario de amortización de un préstamo"):
                opciones = (prest[prest["pendiente"] > 0.01]
                            .apply(lambda r: f"{r['bar']}" + (f" · {r['prestamo']}" if r["prestamo"] else ""),
                                   axis=1).tolist())
                elegido = st.selectbox("Préstamo", opciones)
                fila = prest[prest["pendiente"] > 0.01].iloc[opciones.index(elegido)]
                cal = calendario[(calendario["bar"] == fila["bar"]) & (calendario["prestamo"] == fila["prestamo"])]
                st.dataframe(pd.DataFrame({"Fecha": cal["fecha"].dt.strftime("%d/%m/%Y"), "Cuota": cal["cuota"],
                                           "Saldo tras la cuota": cal["saldo"]})
                             .style.format({"Cuota": eur, "Saldo tras la cuota": eur}), hide_index=True)
                if fila["cuotas_restantes"] > len(cal):
                    st.caption(f"Se muestran los próximos 24 meses ({len(cal)} de {fila['cuotas_restantes']} "
                               f"cuotas pendientes). Fin previsto: {fila['fin_previsto']:%d/%m/%Y}.")

# --------------------------------------------------------------------------- #
# TAB 4 · Informe ejecutivo
# --------------------------------------------------------------------------- #
with tab_inf:
    if not hay_datos:
        st.info("Carga datos para generar el informe ejecutivo.")
    else:
        parametros = {
            "Fecha de referencia": f"{fecha_ref:%d/%m/%Y}",
            "Ventanas de aviso": f"Urgente ≤ {umbrales[0]} d · Próximo ≤ {umbrales[1]} d · "
                                 f"Planificar ≤ {umbrales[2]} d",
            "Prórroga tácita": f"{meses_prorroga} meses",
            "Descuento de cuotas": f"{periodicidad} (de la recaudación de la máquina)",
            "Criterio préstamos": f"Riesgo ≥ {num(tolerancia, 1)} {unidad} sin descontar o contrato que vence antes "
                                  f"de amortizar · Crítico ≥ {num(critico, 1)} {unidad} o contrato vencido",
        }
        informe = az.exportar_informe_excel(cont, prest, calendario, kpis, parametros)
        c1, c2 = st.columns([1.4, 1])
        with c1:
            st.markdown("#### 📊 Informe para gerencia")
            st.markdown(
                "Excel con cuatro pestañas listo para presentar:\n"
                "- **Resumen_Ejecutivo**: KPIs de contratos y préstamos y parámetros usados.\n"
                "- **Vencimientos**: contratos vencidos y por vencer, con su gestión y notas.\n"
                "- **Prestamos**: saldo, retrasos, fin previsto y riesgo frente al vencimiento del contrato.\n"
                "- **Calendario_Cobros**: previsión mensual de cuotas por establecimiento.\n\n"
                "Cabeceras corporativas, columnas autoajustadas, formato moneda €, filtros y semáforo de colores."
            )
            st.download_button(
                "⬇️ Descargar informe Excel", data=informe, type="primary",
                file_name=f"Informe_Contratos_{datetime.now():%Y%m%d_%H%M}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with c2:
            st.markdown("#### Resumen")
            lineas = [f"- Fecha de referencia: **{fecha_ref:%d/%m/%Y}**"]
            if cont is not None:
                lineas.append(f"- Contratos: **{kpis['n_contratos']}** · **{kpis['n_vencidos']} vencidos**, "
                              f"**{kpis['n_urgentes']} urgentes**, {kpis['n_proximos']} próximos y "
                              f"{kpis['n_planificar']} a planificar")
                if not pd.isna(kpis["rec_en_juego"]):
                    lineas.append(f"- Recaudación anual en juego: **{eur(kpis['rec_en_juego'], 0)}**")
            if prest is not None:
                lineas.append(f"- Préstamos: **{eur(kpis['capital_pendiente'])}** pendientes en "
                              f"{kpis['n_activos']} activos")
                lineas.append(f"- En riesgo: **{eur(kpis['capital_riesgo'])}** "
                              f"({kpis['n_criticos']} críticos, {kpis['n_riesgo']} en riesgo)")
            lineas.append(f"- Ahorro estimado: **{num(kpis['horas_ahorradas'], 1)} h** de revisión manual")
            st.markdown("\n".join(lineas))

st.divider()
st.caption("Gestor de Contratos · Python, Streamlit, Pandas, Plotly y SQLite · "
           "Los datos se procesan localmente; los datos de demostración son ficticios.")
