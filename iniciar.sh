#!/usr/bin/env sh
# spaceLimbo para Linux/macOS: ./iniciar.sh   (refazer configuração: ./iniciar.sh --configurar)
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv || { echo "Instale o Python 3.10+ (Ubuntu: sudo apt install python3 python3-venv)"; exit 1; }
fi
exec .venv/bin/python launcher.py "$@"
