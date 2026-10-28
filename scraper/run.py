"""Paso 3: corrida de scraping (solo extracción + deduplicación).

Uso:
  python -m scraper.run                    # corrida completa
  python -m scraper.run --max-busquedas 3  # prueba chica (Paso 4)

Recorre un árbol de búsquedas, siempre la PRIMERA página (48 avisos máx.):
  nivel 1: marca x vendedor        (URLs de data/discovery.json)
  nivel 2: ... x modelo            (links del filtro MODEL de la página nivel 1)
  nivel 3: ... x rango de año      (filtro VEHICLE_YEAR + url_template del sitio)
Una búsqueda con <= 48 avisos es una hoja; si tiene más, se parte en el nivel
siguiente. Las búsquedas se procesan de mayor a menor (cola de prioridad), así
si la guardia de presupuesto corta, lo que queda afuera es la cola larga.

Reanudable: cada página queda en caché (data/raw/pages/). Al relanzar, lo ya
bajado se relee del disco sin requests y la corrida sigue donde quedó.
"""
import argparse
import csv
import heapq
import itertools
import logging
import sys
from collections import defaultdict
from datetime import datetime

from scraper.client import MAX_REQUESTS, ROBOTS_HOSTS, Blocked, BudgetExceeded, Disallowed
from scraper.discover import OUT_FILE as DISCOVERY_FILE
from scraper.pages import (DATA_DIR, INDEX_FILE, get_page, load_json, load_progress, new_client,
                           save_json, save_progress, setup_logging)
from scraper.parse import COLUMNS, clean_url, parse_card, parse_page

PAGE_SIZE = 48
BUDGET_MARGIN = 50  # la corrida frena sola cuando quedan menos de 50 requests del tope
CSV_FILE = DATA_DIR / "autos_raw.csv"
SEARCHES_FILE = DATA_DIR / "busquedas.csv"
SAVE_EVERY = 25

log = logging.getLogger("run")


class StopRun(Exception):
    """Fin anticipado ordenado (guardia de presupuesto o límite de prueba)."""


def year_ranges(year_filter):
    """Agrupa años consecutivos en rangos de <= 48 avisos, con los conteos del sitio.

    Devuelve [(desde, hasta, avisos, url)]. Un año que solo ya supera 48 queda
    como rango propio (cobertura parcial, se registra en el log).
    """
    years = sorted(
        (int(v["name"]), v["results"] or 0, v["url"])
        for v in year_filter["values"] if (v["name"] or "").isdigit() and len(v["name"]) == 4
    )
    template = (year_filter.get("url_templates") or {}).get("from_and_to")
    ranges, current = [], []
    for year in years:
        if current and sum(c for _, c, _ in current) + year[1] > PAGE_SIZE:
            ranges.append(current)
            current = []
        current.append(year)
    if current:
        ranges.append(current)

    out = []
    for group in ranges:
        start, end = group[0][0], group[-1][0]
        count = sum(c for _, c, _ in group)
        if start == end:
            url = group[0][2]  # link del propio sitio para un solo año
        elif template:
            url = clean_url(template.replace("$from", str(start)).replace("$to", str(end)))
        else:
            out.extend((y, y, c, u) for y, c, u in group)  # sin plantilla: año por año
            continue
        out.append((start, end, count, url))
    return out


