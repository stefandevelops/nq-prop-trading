"""Screen-reading signal agent for Bookmap and DeepCharts (macOS). Alerts only: it never places orders.

Every few seconds it captures the Bookmap / DeepCharts windows, sends them to a vision model together with
the playbook rules (ORB 15m and IB acceptance breakouts, order-flow confirmation), today's levels from
backtest/premarket_levels.py and its own recent readings, and asks for a structured read. Long/short
signals trigger a voice alert and a macOS notification with the MNQ size; every reading is logged.

Models (set in .env, never printed):
  GEMINI_API_KEY=...        Google AI Studio key, free tier (default when present)
  OPENAI_API_KEY=...        any OpenAI-compatible vision model (--provider openai)
  (neither)                 local Ollama, free and private: `ollama pull qwen2.5vl:7b` (--provider ollama)

Usage:
  .venv-nautilus/bin/python signals/screen_agent.py --list-windows        # what it can see
  .venv-nautilus/bin/python signals/screen_agent.py                       # live, 9:25-13:05 ET only
  .venv-nautilus/bin/python signals/screen_agent.py --replay              # Bookmap replay: any time, session time read from the chart
  .venv-nautilus/bin/python signals/screen_agent.py --once --image a.png  # analyse saved screenshots
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from common import load_config, size_position  # noqa: E402

ET = ZoneInfo("America/New_York")
LOG_DIR = ROOT / "signals" / "log"
LEVELS = ROOT / "signals" / "levels.json"
DEFAULT_MODELS = {"gemini": "gemini-flash-latest", "openai": "gpt-4.1-mini", "ollama": "qwen2.5vl:7b"}
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

RULES = """You are an order-flow assistant for a discretionary NQ/MNQ futures trader on a prop-firm challenge.
You see screenshots of Bookmap (heatmap of resting liquidity, volume bubbles = aggressive trades, CVD) and/or
DeepCharts (candles/footprint, delta, big-trade bubbles, volume profile). You give alerts; the trader decides.

Only two setups produce long/short signals (first side to trigger only, times are New York):
1. ORB 15m (from 9:45): opening range = high/low of 9:30-9:45. Trigger: a 5-minute candle CLOSES beyond it.
   Stop: far side of the range (skip if wider than 120 points). Target 2R. Max 2 attempts per direction.
2. IB acceptance (from 10:30): initial balance = high/low of 9:30-10:30. Trigger: TWO consecutive 5-minute
   closes beyond the IB. Stop 30 points back inside the IB edge. Target: IB edge + half the IB range.
No new entries after 13:00. No entries in the first 15 minutes (the range is still forming).

Order-flow confirmation (report it for every trigger):
- delta: does delta / CVD agree with the break on the trigger candle(s)?
- big_trades: do large aggressive trades print in the BODY of the candle (follow-through) or in the WICK
  (absorption, stand aside)?
- liquidity: on a retest of the edge, does passive liquidity on the heatmap/DOM hold and reload (good), or
  get pulled / absorb against the trade (bad)?
confirm = "yes" if all three agree, "partial" if one or two, "no" if none or absorption against the trade.

Signal values:
- "long"/"short": the trigger condition is met NOW (the candle has closed), the time window allows it, and
  you can actually read the range edges. Give price, stop and target as numbers read from the chart.
- "watch": price is within about 20 points of an opening-range/IB edge or a key level, or a trigger candle is
  still forming.
- "none": anything else, including when you cannot read the chart clearly (say so in notes).
Be conservative: a missed signal costs nothing, a false one costs money. Never invent prices you cannot see.

