"""Extracción de datos desde el HTML guardado de una página de búsqueda.

Los avisos y los filtros vienen en un JSON embebido:
<script id="__NORDIC_RENDERING_CTX__"> _n.ctx.r = {...}; ... </script>
Se usa ese JSON (no selectores CSS) porque trae precio numérico y moneda
por separado, y es mucho más estable que las clases CSS del sitio.
"""
import json
import re
import unicodedata

from bs4 import BeautifulSoup

PREFIX = "_n.ctx.r="

COLUMNS = [
    "item_id", "url", "titulo", "marca", "modelo", "modelo_origen", "version", "anio", "km",
    "precio", "moneda", "barrio", "departamento", "tipo_vendedor", "tienda_oficial",
    "transmision_titulo", "combustible_titulo", "motor_titulo",
    "busqueda_origen", "fecha_scraping", "flag",
]


def load_state(html):
    """Devuelve initialState del JSON embebido (o None si no está)."""
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NORDIC_RENDERING_CTX__")
    if tag is None or not tag.string or PREFIX not in tag.string:
        return None
    text = tag.string
    data, _ = json.JSONDecoder().raw_decode(text[text.index(PREFIX) + len(PREFIX):])
    # Algunas páginas (ej. marcas sin avisos visibles) vienen como "staticMarkup",
    # sin appProps ni resultados: se tratan como página sin datos.
    return data.get("appProps", {}).get("pageProps", {}).get("initialState")


def clean_url(url):
    """Saca el fragmento (#...) y el sufijo _NoIndex_True, prohibido por robots.txt."""
    url = url.split("#", 1)[0].replace("_NoIndex_True", "")
    return url


def _count(text):
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else None


def parse_filters(state):
    """{filter_id: {"name", "values": [{"name", "results", "url"}], "url_templates"}}"""
    out = {}
    for comp in state.get("sidebar", {}).get("components", []):
        for flt in comp.get("filters", []) or []:
            out[flt["id"]] = {
                "name": flt.get("name"),
                "values": [
                    {"name": v.get("name"), "results": _count(v.get("results")),
                     "url": clean_url(v["url"]) if v.get("url") else None}
                    for v in flt.get("values", [])
                ],
                "url_templates": flt.get("url_templates"),
            }
    return out


def parse_page(html):
    """Resumen de una página de búsqueda: total informado, tarjetas y filtros."""
    state = load_state(html)
    if state is None:
        return None
    return {
        "total": state.get("melidata_track", {}).get("event_data", {}).get("total"),
        "cards": [r["polycard"] for r in state.get("results", []) if r.get("polycard")],
        "filters": parse_filters(state),
    }


# --- campos de cada aviso ---------------------------------------------------

def _plain(text):
    """Minúsculas y sin tildes, para buscar palabras en el título."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


TRANSMISSION_HINTS = [
    ("automatica", r"\b(at|aut|automatic[oa]?|cvt)\b"),
    ("manual", r"\b(mt|manual)\b"),
]
FUEL_HINTS = [
    ("diesel", r"\b(diesel|tdi|hdi|crdi|turbodiesel)\b"),
    ("hibrido", r"\b(hibrido|hybrid|hev|phev)\b"),
    ("electrico", r"\b(electrico|electric)\b"),
    ("nafta", r"\b(nafta)\b"),
]


def title_hint(title, hints):
    """Valor si el título trae indicios de una sola categoría; si no, None."""
    plain = _plain(title or "")
    found = {value for value, rx in hints if re.search(rx, plain)}
    return found.pop() if len(found) == 1 else None


def motor_hint(title):
    """Cilindrada tipo '1.6' si aparece en el título."""
    m = re.search(r"\b(\d\.\d)\b", title or "")
    return m.group(1) if m else None


def version_from_title(title, marca, modelo, anio):
    """Lo que queda del título después de 'Marca Modelo Año'."""
    if not title:
        return None
    rest = title.strip()
    prefix = f"{marca} {modelo}".strip()
    if prefix and _plain(rest).startswith(_plain(prefix)):
        rest = rest[len(prefix):].strip()
    if anio and rest.startswith(str(anio)):
        rest = rest[len(str(anio)):].strip()
    rest = rest.strip(" -")
    return rest or None


def split_location(text):
    """'Pocitos Nuevo - Montevideo' -> ('Pocitos Nuevo', 'Montevideo')."""
    if not text:
        return None, None
    if " - " in text:
        barrio, depto = text.rsplit(" - ", 1)
        return barrio.strip(), depto.strip()
    return None, text.strip()


def model_from_title(title, marca, modelos):
    """Modelo más largo de la lista del sitio con el que arranca el título (tras la marca)."""
    rest = _plain(title or "")
    if _plain(marca) and rest.startswith(_plain(marca)):
        rest = rest[len(_plain(marca)):].strip()
    best = None
    for m in modelos:
        pm = _plain(m)
        if pm and (rest == pm or rest.startswith(pm + " ")) and (best is None or len(pm) > len(_plain(best))):
            best = m
    return best


def parse_card(card, marca, modelo, tipo_vendedor, busqueda_origen, fecha, anio_scraping,
               modelos_marca=()):
    """Una fila del CSV. Si la búsqueda no fijó el modelo, se busca en el título
    contra la lista de modelos que publica el sitio para esa marca."""
    meta = card["metadata"]
    comps = {c["type"]: c for c in card.get("components", [])}

    titulo = comps.get("title", {}).get("title", {}).get("text")
    modelo_origen = "busqueda" if modelo else None
    if not modelo:
        modelo = model_from_title(titulo, marca, modelos_marca)
        modelo_origen = "titulo" if modelo else None
    price = comps.get("price", {}).get("price", {}).get("current_price", {})

    anio = km = None
    for text in comps.get("attributes_list", {}).get("attributes_list", {}).get("texts", []):
        if re.fullmatch(r"\d{4}", text.strip()):
            anio = int(text)
        elif "km" in text.lower():
            km = _count(text)

    barrio, departamento = split_location(comps.get("location", {}).get("location", {}).get("text"))

    # El componente "seller" solo aparece en tiendas oficiales y trae el nombre del
    # comercio: se guarda únicamente que existe, nunca el nombre.
    tienda_oficial = "seller" in comps

    flags = []
    if km == 0:
        flags.append("km_0")
    elif km is not None and km < 1000:
        flags.append("km_menor_1000")
    if anio is not None and anio >= anio_scraping:
        flags.append("anio_actual_o_posterior")
    for name, value in (("sin_precio", price.get("value")), ("sin_anio", anio), ("sin_km", km)):
        if value is None:
            flags.append(name)

    url = meta.get("url")
    return {
        "item_id": meta.get("id"),
        "url": f"https://{url}" if url and not url.startswith("http") else url,
        "titulo": titulo,
        "marca": marca,
        "modelo": modelo,
        "modelo_origen": modelo_origen,
        "version": version_from_title(titulo, marca, modelo, anio),
        "anio": anio,
        "km": km,
        "precio": price.get("value"),
        "moneda": price.get("currency"),
        "barrio": barrio,
        "departamento": departamento,
        "tipo_vendedor": tipo_vendedor,
        "tienda_oficial": tienda_oficial,
        "transmision_titulo": title_hint(titulo, TRANSMISSION_HINTS),
        "combustible_titulo": title_hint(titulo, FUEL_HINTS),
        "motor_titulo": motor_hint(titulo),
        "busqueda_origen": busqueda_origen,
        "fecha_scraping": fecha,
        "flag": ";".join(flags) or None,
    }
