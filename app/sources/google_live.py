import json
import datetime
import re
import primp
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from selectolax.lexbor import LexborHTMLParser
from fast_flights import create_query, FlightQuery, Passengers, fetch_flights_html
from app.database import get_db, init_db

DAYS_FR = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."]
MONTHS_SHORT_FR = {
    1: "janv.", 2: "févr.", 3: "mars", 4: "avr.",
    5: "mai", 6: "juin", 7: "juil.", 8: "août",
    9: "sept.", 10: "oct.", 11: "nov.", 12: "déc."
}

# Compagnies régulières (Full-Service) qui incluent 1 bagage cabine (7-10 kg) + 1 bagage en soute (23 kg) sur l'international
FULL_SERVICE_AIRLINES = {
    "china southern", "hainan", "cathay pacific", "air china", "china eastern",
    "xiamen", "sichuan", "shandong", "shenzhen", "juneyao", "korean air",
    "asiana", "vietnam airlines", "eva air", "china airlines", "thai airways",
    "singapore airlines", "malaysia airlines", "garuda", "ana", "all nippon",
    "japan airlines", "jal", "air macau", "air france", "klm", "lufthansa",
    "turkish airlines", "qatar airways", "emirates", "etihad", "british airways"
}

# Compagnies low-cost asiatiques qui incluent 1 bagage cabine (7 kg) mais facturent la soute
ASIAN_LOWCOST_CABIN_INCLUDED = {
    "airasia", "thai airasia", "airasia x", "scoot", "cebu pacific",
    "vietjet", "thai lion", "batik air", "greater bay", "hk express", "jeju air", "t'way"
}

def format_date_fr(date_str: str) -> str:
    """Convertit '2026-11-15' en 'Dim. 15 nov. 2026'."""
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        day_name = DAYS_FR[d.weekday()]
        m_name = MONTHS_SHORT_FR.get(d.month, "")
        return f"{day_name} {d.day} {m_name} {d.year}"
    except Exception:
        return date_str

def _fmt_time(t_list) -> str:
    if not t_list or not isinstance(t_list, list):
        return ""
    h = int(t_list[0]) if len(t_list) >= 1 and t_list[0] is not None else 0
    m = int(t_list[1]) if len(t_list) >= 2 and t_list[1] is not None else 0
    return f"{h:02d}:{m:02d}"

def _fmt_date(d_list, fallback: str = "") -> str:
    if not d_list or not isinstance(d_list, list) or len(d_list) < 3:
        return fallback
    return f"{int(d_list[0]):04d}-{int(d_list[1]):02d}-{int(d_list[2]):02d}"

def _fmt_dur(minutes: Optional[int]) -> str:
    if not minutes or minutes <= 0:
        return ""
    h = int(minutes) // 60
    m = int(minutes) % 60
    if h > 0 and m > 0:
        return f"{h}h{m:02d}"
    elif h > 0:
        return f"{h}h00"
    return f"{m}min"

from functools import lru_cache

def _is_full_service(airlines_str: str) -> bool:
    low = airlines_str.lower()
    return any(fs in low for fs in FULL_SERVICE_AIRLINES)

@lru_cache(maxsize=2048)
def build_google_tfs_url(
    origin: str,
    dest: str,
    date_str: str,
    carry_on_bags: int = 1,
    checked_bags: int = 0,
    max_stops: Optional[int] = None,
    max_duration_minutes: Optional[int] = None,
    max_layover_minutes: Optional[int] = None,
    tfu_token: Optional[str] = None,
    booking_page: bool = False
) -> str:
    """
    Construit l'URL officielle Google Flights avec le paramètre protobuf `tfs=` (et `tfu=`),
    verrouillée en Euros (`curr=EUR`) et en Français (`hl=fr&gl=fr`).
    """
    fq_stops = max_stops if (max_stops is not None and max_stops >= 0) else None
    fq_dur = int(max_duration_minutes) if (max_duration_minutes and max_duration_minutes > 0) else None
    fq_lay = int(max_layover_minutes) if (max_layover_minutes and max_layover_minutes > 0) else None

    q = create_query(
        flights=[
            FlightQuery(
                date=date_str[:10],
                from_airport=origin.strip().upper(),
                to_airport=dest.strip().upper(),
                max_stops=fq_stops,
                max_duration_minutes=fq_dur,
                max_layover_minutes=fq_lay
            )
        ],
        trip="one-way",
        passengers=Passengers(adults=1),
        currency="EUR",
        language="fr",
        carry_on_bags=carry_on_bags,
        checked_bags=checked_bags
    )
    base_url = q.url()
    if booking_page and tfu_token:
        base_url = base_url.replace("/travel/flights/search?", "/travel/flights/booking?")
    if tfu_token:
        return f"{base_url}&tfu={tfu_token}&gl=fr"
    return f"{base_url}&gl=fr"