Reply with ONE JSON object only, no prose:
{"signal": "none|watch|long|short", "setup": "ORB 15m|IB acceptance|none", "confidence": 0-100,
 "price": number|null, "stop": number|null, "target": number|null,
 "range_high": number|null, "range_low": number|null,
 "trigger": "what happened, one sentence",
 "delta": "agrees|against|unclear", "big_trades": "body|wick|none|unclear", "liquidity": "holding|pulled|unclear",
 "confirm": "yes|partial|no", "invalidation": "what would cancel it", "notes": "one short sentence"}"""


# ----------------------------------------------------------------------------- environment

def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def phase(now: datetime, replay: bool) -> str:
    if replay:
        return "REPLAY: read the session time from the chart's time axis and apply the same time rules."
    m = now.hour * 60 + now.minute
    if now.weekday() >= 5 or m < 9 * 60 + 30:
        return "Before the open: no entries, report 'watch' at most."
    if m < 9 * 60 + 45:
        return "9:30-9:45: opening range forming, no entries."
    if m < 10 * 60 + 30:
        return "9:45-10:30: ORB 15m active; initial balance still forming."
    if m < 13 * 60:
        return "10:30-13:00: ORB 15m and IB acceptance both active."
    return "After 13:00: no new entries, 'watch' or 'none' only."


# ----------------------------------------------------------------------------- screen capture

def check_permission() -> None:
    import Quartz
    if not Quartz.CGPreflightScreenCaptureAccess():
        Quartz.CGRequestScreenCaptureAccess()
        sys.exit("Screen Recording permission is missing. System Settings > Privacy & Security > Screen Recording: "
                 "enable the app you run this from (Terminal or Cursor), restart that app, then run again.")


def find_windows(patterns: list[str]) -> list[dict]:
    import Quartz
    opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    out = []
    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
        owner, title = w.get("kCGWindowOwnerName", "") or "", w.get("kCGWindowName", "") or ""
        b = w.get("kCGWindowBounds", {})
        if w.get("kCGWindowLayer", 1) != 0 or b.get("Width", 0) < 400 or b.get("Height", 0) < 300:
            continue
        if any(p.lower() in f"{owner} {title}".lower() for p in patterns):
            out.append({"id": int(w["kCGWindowNumber"]), "owner": owner, "title": title,
                        "size": f"{int(b['Width'])}x{int(b['Height'])}"})
    return out


def capture(windows: list[dict], display: int | None, folder: Path, max_px: int) -> list[tuple[str, Path]]:
    shots = []
    targets = [(f"display {display}", ["-D", str(display)])] if display else \
              [(f"{w['owner']} - {w['title']}".strip(" -"), ["-o", "-l", str(w["id"])]) for w in windows]
    for i, (label, args) in enumerate(targets):
        path = folder / f"shot{i}.jpg"
        r = subprocess.run(["screencapture", "-x", "-t", "jpg", *args, str(path)], capture_output=True)
        if r.returncode or not path.exists():
            print(f"  capture failed for {label}")
            continue
        subprocess.run(["sips", "-Z", str(max_px), str(path)], capture_output=True)
        shots.append((label, path))
    return shots


# ----------------------------------------------------------------------------- model

def ask_model(provider: str, model: str, prompt: str, images: list[tuple[str, Path]], timeout: int) -> str:
    b64 = [(label, base64.b64encode(p.read_bytes()).decode(), "png" if p.suffix.lower() == ".png" else "jpeg") for label, p in images]
    if provider == "ollama":
        text = prompt + "\n\nImages, in order: " + "; ".join(label for label, _, _ in b64)
        r = requests.post("http://localhost:11434/api/chat", timeout=timeout, json={
            "model": model, "stream": False, "format": "json", "options": {"temperature": 0.1},
            "messages": [{"role": "system", "content": RULES},
                         {"role": "user", "content": text, "images": [b for _, b, _ in b64]}]})
        r.raise_for_status()
        return r.json()["message"]["content"]
    url = GEMINI_URL if provider == "gemini" else os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/chat/completions"
    key = os.environ["GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"]
    content = [{"type": "text", "text": prompt}]
    for label, b, mime in b64:
        content += [{"type": "text", "text": f"Screenshot: {label}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b}"}}]
    r = requests.post(url, timeout=timeout, headers={"Authorization": f"Bearer {key}"}, json={
        "model": model, "temperature": 0.1,
        "messages": [{"role": "system", "content": RULES}, {"role": "user", "content": content}]})
    if r.status_code == 429:
        raise RuntimeError("rate limited (429)")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in reply: {text[:120]!r}")
    d = json.loads(m.group(0))
    d["signal"] = str(d.get("signal", "none")).lower()
    if d["signal"] not in ("none", "watch", "long", "short"):
        d["signal"] = "none"
    return d


# ----------------------------------------------------------------------------- alerts and logging

def notify(title: str, body: str, speak: str | None) -> None:
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    subprocess.run(["osascript", "-e", f'display notification "{esc(body)}" with title "{esc(title)}" sound name "Glass"'],
                   capture_output=True)
    if speak:
        subprocess.Popen(["say", speak])


def describe(d: dict, cfg: dict) -> tuple[str, str]:
    price, stop = d.get("price"), d.get("stop")
    size = ""
    if isinstance(price, (int, float)) and isinstance(stop, (int, float)) and price != stop:
        risk = cfg["plan"]["risk_per_trade"]
        q = size_position(cfg, "MNQ", risk, abs(price - stop))
        size = f" | {abs(price - stop):.0f} pt stop -> {q} MNQ at ${risk:.0f}" + (" (too wide, skip)" if q < 1 else "")
    head = f"{d['signal'].upper()} {d.get('setup', '')} @ {price} (conf {d.get('confidence', '?')}, confirm {d.get('confirm', '?')})"
    body = (f"stop {stop} target {d.get('target')}{size} | delta {d.get('delta')}, big trades {d.get('big_trades')}, "
            f"liquidity {d.get('liquidity')} | {d.get('trigger', '')}")
    return head, body


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apps", default="Bookmap,DeepCharts", help="comma-separated window owner/title matches")
    p.add_argument("--display", type=int, help="capture a whole display (1 = main) instead of matching windows")
    p.add_argument("--interval", type=float, default=20.0, help="seconds between readings (Gemini free tier: keep >= 15)")
    p.add_argument("--provider", choices=["gemini", "openai", "ollama"], help="default: gemini if GEMINI_API_KEY is set, else ollama")
    p.add_argument("--model", help="model name (defaults: %s)" % DEFAULT_MODELS)
    p.add_argument("--min-confidence", type=int, default=60, help="alert on long/short only at or above this confidence")
    p.add_argument("--cooldown", type=int, default=300, help="seconds before the same signal can alert again")
    p.add_argument("--watch-alerts", action="store_true", help="also notify (silently) on 'watch' readings")
    p.add_argument("--replay", action="store_true", help="run at any time; the model reads the session time from the chart")
    p.add_argument("--anytime", action="store_true", help="run outside 9:25-13:05 ET")
    p.add_argument("--max-px", type=int, default=1600, help="resize screenshots to at most this many pixels")
    p.add_argument("--save-all", action="store_true", help="keep every screenshot, not just long/short ones")
    p.add_argument("--image", nargs="+", type=Path, help="analyse these image files instead of the screen")
    p.add_argument("--once", action="store_true", help="one reading, then exit")
    p.add_argument("--dry-run", action="store_true", help="capture and build the prompt but don't call the model")
    p.add_argument("--list-windows", action="store_true", help="list matching windows and exit")
    args = p.parse_args()

    load_env()
    cfg = load_config()
    provider = args.provider or ("gemini" if os.environ.get("GEMINI_API_KEY") else "ollama")
    model = args.model or DEFAULT_MODELS[provider]
    patterns = [s.strip() for s in args.apps.split(",") if s.strip()]

    if not args.image:
        check_permission()
    if args.list_windows:
        ws = find_windows(patterns)
        for w in ws:
            print(f"  id {w['id']:6d}  {w['size']:>10s}  {w['owner']} - {w['title']}")
        print(f"{len(ws)} window(s) match {patterns}." + ("" if ws else " Open the apps on screen, or use --display 1."))
        return

    levels = json.loads(LEVELS.read_text()) if LEVELS.exists() else None
    today = datetime.now(ET).strftime("%Y-%m-%d")
    if levels and levels.get("date") != today and not args.replay:
        print(f"Note: {LEVELS.name} is from {levels.get('date')}; run backtest/premarket_levels.py for today's levels.")
    day_dir = LOG_DIR / today
    day_dir.mkdir(parents=True, exist_ok=True)
    history: list[str] = []
    last_alert: dict[str, float] = {}
    print(f"Screen agent: {provider} / {model}, every {args.interval:g}s, alerts at confidence >= {args.min_confidence}. "
          f"Signals only; you place the orders. Ctrl+C to stop.")

    while True:
        now = datetime.now(ET)
        m = now.hour * 60 + now.minute
        if not (args.replay or args.anytime or args.image) and not (9 * 60 + 25 <= m <= 13 * 60 + 5 and now.weekday() < 5):
            if args.once:
                sys.exit("Outside 9:25-13:05 ET on a weekday. Use --replay or --anytime.")
            time.sleep(30)
            continue
        t0 = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            if args.image:
                shots = [(p.name, p) for p in args.image]
            else:
                shots = capture(find_windows(patterns) if not args.display else [], args.display, Path(tmp), args.max_px)
            if not shots:
                print(f"{now:%H:%M:%S} no Bookmap/DeepCharts window on screen (see --list-windows)")
            else:
                prompt = (f"Now: {now:%A %Y-%m-%d %H:%M:%S} New York time. Phase: {phase(now, args.replay)}\n"
                          f"Risk per trade ${cfg['plan']['risk_per_trade']:.0f} on MNQ.\n"
                          f"Today's levels (from the data feed): {json.dumps(levels) if levels else 'not available, read them from the chart'}\n"
                          f"Your last readings (oldest first): {' | '.join(history[-5:]) or 'none yet'}")
                if args.dry_run:
                    print(prompt, "\nImages:", [label for label, _ in shots])
                    return
                try:
                    d = parse(ask_model(provider, model, prompt, shots, timeout=90))
                except Exception as e:  # keep running through network/model hiccups
                    print(f"{now:%H:%M:%S} model error: {e}")
                    d = None
                if d:
                    head, body = describe(d, cfg)
                    print(f"{now:%H:%M:%S} {head} | {body} | {d.get('notes', '')}  [{time.time() - t0:.1f}s]")
                    history.append(f"{now:%H:%M} {d['signal']} {d.get('setup', '')} {d.get('trigger', '')}"[:200])
                    rec = {"time": now.isoformat(timespec="seconds"), "provider": provider, "model": model, **d}
                    key = f"{d['signal']}|{d.get('setup')}"
                    actionable = d["signal"] in ("long", "short") and (d.get("confidence") or 0) >= args.min_confidence
                    if actionable and time.time() - last_alert.get(key, 0) > args.cooldown:
                        last_alert[key] = time.time()
                        notify(f"NQ {head}", body, f"{d['signal']} signal, {d.get('setup', '')}, confirmation {d.get('confirm', 'unclear')}")
                        rec["alerted"] = True
                    elif d["signal"] == "watch" and args.watch_alerts and time.time() - last_alert.get(key, 0) > args.cooldown:
                        last_alert[key] = time.time()
                        notify("NQ watch", d.get("trigger", ""), None)
                    if (d["signal"] in ("long", "short") or args.save_all) and not args.image:
                        stamp = now.strftime("%H%M%S")
                        for i, (_, path) in enumerate(shots):
                            dest = day_dir / f"{stamp}_{d['signal']}_{i}.jpg"
                            dest.write_bytes(path.read_bytes())
                        rec["screenshots"] = f"{stamp}_{d['signal']}_*.jpg"
                    with open(day_dir / "readings.jsonl", "a") as f:
                        f.write(json.dumps(rec) + "\n")
        if args.once or args.image:
            return
        time.sleep(max(1.0, args.interval - (time.time() - t0)))


if __name__ == "__main__":
    main()
