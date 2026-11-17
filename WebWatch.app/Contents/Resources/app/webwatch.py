#!/usr/bin/env python3
"""
WebWatch - vigilante de páginas web (sin IA: solo las reglas que tú defines).

Uso normal: abre la app WebWatch. Comandos:
  webwatch.py ui                 abre el panel en el navegador
  webwatch.py run [--id ID]      revisa ahora (todas o una)
  webwatch.py tick               revisa solo las webs a las que les toca (lo lanza macOS cada 10 min)
  webwatch.py install|uninstall  activa/quita la revisión automática (launchd)
  webwatch.py login-item on|off  abrir en la barra de menús al iniciar sesión
  webwatch.py browser URL        abre el navegador del bot (para captchas, cookies, idioma)
"""
import argparse
import csv
import difflib
import fcntl
import hashlib
import importlib.util
import json
import os
import platform
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

VERSION = (Path(__file__).resolve().parent / "VERSION").read_text().strip() if (Path(__file__).resolve().parent / "VERSION").exists() else "2.1"
BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("WEBWATCH_DATA") or (BASE.parent if BASE.name == "app" else BASE))
CONFIG_PATH = DATA / "config.json"
STATE_PATH = DATA / "state.json"
HISTORY_PATH = DATA / "history.json"
UI_PATH = DATA / "ui.json"
LOG_PATH = DATA / "webwatch.log"
PROFILE_DIR = DATA / "browser-profile"
RUN_LOCK = DATA / ".run.lock"
BROWSER_LOCK = DATA / ".browser.lock"
APP_PATH_FILE = DATA / "app_path.txt"
LABEL = "com.webwatch.bot"
LABEL_MENUBAR = "com.webwatch.menubar"
LA_DIR = Path.home() / "Library" / "LaunchAgents"
PORT = 8750
TICK_SECONDS = 600
IS_MAC = platform.system() == "Darwin"
BLOCK_RETRY_HOURS = 6  # con captcha no insiste: cada intento empeora la «reputación» ante la tienda


def _chrome_major():
    """Versión real de Chrome instalado: el user agent debe coincidir con la que anuncia el propio navegador
    (sec-ch-ua). Si no coincide, las tiendas lo ven como bot y piden captcha aunque ya lo resolvieras."""
    for app in ("/Applications/Google Chrome.app", str(Path.home() / "Applications/Google Chrome.app")):
        try:
            with open(f"{app}/Contents/Info.plist", "rb") as f:
                return str(plistlib.load(f)["CFBundleShortVersionString"]).split(".")[0]
        except Exception:  # noqa: BLE001
            continue
    return "142"


CHROME_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             f"(KHTML, like Gecko) Chrome/{_chrome_major()}.0.0.0 Safari/537.36")
HTTP_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
}
ALI_COOKIE = "site=esp&c_tp=EUR&region=ES&b_locale=es_ES"
STORE_NAMES = {"amazon": "Amazon", "aliexpress": "AliExpress"}

DEFAULT_CONFIG = {
    "interval_hours": 4,
    "paused": False,
    "defaults": {"timeout": 30, "pause_seconds": 3, "alert_after_errors": 3},
    "notify_desktop": True,
    "telegram": {"enabled": False, "token": "", "chat_id": ""},
    "excel": {"enabled": True, "path": "webwatch_log.xlsx"},
    "csv": {"enabled": True, "path": "observaciones.csv", "delimiter": ";"},
    "watches": [
        {"id": "obra0001", "name": "Obra piso Greenquart", "url": "https://greenquart.com/estado-obra.php",
         "type": "change", "selector": "", "ignore": [], "render": "auto", "interval": None, "enabled": True}
    ],
}


# ================================================================ utilidades
def _copy(v):
    return json.loads(json.dumps(v))


def _merge(dst, src):
    for k, v in src.items():
        if k not in dst:
            dst[k] = _copy(v)
        elif isinstance(v, dict) and isinstance(dst[k], dict):
            _merge(dst[k], v)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def save_json(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_config():
    DATA.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_json(CONFIG_PATH, DEFAULT_CONFIG)
    cfg = load_json(CONFIG_PATH, None) or _copy(DEFAULT_CONFIG)
    _merge(cfg, DEFAULT_CONFIG)
    for w in cfg["watches"]:
        if w.get("type") == "price":  # versión 1
            w["type"] = "product"
        w.setdefault("render", "auto")
        if w["render"] == "http" and store_of(w.get("url", "")):
            w["render"] = "auto"
    return cfg


def save_config(cfg):
    save_json(CONFIG_PATH, cfg)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ts(t):
    return datetime.strptime(t, "%Y-%m-%d %H:%M:%S").timestamp()


def fmt_ts(x):
    return datetime.fromtimestamp(x).strftime("%Y-%m-%d %H:%M:%S")


def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def data_path(p, default):
    p = Path(os.path.expanduser(p or default))
    return p if p.is_absolute() else DATA / p


def excel_path(cfg):
    return data_path(cfg["excel"].get("path"), "webwatch_log.xlsx")


def csv_path(cfg):
    return data_path(cfg["csv"].get("path"), "observaciones.csv")


def has_playwright():
    return importlib.util.find_spec("playwright") is not None


def online():
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53), ("apple.com", 443)):
        try:
            socket.create_connection((host, port), timeout=3).close()
            return True
        except OSError:
            continue
    return False


STORE_MIN_HOURS = 2  # Amazon/AliExpress: más a menudo dispara captchas a diario


def interval_of(w, cfg):
    h = float(w.get("interval") or cfg.get("interval_hours") or 4)
    if store_of(w.get("url", "")):
        h = max(h, STORE_MIN_HOURS)
    return h * 3600


def _jitter(w, st):
    """Variación estable (misma para is_due y para «próxima revisión») a partir de la web y su última
    revisión. Tiendas: +0-25 % (nunca por debajo del mínimo), resto ±10 %. Así no revisa siempre a la
    misma hora exacta, que es un patrón muy de bot."""
    seed = f"{w.get('id')}|{(st.get('last') or {}).get('t', '')}".encode()
    r = int(hashlib.sha256(seed).hexdigest()[:8], 16) / 0xFFFFFFFF
    return 1 + 0.25 * r if store_of(w.get("url", "")) else 0.9 + 0.2 * r


def retry_interval(w, st, cfg):
    iv = interval_of(w, cfg)
    if st.get("blocked"):
        iv = max(iv, BLOCK_RETRY_HOURS * 3600)  # captcha: no insistir hasta que lo resuelvas
    elif st.get("errors"):
        iv = min(iv, 1800)  # otro fallo: reintenta en 30 min
    return iv * _jitter(w, st)


