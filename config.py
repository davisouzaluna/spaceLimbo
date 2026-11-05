"""Configuração do spaceLimbo.

Lê o arquivo .env sem precisar de python-dotenv (menos uma dependência).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(BASE_DIR / ".env")

# Token do bot (Discord Developer Portal → Bot → Reset Token)
TOKEN = os.environ.get("DISCORD_TOKEN", "")

# Se definido, os comandos slash são sincronizados só neste servidor (aparecem na hora).
DEV_GUILD_ID = int(os.environ.get("DEV_GUILD_ID", "0") or 0)

# Áudio
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "ffmpeg")
DEFAULT_VOLUME = float(os.environ.get("DEFAULT_VOLUME", "0.5"))  # 0.0 a 1.5
IDLE_TIMEOUT = int(os.environ.get("IDLE_TIMEOUT", "300"))  # segundos parado antes de sair do canal

EMBED_COLOR = 0x7B5CFF
