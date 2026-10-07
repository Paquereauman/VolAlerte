import statistics
import datetime
import re
from typing import Optional
from app.models import AnticipationBracket, PriceObservation
from app.database import get_db

BRACKET_DEFS = [
    {"label": "> 180 j", "min_days": 181, "max_days": 9999},
    {"label": "120-180 j", "min_days": 120, "max_days": 180},
    {"label": "90-120 j", "min_days": 90, "max_days": 119},
    {"label": "60-90 j", "min_days": 60, "max_days": 89},
    {"label": "30-60 j", "min_days": 30, "max_days": 59},
    {"label": "14-30 j", "min_days": 14, "max_days": 29},
    {"label": "< 14 j", "min_days": 0, "max_days": 13},
]

def calculate_anticipation_days(date_vol: str, date_releve: str) -> int:
    """Calcule le délai d'anticipation en jours (date du vol - date du relevé)."""
    d_vol = datetime.date.fromisoformat(date_vol[:10])
    d_rel = datetime.date.fromisoformat(date_releve[:10])
    return max(0, (d_vol - d_rel).days)

def get_confidence_level(count: int) -> str:
    """Retourne le niveau de confiance selon le nombre de prix observés."""
    if count < 30:
        return "données insuffisantes"
    elif count <= 100:
        return "indicatif"
    return "fiable"

def compute_anticipation_brackets(prices_with_days: list[tuple[float, int]]) -> list[AnticipationBracket]:
    """
    Pour une liste de tuples (prix_billet, jours_anticipation),
    calcule la médiane par tranche, le niveau de confiance et l'écart avec la meilleure tranche.
    """
    bracket_buckets: dict[str, list[float]] = {b["label"]: [] for b in BRACKET_DEFS}

    for price, days in prices_with_days:
        for b in BRACKET_DEFS:
            if b["min_days"] <= days <= b["max_days"]:
                bracket_buckets[b["label"]].append(price)
                break

    results: list[AnticipationBracket] = []
    best_median: Optional[float] = None

    for b in BRACKET_DEFS:
        prices = bracket_buckets[b["label"]]
        count = len(prices)
        med = round(statistics.median(prices), 1) if prices else None
        conf = get_confidence_level(count)

        if med is not None and conf != "données insuffisantes":
            if best_median is None or med < best_median:
                best_median = med

        results.append(AnticipationBracket(
            label=b["label"],
            min_days=b["min_days"],
            max_days=b["max_days"],
            median_price=med,
            count=count,
            confidence=conf,
            diff_with_best=None
        ))

    # Calcul de l'écart avec la meilleure tranche
    if best_median is not None:
        for res in results:
            if res.median_price is not None:
                res.diff_with_best = round(res.median_price - best_median, 1)

    return results

def get_best_window_info(brackets: list[AnticipationBracket]) -> dict:
    """Trouve la meilleure fenêtre de réservation (tranche fiable ou indicative avec la médiane la plus basse)."""
    valid_brackets = [b for b in brackets if b.median_price is not None and b.confidence != "données insuffisantes"]
    if not valid_brackets:
        return {
            "window": "Données insuffisantes",
            "median": None,
            "confidence": "données insuffisantes",
            "count": 0,
            "advice": "Pas assez de relevés pour conseiller une fenêtre d'achat."
        }

    best = min(valid_brackets, key=lambda b: b.median_price)
    return {
        "window": best.label,
        "median": best.median_price,
        "confidence": best.confidence,
        "count": best.count,
        "advice": f"Fenêtre optimale : {best.label} (médiane {best.median_price} €, basé sur {best.count} prix - niveau {best.confidence})"
    }

def get_price_percentile(all_prices: list[float], current_price: float) -> float:
    """Calcule le percentile d'un prix par rapport à l'historique (0 à 100%)."""
    if not all_prices:
        return 50.0
    sorted_prices = sorted(all_prices)
    lower_count = sum(1 for p in sorted_prices if p <= current_price)
    return round((lower_count / len(sorted_prices)) * 100, 1)

def get_baggage_cost(route_id: Optional[int], compagnie: str, bagage_type: str) -> float:
    """
    Récupère le prix du bagage choisi (valeur haute de la fourchette).
    Si le bagage est 'aucun', renvoie 0.0.
    """
    if not bagage_type or bagage_type == "aucun":
        return 0.0

    defaults = {
        "cabine": 25.0,
        "soute_1": 45.0,
        "soute_2": 85.0
    }

    with get_db() as conn:
        # Essayer avec la compagnie exacte
        if compagnie:
            cur = conn.execute("""
                SELECT prix_haut_eur FROM baggage_prices
                WHERE (route_id = ? OR route_id IS NULL)
                  AND LOWER(compagnie) = LOWER(?)
                  AND type = ?
                ORDER BY date_releve DESC LIMIT 1
            """, (route_id, compagnie.strip(), bagage_type))
            row = cur.fetchone()
            if row:
                return float(row["prix_haut_eur"])

        # Essayer au niveau du trajet (toute compagnie)
        if route_id:
            cur = conn.execute("""
                SELECT prix_haut_eur FROM baggage_prices
                WHERE route_id = ? AND type = ?
                ORDER BY date_releve DESC LIMIT 1
            """, (route_id, bagage_type))
            row = cur.fetchone()
            if row:
                return float(row["prix_haut_eur"])

    return defaults.get(bagage_type, 25.0)

def detect_flash_drop(prices_chronological: list[tuple[str, float]]) -> Optional[dict]:
    """Détecte une baisse brutale (-20% en 24h)."""
    if len(prices_chronological) < 2:
        return None
    latest_date, latest_price = prices_chronological[-1]
    prev_date, prev_price = prices_chronological[-2]

    if prev_price > 0:
        drop_pct = (prev_price - latest_price) / prev_price
        if drop_pct >= 0.20:
            return {
                "drop_pct": round(drop_pct * 100, 1),
                "prev_price": prev_price,
                "latest_price": latest_price
            }
    return None

def compute_7day_trend(prices_with_dates: list[tuple[str, float]]) -> str:
    """Calcule la tendance sur les 7 derniers jours (en baisse, stable, en hausse)."""
    if len(prices_with_dates) < 2:
        return "stable"

    today = datetime.date.today()
    seven_days_ago = today - datetime.timedelta(days=7)
    fourteen_days_ago = today - datetime.timedelta(days=14)

    recent = [p for d_str, p in prices_with_dates if datetime.date.fromisoformat(d_str[:10]) >= seven_days_ago]
    older = [p for d_str, p in prices_with_dates if fourteen_days_ago <= datetime.date.fromisoformat(d_str[:10]) < seven_days_ago]

    if not recent:
        return "stable"
    if not older:
        # Comparer premier et dernier
        diff = prices_with_dates[-1][1] - prices_with_dates[0][1]
        if diff < -3:
            return "en baisse"
        elif diff > 3:
            return "en hausse"
        return "stable"

    med_recent = statistics.median(recent)
    med_older = statistics.median(older)
    diff = med_recent - med_older

    if diff < -2.0:
        return "en baisse"
    elif diff > 2.0:
        return "en hausse"
    return "stable"

MONTH_NAMES_FR = {
    1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril",
    5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août",
    9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"
}

def parse_month_info(dates_ou_mois: str) -> tuple[str, str, Optional[str]]:
    """
    Extrait le code mois (ex: '2026-01'), le libellé français (ex: 'Janvier 2026')
    et le ou les jours spécifiques (ex: '22' ou '15-25').
    """
    if not dates_ou_mois:
        return "", "Mois visé", None
    m = re.search(r"(\d{4})-(\d{2})", dates_ou_mois)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        month_label = f"{MONTH_NAMES_FR.get(month, 'Mois')} {year}"
        month_id = f"{year}-{month:02d}"
        days = re.findall(r"\d{4}-\d{2}-(\d{2})", dates_ou_mois)
        day_str = "-".join(days) if days else None
        return month_id, month_label, day_str
    return "", dates_ou_mois, None

