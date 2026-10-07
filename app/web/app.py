import io
import csv
import re
import datetime
from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.config import settings, DATA_DIR, DB_PATH
from app.database import (
    get_db,
    init_db,
    get_api_usage,
    get_last_run,
    backup_database
)
from app.models import Route
from app.analytics import (
    compute_anticipation_brackets,
    get_best_window_info,
    compute_7day_trend,
    get_baggage_cost,
    get_price_percentile,
    compute_monthly_price_stats,
    parse_month_info,
    scan_radar_deals,
    format_minutes_to_hours,
    get_nearby_airports
)
from app.sources.mock_source import seed_demo_database
from app.sources.google_live import (
    fetch_live_google_flights,
    build_google_tfs_url,
    build_trip_com_url,
    build_skyscanner_url,
    format_date_fr
)
from app.scheduler_task import execute_daily_run

app = FastAPI(title="VolAlerte", description="Suivi intelligent des prix de vols")

# Fichiers statiques et templates
static_dir = DATA_DIR.parent / "app" / "web" / "static"
templates_dir = DATA_DIR.parent / "app" / "web" / "templates"

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

@app.on_event("startup")
def on_startup():
    init_db()
    if settings.DEMO_MODE:
        seed_demo_database()

def _extract_iata_code(text: str, default: str = "CGO") -> str:
    s = (text or "").upper()
    m_paren = re.search(r'\(([A-Z]{3})\)', s)
    if m_paren:
        return m_paren.group(1)
    tokens = re.findall(r'\b([A-Z]{3})\b', s)
    if tokens:
        return tokens[-1]
    clean = s.strip()[:3]
    return clean if len(clean) == 3 else default

