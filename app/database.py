import sqlite3
import shutil
import datetime
from pathlib import Path
from contextlib import contextmanager
from app.config import DB_PATH, BACKUP_DIR

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origine TEXT NOT NULL,
    destination TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'aller_simple',
    dates_ou_mois TEXT NOT NULL,
    passagers INTEGER DEFAULT 1,
    bagage TEXT DEFAULT 'cabine',
    seuil_eur REAL DEFAULT 80.0,
    actif INTEGER DEFAULT 1,
    max_duree_heures REAL DEFAULT 12.0,
    max_escales INTEGER DEFAULT 1,
    max_escale_duree_heures REAL DEFAULT 4.0
);

CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    date_vol TEXT NOT NULL,
    date_releve TEXT NOT NULL,
    jours_anticipation INTEGER NOT NULL,
    prix_billet_eur REAL NOT NULL,
    compagnie TEXT DEFAULT '',
    escales INTEGER DEFAULT 0,
    niveau_google TEXT DEFAULT '',
    fourchette_basse REAL DEFAULT NULL,
    fourchette_haute REAL DEFAULT NULL,
    lien TEXT DEFAULT '',
    duree_totale_minutes INTEGER DEFAULT NULL,
    duree_escale_max_minutes INTEGER DEFAULT 0,
    escales_details TEXT DEFAULT '',
    horaires_vol TEXT DEFAULT '',
    numero_vol TEXT DEFAULT '',
    prix_cabine_eur REAL DEFAULT NULL,
    prix_soute_eur REAL DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS live_flight_cache (
    origin TEXT NOT NULL,
    dest TEXT NOT NULL,
    date_vol TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    flights_json TEXT NOT NULL,
    PRIMARY KEY (origin, dest, date_vol)
);

CREATE TABLE IF NOT EXISTS baggage_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER REFERENCES routes(id) ON DELETE CASCADE,
    compagnie TEXT NOT NULL,
    type TEXT NOT NULL,
    prix_bas_eur REAL NOT NULL,
    prix_haut_eur REAL NOT NULL,
    date_releve TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    prix_billet REAL NOT NULL,
    prix_bagage REAL NOT NULL,
    prix_total REAL NOT NULL,
    message TEXT NOT NULL,
    canaux TEXT NOT NULL,
    lien TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mois TEXT NOT NULL,
    source TEXT NOT NULL,
    nombre_requetes INTEGER DEFAULT 0,
    UNIQUE(mois, source)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    statut TEXT NOT NULL,
    message_erreur TEXT DEFAULT '',
    duree REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_price_route_date ON price_observations(route_id, date_vol);
CREATE INDEX IF NOT EXISTS idx_price_anticipation ON price_observations(route_id, jours_anticipation);
CREATE INDEX IF NOT EXISTS idx_baggage_compagnie ON baggage_prices(compagnie, type);
"""

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Initialise les tables SQLite, effectue les migrations et sauvegarde si nécessaire."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
        
        # Migrations rétrocompatibles pour price_observations
        obs_cols = [c["name"] for c in conn.execute("PRAGMA table_info(price_observations)").fetchall()]
        if "duree_totale_minutes" not in obs_cols:
            conn.execute("ALTER TABLE price_observations ADD COLUMN duree_totale_minutes INTEGER DEFAULT NULL")
        if "duree_escale_max_minutes" not in obs_cols:
            conn.execute("ALTER TABLE price_observations ADD COLUMN duree_escale_max_minutes INTEGER DEFAULT 0")
        if "escales_details" not in obs_cols:
            conn.execute("ALTER TABLE price_observations ADD COLUMN escales_details TEXT DEFAULT ''")
        if "horaires_vol" not in obs_cols:
            conn.execute("ALTER TABLE price_observations ADD COLUMN horaires_vol TEXT DEFAULT ''")
        if "numero_vol" not in obs_cols:
            conn.execute("ALTER TABLE price_observations ADD COLUMN numero_vol TEXT DEFAULT ''")
        if "prix_cabine_eur" not in obs_cols:
            conn.execute("ALTER TABLE price_observations ADD COLUMN prix_cabine_eur REAL DEFAULT NULL")
        if "prix_soute_eur" not in obs_cols:
            conn.execute("ALTER TABLE price_observations ADD COLUMN prix_soute_eur REAL DEFAULT NULL")

        # Migrations rétrocompatibles pour routes
        route_cols = [c["name"] for c in conn.execute("PRAGMA table_info(routes)").fetchall()]
        if "max_duree_heures" not in route_cols:
            conn.execute("ALTER TABLE routes ADD COLUMN max_duree_heures REAL DEFAULT 12.0")
        if "max_escales" not in route_cols:
            conn.execute("ALTER TABLE routes ADD COLUMN max_escales INTEGER DEFAULT 1")
        if "max_escale_duree_heures" not in route_cols:
            conn.execute("ALTER TABLE routes ADD COLUMN max_escale_duree_heures REAL DEFAULT 4.0")

def backup_database():
    """Sauvegarde hebdomadaire : copie datée et conservation des 8 dernières."""
    if not DB_PATH.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_file = BACKUP_DIR / f"vols_{timestamp}.db"
    shutil.copy2(DB_PATH, backup_file)

    # Conserver les 8 dernières copies
    backups = sorted(BACKUP_DIR.glob("vols_*.db"), key=lambda f: f.stat().st_mtime)
    while len(backups) > 8:
        oldest = backups.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass

def increment_api_usage(source: str, count: int = 1):
    """Incrémente le compteur de requêtes consommées pour le mois en cours."""
    current_month = datetime.date.today().strftime("%Y-%m")
    with get_db() as conn:
        conn.execute("""
            INSERT INTO api_usage (mois, source, nombre_requetes)
            VALUES (?, ?, ?)
            ON CONFLICT(mois, source) DO UPDATE SET
                nombre_requetes = nombre_requetes + excluded.nombre_requetes
        """, (current_month, source.lower(), count))

def get_api_usage(source: str = "serpapi") -> int:
    """Retourne le nombre de requêtes consommées pour le mois en cours."""
    current_month = datetime.date.today().strftime("%Y-%m")
    with get_db() as conn:
        cur = conn.execute("""
            SELECT nombre_requetes FROM api_usage
            WHERE mois = ? AND source = ?
        """, (current_month, source.lower()))
        row = cur.fetchone()
        return row["nombre_requetes"] if row else 0

def log_run(statut: str, message_erreur: str = "", duree: float = 0.0):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute("""
            INSERT INTO runs (date, statut, message_erreur, duree)
            VALUES (?, ?, ?, ?)
        """, (now_str, statut, message_erreur, round(duree, 2)))

def get_last_run() -> dict | None:
    with get_db() as conn:
        cur = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None