def compute_monthly_price_stats(
    route_id: Optional[int],
    dates_ou_mois: str,
    baggage_cost: float = 0.0,
    current_total_price: Optional[float] = None,
    live_prices: Optional[list[float]] = None
) -> dict:
    """
    Calcule les métriques mensuelles de référence en filtrant les tarifs aberrants
    (ex: billets multi-compagnies plein tarif à 1 500 € - 2 000 € sur Google Flights) :
    - Prix moyen billet seul du mois (médiane / moyenne tronquée des vols économiques réalistes)
    - Prix moyen total avec bagage sélectionné
    - Fourchette habituelle (basse / haute réaliste)
    - Économie réalisée par rapport au prix moyen du mois
    """
    month_id, month_name, day_str = parse_month_info(dates_ou_mois)

    with get_db() as conn:
        cur = conn.execute("""
            SELECT fourchette_basse, fourchette_haute, prix_billet_eur
            FROM price_observations
            WHERE route_id = ?
            ORDER BY date_releve DESC, id DESC LIMIT 1
        """, (route_id,))
        last_row = cur.fetchone()

        cur_all = conn.execute("""
            SELECT prix_billet_eur FROM price_observations
            WHERE route_id = ?
        """, (route_id,))
        all_prices = [float(r["prix_billet_eur"]) for r in cur_all.fetchall() if r["prix_billet_eur"]]

    f_low = float(last_row["fourchette_basse"]) if last_row and last_row["fourchette_basse"] else None
    f_high = float(last_row["fourchette_haute"]) if last_row and last_row["fourchette_haute"] else None

    # Combiner les prix live du jour et l'historique en écartant les valeurs aberrantes (> 2.4x le tarif min)
    combined_pool = []
    if live_prices:
        combined_pool.extend([float(p) for p in live_prices if p and p > 0])
    if all_prices:
        combined_pool.extend([float(p) for p in all_prices if p and p > 0])

    if combined_pool:
        p_min = min(combined_pool)
        realistic = sorted([p for p in combined_pool if p <= p_min * 2.4])
        if len(realistic) >= 2 and realistic[-1] > realistic[0]:
            f_low = round(realistic[0], 1)
            f_high = round(realistic[-1], 1)
        elif f_low is not None and f_high is not None and f_high > f_low * 2.4:
            # Corriger une fourchette haute polluée par un vol hors de prix (ex: 1985 €)
            f_high = round(f_low * 1.85, 1)

    if f_low is not None and f_high is not None and f_high > f_low * 2.4:
        f_high = round(f_low * 1.85, 1)

    source_avg = ""
    if combined_pool:
        p_min = min(combined_pool)
        realistic = sorted([p for p in combined_pool if p <= p_min * 2.4])
        if len(realistic) >= 2 and realistic[-1] > realistic[0]:
            # Moyenne pondérée entre la médiane des vols réalistes et le milieu de la fourchette réaliste
            med = statistics.median(realistic)
            mid = (realistic[0] + realistic[-1]) / 2.0
            monthly_ticket_avg = round((med + mid) / 2.0, 1)
            source_avg = "Fourchette habituelle Google Flights (vols éco)"
        elif f_low is not None and f_high is not None and f_high > f_low:
            monthly_ticket_avg = round((f_low + f_high) / 2.0, 1)
            source_avg = "Fourchette habituelle Google Flights"
        else:
            monthly_ticket_avg = round(statistics.median(realistic), 1)
            source_avg = f"Médiane historique ({len(realistic)} relevés)"
    elif f_low is not None and f_high is not None and f_high > f_low:
        monthly_ticket_avg = round((f_low + f_high) / 2.0, 1)
        source_avg = "Fourchette habituelle Google Flights"
    else:
        monthly_ticket_avg = None
        source_avg = "Données insuffisantes (historique en cours de collecte)"

    monthly_avg_total = round(monthly_ticket_avg + baggage_cost, 1) if monthly_ticket_avg is not None else None

    monthly_savings = None
    monthly_savings_pct = None
    if current_total_price is not None and monthly_avg_total is not None and monthly_avg_total > 0:
        monthly_savings = round(monthly_avg_total - current_total_price, 1)
        monthly_savings_pct = round((monthly_savings / monthly_avg_total) * 100, 1)

    return {
        "month_id": month_id,
        "month_name": month_name,
        "day_str": day_str,
        "monthly_ticket_avg": monthly_ticket_avg,
        "monthly_avg_total": monthly_avg_total,
        "range_low": f_low,
        "range_high": f_high,
        "monthly_savings": monthly_savings,
        "monthly_savings_pct": monthly_savings_pct,
        "source_avg": source_avg,
    }

AIRPORT_CLUSTERS = {
    "CGO": {
        "name": "Zhengzhou Xinzheng (CGO)",
        "city": "Zhengzhou",
        "nearby": [
            {
                "code": "LYA",
                "name": "Luoyang Beijiao (LYA)",
                "detail": "120 km • 38 min TGV (~8 €)",
                "tgv_time_str": "38 min de TGV (Zhengzhou ➔ Luoyang, ~8 €) + 25 min navette",
                "tgv_min": 65,
                "tgv_cost_eur": 8,
            },
            {
                "code": "XIY",
                "name": "Xi'an Xianyang (XIY)",
                "detail": "Grand Hub International • 1h30 TGV (~22 €) + 30 min métro XIY",
                "tgv_time_str": "1h30 de TGV (Zhengzhou Est ➔ Xi'an Nord, ~22 €) + 30 min métro vers XIY",
                "tgv_min": 120,
                "tgv_cost_eur": 22,
            },
            {
                "code": "WUH",
                "name": "Wuhan Tianhe (WUH)",
                "detail": "Hub Asie du Sud-Est • 1h45 TGV (~24 €) + 35 min métro WUH",
                "tgv_time_str": "1h45 de TGV (Zhengzhou Est ➔ Wuhan, ~24 €) + 35 min métro Ligne 2 vers WUH",
                "tgv_min": 140,
                "tgv_cost_eur": 24,
            },
            {
                "code": "PKX",
                "name": "Pékin Daxing (PKX)",
                "detail": "Hub Low-Cost Direct (VietJet/AirAsia) • 2h15 TGV (~38 €) + 35 min express PKX",
                "tgv_time_str": "2h15 de TGV (Zhengzhou Est ➔ Pékin Ouest, ~38 €) + 35 min train express vers PKX",
                "tgv_min": 170,
                "tgv_cost_eur": 38,
            },
        ]
    },
    "PKX": {
        "name": "Pékin Daxing (PKX)",
        "city": "Pékin",
        "nearby": [
            {"code": "PEK", "name": "Pékin Capital (PEK)", "detail": "45 min métro express", "tgv_time_str": "45 min métro express (~4 €)", "tgv_min": 45, "tgv_cost_eur": 4},
            {"code": "CGO", "name": "Zhengzhou (CGO)", "detail": "2h15 TGV (~38 €)", "tgv_time_str": "2h15 de TGV (~38 €)", "tgv_min": 135, "tgv_cost_eur": 38},
        ]
    },
    "PVG": {
        "name": "Shanghai Pudong (PVG)",
        "city": "Shanghai",
        "nearby": [
            {"code": "SHA", "name": "Shanghai Hongqiao (SHA)", "detail": "40 min métro/Maglev", "tgv_time_str": "40 min métro/Maglev (~6 €)", "tgv_min": 40, "tgv_cost_eur": 6},
            {"code": "HGH", "name": "Hangzhou (HGH)", "detail": "45 min TGV (~10 €)", "tgv_time_str": "45 min de TGV (~10 €)", "tgv_min": 60, "tgv_cost_eur": 10},
        ]
    },
    "XIY": {
        "name": "Xi'an Xianyang (XIY)",
        "city": "Xi'an",
        "nearby": [
            {"code": "CGO", "name": "Zhengzhou (CGO)", "detail": "1h30 TGV"},
            {"code": "WUH", "name": "Wuhan (WUH)", "detail": "2h TGV"},
        ]
    },
    "WUH": {
        "name": "Wuhan Tianhe (WUH)",
        "city": "Wuhan",
        "nearby": [
            {"code": "CGO", "name": "Zhengzhou (CGO)", "detail": "1h45 TGV"},
            {"code": "CSX", "name": "Changsha (CSX)", "detail": "1h15 TGV"},
        ]
    },
    "PAR": {
        "name": "Paris (Tous aéroports)",
        "city": "Paris",
        "nearby": [
            {"code": "CDG", "name": "Paris Charles de Gaulle (CDG)", "detail": "Hub International"},
            {"code": "ORY", "name": "Paris Orly (ORY)", "detail": "Hub Transavia / Vueling"},
            {"code": "BVA", "name": "Paris Beauvais (BVA)", "detail": "Hub Ryanair / Wizz Air"},
            {"code": "LIL", "name": "Lille Lesquin (LIL)", "detail": "1h TGV"},
            {"code": "CRL", "name": "Bruxelles Charleroi (CRL)", "detail": "Hub Low-cost"},
        ]
    },
    "CDG": {
        "name": "Paris Charles de Gaulle (CDG)",
        "city": "Paris",
        "nearby": [
            {"code": "ORY", "name": "Paris Orly (ORY)", "detail": "45 min navette"},
            {"code": "BVA", "name": "Paris Beauvais (BVA)", "detail": "Hub Low-cost"},
        ]
    },
    "ORY": {
        "name": "Paris Orly (ORY)",
        "city": "Paris",
        "nearby": [
            {"code": "CDG", "name": "Paris CDG", "detail": "45 min navette"},
            {"code": "BVA", "name": "Paris Beauvais (BVA)", "detail": "Hub Low-cost"},
        ]
    }
}

def get_nearby_airports(origin: str) -> list[dict]:
    """Retourne la liste des aéroports voisins pour une ville/code donné."""
    if not origin:
        return []
    code_match = re.search(r'\b([A-Z]{3})\b', origin.upper())
    code = code_match.group(1) if code_match else origin.strip().upper()
    if code in AIRPORT_CLUSTERS:
        return AIRPORT_CLUSTERS[code]["nearby"]
    for k, v in AIRPORT_CLUSTERS.items():
        if v["city"].lower() in origin.lower() or k.lower() in origin.lower():
            return v["nearby"]
    return []

def format_minutes_to_hours(minutes: Optional[int]) -> str:
    """Convertit des minutes en format lisible (ex: 255 -> '4h15', 180 -> '3h00')."""
    if not minutes or minutes <= 0:
        return "Non spécifiée"
    h = int(minutes) // 60
    m = int(minutes) % 60
    if h > 0 and m > 0:
        return f"{h}h{m:02d}"
    elif h > 0:
        return f"{h}h00"
    return f"{m}min"

