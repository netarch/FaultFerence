"""Lightweight stdlib HTTP server for the FaultFerence 2D Detective game.

Usage (from repo root):
    .venv/bin/python dashboard/server.py --port 8050
"""

import argparse
import datetime
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import game  # noqa: E402

STATIC_DIR = os.path.join(HERE, "static")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

STORE = game.SessionStore()


def _daily_seed() -> int:
    d = datetime.date.today()
    return d.year * 10000 + d.month * 100 + d.day


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers["Content-Length"]) if "Content-Length" in self.headers else 0
        return json.loads(self.rfile.read(n)) if n > 0 else {}

    def _static(self, path: str) -> None:
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_error(404)
            return
        ext = os.path.splitext(full)[1]
        ctype = CONTENT_TYPES[ext]
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}

        if method == "GET" and url.path == "/api/config":
            self._json(
                200,
                {
                    "topologies": list(game.TOPOLOGIES.keys()),
                    "failure_modes": list(game.FAILURE_MODES.keys()),
                    "inference_modes": list(game.INFERENCE_MODES),
                    "weapons": list(game.WEAPONS),
                    "daily_seed": _daily_seed(),
                },
            )
            return

        if method == "POST" and url.path == "/api/new":
            b = self._body()
            raw_seed = str(b["seed"]).strip()
            if raw_seed == "daily":
                seed = _daily_seed()
            elif raw_seed == "":
                seed = int(time.time() * 1000) % 1_000_000
            else:
                seed = int(raw_seed)
            s = game.GameSession(
                topology=b["topology"],
                failure_mode=b["failure_mode"],
                inference=b["inference"],
                seed=seed,
                num_pairs=int(b["num_pairs"]),
                drop_prob=float(b["drop_prob"]),
                cred_mass=float(b["cred_mass"]),
            )
            STORE.add(s)
            with s.lock:
                self._json(200, {"state": s.state_json(), "actions": s.candidate_actions()})
            return

        if method == "GET" and url.path == "/api/actions":
            s = STORE.get(q["sid"])
            with s.lock:
                self._json(200, {"actions": s.candidate_actions()})
            return

        if method == "POST" and url.path == "/api/apply":
            b = self._body()
            s = STORE.get(b["sid"])
            with s.lock:
                res = s.apply(b["action"])
                res["actions"] = s.candidate_actions()
                self._json(200, res)
            return

        if method == "POST" and url.path == "/api/gadget":
            b = self._body()
            s = STORE.get(b["sid"])
            with s.lock:
                res = s.run_gadget(b["gadget"])
                res["actions"] = s.candidate_actions()
                self._json(200, res)
            return

        if method == "POST" and url.path == "/api/accuse":
            b = self._body()
            s = STORE.get(b["sid"])
            with s.lock:
                res = s.accuse(int(b["node"]))
                res["actions"] = s.candidate_actions()
                self._json(200, res)
            return

        if method == "POST" and url.path == "/api/inference":
            b = self._body()
            s = STORE.get(b["sid"])
            with s.lock:
                self._json(200, {"state": s.set_inference(b["inference"])})
            return

        if method == "GET" and url.path == "/api/fives":
            s = STORE.get(q["sid"])
            with s.lock:
                self._json(200, s.fives(float(q["lambda"]), int(q["k"]), int(q["top"])))
            return

        if method == "GET" and not url.path.startswith("/api/"):
            self._static(url.path)
            return

        self.send_error(404)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def main():
    ap = argparse.ArgumentParser(description="FaultFerence 2D Detective game server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8050)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"FaultFerence 2D Detective running on http://{args.host}:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
