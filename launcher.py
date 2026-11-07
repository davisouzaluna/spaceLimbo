"""Inicializador do spaceLimbo para quem não programa.

Chamado pelo INICIAR.bat (Windows) ou iniciar.sh (Linux/macOS). Ele:
  1. instala/atualiza as bibliotecas (e o yt-dlp, que precisa de atualização frequente);
  2. na primeira vez, pergunta o token do bot e cria o arquivo .env;
  3. se você quiser compartilhar o painel, instala o cloudflared;
  4. liga o bot e abre o painel no navegador.

Só usa a biblioteca padrão do Python até o passo 4.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENV_FILE = BASE / ".env"
REQUIREMENTS = BASE / "requirements.txt"
PORTAL = "https://discord.com/developers/applications"
INVITE_PERMISSIONS = 3165184  # Ver canais, Enviar mensagens, Inserir links, Conectar, Falar
IS_WINDOWS = platform.system() == "Windows"


def titulo(texto: str) -> None:
    print("\n" + "-" * 64)
    print("  " + texto)
    print("-" * 64)


def perguntar_sim_nao(pergunta: str, padrao: bool = True) -> bool:
    dica = "S/n" if padrao else "s/N"
    while True:
        r = input(f"{pergunta} [{dica}]: ").strip().lower()
        if not r:
            return padrao
        if r in ("s", "sim", "y", "yes"):
            return True
        if r in ("n", "nao", "não", "no"):
            return False


# ------------------------------------------------------------------ .env

def ler_env() -> dict[str, str]:
    dados: dict[str, str] = {}
    if ENV_FILE.exists():
        for linha in ENV_FILE.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                dados[k.strip()] = v.strip().strip('"').strip("'")
    return dados


def salvar_env(dados: dict[str, str]) -> None:
    linhas = ["# Criado pelo assistente do spaceLimbo. Para refazer, rode o CONFIGURAR.", ""]
    linhas += [f"{k}={v}" for k, v in dados.items()]
    ENV_FILE.write_text("\n".join(linhas) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ passos

def instalar_dependencias() -> bool:
    titulo("Verificando as peças do spaceLimbo (pode demorar na primeira vez)")
    pip = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    ok = subprocess.run([*pip, "-r", str(REQUIREMENTS)]).returncode == 0
    # O YouTube muda com frequência; o yt-dlp mais novo costuma resolver músicas que pararam de tocar.
    subprocess.run([*pip, "-U", "yt-dlp"])
    if not all(importlib.util.find_spec(m) for m in ("discord", "yt_dlp")):
        print("\n✖ Não consegui instalar as bibliotecas. Confira a internet e abra de novo.")
        return False
    if not ok:
        print("⚠ Não consegui atualizar agora (sem internet?). Seguindo com o que já está instalado.")
    print("✔ Tudo pronto.")
    return True


def checar_token(token: str) -> tuple[bool | None, dict]:
    """True = válido, False = recusado, None = não deu para verificar (sem internet etc.)."""
    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": f"Bot {token}", "User-Agent": "DiscordBot (spaceLimbo, 1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True, json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return False, {}
        return None, {}
    except Exception:
        return None, {}


def assistente(atual: dict[str, str]) -> dict[str, str]:
    titulo("Configuração do spaceLimbo — passo 1 de 3: criar o bot no Discord")
    print(
        "Isso é feito só uma vez:\n"
        "  1. Vou abrir o site do Discord para desenvolvedores (faça login se pedir).\n"
        '  2. Clique em "New Application", dê o nome spaceLimbo e confirme.\n'
        '  3. No menu da esquerda, clique em "Bot".\n'
        '  4. Clique em "Reset Token", confirme e depois em "Copy".\n'
        "Se você já tem o token, é só colar abaixo."
    )
    if not atual.get("DISCORD_TOKEN") or perguntar_sim_nao("\nAbrir o site do Discord agora?", True):
        webbrowser.open(PORTAL)

    info: dict = {}
    while True:
        token = input("\nCole o token aqui (botão direito do mouse cola) e aperte Enter:\n> ").strip().strip('"')
        if not token and atual.get("DISCORD_TOKEN"):
            token = atual["DISCORD_TOKEN"]
            print("(mantendo o token que já estava salvo)")
        if len(token) < 50:
            print("✖ Isso não parece um token (ele é bem comprido). Tente copiar de novo.")
            continue
        valido, info = checar_token(token)
        if valido is False:
            print("✖ O Discord recusou esse token. Clique em Reset Token de novo e copie o novo.")
            continue
        if valido is None:
            print("⚠ Não consegui conferir o token agora (internet?). Vou salvar mesmo assim.")
        else:
            print(f"✔ Token certo! Seu bot se chama {info.get('username', 'spaceLimbo')}.")
        break

    titulo("Passo 2 de 3: quem vai usar o painel?")
    print(
        "O painel (a tela para organizar as músicas) abre neste computador.\n"
        "(Os comandos /play no Discord funcionam para todo mundo de qualquer jeito.)\n"
    )
    rede = perguntar_sim_nao(
        "Outros computadores ou celulares da SUA REDE (mesmo Wi-Fi/roteador) vão abrir o painel?",
        atual.get("PANEL_HOST") == "0.0.0.0",
    )
    compartilhar = perguntar_sim_nao(
        "Amigos em OUTRAS casas vão abrir o painel? (crio um link na internet)",
        atual.get("SHARE_PANEL", "1") == "1",
    )

    dados = {
        "DISCORD_TOKEN": token,
        "PANEL_TOKEN": atual.get("PANEL_TOKEN") or secrets.token_urlsafe(9),
        "SHARE_PANEL": "1" if compartilhar else "0",
        "PANEL_HOST": "0.0.0.0" if rede else "127.0.0.1",
    }
    # mantém outros ajustes que a pessoa tenha colocado à mão
    for k, v in atual.items():
        dados.setdefault(k, v)
    salvar_env(dados)
    print(f"✔ Configuração salva. Senha do painel: {dados['PANEL_TOKEN']}")

    titulo("Passo 3 de 3: colocar o bot no seu servidor")
    if info.get("id"):
        convite = (
            f"https://discord.com/oauth2/authorize?client_id={info['id']}"
            f"&scope=bot+applications.commands&permissions={INVITE_PERMISSIONS}"
        )
        print("Vou abrir o convite. Escolha o servidor e clique em Autorizar.\n" + convite)
        input("Aperte Enter para abrir o convite…")
        webbrowser.open(convite)
    else:
        print("Quando o bot ligar, o link de convite vai aparecer nesta janela.")
    input("\nTudo certo! Aperte Enter para ligar o spaceLimbo…")
    return dados


def garantir_cloudflared() -> bool:
    sys.path.insert(0, str(BASE))
    from tunnel import find_cloudflared  # importa só agora: config.py lê o .env recém-criado

    if find_cloudflared():
        return True
    titulo("Instalando o cloudflared (cria o link do painel para os amigos)")
    if IS_WINDOWS and shutil.which("winget"):
        subprocess.run([
            "winget", "install", "-e", "--id", "Cloudflare.cloudflared", "--silent",
            "--accept-package-agreements", "--accept-source-agreements",
        ])
        if find_cloudflared():
            print("✔ cloudflared instalado.")
            return True
    print(
        "⚠ Não consegui instalar o cloudflared sozinho. O bot vai funcionar, mas o painel fica só neste PC.\n"
        "  Para instalar à mão: https://developers.cloudflare.com/cloudflare-one/networks/connectors/"
        "cloudflare-tunnel/downloads/"
    )
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicializador do spaceLimbo")
    parser.add_argument("--configurar", action="store_true", help="refaz a configuração")
    args = parser.parse_args()
    os.chdir(BASE)

    print("\n   s p a c e L i m b o   🪐\n")
    if not instalar_dependencias():
        return 1

    env = ler_env()
    if args.configurar or not env.get("DISCORD_TOKEN"):
        try:
            env = assistente(env)
        except (KeyboardInterrupt, EOFError):
            print("\nConfiguração cancelada.")
            return 1

    os.environ.setdefault("OPEN_BROWSER", "1")
    sys.path.insert(0, str(BASE))
    import config  # importa depois do .env existir

    if config.SHARE_PANEL and not garantir_cloudflared():
        config.SHARE_PANEL = False

    import bot

    return bot.run()


if __name__ == "__main__":
    sys.exit(main())