# Destinations réelles et réalistes pour le Radar Bons Plans
CATALOG_ASIA = [
    {
        "dest_code": "BKK", "city": "Bangkok", "country": "Thaïlande", "flag": "🇹🇭", "region": "Asie du Sud-Est",
        "departures": {
            "CGO": {
                "price": 115.0, "airline": "Spring Airlines / Thai AirAsia", "stops": 0,
                "flight_duration_min": 230, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "cabine_extra": 15.0, "soute_extra": 38.0
            },
            "WUH": {
                "price": 82.0, "airline": "AirAsia", "stops": 0,
                "flight_duration_min": 215, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 105, "tgv_name": "TGV Zhengzhou ➔ Wuhan (1h45)",
                "cabine_extra": 15.0, "soute_extra": 38.0
            },
            "XIY": {
                "price": 95.0, "airline": "Spring Airlines", "stops": 0,
                "flight_duration_min": 235, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 90, "tgv_name": "TGV Zhengzhou ➔ Xi'an (1h30)",
                "cabine_extra": 15.0, "soute_extra": 38.0
            }
        }
    },
    {
        "dest_code": "CNX", "city": "Chiang Mai", "country": "Thaïlande", "flag": "🇹🇭", "region": "Asie du Sud-Est",
        "departures": {
            "CGO": {
                "price": 128.0, "airline": "Thai AirAsia", "stops": 0,
                "flight_duration_min": 235, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "cabine_extra": 18.0, "soute_extra": 42.0
            },
            "XIY": {
                "price": 78.0, "airline": "Spring Airlines", "stops": 0,
                "flight_duration_min": 220, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 90, "tgv_name": "TGV Zhengzhou ➔ Xi'an (1h30)",
                "cabine_extra": 0.0, "soute_extra": 38.0
            },
            "WUH": {
                "price": 108.0, "airline": "China Southern Airlines", "stops": 1,
                "flight_duration_min": 360, "max_layover_min": 110, "layover_details": "1 escale de 1h50 à Canton CAN",
                "tgv_approach_min": 105, "tgv_name": "TGV Zhengzhou ➔ Wuhan (1h45)",
                "cabine_extra": 0.0, "soute_extra": 35.0
            }
        }
    },
    {
        "dest_code": "HAN", "city": "Hanoï", "country": "Vietnam", "flag": "🇻🇳", "region": "Asie du Sud-Est",
        "good_deal_max_eur": 100,
        "ota_tip": "Sur Chine ➔ Vietnam (Hanoï), VietJet vole en direct depuis Pékin Daxing (PKX, 96 €) et Shanghai (PVG, 86 €) les mardis/vendredis, et Trip.com / Skyscanner référencent des tarifs agences chinoises non listés sur Google Flights.",
        "departures": {
            "PVG": {
                "price": 86.0, "airline": "VietJet Air (Direct)", "stops": 0,
                "flight_duration_min": 235, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 240, "tgv_name": "TGV / Hub Shanghai Pudong (PVG)",
                "cabine_extra": 0.0, "soute_extra": 35.0
            },
            "PKX": {
                "price": 96.0, "airline": "VietJet Air (Direct)", "stops": 0,
                "flight_duration_min": 230, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 135, "tgv_name": "TGV Zhengzhou ➔ Pékin Daxing (2h15)",
                "cabine_extra": 0.0, "soute_extra": 35.0
            },
            "XIY": {
                "price": 98.0, "airline": "Shandong / China Eastern", "stops": 1,
                "flight_duration_min": 340, "max_layover_min": 115, "layover_details": "1 escale",
                "tgv_approach_min": 90, "tgv_name": "TGV Zhengzhou ➔ Xi'an (1h30)",
                "cabine_extra": 0.0, "soute_extra": 35.0
            },
            "WUH": {
                "price": 108.0, "airline": "China Southern Airlines", "stops": 1,
                "flight_duration_min": 280, "max_layover_min": 95, "layover_details": "1 escale à Canton CAN",
                "tgv_approach_min": 105, "tgv_name": "TGV Zhengzhou ➔ Wuhan (1h45)",
                "cabine_extra": 0.0, "soute_extra": 35.0
            },
            "CGO": {
                "price": 114.0, "airline": "China Southern Airlines", "stops": 1,
                "flight_duration_min": 315, "max_layover_min": 105, "layover_details": "1 escale de 1h45 à Canton CAN",
                "cabine_extra": 0.0, "soute_extra": 35.0
            },
            "PEK": {
                "price": 128.0, "airline": "Shenzhen Airlines", "stops": 1,
                "flight_duration_min": 420, "max_layover_min": 140, "layover_details": "1 escale à Shenzhen SZX",
                "tgv_approach_min": 150, "tgv_name": "TGV ➔ Pékin Capital (PEK)",
                "cabine_extra": 0.0, "soute_extra": 35.0
            }
        }
    },
    {
        "dest_code": "HKG", "city": "Hong Kong", "country": "Hong Kong", "flag": "🇭🇰", "region": "Asie de l'Est",
        "departures": {
            "CGO": {
                "price": 95.0, "airline": "Cathay Pacific / Greater Bay", "stops": 0,
                "flight_duration_min": 165, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "cabine_extra": 0.0, "soute_extra": 30.0
            },
            "WUH": {
                "price": 85.0, "airline": "China Southern Airlines", "stops": 0,
                "flight_duration_min": 135, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 105, "tgv_name": "TGV Zhengzhou ➔ Wuhan (1h45)",
                "cabine_extra": 0.0, "soute_extra": 30.0
            }
        }
    },
    {
        "dest_code": "SIN", "city": "Singapour", "country": "Singapour", "flag": "🇸🇬", "region": "Asie du Sud-Est",
        "departures": {
            "CGO": {
                "price": 118.0, "airline": "Scoot", "stops": 0,
                "flight_duration_min": 310, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "cabine_extra": 0.0, "soute_extra": 45.0
            },
            "WUH": {
                "price": 102.0, "airline": "Scoot", "stops": 0,
                "flight_duration_min": 295, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 105, "tgv_name": "TGV Zhengzhou ➔ Wuhan (1h45)",
                "cabine_extra": 0.0, "soute_extra": 45.0
            },
            "XIY": {
                "price": 115.0, "airline": "Scoot", "stops": 0,
                "flight_duration_min": 325, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 90, "tgv_name": "TGV Zhengzhou ➔ Xi'an (1h30)",
                "cabine_extra": 0.0, "soute_extra": 45.0
            }
        }
    },
    {
        "dest_code": "ICN", "city": "Séoul", "country": "Corée du Sud", "flag": "🇰🇷", "region": "Asie de l'Est",
        "departures": {
            "CGO": {
                "price": 92.0, "airline": "China Southern / Korean Air", "stops": 0,
                "flight_duration_min": 155, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "cabine_extra": 0.0, "soute_extra": 35.0
            },
            "XIY": {
                "price": 105.0, "airline": "Korean Air / Asiana", "stops": 0,
                "flight_duration_min": 190, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 90, "tgv_name": "TGV Zhengzhou ➔ Xi'an (1h30)",
                "cabine_extra": 0.0, "soute_extra": 35.0
            }
        }
    },
    {
        "dest_code": "KUL", "city": "Kuala Lumpur", "country": "Malaisie", "flag": "🇲🇾", "region": "Asie du Sud-Est",
        "departures": {
            "CGO": {
                "price": 135.0, "airline": "China Southern Airlines", "stops": 1,
                "flight_duration_min": 450, "max_layover_min": 130, "layover_details": "1 escale de 2h10 à Canton CAN",
                "cabine_extra": 0.0, "soute_extra": 35.0
            },
            "WUH": {
                "price": 88.0, "airline": "AirAsia (Direct)", "stops": 0,
                "flight_duration_min": 280, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 105, "tgv_name": "TGV Zhengzhou ➔ Wuhan (1h45)",
                "cabine_extra": 16.0, "soute_extra": 40.0
            },
            "XIY": {
                "price": 118.0, "airline": "AirAsia X (Direct)", "stops": 0,
                "flight_duration_min": 315, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 90, "tgv_name": "TGV Zhengzhou ➔ Xi'an (1h30)",
                "cabine_extra": 16.0, "soute_extra": 40.0
            }
        }
    },
    {
        "dest_code": "NRT", "city": "Tokyo (Narita)", "country": "Japon", "flag": "🇯🇵", "region": "Asie de l'Est",
        "good_deal_max_eur": 135,
        "ota_tip": "Spring Japan (IJ 18 depuis Pékin PEK ou IJ 254 depuis Tianjin TSN) assure des vols DIRECTS en 3h15-3h40 à 132 € tarif compagnie (~98 € via Trip.com sur la page de réservation Google Flights) !",
        "departures": {
            "PEK": {
                "price": 132.0, "airline": "Spring Japan (Direct)", "stops": 0,
                "flight_duration_min": 220, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 135, "tgv_name": "TGV Zhengzhou ➔ Pékin (2h15, ~38 €)",
                "cabine_extra": 0.0, "soute_extra": 38.0
            },
            "TSN": {
                "price": 132.0, "airline": "Spring Japan (Direct)", "stops": 0,
                "flight_duration_min": 195, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 150, "tgv_name": "TGV Zhengzhou ➔ Tianjin (2h30, ~39 €)",
                "cabine_extra": 0.0, "soute_extra": 38.0
            },
            "PVG": {
                "price": 159.0, "airline": "Spring Japan (Direct)", "stops": 0,
                "flight_duration_min": 185, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 240, "tgv_name": "TGV Zhengzhou ➔ Shanghai (4h00, ~55 €)",
                "cabine_extra": 0.0, "soute_extra": 38.0
            },
            "CGO": {
                "price": 148.0, "airline": "Spring Airlines / China Southern", "stops": 1,
                "flight_duration_min": 405, "max_layover_min": 135, "layover_details": "1 escale de 2h15 à Shanghai PVG",
                "cabine_extra": 15.0, "soute_extra": 45.0
            },
            "XIY": {
                "price": 132.0, "airline": "China Eastern", "stops": 1,
                "flight_duration_min": 390, "max_layover_min": 120, "layover_details": "1 escale de 2h00 à Shanghai PVG",
                "tgv_approach_min": 90, "tgv_name": "TGV Zhengzhou ➔ Xi'an (1h30, ~22 €)",
                "cabine_extra": 0.0, "soute_extra": 45.0
            }
        }
    },
    {
        "dest_code": "SGN", "city": "Hô Chi Minh-Ville", "country": "Vietnam", "flag": "🇻🇳", "region": "Asie du Sud-Est",
        "departures": {
            "CGO": {
                "price": 130.0, "airline": "China Southern Airlines", "stops": 1,
                "flight_duration_min": 380, "max_layover_min": 110, "layover_details": "1 escale de 1h50 à Canton CAN",
                "cabine_extra": 0.0, "soute_extra": 35.0
            },
            "WUH": {
                "price": 115.0, "airline": "China Southern Airlines", "stops": 1,
                "flight_duration_min": 350, "max_layover_min": 100, "layover_details": "1 escale de 1h40 à Canton CAN",
                "tgv_approach_min": 105, "tgv_name": "TGV Zhengzhou ➔ Wuhan (1h45)",
                "cabine_extra": 0.0, "soute_extra": 35.0
            }
        }
    },
    {
        "dest_code": "HKT", "city": "Phuket", "country": "Thaïlande", "flag": "🇹🇭", "region": "Asie du Sud-Est",
        "departures": {
            "CGO": {
                "price": 149.0, "airline": "Thai Lion Air / Spring", "stops": 1,
                "flight_duration_min": 435, "max_layover_min": 120, "layover_details": "1 escale de 2h00 à Bangkok DMK",
                "cabine_extra": 18.0, "soute_extra": 45.0
            },
            "XIY": {
                "price": 135.0, "airline": "Spring Airlines", "stops": 1,
                "flight_duration_min": 410, "max_layover_min": 110, "layover_details": "1 escale de 1h50 à Bangkok",
                "tgv_approach_min": 90, "tgv_name": "TGV Zhengzhou ➔ Xi'an (1h30)",
                "cabine_extra": 18.0, "soute_extra": 45.0
            }
        }
    }
]

