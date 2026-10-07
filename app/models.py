from dataclasses import dataclass
from typing import Optional

@dataclass
class Route:
    id: Optional[int]
    origine: str
    destination: str
    type: str  # 'aller_simple' ou 'aller_retour'
    dates_ou_mois: str  # ex: '2026-11' ou '2026-11-14' ou '2026-11-14:2026-11-21'
    passagers: int = 1
    bagage: str = "cabine"  # 'aucun', 'cabine', 'soute_1', 'soute_2'
    seuil_eur: float = 80.0
    actif: bool = True
    max_duree_heures: Optional[float] = 12.0  # Durée maximale acceptée en heures (0 = illimité)
    max_escales: Optional[int] = 1  # 0 = direct uniquement, 1 = 1 escale max, 2 = 2 max, 99 = illimité
    max_escale_duree_heures: Optional[float] = 4.0  # Durée max d'une escale en heures (0 = illimité)

@dataclass
class PriceObservation:
    id: Optional[int]
    route_id: int
    source: str  # 'travelpayouts', 'google', 'amadeus', 'kiwi'
    date_vol: str  # YYYY-MM-DD
    date_releve: str  # YYYY-MM-DD
    jours_anticipation: int
    prix_billet_eur: float
    compagnie: str = ""
    escales: int = 0
    niveau_google: str = ""  # 'bas', 'habituel', 'eleve'
    fourchette_basse: Optional[float] = None
    fourchette_haute: Optional[float] = None
    lien: str = ""
    duree_totale_minutes: Optional[int] = None  # Durée totale en minutes (vol + escales)
    duree_escale_max_minutes: Optional[int] = 0  # Escale la plus longue en minutes
    escales_details: str = ""  # Détails des escales (ex: 'Escale 1h45 à Canton CAN')
    horaires_vol: str = ""  # Ex: '08:00 CGO ➔ 14:00 BKK'
    numero_vol: str = ""  # Ex: 'CZ 3391 + CZ 5095'
    prix_cabine_eur: Optional[float] = None
    prix_soute_eur: Optional[float] = None

@dataclass
class BaggagePrice:
    id: Optional[int]
    route_id: Optional[int]
    compagnie: str
    type: str  # 'cabine', 'soute_1', 'soute_2'
    prix_bas_eur: float
    prix_haut_eur: float
    date_releve: str

@dataclass
class Alert:
    id: Optional[int]
    route_id: int
    date: str
    prix_billet: float
    prix_bagage: float
    prix_total: float
    message: str
    canaux: str
    lien: str = ""

@dataclass
class AnticipationBracket:
    label: str  # ex: "60-90 j"
    min_days: int
    max_days: int
    median_price: Optional[float]
    count: int
    confidence: str  # "données insuffisantes", "indicatif", "fiable"
    diff_with_best: Optional[float] = None  # Écart en € avec la tranche la moins chère
