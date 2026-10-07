"""
Démarreur du serveur local FastAPI Uvicorn pour VolAlerte.
"""
import sys
import socket
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import uvicorn
from app.config import settings

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

def main():
    port = settings.APP_PORT
    host = settings.APP_HOST

    # Si le port est déjà actif, le serveur tourne déjà, ne rien faire
    if is_port_in_use(port, host):
        print(f"VolAlerte tourne déjà sur http://{host}:{port}")
        return

    uvicorn.run(
        "app.web.app:app",
        host=host,
        port=port,
        log_level="warning",
        reload=False
    )

if __name__ == "__main__":
    main()