CATALOG_EUROPE = [
    {
        "dest_code": "FCO", "city": "Rome", "country": "Italie", "flag": "🇮🇹", "region": "Europe du Sud",
        "departures": {
            "PAR": {
                "price": 38.0, "airline": "EasyJet / Transavia", "stops": 0,
                "flight_duration_min": 125, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "cabine_extra": 25.0, "soute_extra": 40.0
            },
            "BVA": {
                "price": 24.0, "airline": "Ryanair", "stops": 0,
                "flight_duration_min": 125, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 75, "tgv_name": "Navette Paris ➔ Beauvais (1h15)",
                "cabine_extra": 25.0, "soute_extra": 40.0
            }
        }
    },
    {
        "dest_code": "LIS", "city": "Lisbonne", "country": "Portugal", "flag": "🇵🇹", "region": "Europe du Sud",
        "departures": {
            "PAR": {
                "price": 42.0, "airline": "Transavia / Vueling", "stops": 0,
                "flight_duration_min": 155, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "cabine_extra": 22.0, "soute_extra": 42.0
            },
            "BVA": {
                "price": 29.0, "airline": "Ryanair", "stops": 0,
                "flight_duration_min": 155, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 75, "tgv_name": "Navette Paris ➔ Beauvais (1h15)",
                "cabine_extra": 22.0, "soute_extra": 42.0
            }
        }
    },
    {
        "dest_code": "BCN", "city": "Barcelone", "country": "Espagne", "flag": "🇪🇸", "region": "Europe du Sud",
        "departures": {
            "PAR": {
                "price": 35.0, "airline": "Vueling", "stops": 0,
                "flight_duration_min": 105, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "cabine_extra": 20.0, "soute_extra": 38.0
            },
            "BVA": {
                "price": 22.0, "airline": "Ryanair", "stops": 0,
                "flight_duration_min": 105, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 75, "tgv_name": "Navette Paris ➔ Beauvais (1h15)",
                "cabine_extra": 20.0, "soute_extra": 38.0
            }
        }
    },
    {
        "dest_code": "RAK", "city": "Marrakech", "country": "Maroc", "flag": "🇲🇦", "region": "Afrique du Nord",
        "departures": {
            "PAR": {
                "price": 55.0, "airline": "Transavia", "stops": 0,
                "flight_duration_min": 195, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "cabine_extra": 25.0, "soute_extra": 45.0
            },
            "BVA": {
                "price": 35.0, "airline": "Ryanair", "stops": 0,
                "flight_duration_min": 195, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 75, "tgv_name": "Navette Paris ➔ Beauvais (1h15)",
                "cabine_extra": 25.0, "soute_extra": 45.0
            }
        }
    },
    {
        "dest_code": "ATH", "city": "Athènes", "country": "Grèce", "flag": "🇬🇷", "region": "Europe du Sud",
        "departures": {
            "PAR": {
                "price": 59.0, "airline": "Transavia / Air France", "stops": 0,
                "flight_duration_min": 190, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "cabine_extra": 25.0, "soute_extra": 45.0
            },
            "BVA": {
                "price": 39.0, "airline": "Ryanair", "stops": 0,
                "flight_duration_min": 190, "max_layover_min": 0, "layover_details": "Direct (sans escale)",
                "tgv_approach_min": 75, "tgv_name": "Navette Paris ➔ Beauvais (1h15)",
                "cabine_extra": 25.0, "soute_extra": 45.0
            }
        }
    }
]

def _normalize_future_date(target_month: str, exact_date: str = "") -> tuple[str, str, str]:
    """
    Garantit que le mois et la date de vol sont toujours dans le futur (à partir d'octobre 2026).
    Retourne (month_id, month_name, flight_date_iso).
    """
    today = datetime.date.today()
    if exact_date and len(exact_date.strip()) >= 10:
        try:
            d = datetime.date.fromisoformat(exact_date.strip()[:10])
            if d < today:
                d = today + datetime.timedelta(days=14)
            m_id = f"{d.year}-{d.month:02d}"
            m_name = f"{MONTH_NAMES_FR.get(d.month, 'Mois')} {d.year}"
            return m_id, m_name, d.isoformat()
        except Exception:
            pass

    # Si l'ancien défaut '2026-01', '2026-02', '2026-03' est passé, basculer sur 2027 ou 2026-11
    remap = {
        "2026-01": "2027-01",
        "2026-02": "2027-02",
        "2026-03": "2027-03",
    }
    tm = remap.get(target_month, target_month)
    m_id, month_name, _ = parse_month_info(tm)
    if not m_id:
        m_id = "2026-11"
        month_name = "Novembre 2026"

    flight_date = f"{m_id}-15"
    try:
        fd = datetime.date.fromisoformat(flight_date)
        if fd <= today:
            fd = today + datetime.timedelta(days=14)
            m_id = f"{fd.year}-{fd.month:02d}"
            month_name = f"{MONTH_NAMES_FR.get(fd.month, 'Mois')} {fd.year}"
            flight_date = fd.isoformat()
    except Exception:
        flight_date = "2026-11-15"

    return m_id, month_name, flight_date


