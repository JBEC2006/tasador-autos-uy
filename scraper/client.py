"""Cliente HTTP "educado": robots.txt, pausas, tope de requests y corte ante bloqueos.

Todas las descargas del proyecto pasan por PoliteClient.get(), así las reglas
se aplican en un solo lugar.
"""
import logging
import random
import re
import time
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"

# User-Agent de navegador normal (regla 3: sin evasión, uno fijo, sin rotar).
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "es-UY,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

ROBOTS_HOSTS = [
    "autos.mercadolibre.com.uy",
    "auto.mercadolibre.com.uy",
    "listado.mercadolibre.com.uy",
    "www.mercadolibre.com.uy",
]

MIN_PAUSE, MAX_PAUSE = 4.0, 8.0
MAX_REQUESTS = 2000
BLOCK_MARKERS = ("account-verification", "captcha", "/gz/", "negative_traffic")

log = logging.getLogger("scraper")


class Blocked(Exception):
    """Bloqueo repetido: hay que guardar progreso y frenar."""


class Disallowed(Exception):
    """La URL está prohibida por robots.txt."""


class BudgetExceeded(Exception):
    """Se alcanzó el tope total de requests."""


def wildcard_rules(robots_text):
    """Reglas Allow/Disallow del grupo 'User-agent: *', compiladas a regex.

    urllib.robotparser solo hace match por prefijo literal: no entiende '*' ni '$'
    (ej. 'Disallow: /*_Desde_' nunca matchea). Por eso se complementa con esto.
    """
    rules, in_star, prev_was_agent = [], False, False
    for raw in robots_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (p.strip() for p in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            in_star = (value == "*") or (in_star and prev_was_agent)
            prev_was_agent = True
            continue
        prev_was_agent = False
        if in_star and key in ("allow", "disallow") and value:
            regex = re.escape(value).replace(r"\*", ".*")
            if regex.endswith(r"\$"):
                regex = regex[:-2] + "$"
            rules.append((key == "allow", len(value), re.compile(regex)))
    return rules


def wildcard_allowed(rules, path):
    """Regla más específica (más larga) gana; empate -> Allow."""
    best = None
    for allow, length, rx in rules:
        if rx.match(path) and (best is None or length > best[1] or (length == best[1] and allow)):
            best = (allow, length)
    return True if best is None else best[0]


class PoliteClient:
    def __init__(self, request_count=0):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.request_count = request_count
        self.robots = {}
        self.wildcards = {}
        self.last_request = 0.0

    # --- robots.txt -------------------------------------------------------
    def load_robots(self, host):
        """Descarga y guarda el robots.txt de un subdominio (cuenta como request)."""
        if host in self.robots:
            return self.robots[host]
        url = f"https://{host}/robots.txt"
        self._wait()
        resp = self.session.get(url, timeout=30)
        self._count()
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"robots_{host}.txt").write_text(resp.text, encoding="utf-8")
        rp = robotparser.RobotFileParser(url)
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
        elif resp.status_code in (401, 403):
            rp.disallow_all = True
        else:
            rp.allow_all = True
        self.robots[host] = rp
        self.wildcards[host] = wildcard_rules(resp.text) if resp.status_code == 200 else []
        log.info("robots.txt %s -> HTTP %s", host, resp.status_code)
        return rp

    def allowed(self, url):
        """Permitida solo si lo permiten robotparser Y el chequeo de comodines."""
        parsed = urlparse(url)
        rp = self.load_robots(parsed.netloc)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return rp.can_fetch(USER_AGENT, url) and wildcard_allowed(self.wildcards[parsed.netloc], path)

    def crawl_delay(self, host):
        rp = self.robots.get(host)
        if rp is None:
            return None
        return rp.crawl_delay(USER_AGENT)

    # --- ritmo ------------------------------------------------------------
    def _wait(self, host=None):
        pause = random.uniform(MIN_PAUSE, MAX_PAUSE)
        delay = self.crawl_delay(host) if host else None
        if delay:
            pause = max(pause, float(delay))
        elapsed = time.time() - self.last_request
        if self.last_request and elapsed < pause:
            time.sleep(pause - elapsed)

    def _count(self):
        self.request_count += 1
        self.last_request = time.time()

    # --- descarga ---------------------------------------------------------
    def _is_blocked(self, resp):
        if resp.status_code in (403, 429):
            return True
        final = resp.url.lower()
        if any(m in final for m in BLOCK_MARKERS):
            return True
        return any(r.status_code in (301, 302, 303, 307) and
                   any(m in r.headers.get("Location", "").lower() for m in BLOCK_MARKERS)
                   for r in resp.history)

    def get(self, url):
        host = urlparse(url).netloc
        if not self.allowed(url):
            log.warning("PROHIBIDO por robots.txt, no se pide: %s", url)
            raise Disallowed(url)
        for attempt in (1, 2):
            if self.request_count >= MAX_REQUESTS:
                raise BudgetExceeded(f"tope de {MAX_REQUESTS} requests alcanzado")
            self._wait(host)
            resp = self.session.get(url, timeout=30)
            self._count()
            if not self._is_blocked(resp):
                return resp
            log.warning("Bloqueo (HTTP %s, url final %s) intento %d", resp.status_code, resp.url, attempt)
            if attempt == 1:
                time.sleep(60)
        raise Blocked(f"HTTP {resp.status_code} en {url} (final: {resp.url})")