class Run:
    def __init__(self, max_new):
        self.progress = load_progress()
        self.client = new_client(self.progress)
        self.discovery = load_json(DISCOVERY_FILE, None)
        if self.discovery is None:
            raise SystemExit("Falta data/discovery.json: correr primero python -m scraper.discover")
        self.models = {b["marca"]: [m["modelo"] for m in b["modelos"]] for b in self.discovery["marcas"]}
        self.max_new = max_new
        self.new_fetches = 0
        self.rows = {}           # item_id -> fila (deduplicación)
        self.searches = []       # estadísticas por búsqueda (data/busquedas.csv)
        self.heap, self.seq = [], itertools.count()
        self.seen_urls = set()
        self.anio_scraping = datetime.now().year

    # --- cola ----------------------------------------------------------------
    def push(self, node):
        if node["url"] in self.seen_urls:
            return
        self.seen_urls.add(node["url"])
        heapq.heappush(self.heap, (-(node["esperado"] or 0), next(self.seq), node))

    def seed(self):
        for b in self.discovery["marcas"]:
            if not b["vendedor"]:
                # Marcas mínimas sin filtro de vendedor: su página ya está en caché.
                self.push({"nivel": 0, "marca": b["marca"], "modelo": None, "vendedor": None,
                           "esperado": b["total_informado"], "url": b["url"],
                           "label": f"{b['marca']} (sin filtro vendedor)"})
                continue
            for vendedor, info in b["vendedor"].items():
                if info["results"]:
                    self.push({"nivel": 1, "marca": b["marca"], "modelo": None, "vendedor": vendedor,
                               "esperado": info["results"], "url": info["url"],
                               "label": f"{b['marca']} | {vendedor}"})

    # --- una búsqueda ----------------------------------------------------------
    def fetch(self, url):
        cached = url in load_json(INDEX_FILE, {})
        if not cached:
            if self.client.request_count >= MAX_REQUESTS - BUDGET_MARGIN:
                raise StopRun(f"guardia de presupuesto: {self.client.request_count} requests "
                              f"(tope {MAX_REQUESTS}, margen {BUDGET_MARGIN})")
            if self.max_new is not None and self.new_fetches >= self.max_new:
                raise StopRun(f"prueba chica: límite de {self.max_new} búsquedas nuevas alcanzado")
            self.new_fetches += 1
        html = get_page(self.client, url)
        fetched_at = load_json(INDEX_FILE, {}).get(url, {}).get("fetched_at", "")
        return html, fetched_at[:10], cached

    def process(self, node):
        url = node["url"]
        if not self.client.allowed(url):
            log.warning("PROHIBIDO por robots.txt, se saltea: %s", url)
            return
        html, fecha, cached = self.fetch(url)
        page = parse_page(html)
        if page is None:
            log.warning("%s: página sin JSON de resultados (%s)", node["label"], url)
            return

        total = page["total"] or 0
        new = 0
        for card in page["cards"]:
            row = parse_card(card, node["marca"], node["modelo"], node["vendedor"], node["label"],
                             fecha, self.anio_scraping, self.models.get(node["marca"], ()))
            old = self.rows.get(row["item_id"])
            # Si el aviso aparece en varias búsquedas, queda la más específica.
            if old is None:
                new += 1
            if old is None or node["nivel"] > old["_nivel"]:
                row["_nivel"] = node["nivel"]
                self.rows[row["item_id"]] = row

        leaf = total <= PAGE_SIZE
        children = [] if leaf else self.children(node, page)
        if not leaf and not children:
            log.warning("%s: %d avisos y no se puede partir más: cobertura parcial", node["label"], total)
        self.searches.append({"busqueda": node["label"], "nivel": node["nivel"], "url": url,
                              "total_informado": total, "en_pagina": len(page["cards"]),
                              "nuevos": new, "hoja": leaf or not children,
                              "desde_cache": cached})
        self.progress["busquedas_hechas"][url] = {"total_informado": total, "en_pagina": len(page["cards"])}
        log.info("%s | informados %d | en página %d | nuevos %d | acumulado %d | requests %d%s",
                 node["label"], total, len(page["cards"]), new, len(self.rows),
                 self.client.request_count, " (caché)" if cached else "")
        for child in children:
            self.push(child)

    def children(self, node, page):
        filters = page["filters"]
        if node["nivel"] == 1 and "MODEL" in filters:
            values = filters["MODEL"]["values"]
            missing = page["total"] - sum(v["results"] or 0 for v in values)
            if missing > 0:
                log.info("%s: %d avisos sin modelo en el filtro (quedan solo en esta página)",
                         node["label"], missing)
            return [{"nivel": 2, "marca": node["marca"], "modelo": v["name"], "vendedor": node["vendedor"],
                     "esperado": v["results"], "url": v["url"],
                     "label": f"{node['marca']} | {node['vendedor']} | {v['name']}"}
                    for v in values if v["url"]]
        if node["nivel"] == 2 and "VEHICLE_YEAR" in filters:
            return [{"nivel": 3, "marca": node["marca"], "modelo": node["modelo"], "vendedor": node["vendedor"],
                     "esperado": count, "url": url,
                     "label": f"{node['label']} | {start}" + (f"-{end}" if end != start else "")}
                    for start, end, count, url in year_ranges(filters["VEHICLE_YEAR"])]
        return []

    # --- salida ----------------------------------------------------------------
    def save(self):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(self.rows.values())
        if self.searches:
            with open(SEARCHES_FILE, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(self.searches[0]))
                w.writeheader()
                w.writerows(self.searches)
        save_progress(self.progress, self.client)

    def coverage(self):
        total = self.discovery["total_informado"]
        got = len(self.rows)
        log.info("=== Cobertura: %d avisos obtenidos de %d informados (%.1f%%) ===",
                 got, total, 100 * got / total if total else 0)
        by_brand = defaultdict(int)
        for r in self.rows.values():
            by_brand[r["marca"]] += 1
        brands = sorted(self.discovery["marcas"], key=lambda b: -(b["total_informado"] or 0))[:15]
        log.info("%-16s %10s %10s %7s", "marca", "informados", "obtenidos", "%")
        for b in brands:
            t = b["total_informado"] or 0
            log.info("%-16s %10d %10d %6.1f%%", b["marca"], t, by_brand[b["marca"]], 100 * by_brand[b["marca"]] / t if t else 0)

    def main(self):
        log.info("=== Corrida (requests previos: %d, tope %d, margen %d) ===",
                 self.client.request_count, MAX_REQUESTS, BUDGET_MARGIN)
        status = 0
        try:
            for host in ROBOTS_HOSTS:
                self.client.load_robots(host)
            self.seed()
            done = 0
            while self.heap:
                _, _, node = heapq.heappop(self.heap)
                self.process(node)
                done += 1
                if done % SAVE_EVERY == 0:
                    self.save()
            log.info("Cola terminada: no quedan búsquedas pendientes.")
        except StopRun as e:
            log.warning("Corrida detenida: %s. Pendientes en cola: %d", e, len(self.heap))
        except Blocked as e:
            log.error("FRENADO por bloqueo repetido: %s. Se guardó el progreso.", e)
            status = 2
        except BudgetExceeded as e:
            log.error("FRENADO: %s", e)
            status = 2
        except Disallowed as e:
            log.error("URL prohibida inesperada: %s", e)
            status = 2
        finally:
            self.save()
            self.coverage()
            log.info("Requests totales del proyecto: %d. CSV: %s (%d filas)",
                     self.client.request_count, CSV_FILE, len(self.rows))
        sys.exit(status)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-busquedas", type=int, default=None,
                    help="cantidad máxima de búsquedas NUEVAS (no en caché); para la prueba chica")
    args = ap.parse_args()
    setup_logging()
    Run(args.max_busquedas).main()


if __name__ == "__main__":
    main()