def _extract_iata_and_future_date(origine: str, destination: str, dates_ou_mois: str) -> tuple[str, str, str]:
    o_str = _extract_iata_code(origine, "CGO")
    d_str = _extract_iata_code(destination, "BKK")
    if o_str == "PAR":
        o_str = "ORY"
    if d_str == "ROM":
        d_str = "FCO"

    dep_date = (dates_ou_mois or "2026-11-15").strip()
    if ":" in dep_date:
        dep_date = dep_date.split(":")[0]
    elif len(dep_date) == 7:
        dep_date = f"{dep_date}-15"

    today = datetime.date.today()
    try:
        dt = datetime.date.fromisoformat(dep_date[:10])
        if dt <= today:
            dt = datetime.date(2026, 11, 15)
        dep_date = dt.isoformat()
    except Exception:
        dep_date = "2026-11-15"

    return o_str, d_str, dep_date

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    routes_data = []
    with get_db() as conn:
        routes_cur = conn.execute("SELECT * FROM routes ORDER BY id ASC")
        raw_routes = routes_cur.fetchall()

        for r in raw_routes:
            route_id = r["id"]
            o_iata, d_iata, dep_date_iso = _extract_iata_and_future_date(r["origine"], r["destination"], r["dates_ou_mois"])
            dep_date_fr = format_date_fr(dep_date_iso)

            # Récupérer les vols live depuis le cache (ou repli sur le vendredi 13 du même mois si aucun vol le dimanche 15)
            live_flights, live_fetched_at = fetch_live_google_flights(o_iata, d_iata, dep_date_iso, force_refresh=False, allow_network=False)
            if not live_flights:
                alt_date = f"{dep_date_iso[:7]}-13"
                live_flights, live_fetched_at = fetch_live_google_flights(o_iata, d_iata, alt_date, force_refresh=False, allow_network=False)
                if live_flights:
                    dep_date_iso = alt_date
                    dep_date_fr = format_date_fr(dep_date_iso)

            obs_cur = conn.execute("""
                SELECT * FROM price_observations
                WHERE route_id = ?
                ORDER BY date_releve DESC, prix_billet_eur ASC
            """, (route_id,))
            observations = obs_cur.fetchall()

            last_obs = observations[0] if observations else None
            best_live = min(live_flights, key=lambda x: x["price_base_eur"]) if live_flights else None

            if best_live:
                comp = best_live["airlines"]
                last_ticket = float(best_live["price_base_eur"])
                total_cabine = float(best_live["price_cabine_eur"])
                total_soute = float(best_live["price_soute_eur"])
                cost_cabine = round(total_cabine - last_ticket, 1)
                cost_soute = round(total_soute - last_ticket, 1)
                if r["bagage"] == "cabine":
                    baggage_cost = cost_cabine
                    total_price = total_cabine
                elif r["bagage"] in ("soute_1", "soute_2"):
                    baggage_cost = cost_soute
                    total_price = total_soute
                else:
                    baggage_cost = 0.0
                    total_price = last_ticket
                flight_dur_str = best_live["duration_str"]
                stops_count = best_live["stops"]
                escales_desc = best_live["layover_details"]
                schedule_str = best_live["schedule_str"]
                flight_numbers = best_live["flight_numbers"]
                source_label = "Google Flights Live (EUR)"
                obs_date = live_fetched_at
                tfu_tok = best_live.get("tfu_token")
            else:
                comp = last_obs["compagnie"] if last_obs else ""
                baggage_cost = get_baggage_cost(route_id, comp, r["bagage"]) if last_obs else 0.0
                last_ticket = float(last_obs["prix_billet_eur"]) if last_obs else None
                total_price = round(last_ticket + baggage_cost, 1) if last_ticket is not None else None
                cost_cabine = get_baggage_cost(route_id, comp, "cabine") if last_obs else 0.0
                cost_soute = get_baggage_cost(route_id, comp, "soute_1") if last_obs else 0.0
                total_cabine = round(last_ticket + cost_cabine, 1) if last_ticket is not None else None
                total_soute = round(last_ticket + cost_soute, 1) if last_ticket is not None else None
                flight_dur_str = format_minutes_to_hours(last_obs["duree_totale_minutes"]) if (last_obs and last_obs["duree_totale_minutes"]) else None
                stops_count = last_obs["escales"] if (last_obs and last_obs["escales"] is not None) else 0
                escales_desc = last_obs["escales_details"] if (last_obs and last_obs["escales_details"]) else ("Direct (sans escale)" if stops_count == 0 else f"{stops_count} escale(s)")
                schedule_str = (last_obs["horaires_vol"] if (last_obs and "horaires_vol" in last_obs.keys() and last_obs["horaires_vol"]) else f"Départ {o_iata} ➔ {d_iata}")
                flight_numbers = (last_obs["numero_vol"] if (last_obs and "numero_vol" in last_obs.keys() and last_obs["numero_vol"]) else comp)
                source_label = "Google Flights (SerpApi)" if (last_obs and last_obs["source"] == "google") else ((last_obs["source"].capitalize()) if last_obs else "")
                obs_date = last_obs["date_releve"] if last_obs else ""
                tfu_tok = None

            carry_on_p = 1 if r["bagage"] == "cabine" else 0
            checked_p = 1 if r["bagage"] in ("soute_1", "soute_2") else 0
            google_link = build_google_tfs_url(o_iata, d_iata, dep_date_iso, carry_on_bags=carry_on_p, checked_bags=checked_p)
            google_booking_link = build_google_tfs_url(o_iata, d_iata, dep_date_iso, carry_on_bags=carry_on_p, checked_bags=checked_p, tfu_token=tfu_tok, booking_page=True)
            trip_com_link = build_trip_com_url(o_iata, d_iata, dep_date_iso)
            skyscanner_link = build_skyscanner_url(o_iata, d_iata, dep_date_iso)

            # Croiser avec les aéroports voisins (ex: XIY 78 € pour CNX, PKX 96 € Direct pour HAN)
            nearby_deal = None
            nearby_list = get_nearby_airports(o_iata)
            check_dates = [dep_date_iso]
            for d_day in (f"{dep_date_iso[:7]}-15", f"{dep_date_iso[:7]}-13"):
                if d_day not in check_dates:
                    check_dates.append(d_day)
            for nb in nearby_list:
                nb_code = nb["code"]
                for cd in check_dates:
                    nb_flights, _ = fetch_live_google_flights(nb_code, d_iata, cd, force_refresh=False, allow_network=False)
                    if nb_flights:
                        best_nb = min(nb_flights, key=lambda x: x["price_cabine_eur"] if r["bagage"] == "cabine" else x["price_base_eur"])
                        nb_price = float(best_nb["price_cabine_eur"] if r["bagage"] == "cabine" else best_nb["price_base_eur"])
                        if total_price is not None and nb_price < total_price:
                            if nearby_deal is None or nb_price < nearby_deal["price"]:
                                nb_book_url = build_google_tfs_url(
                                    nb_code, d_iata, best_nb["dep_date"],
                                    carry_on_bags=carry_on_p, checked_bags=checked_p,
                                    tfu_token=best_nb.get("tfu_token"), booking_page=True
                                )
                                tgv_min = int(nb.get("tgv_min", 120))
                                tgv_cost = int(nb.get("tgv_cost_eur", 22))
                                tgv_time_str = nb.get("tgv_time_str", nb["detail"])
                                tot_j_str = format_minutes_to_hours(int(best_nb.get("duration_min", 220)) + tgv_min)
                                raw_sav = int(total_price - nb_price)
                                nearby_deal = {
                                    "code": nb_code,
                                    "name": nb["name"],
                                    "detail": nb["detail"],
                                    "tgv_time_str": tgv_time_str,
                                    "tgv_cost_eur": tgv_cost,
                                    "price": int(nb_price),
                                    "price_with_tgv": int(nb_price) + tgv_cost,
                                    "savings": raw_sav,
                                    "net_savings": max(0, raw_sav - tgv_cost),
                                    "airline": best_nb["airlines"],
                                    "flight_numbers": best_nb["flight_numbers"],
                                    "dep_date_fr": best_nb["dep_date_fr"],
                                    "schedule_str": best_nb["schedule_str"],
                                    "duration_str": best_nb.get("duration_str", ""),
                                    "total_journey_str": tot_j_str,
                                    "stops_label": "Direct" if best_nb["stops"] == 0 else f"{best_nb['stops']} esc.",
                                    "booking_url": nb_book_url,
                                }

            history_tuples = [(float(o["prix_billet_eur"]), int(o["jours_anticipation"])) for o in observations]
            dates_prices = [(str(o["date_releve"]), float(o["prix_billet_eur"])) for o in observations]
            dates_prices_sorted = sorted(dates_prices, key=lambda x: x[0])

            brackets = compute_anticipation_brackets(history_tuples)
            best_win = get_best_window_info(brackets)
            trend = compute_7day_trend(dates_prices_sorted)

            monthly_stats = compute_monthly_price_stats(
                route_id=route_id,
                dates_ou_mois=dep_date_iso,
                baggage_cost=baggage_cost,
                current_total_price=total_price
            )

            routes_data.append({
                "id": route_id,
                "origine": r["origine"],
                "destination": r["destination"],
                "o_iata": o_iata,
                "d_iata": d_iata,
                "dep_date_iso": dep_date_iso,
                "dep_date_fr": dep_date_fr,
                "schedule_str": schedule_str,
                "flight_numbers": flight_numbers,
                "compagnie": comp,
                "type": r["type"],
                "dates_ou_mois": r["dates_ou_mois"],
                "passagers": r["passagers"],
                "bagage": r["bagage"],
                "seuil_eur": r["seuil_eur"],
                "actif": bool(r["actif"]),
                "last_obs": dict(last_obs) if last_obs else None,
                "last_ticket": last_ticket,
                "baggage_cost": baggage_cost,
                "total_price": total_price,
                "cost_cabine": cost_cabine,
                "cost_soute": cost_soute,
                "total_cabine": total_cabine,
                "total_soute": total_soute,
                "best_window": best_win,
                "trend": trend,
                "observations_count": len(observations),
                "month_id": monthly_stats["month_id"],
                "month_name": monthly_stats["month_name"],
                "day_str": monthly_stats["day_str"],
                "monthly_ticket_avg": monthly_stats["monthly_ticket_avg"],
                "monthly_avg_total": monthly_stats["monthly_avg_total"],
                "range_low": monthly_stats["range_low"],
                "range_high": monthly_stats["range_high"],
                "monthly_savings": monthly_stats["monthly_savings"],
                "monthly_savings_pct": monthly_stats["monthly_savings_pct"],
                "source_avg": monthly_stats.get("source_avg", ""),
                "flight_duration_str": flight_dur_str,
                "stops": stops_count,
                "escales_details": escales_desc,
                "obs_source": source_label,
                "obs_date": obs_date,
                "google_link": google_link,
                "google_booking_link": google_booking_link,
                "trip_com_link": trip_com_link,
                "skyscanner_link": skyscanner_link,
                "nearby_deal": nearby_deal,
            })

        alerts_cur = conn.execute("""
            SELECT a.*, r.origine, r.destination, r.dates_ou_mois, r.bagage
            FROM alerts a
            JOIN routes r ON a.route_id = r.id
            ORDER BY a.id DESC LIMIT 5
        """)
        recent_alerts = [_enrich_alert_row(dict(a)) for a in alerts_cur.fetchall()]

    serpapi_used = get_api_usage("serpapi")
    last_run = get_last_run()

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "routes": routes_data,
        "recent_alerts": recent_alerts,
        "serpapi_used": serpapi_used,
        "serpapi_max": 100,
        "demo_mode": settings.DEMO_MODE,
        "last_run": last_run,
        "active_page": "dashboard"
    })

