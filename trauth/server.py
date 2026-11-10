"""T.R.A.U.T.H. add-on server.

Serves the T.R.A.U.T.H. web app through Home Assistant ingress and relays
requests to the Home Assistant API using the Supervisor token, so the
browser never needs its own Home Assistant credentials.

Routes
  GET  /                       -> www/index.html
  GET  /api/me                 -> the Home Assistant user viewing the app
  GET  /api/data               -> saved app data (profiles, chores, ...)
  POST /api/data               -> merge + save app data
  GET  /api/ha/<path>          -> Home Assistant REST API (GET)
  POST /api/ha/<path>          -> Home Assistant REST API (POST)
  POST /api/update             -> download the newest app screen from GitHub now

Self-updating: the app screen (www/index.html) is downloaded from GitHub
when the add-on starts and every few hours after, so new versions arrive
with a restart (or on their own) instead of a Home Assistant add-on update.
If GitHub can't be reached, the copy bundled with the add-on is used.

App data lives in /share/trauth/trauth.json so it survives reinstalls,
and is included in Home Assistant backups.
Only the Python standard library is used.
"""

import json
import shutil
import time
import mimetypes
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8099"))
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
CORE_API = os.environ.get("HA_URL", "http://supervisor/core/api").rstrip("/")
WWW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www")
SHARE_DIR = os.environ.get("SHARE_DIR", "/share/trauth")
DATA_FILE = os.environ.get("DATA_FILE", os.path.join(SHARE_DIR, "trauth.json"))
LEGACY_DATA = "/data/trauth.json"
UI_CACHE = os.path.join(SHARE_DIR, "www", "index.html")
UI_URL = os.environ.get("UI_URL", "https://raw.githubusercontent.com/kylejtrauth-del/trauth-home/main/trauth/www/index.html")
UI_REFRESH_SECONDS = 3 * 60 * 60
MAX_BODY = 2_000_000

_lock = threading.Lock()


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, DATA_FILE)


def migrate_legacy_data():
    """Move app data from the old /data location to /share (one time)."""
    try:
        if not os.path.exists(DATA_FILE) and os.path.exists(LEGACY_DATA):
            os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
            shutil.copyfile(LEGACY_DATA, DATA_FILE)
            print("Moved app data to", DATA_FILE, flush=True)
    except OSError as e:
        print("Data migration skipped:", e, flush=True)


def fetch_ui():
    """Download the newest app screen from GitHub. Returns True if it changed."""
    try:
        req = urllib.request.Request(UI_URL + "?t=" + str(int(time.time())), headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
        text = body.decode("utf-8", "replace")
        if resp.status != 200 or "<!DOCTYPE html>" not in text[:200] or "T.R.A.U.T.H." not in text:
            raise ValueError("unexpected content")
        old = b""
        if os.path.exists(UI_CACHE):
            with open(UI_CACHE, "rb") as f:
                old = f.read()
        if body == old:
            return False
        os.makedirs(os.path.dirname(UI_CACHE), exist_ok=True)
        tmp = UI_CACHE + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, UI_CACHE)
        print("App screen updated from GitHub", flush=True)
        return True
    except Exception as e:
        print("App screen update skipped:", e, flush=True)
        return False


def ui_updater():
    while True:
        fetch_ui()
        time.sleep(UI_REFRESH_SECONDS)


class Handler(BaseHTTPRequestHandler):
    server_version = "TRAUTH/1.0"

    def log_message(self, fmt, *args):  # keep the add-on log quiet
        pass

    # ---------- helpers ----------
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("body too large")
        return self.rfile.read(length) if length else b""

    def _path(self):
        return self.path.split("?", 1)[0]

    # ---------- Home Assistant relay ----------
    def _relay(self, method):
        sub = self.path[len("/api/ha"):]  # keeps the query string
        if not sub.startswith("/") or ".." in sub:
            return self._json(400, {"error": "bad path"})
        body = self._body() if method == "POST" else None
        req = urllib.request.Request(CORE_API + sub, data=body, method=method)
        req.add_header("Authorization", "Bearer " + TOKEN)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                ctype = resp.headers.get("Content-Type", "application/json")
                return self._send(resp.status, resp.read(), ctype)
        except urllib.error.HTTPError as e:
            return self._send(e.code, e.read() or b"{}", e.headers.get("Content-Type", "application/json"))
        except Exception as e:  # network trouble talking to Home Assistant
            return self._json(502, {"error": str(e)})

    # ---------- routes ----------
    def do_GET(self):
        p = self._path()
        if p.startswith("/api/ha/"):
            return self._relay("GET")
        if p == "/api/me":
            return self._json(200, {
                "id": self.headers.get("X-Remote-User-Id", ""),
                "name": self.headers.get("X-Remote-User-Name", ""),
                "display": self.headers.get("X-Remote-User-Display-Name", ""),
            })
        if p == "/api/data":
            with _lock:
                return self._json(200, load_data())
        return self._static(p)

    do_HEAD = do_GET

    def do_POST(self):
        p = self._path()
        if p.startswith("/api/ha/"):
            return self._relay("POST")
        if p == "/api/update":
            changed = fetch_ui()
            return self._json(200, {"updated": changed})
        if p == "/api/data":
            try:
                patch = json.loads(self._body() or b"{}")
                if not isinstance(patch, dict):
                    raise ValueError("expected an object")
            except Exception as e:
                return self._json(400, {"error": str(e)})
            with _lock:
                data = load_data()
                data.update(patch)
                save_data(data)
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})

    def _static(self, p):
        rel = "index.html" if p in ("", "/") else p.lstrip("/")
        if rel == "index.html" and os.path.isfile(UI_CACHE):
            with open(UI_CACHE, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        full = os.path.realpath(os.path.join(WWW, rel))
        if not full.startswith(os.path.realpath(WWW) + os.sep) or not os.path.isfile(full):
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)


if __name__ == "__main__":
    migrate_legacy_data()
    threading.Thread(target=ui_updater, daemon=True).start()
    print(f"T.R.A.U.T.H. listening on port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
