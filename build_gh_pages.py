"""
Génère la version statique complète et interactive de VolAlerte dans le dossier /docs
pour hébergement public sur GitHub Pages : https://paquereauman.github.io/VolAlerte/
"""
import os
import re
import shutil
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8765"
GH_PREFIX = "/VolAlerte"
DOCS_DIR = Path(__file__).resolve().parent / "docs"
STATIC_SRC = Path(__file__).resolve().parent / "app" / "web" / "static"


def fetch_html(path: str) -> str:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "VolAlerte-StaticBuilder/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


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

    # Form action on radar
    html = html.replace('action="/radar"', f'action="{GH_PREFIX}/radar/"')
    return html


RADAR_CLIENT_FILTER_JS = """
<script>
// Filtrage interactif côté client pour GitHub Pages (https://paquereauman.github.io/VolAlerte/radar/)
document.addEventListener("DOMContentLoaded", function() {
  const form = document.querySelector('form[action*="/radar"]');
  if (!form) return;

  const params = new URLSearchParams(window.location.search);
  const bagageMode = params.get("bagage_mode") || "cabine";
  const tripType = params.get("trip_type") || "oneway";

  // Rediriger vers la variante pré-calculée si bagage_mode ou trip_type change
  form.addEventListener("submit", function(e) {
    e.preventDefault();
    const fd = new FormData(form);
    const bm = fd.get("bagage_mode") || "cabine";
    const tt = fd.get("trip_type") || "oneway";
    const orig = fd.get("origin") || "CGO";
    const q = new URLSearchParams({origin: orig, trip_type: tt, bagage_mode: bm});

    let targetPage = "/VolAlerte/radar/";
    if (tt === "roundtrip") {
      targetPage = "/VolAlerte/radar/roundtrip/";
    } else if (bm === "soute_1") {
      targetPage = "/VolAlerte/radar/soute/";
    } else if (bm === "aucun" || bm === "sans") {
      targetPage = "/VolAlerte/radar/sans/";
    } else if (orig === "PKX" || orig === "PEK") {
      targetPage = "/VolAlerte/radar/pekin/";
    } else if (orig === "PVG" || orig === "SHA") {
      targetPage = "/VolAlerte/radar/shanghai/";
    } else if (orig === "XIY") {
      targetPage = "/VolAlerte/radar/xian/";
    }
    window.location.href = targetPage + "?" + q.toString();
  });
});
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


def build():
    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # .nojekyll pour GitHub Pages
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    # Copier les fichiers statiques
    static_dst = DOCS_DIR / "static"
    shutil.copytree(STATIC_SRC, static_dst)
    print("[OK] Fichiers statiques copiés dans docs/static/")

    # Pages principales
    save_page("index.html", fetch_html("/"))
    save_page("radar/index.html", fetch_html("/radar?bagage_mode=cabine&trip_type=oneway"), inject_radar_js=True)
    save_page("radar/soute/index.html", fetch_html("/radar?bagage_mode=soute_1&trip_type=oneway"), inject_radar_js=True)
    save_page("radar/sans/index.html", fetch_html("/radar?bagage_mode=aucun&trip_type=oneway"), inject_radar_js=True)
    save_page("radar/roundtrip/index.html", fetch_html("/radar?bagage_mode=cabine&trip_type=roundtrip"), inject_radar_js=True)
    save_page("radar/pekin/index.html", fetch_html("/radar?origin=PKX&bagage_mode=cabine"), inject_radar_js=True)
    save_page("radar/shanghai/index.html", fetch_html("/radar?origin=PVG&bagage_mode=cabine"), inject_radar_js=True)
    save_page("radar/xian/index.html", fetch_html("/radar?origin=XIY&bagage_mode=cabine"), inject_radar_js=True)
    save_page("alerts/index.html", fetch_html("/alerts"))
    save_page("settings/index.html", fetch_html("/settings"))

    for route_id in (1, 2, 3):
        try:
            save_page(f"route/{route_id}/index.html", fetch_html(f"/route/{route_id}"))
        except Exception as e:
            print(f"[WARN] route/{route_id}: {e}")


if __name__ == "__main__":
    build()