@app.get("/route/{route_id}", response_class=HTMLResponse)
async def route_detail(request: Request, route_id: int):
    with get_db() as conn:
        r_cur = conn.execute("SELECT * FROM routes WHERE id = ?", (route_id,))
        route = r_cur.fetchone()
        if not route:
            return RedirectResponse("/", status_code=303)

        o_iata, d_iata, dep_date_iso = _extract_iata_and_future_date(route["origine"], route["destination"], route["dates_ou_mois"])
        dep_date_fr = format_date_fr(dep_date_iso)

        live_flights, _ = fetch_live_google_flights(o_iata, d_iata, dep_date_iso, force_refresh=False, allow_network=False)
        if not live_flights:
            alt_date = f"{dep_date_iso[:7]}-13"
            live_flights, _ = fetch_live_google_flights(o_iata, d_iata, alt_date, force_refresh=False, allow_network=False)
            if live_flights:
                dep_date_iso = alt_date
                dep_date_fr = format_date_fr(dep_date_iso)

        obs_cur = conn.execute("""
            SELECT * FROM price_observations
            WHERE route_id = ?
            ORDER BY date_releve ASC
        """, (route_id,))
        observations = [dict(o) for o in obs_cur.fetchall()]
        for o in observations:
            o["flight_duration_str"] = format_minutes_to_hours(o.get("duree_totale_minutes"))
            o["escales_str"] = o.get("escales_details") or ("Direct (0 escale)" if o.get("escales") == 0 else f"{o.get('escales')} escale(s)")
            src = o.get("source", "")
            o["source_label"] = "Google Flights Live (EUR)" if src == "google_live" else ("Google Flights (SerpApi)" if src == "google" else src.capitalize())

        bags_cur = conn.execute("""
            SELECT * FROM baggage_prices
            WHERE route_id = ? OR route_id IS NULL
            ORDER BY compagnie ASC, type ASC
        """, (route_id,))
        baggage_list = [dict(b) for b in bags_cur.fetchall()]

    history_tuples = [(float(o["prix_billet_eur"]), int(o["jours_anticipation"])) for o in observations]
    brackets = compute_anticipation_brackets(history_tuples)
    best_win = get_best_window_info(brackets)

    dates_labels = []
    ticket_prices = []
    cabine_prices = []
    soute_prices = []
    soute2_prices = []
    typical_lows = []
    typical_highs = []

    for o in observations:
        dates_labels.append(o["date_releve"])
        t_price = float(o["prix_billet_eur"])
        bag_cabine = get_baggage_cost(route_id, o["compagnie"], "cabine")
        bag_soute = get_baggage_cost(route_id, o["compagnie"], "soute_1")
        bag_soute2 = get_baggage_cost(route_id, o["compagnie"], "soute_2")

        ticket_prices.append(t_price)
        cabine_prices.append(round(t_price + bag_cabine, 1))
        soute_prices.append(round(t_price + bag_soute, 1))
        soute2_prices.append(round(t_price + bag_soute2, 1))
        typical_lows.append(o["fourchette_basse"])
        typical_highs.append(o["fourchette_haute"])

    best_live = min(live_flights, key=lambda x: x["price_base_eur"]) if live_flights else None
    if best_live:
        latest_compagnie = best_live["airlines"]
        latest_ticket = float(best_live["price_base_eur"])
        cost_cabine = float(best_live["price_cabine_eur"] - best_live["price_base_eur"])
        cost_soute = float(best_live["price_soute_eur"] - best_live["price_base_eur"])
        cost_soute2 = cost_soute + 40.0
    else:
        latest_compagnie = observations[-1]["compagnie"] if observations else ""
        latest_ticket = float(observations[-1]["prix_billet_eur"]) if observations else 0.0
        cost_cabine = get_baggage_cost(route_id, latest_compagnie, "cabine")
        cost_soute = get_baggage_cost(route_id, latest_compagnie, "soute_1")
        cost_soute2 = get_baggage_cost(route_id, latest_compagnie, "soute_2")

    options_summary = {
        "aucun": {"cost": 0.0, "total": latest_ticket},
        "cabine": {"cost": cost_cabine, "total": round(latest_ticket + cost_cabine, 1)},
        "soute_1": {"cost": cost_soute, "total": round(latest_ticket + cost_soute, 1)},
        "soute_2": {"cost": cost_soute2, "total": round(latest_ticket + cost_soute2, 1)},
    }

    bracket_labels = [b.label for b in brackets]
    bracket_medians = [b.median_price for b in brackets]
    bracket_counts = [b.count for b in brackets]
    bracket_confs = [b.confidence for b in brackets]
    bracket_diffs = [b.diff_with_best for b in brackets]

    active_baggage = route["bagage"]
    active_cost = options_summary.get(active_baggage, {}).get("cost", 0.0)
    active_total = options_summary.get(active_baggage, {}).get("total", latest_ticket)

    monthly_stats = compute_monthly_price_stats(
        route_id=route_id,
        dates_ou_mois=dep_date_iso,
        baggage_cost=active_cost,
        current_total_price=active_total
    )

    carry_on_p = 1 if active_baggage == "cabine" else 0
    checked_p = 1 if active_baggage in ("soute_1", "soute_2") else 0
    tfu_tok = best_live.get("tfu_token") if best_live else None
    google_link = build_google_tfs_url(o_iata, d_iata, dep_date_iso, carry_on_bags=carry_on_p, checked_bags=checked_p)
    google_booking_link = build_google_tfs_url(o_iata, d_iata, dep_date_iso, carry_on_bags=carry_on_p, checked_bags=checked_p, tfu_token=tfu_tok, booking_page=True)
    trip_com_link = build_trip_com_url(o_iata, d_iata, dep_date_iso)

    return templates.TemplateResponse(request=request, name="detail.html", context={
        "route": dict(route),
        "dep_date_iso": dep_date_iso,
        "dep_date_fr": dep_date_fr,
        "best_live": best_live,
        "live_flights": live_flights[:8] if live_flights else [],
        "observations": observations,
        "baggage_list": baggage_list,
        "best_window": best_win,
        "brackets": brackets,
        "dates_labels": dates_labels,
        "ticket_prices": ticket_prices,
        "cabine_prices": cabine_prices,
        "soute_prices": soute_prices,
        "soute2_prices": soute2_prices,
        "options_summary": options_summary,
        "typical_lows": typical_lows,
        "typical_highs": typical_highs,
        "bracket_labels": bracket_labels,
        "bracket_medians": bracket_medians,
        "bracket_counts": bracket_counts,
        "bracket_confs": bracket_confs,
        "bracket_diffs": bracket_diffs,
        "google_link": google_link,
        "google_booking_link": google_booking_link,
        "trip_com_link": trip_com_link,
        "monthly_stats": monthly_stats,
        "active_page": "dashboard"
    })