def is_due(w, st, cfg):
    last = (st.get("last") or {}).get("t")
    if not last:
        return True
    return time.time() - ts(last) >= retry_interval(w, st, cfg) - 60


def money(p, cur=None):
    if p is None:
        return "—"
    s = f"{p:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(cur or "EUR", cur or "")
    return f"{s} {sym}".strip()


def parse_price(text):
    """'1.299,95 €' -> 1299.95 ; '$1,299.95' -> 1299.95 ; '49,90' -> 49.9"""
    m = re.search(r"\d[\d.,\s  ]*", text or "")
    if not m:
        return None
    s = re.sub(r"[\s  ]", "", m.group(0)).rstrip(".,")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + "." + tail if len(tail) <= 2 else s.replace(",", "")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.rpartition(".")[2]) == 3):
        s = s.replace(".", "")
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def guess_currency(text):
    t = text or ""
    for sym, code in (("€", "EUR"), ("EUR", "EUR"), ("£", "GBP"), ("US $", "USD"), ("US$", "USD"), ("$", "USD")):
        if sym in t:
            return code
    return None


# ================================================================ tiendas
def store_of(url):
    h = urlparse(url or "").netloc.lower()
    if re.search(r"(^|\.)amazon\.", h) or h.endswith("amzn.eu") or h.endswith("amzn.to") or h.endswith("a.co"):
        return "amazon"
    if "aliexpress." in h:
        return "aliexpress"
    return None


def canonical_url(url):
    st = store_of(url)
    host = urlparse(url).netloc
    if st == "amazon":
        m = re.search(r"/(?:dp|gp/product|gp/aw/d|exec/obidos/ASIN)/([A-Z0-9]{10})", url)
        if m and "amazon." in host:
            return f"https://{host}/dp/{m.group(1)}"
    if st == "aliexpress":
        m = re.search(r"/item/(\d+)\.html", url)
        if m:
            return f"https://{host}/item/{m.group(1)}.html"
    return url


class Blocked(Exception):
    pass


class Busy(Exception):
    pass


BLOCK_SIGNS = {
    "amazon": ["validateCaptcha", "captchacharacters", "api-services-support@amazon.com",
               "Introduce los caracteres que ves", "Enter the characters you see below"],
    "aliexpress": ["_____tmd_____", "baxia-punish", "nc_1_n1z", "x5secdata", "Slide to verify"],
}


def detect_block(html, store):
    for s in BLOCK_SIGNS.get(store or "", []):
        if s in html:
            raise Blocked(f"{STORE_NAMES[store]} pide verificar que eres humano (captcha). "
                          "Ábrela una vez en el navegador del bot y resuélvelo.")


AMZ_PRICE = [
    "#corePrice_feature_div .a-price .a-offscreen", "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#apex_desktop .a-price .a-offscreen", "#tp_price_block_total_price_ww .a-offscreen",
    "#priceblock_dealprice", "#priceblock_ourprice", "#priceblock_saleprice", "#price_inside_buybox",
    "#newBuyBoxPrice", "#kindle-price", ".a-price .a-offscreen",
]
ALI_PRICE = [
    "[class*='price-default--current']", "[class*='price--currentPriceText']", ".product-price-current",
    "[class*='product-price-current']", "[class*='uniform-banner-box-price']", "[class*='price--current']",
]
ALI_RX_TEXT = [r'"formatedActivityPrice"\s*:\s*"([^"]+)"', r'"formatedPrice"\s*:\s*"([^"]+)"']
ALI_RX_NUM = [r'"minActivityAmount"\s*:\s*\{[^{}]*?"value"\s*:\s*([\d.]+)',
              r'"minAmount"\s*:\s*\{[^{}]*?"value"\s*:\s*([\d.]+)']
WAIT_SEL = {
    "amazon": "#productTitle, form[action*='validateCaptcha'], #captchacharacters",
    "aliexpress": ", ".join(ALI_PRICE + ["[data-pl='product-title']", "iframe[src*='punish']"]),
}


def _ld_nodes(data):
    if isinstance(data, list):
        for x in data:
            yield from _ld_nodes(x)
    elif isinstance(data, dict):
        yield data
        for k in ("@graph", "mainEntity", "hasVariant"):
            if k in data:
                yield from _ld_nodes(data[k])


def _is_product(node):
    t = node.get("@type")
    t = t if isinstance(t, list) else [t]
    return any(str(x).lower() in ("product", "productgroup", "book", "individualproduct", "vehicle") for x in t)


def first_price(soup, selectors):
    for sel in selectors:
        for el in soup.select(sel)[:3]:
            txt = el.get("content") or el.get("value") or el.get_text(" ")
            p = parse_price(txt)
            if p:
                return p, txt
    return None, None


