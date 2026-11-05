"""Configuração do spaceLimbo.

Lê o arquivo .env sem precisar de python-dotenv (menos uma dependência).
"""
import os
import shutil
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

# Painel web
PANEL_HOST = os.environ.get("PANEL_HOST", "127.0.0.1")
PANEL_PORT = int(os.environ.get("PANEL_PORT", "8080"))
PANEL_TOKEN = os.environ.get("PANEL_TOKEN", "")  # senha do painel; vazio = sem senha (só use localmente!)
PANEL_URL = os.environ.get("PANEL_URL", f"http://{PANEL_HOST}:{PANEL_PORT}")

# Abrir o painel no navegador ao ligar (o INICIAR liga isso)
OPEN_BROWSER = os.environ.get("OPEN_BROWSER", "0") == "1"


def _find_ffmpeg() -> str:
    """FFMPEG_PATH do .env → ffmpeg instalado no sistema → ffmpeg embutido do pacote imageio-ffmpeg."""
    if os.environ.get("FFMPEG_PATH"):
        return os.environ["FFMPEG_PATH"]
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


# Áudio
FFMPEG_PATH = _find_ffmpeg()
DEFAULT_VOLUME = float(os.environ.get("DEFAULT_VOLUME", "0.5"))  # 0.0 a 1.5
IDLE_TIMEOUT = int(os.environ.get("IDLE_TIMEOUT", "300"))  # segundos parado antes de sair do canal

# Banco de dados (SQLite, já vem com o Python)
DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "spacelimbo.db"))

EMBED_COLOR = 0x7B5CFF
