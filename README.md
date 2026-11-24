# Automatizaciones TRUSS/CYTILAND

Suite modular de herramientas en Python/Streamlit para la gestión diaria de una operadora de máquinas recreativas, a partir de exportaciones del ERP IPS-Maq+.

| Módulo | Estado | Descripción |
|---|---|---|
| [`01-auditor-recaudaciones`](01-auditor-recaudaciones/) | ✅ [Demo en vivo](https://auditor-recaudaciones.streamlit.app/) | Descuadres contadores vs efectivo, caídas de recaudación e informe ejecutivo. |
| [`02-gestor-contratos`](02-gestor-contratos/) | ✅ [Demo en vivo](https://gestor-contratos.streamlit.app/) | Vencimientos de contratos con hosteleros, seguimiento de renovaciones y control de préstamos/anticipos. |
| `03-optimizador-rutas` | 🔜 Próximamente | Optimización de rutas de recaudación. |

Cada herramienta es independiente: tiene su propio `iniciar_*.bat`, `requirements.txt`, `.streamlit/config.toml` y `README.md`.

> 🔒 Privacidad: el repositorio nunca contiene datos reales. Solo se versionan datos ficticios generados por `sample_data.py`.
