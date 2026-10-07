import datetime
from typing import Optional
from app.models import Route, PriceObservation, Alert
from app.database import get_db
from app.analytics import (
    compute_anticipation_brackets,
    get_best_window_info,
    get_price_percentile,
    get_baggage_cost,
    detect_flash_drop
)
from app.notifier import dispatch_alert

def check_anti_duplicate(route_id: int, current_total_price: float) -> bool:
    """
    Renvoie True si une alerte peut être envoyée.
    Renvoie False si une alerte a déjà été envoyée pour un prix égal ou inférieur dans les 3 derniers jours.
    """
    three_days_ago = (datetime.datetime.now() - datetime.timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cur = conn.execute("""
            SELECT prix_total FROM alerts
            WHERE route_id = ? AND date >= ?
            ORDER BY prix_total ASC LIMIT 1
        """, (route_id, three_days_ago))
        row = cur.fetchone()
        if row:
            lowest_recent_alert = float(row["prix_total"])
            if current_total_price >= lowest_recent_alert:
                return False  # Doublon évité
    return True

def format_alert_message(
    route: Route,
    date_vol: str,
    prix_billet: float,
    prix_bagage: float,
    prix_total: float,
    niveau_google: str,
    days_anticipation: int,
    best_window: dict,
    flash_drop: Optional[dict] = None
) -> str:
    """
    Formate le message d'alerte selon les exigences du prompt :
    « Paris → Rome, 14 nov. : billet 34 € + bagage cabine 25 € = 59 €. Niveau Google : bas.
      J-75, dans la meilleure fenêtre pour ce trajet (60-90 jours, basé sur 340 prix).
      Vérifie vite sur le site de la compagnie. »
    """
    # Formatage de la date du vol (ex: 14 nov.)
    try:
        dt = datetime.date.fromisoformat(date_vol[:10])
        mois_fr = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
        date_vol_str = f"{dt.day} {mois_fr[dt.month - 1]}"
    except Exception:
        date_vol_str = date_vol

    bagage_label = {
        "aucun": "sans bagage",
        "cabine": "bagage cabine",
        "soute_1": "bagage soute (1)",
        "soute_2": "bagage soute (2)"
    }.get(route.bagage, "bagage")

    bagage_part = f" + {bagage_label} {int(prix_bagage)} €" if prix_bagage > 0 else ""
    google_part = f" Niveau Google : {niveau_google}." if niveau_google else ""

    # Contexte fenêtre
    if best_window.get("confidence") != "données insuffisantes" and best_window.get("window"):
        window_part = f" J-{days_anticipation}, dans la meilleure fenêtre pour ce trajet ({best_window['window']}, basé sur {best_window.get('count', 0)} prix)."
    else:
        window_part = f" J-{days_anticipation} avant le départ."

    drop_part = ""
    if flash_drop:
        drop_part = f" ⚡ Baisse flash de -{flash_drop['drop_pct']}% en 24h !"

    msg = (
        f"{route.origine} → {route.destination}, {date_vol_str} : "
        f"billet {int(prix_billet)} €{bagage_part} = {int(prix_total)} €."
        f"{google_part}{window_part}{drop_part} "
        f"Prix probablement bas, vérifie vite sur le site de la compagnie."
    )
    return msg

async def evaluate_and_trigger_alert(
    route: Route,
    latest_obs: PriceObservation,
    airline_baggage_cost: float,
    all_route_prices: list[float],
    history_tuples: list[tuple[float, int]],
    chronological_prices: list[tuple[str, float]]
) -> Optional[Alert]:
    """
    Évalue les conditions d'alerte :
    1. prix total <= seuil OU billet dans les 10% les moins chers de l'historique
    2. niveau Google « bas » ou « habituel » (ou vide si source Travelpayouts sans niveau Google)
    3. anti-doublon respecté sur les 3 derniers jours
    """
    prix_billet = latest_obs.prix_billet_eur
    prix_total = round(prix_billet + airline_baggage_cost, 1)

    # 1. Vérification du seuil ou du 10e percentile
    threshold_met = (prix_total <= route.seuil_eur)
    percentile = get_price_percentile(all_route_prices, prix_billet)
    is_top_10_percent = (percentile <= 10.0)

    if not (threshold_met or is_top_10_percent):
        return None

    # 2. Vérification niveau Google ('bas' ou 'habituel')
    # Si le niveau Google est spécifié, il ne doit pas être 'eleve'
    if latest_obs.niveau_google and latest_obs.niveau_google.lower() == "eleve":
        return None

    # 3. Anti-doublon sur 3 jours
    if not check_anti_duplicate(route.id, prix_total):
        return None

    # Calcul de la meilleure fenêtre pour le message
    brackets = compute_anticipation_brackets(history_tuples)
    best_window = get_best_window_info(brackets)
    flash_drop = detect_flash_drop(chronological_prices)

    message = format_alert_message(
        route=route,
        date_vol=latest_obs.date_vol,
        prix_billet=prix_billet,
        prix_bagage=airline_baggage_cost,
        prix_total=prix_total,
        niveau_google=latest_obs.niveau_google or "bas",
        days_anticipation=latest_obs.jours_anticipation,
        best_window=best_window,
        flash_drop=flash_drop
    )

    if flash_drop:
        title = f"🔥 PRIX CASSÉ / VENTE FLASH (-{flash_drop['drop_pct']}%) : {route.origine} → {route.destination}"
    else:
        title = f"🚨 Alerte Prix Vol : {route.origine} → {route.destination}"
    channels_sent = await dispatch_alert(title, message, latest_obs.lien)
    channels_str = ",".join(channels_sent) if channels_sent else "none"

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    alert = Alert(
        id=None,
        route_id=route.id,
        date=now_str,
        prix_billet=prix_billet,
        prix_bagage=airline_baggage_cost,
        prix_total=prix_total,
        message=message,
        canaux=channels_str,
        lien=latest_obs.lien
    )

    with get_db() as conn:
        conn.execute("""
            INSERT INTO alerts (route_id, date, prix_billet, prix_bagage, prix_total, message, canaux, lien)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (alert.route_id, alert.date, alert.prix_billet, alert.prix_bagage, alert.prix_total, alert.message, alert.canaux, alert.lien))

    return alert

async def check_script_inactivity_alert():
    """Alerte si le script n'a pas tourné depuis 3 jours."""
    three_days_ago = (datetime.datetime.now() - datetime.timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cur = conn.execute("SELECT date FROM runs ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if row and row["date"] < three_days_ago:
            title = "⚠️ VolAlerte : Surveillance inactive"
            msg = f"Attention, la vérification automatique quotidienne n'a pas tourné depuis le {row['date']} (plus de 3 jours). Vérifiez que votre PC s'allume ou relancez l'application."
            await dispatch_alert(title, msg)
