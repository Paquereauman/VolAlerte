import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "vols.db"
BACKUP_DIR = DATA_DIR / "backups"
ENV_FILE = BASE_DIR / ".env"

# Charge les variables d'environnement
load_dotenv(ENV_FILE)

class Settings:
    @property
    def DEMO_MODE(self) -> bool:
        return os.getenv("DEMO_MODE", "1").lower() in ("1", "true", "yes")

    @property
    def TRAVELPAYOUTS_TOKEN(self) -> str:
        return os.getenv("TRAVELPAYOUTS_TOKEN", "").strip()

    @property
    def SERPAPI_API_KEY(self) -> str:
        return os.getenv("SERPAPI_API_KEY", "").strip()

    @property
    def ALERT_CHANNELS(self) -> list[str]:
        raw = os.getenv("ALERT_CHANNELS", "windows,ntfy")
        return [c.strip().lower() for c in raw.split(",") if c.strip()]

    @property
    def TELEGRAM_BOT_TOKEN(self) -> str:
        return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    @property
    def TELEGRAM_CHAT_ID(self) -> str:
        return os.getenv("TELEGRAM_CHAT_ID", "").strip()

    @property
    def NTFY_TOPIC(self) -> str:
        return os.getenv("NTFY_TOPIC", "volalerte_alertes").strip()

    @property
    def APP_PORT(self) -> int:
        try:
            return int(os.getenv("APP_PORT", "8765"))
        except ValueError:
            return 8765

    @property
    def APP_HOST(self) -> str:
        return os.getenv("APP_HOST", "127.0.0.1")

    @property
    def DAILY_CHECK_TIME(self) -> str:
        return os.getenv("DAILY_CHECK_TIME", "09:00").strip()

    @staticmethod
    def mask_key(val: str) -> str:
        if not val:
            return ""
        if len(val) <= 8:
            return "••••••••"
        return f"{val[:4]}••••••••{val[-4:]}"

    @classmethod
    def update_env(cls, updates: dict[str, str]):
        """Met à jour le fichier .env sans écraser les commentaires ou lignes existantes."""
        lines = []
        if ENV_FILE.exists():
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()

        new_lines = []
        handled_keys = set()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                new_lines.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                handled_keys.add(key)
            else:
                new_lines.append(line)

        for key, value in updates.items():
            if key not in handled_keys:
                new_lines.append(f"{key}={value}\n")

        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        load_dotenv(ENV_FILE, override=True)

settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