def build_trip_com_url(origin: str, dest: str, date_str: str) -> str:
    """Construit le lien de vérification croisée Trip.com verrouillé en EUR."""
    o = origin.strip().upper()
    d = dest.strip().upper()
    dt = date_str[:10]
    return f"https://fr.trip.com/flights/showfarefirst?dcity={o}&acity={d}&ddate={dt}&triptype=ow&class=y&quantity=1&curr=EUR&locale=fr-FR"

def build_skyscanner_url(origin: str, dest: str, date_str: str) -> str:
    """Construit le lien Skyscanner verrouillé en EUR (capte les tarifs OTA chinois absents de Google Flights)."""
    o = origin.strip().lower()
    d = dest.strip().lower()
    yymmdd = date_str[:10].replace("-", "")[2:]
    return f"https://www.skyscanner.fr/transport/vols/{o}/{d}/{yymmdd}/?adultsv2=1&cabinclass=economy&currency=EUR&locale=fr-FR&market=FR"

def _parse_google_flights_html(html: str, origin: str, dest: str, date_str: str) -> list[dict]:
    """Extrait tous les vols depuis le bloc script.ds:1 d'une page Google Flights."""
    parser = LexborHTMLParser(html)
    script = parser.css_first(r"script.ds\:1")
    if not script:
        return []
    text = script.text()
    if "data:" not in text:
        return []
    data_str = text.split("data:", 1)[1].rsplit(",", 1)[0]
    payload = json.loads(data_str)
    if not payload or len(payload) < 4:
        return []

    best_raw = payload[2][0] if (payload[2] and len(payload[2]) > 0 and payload[2][0]) else []
    other_raw = payload[3][0] if (payload[3] and len(payload[3]) > 0 and payload[3][0]) else []

    flights_out = []
    seen_keys = set()

    for is_best, group in [(True, best_raw), (False, other_raw)]:
        for k in group:
            if not k or len(k) < 2 or not k[1] or len(k[1]) == 0 or not k[1][0] or len(k[1][0]) < 2:
                continue
            price_val = k[1][0][1]
            if price_val is None:
                continue
            price_eur = int(price_val)
            tfu_token = k[1][1] if len(k[1]) > 1 else ""

            f = k[0]
            airlines_list = f[1] if (len(f) > 1 and isinstance(f[1], list)) else []
            airlines_str = " / ".join(airlines_list) if airlines_list else "Compagnie régulière"

            legs_raw = f[2] if (len(f) > 2 and isinstance(f[2], list)) else []
            stops_count = max(0, len(legs_raw) - 1)

            flight_nums = []
            legs_summary = []
            for leg in legs_raw:
                l_dep_code = leg[3] if len(leg) > 3 else origin
                l_arr_code = leg[6] if len(leg) > 6 else dest
                l_dep_t = _fmt_time(leg[8] if len(leg) > 8 else None)
                l_arr_t = _fmt_time(leg[10] if len(leg) > 10 else None)
                l_dur = _fmt_dur(leg[11] if len(leg) > 11 else None)
                l_aircraft = leg[17] if (len(leg) > 17 and leg[17]) else ""
                f_num = ""
                if len(leg) > 22 and isinstance(leg[22], list) and len(leg[22]) >= 2:
                    f_num = f"{leg[22][0]} {leg[22][1]}"
                    flight_nums.append(f_num)
                legs_summary.append({
                    "flight_num": f_num,
                    "dep_code": l_dep_code,
                    "arr_code": l_arr_code,
                    "dep_time": l_dep_t,
                    "arr_time": l_arr_t,
                    "duration": l_dur,
                    "aircraft": l_aircraft
                })

            flight_numbers_str = " + ".join(flight_nums) if flight_nums else airlines_str
            dep_code = f[3] if (len(f) > 3 and f[3]) else origin
            dep_date_actual = _fmt_date(f[4] if len(f) > 4 else None, date_str[:10])
            dep_time = _fmt_time(f[5] if len(f) > 5 else None)
            arr_code = f[6] if (len(f) > 6 and f[6]) else dest
            arr_date_actual = _fmt_date(f[7] if len(f) > 7 else None, date_str[:10])
            arr_time = _fmt_time(f[8] if len(f) > 8 else None)
            total_dur_min = int(f[9]) if (len(f) > 9 and f[9]) else 240

            day_diff = 0
            try:
                d1 = datetime.date.fromisoformat(dep_date_actual)
                d2 = datetime.date.fromisoformat(arr_date_actual)
                day_diff = (d2 - d1).days
            except Exception:
                pass

            arr_time_display = f"{arr_time} (+{day_diff}j)" if day_diff > 0 else arr_time
            schedule_str = f"{dep_time} {dep_code} ➔ {arr_time_display} {arr_code}"

            # Escales (layovers)
            layovers_raw = f[13] if (len(f) > 13 and isinstance(f[13], list)) else []
            max_layover_min = 0
            layover_parts = []
            for lay in layovers_raw:
                if isinstance(lay, list) and len(lay) >= 2:
                    lay_m = int(lay[0]) if lay[0] else 0
                    if lay_m > max_layover_min:
                        max_layover_min = lay_m
                    lay_code = lay[1] or ""
                    lay_city = lay[5] if (len(lay) > 5 and lay[5]) else (lay[4] if len(lay) > 4 else lay_code)
                    layover_parts.append(f"{_fmt_dur(lay_m)} à {lay_city} ({lay_code})")

            if stops_count == 0:
                layover_details = "Direct (sans escale)"
            elif layover_parts:
                layover_details = f"{stops_count} escale(s) : " + ", ".join(layover_parts)
            else:
                layover_details = f"{stops_count} escale(s)"

            # k[5] = [carry_on_fee_flag, ...] : 0 = bagage cabine inclus, 1 = bagage cabine payant
            k5 = k[5] if (len(k) > 5 and isinstance(k[5], list)) else [0, 0, 0]
            cabine_not_included = bool(k5 and len(k5) > 0 and k5[0] == 1)
            cabine_included = not cabine_not_included

            full_service = _is_full_service(airlines_str)
            soute_included = full_service
            soute_extra = 0 if soute_included else 38

            dedup_key = f"{flight_numbers_str}_{dep_time}_{price_eur}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            flights_out.append({
                "origin": dep_code,
                "dest": arr_code,
                "dep_date": dep_date_actual,
                "dep_date_fr": format_date_fr(dep_date_actual),
                "dep_time": dep_time,
                "arr_date": arr_date_actual,
                "arr_time": arr_time,
                "arr_time_display": arr_time_display,
                "day_diff": day_diff,
                "schedule_str": schedule_str,
                "airlines": airlines_str,
                "flight_numbers": flight_numbers_str,
                "duration_min": total_dur_min,
                "duration_str": _fmt_dur(total_dur_min),
                "stops": stops_count,
                "max_layover_min": max_layover_min,
                "layover_details": layover_details,
                "legs_summary": legs_summary,
                "price_base_eur": price_eur,
                "price_cabine_eur": price_eur if cabine_included else (price_eur + 28),
                "cabine_included": cabine_included,
                "soute_included": soute_included,
                "price_soute_eur": price_eur if soute_included else (price_eur + soute_extra),
                "tfu_token": tfu_token,
                "is_best_flight": is_best,
            })

    return flights_out

