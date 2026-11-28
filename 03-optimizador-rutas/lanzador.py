"""
lanzador.py
-----------
Arranque local usado por iniciar_optimizador_rutas.bat: busca un puerto libre, inicia
Streamlit y abre el navegador cuando el servidor está listo.
También vale en macOS/Linux:  python lanzador.py
"""
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP = Path(__file__).resolve().parent / "app.py"


def puerto_libre(inicio: int = 8501, fin: int = 8600) -> int:
    for p in range(inicio, fin):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return inicio


def abrir_cuando_listo(puerto: int, espera_max: float = 60) -> None:
    limite = time.time() + espera_max
    while time.time() < limite:
        try:
            socket.create_connection(("127.0.0.1", puerto), timeout=1).close()
            webbrowser.open(f"http://localhost:{puerto}")
            return
        except OSError:
            time.sleep(0.5)


if __name__ == "__main__":
    from streamlit.web import cli as stcli

    puerto = puerto_libre()
    print(f"  [OK] Abriendo http://localhost:{puerto} en tu navegador...")
    threading.Thread(target=abrir_cuando_listo, args=(puerto,), daemon=True).start()
    sys.argv = ["streamlit", "run", str(APP), "--server.port", str(puerto),
                "--server.headless", "true", "--browser.gatherUsageStats", "false"]
    sys.exit(stcli.main())
