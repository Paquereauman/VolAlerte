import random
import datetime
from app.sources.base import FlightSourceBase
from app.models import Route, PriceObservation, BaggagePrice
from app.analytics import calculate_anticipation_days
from app.database import get_db

class MockFlightSource(FlightSourceBase):
    """
    Source de démonstration avec des données réalistes.
    Permet de tester 100% de l'interface, des calculs et des alertes sans aucune clé API.
    """

    async def search_prices(self, route: Route, flexible_days: int = 0) -> list[PriceObservation]:
        import re
        from app.sources.google_live import fetch_live_google_flights, build_google_tfs_url, build_trip_com_url

        today = datetime.date.today()
        today_str = today.isoformat()

        orig_m = re.search(r'\b([A-Z]{3})\b', (route.origine or "").upper())
        dest_m = re.search(r'\b([A-Z]{3})\b', (route.destination or "").upper())
        o_iata = orig_m.group(1) if orig_m else (route.origine or "CGO").strip().upper()[:3]
        d_iata = dest_m.group(1) if dest_m else (route.destination or "BKK").strip().upper()[:3]
        if o_iata == "PAR":
            o_iata = "ORY"
        if d_iata == "ROM":
            d_iata = "FCO"

        # Calcul de la date du vol cible (toujours dans le futur)
        if ":" in route.dates_ou_mois:
            dep_date = route.dates_ou_mois.split(":")[0]
        elif len(route.dates_ou_mois) == 7:
            dep_date = f"{route.dates_ou_mois}-15"
        else:
            dep_date = route.dates_ou_mois

        try:
            dt = datetime.date.fromisoformat(dep_date[:10])
            if dt <= today:
                dt = datetime.date(2026, 11, 15)
            dep_date = dt.isoformat()
        except Exception:
            dep_date = "2026-11-15"

        anticipation = calculate_anticipation_days(dep_date, today_str)
        carry_on_p = 1 if route.bagage == "cabine" else 0
        checked_p = 1 if route.bagage in ("soute_1", "soute_2") else 0

        # Chercher d'abord les vrais vols Google Flights en cache / live
        live_flights, _ = fetch_live_google_flights(o_iata, d_iata, dep_date, force_refresh=False, allow_network=False)
        if live_flights:
            best = min(live_flights, key=lambda x: x["price_base_eur"])
            all_p = [f["price_base_eur"] for f in live_flights]
            f_low = float(min(all_p))
            f_high = float(max(all_p)) if max(all_p) > min(all_p) else float(min(all_p) + 40)
            booking_url = build_google_tfs_url(
                o_iata, d_iata, best["dep_date"],
                carry_on_bags=carry_on_p, checked_bags=checked_p,
                tfu_token=best.get("tfu_token"), booking_page=True
            )
            return [
                PriceObservation(
                    id=None,
                    route_id=route.id or 1,
                    source="google_live",
                    date_vol=best["dep_date"],
                    date_releve=today_str,
                    jours_anticipation=anticipation,
                    prix_billet_eur=float(best["price_base_eur"]),
                    compagnie=best["airlines"],
                    escales=int(best["stops"]),
                    niveau_google="bas",
                    fourchette_basse=f_low,
                    fourchette_haute=f_high,
                    lien=booking_url,
                    duree_totale_minutes=int(best["duration_min"]),
                    duree_escale_max_minutes=int(best["max_layover_min"]),
                    escales_details=best["layover_details"],
                    horaires_vol=best["schedule_str"],
                    numero_vol=best["flight_numbers"],
                    prix_cabine_eur=float(best["price_cabine_eur"]),
                    prix_soute_eur=float(best["price_soute_eur"]),
                )
            ]

        dest_upper = route.destination.upper()
        if "HAN" in dest_upper or "HANOI" in dest_upper or "VIETNAM" in dest_upper:
            base_ticket = 114.0
            company = "China Southern Airlines"
            f_low, f_high = 96.0, 185.0
            stops = 1
            tot_dur = 315
            max_lay = 105
            esc_det = "1 escale de 1h45 à Canton (CAN)"
        elif "CNX" in dest_upper or "CHIANG" in dest_upper:
            base_ticket = 124.0
            company = "Thai AirAsia"
            f_low, f_high = 78.0, 210.0
            stops = 0
            tot_dur = 235
            max_lay = 0
            esc_det = "Direct (sans escale)"
        elif "ROM" in dest_upper or "ROME" in dest_upper or "FCO" in dest_upper:
            base_ticket = 34.0
            company = "Ryanair"
            f_low, f_high = 30.0, 85.0
            stops = 0
            tot_dur = 125
            max_lay = 0
            esc_det = "Direct (sans escale)"
        else:
            base_ticket = 78.0
            company = "Transavia"
            f_low, f_high = 60.0, 150.0
            stops = 0
            tot_dur = 150
            max_lay = 0
            esc_det = "Direct (sans escale)"

        google_url = build_google_tfs_url(
            o_iata, d_iata, dep_date,
            carry_on_bags=carry_on_p, checked_bags=checked_p,
            booking_page=True
        )
        trip_url = build_trip_com_url(o_iata, d_iata, dep_date)

        return [
            PriceObservation(
                id=None,
                route_id=route.id or 1,
                source="google",
                date_vol=dep_date,
                date_releve=today_str,
                jours_anticipation=anticipation,
                prix_billet_eur=base_ticket,
                compagnie=company,
                escales=stops,
                niveau_google="bas",
                fourchette_basse=f_low,
                fourchette_haute=f_high,
                lien=google_url,
                duree_totale_minutes=tot_dur,
                duree_escale_max_minutes=max_lay,
                escales_details=esc_det
            ),
            PriceObservation(
                id=None,
                route_id=route.id or 1,
                source="travelpayouts",
                date_vol=dep_date,
                date_releve=today_str,
                jours_anticipation=anticipation,
                prix_billet_eur=base_ticket + 3.0,
                compagnie=company,
                escales=stops,
                niveau_google="",
                lien=trip_url,
                duree_totale_minutes=tot_dur,
                duree_escale_max_minutes=max_lay,
                escales_details=esc_det
            )
        ]

    async def get_baggage(self, route: Route, airline: str) -> list[BaggagePrice]:
        today_str = datetime.date.today().isoformat()
        comp = airline or "Compagnie"
        if "CHINA SOUTHERN" in comp.upper() or "VIETNAM" in comp.upper():
            return [
                BaggagePrice(None, route.id, comp, "cabine", 0.0, 0.0, today_str),
                BaggagePrice(None, route.id, comp, "soute_1", 30.0, 40.0, today_str),
                BaggagePrice(None, route.id, comp, "soute_2", 60.0, 75.0, today_str),
            ]
        elif "AIRASIA" in comp.upper():
            return [
                BaggagePrice(None, route.id, comp, "cabine", 14.0, 18.0, today_str),
                BaggagePrice(None, route.id, comp, "soute_1", 32.0, 42.0, today_str),
                BaggagePrice(None, route.id, comp, "soute_2", 65.0, 80.0, today_str),
            ]
        return [
            BaggagePrice(None, route.id, comp, "cabine", 20.0, 25.0, today_str),
            BaggagePrice(None, route.id, comp, "soute_1", 35.0, 45.0, today_str),
            BaggagePrice(None, route.id, comp, "soute_2", 70.0, 85.0, today_str),
        ]

