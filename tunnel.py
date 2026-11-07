"""Coloca o painel na internet com um Cloudflare Quick Tunnel (grátis, sem criar conta).

O programa `cloudflared` cria um endereço https://algo.trycloudflare.com que leva ao painel
rodando no seu PC. O endereço muda toda vez que o bot é ligado.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path

import config

log = logging.getLogger("spacelimbo.tunnel")
URL_RE = re.compile(rb"https://[a-z0-9-]+\.trycloudflare\.com")

# onde o launcher.py baixa o cloudflared quando não dá para instalar pelo sistema
LOCAL_CLOUDFLARED = Path(__file__).resolve().parent / "ferramentas" / (
    "cloudflared.exe" if os.name == "nt" else "cloudflared"
)


def find_cloudflared() -> str | None:
    candidates = [config.CLOUDFLARED_PATH, shutil.which("cloudflared"), str(LOCAL_CLOUDFLARED)]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(str(Path(local) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe"))
    for pf in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if pf:
            candidates.append(str(Path(pf) / "cloudflared" / "cloudflared.exe"))
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


class Tunnel:
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.url: str | None = None
        self._drain_task: asyncio.Task | None = None

    async def start(self, local_url: str, timeout: float = 45) -> str | None:
        exe = find_cloudflared()
        if not exe:
            log.warning("cloudflared não encontrado; o painel ficará só no seu PC.")
            return None
        self.proc = await asyncio.create_subprocess_exec(
            exe, "tunnel", "--no-autoupdate", "--url", local_url,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            self.url = await asyncio.wait_for(self._read_url(), timeout)
        except Exception as exc:
            log.warning("Não consegui abrir o túnel (%s).", exc or "tempo esgotado")
            await self.stop()
            return None
        # continua lendo a saída para o buffer não encher e travar o cloudflared
        self._drain_task = asyncio.create_task(self._drain())
        return self.url

    async def _read_url(self) -> str:
        assert self.proc and self.proc.stderr
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                raise RuntimeError("o cloudflared fechou")
            m = URL_RE.search(line)
            if m:
                return m.group().decode()

    async def _drain(self) -> None:
        assert self.proc and self.proc.stderr
        while await self.proc.stderr.readline():
            pass

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except asyncio.TimeoutError:
                self.proc.kill()
        self.proc = None