def extract_product(html, url="", store=None, selector=""):
    soup = BeautifulSoup(html, "html.parser")
    info = {"title": None, "price": None, "currency": None, "available": None}

    if store == "amazon":
        t = soup.select_one("#productTitle")
        if t:
            info["title"] = norm(t.get_text())
        p, txt = first_price(soup, AMZ_PRICE)
        if p is None:
            w, f = soup.select_one(".a-price .a-price-whole"), soup.select_one(".a-price .a-price-fraction")
            if w:
                txt = norm(w.get_text()).rstrip(".,") + "," + (norm(f.get_text()) if f else "00")
                p = parse_price(txt)
        if p:
            sym = soup.select_one(".a-price-symbol")
            info["price"] = p
            info["currency"] = guess_currency(txt) or guess_currency(sym.get_text() if sym else "")
        av = soup.select_one("#availability")
        if soup.select_one("#outOfStock"):
            info["available"] = False
        elif av:
            a = av.get_text(" ").lower()
            if any(k in a for k in ("no disponible", "unavailable", "agotado", "sin stock", "out of stock")):
                info["available"] = False
            elif any(k in a for k in ("en stock", "in stock", "disponible", "quedan", "only", "envío")):
                info["available"] = True
        if info["available"] is None and soup.select_one("#add-to-cart-button"):
            info["available"] = True

    if store == "aliexpress":
        t = soup.select_one("[data-pl='product-title']") or soup.select_one("h1")
        if t:
            info["title"] = norm(t.get_text())
        p, txt = first_price(soup, ALI_PRICE)
        if p is None:
            for rx in ALI_RX_TEXT:
                m = re.search(rx, html)
                if m and parse_price(m.group(1)):
                    p, txt = parse_price(m.group(1)), m.group(1)
                    break
        if p is None:
            for rx in ALI_RX_NUM:
                m = re.search(rx, html)
                if m:
                    p, txt = float(m.group(1)), ""
                    break
        if p:
            info["price"], info["currency"] = p, guess_currency(txt) or "EUR"
        m = re.search(r'"totalAvailQuantity"\s*:\s*(\d+)', html)
        if m:
            info["available"] = int(m.group(1)) > 0

    # Datos estructurados (sirven para la mayoría de tiendas)
    for s in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(s.string or s.get_text() or "")
        except ValueError:
            continue
        for node in _ld_nodes(data):
            if not _is_product(node):
                continue
            info["title"] = info["title"] or node.get("name")
            offers = node.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if not isinstance(offers, dict):
                continue
            raw = offers.get("price", offers.get("lowPrice"))
            if raw is None and isinstance(offers.get("priceSpecification"), dict):
                raw = offers["priceSpecification"].get("price")
            try:
                p = float(raw) if raw not in (None, "") else None
            except (TypeError, ValueError):
                p = parse_price(str(raw))
            if p and info["price"] is None:
                info["price"], info["currency"] = p, offers.get("priceCurrency") or info["currency"]
            av = str(offers.get("availability", ""))
            if av and info["available"] is None:
                info["available"] = not any(x in av for x in ("OutOfStock", "SoldOut", "Discontinued"))

    if info["price"] is None:
        p, txt = first_price(soup, ['meta[property="product:price:amount"]', 'meta[property="og:price:amount"]',
                                    '[itemprop="price"]'])
        if p:
            cur = soup.select_one('meta[property="product:price:currency"], meta[property="og:price:currency"], '
                                  '[itemprop="priceCurrency"]')
            info["price"] = p
            info["currency"] = (cur.get("content") if cur else None) or guess_currency(txt)

    if selector:
        els = soup.select(selector)
        if not els:
            raise RuntimeError(f"El selector «{selector}» no encuentra nada en la página")
        txt = norm(els[0].get("content") or els[0].get_text(" "))
        p = parse_price(txt)
        if p is None:
            raise RuntimeError(f"El selector encuentra «{txt[:60]}», pero no parece un precio")
        info["price"], info["currency"] = p, guess_currency(txt) or info["currency"]

    if not info["title"]:
        og = soup.select_one('meta[property="og:title"]')
        info["title"] = (og.get("content") if og else None) or (soup.title.get_text() if soup.title else None)
    info["title"] = norm(info["title"])[:160] or None
    return info


def extract_text(html, selector, ignore):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    if selector:
        els = soup.select(selector)
        if not els:
            raise RuntimeError(f"El selector «{selector}» no encuentra nada en la página")
    else:
        els = [soup.body or soup]
    text = norm(" ".join(e.get_text(" ") for e in els))
    for pat in ignore or []:
        try:
            text = re.sub(pat, "", text)
        except re.error as e:
            raise RuntimeError(f"Expresión a ignorar no válida «{pat}»: {e}")
    title = norm(soup.title.get_text()) if soup.title else None
    return norm(text), title


def describe_diff(old, new, limit=700):
    """Resume el cambio en frases legibles: «antes» → «ahora», añadido, quitado."""
    a, b = old.split(" "), new.split(" ")
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        ctx = " ".join(a[max(0, i1 - 3):i1])
        pre = f"…{ctx} " if ctx else ""
        was, now_ = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if op == "replace":
            out.append(f"✏️ {pre}«{was}» → «{now_}»")
        elif op == "insert":
            out.append(f"➕ {pre}«{now_}»")
        else:
            out.append(f"➖ {pre}«{was}»")
    txt = "\n".join(out) or "(cambio menor de formato)"
    return txt[:limit] + ("…" if len(txt) > limit else "")


def friendly_error(e, url):
    host = urlparse(url).netloc.replace("www.", "") or "la web"
    if isinstance(e, requests.Timeout):
        return f"{host} tardó demasiado en responder"
    if isinstance(e, requests.ConnectionError):
        return f"No se pudo conectar con {host} (¿sin internet o la web está caída?)"
    if isinstance(e, requests.HTTPError) and e.response is not None:
        code = e.response.status_code
        return {404: "La página ya no existe (error 404)", 403: f"{host} no deja entrar al bot (error 403)",
                401: "La página pide usuario y contraseña", 429: f"{host} pide ir más despacio (error 429)"}.get(
            code, f"{host} respondió con error {code}")
    msg = str(e)
    if type(e).__name__ == "TimeoutError" or "Timeout" in msg.split("\n")[0]:
        return f"{host} tardó demasiado en cargar en el navegador del bot"
    return msg.split("\nCall log:")[0]


# ================================================================ descarga
def launch_ctx(pw, headless):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    kw = {"headless": headless, "locale": "es-ES"}
    if headless:
        kw.update(user_agent=CHROME_UA, viewport={"width": 1366, "height": 900})
    else:
        kw["no_viewport"] = True
    last = None
    for channel in ("chrome", None):
        try:
            if channel:
                ctx = pw.chromium.launch_persistent_context(str(PROFILE_DIR), channel=channel, **kw)
            else:
                ctx = pw.chromium.launch_persistent_context(str(PROFILE_DIR), **kw)
            ctx.add_cookies([{"name": "aep_usuc_f", "value": ALI_COOKIE, "domain": ".aliexpress.com", "path": "/"}])
            return ctx
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"No pude abrir el navegador del bot ({str(last)[:120]}). "
                       "Instala Google Chrome o ejecuta: playwright install chromium")


