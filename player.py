"""Busca (yt-dlp), fila e reprodução (FFmpeg) — o coração do bot."""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import asdict, dataclass
from urllib.parse import parse_qs, urlparse

import discord
import yt_dlp

import config

log = logging.getLogger("spacelimbo.player")

URL_RE = re.compile(r"^https?://", re.I)

YDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",  # força IPv4 (evita bloqueios em algumas redes)
}

# -reconnect*: se o stream HTTP cair, o FFmpeg reconecta em vez de encerrar a música
FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin"

# ?t=90, &t=1m30s, #t=300, ?start=90 (YouTube e afins)
LINK_TIME_RE = re.compile(r"[?&#](?:t|start|time_continue)=([0-9hms]+)", re.I)
UNIT_RE = re.compile(r"(\d+)([hms])")
UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}
FFMPEG_OPTS = "-vn"  # descarta vídeo


def fmt_time(seconds: int) -> str:
    """Tempo no formato m:ss ou h:mm:ss (0 vira 0:00)."""
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def parse_time(text: str) -> tuple[int, str]:
    """Lê um momento digitado pela pessoa.

    Aceita "90", "1:30", "1:02:03", "1m30s" e relativos "+30" / "-10".
    Devolve (segundos, modo), com modo "abs", "+" ou "-".
    """
    text = text.strip().lower().replace(" ", "")
    mode = "abs"
    if text[:1] in "+-" and text[:1]:
        mode, text = text[0], text[1:]
    try:
        if ":" in text:
            seconds = 0
            for part in text.split(":"):
                seconds = seconds * 60 + int(part)
        elif text.isdigit():
            seconds = int(text)
        else:
            units = UNIT_RE.findall(text)
            if not units or "".join(n + u for n, u in units) != text:
                raise ValueError
            seconds = sum(int(n) * UNIT_SECONDS[u] for n, u in units)
    except ValueError:
        raise ValueError("Não entendi o tempo. Exemplos: 1:30, 90, 5m, +30, -10") from None
    return seconds, mode


def link_start_time(url: str) -> int:
    """Segundo inicial pedido no link (ex.: youtu.be/abc?t=300). 0 se não houver."""
    m = LINK_TIME_RE.search(url)
    if not m:
        return 0
    value = m.group(1).lower()
    if value.isdigit():
        return int(value)
    return sum(int(n) * UNIT_SECONDS[u] for n, u in UNIT_RE.findall(value))


