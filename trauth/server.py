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

App data lives in /data/trauth.json, which Home Assistant backs up.
Only the Python standard library is used.
"""

import json
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
DATA_FILE = os.environ.get("DATA_FILE", "/data/trauth.json")
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
        full = os.path.realpath(os.path.join(WWW, rel))
        if not full.startswith(os.path.realpath(WWW) + os.sep) or not os.path.isfile(full):
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)


if __name__ == "__main__":
    print(f"T.R.A.U.T.H. listening on port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