class Fetcher:
    """Descarga páginas. Reutiliza un único navegador para toda la revisión."""

    def __init__(self, defaults):
        self.timeout = defaults.get("timeout", 30)
        self.s = requests.Session()
        self._pw = self._ctx = self._lock = None

    def http(self, url, store):
        cookies = {"aep_usuc_f": ALI_COOKIE} if store == "aliexpress" else None
        r = self.s.get(url, headers=HTTP_HEADERS, timeout=self.timeout, cookies=cookies)
        if store and r.status_code in (403, 429, 503):
            raise Blocked(f"{STORE_NAMES[store]} ha bloqueado la petición directa (código {r.status_code})")
        r.raise_for_status()
        if r.encoding is None or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        return r.text

    def _context(self):
        if self._ctx:
            return self._ctx
        if not has_playwright():
            raise RuntimeError("Esta web necesita el navegador del bot y Playwright no está instalado")
        self._lock = open(BROWSER_LOCK, "w")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock.close()
            self._lock = None
            raise RuntimeError("La ventana del navegador del bot está abierta: ciérrala para que pueda revisar")
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._ctx = launch_ctx(self._pw, headless=True)
        return self._ctx

    def browser(self, url, store):
        page = self._context().new_page()
        try:
            try:
                # Con tienda conocida basta con que empiece a llegar la página: luego se espera
                # al precio o al captcha (WAIT_SEL), que es lo que importa.
                page.goto(url, wait_until="commit" if WAIT_SEL.get(store) else "domcontentloaded", timeout=45000)
            except Exception as e:  # noqa: BLE001
                # Muchas tiendas no terminan nunca de «cargar» (anuncios, rastreadores). Si ya hay
                # página, se sigue; si no, error.
                if type(e).__name__ != "TimeoutError" or not page.url.startswith("http"):
                    raise
            try:
                if WAIT_SEL.get(store):
                    page.wait_for_selector(WAIT_SEL[store], timeout=30000)
                else:
                    page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(800)
            return page.content()
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

    def get(self, watch):
        url, store = watch["url"], store_of(watch["url"])
        mode = watch.get("render") or "auto"
        use_browser = mode == "browser" or (mode == "auto" and store == "aliexpress" and has_playwright())
        if not use_browser:
            try:
                html = self.http(url, store)
                detect_block(html, store)
                return html, "http"
            except Blocked:
                if not (mode == "auto" and has_playwright()):
                    raise
        html = self.browser(url, store)
        detect_block(html, store)
        return html, "navegador"

    def close(self):
        for fn in (lambda: self._ctx and self._ctx.close(), lambda: self._pw and self._pw.stop()):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
        if self._lock:
            fcntl.flock(self._lock, fcntl.LOCK_UN)
            self._lock.close()
        self._pw = self._ctx = self._lock = None


# ================================================================ revisión
def check(watch, prev, fetcher):
    """Devuelve dict: value, state, alert(título, detalle)|None, note, price, currency, available, title, via."""
    kind = "product" if watch.get("type") == "price" else watch.get("type", "change")
    store = store_of(watch["url"])
    html, via = fetcher.get(watch)
    out = {"via": via, "price": None, "currency": None, "available": None, "title": None, "alert": None}

    if kind == "product":
        info = extract_product(html, watch["url"], store, watch.get("selector"))
        if info["price"] is None and via == "http" and (watch.get("render") or "auto") == "auto" and has_playwright():
            html = fetcher.browser(watch["url"], store)
            detect_block(html, store)
            via = out["via"] = "navegador"
            info = extract_product(html, watch["url"], store, watch.get("selector"))
        out.update(info)
        price, avail = info["price"], info["available"]
        if price is None and avail is not False:
            raise RuntimeError("No encuentro el precio. Indica el selector CSS del precio en «Opciones avanzadas».")
        old, was, low, high = prev.get("price"), prev.get("available"), prev.get("min"), prev.get("max")
        cur = info["currency"] or prev.get("currency")
        nums = [x for x in (low, price) if x is not None]
        new = {"price": price if price is not None else old, "available": avail, "title": info["title"],
               "currency": cur, "min": min(nums) if nums else None,
               "max": max([x for x in (high, price) if x is not None]) if (high or price) else None}
        reasons, title = [], None
        if price is not None:
            below = watch.get("below")
            if below not in (None, "") and price <= float(below) and (old is None or old > float(below)):
                reasons.append(f"Precio {money(price, cur)} por debajo de tu objetivo ({money(float(below), cur)})")
            drop = watch.get("drop_percent")
            if drop not in (None, "") and old and price <= old * (1 - float(drop) / 100):
                reasons.append(f"Baja un {100 * (old - price) / old:.0f}%: de {money(old, cur)} a {money(price, cur)}")
            if watch.get("notify_min") and low is not None and price < low:
                reasons.append(f"Mínimo histórico: {money(price, cur)} (antes {money(low, cur)})")
            if watch.get("any_change") and old is not None and price != old and not reasons:
                reasons.append(f"El precio cambia de {money(old, cur)} a {money(price, cur)}")
            if reasons:
                title = "Oferta" if old is None or price < old else "Cambio de precio"
        if watch.get("notify_stock", True) and was is False and avail is True:
            reasons.append("Vuelve a haber stock")
            title = title or "Vuelve el stock"
        out["value"] = (money(price, cur) if price is not None else "Sin precio") + (" · sin stock" if avail is False else "")
        if "price" not in prev:
            out["note"] = "primera lectura (referencia)"
        elif price is None or price == old:
            out["note"] = "sin cambios" if avail == was else ("sin stock" if avail is False else "stock cambia")
        else:
            out["note"] = f"antes {money(old, cur)}"
        out["state"] = new
        if reasons:
            out["alert"] = (title, " · ".join(reasons))
        return out

    text, page_title = extract_text(html, watch.get("selector"), watch.get("ignore"))
    out["title"] = page_title
    if kind == "change":
        h = hashlib.sha256(text.encode()).hexdigest()
        out["state"], out["value"] = {"hash": h, "text": text, "title": page_title}, text[:240]
        if "hash" not in prev:
            out["note"] = "primera lectura (referencia)"
        elif h == prev["hash"]:
            out["note"] = "sin cambios"
        else:
            out["note"] = "CAMBIO"
            out["alert"] = ("Cambio detectado", describe_diff(prev.get("text", ""), text))
        return out

    if kind == "keyword":
        low_text = text.lower()
        appears = [k for k in watch.get("appears", []) if k.lower() in low_text]
        gone = [k for k in watch.get("disappears", []) if k.lower() not in low_text]
        out["state"] = {"appears": appears, "gone": gone, "title": page_title}
        parts = []
        if watch.get("appears"):
            parts.append("aparecen: " + (", ".join(appears) or "ninguna"))
        if watch.get("disappears"):
            parts.append("ya no están: " + (", ".join(gone) or "ninguna"))
        out["value"] = " · ".join(parts)
        if "appears" not in prev:
            out["note"] = "primera lectura (referencia)"
            return out
        reasons = [f"Aparece «{k}»" for k in appears if k not in prev["appears"]]
        reasons += [f"Desaparece «{k}»" for k in gone if k not in prev["gone"]]
        out["note"] = "CAMBIO" if reasons else "sin cambios"
        if reasons:
            out["alert"] = ("Palabra clave", " · ".join(reasons))
        return out

    raise RuntimeError(f"Tipo desconocido: {kind}")


