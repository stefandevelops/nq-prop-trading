#!/bin/zsh
# Builds "Trading Desk.app" in the project folder: double-click it to start the desk server and open the app.
# Usage: zsh desk/make_launcher.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/Trading Desk.app"
mkdir -p "$ROOT/signals/log"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script \"cd \" & quoted form of \"$ROOT\" & \" && (nohup .venv-nautilus/bin/python desk/server.py --open >> signals/log/desk.out 2>&1 &)\""
echo "Built: $APP"
echo "Drag it to the Dock or Applications. The first time it captures the screen, macOS asks for Screen Recording permission for 'Trading Desk'."