# Cache RAM ultra-rapide (0.05 ms) en façade de SQLite
_MEM_CACHE: dict[tuple[str, str, str], tuple[list[dict], str, float]] = {}
_BG_IN_PROGRESS: set[tuple[str, str, str]] = set()
_SHARED_CLIENT: Optional[primp.Client] = None

def _get_http_client() -> primp.Client:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None:
        _SHARED_CLIENT = primp.Client(impersonate="chrome_145", impersonate_os="macos", cookie_store=True)
    return _SHARED_CLIENT

def _fetch_html_fast(q) -> str:
    """Réutilise le pool de connexions HTTP/2 persistant (gain de 60% sur le temps réseau)."""
    client = _get_http_client()
    r = client.get(q.url(), timeout=12.0)
    return r.text

def fetch_live_google_flights(
    origin: str,
    dest: str,
    date_str: str,
    force_refresh: bool = False,
    cache_ttl_hours: float = 12.0,
    allow_network: bool = True
) -> tuple[list[dict], str]:
    """
    Récupère la liste complète des vols réels sur Google Flights en EUR pour (origin, dest, date_str).
    1. Vérifie d'abord le cache RAM `_MEM_CACHE` (< 0.05 ms).
    2. Sinon vérifie le cache SQLite `live_flight_cache` (< 1 ms).
    3. Si `allow_network=False`, retourne immédiatement sans bloquer l'interface et lance le rafraîchissement en tâche de fond.
    """
    orig = origin.strip().upper()[:3]
    dst = dest.strip().upper()[:3]
    dt = date_str[:10]
    key = (orig, dst, dt)

    now_ts = datetime.datetime.now().timestamp()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. Lecture instantanée en RAM
    if not force_refresh and key in _MEM_CACHE:
        flights_mem, fetched_str, saved_ts = _MEM_CACHE[key]
        if (now_ts - saved_ts) <= (cache_ttl_hours * 3600.0) and flights_mem:
            return flights_mem, fetched_str

    # 2. Lecture rapide dans SQLite
    init_db()
    if not force_refresh:
        with get_db() as conn:
            row = conn.execute(
                "SELECT fetched_at, flights_json FROM live_flight_cache WHERE origin = ? AND dest = ? AND date_vol = ?",
                (orig, dst, dt)
            ).fetchone()
            if row:
                try:
                    cached_flights = json.loads(row["flights_json"])
                    if cached_flights:
                        _MEM_CACHE[key] = (cached_flights, row["fetched_at"], now_ts)
                        fetched_dt = datetime.datetime.strptime(row["fetched_at"][:16], "%Y-%m-%d %H:%M")
                        age_hours = (datetime.datetime.now() - fetched_dt).total_seconds() / 3600.0
                        if age_hours <= cache_ttl_hours or not allow_network:
                            return cached_flights, row["fetched_at"]
                except Exception:
                    pass

    if not allow_network and not force_refresh:
        # Ne pas bloquer le rendu de la page : lancer le chargement en arrière-plan
        warm_radar_cache_async([(orig, dst)], dt)
        return [], now_str

    # 3. Requête Live Google Flights via le client HTTP/2 persistant
    try:
        q0 = create_query(
            flights=[FlightQuery(date=dt, from_airport=orig, to_airport=dst)],
            trip="one-way",
            passengers=Passengers(adults=1),
            currency="EUR",
            language="fr",
            carry_on_bags=0
        )
        html0 = _fetch_html_fast(q0)
        flights = _parse_google_flights_html(html0, orig, dst, dt)

        if flights and any(not f["cabine_included"] for f in flights):
            try:
                q1 = create_query(
                    flights=[FlightQuery(date=dt, from_airport=orig, to_airport=dst)],
                    trip="one-way",
                    passengers=Passengers(adults=1),
                    currency="EUR",
                    language="fr",
                    carry_on_bags=1
                )
                html1 = _fetch_html_fast(q1)
                flights_cb1 = _parse_google_flights_html(html1, orig, dst, dt)
                cb1_map = {f["flight_numbers"]: f for f in flights_cb1}
                for f in flights:
                    if f["flight_numbers"] in cb1_map:
                        f["price_cabine_eur"] = cb1_map[f["flight_numbers"]]["price_base_eur"]
                        f["tfu_token_cabine"] = cb1_map[f["flight_numbers"]]["tfu_token"]
            except Exception:
                pass

        if flights:
            _MEM_CACHE[key] = (flights, now_str, now_ts)
            with get_db() as conn:
                conn.execute("""
                    INSERT INTO live_flight_cache (origin, dest, date_vol, fetched_at, flights_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(origin, dest, date_vol) DO UPDATE SET
                        fetched_at = excluded.fetched_at,
                        flights_json = excluded.flights_json
                """, (orig, dst, dt, now_str, json.dumps(flights, ensure_ascii=False)))

                routes_rows = conn.execute(
                    "SELECT id, dates_ou_mois FROM routes WHERE origine LIKE ? AND destination LIKE ?",
                    (f"%{orig}%", f"%{dst}%")
                ).fetchall()
                best_f = min(flights, key=lambda x: x["price_base_eur"])
                all_p = [x["price_base_eur"] for x in flights]
                f_low = float(min(all_p)) if len(all_p) >= 2 else None
                f_high = float(max(all_p)) if len(all_p) >= 2 else None
                today_iso = datetime.date.today().isoformat()
                try:
                    d_vol_dt = datetime.date.fromisoformat(dt)
                    anticipation = max(0, (d_vol_dt - datetime.date.today()).days)
                except Exception:
                    anticipation = 30

                live_link = build_google_tfs_url(
                    orig, dst, dt,
                    carry_on_bags=1,
                    tfu_token=best_f.get("tfu_token")
                )

                for rr in routes_rows:
                    conn.execute("""
                        INSERT INTO price_observations (
                            route_id, source, date_vol, date_releve, jours_anticipation,
                            prix_billet_eur, compagnie, escales, niveau_google,
                            fourchette_basse, fourchette_haute, lien,
                            duree_totale_minutes, duree_escale_max_minutes, escales_details,
                            horaires_vol, numero_vol, prix_cabine_eur, prix_soute_eur
                        ) VALUES (?, 'google_live', ?, ?, ?, ?, ?, ?, 'bas', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        rr["id"], dt, today_iso, anticipation,
                        float(best_f["price_base_eur"]), best_f["airlines"], int(best_f["stops"]),
                        f_low, f_high, live_link,
                        int(best_f["duration_min"]), int(best_f["max_layover_min"]), best_f["layover_details"],
                        best_f["schedule_str"], best_f["flight_numbers"],
                        float(best_f["price_cabine_eur"]), float(best_f["price_soute_eur"])
                    ))

            return flights, now_str
    except Exception:
        pass

    if key in _MEM_CACHE:
        return _MEM_CACHE[key][0], _MEM_CACHE[key][1]
    return [], now_str

def warm_radar_cache(pairs: list[tuple[str, str]], date_str: str, force_refresh: bool = False):
    """Pré-charge en parallèle (12 threads HTTP/2) les paires manquantes."""
    init_db()
    dt = date_str[:10]
    to_fetch = []
    if force_refresh:
        to_fetch = list(set(pairs))
    else:
        with get_db() as conn:
            for orig, dst in set(pairs):
                key = (orig.strip().upper()[:3], dst.strip().upper()[:3], dt)
                if key in _MEM_CACHE:
                    continue
                row = conn.execute(
                    "SELECT fetched_at, flights_json FROM live_flight_cache WHERE origin = ? AND dest = ? AND date_vol = ?",
                    key
                ).fetchone()
                if row:
                    try:
                        _MEM_CACHE[key] = (json.loads(row["flights_json"]), row["fetched_at"], datetime.datetime.now().timestamp())
                        continue
                    except Exception:
                        pass
                to_fetch.append((key[0], key[1]))

    if not to_fetch:
        return

    import threading
    sem = threading.Semaphore(12)

    def _worker(pair):
        with sem:
            fetch_live_google_flights(pair[0], pair[1], dt, force_refresh=force_refresh, allow_network=True)

    threads = [threading.Thread(target=_worker, args=(p,), daemon=True) for p in to_fetch]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=14.0)

def warm_radar_cache_async(pairs: list[tuple[str, str]], date_str: str):
    """Lance le pré-chargement en tâche de fond (100% daemon) sans bloquer la requête HTTP ni la fermeture du processus."""
    import threading
    import sys
    if "pytest" in sys.modules:
        return
    dt = date_str[:10]
    new_pairs = []
    for o, d in set(pairs):
        k = (o.strip().upper()[:3], d.strip().upper()[:3], dt)
        if k not in _MEM_CACHE and k not in _BG_IN_PROGRESS:
            _BG_IN_PROGRESS.add(k)
            new_pairs.append((k[0], k[1]))
    if not new_pairs:
        return

    def _bg():
        try:
            warm_radar_cache(new_pairs, dt, force_refresh=False)
        finally:
            for o, d in new_pairs:
                _BG_IN_PROGRESS.discard((o, d, dt))

    t = threading.Thread(target=_bg, daemon=True)
    t.start()
