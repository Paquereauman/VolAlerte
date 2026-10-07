import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pytest
import datetime
from app.analytics import (
    calculate_anticipation_days,
    get_confidence_level,
    compute_anticipation_brackets,
    get_best_window_info,
    get_price_percentile,
    detect_flash_drop
)
from app.alert_engine import format_alert_message
from app.models import Route, PriceObservation

def test_anticipation_days_calculation():
    """Vérifie le calcul exact du délai d'anticipation (date du vol - date du relevé)."""
    d_vol = "2026-11-14"
    d_releve = "2026-08-31"
    # Du 31 août au 14 novembre = 75 jours
    days = calculate_anticipation_days(d_vol, d_releve)
    assert days == 75

    # Si relevé le jour même
    assert calculate_anticipation_days("2026-11-14", "2026-11-14") == 0
    # Si négatif par erreur d'horodatage, ne descend pas sous 0
    assert calculate_anticipation_days("2026-11-10", "2026-11-14") == 0

def test_confidence_levels():
    """
    Règle imposée :
    - moins de 30 prix = « données insuffisantes » (pas de conseil)
    - 30 à 100 = « indicatif »
    - plus de 100 = « fiable »
    """
    assert get_confidence_level(0) == "données insuffisantes"
    assert get_confidence_level(29) == "données insuffisantes"
    assert get_confidence_level(30) == "indicatif"
    assert get_confidence_level(100) == "indicatif"
    assert get_confidence_level(101) == "fiable"
    assert get_confidence_level(350) == "fiable"

def test_anticipation_brackets_and_median_outlier_rejection():
    """
    Vérifie le regroupement par tranches et le calcul de la médiane (pour ignorer les prix aberrants).
    """
    prices_with_days = [
        # Tranche 60-90 j (75 j) : 32, 34, 36, et un prix aberrant 999
        (32.0, 75),
        (34.0, 70),
        (36.0, 80),
        (999.0, 65),  # Prix aberrant
        # Tranche 14-30 j (20 j) : 60, 65, 70
        (60.0, 20),
        (65.0, 25),
        (70.0, 18),
    ]

    brackets = compute_anticipation_brackets(prices_with_days)
    b_60_90 = next(b for b in brackets if b.label == "60-90 j")
    b_14_30 = next(b for b in brackets if b.label == "14-30 j")

    # La médiane de [32, 34, 36, 999] est (34+36)/2 = 35.0 (alors que la moyenne serait 275.25 !)
    assert b_60_90.median_price == 35.0
    assert b_60_90.count == 4
    assert b_60_90.confidence == "données insuffisantes"  # Car < 30 relevés

    # Tranche 14-30 : médiane de [60, 65, 70] = 65.0
    assert b_14_30.median_price == 65.0
    assert b_14_30.count == 3

    # Quand le nombre est suffisant (>30), la tranche 60-90 j est la moins chère
    large_dataset = [(35.0, 75) for _ in range(40)] + [(65.0, 20) for _ in range(40)]
    large_brackets = compute_anticipation_brackets(large_dataset)
    best_info = get_best_window_info(large_brackets)

    assert best_info["window"] == "60-90 j"
    assert best_info["median"] == 35.0
    assert best_info["confidence"] == "indicatif"

    # Vérification des écarts
    b_14_30_large = next(b for b in large_brackets if b.label == "14-30 j")
    assert b_14_30_large.diff_with_best == 30.0  # 65.0 - 35.0 = 30.0 € d'écart

def test_price_percentile():
    """Vérifie le calcul du percentile historique pour le seuil des 10% les moins chers."""
    history = [20, 25, 30, 40, 50, 60, 70, 80, 90, 100]
    # 20 est dans les 10% les plus bas
    assert get_price_percentile(history, 20) <= 10.0
    # 25 est à 20%
    assert get_price_percentile(history, 25) == 20.0
    # 100 est à 100%
    assert get_price_percentile(history, 100) == 100.0

def test_prudent_alert_message_formatting():
    """
    Vérifie les principes stricts imposés :
    - Prudence : contient « prix probablement bas, vérifie vite sur le site de la compagnie »
    - Ne contient JAMAIS « réserve maintenant »
    - Inclut le bagage choisi et le prix total exact
    """
    route = Route(
        id=1,
        origine="Paris",
        destination="Rome",
        type="aller_simple",
        dates_ou_mois="2026-11-14",
        bagage="cabine",
        seuil_eur=60.0
    )

    best_window = {
        "window": "60-90 jours",
        "median": 34.0,
        "count": 340,
        "confidence": "fiable"
    }

    msg = format_alert_message(
        route=route,
        date_vol="2026-11-14",
        prix_billet=34.0,
        prix_bagage=25.0,
        prix_total=59.0,
        niveau_google="bas",
        days_anticipation=75,
        best_window=best_window
    )

    # Vérifications des règles éditoriales
    assert "Paris → Rome, 14 nov. : billet 34 € + bagage cabine 25 € = 59 €" in msg
    assert "Niveau Google : bas" in msg
    assert "J-75, dans la meilleure fenêtre pour ce trajet (60-90 jours, basé sur 340 prix)" in msg
    assert "Prix probablement bas, vérifie vite sur le site de la compagnie." in msg
    assert "réserve maintenant" not in msg.lower()
    assert "reservez maintenant" not in msg.lower()

