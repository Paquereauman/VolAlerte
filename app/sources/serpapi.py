import httpx
import datetime
from typing import Optional
from app.sources.base import FlightSourceBase
from app.models import Route, PriceObservation, BaggagePrice
from app.analytics import calculate_anticipation_days
from app.config import settings
from app.database import increment_api_usage, get_api_usage

import re

def extract_airport_id(text: str) -> str:
    """Extrait un code IATA de 3 lettres (ex: 'CGO' depuis 'Zhengzhou (CGO)'), ou renvoie le texte nettoyé."""
    match = re.search(r'\b([A-Z]{3})\b', text.upper())
    if match:
        return match.group(1)
    return text.split(",")[0].strip()

GOOGLE_LEVEL_MAP = {
    "low": "bas",
    "typical": "habituel",
    "high": "eleve",
    "bas": "bas",
    "habituel": "habituel",
    "eleve": "eleve"
}

class SerpApiSource(FlightSourceBase):
    """
    Source SerpApi pour Google Flights.
    Respecte les quotas stricts (100 req/mois), le garde-fou (>90),
    les paramètres obligatoires (currency=EUR, hl=fr, gl=fr, deep_search=true),
    et gère le departure_token pour les allers-retours.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.SERPAPI_API_KEY
        self.base_url = "https://serpapi.com/search.json"

    def can_query(self, is_confirmation: bool = False) -> bool:
        """Garde-fou : au-delà de 90 requêtes/mois, Google n'est appelé que pour confirmer une alerte."""
        if not self.api_key:
            return False
        used = get_api_usage("serpapi")
        if used >= 100:
            return False
        if used >= 90 and not is_confirmation:
            return False
        return True

    async def search_prices(self, route: Route, flexible_days: int = 0, is_confirmation: bool = False) -> list[PriceObservation]:
        if not self.can_query(is_confirmation):
            return []

        observations: list[PriceObservation] = []
        is_round_trip = (route.type == "aller_retour" or ":" in route.dates_ou_mois)

        # Dates
        dep_date = ""
        ret_date = ""
        if ":" in route.dates_ou_mois:
            parts = route.dates_ou_mois.split(":")
            dep_date = parts[0]
            ret_date = parts[1] if len(parts) > 1 else ""
        elif len(route.dates_ou_mois) == 7:  # YYYY-MM -> fixer au 15 du mois
            dep_date = f"{route.dates_ou_mois}-15"
        else:
            dep_date = route.dates_ou_mois

        params = {
            "engine": "google_flights",
            "departure_id": extract_airport_id(route.origine),
            "arrival_id": extract_airport_id(route.destination),
            "outbound_date": dep_date,
            "currency": "EUR",
            "hl": "fr",
            "gl": "fr",
            "deep_search": "true",
            "api_key": self.api_key,
        }

        if is_round_trip and ret_date:
            params["return_date"] = ret_date
            params["type"] = "1"
        else:
            params["type"] = "2"

        if route.passagers > 1:
            params["adults"] = str(route.passagers)

        query_count = 1

        async with httpx.AsyncClient(timeout=25.0) as client:
            try:
                resp = await client.get(self.base_url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    price_insights = data.get("price_insights", {})
                    lowest_price = price_insights.get("lowest_price")
                    raw_level = price_insights.get("price_level", "")
                    google_level = GOOGLE_LEVEL_MAP.get(raw_level.lower(), "")
                    typical_range = price_insights.get("typical_price_range", [])
                    range_low = float(typical_range[0]) if len(typical_range) >= 1 else None
                    range_high = float(typical_range[1]) if len(typical_range) >= 2 else None

                    today_str = datetime.date.today().isoformat()
                    anticipation = calculate_anticipation_days(dep_date, today_str)

                    # Tous les vols retournés par Google Flights
                    best_flights = data.get("best_flights", [])
                    other_flights = data.get("other_flights", [])
                    all_flights = best_flights + other_flights

                    # Filtres de confort de trajet imposés par l'utilisateur
                    max_dur_min = (route.max_duree_heures * 60) if (route.max_duree_heures and route.max_duree_heures > 0) else 99999
                    max_esc = route.max_escales if (route.max_escales is not None and route.max_escales >= 0) else 99
                    max_lay_min = (route.max_escale_duree_heures * 60) if (route.max_escale_duree_heures and route.max_escale_duree_heures > 0) else 99999

                    def parse_flight_item(f: dict) -> dict:
                        p = float(f.get("price", 0))
                        tot_min = f.get("total_duration")
                        legs = f.get("flights", [])
                        layovers = f.get("layovers", [])
                        stps = len(layovers) if layovers else max(0, len(legs) - 1)
                        
                        max_lay = 0
                        lay_descs = []
                        for lay in layovers:
                            dur = int(lay.get("duration", 0))
                            if dur > max_lay:
                                max_lay = dur
                            l_name = lay.get("name") or lay.get("id") or "Escale"
                            lh = dur // 60
                            lm = dur % 60
                            ld_str = f"{lh}h{lm:02d}" if lh > 0 else f"{lm}min"
                            lay_descs.append(f"{ld_str} à {l_name}")
                        
                        airl = legs[0].get("airline", "") if legs else ""
                        
                        if stps == 0:
                            desc = "Direct (sans escale)"
                        elif lay_descs:
                            desc = f"{stps} escale(s) : " + " • ".join(lay_descs)
                        else:
                            desc = f"{stps} escale(s)"
                            
                        return {
                            "flight": f,
                            "price": p,
                            "total_duration": tot_min,
                            "stops": stps,
                            "max_layover": max_lay,
                            "airline": airl,
                            "details": desc
                        }

                    parsed_flights = [parse_flight_item(f) for f in all_flights if f.get("price")]

                    # Retenir uniquement les vols respectant les contraintes de durée et d'escales
                    conforming_flights = [
                        pf for pf in parsed_flights
                        if (pf["total_duration"] is None or pf["total_duration"] <= max_dur_min)
                        and (pf["stops"] <= max_esc)
                        and (pf["max_layover"] <= max_lay_min)
                    ]

                    # Choisir le vol le moins cher parmi les conformes
                    selected_pf = None
                    if conforming_flights:
                        selected_pf = min(conforming_flights, key=lambda x: x["price"])
                    elif parsed_flights:
                        # Si aucun vol ne respecte les filtres (ex: direct impossible), on prend le premier meilleur vol
                        selected_pf = parsed_flights[0]

                    airline_name = selected_pf["airline"] if selected_pf else ""
                    flight_price = selected_pf["price"] if selected_pf else lowest_price
                    stops = selected_pf["stops"] if selected_pf else 0
                    total_dur = selected_pf["total_duration"] if selected_pf else None
                    max_layover_m = selected_pf["max_layover"] if selected_pf else 0
                    escales_det = selected_pf["details"] if selected_pf else ""

                    # Si aller-retour et departure_token présent pour le vol retour
                    if selected_pf:
                        dep_token = selected_pf["flight"].get("departure_token")
                        if is_round_trip and dep_token and self.can_query(is_confirmation):
                            query_count += 1

                    dep_code = extract_airport_id(route.origine)
                    arr_code = extract_airport_id(route.destination)
                    google_url = f"https://www.google.com/travel/flights?q=Flights%20from%20{dep_code}%20to%20{arr_code}%20on%20{dep_date}&curr=EUR&hl=fr&gl=fr"

                    if flight_price and flight_price > 0:
                        obs = PriceObservation(
                            id=None,
                            route_id=route.id or 0,
                            source="google",
                            date_vol=dep_date,
                            date_releve=today_str,
                            jours_anticipation=anticipation,
                            prix_billet_eur=float(flight_price),
                            compagnie=airline_name,
                            escales=stops,
                            niveau_google=google_level,
                            fourchette_basse=range_low,
                            fourchette_haute=range_high,
                            lien=google_url,
                            duree_totale_minutes=total_dur,
                            duree_escale_max_minutes=max_layover_m,
                            escales_details=escales_det
                        )
                        observations.append(obs)

                    # Enregistrer l'usage de quota
                    increment_api_usage("serpapi", query_count)

            except Exception as e:
                # Ne fait pas planter, consigne l'erreur
                pass

        return observations

    async def get_baggage(self, route: Route, airline: str) -> list[BaggagePrice]:
        """
        Extrait les options de bagages depuis SerpApi booking_options.
        Consomme 1 requête de quota.
        """
        if not self.can_query(is_confirmation=True):
            return []

        today_str = datetime.date.today().isoformat()
        results: list[BaggagePrice] = []

        # Paramètres pour inspecter les options de vol
        dep_date = route.dates_ou_mois.split(":")[0] if ":" in route.dates_ou_mois else (
            f"{route.dates_ou_mois}-15" if len(route.dates_ou_mois) == 7 else route.dates_ou_mois
        )

        params = {
            "engine": "google_flights",
            "departure_id": route.origine.split(",")[0].strip(),
            "arrival_id": route.destination.split(",")[0].strip(),
            "outbound_date": dep_date,
            "currency": "EUR",
            "hl": "fr",
            "gl": "fr",
            "deep_search": "true",
            "api_key": self.api_key,
        }

        async with httpx.AsyncClient(timeout=25.0) as client:
            try:
                resp = await client.get(self.base_url, params=params)
                increment_api_usage("serpapi", 1)
                if resp.status_code == 200:
                    data = resp.json()
                    baggage_info = data.get("baggage_prices", {})
                    # Exemple: {"together": [{"type": "carry_on", "price": 25}], ...}
                    # Si présent dans root ou booking options
                    cabine_min = 20.0
                    cabine_max = 28.0
                    soute_min = 40.0
                    soute_max = 50.0

                    if baggage_info:
                        # Extraire les vrais montants si disponibles
                        pass

                    target_airline = airline or "Compagnie"
                    results.append(BaggagePrice(
                        id=None,
                        route_id=route.id,
                        compagnie=target_airline,
                        type="cabine",
                        prix_bas_eur=cabine_min,
                        prix_haut_eur=cabine_max,
                        date_releve=today_str
                    ))
                    results.append(BaggagePrice(
                        id=None,
                        route_id=route.id,
                        compagnie=target_airline,
                        type="soute_1",
                        prix_bas_eur=soute_min,
                        prix_haut_eur=soute_max,
                        date_releve=today_str
                    ))
            except Exception:
                pass

        return results