def fmt_duration(seconds: int) -> str:
    """Duração de uma música: sem duração conhecida (0) significa transmissão ao vivo."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "ao vivo"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


@dataclass
class Track:
    title: str
    url: str           # link da página (o link do áudio expira, então é resolvido na hora de tocar)
    duration: int = 0
    thumbnail: str = ""
    requester: str = ""
    start: int = 0     # segundo em que começa a tocar (vem do ?t= do link)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict, requester: str = "") -> "Track":
        return cls(
            title=d.get("title") or "Sem título",
            url=d["url"],
            duration=int(d.get("duration") or 0),
            thumbnail=d.get("thumbnail") or "",
            requester=requester or d.get("requester") or "",
            start=int(d.get("start") or 0),
        )


# ---------------------------------------------------------------- busca

def _thumb(entry: dict) -> str:
    if entry.get("thumbnail"):
        return entry["thumbnail"]
    thumbs = entry.get("thumbnails") or []
    return thumbs[-1].get("url", "") if thumbs else ""


def _entry_to_track(entry: dict, requester: str) -> Track:
    url = entry.get("webpage_url") or entry.get("url") or ""
    if url and not URL_RE.match(url):  # alguns resultados vêm só com o ID do vídeo
        url = f"https://www.youtube.com/watch?v={url}"
    return Track(
        title=entry.get("title") or "Sem título",
        url=url,
        duration=int(entry.get("duration") or 0),
        thumbnail=_thumb(entry),
        requester=requester,
    )


def _search_sync(query: str, limit: int, allow_playlist: bool) -> list[dict]:
    opts = {**YDL_OPTS, "extract_flat": "in_playlist", "noplaylist": not allow_playlist}
    target = query if URL_RE.match(query) else f"ytsearch{limit}:{query}"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)
    if not info:
        return []
    entries = info.get("entries")
    if entries is None:
        return [info]
    return [e for e in entries if e]


async def search(query: str, *, limit: int = 1, requester: str = "", allow_playlist: bool = True) -> list[Track]:
    """Busca por texto ou link. yt-dlp é síncrono (bloqueante), então roda numa thread."""
    query = query.strip()
    entries = await asyncio.to_thread(_search_sync, query, limit, allow_playlist)
    tracks = [_entry_to_track(e, requester) for e in entries if (e.get("webpage_url") or e.get("url"))]
    if len(tracks) == 1 and URL_RE.match(query):
        tracks[0].start = link_start_time(query)
    return tracks


def _stream_sync(url: str) -> dict:
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)
    if "entries" in info:
        info = info["entries"][0]
    return info


def _stream_expiry(stream_url: str) -> float:
    """Até quando o link do áudio vale. O YouTube informa no parâmetro expire=; senão, 30 min."""
    try:
        return float(parse_qs(urlparse(stream_url).query)["expire"][0])
    except (KeyError, ValueError, IndexError):
        return time.time() + 1800


async def resolve_stream(track: Track) -> tuple[str, float]:
    """Devolve (link do áudio, horário em que ele expira)."""
    info = await asyncio.to_thread(_stream_sync, track.url)
    track.duration = track.duration or int(info.get("duration") or 0)
    track.thumbnail = track.thumbnail or _thumb(info)
    return info["url"], _stream_expiry(info["url"])


# ---------------------------------------------------------------- player por servidor

class GuildPlayer:
    """Uma fila independente para cada servidor (guild)."""

    LOOP_MODES = ("off", "track", "queue")

    def __init__(self, bot: discord.Client, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.queue: list[Track] = []
        self.current: Track | None = None
        self.volume = config.DEFAULT_VOLUME
        self.loop = "off"
        self.text_channel: discord.abc.Messageable | None = None
        self.last_activity = time.time()
        self._lock = asyncio.Lock()
        self._skip = False
        self._started = 0.0
        self._paused_at: float | None = None
        self._paused_total = 0.0
        # Cada vc.play() ganha um número. Ao avançar/voltar, o "after" da fonte antiga
        # é ignorado (senão ele pularia para a próxima música).
        self._gen = 0
        # Link do áudio da música atual, reaproveitado no /seek sem rodar o yt-dlp de novo
        self._stream: tuple[Track, str, float] | None = None

    # --- atalhos
    @property
    def guild(self) -> discord.Guild | None:
        return self.bot.get_guild(self.guild_id)

    @property
    def vc(self) -> discord.VoiceClient | None:
        g = self.guild
        return g.voice_client if g else None  # type: ignore[return-value]

    @property
    def position(self) -> int:
        if not self.current:
            return 0
        end = self._paused_at or time.monotonic()
        return max(0, int(end - self._started - self._paused_total))

    # --- conexão
    async def connect(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        vc = self.vc
        if vc and vc.is_connected():
            if vc.channel.id != channel.id:
                await vc.move_to(channel)
            return vc
        return await channel.connect(self_deaf=True)

    async def disconnect(self) -> None:
        self.stop()
        vc = self.vc
        if vc:
            await vc.disconnect(force=False)

    # --- fila
    def add(self, tracks: list[Track], *, front: bool = False) -> None:
        if front:
            self.queue[0:0] = tracks
        else:
            self.queue.extend(tracks)
        self.last_activity = time.time()

    async def start_if_idle(self) -> None:
        vc = self.vc
        if vc and self.current is None and not vc.is_playing() and not vc.is_paused():
            await self.play_next()

    async def play_next(self, skipped: bool = False) -> None:
        async with self._lock:
            prev, self.current = self.current, None
            if prev is not None:
                if self.loop == "track" and not skipped:
                    self.queue.insert(0, prev)
                elif self.loop == "queue":
                    self.queue.append(prev)

            vc = self.vc
            if vc is None or not vc.is_connected():
                return

            while self.queue:
                track = self.queue.pop(0)
                try:
                    stream_url = await self._stream_for(track)
                except Exception as exc:  # vídeo removido, bloqueado por região etc.
                    log.warning("Falha ao resolver %s: %s", track.url, exc)
                    await self.announce(f"⚠️ Não consegui tocar **{track.title}** — pulando.")
                    continue

                start, track.start = track.start, 0  # o ?t= do link vale só na primeira vez
                if track.duration and start >= track.duration:
                    start = 0
                self.current = track
                self.last_activity = time.time()
                self._start_source(vc, stream_url, start)
                if prev is None or prev.url != track.url or self.loop != "track":
                    await self.announce(embed=self.now_playing_embed())
                return

    async def _stream_for(self, track: Track) -> str:
        """Link do áudio: reaproveita o da música atual se ainda não expirou."""
        if self._stream and self._stream[0] is track and time.time() < self._stream[2] - 60:
            return self._stream[1]
        url, expires = await resolve_stream(track)
        self._stream = (track, url, expires)
        return url

    def _start_source(self, vc: discord.VoiceClient, stream_url: str, offset: int = 0) -> None:
        """Abre o FFmpeg já no segundo `offset` (-ss antes do -i: pula direto, sem baixar o começo)."""
        before = f"-ss {offset} {FFMPEG_BEFORE}" if offset else FFMPEG_BEFORE
        audio = discord.FFmpegPCMAudio(
            stream_url,
            executable=config.FFMPEG_PATH,
            before_options=before,
            options=FFMPEG_OPTS,
        )
        source = discord.PCMVolumeTransformer(audio, volume=self.volume)
        self._gen += 1
        gen = self._gen
        self._started, self._paused_at, self._paused_total = time.monotonic() - offset, None, 0.0
        vc.play(source, after=lambda error: self._after(error, gen))

    def _after(self, error: Exception | None, gen: int) -> None:
        # Chamado pelo discord.py numa THREAD separada quando a fonte de áudio termina.
        if error:
            log.error("Erro na reprodução: %s", error)
        if gen != self._gen:
            return  # fonte substituída por um /seek: não é o fim da música
        skipped, self._skip = self._skip, False
        asyncio.run_coroutine_threadsafe(self.play_next(skipped=skipped), self.bot.loop)

    # --- controles
    def skip(self) -> bool:
        vc = self.vc
        if vc and (vc.is_playing() or vc.is_paused()):
            self._skip = True
            vc.stop()  # dispara _after → próxima música
            return True
        return False

    def stop(self) -> None:
        self.queue.clear()
        self.current = None  # sem "atual", o _after não tem o que repetir
        self._stream = None
        vc = self.vc
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

    async def seek(self, position: int) -> int:
        """Vai para `position` segundos da música atual. Devolve a posição usada."""
        track, vc = self.current, self.vc
        if track is None or vc is None or not (vc.is_playing() or vc.is_paused()):
            raise ValueError("Nada tocando.")
        if not track.duration:
            raise ValueError("Não dá para avançar numa transmissão ao vivo.")
        position = max(0, min(int(position), track.duration - 1))
        async with self._lock:
            if self.current is not track:  # a música mudou enquanto esperava
                raise ValueError("A música mudou; tente de novo.")
            stream_url = await self._stream_for(track)
            was_paused = vc.is_paused()
            self._gen += 1  # invalida o "after" da fonte atual antes de pará-la
            vc.stop()
            self._start_source(vc, stream_url, position)
            if was_paused:
                vc.pause()
                self._paused_at = time.monotonic()
        self.last_activity = time.time()
        return position

    def pause(self) -> bool:
        vc = self.vc
        if vc and vc.is_playing():
            vc.pause()
            self._paused_at = time.monotonic()
            return True
        return False

    def resume(self) -> bool:
        vc = self.vc
        if vc and vc.is_paused():
            vc.resume()
            if self._paused_at:
                self._paused_total += time.monotonic() - self._paused_at
            self._paused_at = None
            self.last_activity = time.time()
            return True
        return False

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.5, volume))
        vc = self.vc
        if vc and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = self.volume

    def set_loop(self, mode: str) -> None:
        if mode not in self.LOOP_MODES:
            raise ValueError("Modo inválido")
        self.loop = mode

    def shuffle(self) -> None:
        random.shuffle(self.queue)

    def remove(self, index: int) -> Track:
        return self.queue.pop(index)

    def move(self, src: int, dst: int) -> None:
        track = self.queue.pop(src)
        self.queue.insert(dst, track)

    # --- saída
    async def announce(self, content: str | None = None, *, embed: discord.Embed | None = None) -> None:
        if self.text_channel is None:
            return
        try:
            await self.text_channel.send(content=content, embed=embed)
        except discord.HTTPException:
            pass

    def now_playing_embed(self) -> discord.Embed:
        t = self.current
        if not t:
            return discord.Embed(description="Nada tocando.", color=config.EMBED_COLOR)
        total = t.duration
        pos = self.position
        bar = ""
        if total:
            filled = int(16 * pos / total)
            bar = "▬" * filled + "🔘" + "▬" * (16 - filled)
        e = discord.Embed(title=t.title, url=t.url, color=config.EMBED_COLOR)
        e.set_author(name="🪐 Tocando agora")
        e.description = f"{bar}\n`{fmt_time(pos)} / {fmt_duration(total)}`" if bar else None
        if t.thumbnail:
            e.set_thumbnail(url=t.thumbnail)
        loop_txt = {"off": "desligado", "track": "música", "queue": "fila"}[self.loop]
        e.set_footer(text=f"Pedido por {t.requester or '—'} • Volume {int(self.volume * 100)}% • Loop: {loop_txt}")
        return e

    def state(self) -> dict:
        vc = self.vc
        connected = bool(vc and vc.is_connected())
        return {
            "guild_id": str(self.guild_id),
            "connected": connected,
            "channel": {"id": str(vc.channel.id), "name": vc.channel.name} if connected else None,
            "current": self.current.to_dict() if self.current else None,
            "position": min(self.position, self.current.duration) if self.current and self.current.duration else self.position,
            "paused": bool(vc and vc.is_paused()),
            "volume": round(self.volume * 100),
            "loop": self.loop,
            "queue": [t.to_dict() for t in self.queue],
        }


class PlayerManager:
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self._players: dict[int, GuildPlayer] = {}

    def get(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer(self.bot, guild_id)
        return self._players[guild_id]

    def all(self) -> list[GuildPlayer]:
        return list(self._players.values())