def test_flash_drop_detection():
    """Vérifie la détection d'une baisse flash de 20% ou plus."""
    # Baisse de 100 € à 75 € (-25%)
    history = [("2026-09-28", 100.0), ("2026-09-29", 75.0)]
    drop = detect_flash_drop(history)
    assert drop is not None
    assert drop["drop_pct"] == 25.0

    # Baisse mineure de 100 € à 90 € (-10% -> pas d'alerte flash)
    history_minor = [("2026-09-28", 100.0), ("2026-09-29", 90.0)]
    assert detect_flash_drop(history_minor) is None

def test_baggage_cost_resolution():
    """Vérifie que le prix du bagage prend la valeur haute et applique les fallbacks."""
    from app.analytics import get_baggage_cost
    from app.database import init_db, get_db

    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM baggage_prices WHERE compagnie = 'TestAir'")
        conn.execute("""
            INSERT INTO baggage_prices (route_id, compagnie, type, prix_bas_eur, prix_haut_eur, date_releve)
            VALUES (NULL, 'TestAir', 'cabine', 20.0, 28.0, '2026-09-30')
        """)

    # La valeur haute doit être 28.0 €
    cost = get_baggage_cost(None, "TestAir", "cabine")
    assert cost == 28.0

    # Bagage 'aucun' doit toujours être 0.0 €
    assert get_baggage_cost(None, "TestAir", "aucun") == 0.0

def test_api_quota_tracking():
    """Vérifie l'incrément et la lecture du quota d'API SerpApi."""
    from app.database import init_db, increment_api_usage, get_api_usage

    init_db()
    initial = get_api_usage("serpapi")
    increment_api_usage("serpapi", 2)
    assert get_api_usage("serpapi") == initial + 2

def test_parse_month_info_and_monthly_stats():
    """Vérifie le parsing des dates/mois et le calcul du prix moyen du mois."""
    from app.analytics import parse_month_info, compute_monthly_price_stats
    from app.database import init_db, get_db

    init_db()
    # Test parsing
    m_id, m_name, d_str = parse_month_info("2026-01-22")
    assert m_id == "2026-01"
    assert "Janvier 2026" in m_name
    assert d_str == "22"

    m_id2, m_name2, d_str2 = parse_month_info("2026-11")
    assert m_id2 == "2026-11"
    assert "Novembre 2026" in m_name2
    assert d_str2 is None

    # Test calcul avec une route de test
    with get_db() as conn:
        conn.execute("DELETE FROM price_observations WHERE route_id = 999")
        conn.execute("DELETE FROM routes WHERE id = 999")
        conn.execute("""
            INSERT INTO routes (id, origine, destination, dates_ou_mois, passagers, bagage, seuil_eur, actif)
            VALUES (999, 'TEST', 'TEST', '2026-01-22', 1, 'cabine', 100.0, 1)
        """)
        conn.execute("""
            INSERT INTO price_observations (route_id, source, date_vol, date_releve, jours_anticipation, prix_billet_eur, compagnie, escales, niveau_google, fourchette_basse, fourchette_haute, lien)
            VALUES (999, 'google', '2026-01-22', '2026-10-01', 30, 120.0, 'China Southern', 0, 'bas', 100.0, 200.0, '')
        """)

    stats = compute_monthly_price_stats(route_id=999, dates_ou_mois="2026-01-22", baggage_cost=0.0, current_total_price=120.0)
    # Fourchette [100, 200] -> moyenne = 150.0 €
    assert stats["monthly_ticket_avg"] == 150.0
    assert stats["monthly_avg_total"] == 150.0
    # Économie vs moyenne = 150 - 120 = 30.0 € (20.0%)
    assert stats["monthly_savings"] == 30.0
    assert stats["monthly_savings_pct"] == 20.0