# ================================================================ avisos y registros
def notify_desktop(title, message, url=None):
    try:
        if IS_MAC:
            tn = shutil.which("terminal-notifier") or next(
                (p for p in ("/opt/homebrew/bin/terminal-notifier", "/usr/local/bin/terminal-notifier")
                 if os.path.exists(p)), None)
            if tn:  # notificación clicable que abre la web
                subprocess.run([tn, "-title", title, "-message", message[:220], "-sound", "Glass",
                                "-group", "webwatch"] + (["-open", url] if url else []), check=False, timeout=10)
                return
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
            subprocess.run(["osascript", "-e", f'display notification "{esc(message[:220])}" '
                                               f'with title "{esc(title)}" sound name "Glass"'],
                           check=False, timeout=10)
        else:
            subprocess.run(["notify-send", title, message[:220]], check=False, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(f"[notificación] {title}: {message}")


def telegram_send(cfg, text):
    tg = cfg.get("telegram", {})
    if not tg.get("token") or not tg.get("chat_id"):
        raise RuntimeError("Falta el token o el chat ID de Telegram")
    r = requests.post(f"https://api.telegram.org/bot{tg['token']}/sendMessage",
                      data={"chat_id": tg["chat_id"], "text": text[:4000], "disable_web_page_preview": "true"},
                      timeout=20)
    if not r.ok:
        try:
            desc = r.json().get("description", r.text)
        except ValueError:
            desc = r.text
        raise RuntimeError(f"Telegram: {desc[:150]}")


def notify_telegram(cfg, text):
    if cfg.get("telegram", {}).get("enabled"):
        try:
            telegram_send(cfg, text)
        except Exception as e:  # noqa: BLE001
            print("Telegram error:", e)


XLS_MAIN = ["Fecha", "Web", "Tipo", "Estado", "Valor", "Precio", "Disponible", "Nota", "URL"]
XLS_ALERT = ["Fecha", "Web", "Motivo", "Detalle", "URL"]


def ensure_excel(cfg):
    path = excel_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    wb = Workbook()
    ws = wb.active
    ws.title = "Revisiones"
    ev = wb.create_sheet("Alertas")
    fill = PatternFill("solid", fgColor="E8F0FE")
    for sheet, head, widths in ((ws, XLS_MAIN, (19, 28, 10, 9, 46, 11, 11, 28, 50)),
                                (ev, XLS_ALERT, (19, 28, 18, 80, 50))):
        sheet.append(head)
        for c in sheet[1]:
            c.font, c.fill = Font(bold=True), fill
        sheet.freeze_panes = "A2"
        for i, w in enumerate(widths):
            sheet.column_dimensions[chr(65 + i)].width = w
    wb.save(path)
    return path


def log_excel(cfg, res):
    if not cfg["excel"].get("enabled", True):
        return
    path = ensure_excel(cfg)
    wb = load_workbook(path)
    avail = {True: "sí", False: "no"}.get(res.get("available"), "")
    wb["Revisiones"].append([res["t"], res["name"], res["type"], res["status"], res.get("value", ""),
                             res.get("price"), avail, res.get("note", ""), res["url"]])
    if res["status"] == "ALERTA":
        wb["Alertas"].append([res["t"], res["name"], res.get("alert_title", ""), res.get("detail", ""), res["url"]])
    try:
        wb.save(path)
    except PermissionError:
        wb.save(path.with_name(path.stem + "_pendiente.xlsx"))


CSV_HEAD = ["fecha", "web", "tipo", "estado", "valor", "precio", "moneda", "disponible", "titulo",
            "nota", "detalle", "via", "url"]


def log_csv(cfg, res):
    c = cfg["csv"]
    if not c.get("enabled", True):
        return
    path = csv_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    delim = c.get("delimiter") or ";"
    price = res.get("price")
    price = "" if price is None else (f"{price:.2f}".replace(".", ",") if delim == ";" else f"{price:.2f}")
    with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
        w = csv.writer(f, delimiter=delim)
        if new:
            w.writerow(CSV_HEAD)
        w.writerow([res["t"], res["name"], res["type"], res["status"], res.get("value", ""), price,
                    res.get("currency") or "", {True: "si", False: "no"}.get(res.get("available"), ""),
                    res.get("title") or "", res.get("note", ""), (res.get("detail") or "").replace("\n", " | "),
                    res.get("via", ""), res["url"]])


# ================================================================ ejecución
def run_checks(ids=None):
    lock = open(RUN_LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise Busy("Ya hay una revisión en curso; espera unos segundos")
    fetcher = None
    try:
        cfg = load_config()
        defaults = cfg["defaults"]
        state = load_json(STATE_PATH, {})
        history = load_json(HISTORY_PATH, [])
        watches = [w for w in cfg["watches"]
                   if (ids is None and w.get("enabled", True)) or (ids is not None and w["id"] in ids)]
        fetcher = Fetcher(defaults)
        results, renamed = [], False
        for i, w in enumerate(watches):
            st = state.setdefault(w["id"], {})
            res = {"t": now(), "id": w["id"], "name": w["name"], "url": w["url"],
                   "type": w.get("type", "change"), "detail": "", "price": None}
            try:
                r = check(w, st.get("data", {}), fetcher)
                st["data"], st["errors"] = r["state"], 0
                st.pop("blocked", None)
                if w.get("auto_name") and r.get("title"):
                    w["name"] = res["name"] = r["title"][:70]
                    w.pop("auto_name", None)
                    renamed = True
                res.update(status="ALERTA" if r["alert"] else "OK", value=r["value"], note=r["note"],
                           price=r["price"], currency=r["currency"], available=r["available"],
                           title=r["title"], via=r["via"])
                if r["alert"]:
                    title, detail = r["alert"]
                    res["detail"], res["alert_title"] = detail, title
                    if cfg.get("notify_desktop", True):
                        notify_desktop(f"WebWatch · {title}", f"{w['name']}: {detail}", w["url"])
                    notify_telegram(cfg, f"🔔 {w['name']}\n{title}\n{detail}\n{w['url']}")
            except Exception as e:  # noqa: BLE001
                st["errors"] = st.get("errors", 0) + 1
                blocked = isinstance(e, Blocked)
                res.update(status="ERROR", value="", note=friendly_error(e, w["url"])[:240], blocked=blocked)
                if blocked and not st.get("blocked"):
                    # Primer captcha: avisa ya (no tras 3 fallos) y deja de insistir hasta que se resuelva.
                    msg = (f"{w['name']}: la tienda pide captcha. Abre WebWatch y pulsa «Resolver»; "
                           f"mientras tanto lo reintento cada {BLOCK_RETRY_HOURS} h.")
                    if cfg.get("notify_desktop", True):
                        notify_desktop("WebWatch · Hace falta resolver un captcha", msg, w["url"])
                    notify_telegram(cfg, f"🧩 {msg}\n{w['url']}")
                if blocked:
                    st["blocked"] = res["t"]
                elif st["errors"] == defaults.get("alert_after_errors", 3):
                    msg = f"{w['name']} falla {st['errors']} veces seguidas: {res['note']}"
                    if cfg.get("notify_desktop", True):
                        notify_desktop("WebWatch · No puedo revisar una web", msg, w["url"])
                    notify_telegram(cfg, f"⚠️ {msg}\n{w['url']}")
            for logger in (log_excel, log_csv):
                try:
                    logger(cfg, res)
                except Exception as e:  # noqa: BLE001
                    print(f"No pude escribir el registro ({logger.__name__}): {e}")
            st["last"] = {k: res.get(k) for k in ("t", "status", "value", "note")}
            if res["status"] != "ERROR":
                if res["status"] == "ALERTA":
                    st["last_alert"] = res["t"]
                if res.get("note") == "CAMBIO" or res["status"] == "ALERTA":
                    st["last_change"] = res["t"]
            results.append(res)
            history.append(res)
            save_json(STATE_PATH, state)
            save_json(HISTORY_PATH, history[-3000:])
            print(f"[{res['t']}] {w['name']}: {res['status']} ({res['note']})", flush=True)
            if i < len(watches) - 1:
                time.sleep(defaults.get("pause_seconds", 3))
        if renamed:
            fresh = load_config()
            names = {w["id"]: w["name"] for w in watches}
            for w in fresh["watches"]:
                if w["id"] in names and w.get("auto_name"):
                    w["name"] = names[w["id"]]
                    w.pop("auto_name", None)
            save_config(fresh)
        return results
    finally:
        if fetcher:
            fetcher.close()
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def due_ids(cfg=None, state=None):
    cfg = cfg or load_config()
    state = state if state is not None else load_json(STATE_PATH, {})
    return [w["id"] for w in cfg["watches"] if w.get("enabled", True) and is_due(w, state.get(w["id"], {}), cfg)]


# ================================================================ arranque automático (launchd)
def agent_path(label):
    return LA_DIR / f"{label}.plist"


def venv_python():
    p = DATA / "venv" / "bin" / "python"
    return str(p) if p.exists() else sys.executable


def app_path():
    if APP_PATH_FILE.exists():
        p = APP_PATH_FILE.read_text().strip()
        if p and Path(p).exists():
            return p
    for c in ("/Applications/WebWatch.app", str(Path.home() / "Applications/WebWatch.app")):
        if Path(c).exists():
            return c
    return None


def _launchctl_load(path):
    uid = str(os.getuid())
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(path)], capture_output=True)
    time.sleep(0.3)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], capture_output=True)
    if r.returncode != 0:
        subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True)