@app.post("/route/{route_id}/update-baggage")
async def update_route_baggage(route_id: int, bagage: str = Form(...)):
    with get_db() as conn:
        conn.execute("UPDATE routes SET bagage = ? WHERE id = ?", (bagage.strip(), route_id))
    return RedirectResponse(f"/route/{route_id}?baggage_updated=1", status_code=303)

@app.get("/route/{route_id}/export-csv")
async def export_csv(route_id: int):
    with get_db() as conn:
        r_cur = conn.execute("SELECT * FROM routes WHERE id = ?", (route_id,))
        route = r_cur.fetchone()
        if not route:
            return Response("Trajet introuvable", status_code=404)

        obs_cur = conn.execute("""
            SELECT source, date_vol, date_releve, jours_anticipation, prix_billet_eur,
                   compagnie, escales, niveau_google, fourchette_basse, fourchette_haute
            FROM price_observations
            WHERE route_id = ?
            ORDER BY date_releve ASC
        """, (route_id,))
        rows = obs_cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Source", "Date_du_vol", "Date_du_releve", "Jours_anticipation",
        "Prix_billet_EUR", "Compagnie", "Escales", "Niveau_Google",
        "Fourchette_basse", "Fourchette_haute"
    ])

    for r in rows:
        writer.writerow([
            r["source"], r["date_vol"], r["date_releve"], r["jours_anticipation"],
            r["prix_billet_eur"], r["compagnie"], r["escales"], r["niveau_google"],
            r["fourchette_basse"] or "", r["fourchette_haute"] or ""
        ])

    csv_data = output.getvalue()
    filename = f"historique_vol_{route['origine']}_{route['destination']}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/radar", response_class=HTMLResponse)
