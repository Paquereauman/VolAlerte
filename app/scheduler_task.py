import asyncio
import time
import datetime
from app.config import settings
from app.models import Route, PriceObservation
from app.database import (
    init_db,
    get_db,
    log_run,
    backup_database
)
from app.sources.travelpayouts import TravelpayoutsSource
from app.sources.serpapi import SerpApiSource
from app.sources.mock_source import MockFlightSource, seed_demo_database
from app.analytics import get_baggage_cost
from app.alert_engine import evaluate_and_trigger_alert, check_script_inactivity_alert

async def execute_daily_run():
    """
    Exécute le cycle complet quotidien de surveillance et d'alerte :
    1. Pour chaque trajet actif, relève les prix Travelpayouts et enregistre.
    2. Lance la recherche Google via SerpApi et enregistre prix, niveau et fourchette habituelle.
    3. Si le dernier prix bagage connu a > 7 jours, le rafraîchit.
    4. Calcule le prix total = billet + bagage choisi (valeur haute).
    5. Déclenche les alertes selon les conditions strictes.
    6. Rafraîchit le prix bagage avant envoi si nécessaire.
    7. Envoie les notifications.
    Sauvegarde la base si besoin et consigne le statut dans `runs`.
    Effectue jusqu'à 2 nouvelles tentatives espacées en cas d'erreur API.
    """
    start_time = time.time()
    init_db()

    # Si mode démo, s'assurer que la base contient des données de test
    if settings.DEMO_MODE:
        seed_demo_database()

    # Vérification d'inactivité passée (> 3 jours)
    await check_script_inactivity_alert()

    # Sauvegarde hebdomadaire automatique
    try:
        backup_database()
    except Exception:
        pass

    travelpayouts_src = TravelpayoutsSource()
    serpapi_src = SerpApiSource()
    mock_src = MockFlightSource()

    # Récupérer tous les trajets actifs
    routes: list[Route] = []
    with get_db() as conn:
        cur = conn.execute("SELECT * FROM routes WHERE actif = 1")
        for row in cur.fetchall():
            routes.append(Route(
                id=row["id"],
                origine=row["origine"],
                destination=row["destination"],
                type=row["type"],
                dates_ou_mois=row["dates_ou_mois"],
                passagers=row["passagers"],
                bagage=row["bagage"],
                seuil_eur=float(row["seuil_eur"]),
                actif=bool(row["actif"])
            ))

    if not routes:
        log_run("ok", "Aucun trajet actif à surveiller", time.time() - start_time)
        return

    error_messages = []

    for route in routes:
        retries = 2
        success = False

        while retries >= 0 and not success:
            try:
                observations: list[PriceObservation] = []

                if settings.DEMO_MODE:
                    obs_list = await mock_src.search_prices(route)
                    observations.extend(obs_list)
                else:
                    # 1. Travelpayouts (dates flexibles +/- 3 jours ou mois)
                    tp_obs = await travelpayouts_src.search_prices(route, flexible_days=3)
                    observations.extend(tp_obs)

                    # 2. SerpApi Google Flights
                    google_obs = await serpapi_src.search_prices(route)
                    observations.extend(google_obs)

                # Enregistrement des nouvelles observations
                if observations:
                    with get_db() as conn:
                        conn.executemany("""
                            INSERT INTO price_observations (
                                route_id, source, date_vol, date_releve, jours_anticipation,
                                prix_billet_eur, compagnie, escales, niveau_google,
                                fourchette_basse, fourchette_haute, lien
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, [
                            (
                                route.id, o.source, o.date_vol, o.date_releve, o.jours_anticipation,
                                o.prix_billet_eur, o.compagnie, o.escales, o.niveau_google,
                                o.fourchette_basse, o.fourchette_haute, o.lien
                            ) for o in observations
                        ])

                # 3. Vérifier la fraîcheur des tarifs bagages (> 7 jours)
                seven_days_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
                needs_baggage_refresh = False
                with get_db() as conn:
                    cur = conn.execute("""
                        SELECT MAX(date_releve) as last_date FROM baggage_prices
                        WHERE route_id = ?
                    """, (route.id,))
                    row = cur.fetchone()
                    if not row or not row["last_date"] or row["last_date"] < seven_days_ago:
                        needs_baggage_refresh = True

                if needs_baggage_refresh:
                    # Rafraîchir via options de réservation
                    if settings.DEMO_MODE:
                        fresh_bags = await mock_src.get_baggage(route, "Ryanair")
                    else:
                        fresh_bags = await serpapi_src.get_baggage(route, "")

                    if fresh_bags:
                        with get_db() as conn:
                            conn.executemany("""
                                INSERT INTO baggage_prices (route_id, compagnie, type, prix_bas_eur, prix_haut_eur, date_releve)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, [(b.route_id, b.compagnie, b.type, b.prix_bas_eur, b.prix_haut_eur, b.date_releve) for b in fresh_bags])

                # Récupérer tout l'historique de ce trajet pour les calculs de percentiles et fenêtres
                all_prices = []
                history_tuples = []
                chronological_prices = []
                with get_db() as conn:
                    cur = conn.execute("""
                        SELECT date_releve, prix_billet_eur, jours_anticipation
                        FROM price_observations
                        WHERE route_id = ?
                        ORDER BY date_releve ASC
                    """, (route.id,))
                    for row in cur.fetchall():
                        p = float(row["prix_billet_eur"])
                        j = int(row["jours_anticipation"])
                        d = str(row["date_releve"])
                        all_prices.append(p)
                        history_tuples.append((p, j))
                        chronological_prices.append((d, p))

                # Évaluer les alertes pour les meilleures observations récentes
                if observations:
                    # Prendre l'observation la plus basse (ou Google en priorité si dispo)
                    best_obs = min(observations, key=lambda o: o.prix_billet_eur)
                    # 4. Calcul du prix bagage
                    baggage_cost = get_baggage_cost(route.id, best_obs.compagnie, route.bagage)

                    # 5 & 6 & 7. Évaluation et diffusion de l'alerte
                    await evaluate_and_trigger_alert(
                        route=route,
                        latest_obs=best_obs,
                        airline_baggage_cost=baggage_cost,
                        all_route_prices=all_prices,
                        history_tuples=history_tuples,
                        chronological_prices=chronological_prices
                    )

                success = True

            except Exception as e:
                retries -= 1
                if retries >= 0:
                    await asyncio.sleep(3.0)  # Tentative espacée
                else:
                    error_messages.append(f"Route {route.id} ({route.origine}->{route.destination}): {str(e)}")

    duration = time.time() - start_time
    if error_messages:
        log_run("erreur", " | ".join(error_messages), duration)
    else:
        log_run("ok", "", duration)