def _launchctl_unload(path):
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)


def schedule_install():
    if not IS_MAC:
        raise RuntimeError("La revisión automática solo está disponible en macOS por ahora")
    p = agent_path(LABEL)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [venv_python(), str(BASE / "webwatch.py"), "tick"],
        "WorkingDirectory": str(DATA),
        "StartInterval": TICK_SECONDS,  # launchd la recupera al despertar si se perdió
        "RunAtLoad": True,              # y al iniciar sesión (si el Mac estaba apagado)
        "ProcessType": "Background",
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        "EnvironmentVariables": {"WEBWATCH_DATA": str(DATA),
                                 "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
    }))
    _launchctl_load(p)


def schedule_uninstall():
    p = agent_path(LABEL)
    _launchctl_unload(p)
    p.unlink(missing_ok=True)


def login_item(on):
    p = agent_path(LABEL_MENUBAR)
    if not on:
        p.unlink(missing_ok=True)
        return
    ap = app_path()
    if not IS_MAC or not ap:
        raise RuntimeError("Solo disponible con la app instalada en macOS")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(plistlib.dumps({"Label": LABEL_MENUBAR, "RunAtLoad": True,
                                  "ProgramArguments": ["/usr/bin/open", "-g", "-a", ap, "--args", "--background"]}))


def schedule_status():
    return {"supported": IS_MAC, "installed": agent_path(LABEL).exists(),
            "login_item": agent_path(LABEL_MENUBAR).exists(), "app": app_path() is not None}


# ================================================================ panel (servidor local)
MASK = "••••"


def public_cfg(cfg):
    c = {k: _copy(v) for k, v in cfg.items() if k != "watches"}
    tok = c["telegram"].get("token", "")
    c["telegram"]["token"] = (MASK + tok[-4:]) if tok else ""
    c["excel_full_path"], c["csv_full_path"] = str(excel_path(cfg)), str(csv_path(cfg))
    return c


