"""Paso 2: arma la lista de búsquedas a partir de data/discovery.json (sin requests).

Uso: python -m scraper.plan

Partición (solo primera página de cada búsqueda = 48 avisos como máximo):
  marca x vendedor            -> si tiene <= 48 avisos, es una búsqueda final ("hoja")
  marca x vendedor x modelo   -> se conoce al bajar la página marca x vendedor
  ... x rango de año          -> para modelos con > 48 avisos, rangos armados con
                                 los conteos por año que informa el propio sitio
Los niveles 2 y 3 dependen de conteos que se ven recién en la corrida, así que
acá se estiman repartiendo los avisos del modelo según el % dueño/concesionaria
de la marca. El nivel 1 es exacto.
Salida: data/plan_busquedas.csv
"""
import csv
import math

from scraper.discover import OUT_FILE as DISCOVERY_FILE
from scraper.pages import DATA_DIR, load_json

PAGE_SIZE = 48
YEAR_RANGE_FILL = 42  # avisos promedio por rango de año (no siempre se llena a 48)
BUDGET = 2000
PLAN_FILE = DATA_DIR / "plan_busquedas.csv"


def build_plan(discovery):
    rows = []
    for b in discovery["marcas"]:
        total = b["total_informado"] or 0
        if not b["vendedor"]:
            # Sin filtro dueño/concesionaria: la página de marca ya está en caché.
            rows.append({"nivel": 0, "marca": b["marca"], "vendedor": "", "modelo": "",
                         "avisos": total, "estimado": False, "requests": 0,
                         "accion": "ya en caché (sin tipo de vendedor)", "url": b["url"]})
            continue
        for vendedor, info in b["vendedor"].items():
            n = info["results"] or 0
            if n == 0:
                continue
            leaf = n <= PAGE_SIZE
            rows.append({"nivel": 1, "marca": b["marca"], "vendedor": vendedor, "modelo": "",
                         "avisos": n, "estimado": False, "requests": 1,
                         "accion": "hoja" if leaf else "se parte por modelo", "url": info["url"]})
            if leaf:
                continue
            share = n / total
            for m in b["modelos"]:
                est = (m["results"] or 0) * share
                if est < 0.5 and not ((m["results"] or 0) == 1 and share >= 0.5):
                    continue
                if est <= PAGE_SIZE:
                    req, accion = 1, "hoja"
                else:
                    req, accion = 1 + math.ceil(est / YEAR_RANGE_FILL), "se parte por año"
                rows.append({"nivel": 2, "marca": b["marca"], "vendedor": vendedor,
                             "modelo": m["modelo"], "avisos": round(est, 1), "estimado": True,
                             "requests": req, "accion": accion, "url": ""})
    return rows


def main():
    discovery = load_json(DISCOVERY_FILE, None)
    if discovery is None:
        raise SystemExit("Falta data/discovery.json: correr primero python -m scraper.discover")
    progress = load_json(DATA_DIR / "progress.json", {"requests_total": 0})
    rows = build_plan(discovery)

    with open(PLAN_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    done = progress["requests_total"]
    lvl1 = sum(r["requests"] for r in rows if r["nivel"] == 1)
    lvl2 = [r for r in rows if r["nivel"] == 2]
    split_year = [r for r in lvl2 if r["accion"] == "se parte por año"]
    tail = [r for r in lvl2 if r["accion"] == "hoja" and r["avisos"] <= 2]
    total_run = sum(r["requests"] for r in rows)
    print(f"Avisos de usados informados: {discovery['total_informado']}")
    print(f"Requests ya hechos (descubrimiento): {done}")
    print(f"Nivel 1 marca x vendedor (exacto): {lvl1} búsquedas, "
          f"{sum(1 for r in rows if r['nivel'] == 1 and r['accion'] == 'hoja')} son hojas")
    print(f"Nivel 2 marca x vendedor x modelo (estimado): {len(lvl2)} búsquedas")
    print(f"Nivel 3 rangos de año (estimado): {sum(r['requests'] - 1 for r in split_year)} búsquedas "
          f"para {len(split_year)} modelo x vendedor con > {PAGE_SIZE} avisos")
    print(f"Cola larga (modelo x vendedor con <= 2 avisos): {len(tail)} requests, "
          f"~{sum(r['avisos'] for r in tail):.0f} avisos")
    print(f"TOTAL corrida estimado: {total_run} -> proyecto: {done + total_run} de {BUDGET}")
    print(f"Lista guardada en {PLAN_FILE}")


if __name__ == "__main__":
    main()
