# ✈️ VolAlerte — Suivi Intelligent des Prix de Vols (avec Bagages Réels)

VolAlerte est une application locale autonome sous Windows permettant de surveiller 1 à 2 trajets aériens, de calculer le prix total bagage compris, et de déterminer statistiquement le meilleur moment pour réserver grâce à l'analyse de l'historique des prix par tranches d'anticipation.

---

## 🎯 Principes directeurs

1. **Fiabilité avant tout** : chaque conseil affiche son niveau de confiance (*fiable* > 100 prix, *indicatif* 30-100 prix, *données insuffisantes* < 30 prix). Pas assez de données = pas de conseil.
2. **Prix réel** : le prix d'alerte inclut le bagage sélectionné par l'utilisateur (valeur haute de la fourchette constatée).
3. **Prudence** : une alerte mentionne toujours « *prix probablement bas, vérifie vite sur le site de la compagnie* », jamais « *réserve maintenant* ».
4. **Sources interchangeables** : chaque API implémente l'interface commune `FlightSourceBase` (`search_prices`, `get_baggage`).
5. **Autonomie quotidienne** : une tâche planifiée Windows relève les prix une fois par jour à 09:00, même si l'interface web est fermée (avec rattrapage automatique si le PC était éteint).
6. **100% services gratuits** : utilise les quotas gratuits Travelpayouts (gratuit sans limite pratique) et SerpApi Google Flights (100 req/mois, avec garde-fou à 90 req/mois).

---

## 📦 Stack Technique

* **Langage & Backend** : Python 3.12, FastAPI, Uvicorn, SQLite (`data/vols.db`).
* **Interface & Graphiques** : HTML5, Jinja2, Chart.js 4.4 (fichier local `chart.umd.min.js`, aucun CDN externe), CSS moderne (thème clair et sombre automatique).
* **Application autonome & PWA** :
  * Double-clic sur le raccourci Bureau : lance silencieusement le serveur local via `pythonw.exe` (sans aucune fenêtre noire console) et ouvre l'interface dans sa propre fenêtre d'application (`msedge --app=http://localhost:8765`).
  * Installable également en PWA (manifest + Service Worker + icônes).
* **Notifications multi-canaux** :
  * Windows native (toasts système).
  * Telegram Bot API (facultatif).
  * ntfy.sh (gratuit sans inscription, notifications push sur smartphone et bureau).

---

## 🚀 Installation en une commande

1. Ouvrez le dossier `VolAlerte` dans l'Explorateur de fichiers Windows.
2. Double-cliquez sur `install.bat`.

Ce script automatique :
* Crée l'environnement virtuel Python (`venv`).
* Installe les dépendances nécessaires (`fastapi`, `uvicorn`, `httpx`, `winotify`, `pytest`, etc.).
* Initialise la base de données SQLite `data/vols.db`.
* Crée un raccourci **VolAlerte** sur votre **Bureau Windows**.
* Enregistre la tâche planifiée Windows `VolAlerte_DailyCheck` (quotidienne à 09:00 avec rattrapage automatique dès que le PC démarre).

---

## 💡 Mode Démo (Sans aucune clé API)

L'application est configurée par défaut en **Mode Démo** (`DEMO_MODE=1` dans `.env`).
Vous pouvez explorer immédiatement le tableau de bord avec plus de 400 relevés réalistes sur les trajets Paris ➔ Rome et Paris ➔ Lisbonne, consulter les graphiques par tranches d'anticipation et tester les alertes.

Pour passer en mode réel avec les vraies API, rendez-vous dans l'écran **Réglages** et basculez l'interrupteur sur **Mode Réel**.

---

## 🔑 Où obtenir chaque clé API (100% Gratuites)

### 1. Travelpayouts Data API (Gratuit et illimité)
* **Utilité** : Relevé des prix, dates flexibles, liaisons multi-aéroports, et historique des dates de découverte (`found_at`).
* **Lien** : Rendez-vous sur [https://www.travelpayouts.com](https://www.travelpayouts.com)
* **Inscription** : Créez un compte partenaire gratuit.
* **Récupération du token** : Dans le menu *Outils* ➔ *API*, copiez votre token d'accès (`X-Access-Token`).

### 2. SerpApi Google Flights (100 requêtes/mois gratuites)
* **Utilité** : Prix en direct, niveau Google (« bas », « habituel », « élevé »), fourchette de prix, et options de bagages.
* **Lien** : Rendez-vous sur [https://serpapi.com](https://serpapi.com)
* **Inscription** : Créez un compte gratuit.
* **Récupération de la clé** : Copiez votre clé d'API personnelle depuis votre tableau de bord.
* **Garde-fou automatique** : Au-delà de 90 requêtes consommées dans le mois, l'application bloque les appels superflus et ne sollicite Google Flights que pour valider formellement une alerte.

### 3. Telegram Bot (Facultatif)
* Si vous souhaitez recevoir les alertes sur votre messagerie Telegram :
  1. Parlez au bot `@BotFather` sur Telegram et tapez `/newbot` pour créer votre bot et obtenir son token.
  2. Lancez une conversation avec votre bot et récupérez votre `chat_id` (via `@userinfobot`).
  3. Renseignez ces valeurs dans l'écran **Réglages**.

### 4. ntfy.sh (Recommandé, simple et gratuit sans inscription)
* Installez l'application **ntfy** sur votre smartphone (Android / iOS).
* Choisissez un nom de sujet unique dans les Réglages (ex: `volalerte_bpaquereau_89`).
* Dans l'application mobile ntfy, abonnez-vous à ce même sujet : vous recevrez instantanément les alertes avec le lien direct vers le vol !

---

## 🖥️ Les 4 Écrans de l'Interface

1. **Tableau de bord** (`/`) :
   * Une carte synthétique par trajet surveillé : dernier prix total bagage compris, décomposition billet + bagage, niveau Google, tendance 7 jours, meilleure fenêtre de réservation et niveau de confiance.
   * Jauge du quota mensuel SerpApi (requêtes utilisées / 100).
   * Bouton « *⚡ Vérifier maintenant* » pour forcer un relevé immédiat.
2. **Détail d'un trajet** (`/route/{id}`) :
   * Graphique interactif d'évolution chronologique des prix (courbe billet seul et prix total).
   * Graphique du prix médian par tranche d'anticipation avec surlignage de la fenêtre optimale.
   * Tableau complet des tranches d'anticipation avec écarts en euros.
   * Grille tarifaire des bagages par compagnie.
   * Bouton d'export de l'historique complet en fichier **CSV**.
3. **Alertes** (`/alerts`) :
   * Liste chronologique des alertes déclenchées avec message prudent et lien de vérification direct.
4. **Réglages** (`/settings`) :
   * Ajout, modification, pause et suppression de trajets (gestion multi-aéroports : ex. `Paris (CDG, ORY, BVA)`).
   * Sélection du bagage (aucun, cabine, soute 1, soute 2) et du seuil d'alerte en euros.
   * Masquage et mise à jour sécurisée des clés d'API dans `.env`.
   * Bouton de sauvegarde manuelle de la base SQLite (8 copies datées conservées automatiquement dans `data/backups/`).

---

## 🧪 Exécution des Tests Unitaires

Pour exécuter la suite de tests automatisés (calcul d'anticipation, médiane, percentiles, formatage prudent, détection de baisse flash, gestion des bagages et quotas) :

```bash
cd VolAlerte
venv\Scripts\pytest.exe tests -v
```

Tous les tests sont verts et validés.