def build_view():
    cfg = load_config()
    state = load_json(STATE_PATH, {})
    hist = load_json(HISTORY_PATH, [])
    seen = load_json(UI_PATH, {}).get("seen", "")
    by = {}
    for h in hist:
        by.setdefault(h["id"], []).append(h)
    watches = []
    for w in cfg["watches"]:
        st, hs = state.get(w["id"], {}), by.get(w["id"], [])
        data = st.get("data", {})
        prices = [[h["t"], h["price"]] for h in hs if h.get("price") is not None][-60:]
        last = st.get("last")
        nxt = fmt_ts(ts(last["t"]) + retry_interval(w, st, cfg)) if last else None
        watches.append(dict(w, store=store_of(w["url"]), last=last, errors=st.get("errors", 0), prices=prices,
                            min=data.get("min"), max=data.get("max"), currency=data.get("currency"),
                            available=data.get("available"), title=data.get("title"),
                            last_alert=st.get("last_alert"), last_change=st.get("last_change"), next=nxt,
                            blocked=bool(st.get("blocked")),
                            checks=len(hs)))
    alerts = [h for h in hist if h.get("status") == "ALERTA"]
    today = now()[:10]
    lasts = [s["last"]["t"] for s in state.values() if s.get("last")]
    nexts = [w["next"] for w in watches if w.get("enabled", True) and w["next"]]
    return {"config": public_cfg(cfg), "watches": watches, "history": hist[-500:][::-1],
            "unseen": sum(1 for h in alerts if h["t"] > seen),
            "alerts_today": sum(1 for h in alerts if h["t"].startswith(today)),
            "last_run": max(lasts) if lasts else None, "next_run": min(nexts) if nexts else None,
            "schedule": schedule_status(), "playwright": has_playwright(), "platform": platform.system(),
            "now": now(), "version": VERSION, "data_dir": str(DATA), "tick_minutes": TICK_SECONDS // 60}


def clean_watch(d):
    url = (d.get("url") or "").strip()
    pu = urlparse(url)
    if pu.scheme not in ("http", "https") or not pu.netloc:
        raise ValueError("La dirección debe empezar por http:// o https://")
    kind = d.get("type", "change")
    kind = "product" if kind == "price" else kind
    if kind not in ("change", "product", "keyword"):
        raise ValueError("Tipo no válido")
    if kind == "product":
        url = canonical_url(url)
    name = (d.get("name") or "").strip()
    auto_name = not name
    name = name or pu.netloc.replace("www.", "")

    def lst(v):
        return [x.strip() for x in (v if isinstance(v, list) else str(v or "").split(",")) if x.strip()]

    def num(v):
        if v in (None, ""):
            return None
        try:
            return float(str(v).replace(",", "."))
        except ValueError:
            raise ValueError(f"«{v}» no es un número")

    interval = num(d.get("interval"))
    if interval is not None and interval < 0.25:
        raise ValueError("La frecuencia mínima es 15 minutos")
    if interval is not None and store_of(url) and interval < STORE_MIN_HOURS:
        raise ValueError(f"En {STORE_NAMES[store_of(url)]} la frecuencia mínima es {STORE_MIN_HOURS} h "
                         "(más a menudo la tienda acaba pidiendo captcha)")
    w = {"id": d.get("id") or uuid.uuid4().hex[:8], "name": name[:80], "url": url, "type": kind,
         "selector": (d.get("selector") or "").strip(),
         "render": d.get("render") if d.get("render") in ("auto", "http", "browser") else "auto",
         "interval": interval, "enabled": bool(d.get("enabled", True))}
    if auto_name:
        w["auto_name"] = True
    if kind == "change":
        ign = d.get("ignore", [])
        w["ignore"] = [x for x in (ign if isinstance(ign, list) else str(ign).splitlines()) if x.strip()]
    if kind == "product":
        w.update(below=num(d.get("below")), drop_percent=num(d.get("drop_percent")),
                 any_change=bool(d.get("any_change")), notify_min=bool(d.get("notify_min")),
                 notify_stock=bool(d.get("notify_stock", True)))
    if kind == "keyword":
        w["appears"], w["disappears"] = lst(d.get("appears")), lst(d.get("disappears"))
        if not w["appears"] and not w["disappears"]:
            raise ValueError("Indica al menos una palabra que deba aparecer o desaparecer")
    return w


def open_path(path):
    subprocess.Popen(["open" if IS_MAC else "xdg-open", str(path)])


def start_bot_browser(url):
    if not has_playwright():
        raise RuntimeError("Falta Playwright. Borra ~/Library/Application Support/WebWatch/.installed y vuelve a abrir WebWatch")
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("Dirección no válida")
    log = open(LOG_PATH, "a")
    subprocess.Popen([venv_python(), str(BASE / "webwatch.py"), "browser", url], stdout=log, stderr=log,
                     start_new_session=True, cwd=str(DATA))


class Handler(BaseHTTPRequestHandler):
    server_version = "WebWatch"
    protocol_version = "HTTP/1.1"
    last_hit = time.time()

    def log_message(self, *a):
        pass

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        Handler.last_hit = time.time()
        if not self._host_ok():
            return self._send(403, {"error": "host"})
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, (BASE / "web" / "index.html").read_bytes(), "text/html")
        if path == "/api/ping":
            return self._send(200, {"ok": True, "app": "webwatch"})
        if path == "/api/state":
            return self._send(200, build_view())
        self._send(404, {"error": "no encontrado"})

    def do_POST(self):
        Handler.last_hit = time.time()
        if not self._host_ok() or self.headers.get("X-WW") != "1":
            return self._send(403, {"error": "prohibido"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, self.route(self.path, body))
        except Busy as e:
            self._send(409, {"error": str(e)})
        except Blocked as e:
            self._send(400, {"error": str(e), "blocked": True})
        except (ValueError, RuntimeError) as e:
            self._send(400, {"error": str(e)})
        except requests.RequestException as e:
            if self.path == "/api/test":
                return self._send(400, {"error": friendly_error(e, "")})
            msg, tok = str(e), load_config()["telegram"].get("token")
            if tok:
                msg = msg.replace(tok, "***")
            self._send(502, {"error": f"No se pudo conectar: {msg[:160]}"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def route(self, path, b):
        cfg = load_config()
        if path == "/api/watch":
            w = clean_watch(b)
            ws = cfg["watches"]
            idx = next((i for i, x in enumerate(ws) if x["id"] == w["id"]), None)
            if idx is None:
                ws.append(w)
            else:
                old = ws[idx]
                if (old.get("url"), old.get("selector"), old.get("type")) != (w["url"], w["selector"], w["type"]):
                    st = load_json(STATE_PATH, {})
                    st.pop(w["id"], None)  # cambia lo que se vigila: nueva referencia
                    save_json(STATE_PATH, st)
                ws[idx] = w
            save_config(cfg)
            return {"ok": True, "id": w["id"]}
        if path == "/api/watch/delete":
            cfg["watches"] = [w for w in cfg["watches"] if w["id"] != b.get("id")]
            save_config(cfg)
            return {"ok": True}
        if path == "/api/watch/toggle":
            for w in cfg["watches"]:
                if w["id"] == b.get("id"):
                    w["enabled"] = not w.get("enabled", True)
            save_config(cfg)
            return {"ok": True}
        if path == "/api/watch/reset":
            st = load_json(STATE_PATH, {})
            st.pop(b.get("id"), None)
            save_json(STATE_PATH, st)
            return {"ok": True}
        if path == "/api/run":
            return {"results": run_checks([b["id"]] if b.get("id") else None)}
        if path == "/api/test":
            w = clean_watch(b)
            f = Fetcher(cfg["defaults"])
            try:
                r = check(w, {}, f)
            finally:
                f.close()
            out = {k: r.get(k) for k in ("value", "note", "title", "price", "currency", "available", "via")}
            out.update(store=store_of(w["url"]), url=w["url"])
            return out
        if path == "/api/settings":
            tg = b.get("telegram", {})
            tok = tg.get("token", "")
            if tok and not tok.startswith(MASK):
                cfg["telegram"]["token"] = tok.strip()
            elif tok == "":
                cfg["telegram"]["token"] = ""
            cfg["telegram"]["chat_id"] = str(tg.get("chat_id", "")).strip()
            cfg["telegram"]["enabled"] = bool(tg.get("enabled"))
            cfg["notify_desktop"] = bool(b.get("notify_desktop", True))
            if b.get("interval_hours"):
                cfg["interval_hours"] = max(0.25, float(b["interval_hours"]))
            for key in ("excel", "csv"):
                if key in b:
                    cfg[key]["enabled"] = bool(b[key].get("enabled", True))
                    if b[key].get("path"):
                        cfg[key]["path"] = b[key]["path"].strip()
                    if key == "csv" and b[key].get("delimiter") in (";", ","):
                        cfg[key]["delimiter"] = b[key]["delimiter"]
            save_config(cfg)
            return {"ok": True}
        if path == "/api/auto":
            cfg["paused"] = not bool(b.get("on"))
            save_config(cfg)
            if b.get("on") and IS_MAC and not agent_path(LABEL).exists():
                schedule_install()
            return {"ok": True}
        if path == "/api/login-item":
            login_item(bool(b.get("on")))
            return {"ok": True}
        if path == "/api/seen":
            save_json(UI_PATH, dict(load_json(UI_PATH, {}), seen=now()))
            return {"ok": True}
        if path == "/api/browser":
            start_bot_browser(b.get("url") or "https://www.amazon.es")
            return {"ok": True}
        if path == "/api/telegram/detect":
            tok = cfg["telegram"].get("token")
            if not tok:
                raise ValueError("Pega primero el token del bot")
            r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20).json()
            if not r.get("ok"):
                raise ValueError(f"Telegram: {r.get('description', 'token no válido')}")
            chats = {}
            for u in r.get("result", []):
                m = u.get("message") or u.get("channel_post")
                if m:
                    chats[m["chat"]["id"]] = m["chat"].get("first_name") or m["chat"].get("title", "")
            if not chats:
                raise ValueError("No veo mensajes: abre tu bot en Telegram, pulsa Iniciar, escríbele «hola» y repite.")
            cid, name = list(chats.items())[-1]
            cfg["telegram"].update(chat_id=str(cid), enabled=True)
            save_config(cfg)
            return {"chat_id": str(cid), "name": name}
        if path == "/api/telegram/test":
            telegram_send(cfg, "✅ WebWatch conectado: aquí recibirás tus alertas.")
            return {"ok": True}
        if path == "/api/notify/test":
            notify_desktop("WebWatch", "Así se verán tus avisos 👀")
            return {"ok": True}
        if path == "/api/open":
            what = b.get("what")
            if what == "excel":
                open_path(ensure_excel(cfg))
            elif what == "csv":
                open_path(csv_path(cfg) if csv_path(cfg).exists() else DATA)
            elif what == "folder":
                open_path(DATA)
            elif what == "log":
                LOG_PATH.touch()
                open_path(LOG_PATH)
            elif what == "url" and urlparse(b.get("url", "")).scheme in ("http", "https"):
                open_path(b["url"])
            else:
                raise ValueError("No se puede abrir")
            return {"ok": True}
        raise ValueError("ruta desconocida")


def ping():
    try:
        return requests.get(f"http://127.0.0.1:{PORT}/api/ping", timeout=1,
                            proxies={"http": None, "https": None}).ok
    except requests.RequestException:
        return False


def serve_forever(idle=True):
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    if idle:  # en modo navegador se apaga solo tras 20 min sin uso
        def idle_watch():
            while True:
                time.sleep(30)
                if time.time() - Handler.last_hit > 1200:
                    srv.shutdown()
                    return
        threading.Thread(target=idle_watch, daemon=True).start()
    srv.serve_forever()


# ================================================================ comandos
def cmd_ui(_):
    load_config()
    if not ping():
        log = open(LOG_PATH, "a")
        subprocess.Popen([sys.executable, str(BASE / "webwatch.py"), "serve"], stdout=log, stderr=log,
                         start_new_session=True, cwd=str(DATA))
        for _i in range(40):
            if ping():
                break
            time.sleep(0.25)
        else:
            sys.exit(f"No se pudo arrancar el panel. Mira {LOG_PATH}")
    webbrowser.open(f"http://127.0.0.1:{PORT}/")


def cmd_tick(_):
    cfg = load_config()
    if cfg.get("paused"):
        return
    ids = due_ids(cfg)
    if not ids:
        return
    if not online():
        print(f"[{now()}] Sin conexión; lo intento en la próxima vuelta", flush=True)
        return
    try:
        run_checks(ids)
    except Busy:
        pass


def cmd_browser(args):
    from playwright.sync_api import sync_playwright
    lock = open(BROWSER_LOCK, "w")
    fcntl.flock(lock, fcntl.LOCK_EX)  # espera si hay una revisión usando el navegador
    with sync_playwright() as pw:
        ctx = launch_ctx(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        while True:
            try:
                if not ctx.pages:
                    break
                ctx.pages[0].wait_for_timeout(700)
            except Exception:  # noqa: BLE001
                break
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass
    fcntl.flock(lock, fcntl.LOCK_UN)
    lock.close()
    recheck_blocked(args.url)


def recheck_blocked(url):
    """Tras resolver el captcha, el permiso dura poco: revisa ya las webs bloqueadas de esa tienda."""
    store, host = store_of(url), urlparse(url).netloc
    state = load_json(STATE_PATH, {})
    ids = [w["id"] for w in load_config()["watches"]
           if state.get(w["id"], {}).get("blocked")
           and ((store and store_of(w["url"]) == store) or urlparse(w["url"]).netloc == host)]
    if not ids:
        return
    print(f"[{now()}] Navegador del bot cerrado: reviso {len(ids)} web(s) que tenían captcha", flush=True)
    try:
        run_checks(ids)
    except Busy:
        pass


def main():
    ap = argparse.ArgumentParser(description="WebWatch")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("ui").set_defaults(f=cmd_ui)
    sub.add_parser("serve").set_defaults(f=lambda a: serve_forever(True))
    r = sub.add_parser("run")
    r.add_argument("--id")
    r.set_defaults(f=lambda a: run_checks([a.id] if a.id else None))
    sub.add_parser("tick").set_defaults(f=cmd_tick)
    sub.add_parser("install").set_defaults(f=lambda a: (schedule_install(), print("Revisión automática activada")))
    sub.add_parser("uninstall").set_defaults(f=lambda a: (schedule_uninstall(), print("Revisión automática quitada")))
    li = sub.add_parser("login-item")
    li.add_argument("state", choices=["on", "off"])
    li.set_defaults(f=lambda a: login_item(a.state == "on"))
    b = sub.add_parser("browser")
    b.add_argument("url")
    b.set_defaults(f=cmd_browser)
    args = ap.parse_args()
    (args.f if args.cmd else cmd_ui)(args)


if __name__ == "__main__":
    main()
