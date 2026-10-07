from abc import ABC, abstractmethod
from typing import Optional
from app.models import Route, PriceObservation, BaggagePrice

class FlightSourceBase(ABC):
    """
    Interface commune pour toutes les sources de données de vols.
    Permet d'ajouter ou remplacer une API sans modifier le reste de l'application.
    """

    @abstractmethod
    async def search_prices(self, route: Route, flexible_days: int = 0) -> list[PriceObservation]:
        """
        Recherche les prix disponibles pour le trajet donné.
        Renvoie une liste d'observations normalisées.
        """
        pass

    @abstractmethod
    async def get_baggage(self, route: Route, airline: str) -> list[BaggagePrice]:
        """
        Récupère les tarifs de bagages connus ou frais pour une compagnie / trajet.
        """
        pass
