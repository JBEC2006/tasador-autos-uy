"""Paso 0: prueba de factibilidad con UNA sola página de búsqueda.

Uso: python -m scraper.feasibility
"""
import logging
import sys
from datetime import datetime

from scraper.client import RAW_DIR, ROBOTS_HOSTS, Blocked, Disallowed, PoliteClient

URL = "https://autos.mercadolibre.com.uy/volkswagen/gol/"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    client = PoliteClient()
    for host in ROBOTS_HOSTS:
        client.load_robots(host)
    print("Crawl-delay grupo *:", {h: client.crawl_delay(h) for h in ROBOTS_HOSTS})

    try:
        resp = client.get(URL)
    except Disallowed:
        sys.exit(f"{URL} está prohibida por robots.txt; no se pidió.")
    except Blocked as e:
        sys.exit(f"BLOQUEADO: {e}")

    out = RAW_DIR / f"feasibility_vw_gol_{datetime.now():%Y%m%d_%H%M%S}.html"
    out.write_text(resp.text, encoding="utf-8")

    html = resp.text
    print("HTTP:", resp.status_code)
    print("URL final:", resp.url)
    print("Redirecciones:", [(r.status_code, r.headers.get("Location")) for r in resp.history] or "ninguna")
    print("Tamaño HTML:", len(html))
    print("Señales de muro (captcha / account-verification):",
          any(m in html.lower() for m in ("captcha", "account-verification")))
    print("Señales de avisos:", {
        "ui-search-layout__item": html.count("ui-search-layout__item"),
        "MLU- ids": html.count("MLU"),
        "__PRELOADED_STATE__": "__PRELOADED_STATE__" in html,
        "application/ld+json": html.count("application/ld+json"),
    })
    print("Requests totales:", client.request_count)
    print("Guardado en:", out)


if __name__ == "__main__":
    main()