def test_nearby_airports_and_radar_deals():
    """Vérifie le cluster des aéroports voisins et l'algorithme du Radar Bons Plans."""
    from app.analytics import get_nearby_airports, scan_radar_deals

    # 1. Test aéroports proches de Zhengzhou
    nearby_cgo = get_nearby_airports("CGO")
    codes = [a["code"] for a in nearby_cgo]
    assert "WUH" in codes
    assert "XIY" in codes
    assert "LYA" in codes

    # 2. Test scan des bons plans
    radar = scan_radar_deals(origin="CGO", include_nearby=True, target_month="2026-01", filter_tag="all")
    assert radar["deals_count"] > 0
    assert len(radar["deals"]) >= 5

    # Vérification que le tri est croissant par prix affiché (incluant le bagage choisi)
    prices = [d["display_price"] for d in radar["deals"]]
    assert prices == sorted(prices)

    # Vérification que le filtre 'broken_only' ne renvoie que des prix cassés
    radar_broken = scan_radar_deals(origin="CGO", include_nearby=True, target_month="2026-11", filter_tag="broken_only")
    for d in radar_broken["deals"]:
        assert d["is_broken"] is True

def test_format_minutes_to_hours():
    """Vérifie la conversion claire des durées en heures et minutes."""
    from app.analytics import format_minutes_to_hours
    assert format_minutes_to_hours(255) == "4h15"
    assert format_minutes_to_hours(180) == "3h00"
    assert format_minutes_to_hours(45) == "45min"
    assert format_minutes_to_hours(0) == "Non spécifiée"
    assert format_minutes_to_hours(None) == "Non spécifiée"

def test_radar_comfort_filters():
    """Vérifie le filtrage anti-trajets trop longs et escales dans le Radar."""
    from app.analytics import scan_radar_deals

    # 1. Filtre vols directs uniquement (0 escale)
    radar_direct = scan_radar_deals(origin="CGO", include_nearby=True, max_stops=0)
    for d in radar_direct["deals"]:
        assert d["stops"] == 0
        assert "Direct" in d["stops_label"]

    # 2. Filtre durée maximale de voyage (ex: max 6 heures total porte-à-porte)
    radar_max_6h = scan_radar_deals(origin="CGO", include_nearby=True, max_duration=6.0)
    for d in radar_max_6h["deals"]:
        # Chaque vol retenu doit avoir une durée totale <= 360 min
        assert "h" in d["total_journey_str"]
        h_part = int(d["total_journey_str"].split("h")[0])
        assert h_part <= 6

    # 3. Vérification de la présence de la source, date explicite et lien protobuf tfs= en EUR
    for d in radar_direct["deals"]:
        assert d["source_name"] != ""
        assert d["date_observation"] != ""
        assert d["dep_date_fr"] != ""
        assert d["schedule_str"] != ""
        assert "curr=EUR" in d["google_link"]
        assert "/travel/flights/search?tfs=" in d["google_link"]

def test_strict_data_integrity_no_synthetic_average():
    """Vérifie qu'aucun pourcentage ni moyenne mensuelle n'est inventé en l'absence d'historique réel."""
    from app.database import get_db
    from app.analytics import compute_monthly_price_stats

    # Créer une route avec 1 seul relevé et SANS fourchette Google
    with get_db() as conn:
        conn.execute("DELETE FROM price_observations WHERE route_id = 888")
        conn.execute("DELETE FROM routes WHERE id = 888")
        conn.execute("""
            INSERT INTO routes (id, origine, destination, dates_ou_mois, passagers, bagage, seuil_eur, actif)
            VALUES (888, 'CGO', 'TEST_SOLO', '2026-11-15', 1, 'cabine', 100.0, 1)
        """)
        conn.execute("""
            INSERT INTO price_observations (route_id, source, date_vol, date_releve, jours_anticipation, prix_billet_eur, compagnie, escales, niveau_google, fourchette_basse, fourchette_haute, lien)
            VALUES (888, 'serpapi', '2026-11-15', '2026-10-01', 45, 120.0, 'Air Test', 0, '', NULL, NULL, '')
        """)

    stats = compute_monthly_price_stats(route_id=888, dates_ou_mois="2026-11-15", baggage_cost=0.0, current_total_price=120.0)
    # Règle d'intégrité : pas de fourchette Google et < 2 relevés => PAS de moyenne inventée, PAS de fausse économie !
    assert stats["monthly_ticket_avg"] is None
    assert stats["monthly_avg_total"] is None
    assert stats["monthly_savings"] is None
    assert stats["monthly_savings_pct"] is None
    assert "Données insuffisantes" in stats["source_avg"]

    # Nettoyage
    with get_db() as conn:
        conn.execute("DELETE FROM price_observations WHERE route_id = 888")
        conn.execute("DELETE FROM routes WHERE id = 888")