async def radar_view(
    request: Request,
    origin: str = "CGO",
    month: str = "2026-11",
    exact_date: str = "",
    bagage: str = "cabine",
    include_nearby: int = 1,
    filter: str = "all",
    max_duration: float = 0.0,
    max_stops: int = -1,
    max_layover: float = 0.0,
    refresh: int = 0
):
    radar_data = scan_radar_deals(
        origin=origin,
        include_nearby=bool(include_nearby),
        target_month=month,
        filter_tag=filter,
        max_duration=float(max_duration),
        max_stops=int(max_stops),
        max_layover=float(max_layover),
        bagage_mode=bagage,
        exact_date=exact_date,
        force_refresh=bool(refresh)
    )
    return templates.TemplateResponse(request=request, name="radar.html", context={
        "radar": radar_data,
        "demo_mode": settings.DEMO_MODE,
        "active_page": "radar"
    })

@app.post("/radar/add-to-watchlist")
async def add_radar_deal_to_watchlist(
    origine: str = Form(...),
    destination: str = Form(...),
    dates_ou_mois: str = Form(...),
    seuil_eur: float = Form(...)
):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO routes (origine, destination, type, dates_ou_mois, passagers, bagage, seuil_eur, actif)
            VALUES (?, ?, 'aller_simple', ?, 1, 'cabine', ?, 1)
        """, (origine.strip(), destination.strip(), dates_ou_mois.strip(), seuil_eur))
    return RedirectResponse("/?added_from_radar=1", status_code=303)

def _enrich_alert_row(a: dict) -> dict:
    o_iata, d_iata, dep_date_iso = _extract_iata_and_future_date(
        a.get("origine", ""), a.get("destination", ""), a.get("dates_ou_mois", "")
    )
    bagage = a.get("bagage") or "cabine"
    carry_on_p = 1 if bagage == "cabine" else 0
    checked_p = 1 if bagage in ("soute_1", "soute_2") else 0

    live_flights, fetched_at = fetch_live_google_flights(
        o_iata, d_iata, dep_date_iso, force_refresh=False, allow_network=False
    )
    if not live_flights:
        alt_date = f"{dep_date_iso[:7]}-13"
        live_flights, fetched_at = fetch_live_google_flights(
            o_iata, d_iata, alt_date, force_refresh=False, allow_network=False
        )
        if live_flights:
            dep_date_iso = alt_date
    best_live = min(live_flights, key=lambda x: x["price_base_eur"]) if live_flights else None

    if best_live:
        dep_date_iso = best_live["dep_date"]
        dep_date_fr = best_live["dep_date_fr"]
        schedule_str = best_live["schedule_str"]
        airline = best_live["airlines"]
        flight_numbers = best_live["flight_numbers"]
        duration_str = best_live["duration_str"]
        layover_details = best_live["layover_details"]
        stops = best_live["stops"]
        tfu_tok = best_live.get("tfu_token_cabine") if (bagage == "cabine" and best_live.get("tfu_token_cabine")) else best_live.get("tfu_token")

        ticket_eur = float(best_live["price_base_eur"])
        cabine_eur = float(best_live["price_cabine_eur"])
        soute_eur = float(best_live["price_soute_eur"])
        if bagage == "cabine":
            bag_eur = round(cabine_eur - ticket_eur, 1)
            tot_eur = cabine_eur
        elif bagage in ("soute_1", "soute_2"):
            bag_eur = round(soute_eur - ticket_eur, 1)
            tot_eur = soute_eur
        else:
            bag_eur = 0.0
            tot_eur = ticket_eur

        a["prix_billet"] = ticket_eur
        a["prix_bagage"] = bag_eur
        a["prix_total"] = tot_eur
        a["message"] = (
            f"{a.get('origine', o_iata)} ➔ {a.get('destination', d_iata)} • Vol le {dep_date_fr} ({schedule_str}) "
            f"sur {airline} ({flight_numbers}, {layover_details}) : "
            f"billet {int(ticket_eur)} € + bagage {bagage} {int(bag_eur)} € = {int(tot_eur)} € TTC."
        )
    else:
        dep_date_fr = format_date_fr(dep_date_iso)
        schedule_str = f"Départ {o_iata} ➔ {d_iata}"
        airline = ""
        flight_numbers = ""
        duration_str = ""
        layover_details = ""
        stops = 0
        tfu_tok = None

    google_booking_link = build_google_tfs_url(
        o_iata, d_iata, dep_date_iso,
        carry_on_bags=carry_on_p, checked_bags=checked_p,
        tfu_token=tfu_tok, booking_page=True
    )
    google_link = build_google_tfs_url(
        o_iata, d_iata, dep_date_iso,
        carry_on_bags=carry_on_p, checked_bags=checked_p,
        booking_page=False
    )
    trip_com_link = build_trip_com_url(o_iata, d_iata, dep_date_iso)
    skyscanner_link = build_skyscanner_url(o_iata, d_iata, dep_date_iso)

    # Vérifier aussi s'il existe un meilleur vol depuis un aéroport TGV voisin (ex: XIY 78 € vers CNX ou PKX 96 € vers HAN)
    nearby_deal = None
    nearby_list = get_nearby_airports(o_iata)
    check_dates = [dep_date_iso]
    for d_day in (f"{dep_date_iso[:7]}-15", f"{dep_date_iso[:7]}-13"):
        if d_day not in check_dates:
            check_dates.append(d_day)
    for nb in nearby_list:
        nb_code = nb["code"]
        for cd in check_dates:
            nb_flights, _ = fetch_live_google_flights(nb_code, d_iata, cd, force_refresh=False, allow_network=False)
            if nb_flights:
                best_nb = min(nb_flights, key=lambda x: x["price_cabine_eur"] if bagage == "cabine" else x["price_base_eur"])
                nb_price = float(best_nb["price_cabine_eur"] if bagage == "cabine" else best_nb["price_base_eur"])
                if a.get("prix_total") and nb_price < float(a["prix_total"]):
                    if nearby_deal is None or nb_price < nearby_deal["price"]:
                        nb_book_url = build_google_tfs_url(
                            nb_code, d_iata, best_nb["dep_date"],
                            carry_on_bags=carry_on_p, checked_bags=checked_p,
                            tfu_token=best_nb.get("tfu_token"), booking_page=True
                        )
                        nb_search_url = build_google_tfs_url(
                            nb_code, d_iata, best_nb["dep_date"],
                            carry_on_bags=carry_on_p, checked_bags=checked_p,
                            booking_page=False
                        )
                        tgv_min = int(nb.get("tgv_min", 120))
                        tgv_cost = int(nb.get("tgv_cost_eur", 22))
                        tgv_time_str = nb.get("tgv_time_str", nb["detail"])
                        tot_j_str = format_minutes_to_hours(int(best_nb.get("duration_min", 220)) + tgv_min)
                        raw_sav = int(float(a["prix_total"]) - nb_price)
                        nearby_deal = {
                            "code": nb_code,
                            "name": nb["name"],
                            "detail": nb["detail"],
                            "tgv_time_str": tgv_time_str,
                            "tgv_cost_eur": tgv_cost,
                            "price": int(nb_price),
                            "price_with_tgv": int(nb_price) + tgv_cost,
                            "price_base": float(best_nb["price_base_eur"]),
                            "savings": raw_sav,
                            "net_savings": max(0, raw_sav - tgv_cost),
                            "airline": best_nb["airlines"],
                            "flight_numbers": best_nb["flight_numbers"],
                            "dep_date_iso": best_nb["dep_date"],
                            "dep_date_fr": best_nb["dep_date_fr"],
                            "schedule_str": best_nb["schedule_str"],
                            "duration_str": best_nb["duration_str"],
                            "total_journey_str": tot_j_str,
                            "layover_details": best_nb["layover_details"],
                            "stops": best_nb["stops"],
                            "stops_label": "Direct" if best_nb["stops"] == 0 else f"{best_nb['stops']} esc.",
                            "booking_url": nb_book_url,
                            "search_url": nb_search_url,
                        }

    tgv_time_str = ""
    total_journey_str = duration_str
    tgv_cost_eur = 0

    # Si le vol direct de l'aéroport d'origine dépasse 150 € (ex: CGO->CNX à 229 €) alors que l'aéroport TGV voisin
    # est en alerte prix cassé (ex: XIY->CNX à 78 € Direct), l'alerte pointe directement sur le vol à 78 € !
    if nearby_deal and float(a.get("prix_total", 0)) > 150:
        o_iata = nearby_deal["code"]
        dep_date_iso = nearby_deal["dep_date_iso"]
        dep_date_fr = nearby_deal["dep_date_fr"]
        schedule_str = nearby_deal["schedule_str"]
        airline = nearby_deal["airline"]
        flight_numbers = nearby_deal["flight_numbers"]
        duration_str = nearby_deal["duration_str"]
        layover_details = nearby_deal["layover_details"]
        stops = nearby_deal["stops"]
        tgv_time_str = nearby_deal["tgv_time_str"]
        total_journey_str = nearby_deal["total_journey_str"]
        tgv_cost_eur = nearby_deal["tgv_cost_eur"]
        google_booking_link = nearby_deal["booking_url"]
        google_link = nearby_deal["search_url"]
        trip_com_link = build_trip_com_url(o_iata, d_iata, dep_date_iso)
        skyscanner_link = build_skyscanner_url(o_iata, d_iata, dep_date_iso)
        a["origine"] = f"{nearby_deal['name']} (🚅 {tgv_time_str.split('(')[0].strip()} depuis Zhengzhou)"
        a["prix_billet"] = nearby_deal["price_base"]
        a["prix_bagage"] = round(nearby_deal["price"] - nearby_deal["price_base"], 1)
        a["prix_total"] = float(nearby_deal["price"])
        a["message"] = (
            f"🚅 Bon plan TGV (Train estimé : {tgv_time_str} • Durée totale Train + Vol : ~{total_journey_str}) • "
            f"{nearby_deal['name']} ➔ {a.get('destination', d_iata)} • Vol le {dep_date_fr} ({schedule_str}, vol de {duration_str}) "
            f"sur {airline} ({flight_numbers}, {layover_details}) : "
            f"billet {int(a['prix_billet'])} € + bagage {bagage} {int(a['prix_bagage'])} € = {int(a['prix_total'])} € TTC "
            f"(+{tgv_cost_eur} € TGV = {nearby_deal['price_with_tgv']} € tout compris • économie de -{nearby_deal['savings']} € sur le vol / -{nearby_deal['net_savings']} € net vs départ CGO)."
        )
        nearby_deal = None

    a["o_iata"] = o_iata
    a["d_iata"] = d_iata
    a["dep_date_iso"] = dep_date_iso
    a["dep_date_fr"] = dep_date_fr
    a["schedule_str"] = schedule_str
    a["airline"] = airline
    a["flight_numbers"] = flight_numbers
    a["duration_str"] = duration_str
    a["tgv_time_str"] = tgv_time_str
    a["total_journey_str"] = total_journey_str
    a["tgv_cost_eur"] = tgv_cost_eur
    a["layover_details"] = layover_details
    a["stops"] = stops
    a["lien"] = google_booking_link
    a["google_booking_link"] = google_booking_link
    a["google_link"] = google_link
    a["trip_com_link"] = trip_com_link
    a["skyscanner_link"] = skyscanner_link
    a["nearby_deal"] = nearby_deal
    return a

@app.get("/alerts", response_class=HTMLResponse)
async def alerts_view(request: Request):
    with get_db() as conn:
        alerts_cur = conn.execute("""
            SELECT a.*, r.origine, r.destination, r.dates_ou_mois, r.bagage
            FROM alerts a
            JOIN routes r ON a.route_id = r.id
            ORDER BY a.id DESC
        """)
        alerts_list = [_enrich_alert_row(dict(row)) for row in alerts_cur.fetchall()]

    return templates.TemplateResponse(request=request, name="alerts.html", context={
        "alerts": alerts_list,
        "active_page": "alerts"
    })

@app.get("/settings", response_class=HTMLResponse)
async def settings_view(request: Request):
    with get_db() as conn:
        cur = conn.execute("SELECT * FROM routes ORDER BY id ASC")
        routes_list = [dict(row) for row in cur.fetchall()]

    serpapi_used = get_api_usage("serpapi")

    return templates.TemplateResponse(request=request, name="settings.html", context={
        "routes": routes_list,
        "settings": settings,
        "serpapi_used": serpapi_used,
        "serpapi_max": 100,
        "active_page": "settings"
    })

@app.post("/settings/route/save")
async def save_route(
    route_id: int = Form(0),
    origine: str = Form(...),
    destination: str = Form(...),
    type_trajet: str = Form("aller_simple"),
    dates_ou_mois: str = Form(...),
    passagers: int = Form(1),
    bagage: str = Form("cabine"),
    seuil_eur: float = Form(80.0),
    actif: int = Form(1),
    max_duree_heures: float = Form(12.0),
    max_escales: int = Form(1),
    max_escale_duree_heures: float = Form(4.0)
):
    with get_db() as conn:
        if route_id > 0:
            conn.execute("""
                UPDATE routes SET
                    origine = ?, destination = ?, type = ?, dates_ou_mois = ?,
                    passagers = ?, bagage = ?, seuil_eur = ?, actif = ?,
                    max_duree_heures = ?, max_escales = ?, max_escale_duree_heures = ?
                WHERE id = ?
            """, (origine.strip(), destination.strip(), type_trajet, dates_ou_mois.strip(),
                  passagers, bagage, seuil_eur, actif,
                  max_duree_heures, max_escales, max_escale_duree_heures, route_id))
        else:
            conn.execute("""
                INSERT INTO routes (origine, destination, type, dates_ou_mois, passagers, bagage, seuil_eur, actif,
                                    max_duree_heures, max_escales, max_escale_duree_heures)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (origine.strip(), destination.strip(), type_trajet, dates_ou_mois.strip(),
                  passagers, bagage, seuil_eur, actif,
                  max_duree_heures, max_escales, max_escale_duree_heures))
    return RedirectResponse("/settings?saved=1", status_code=303)

