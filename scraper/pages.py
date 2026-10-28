"""Caché de páginas descargadas, progreso persistente y logging.

Cada página se descarga una sola vez y se guarda en data/raw/pages/. Si otra
fase necesita la misma URL, la lee del disco en vez de volver a pedirla.
El contador de requests vive en data/progress.json, así el tope de 2.000 vale
para todo el proyecto (descubrimiento + corrida), no por script.
"""
import hashlib
import json
import logging
import sys
from datetime import datetime

from scraper.client import DATA_DIR, RAW_DIR, PoliteClient

PAGES_DIR = RAW_DIR / "pages"
INDEX_FILE = PAGES_DIR / "index.json"
PROGRESS_FILE = DATA_DIR / "progress.json"
LOG_FILE = DATA_DIR / "scrape.log"


def setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, encoding="utf-8")):
        handler.setFormatter(fmt)
        root.addHandler(handler)


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_progress():
    return load_json(PROGRESS_FILE, {"requests_total": 0, "busquedas_hechas": {}})


def save_progress(progress, client):
    progress["requests_total"] = client.request_count
    progress["actualizado"] = datetime.now().isoformat(timespec="seconds")
    save_json(PROGRESS_FILE, progress)


def new_client(progress):
    return PoliteClient(request_count=progress.get("requests_total", 0))


def get_page(client, url):
    """HTML de la URL: del caché si ya se bajó, si no lo descarga y lo guarda."""
    index = load_json(INDEX_FILE, {})
    if url in index:
        return (PAGES_DIR / index[url]["file"]).read_text(encoding="utf-8")
    resp = client.get(url)  # puede lanzar Disallowed / Blocked / BudgetExceeded
    # El contador se persiste después de cada request, así un corte inesperado
    # no hace "perder" requests ya hechos.
    progress = load_progress()
    progress["requests_total"] = client.request_count
    save_json(PROGRESS_FILE, progress)
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".html"
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    (PAGES_DIR / name).write_text(resp.text, encoding="utf-8")
    index[url] = {"file": name, "status": resp.status_code, "final_url": resp.url,
                  "fetched_at": datetime.now().isoformat(timespec="seconds")}
    save_json(INDEX_FILE, index)
    return resp.text
