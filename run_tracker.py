"""
Script quotidien de surveillance et d'alerte pour VolAlerte.
Ce script est appelé automatiquement une fois par jour par le planificateur de tâches Windows (schtasks),
ou peut être exécuté manuellement à tout moment.
"""
import sys
import asyncio
from pathlib import Path

# S'assurer que le dossier racine est dans sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.scheduler_task import execute_daily_run

def main():
    try:
        asyncio.run(execute_daily_run())
        sys.exit(0)
    except Exception as e:
        print(f"[ERREUR] Le suivi a échoué: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