@app.post("/settings/route/delete")
async def delete_route(route_id: int = Form(...)):
    with get_db() as conn:
        conn.execute("DELETE FROM routes WHERE id = ?", (route_id,))
    return RedirectResponse("/settings?deleted=1", status_code=303)

@app.post("/settings/app/save")
async def save_app_settings(
    demo_mode: str = Form("0"),
    travelpayouts_token: str = Form(""),
    serpapi_api_key: str = Form(""),
    telegram_bot_token: str = Form(""),
    telegram_chat_id: str = Form(""),
    ntfy_topic: str = Form("volalerte_alertes"),
    channel_windows: str = Form(None),
    channel_telegram: str = Form(None),
    channel_ntfy: str = Form(None),
    daily_check_time: str = Form("09:00")
):
    channels = []
    if channel_windows:
        channels.append("windows")
    if channel_telegram:
        channels.append("telegram")
    if channel_ntfy:
        channels.append("ntfy")

    updates = {
        "DEMO_MODE": "1" if demo_mode == "1" else "0",
        "ALERT_CHANNELS": ",".join(channels),
        "NTFY_TOPIC": ntfy_topic.strip(),
        "DAILY_CHECK_TIME": daily_check_time.strip()
    }

    if travelpayouts_token and not travelpayouts_token.startswith("••"):
        updates["TRAVELPAYOUTS_TOKEN"] = travelpayouts_token.strip()
    if serpapi_api_key and not serpapi_api_key.startswith("••"):
        updates["SERPAPI_API_KEY"] = serpapi_api_key.strip()
    if telegram_bot_token and not telegram_bot_token.startswith("••"):
        updates["TELEGRAM_BOT_TOKEN"] = telegram_bot_token.strip()
    if telegram_chat_id and not telegram_chat_id.startswith("••"):
        updates["TELEGRAM_CHAT_ID"] = telegram_chat_id.strip()

    settings.update_env(updates)
    return RedirectResponse("/settings?config_saved=1", status_code=303)

@app.post("/api/run-now")
async def run_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(execute_daily_run)
    return {"status": "ok", "message": "Vérification lancée en arrière-plan"}

@app.post("/api/backup-now")
async def backup_now():
    backup_database()
    return {"status": "ok", "message": "Sauvegarde effectuée avec succès"}
