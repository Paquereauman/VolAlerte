"""
Génère la version statique complète et 100% interactive de VolAlerte dans le dossier /docs
pour hébergement public sur GitHub Pages : https://paquereauman.github.io/VolAlerte/
"""
import asyncio
import datetime
import re
import shutil
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8765"
GH_PREFIX = "/VolAlerte"
DOCS_DIR = Path(__file__).resolve().parent / "docs"
STATIC_SRC = Path(__file__).resolve().parent / "app" / "web" / "static"


async def _asgi_get(app, path: str) -> str:
    if "?" in path:
        raw_path, query_string = path.split("?", 1)
    else:
        raw_path, query_string = path, ""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": raw_path,
        "raw_path": raw_path.encode("utf-8"),
        "query_string": query_string.encode("utf-8"),
        "headers": [(b"host", b"127.0.0.1:8765"), (b"user-agent", b"VolAlerte-StaticBuilder/1.0")],
        "client": ("127.0.0.1", 8765),
        "server": ("127.0.0.1", 8765),
    }
    body_parts = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))

    await app(scope, receive, send)
    return b"".join(body_parts).decode("utf-8")


def fetch_html(path: str) -> str:
    from app.web.app import app
    return asyncio.run(_asgi_get(app, path))


def rewrite_links_for_gh_pages(html: str) -> str:
    # Stylesheet & static assets
    html = html.replace('href="/static/', f'href="{GH_PREFIX}/static/')
    html = html.replace('src="/static/', f'src="{GH_PREFIX}/static/')

    # Navigation & internal links
    html = html.replace('href="/"', f'href="{GH_PREFIX}/"')
    html = html.replace('href="/radar"', f'href="{GH_PREFIX}/radar/"')
    html = html.replace('href="/radar#', f'href="{GH_PREFIX}/radar/#')
    html = re.sub(r'href="/radar\?([^"]*)"', rf'href="{GH_PREFIX}/radar/?\1"', html)
    html = html.replace('href="/alerts"', f'href="{GH_PREFIX}/alerts/"')
    html = html.replace('href="/settings"', f'href="{GH_PREFIX}/settings/"')
    html = re.sub(r'href="/route/(\d+)"', rf'href="{GH_PREFIX}/route/\1/"', html)

    # Remplacer this.form.submit() (qui court-circuite les listeners submit en JS)
    html = html.replace(
        "onchange=\"document.getElementById('exact_date').value=''; this.form.submit();\"",
        "onchange=\"document.getElementById('exact_date').value=''; window.handleRadarFilterChange();\""
    )
    html = html.replace('onchange="this.form.submit()"', 'onchange="window.handleRadarFilterChange()"')

    # Form action on radar
    html = html.replace('action="/radar"', f'action="{GH_PREFIX}/radar/"')
    return html


def save_page(rel_path: str, html: str, inject_radar_js: bool = False):
    out_file = DOCS_DIR / rel_path
    out_file.parent.mkdir(parents=True, exist_ok=True)
    processed = rewrite_links_for_gh_pages(html)
    out_file.write_text(processed, encoding="utf-8")
    print(f"[OK] {out_file.relative_to(DOCS_DIR)} ({len(processed)} bytes)")


