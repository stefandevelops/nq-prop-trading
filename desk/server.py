"""Trading Desk: local app server for the whole project (levels, checklist, screen agent, journal, dashboard).

    .venv-nautilus/bin/python desk/server.py          # then open http://localhost:8765
    .venv-nautilus/bin/python desk/server.py --open   # opens the browser too (used by the Trading Desk launcher)

Listens on 127.0.0.1 only. Write actions need the app's own header, so other websites can't trigger them.
API keys can be saved to .env from the app but are never sent back.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import socket
import subprocess
import sys
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv-nautilus" / "bin" / "python")
ENV = ROOT / ".env"
LOG_DIR = ROOT / "signals" / "log"
AGENT_OUT = LOG_DIR / "agent.out"
ET = ZoneInfo("America/New_York")
PORT = 8765
STATIC = ("app.html", "dashboard.html", "dashboard/", "desk/index.html", "desk/desk.js", "desk/desk.css", "signals/log/")
DOCS = {"checklist": "CHECKLIST.md", "playbook": "PLAYBOOK.md"}
KEY_NAMES = ("GEMINI_API_KEY", "OPENAI_API_KEY", "DATABENTO_API_KEY")

sys.path.insert(0, str(ROOT / "signals"))
agent_proc: subprocess.Popen | None = None


def env_keys() -> set[str]:
    if not ENV.exists():
        return set()
    return {ln.split("=", 1)[0].strip() for ln in ENV.read_text().splitlines()
            if "=" in ln and not ln.lstrip().startswith("#") and ln.split("=", 1)[1].strip()}


def save_key(name: str, value: str) -> None:
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if ln.split("=", 1)[0].strip() != name] + [f"{name}={value}"]
    ENV.write_text("\n".join(lines) + "\n")
    os.chmod(ENV, 0o600)


def status() -> dict:
    try:
        import Quartz
        from screen_agent import find_windows
        screen_ok = bool(Quartz.CGPreflightScreenCaptureAccess())
        windows = [f"{w['owner']} {w['title']}".strip() for w in find_windows(["Bookmap", "DeepCharts"])] if screen_ok else []
    except Exception:
        screen_ok, windows = False, []
    try:
        ollama = [m["name"] for m in requests.get("http://localhost:11434/api/tags", timeout=0.5).json().get("models", [])]
        ollama_ok = True
    except Exception:
        ollama, ollama_ok = [], False
    levels = ROOT / "signals" / "levels.json"
    cfg = json.loads((ROOT / "challenge.json").read_text())
    keys = env_keys()
    return {
        "now_et": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
        "screen_permission": screen_ok, "windows": windows,
        "keys": {k: k in keys for k in KEY_NAMES},
        "ollama_running": ollama_ok, "ollama_models": ollama,
        "agent_running": agent_proc is not None and agent_proc.poll() is None,
        "levels": json.loads(levels.read_text()) if levels.exists() else None,
        "plan": cfg["plan"], "account": cfg["account"],
        "mnq_cost": cfg["costs"]["MNQ"]["commission_rt"] + cfg["costs"]["MNQ"]["slippage_ticks"] * 0.5,
    }


def readings(day: str) -> list[dict]:
    f = LOG_DIR / day / "readings.jsonl"
    if not f.exists():
        return []
    out = []
    for ln in f.read_text().splitlines()[-300:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


def tail(path: Path, n: int = 80) -> str:
    return "\n".join(path.read_text(errors="replace").splitlines()[-n:]) if path.exists() else ""


def start_agent(opts: dict) -> str:
    global agent_proc
    if agent_proc is not None and agent_proc.poll() is None:
        return "already running"
    cmd = [PY, "-u", str(ROOT / "signals" / "screen_agent.py"), "--interval", str(float(opts.get("interval", 20)))]
    if opts.get("provider") in ("gemini", "openai", "ollama"):
        cmd += ["--provider", opts["provider"]]
    if re.fullmatch(r"[\w .:/-]{1,60}", str(opts.get("model", ""))):
        cmd += ["--model", opts["model"]]
    if re.fullmatch(r"[\w ,.-]{1,120}", str(opts.get("apps", ""))):
        cmd += ["--apps", opts["apps"]]
    for flag in ("replay", "anytime", "watch_alerts", "save_all"):
        if opts.get(flag):
            cmd.append("--" + flag.replace("_", "-"))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = open(AGENT_OUT, "a")
    out.write(f"\n--- started {datetime.now(ET):%Y-%m-%d %H:%M:%S} ET ---\n")
    out.flush()
    agent_proc = subprocess.Popen(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
    return "started"


def stop_agent() -> str:
    global agent_proc
    if agent_proc is None or agent_proc.poll() is not None:
        return "not running"
    agent_proc.terminate()
    try:
        agent_proc.wait(5)
    except subprocess.TimeoutExpired:
        agent_proc.kill()
    agent_proc = None
    return "stopped"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):
        if "/api/" in self.path and self.command == "POST":
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def host_ok(self) -> bool:
        return self.headers.get("Host", "") in (f"localhost:{PORT}", f"127.0.0.1:{PORT}")

    def send_json(self, obj, code: int = 200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.host_ok():
            return self.send_error(403)
        url = urlparse(self.path)
        path = url.path.lstrip("/")
        if path in ("", "index.html"):
            self.path = "/desk/index.html"
            return super().do_GET()
        if path == "api/status":
            return self.send_json(status())
        if path == "api/readings":
            day = parse_qs(url.query).get("day", [datetime.now(ET).strftime("%Y-%m-%d")])[0]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                return self.send_error(400)
            return self.send_json({"day": day, "readings": readings(day), "console": tail(AGENT_OUT)})
        if path == "api/doc":
            name = DOCS.get(parse_qs(url.query).get("name", [""])[0])
            return self.send_json({"text": (ROOT / name).read_text()}) if name else self.send_error(404)
        if ".." in path or not any(path == s or (s.endswith("/") and path.startswith(s)) for s in STATIC):
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self):
        if not self.host_ok() or self.headers.get("X-Desk") != "1":
            return self.send_error(403)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self.send_error(400)
        path = urlparse(self.path).path
        if path == "/api/agent/start":
            return self.send_json({"result": start_agent(body)})
        if path == "/api/agent/stop":
            return self.send_json({"result": stop_agent()})
        if path == "/api/levels":
            r = subprocess.run([PY, str(ROOT / "backtest" / "premarket_levels.py")], cwd=ROOT,
                               capture_output=True, text=True, timeout=180)
            return self.send_json({"ok": r.returncode == 0, "output": (r.stdout + r.stderr)[-6000:]})
        if path == "/api/key":
            name, value = body.get("name"), str(body.get("value", "")).strip()
            if name not in KEY_NAMES or not re.fullmatch(r"[A-Za-z0-9_\-.]{10,200}", value):
                return self.send_json({"ok": False, "error": "invalid key name or format"}, 400)
            save_key(name, value)
            return self.send_json({"ok": True})
        return self.send_error(404)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--open", action="store_true", help="open the app in the browser")
    args = p.parse_args()
    url = f"http://localhost:{PORT}/"
    with socket.socket() as s:
        busy = s.connect_ex(("127.0.0.1", PORT)) == 0
    if busy:
        print(f"Port {PORT} is already in use (Trading Desk probably running): {url}")
        if args.open:
            webbrowser.open(url)
        return
    atexit.register(stop_agent)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Trading Desk running at {url}  (Ctrl+C to stop)")
    if args.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
