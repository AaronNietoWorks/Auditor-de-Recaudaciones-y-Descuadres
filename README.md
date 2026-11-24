# Automatizaciones TRUSS/CYTILAND

Suite modular de herramientas en Python/Streamlit para la gestión diaria de una operadora de máquinas recreativas, a partir de exportaciones del ERP IPS-Maq+.

| Módulo | Estado | Descripción |
|---|---|---|
| [`01-auditor-recaudaciones`](01-auditor-recaudaciones/) | ✅ Disponible | Descuadres contadores vs efectivo, caídas de recaudación e informe ejecutivo. |
| `02-gestor-contratos` | 🔜 Próximamente | Control de vencimientos de contratos. |
| `03-optimizador-rutas` | 🔜 Próximamente | Optimización de rutas de recaudación. |

Cada herramienta es independiente: tiene su propio `iniciar_*.bat`, `requirements.txt`, `.streamlit/config.toml` y `README.md`.

> 🔒 Privacidad: el repositorio nunca contiene datos reales. Solo se versionan datos ficticios generados por `sample_data.py`.