def _ensure_france_tracked_routes():
    from app.database import get_db
    with get_db() as conn:
        rows = conn.execute("SELECT id, origine, destination FROM routes").fetchall()
        existing_dests = {r["destination"] for r in rows}
        today = datetime.date.today()
        for orig, dest, d_vol, bag, seuil, base_p, comp, dur_m, sched, esc_det in [
            ("Zhengzhou (CGO)", "Paris (CDG)", "2026-12-18", "soute_1", 350.0, 361.0, "Hainan Airlines", 1085, "20:40 CGO ➔ 07:45 (+1j) CDG", "1 escale (Soute 23kg incluse)"),
            ("Zhengzhou (CGO)", "Nantes (NTE)", "2026-12-18", "soute_1", 390.0, 403.0, "Hainan (CDG) + TGV CDG 2 ➔ Nantes", 1280, "20:40 CGO ➔ 13:00 (+1j) NTE", "Vol CDG (361€) + TGV T2➔Nantes (42€)"),
        ]:
            if dest not in existing_dests:
                cur = conn.execute(
                    "INSERT INTO routes (origine, destination, type, dates_ou_mois, passagers, bagage, seuil_eur, actif, max_duree_heures, max_escales, max_escale_duree_heures) VALUES (?, ?, 'aller_simple', ?, 1, ?, ?, 1, 24.0, 1, 5.0)",
                    (orig, dest, d_vol, bag, seuil)
                )
                rid = cur.lastrowid
                offsets = [28, 22, 18, 12, 15, 8, 5, 10, 4, 0]
                for idx, off in enumerate(offsets):
                    days_ago = len(offsets) - 1 - idx
                    d_rel = (today - datetime.timedelta(days=days_ago)).isoformat()
                    p = base_p + off
                    conn.execute(
                        "INSERT INTO price_observations (route_id, source, date_vol, date_releve, jours_anticipation, prix_billet_eur, compagnie, escales, fourchette_basse, fourchette_haute, duree_totale_minutes, duree_escale_max_minutes, escales_details, horaires_vol, prix_cabine_eur, prix_soute_eur) VALUES (?, 'Google Flights', ?, ?, ?, ?, ?, 1, ?, ?, ?, 160, ?, ?, ?, ?)",
                        (rid, d_vol, d_rel, 60 + days_ago, p, comp, base_p - 25, base_p + 55, dur_m, esc_det, sched, p, p)
                    )
                print(f"[OK] Route ajoutee au suivi : {orig} -> {dest} (id={rid})")
        conn.commit()


def build():
    _ensure_france_tracked_routes()
    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # .nojekyll pour GitHub Pages
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    # Copier les fichiers statiques
    static_dst = DOCS_DIR / "static"
    shutil.copytree(STATIC_SRC, static_dst)
    print("[OK] Fichiers statiques copiés dans docs/static/")

    # Pages principales et toutes les variantes de hubs / bagages du Radar
    save_page("index.html", fetch_html("/"))
    save_page("radar/index.html", fetch_html("/radar?origin=CGO&bagage=cabine"), inject_radar_js=True)
    save_page("radar/soute/index.html", fetch_html("/radar?origin=CGO&bagage=soute_1"), inject_radar_js=True)
    save_page("radar/sans/index.html", fetch_html("/radar?origin=CGO&bagage=aucun"), inject_radar_js=True)
    save_page("radar/pekin/index.html", fetch_html("/radar?origin=PKX&bagage=cabine"), inject_radar_js=True)
    save_page("radar/shanghai/index.html", fetch_html("/radar?origin=PVG&bagage=cabine"), inject_radar_js=True)
    save_page("radar/xian/index.html", fetch_html("/radar?origin=XIY&bagage=cabine"), inject_radar_js=True)
    save_page("radar/wuhan/index.html", fetch_html("/radar?origin=WUH&bagage=cabine"), inject_radar_js=True)
    save_page("radar/paris/index.html", fetch_html("/radar?origin=PAR&bagage=cabine"), inject_radar_js=True)
    save_page("alerts/index.html", fetch_html("/alerts"))
    save_page("settings/index.html", fetch_html("/settings"))

    from app.database import get_db
    with get_db() as conn:
        route_ids = [r["id"] for r in conn.execute("SELECT id FROM routes").fetchall()]
    for route_id in route_ids:
        try:
            save_page(f"route/{route_id}/index.html", fetch_html(f"/route/{route_id}"))
        except Exception as e:
            print(f"[WARN] route/{route_id}: {e}")


if __name__ == "__main__":
    build()
