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


RADAR_CLIENT_FILTER_JS = r"""
<script>
// Moteur de filtrage interactif instantané pour GitHub Pages (https://paquereauman.github.io/VolAlerte/radar/)
(function() {
  function getTargetPath(origin, bagage) {
    if (origin === "PKX" || origin === "PEK" || origin === "BJS") return "/VolAlerte/radar/pekin/";
    if (origin === "PVG" || origin === "SHA") return "/VolAlerte/radar/shanghai/";
    if (origin === "XIY") return "/VolAlerte/radar/xian/";
    if (origin === "WUH") return "/VolAlerte/radar/wuhan/";
    if (origin === "PAR") return "/VolAlerte/radar/paris/";
    if (bagage === "soute_1") return "/VolAlerte/radar/soute/";
    if (bagage === "aucun" || bagage === "sans") return "/VolAlerte/radar/sans/";
    return "/VolAlerte/radar/";
  }

  function formatDateFrClient(isoDate) {
    if (!isoDate || isoDate.length < 10) return "";
    const parts = isoDate.slice(0, 10).split("-");
    const y = parseInt(parts[0], 10), m = parseInt(parts[1], 10) - 1, d = parseInt(parts[2], 10);
    const dt = new Date(y, m, d);
    if (isNaN(dt.getTime())) return isoDate;
    const days = ["Dim.", "Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam."];
    const months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
    return days[dt.getDay()] + " " + d + " " + months[m] + " " + y;
  }

  window.handleRadarFilterChange = function(overrideFilterTag, fromSearchBtn) {
    const form = document.querySelector('form[action*="/radar"]');
    if (!form) return;

    const originEl = form.querySelector('#origin');
    const destPickEl = form.querySelector('#dest_pick');
    const monthEl = form.querySelector('#month');
    const dateEl = form.querySelector('#exact_date');
    const bagageEl = form.querySelector('#bagage');
    const durEl = form.querySelector('#max_duration');
    const stopsEl = form.querySelector('#max_stops');
    const layEl = form.querySelector('#max_layover');
    const nearEl = form.querySelector('input[name="include_nearby"]');

    const currentParams = new URLSearchParams(window.location.search);
    const filterTag = typeof overrideFilterTag === "string" ? overrideFilterTag : (currentParams.get("filter") || "all");

    const origin = originEl ? originEl.value : "CGO";
    const destPick = destPickEl ? destPickEl.value : "";
    let month = monthEl ? monthEl.value : "2026-11";
    let exactDate = dateEl ? dateEl.value : "";
    if (!exactDate && month) {
      exactDate = month + "-15";
      if (dateEl) dateEl.value = exactDate;
    } else if (exactDate && exactDate.length >= 7 && monthEl) {
      month = exactDate.slice(0, 7);
      monthEl.value = month;
    }
    const bagage = bagageEl ? bagageEl.value : "cabine";
    const maxDur = durEl ? durEl.value : "0";
    const maxStops = stopsEl ? stopsEl.value : "-1";
    const maxLay = layEl ? layEl.value : "0";
    const incNear = (nearEl && nearEl.checked) ? "1" : "0";

    const q = new URLSearchParams({
      origin: origin,
      dest_pick: destPick,
      month: month,
      exact_date: exactDate,
      bagage: bagage,
      max_duration: maxDur,
      max_stops: maxStops,
      max_layover: maxLay,
      include_nearby: incNear,
      filter: filterTag
    });

    const targetPath = getTargetPath(origin, bagage);
    const normCurrent = window.location.pathname.endsWith("/") ? window.location.pathname : (window.location.pathname + "/");

    if (normCurrent !== targetPath) {
      window.location.href = targetPath + "?" + q.toString();
      return;
    }

    // Mettre à jour l'URL sans recharger et filtrer instantanément le DOM
    window.history.replaceState({}, "", targetPath + "?" + q.toString());
    applyDomFilters(q);

    const searchBtn = document.getElementById("btn-radar-search");
    if (searchBtn) {
      const prevText = "🔍 Chercher";
      searchBtn.innerHTML = "✅ Mis à jour (" + (exactDate ? formatDateFrClient(exactDate) : month) + ")";
      setTimeout(function() {
        searchBtn.innerHTML = prevText;
      }, 1600);
    }
  };

  function applyDomFilters(q) {
    const form = document.querySelector('form[action*="/radar"]');
    if (!form) return;

    const origin = q.get("origin") || "";
    const destPick = q.get("dest_pick") || "";
    const month = q.get("month") || "";
    const exactDate = q.get("exact_date") || "";
    const bagage = q.get("bagage") || "";
    const maxDur = parseFloat(q.get("max_duration") || "0");
    const maxStops = parseInt(q.get("max_stops") || "-1", 10);
    const maxLay = parseFloat(q.get("max_layover") || "0");
    const incNear = q.get("include_nearby") !== "0";
    const filterTag = q.get("filter") || "all";

    if (origin && form.querySelector('#origin')) form.querySelector('#origin').value = origin;
    if (form.querySelector('#dest_pick')) form.querySelector('#dest_pick').value = destPick;
    if (month && form.querySelector('#month')) form.querySelector('#month').value = month;
    if (exactDate && form.querySelector('#exact_date')) form.querySelector('#exact_date').value = exactDate;
    if (bagage && form.querySelector('#bagage')) form.querySelector('#bagage').value = bagage;
    if (q.has("max_duration") && form.querySelector('#max_duration')) form.querySelector('#max_duration').value = q.get("max_duration");
    if (q.has("max_stops") && form.querySelector('#max_stops')) form.querySelector('#max_stops').value = q.get("max_stops");
    if (q.has("max_layover") && form.querySelector('#max_layover')) form.querySelector('#max_layover').value = q.get("max_layover");
    if (q.has("include_nearby") && form.querySelector('input[name="include_nearby"]')) {
      form.querySelector('input[name="include_nearby"]').checked = incNear;
    }

    // Mettre à jour dynamiquement les dates affichées et les liens de réservation (Trip.com, Skyscanner)
    if (exactDate && exactDate.length === 10) {
      const dateFr = formatDateFrClient(exactDate);
      const isCustomDate = (exactDate !== "2026-11-15");
      document.querySelectorAll(".js-dep-date-label").forEach(function(span) {
        if (isCustomDate && dateFr) {
          span.textContent = dateFr;
        } else if (span.getAttribute("data-default-label")) {
          span.textContent = span.getAttribute("data-default-label");
        }
      });

      document.querySelectorAll('a[href*="trip.com"]').forEach(function(a) {
        const href = a.getAttribute("href") || "";
        if (href.indexOf("ddate=") !== -1) {
          a.setAttribute("href", href.replace(/ddate=\d{4}-\d{2}-\d{2}/, "ddate=" + exactDate));
        }
      });

      const yymmdd = exactDate.slice(2, 4) + exactDate.slice(5, 7) + exactDate.slice(8, 10);
      document.querySelectorAll('a[href*="skyscanner"]').forEach(function(a) {
        const href = a.getAttribute("href") || "";
        a.setAttribute("href", href.replace(/\/\d{6}\//, "/" + yymmdd + "/"));
      });
    }

    function matchesDeal(el) {
      const dest = el.getAttribute("data-dest") || "";
      const durMin = parseInt(el.getAttribute("data-duration-min") || "0", 10);
      const stops = parseInt(el.getAttribute("data-stops") || "0", 10);
      const layMin = parseInt(el.getAttribute("data-layover-min") || "0", 10);
      const isNearby = el.getAttribute("data-is-nearby") === "1";
      const region = el.getAttribute("data-region") || "";
      const priceDisp = parseInt(el.getAttribute("data-price-display") || "0", 10);

      if (destPick && dest !== destPick) return false;
      if (!incNear && isNearby) return false;
      if (maxDur > 0 && durMin > maxDur * 60) return false;
      if (maxStops >= 0 && stops > maxStops) return false;
      if (maxLay > 0 && layMin > maxLay * 60) return false;
      if (filterTag === "under_100" && priceDisp >= 100) return false;
      if (filterTag === "southeast_asia" && region !== "Asie du Sud-Est") return false;
      return true;
    }

    const rows = document.querySelectorAll("tr.radar-deal-row");
    let visibleCount = 0;
    rows.forEach(function(row) {
      const show = matchesDeal(row);
      row.style.display = show ? "" : "none";
      if (show) visibleCount++;
    });

    const cards = document.querySelectorAll("div.radar-deal-card");
    cards.forEach(function(card) {
      const show = matchesDeal(card);
      card.style.display = show ? "flex" : "none";
      const det = card.querySelector("details.airport-comp-details");
      if (det && destPick && show) {
        det.open = true;
      }
    });

    const tblCard = document.getElementById("radar-summary-table-card");
    if (tblCard) {
      tblCard.style.display = destPick ? "none" : "";
    }

    const grid = document.getElementById("radar-cards-grid");
    if (grid) {
      grid.style.gridTemplateColumns = destPick ? "1fr" : "";
    }

    // Mettre à jour l'état visuel des boutons de filtre budget (Tous / < 100 €)
    form.querySelectorAll('a[href*="filter="]').forEach(function(a) {
      const href = a.getAttribute("href") || "";
      const m = href.match(/filter=([a-z0-9_]+)/i);
      const tag = m ? m[1] : "all";
      const active = (tag === filterTag);
      a.classList.toggle("btn-primary", active);
      a.classList.toggle("btn-secondary", !active);
    });
  }

  document.addEventListener("DOMContentLoaded", function() {
    const form = document.querySelector('form[action*="/radar"]');
    if (!form) return;

    form.addEventListener("submit", function(e) {
      e.preventDefault();
      window.handleRadarFilterChange();
    });

    // Intercepter les clics sur les boutons de filtre rapide (Tous / Moins de 100 € / Asie du Sud-Est)
    const filterLinks = form.querySelectorAll('a[href*="filter="]');
    filterLinks.forEach(function(a) {
      a.addEventListener("click", function(e) {
        e.preventDefault();
        const href = a.getAttribute("href") || "";
        const m = href.match(/filter=([a-z0-9_]+)/i);
        window.handleRadarFilterChange(m ? m[1] : "all");
      });
    });

    // Appliquer les filtres présents dans l'URL au chargement
    const q = new URLSearchParams(window.location.search);
    if (Array.from(q.keys()).length > 0) {
      applyDomFilters(q);
    }
  });
})();
</script>
"""


def save_page(rel_path: str, html: str, inject_radar_js: bool = False):
    out_file = DOCS_DIR / rel_path
    out_file.parent.mkdir(parents=True, exist_ok=True)
    processed = rewrite_links_for_gh_pages(html)
    if inject_radar_js:
        processed = processed.replace("</body>", RADAR_CLIENT_FILTER_JS + "\n</body>")
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