def seed_demo_database():
    """Initialise des routes et plus de 350 observations réalistes pour peupler le mode Démo."""
    with get_db() as conn:
        # Vérifier si des données existent déjà
        cur = conn.execute("SELECT COUNT(*) as count FROM routes")
        if cur.fetchone()["count"] > 0:
            return

        # 1. Créer les 2 trajets demandés
        conn.execute("""
            INSERT INTO routes (id, origine, destination, type, dates_ou_mois, passagers, bagage, seuil_eur, actif)
            VALUES (3, 'Zhengzhou (CGO)', 'Hanoï (HAN)', 'aller_simple', '2026-11-15', 1, 'cabine', 140.0, 1)
        """)
        conn.execute("""
            INSERT INTO routes (id, origine, destination, type, dates_ou_mois, passagers, bagage, seuil_eur, actif)
            VALUES (4, 'Zhengzhou (CGO)', 'Chiang Mai (CNX)', 'aller_simple', '2026-11-15', 1, 'cabine', 150.0, 1)
        """)

        # 2. Insérer les tarifs bagages de référence
        bagages = [
            (3, 'China Southern Airlines', 'cabine', 0.0, 0.0, '2026-09-30'),
            (3, 'China Southern Airlines', 'soute_1', 30.0, 40.0, '2026-09-30'),
            (3, 'Vietnam Airlines', 'cabine', 0.0, 0.0, '2026-09-30'),
            (3, 'Vietnam Airlines', 'soute_1', 28.0, 38.0, '2026-09-30'),
            (4, 'Thai AirAsia', 'cabine', 14.0, 18.0, '2026-09-30'),
            (4, 'Thai AirAsia', 'soute_1', 32.0, 42.0, '2026-09-30'),
            (4, 'Spring Airlines', 'cabine', 12.0, 16.0, '2026-09-30'),
            (4, 'Spring Airlines', 'soute_1', 30.0, 40.0, '2026-09-30'),
        ]
        conn.executemany("""
            INSERT INTO baggage_prices (route_id, compagnie, type, prix_bas_eur, prix_haut_eur, date_releve)
            VALUES (?, ?, ?, ?, ?, ?)
        """, bagages)

        # 3. Générer 350 observations pour le trajet 1 (Paris -> Rome) réparties sur toutes les tranches
        # Fenêtre idéale 60-90j : médiane ~35€
        # 90-120j : ~45€
        # 120-180j : ~55€
        # >180j : ~68€
        # 30-60j : ~48€
        # 14-30j : ~65€
        # <14j : ~95€
        target_vol = datetime.date(2026, 11, 14)
        observations = []

        random.seed(42)

        def add_batch(min_d, max_d, target_med, count):
            for _ in range(count):
                days = random.randint(min_d, max_d)
                noise = random.gauss(0, 5.0)
                price = max(18.0, round(target_med + noise, 1))
                rel_date = target_vol - datetime.timedelta(days=days)
                comp = random.choice(["Ryanair", "EasyJet", "Wizz Air", "Air France"])
                google_lvl = "bas" if price < 40 else ("habituel" if price < 65 else "eleve")
                observations.append((
                    1, "travelpayouts" if random.random() > 0.3 else "google",
                    target_vol.isoformat(), rel_date.isoformat(), days, price,
                    comp, 0, google_lvl, 30.0, 85.0,
                    "https://www.google.com/travel/flights"
                ))

        add_batch(181, 240, 68.0, 45)  # > 180 j
        add_batch(120, 180, 55.0, 55)  # 120-180 j
        add_batch(90, 119, 46.0, 50)   # 90-120 j
        add_batch(60, 89, 34.0, 80)    # 60-90 j (meilleure fenêtre, 80 relevés !)
        add_batch(30, 59, 49.0, 60)    # 30-60 j
        add_batch(14, 29, 66.0, 40)    # 14-30 j
        add_batch(1, 13, 94.0, 35)     # < 14 j

        # Générer 50 observations pour le trajet 2 (Paris -> Lisbonne)
        target_vol2 = datetime.date(2026, 11, 20)
        for _ in range(70):
            days = random.randint(10, 120)
            noise = random.gauss(0, 8.0)
            price = max(45.0, round(78.0 + noise, 1))
            rel_date = target_vol2 - datetime.timedelta(days=days)
            observations.append((
                2, "travelpayouts", target_vol2.isoformat(), rel_date.isoformat(),
                days, price, "Transavia", 0, "habituel", 60.0, 130.0,
                "https://www.google.com/travel/flights"
            ))

        conn.executemany("""
            INSERT INTO price_observations (
                route_id, source, date_vol, date_releve, jours_anticipation,
                prix_billet_eur, compagnie, escales, niveau_google,
                fourchette_basse, fourchette_haute, lien
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, observations)

        # 4. Insérer une alerte modèle déjà émise
        conn.execute("""
            INSERT INTO alerts (route_id, date, prix_billet, prix_bagage, prix_total, message, canaux, lien)
            VALUES (
                1, '2026-09-30 09:00:00', 34.0, 25.0, 59.0,
                'Paris (CDG, ORY, BVA) → Rome (FCO, CIA), 14 nov. : billet 34 € + bagage cabine 25 € = 59 €. Niveau Google : bas. J-45, dans la meilleure fenêtre pour ce trajet (60-90 jours, basé sur 80 prix). Vérifie vite sur le site de la compagnie.',
                'windows,ntfy',
                'https://www.google.com/travel/flights'
            )
        """)

        # 5. Usage API initial
        conn.execute("""
            INSERT INTO api_usage (mois, source, nombre_requetes)
            VALUES ('2026-09', 'serpapi', 28)
            ON CONFLICT(mois, source) DO NOTHING
        """)

        # 6. Log d'un run précédent réussi
        conn.execute("""
            INSERT INTO runs (date, statut, message_erreur, duree)
            VALUES ('2026-09-30 09:00:02', 'ok', '', 3.42)
        """)
