"""Descubrimiento de marcas y modelos desde los filtros del propio sitio.

Uso: python -m scraper.discover

Requests: 4 robots.txt + 1 página raíz (+1 si existe un filtro "Usado" permitido)
+ 1 por marca. Las páginas quedan en caché: si se corta, al relanzarlo no se
vuelven a pedir las que ya se bajaron.
Salida: data/discovery.json (marcas, modelos y conteos informados por el sitio).
"""
import logging
import sys
import unicodedata
from datetime import datetime

from scraper.client import ROBOTS_HOSTS, Blocked, BudgetExceeded, Disallowed
from scraper.pages import DATA_DIR, get_page, load_progress, new_client, save_json, save_progress, setup_logging
from scraper.parse import parse_page

ROOT_URL = "https://autos.mercadolibre.com.uy/"
OUT_FILE = DATA_DIR / "discovery.json"
PAGE_SIZE = 48

log = logging.getLogger("discover")


def plain(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def find_used_filter(filters):
    """Valor 'Usado' de algún filtro de condición, si el sitio lo ofrece."""
    for fid, flt in filters.items():
        for v in flt["values"]:
            if plain(v["name"]) in ("usado", "usados") and v["url"]:
                return fid, v
    return None, None


def seller_counts(filters):
    out = {}
    for v in filters.get("seller_type", {}).get("values", []):
        if v["url"] and "/dueno" in v["url"]:
            out["particular"] = {"results": v["results"], "url": v["url"]}
        elif v["url"] and "/concesionaria" in v["url"]:
            out["concesionaria"] = {"results": v["results"], "url": v["url"]}
    return out


def stop(progress, client, reason):
    save_progress(progress, client)
    log.error("FRENADO: %s. Progreso guardado (requests totales: %d).", reason, client.request_count)
    sys.exit(2)


def main():
    setup_logging()
    progress = load_progress()
    client = new_client(progress)
    log.info("=== Descubrimiento (requests previos del proyecto: %d) ===", client.request_count)

    try:
        for host in ROBOTS_HOSTS:
            client.load_robots(host)

        root = parse_page(get_page(client, ROOT_URL))
        if root is None:
            stop(progress, client, "la página raíz no trae el JSON de resultados")
        log.info("Raíz: %s avisos informados. Filtros: %s", root["total"], ", ".join(root["filters"]))

        base_url, base = ROOT_URL, root
        fid, used = find_used_filter(root["filters"])
        if used is None:
            log.info("No hay filtro 'Usado' en la raíz: se usará el flag de condición.")
        elif not client.allowed(used["url"]):
            log.warning("Filtro 'Usado' (%s) PROHIBIDO por robots.txt: %s", fid, used["url"])
        else:
            log.info("Filtro 'Usado' permitido (%s, %s avisos): %s", fid, used["results"], used["url"])
            base_url, base = used["url"], parse_page(get_page(client, used["url"]))

        brands = base["filters"].get("BRAND", {}).get("values", [])
        brand_sum = sum(b["results"] or 0 for b in brands)
        log.info("Marcas en el filtro: %d, suman %d avisos de %s informados%s",
                 len(brands), brand_sum, base["total"],
                 "" if brand_sum == base["total"] else " (OJO: la lista podría estar truncada)")

        out = {"fecha": datetime.now().isoformat(timespec="seconds"), "base_url": base_url,
               "total_informado": base["total"], "filtro_usado": used, "marcas": []}
        for i, b in enumerate(brands, 1):
            if not client.allowed(b["url"]):
                log.warning("Marca %s PROHIBIDA por robots.txt: %s", b["name"], b["url"])
                continue
            page = parse_page(get_page(client, b["url"]))
            if page is None:
                log.warning("Marca %s: la página no trae el JSON de resultados", b["name"])
                continue
            models = page["filters"].get("MODEL", {}).get("values", [])
            out["marcas"].append({
                "marca": b["name"], "url": b["url"], "total_informado": page["total"],
                "vendedor": seller_counts(page["filters"]),
                "modelos": [{"modelo": m["name"], "results": m["results"], "url": m["url"]} for m in models],
            })
            log.info("[%d/%d] %s: %s avisos, %d modelos (requests: %d)",
                     i, len(brands), b["name"], page["total"], len(models), client.request_count)
            save_json(OUT_FILE, out)
            save_progress(progress, client)
    except Blocked as e:
        stop(progress, client, f"bloqueo repetido ({e})")
    except BudgetExceeded as e:
        stop(progress, client, str(e))
    except Disallowed as e:
        stop(progress, client, f"URL prohibida por robots.txt: {e}")

    save_json(OUT_FILE, out)
    save_progress(progress, client)
    n_models = sum(len(m["modelos"]) for m in out["marcas"])
    big = sum(1 for m in out["marcas"] for x in m["modelos"] if (x["results"] or 0) > PAGE_SIZE)
    log.info("Listo: %d marcas, %d modelos (%d con más de %d avisos). Requests totales: %d. Guardado en %s",
             len(out["marcas"]), n_models, big, PAGE_SIZE, client.request_count, OUT_FILE)


if __name__ == "__main__":
    main()