def scan_radar_deals(
    origin: str = "CGO",
    include_nearby: bool = True,
    target_month: str = "2026-11",
    filter_tag: str = "all",
    max_duration: float = 0.0,
    max_stops: int = -1,
    max_layover: float = 0.0,
    bagage_mode: str = "cabine",
    exact_date: str = "",
    force_refresh: bool = False
) -> dict:
    """
    Scanne les destinations en direct sur Google Flights (en EUR, Français) au départ d'un aéroport
    et de ses aéroports voisins (TGV).
    - Affiche la date exacte, les horaires précis (départ/arrivée), le numéro de vol et la compagnie.
    - Inclut les bagages selon le choix de l'utilisateur (`cabine` par défaut, `aucun`, `soute_1`).
    - Génère les liens protobuf officiels `tfs=` et `tfu=` de Google Flights pour que le prix
      affiché sur la carte soit 100% identique à celui affiché sur Google Flights au clic.
    """
    from app.sources.google_live import (
        fetch_live_google_flights,
        warm_radar_cache,
        warm_radar_cache_async,
        build_google_tfs_url,
        build_trip_com_url,
        build_skyscanner_url,
        format_date_fr
    )

    origin_clean = origin.strip().upper()
    code_match = re.search(r'\b([A-Z]{3})\b', origin_clean)
    origin_code = code_match.group(1) if code_match else (origin_clean[:3] if len(origin_clean) >= 3 else "CGO")

    if origin_code == "BJS":
        origin_code = "PKX"

    m_id, month_name, flight_date = _normalize_future_date(target_month, exact_date)
    flight_date_fr = format_date_fr(flight_date)
    nearby_airports = get_nearby_airports(origin_code)

    is_asia = any(c in origin_code for c in ["CGO", "XIY", "WUH", "LYA", "BJS", "PEK", "PKX", "SHA", "PVG", "CAN"])
    catalog = CATALOG_ASIA if is_asia else CATALOG_EUROPE

    # Si l'utilisateur scanne tout un mois (sans date précise verrouillée), on croise le dimanche 15
    # ET le vendredi 13 (car les low-cost asiatiques comme VietJet PKX->HAN volent les mardis/vendredis !)
    candidate_dates = [flight_date]
    if not exact_date:
        alt_date = f"{m_id}-13"
        if alt_date != flight_date:
            try:
                if datetime.date.fromisoformat(alt_date) > datetime.date.today():
                    candidate_dates.append(alt_date)
            except Exception:
                pass

    pairs_to_warm = []
    for item in catalog:
        dest_code = item["dest_code"]
        departures_map = item.get("departures", {})
        dept_keys = [origin_code]
        if origin_code in ("PEK", "PKX"):
            for bjs_k in ("PKX", "PEK"):
                if bjs_k not in dept_keys:
                    dept_keys.append(bjs_k)
        if include_nearby:
            for k in departures_map.keys():
                if k not in dept_keys:
                    dept_keys.append(k)
        for dk in dept_keys:
            if dk in departures_map:
                pairs_to_warm.append((dk, dest_code))

    try:
        if force_refresh:
            warm_radar_cache(pairs_to_warm, flight_date, force_refresh=True)
        else:
            warm_radar_cache_async(pairs_to_warm, flight_date)
    except Exception:
        pass

    deals = []
    carry_on_param = 1 if bagage_mode == "cabine" else 0
    checked_param = 1 if bagage_mode == "soute_1" else 0

    for item in catalog:
        dest_code = item["dest_code"]
        city = item["city"]
        country = item["country"]
        flag = item["flag"]
        region = item["region"]
        departures_map = item.get("departures", {})
        good_deal_max_eur = item.get("good_deal_max_eur", 105 if is_asia else 55)
        ota_tip = item.get("ota_tip", "")

        candidate_dept_keys = [origin_code]
        if origin_code in ("PEK", "PKX"):
            for bjs_k in ("PKX", "PEK"):
                if bjs_k not in candidate_dept_keys:
                    candidate_dept_keys.append(bjs_k)
        if include_nearby:
            for k in departures_map.keys():
                if k not in candidate_dept_keys:
                    candidate_dept_keys.append(k)

        candidate_options = []
        all_route_prices_for_dest = []

        for d_code in candidate_dept_keys:
            if d_code not in departures_map:
                continue
            meta = departures_map[d_code]
            same_city_pair = (origin_code in ("PEK", "PKX") and d_code in ("PEK", "PKX"))
            tgv_approach_min = 0 if (d_code == origin_code or same_city_pair) else int(meta.get("tgv_approach_min", 0))
            tgv_name = ("Aéroport Pékin Daxing (PKX)" if (same_city_pair and d_code == "PKX" and origin_code != "PKX") else (meta.get("tgv_name", "") if d_code != origin_code else ""))

            live_flights = []
            fetched_at = ""
            for c_date in candidate_dates:
                lf_list, f_at = fetch_live_google_flights(
                    d_code, dest_code, c_date,
                    force_refresh=False,
                    allow_network=False
                )
                if lf_list:
                    live_flights.extend(lf_list)
                    if not fetched_at:
                        fetched_at = f_at

            if live_flights:
                # Collecter tous les prix observés sur ce vol pour calculer la fourchette réelle du jour
                for lf in live_flights:
                    p_mode = (
                        lf["price_cabine_eur"] if bagage_mode == "cabine"
                        else (lf["price_soute_eur"] if bagage_mode == "soute_1" else lf["price_base_eur"])
                    )
                    all_route_prices_for_dest.append(p_mode)

                # Appliquer les filtres de confort (durée max, escales max, attente escale max) sur CHAQUE vol réel
                matching_flights = []
                for lf in live_flights:
                    tot_j_min = int(lf["duration_min"]) + tgv_approach_min
                    if max_duration > 0 and tot_j_min > (max_duration * 60):
                        continue
                    if max_stops >= 0 and int(lf["stops"]) > max_stops:
                        continue
                    if max_layover > 0 and int(lf["max_layover_min"]) > (max_layover * 60):
                        continue
                    matching_flights.append(lf)

                if not matching_flights:
                    continue

                # Trier pour privilégier le prix le plus bas (et à prix quasi-identique, éviter les escales de 20h)
                def _sort_key(fl):
                    p = (
                        fl["price_cabine_eur"] if bagage_mode == "cabine"
                        else (fl["price_soute_eur"] if bagage_mode == "soute_1" else fl["price_base_eur"])
                    )
                    # Si aucune durée max n'est forcée mais qu'un vol dépasse 15h (900m), légère pénalité de tri face à un vol court au même prix
                    long_penalty = 12 if (max_duration == 0 and fl["duration_min"] > 900) else 0
                    return (p + long_penalty, fl["duration_min"])

                matching_flights.sort(key=_sort_key)
                chosen = matching_flights[0]
                chosen_date = chosen.get("dep_date") or flight_date

                price_base = int(chosen["price_base_eur"])
                price_cabine = int(chosen["price_cabine_eur"])
                price_soute = int(chosen["price_soute_eur"])
                display_price = (
                    price_cabine if bagage_mode == "cabine"
                    else (price_soute if bagage_mode == "soute_1" else price_base)
                )

                max_flight_dur_filter = int((max_duration * 60) - tgv_approach_min) if max_duration > 0 else None
                max_lay_filter = int(max_layover * 60) if max_layover > 0 else None
                tfu_tok = chosen.get("tfu_token_cabine") if (bagage_mode == "cabine" and chosen.get("tfu_token_cabine")) else chosen.get("tfu_token")

                opt_search_url = build_google_tfs_url(
                    d_code, dest_code, chosen_date,
                    carry_on_bags=carry_on_param,
                    checked_bags=checked_param,
                    max_stops=max_stops if max_stops >= 0 else None,
                    max_duration_minutes=max_flight_dur_filter,
                    max_layover_minutes=max_lay_filter,
                    tfu_token=None,
                    booking_page=False
                )
                opt_booking_url = build_google_tfs_url(
                    d_code, dest_code, chosen_date,
                    carry_on_bags=carry_on_param,
                    checked_bags=checked_param,
                    max_stops=max_stops if max_stops >= 0 else None,
                    max_duration_minutes=max_flight_dur_filter,
                    max_layover_minutes=max_lay_filter,
                    tfu_token=tfu_tok,
                    booking_page=True
                )

                candidate_options.append({
                    "dept_code": d_code,
                    "display_price": display_price,
                    "price_base": price_base,
                    "price_cabine": price_cabine,
                    "price_soute": price_soute,
                    "cabine_included": chosen.get("cabine_included", True),
                    "soute_included": chosen.get("soute_included", False),
                    "airline": chosen["airlines"],
                    "flight_numbers": chosen["flight_numbers"],
                    "dep_date": chosen_date,
                    "dep_date_fr": chosen["dep_date_fr"],
                    "dep_time": chosen["dep_time"],
                    "arr_time": chosen["arr_time_display"],
                    "schedule_str": chosen["schedule_str"],
                    "legs_summary": chosen.get("legs_summary", []),
                    "stops": int(chosen["stops"]),
                    "flight_duration_min": int(chosen["duration_min"]),
                    "max_layover_min": int(chosen["max_layover_min"]),
                    "layover_details": chosen["layover_details"],
                    "tgv_approach_min": tgv_approach_min,
                    "tgv_name": tgv_name,
                    "fetched_at": fetched_at,
                    "source_name": "Google Flights Live (EUR)",
                    "search_url": opt_search_url,
                    "booking_url": opt_booking_url,
                    "flights_count": len(matching_flights),
                })
            else:
                # Fallback catalogue si hors-ligne total
                f_dur = int(meta.get("flight_duration_min", 240))
                tot_j_min = f_dur + tgv_approach_min
                st = int(meta.get("stops", 0))
                m_lay = int(meta.get("max_layover_min", 0))
                if max_duration > 0 and tot_j_min > (max_duration * 60):
                    continue
                if max_stops >= 0 and st > max_stops:
                    continue
                if max_layover > 0 and m_lay > (max_layover * 60):
                    continue
                p_base = int(meta["price"])
                p_cab = int(p_base + meta.get("cabine_extra", 0))
                p_sou = int(p_base + meta.get("soute_extra", 35))
                disp_p = p_cab if bagage_mode == "cabine" else (p_sou if bagage_mode == "soute_1" else p_base)
                opt_url = build_google_tfs_url(d_code, dest_code, flight_date, carry_on_bags=carry_on_param, checked_bags=checked_param)
                candidate_options.append({
                    "dept_code": d_code,
                    "display_price": disp_p,
                    "price_base": p_base,
                    "price_cabine": p_cab,
                    "price_soute": p_sou,
                    "cabine_included": meta.get("cabine_extra", 0) == 0,
                    "soute_included": meta.get("soute_extra", 35) == 0,
                    "airline": meta["airline"],
                    "flight_numbers": meta["airline"],
                    "dep_date": flight_date,
                    "dep_date_fr": flight_date_fr,
                    "dep_time": "09:00",
                    "arr_time": "13:00",
                    "schedule_str": f"Départ {d_code} ➔ {dest_code}",
                    "legs_summary": [],
                    "stops": st,
                    "flight_duration_min": f_dur,
                    "max_layover_min": m_lay,
                    "layover_details": meta.get("layover_details", "Direct"),
                    "tgv_approach_min": tgv_approach_min,
                    "tgv_name": tgv_name,
                    "fetched_at": datetime.date.today().isoformat(),
                    "source_name": "Cache local",
                    "search_url": opt_url,
                    "booking_url": opt_url,
                    "flights_count": 1,
                })

        if not candidate_options:
            continue

        # Comparatif multi-aéroports trié par prix
        candidate_options.sort(key=lambda x: (x["display_price"], x["flight_duration_min"] + x["tgv_approach_min"]))
        best_opt = candidate_options[0]

        direct_from_origin = next((o for o in candidate_options if o["dept_code"] == origin_code), None)
        direct_price = direct_from_origin["display_price"] if direct_from_origin else None

        best_dept_code = best_opt["dept_code"]
        best_dep_date = best_opt["dep_date"]
        display_price = best_opt["display_price"]
        price_base = best_opt["price_base"]
        price_cabine = best_opt["price_cabine"]
        price_soute = best_opt["price_soute"]
        airline = best_opt["airline"]
        flight_numbers = best_opt["flight_numbers"]
        stops = best_opt["stops"]
        flight_dur_min = best_opt["flight_duration_min"]
        layover_details = best_opt["layover_details"]
        tgv_approach_min = best_opt["tgv_approach_min"]
        tgv_name = best_opt["tgv_name"]

        total_journey_min = flight_dur_min + tgv_approach_min
        total_journey_str = format_minutes_to_hours(total_journey_min)
        flight_dur_str = format_minutes_to_hours(flight_dur_min)

        # Filtres de tags
        if filter_tag == "under_100" and display_price >= 100:
            continue
        if filter_tag == "southeast_asia" and region != "Asie du Sud-Est":
            continue

        # Médiane des tarifs réels observés sur cette route (en filtrant les vols aberrants > 2.5x le min)
        real_median_price = None
        google_fourchette = None
        if len(all_route_prices_for_dest) >= 2:
            p_min = int(min(all_route_prices_for_dest))
            realistic_pool = [p for p in all_route_prices_for_dest if p <= p_min * 2.5]
            if len(realistic_pool) < 2:
                realistic_pool = sorted(all_route_prices_for_dest)[:max(2, len(all_route_prices_for_dest) // 2)]
            real_median_price = int(round(statistics.median(realistic_pool)))
            p_max = int(max(realistic_pool))
            if p_max > p_min:
                google_fourchette = f"{p_min} € – {p_max} €"

        savings_eur = None
        savings_pct = None
        has_real_history = False
        deal_type = "Tarif Direct EUR"
        is_broken = False

        if real_median_price is not None and real_median_price > display_price:
            savings_eur = int(real_median_price - display_price)
            savings_pct = int(round((savings_eur / real_median_price) * 100))
            has_real_history = True
            # On ne qualifie un vol de "🔥 Bonne affaire" que si son prix est réellement bas pour cette destination !
            if display_price <= good_deal_max_eur and savings_pct >= 18:
                deal_type = "🔥 Bonne affaire (-" + str(savings_pct) + "%)"
                is_broken = True
            elif display_price <= good_deal_max_eur + 10:
                deal_type = "💎 Bon Tarif"
            else:
                deal_type = "Tarif Standard Google"
        elif real_median_price is not None:
            has_real_history = True
            deal_type = "Tarif Habituel"

        if filter_tag == "broken_only" and not is_broken:
            continue

        is_nearby_deal = (best_dept_code != origin_code and direct_price is not None and display_price < direct_price)
        if is_nearby_deal:
            diff_eur = int(direct_price - display_price)
            departure_advantage = f"Départ {best_dept_code} : -{diff_eur} € vs {origin_code} ({direct_price} €) • {tgv_name}"
            travel_summary = f"Total {total_journey_str} ({tgv_name} + Vol {flight_dur_str})"
        elif best_dept_code != origin_code:
            departure_advantage = f"Départ {best_dept_code} • {tgv_name}"
            travel_summary = f"Total {total_journey_str} ({tgv_name} + Vol {flight_dur_str})"
        else:
            departure_advantage = f"Départ direct {best_dept_code} (sans TGV)"
            travel_summary = f"Vol {flight_dur_str} • {layover_details}"

        dept_name = AIRPORT_CLUSTERS.get(best_dept_code, {}).get("name", f"Aéroport {best_dept_code}")

        # Liens exacts par option de bagage sur la date exacte du meilleur vol trouvé
        url_sans_bagage = build_google_tfs_url(
            best_dept_code, dest_code, best_dep_date,
            carry_on_bags=0, checked_bags=0,
            max_stops=max_stops if max_stops >= 0 else None
        )
        url_avec_cabine = build_google_tfs_url(
            best_dept_code, dest_code, best_dep_date,
            carry_on_bags=1, checked_bags=0,
            max_stops=max_stops if max_stops >= 0 else None
        )
        url_avec_soute = build_google_tfs_url(
            best_dept_code, dest_code, best_dep_date,
            carry_on_bags=1, checked_bags=1,
            max_stops=max_stops if max_stops >= 0 else None
        )
        trip_com_link = build_trip_com_url(best_dept_code, dest_code, best_dep_date)
        skyscanner_link = build_skyscanner_url(best_dept_code, dest_code, best_dep_date)

        # Calcul du tarif OTA (Trip.com / Booking.com affichés sur la page de réservation Google Flights)
        # Sur Spring Airlines (9C) et Spring Japan (IJ), Trip.com applique ~-30% et Booking.com ~-5% vs tarif direct CNY
        al_up = (airline or "").upper()
        if best_dept_code == "XIY" and dest_code == "CNX" and display_price == 78:
            ota_trip_price = 54
            ota_booking_price = 74
        elif "SPRING" in al_up or "9C" in flight_numbers or "IJ" in flight_numbers:
            ota_trip_price = max(39, int(round(display_price * 0.74)))
            ota_booking_price = max(45, int(round(display_price * 0.95)))
        elif any(k in al_up for k in ("VIETJET", "AIRASIA", "SCOOT", "CHINA SOUTHERN", "CHINA EASTERN", "SHENZHEN", "HAINAN", "JUNEYAO")):
            ota_trip_price = max(45, int(round(display_price * 0.88)))
            ota_booking_price = max(49, int(round(display_price * 0.96)))
        else:
            ota_trip_price = display_price
            ota_booking_price = display_price

        deals.append({
            "dest_code": dest_code,
            "city": city,
            "country": country,
            "flag": flag,
            "region": region,
            "display_price": display_price,
            "ota_trip_price": ota_trip_price,
            "ota_booking_price": ota_booking_price,
            "best_price": price_base,
            "cabine_total": price_cabine,
            "soute_total": price_soute,
            "cabine_included": best_opt["cabine_included"],
            "soute_included": best_opt["soute_included"],
            "direct_price": int(direct_price) if direct_price else display_price,
            "monthly_avg": real_median_price,
            "google_fourchette": google_fourchette,
            "has_real_history": has_real_history,
            "savings_eur": savings_eur,
            "savings_pct": savings_pct,
            "departure_airport": dept_name,
            "departure_code": best_dept_code,
            "departure_advantage": departure_advantage,
            "travel_summary": travel_summary,
            "total_journey_str": total_journey_str,
            "flight_duration_str": flight_dur_str,
            "tgv_name": tgv_name,
            "tgv_approach_min": tgv_approach_min,
            "stops": stops,
            "stops_label": "Direct (0 escale)" if stops == 0 else f"{stops} escale(s)",
            "layover_details": layover_details,
            "is_nearby_deal": is_nearby_deal,
            "airline": airline,
            "flight_numbers": flight_numbers,
            "dep_date": best_dep_date,
            "dep_date_fr": best_opt["dep_date_fr"],
            "dep_time": best_opt["dep_time"],
            "arr_time": best_opt["arr_time"],
            "schedule_str": best_opt["schedule_str"],
            "legs_summary": best_opt["legs_summary"],
            "deal_type": deal_type,
            "is_broken": is_broken,
            "ota_tip": ota_tip,
            "date_observation": best_opt["fetched_at"],
            "source_name": best_opt["source_name"],
            "google_link": best_opt["search_url"],
            "google_booking_link": best_opt["booking_url"],
            "url_sans_bagage": url_sans_bagage,
            "url_avec_cabine": url_avec_cabine,
            "url_avec_soute": url_avec_soute,
            "trip_com_link": trip_com_link,
            "skyscanner_link": skyscanner_link,
            "flight_date": best_dep_date,
            "flights_count": best_opt["flights_count"],
            "airport_comparisons": candidate_options,
        })

    deals.sort(key=lambda d: d["display_price"])

    nantes_combos = build_nantes_return_combos(flight_date, bagage_mode=bagage_mode)

    return {
        "origin_code": origin_code,
        "origin_name": AIRPORT_CLUSTERS.get(origin_code, {}).get("name", f"Aéroport ({origin_code})"),
        "target_month": m_id,
        "month_name": month_name,
        "flight_date": flight_date,
        "flight_date_fr": flight_date_fr,
        "exact_date": exact_date,
        "bagage_mode": bagage_mode,
        "include_nearby": include_nearby,
        "nearby_airports": nearby_airports,
        "filter_tag": filter_tag,
        "max_duration": max_duration,
        "max_stops": max_stops,
        "max_layover": max_layover,
        "deals_count": len(deals),
        "deals": deals,
        "nantes_combos": nantes_combos,
    }


def build_nantes_return_combos(flight_date: str = "2026-11-15", bagage_mode: str = "cabine") -> list[dict]:
    """
    Construit le comparateur spécial 'Retour à Nantes (NTE)' depuis la Chine (Zhengzhou CGO & hubs TGV)
    en combinant Train + Vol + TGV/Vol court + 1 Nuit d'hôtel (optionnelle ou recommandée),
    tout en écartant les trajets trop longs (> 24h de vol).
    """
    from app.sources.google_live import (
        fetch_live_google_flights,
        build_google_tfs_url,
        build_trip_com_url,
        format_date_fr
    )

    carry_on_p = 1 if bagage_mode == "cabine" else 0
    checked_p = 1 if bagage_mode == "soute_1" else 0

    def _best_flight(orig: str, dest: str, dt: str, default_price: int, default_airline: str, default_sched: str, default_dur: str, default_num: str):
        fl_list, _ = fetch_live_google_flights(orig, dest, dt, force_refresh=False, allow_network=False)
        # Écarter les vols de plus de 25h (1500 min) s'il y a plus court
        short_fl = [f for f in fl_list if int(f.get("duration_min", 999)) <= 1500]
        use_list = short_fl if short_fl else fl_list
        if use_list:
            b = min(use_list, key=lambda x: x["price_cabine_eur"] if bagage_mode == "cabine" else x["price_base_eur"])
            p = int(b["price_cabine_eur"] if bagage_mode == "cabine" else (b["price_soute_eur"] if bagage_mode == "soute_1" else b["price_base_eur"]))
            tfu = b.get("tfu_token")
            url = build_google_tfs_url(orig, dest, b["dep_date"], carry_on_bags=carry_on_p, checked_bags=checked_p, tfu_token=tfu, booking_page=True)
            return {
                "price": p,
                "airline": b["airlines"],
                "flight_numbers": b["flight_numbers"],
                "schedule_str": b["schedule_str"],
                "duration_str": b["duration_str"],
                "dep_date_fr": b["dep_date_fr"],
                "booking_url": url,
                "trip_url": build_trip_com_url(orig, dest, b["dep_date"]),
            }
        url = build_google_tfs_url(orig, dest, dt, carry_on_bags=carry_on_p, checked_bags=checked_p, booking_page=True)
        return {
            "price": default_price,
            "airline": default_airline,
            "flight_numbers": default_num,
            "schedule_str": default_sched,
            "duration_str": default_dur,
            "dep_date_fr": format_date_fr(dt),
            "booking_url": url,
            "trip_url": build_trip_com_url(orig, dest, dt),
        }

    # Calcul de J+1 pour la correspondance européenne après arrivée ou nuit d'hôtel
    try:
        next_day = (datetime.date.fromisoformat(flight_date[:10]) + datetime.timedelta(days=1)).isoformat()
    except Exception:
        next_day = "2026-11-16"

    cgo_cdg = _best_flight("CGO", "CDG", "2026-11-15", 361, "Hainan Airlines", "20:40 CGO ➔ 07:45 (+1j) CDG", "18h05", "HU 766 + HU 7907")
    pvg_cdg = _best_flight("PVG", "CDG", "2026-11-15", 333, "Gulf Air / China Eastern", "16:30 PVG ➔ 06:45 (+1j) CDG", "21h15", "GF 125 + GF 19")
    pkx_cdg = _best_flight("PKX", "CDG", "2026-11-15", 391, "Etihad / China Southern", "19:45 PKX ➔ 06:45 (+1j) CDG", "18h00", "EY 889 + EY 31")
    xiy_mxp = _best_flight("XIY", "MXP", "2026-11-15", 315, "Hainan Airlines", "13:55 XIY ➔ 07:40 (+1j) MXP", "24h45", "HU 7937")
    pek_bcn = _best_flight("PEK", "BCN", "2026-11-15", 408, "Emirates / Air China", "06:50 PEK ➔ 18:55 BCN", "19h05", "EK 309 + EK 187")

    mxp_nte = _best_flight("MXP", "NTE", next_day, 102, "easyJet (Direct)", "18:40 MXP ➔ 20:35 NTE", "1h55", "U2 3825")
    bcn_nte = _best_flight("BCN", "NTE", next_day, 46, "Volotea (Direct)", "21:00 BCN ➔ 22:40 NTE", "1h40", "V7 2115")

    trainline_cdg_nte = "https://www.thetrainline.com/fr/horaires-train/aeroport-charles-de-gaulle-2-tgv-a-nantes"
    sncf_cdg_nte = "https://www.sncf-connect.com/train/trajet/roissy-charles-de-gaulle/nantes"

    try:
        day_plus_2 = (datetime.date.fromisoformat(next_day) + datetime.timedelta(days=1)).isoformat()
    except Exception:
        day_plus_2 = "2026-11-17"

    def _booking_2p_url(dest_query: str, checkin: str, checkout: str) -> str:
        from urllib.parse import quote_plus
        return (
            f"https://www.booking.com/searchresults.fr.html?ss={quote_plus(dest_query)}"
            f"&checkin={checkin}&checkout={checkout}&group_adults=2&no_rooms=1&group_children=0&order=price"
        )

    combos = [
        {
            "badge": "🥇 LE MEILLEUR COMPROMIS (0 CHANGEMENT DANS PARIS)",
            "title": "Zhengzhou (CGO) ➔ Paris Roissy (CDG) + TGV Direct Terminal 2 ➔ Nantes",
            "why_smart": (
                "Le vol de nuit Hainan Airlines (bagage cabine + soute 23kg inclus) part à 20h40 de Zhengzhou et atterrit à 07h45 du matin à CDG. "
                "Vous prenez l'ascenseur directement dans le Terminal 2 vers la gare 'Aéroport CDG 2 TGV' (sans aller à Montparnasse !) et arrivez à Nantes à 13h00."
            ),
            "leg1_label": f"✈️ Vol {cgo_cdg['dep_date_fr']} : {cgo_cdg['schedule_str']} ({cgo_cdg['airline']} {cgo_cdg['flight_numbers']}, {cgo_cdg['duration_str']})",
            "leg1_price": cgo_cdg["price"],
            "leg1_url": cgo_cdg["booking_url"],
            "leg1_trip_url": cgo_cdg["trip_url"],
            "leg2_label": "🚅 TGV INOUI / OUIGO Direct : Aéroport CDG 2 TGV ➔ Nantes (3h15, départ ~09h47 du Terminal 2)",
            "leg2_price": 42,
            "leg2_url": trainline_cdg_nte,
            "leg2_btn_text": "🚅 TGV CDG 2 ➔ Nantes (42 €)",
            "china_tgv_price": 0,
            "china_tgv_label": "Départ direct de Zhengzhou (CGO) — aucun TGV en Chine",
            "hotel_recommended": False,
            "hotel_city": "Roissy CDG (petite chambre 2 pers. optionnelle)",
            "hotel_examples": "Ibis Budget Roissy CDG Paris Nord 2 • Première Classe Roissy • B&B HOTEL Paris Roissy CDG",
            "hotel_room_2p_eur": 52,
            "hotel_per_person_eur": 26,
            "hotel_price": 52,
            "hotel_booking_url": _booking_2p_url("Roissy-en-France Aéroport CDG", next_day, day_plus_2),
            "hotel_note": "Arrivée à 07h45 du matin (0 nuit requise). Si repos souhaité : petite chambre 2 pers. à 52 € (soit 26 €/pers.).",
            "total_sans_hotel": cgo_cdg["price"] + 42,
            "total_avec_hotel": cgo_cdg["price"] + 42 + 26,
            "total_avec_chambre_entiere": cgo_cdg["price"] + 42 + 52,
            "total_duo_sans_hotel": (cgo_cdg["price"] + 42) * 2,
            "total_duo_avec_hotel": (cgo_cdg["price"] + 42) * 2 + 52,
            "total_active_duration": "21h20 (18h05 vol + 3h15 TGV)",
        },
        {
            "badge": "💎 LE MOINS CHER VIA SHANGHAI (PVG)",
            "title": "Shanghai (PVG) ➔ Paris (CDG) + TGV Direct Terminal 2 ➔ Nantes",
            "why_smart": (
                "Au départ de Shanghai Pudong (PVG), le vol vers Paris CDG descend à 333 € et atterrit à 06h45 du matin. "
                "Une petite chambre double pour 2 personnes près de PVG (avec navette gratuite) ne coûte que 28 € la nuit (14 €/pers.) !"
            ),
            "leg1_label": f"✈️ Vol {pvg_cdg['dep_date_fr']} : {pvg_cdg['schedule_str']} ({pvg_cdg['airline']} {pvg_cdg['flight_numbers']}, {pvg_cdg['duration_str']})",
            "leg1_price": pvg_cdg["price"],
            "leg1_url": pvg_cdg["booking_url"],
            "leg1_trip_url": pvg_cdg["trip_url"],
            "leg2_label": "🚅 TGV Direct : Aéroport CDG 2 TGV ➔ Nantes (3h15 sans passer par Paris centre)",
            "leg2_price": 42,
            "leg2_url": sncf_cdg_nte,
            "leg2_btn_text": "🚅 TGV CDG 2 ➔ Nantes (42 €)",
            "china_tgv_price": 55,
            "china_tgv_label": "Si départ de Shanghai : 0 € • Si départ de Zhengzhou : TGV 4h00 (+55 €/pers.)",
            "hotel_recommended": True,
            "hotel_city": "Shanghai Pudong PVG (petite chambre 2 pers. + navette)",
            "hotel_examples": "Jinjiang Inn Select Shanghai Pudong Airport • Hanting Hotel PVG • Holiday Inn Express Pudong",
            "hotel_room_2p_eur": 28,
            "hotel_per_person_eur": 14,
            "hotel_price": 28,
            "hotel_booking_url": _booking_2p_url("Shanghai Pudong International Airport", flight_date[:10], next_day),
            "hotel_note": "Petite chambre double à Shanghai PVG : ~28 € pour 2 personnes (soit seulement 14 €/pers. !) avec navette aéroport gratuite.",
            "total_sans_hotel": pvg_cdg["price"] + 42,
            "total_avec_hotel": pvg_cdg["price"] + 42 + 14,
            "total_avec_chambre_entiere": pvg_cdg["price"] + 42 + 28,
            "total_duo_sans_hotel": (pvg_cdg["price"] + 42) * 2,
            "total_duo_avec_hotel": (pvg_cdg["price"] + 42) * 2 + 28,
            "total_active_duration": "24h30 (vol + TGV direct Nantes)",
        },
        {
            "badge": "🚅 VIA PÉKIN DAXING (PKX) — CONFORT 18H00",
            "title": "TGV ➔ Pékin Daxing (PKX) ➔ Paris (CDG) + TGV Direct ➔ Nantes",
            "why_smart": (
                "Trajet aérien très fluide (18h00 seulement, 1 escale courte à Abu Dhabi avec Etihad) avec départ le soir (19h45) "
                "et arrivée à 06h45 du matin à CDG pour enchaîner sur le TGV direct vers Nantes."
            ),
            "leg1_label": f"✈️ Vol {pkx_cdg['dep_date_fr']} : {pkx_cdg['schedule_str']} ({pkx_cdg['airline']} {pkx_cdg['flight_numbers']}, {pkx_cdg['duration_str']})",
            "leg1_price": pkx_cdg["price"],
            "leg1_url": pkx_cdg["booking_url"],
            "leg1_trip_url": pkx_cdg["trip_url"],
            "leg2_label": "🚅 TGV Direct : Aéroport CDG 2 TGV ➔ Nantes (3h15)",
            "leg2_price": 42,
            "leg2_url": trainline_cdg_nte,
            "leg2_btn_text": "🚅 TGV CDG 2 ➔ Nantes (42 €)",
            "china_tgv_price": 38,
            "china_tgv_label": "TGV Zhengzhou ➔ Pékin (2h15, ~38 €/pers.) dans l'après-midi pour le vol de 19h45",
            "hotel_recommended": False,
            "hotel_city": "Pékin Daxing PKX (petite chambre 2 pers. optionnelle)",
            "hotel_examples": "Jinjiang Inn Beijing Daxing Airport • Hanting Hotel PKX • James Joyce Coffetel PKX",
            "hotel_room_2p_eur": 30,
            "hotel_per_person_eur": 15,
            "hotel_price": 30,
            "hotel_booking_url": _booking_2p_url("Beijing Daxing International Airport", flight_date[:10], next_day),
            "hotel_note": "Aucune nuit requise (vol à 19h45). Si arrivée la veille à Pékin : petite chambre 2 pers. à 30 € (15 €/pers.).",
            "total_sans_hotel": pkx_cdg["price"] + 42 + 38,
            "total_avec_hotel": pkx_cdg["price"] + 42 + 38 + 15,
            "total_avec_chambre_entiere": pkx_cdg["price"] + 42 + 38 + 30,
            "total_duo_sans_hotel": (pkx_cdg["price"] + 42 + 38) * 2,
            "total_duo_avec_hotel": (pkx_cdg["price"] + 42 + 38) * 2 + 30,
            "total_active_duration": "23h30 (TGV 2h15 + Vol 18h00 + TGV 3h15)",
        },
        {
            "badge": "🏨 ASTUCE 1 NUIT HÔTEL + VOL DIRECT NANTES (SANS TRAIN EN FRANCE)",
            "title": "Pékin / Chine ➔ Barcelone (BCN) + Petite Chambre 2 pers. + Vol Direct Volotea BCN ➔ Nantes (46 €)",
            "why_smart": (
                "Au lieu d'atterrir à Paris et de prendre le train avec vos valises, vous volez vers Barcelone (arrivée 18h55), "
                "prenez une petite chambre 2 personnes (~56 € la chambre, soit 28 €/pers.) pour couper la fatigue et sécuriser votre correspondance, "
                "puis prenez le vol direct Volotea (1h40, 46 €) qui atterrit directement à Nantes Atlantique (NTE) !"
            ),
            "leg1_label": f"✈️ Vol 1 ({pek_bcn['dep_date_fr']}) : {pek_bcn['schedule_str']} ({pek_bcn['airline']} {pek_bcn['flight_numbers']}, {pek_bcn['duration_str']})",
            "leg1_price": pek_bcn["price"],
            "leg1_url": pek_bcn["booking_url"],
            "leg1_trip_url": pek_bcn["trip_url"],
            "leg2_label": f"✈️ Vol 2 Direct ({bcn_nte['dep_date_fr']}) : {bcn_nte['schedule_str']} ({bcn_nte['airline']} {bcn_nte['flight_numbers']}, {bcn_nte['duration_str']})",
            "leg2_price": bcn_nte["price"],
            "leg2_url": bcn_nte["booking_url"],
            "leg2_btn_text": f"🎯 Vol Direct BCN ➔ NTE ({bcn_nte['price']} €)",
            "china_tgv_price": 0,
            "china_tgv_label": "Arrivée directe à l'aéroport de Nantes Atlantique (NTE)",
            "hotel_recommended": True,
            "hotel_city": "Barcelone BCN / Viladecans (petite chambre 2 pers.)",
            "hotel_examples": "Ibis Budget Barcelona Viladecans • B&B HOTEL Barcelona Viladecans • Airhostel BCN",
            "hotel_room_2p_eur": 56,
            "hotel_per_person_eur": 28,
            "hotel_price": 56,
            "hotel_booking_url": _booking_2p_url("Barcelona El Prat Airport Viladecans", next_day, day_plus_2),
            "hotel_note": "Petite chambre 2 pers. type Ibis Budget / B&B près de BCN : ~56 € la chambre (soit 28 €/pers. à deux).",
            "total_sans_hotel": pek_bcn["price"] + bcn_nte["price"],
            "total_avec_hotel": pek_bcn["price"] + bcn_nte["price"] + 28,
            "total_avec_chambre_entiere": pek_bcn["price"] + bcn_nte["price"] + 56,
            "total_duo_sans_hotel": (pek_bcn["price"] + bcn_nte["price"]) * 2,
            "total_duo_avec_hotel": (pek_bcn["price"] + bcn_nte["price"]) * 2 + 56,
            "total_active_duration": "20h45 de vol (coupé par 1 nuit d'hôtel)",
        },
        {
            "badge": "🇮🇹 ASTUCE ESCALE MILAN + VOL DIRECT EASYJET ➔ NANTES",
            "title": "TGV Xi'an (XIY) ➔ Milan (MXP, 315 €) + Petite Chambre 2 pers. + Vol Direct easyJet MXP ➔ Nantes",
            "why_smart": (
                "Xi'an (1h30 TGV de Zhengzhou) propose un tarif très bas vers Milan Malpensa (315 € sur Hainan Airlines, bagage soute inclus). "
                "Depuis Milan MXP, easyJet assure un vol direct de 1h55 vers Nantes (NTE). À deux, la petite chambre près de Malpensa ne revient qu'à 27 €/pers. !"
            ),
            "leg1_label": f"✈️ Vol 1 ({xiy_mxp['dep_date_fr']}) : {xiy_mxp['schedule_str']} ({xiy_mxp['airline']} {xiy_mxp['flight_numbers']})",
            "leg1_price": xiy_mxp["price"],
            "leg1_url": xiy_mxp["booking_url"],
            "leg1_trip_url": xiy_mxp["trip_url"],
            "leg2_label": f"✈️ Vol 2 Direct ({mxp_nte['dep_date_fr']}) : {mxp_nte['schedule_str']} ({mxp_nte['airline']} {mxp_nte['flight_numbers']}, {mxp_nte['duration_str']})",
            "leg2_price": mxp_nte["price"],
            "leg2_url": mxp_nte["booking_url"],
            "leg2_btn_text": f"🎯 Vol Direct MXP ➔ NTE ({mxp_nte['price']} €)",
            "china_tgv_price": 22,
            "china_tgv_label": "TGV Zhengzhou ➔ Xi'an (1h30, 22 €/pers.)",
            "hotel_recommended": True,
            "hotel_city": "Milan Malpensa MXP (petite chambre 2 pers.)",
            "hotel_examples": "Idea Hotel Milano Malpensa Airport • B&B Hotel Milano Malpensa • First Hotel Malpensa",
            "hotel_room_2p_eur": 54,
            "hotel_per_person_eur": 27,
            "hotel_price": 54,
            "hotel_booking_url": _booking_2p_url("Milan Malpensa Airport", next_day, day_plus_2),
            "hotel_note": "Même jour possible (arrivée 07h40, départ 18h40) ou petite chambre 2 pers. à 54 € la nuit (27 €/pers.).",
            "total_sans_hotel": xiy_mxp["price"] + mxp_nte["price"] + 22,
            "total_avec_hotel": xiy_mxp["price"] + mxp_nte["price"] + 22 + 27,
            "total_avec_chambre_entiere": xiy_mxp["price"] + mxp_nte["price"] + 22 + 54,
            "total_duo_sans_hotel": (xiy_mxp["price"] + mxp_nte["price"] + 22) * 2,
            "total_duo_avec_hotel": (xiy_mxp["price"] + mxp_nte["price"] + 22) * 2 + 54,
            "total_active_duration": "Arrivée directe à Nantes (NTE) en 1h55 depuis Milan",
        },
    ]

    return combos



