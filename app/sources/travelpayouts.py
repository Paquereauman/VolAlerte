import httpx
import datetime
from typing import Optional
from app.sources.base import FlightSourceBase
from app.models import Route, PriceObservation, BaggagePrice
from app.analytics import calculate_anticipation_days
from app.config import settings

CITY_AIRPORTS = {
    "PARIS": ["PAR", "CDG", "ORY", "BVA"],
    "PAR": ["CDG", "ORY", "BVA"],
    "LON": ["LHR", "LGW", "STN", "LTN"],
    "LONDRES": ["LHR", "LGW", "STN", "LTN"],
    "MIL": ["MXP", "LIN", "BGY"],
    "MILAN": ["MXP", "LIN", "BGY"],
    "ROM": ["FCO", "CIA"],
    "ROME": ["FCO", "CIA"],
}

class TravelpayoutsSource(FlightSourceBase):
    """
    Source de données Travelpayouts Data API.
    Fournit le cache des prix trouvés sur Aviasales, avec date du vol et date du relevé (found_at).
    """

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.TRAVELPAYOUTS_TOKEN
        self.base_url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
        self.calendar_url = "https://api.travelpayouts.com/v1/prices/calendar"

    def _resolve_origins(self, code_or_city: str) -> list[str]:
        import re
        codes = re.findall(r'\b([A-Z]{3})\b', code_or_city.upper())
        if codes:
            return codes
        cleaned = code_or_city.strip().upper()
        if "," in cleaned:
            return [x.strip() for x in cleaned.split(",") if x.strip()]
        return CITY_AIRPORTS.get(cleaned, [cleaned])

    async def search_prices(self, route: Route, flexible_days: int = 3) -> list[PriceObservation]:
        if not self.token:
            return []

        observations: list[PriceObservation] = []
        origins = self._resolve_origins(route.origine)
        destinations = self._resolve_origins(route.destination)

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Tester les aéroports principaux
            for origin in origins[:2]:
                for destination in destinations[:2]:
                    params = {
                        "origin": origin,
                        "destination": destination,
                        "currency": "EUR",
                        "token": self.token,
                        "limit": 30
                    }

                    if ":" in route.dates_ou_mois:
                        parts = route.dates_ou_mois.split(":")
                        params["departure_at"] = parts[0]
                        if len(parts) > 1 and parts[1]:
                            params["return_at"] = parts[1]
                    elif len(route.dates_ou_mois) == 7:  # YYYY-MM
                        params["departure_at"] = route.dates_ou_mois
                    else:
                        params["departure_at"] = route.dates_ou_mois

                    try:
                        resp = await client.get(self.base_url, params=params)
                        if resp.status_code == 200:
                            data = resp.json()
                            items = data.get("data", [])
                            today_str = datetime.date.today().isoformat()

                            for item in items:
                                price = float(item.get("price", 0))
                                if price <= 0:
                                    continue

                                dep_at = item.get("departure_at", "")[:10]
                                found_at = item.get("found_at", today_str)[:10]
                                if not dep_at:
                                    continue

                                anticipation = calculate_anticipation_days(dep_at, found_at)
                                airline = item.get("airline", "")
                                transfers = int(item.get("transfers", 0))
                                link = item.get("link", "")
                                if link and not link.startswith("http"):
                                    link = f"https://www.aviasales.com{link}"

                                observations.append(PriceObservation(
                                    id=None,
                                    route_id=route.id or 0,
                                    source="travelpayouts",
                                    date_vol=dep_at,
                                    date_releve=found_at,
                                    jours_anticipation=anticipation,
                                    prix_billet_eur=price,
                                    compagnie=airline,
                                    escales=transfers,
                                    niveau_google="",
                                    lien=link
                                ))
                    except Exception:
                        continue

        return observations

    async def get_baggage(self, route: Route, airline: str) -> list[BaggagePrice]:
        # Travelpayouts Data API renvoie le cache de vols ; les tarifs bagages spécifiques
        # sont complétés par la table locale ou SerpApi.
        return []
