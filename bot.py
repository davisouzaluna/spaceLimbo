"""spaceLimbo — bot de música para Discord com painel web.

Execute:  python bot.py
"""
from __future__ import annotations

import asyncio
import logging
import random
import sys
import time
import webbrowser
from typing import Literal

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import database
from player import PlayerManager, Track, fmt_duration, search
from web import start_web

log = logging.getLogger("spacelimbo")

# Ver canais, Enviar mensagens, Inserir links, Conectar, Falar
INVITE_PERMISSIONS = 3165184


def panel_link(base: str) -> str:
    """Link do painel com a senha embutida (o navegador guarda e apaga da barra de endereço)."""
    return f"{base}/#senha={config.PANEL_TOKEN}" if config.PANEL_TOKEN else base


def banner(*lines: str) -> None:
    print("\n" + "=" * 64)
    for line in lines:
        print("  " + line)
    print("=" * 64 + "\n", flush=True)


class SpaceLimbo(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()  # inclui guilds e voice_states; nada privilegiado
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.players = PlayerManager(self)
        self.web_runner = None
        self._welcomed = False

    async def setup_hook(self) -> None:
        await self.add_cog(Music(self))
        if config.DEV_GUILD_ID:
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        log.info("Conectado como %s (%s servidores)", self.user, len(self.guilds))
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/play"))
        if not self._welcomed:
            self._welcomed = True
            invite = discord.utils.oauth_url(
                self.user.id,
                permissions=discord.Permissions(INVITE_PERMISSIONS),
                scopes=("bot", "applications.commands"),
            )
            names = ", ".join(g.name for g in self.guilds) or "nenhum ainda"
            banner(
                f"{self.user.name} está ONLINE no Discord!",
                f"Servidores: {names}",
                "",
                "Para colocar o bot em outro servidor, abra:",
                invite,
            )

    async def close(self) -> None:
        if self.web_runner:
            await self.web_runner.cleanup()
        await super().close()


async def playlist_names(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    current = current.lower()
    return [
        app_commands.Choice(name=p["name"], value=p["name"])
        for p in database.list_playlists()
        if current in p["name"].lower()
    ][:25]


def simple_embed(text: str) -> discord.Embed:
    return discord.Embed(description=text, color=config.EMBED_COLOR)


class Music(commands.Cog):
    def __init__(self, bot: SpaceLimbo) -> None:
        self.bot = bot
        self.idle_check.start()

    async def cog_unload(self) -> None:
        self.idle_check.cancel()

    # Todos os comandos deste cog só funcionam dentro de servidores
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("Use meus comandos dentro de um servidor.", ephemeral=True)
            return False
        return True

    def player(self, interaction: discord.Interaction):
        p = self.bot.players.get(interaction.guild_id)
        p.text_channel = interaction.channel
        return p

    async def ensure_voice(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
            await interaction.followup.send(embed=simple_embed("🎧 Entre em um canal de voz primeiro."))
            return False
        await self.player(interaction).connect(member.voice.channel)
        return True

    # ------------------------------------------------------------ reprodução

    async def _enqueue(self, interaction: discord.Interaction, busca: str, *, front: bool) -> None:
        await interaction.response.defer(thinking=True)
        if not await self.ensure_voice(interaction):
            return
        p = self.player(interaction)
        try:
            tracks = await search(busca, requester=interaction.user.display_name)
        except Exception as exc:
            await interaction.followup.send(embed=simple_embed(f"❌ Erro na busca: `{exc}`"))
            return
        if not tracks:
            await interaction.followup.send(embed=simple_embed("🔭 Nada encontrado."))
            return
        p.add(tracks, front=front)
        if len(tracks) == 1:
            t = tracks[0]
            where = "a seguir" if front else f"na posição {len(p.queue)}"
            msg = f"➕ **[{t.title}]({t.url})** `{fmt_duration(t.duration)}` — {where}"
        else:
            msg = f"➕ **{len(tracks)}** músicas adicionadas à fila."
        await interaction.followup.send(embed=simple_embed(msg))
        await p.start_if_idle()

    @app_commands.command(name="play", description="Toca uma música pelo nome ou link (YouTube, SoundCloud…)")
    @app_commands.describe(busca="Nome da música ou link")
    async def play(self, interaction: discord.Interaction, busca: str):
        await self._enqueue(interaction, busca, front=False)

    @app_commands.command(name="playnext", description="Coloca uma música no início da fila")
    @app_commands.describe(busca="Nome da música ou link")
    async def playnext(self, interaction: discord.Interaction, busca: str):
        await self._enqueue(interaction, busca, front=True)

    @app_commands.command(name="skip", description="Pula a música atual")
    async def skip(self, interaction: discord.Interaction):
        ok = self.player(interaction).skip()
        await interaction.response.send_message(embed=simple_embed("⏭️ Pulada." if ok else "Nada tocando."))

    @app_commands.command(name="pause", description="Pausa a música")
    async def pause(self, interaction: discord.Interaction):
        ok = self.player(interaction).pause()
        await interaction.response.send_message(embed=simple_embed("⏸️ Pausado." if ok else "Nada tocando."))

    @app_commands.command(name="resume", description="Continua a música pausada")
    async def resume(self, interaction: discord.Interaction):
        ok = self.player(interaction).resume()
        await interaction.response.send_message(embed=simple_embed("▶️ Continuando." if ok else "Nada pausado."))

    @app_commands.command(name="stop", description="Para a música e limpa a fila")
    async def stop(self, interaction: discord.Interaction):
        self.player(interaction).stop()
        await interaction.response.send_message(embed=simple_embed("⏹️ Parado e fila limpa."))

    @app_commands.command(name="leave", description="Sai do canal de voz")
    async def leave(self, interaction: discord.Interaction):
        await self.player(interaction).disconnect()
        await interaction.response.send_message(embed=simple_embed("👋 Até a próxima órbita."))

    @app_commands.command(name="nowplaying", description="Mostra a música atual")
    async def nowplaying(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.player(interaction).now_playing_embed())

    @app_commands.command(name="queue", description="Mostra a fila")
    @app_commands.describe(pagina="Página da fila")
    async def queue(self, interaction: discord.Interaction, pagina: app_commands.Range[int, 1, 100] = 1):
        p = self.player(interaction)
        per_page = 10
        pages = max(1, -(-len(p.queue) // per_page))
        pagina = min(pagina, pages)
        start = (pagina - 1) * per_page
        lines = [
            f"`{i + 1}.` [{t.title}]({t.url}) `{fmt_duration(t.duration)}`"
            for i, t in enumerate(p.queue[start:start + per_page], start=start)
        ]
        e = discord.Embed(title="🌌 Fila", color=config.EMBED_COLOR)
        if p.current:
            e.add_field(name="Tocando agora", value=f"[{p.current.title}]({p.current.url})", inline=False)
        e.add_field(name="Próximas", value="\n".join(lines) or "Fila vazia.", inline=False)
        total = sum(t.duration for t in p.queue)
        e.set_footer(text=f"Página {pagina}/{pages} • {len(p.queue)} músicas • {fmt_duration(total)}")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="volume", description="Ajusta o volume (0–150)")
    async def volume(self, interaction: discord.Interaction, valor: app_commands.Range[int, 0, 150]):
        self.player(interaction).set_volume(valor / 100)
        await interaction.response.send_message(embed=simple_embed(f"🔊 Volume em **{valor}%**."))

    @app_commands.command(name="loop", description="Repetir: desligado, música ou fila")
    async def loop(self, interaction: discord.Interaction, modo: Literal["off", "track", "queue"]):
        self.player(interaction).set_loop(modo)
        nomes = {"off": "desligado", "track": "música atual", "queue": "fila inteira"}
        await interaction.response.send_message(embed=simple_embed(f"🔁 Loop: **{nomes[modo]}**."))

    @app_commands.command(name="shuffle", description="Embaralha a fila")
    async def shuffle(self, interaction: discord.Interaction):
        self.player(interaction).shuffle()
        await interaction.response.send_message(embed=simple_embed("🔀 Fila embaralhada."))

    @app_commands.command(name="remove", description="Remove uma música da fila pela posição")
    async def remove(self, interaction: discord.Interaction, posicao: app_commands.Range[int, 1, 10000]):
        p = self.player(interaction)
        if posicao > len(p.queue):
            await interaction.response.send_message(embed=simple_embed("Posição inválida."), ephemeral=True)
            return
        t = p.remove(posicao - 1)
        await interaction.response.send_message(embed=simple_embed(f"🗑️ Removida: **{t.title}**"))

    @app_commands.command(name="painel", description="Link do painel web do spaceLimbo")
    async def painel(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=simple_embed(f"🛰️ Painel: {config.PANEL_URL}"), ephemeral=True
        )

    # ------------------------------------------------------------ playlists

    playlist = app_commands.Group(name="playlist", description="Playlists salvas do spaceLimbo")

    @playlist.command(name="tocar", description="Coloca uma playlist salva na fila")
    @app_commands.autocomplete(nome=playlist_names)
    async def pl_tocar(self, interaction: discord.Interaction, nome: str, embaralhar: bool = False):
        await interaction.response.defer(thinking=True)
        pl = database.get_playlist_by_name(nome)
        if not pl:
            await interaction.followup.send(embed=simple_embed("Playlist não encontrada."))
            return
        rows = database.get_tracks(pl["id"])
        if not rows:
            await interaction.followup.send(embed=simple_embed("Essa playlist está vazia."))
            return
        if not await self.ensure_voice(interaction):
            return
        tracks = [Track.from_dict(r, interaction.user.display_name) for r in rows]
        if embaralhar:
            random.shuffle(tracks)
        p = self.player(interaction)
        p.add(tracks)
        await interaction.followup.send(embed=simple_embed(f"📀 **{pl['name']}** — {len(tracks)} músicas na fila."))
        await p.start_if_idle()

    @playlist.command(name="listar", description="Lista as playlists salvas")
    async def pl_listar(self, interaction: discord.Interaction):
        pls = database.list_playlists()
        text = "\n".join(f"• **{p['name']}** — {p['count']} músicas ({fmt_duration(p['duration'])})" for p in pls)
        await interaction.response.send_message(embed=simple_embed(text or "Nenhuma playlist ainda. Crie pelo painel!"))

    @playlist.command(name="criar", description="Cria uma playlist vazia")
    async def pl_criar(self, interaction: discord.Interaction, nome: str):
        try:
            database.create_playlist(nome)
        except ValueError as exc:
            await interaction.response.send_message(embed=simple_embed(str(exc)), ephemeral=True)
            return
        await interaction.response.send_message(embed=simple_embed(f"✨ Playlist **{nome}** criada."))

    @playlist.command(name="adicionar", description="Adiciona uma música (ou playlist do YouTube) a uma playlist")
    @app_commands.autocomplete(nome=playlist_names)
    async def pl_adicionar(self, interaction: discord.Interaction, nome: str, busca: str):
        await interaction.response.defer(thinking=True)
        pl = database.get_playlist_by_name(nome)
        if not pl:
            await interaction.followup.send(embed=simple_embed("Playlist não encontrada."))
            return
        tracks = await search(busca)
        if not tracks:
            await interaction.followup.send(embed=simple_embed("Nada encontrado."))
            return
        database.add_tracks(pl["id"], [t.to_dict() for t in tracks])
        what = f"**{tracks[0].title}**" if len(tracks) == 1 else f"{len(tracks)} músicas"
        await interaction.followup.send(embed=simple_embed(f"➕ {what} → **{pl['name']}**"))

    @playlist.command(name="salvar_fila", description="Salva a música atual + fila como uma nova playlist")
    async def pl_salvar_fila(self, interaction: discord.Interaction, nome: str):
        p = self.player(interaction)
        tracks = ([p.current] if p.current else []) + p.queue
        if not tracks:
            await interaction.response.send_message(embed=simple_embed("A fila está vazia."), ephemeral=True)
            return
        try:
            pl = database.create_playlist(nome)
        except ValueError as exc:
            await interaction.response.send_message(embed=simple_embed(str(exc)), ephemeral=True)
            return
        database.add_tracks(pl["id"], [t.to_dict() for t in tracks])
        await interaction.response.send_message(embed=simple_embed(f"💾 Fila salva como **{nome}** ({len(tracks)} músicas)."))

    # ------------------------------------------------------------ manutenção

    @tasks.loop(seconds=60)
    async def idle_check(self):
        now = time.time()
        for p in self.bot.players.all():
            vc = p.vc
            if not vc or not vc.is_connected():
                continue
            humans = [m for m in vc.channel.members if not m.bot]
            if vc.is_playing() and humans:
                p.last_activity = now
                continue
            if now - p.last_activity > config.IDLE_TIMEOUT:
                await p.disconnect()
                await p.announce(embed=simple_embed("💤 Saí do canal por inatividade."))

    @idle_check.before_loop
    async def before_idle_check(self):
        await self.bot.wait_until_ready()


async def main() -> None:
    discord.utils.setup_logging(level=logging.INFO)
    if not config.TOKEN:
        raise SystemExit("Falta o token do bot. Rode o CONFIGURAR (ou preencha DISCORD_TOKEN no .env).")
    database.init()
    async with SpaceLimbo() as bot:
        try:
            bot.web_runner = await start_web(bot)
        except OSError as exc:
            raise SystemExit(
                f"Não consegui abrir o painel na porta {config.PANEL_PORT} ({exc}).\n"
                "O spaceLimbo já está aberto em outra janela?"
            ) from None
        banner(
            "spaceLimbo ligando… (deixe esta janela aberta; feche-a para desligar)",
            f"Painel neste PC: {config.PANEL_URL}",
            f"Senha do painel: {config.PANEL_TOKEN or '(sem senha)'}",
        )
        if config.OPEN_BROWSER:
            webbrowser.open(panel_link(config.PANEL_URL))
        await bot.start(config.TOKEN)


def run() -> int:
    """Liga o bot e devolve um código de saída (0 = ok), com mensagens claras para os erros comuns."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except discord.LoginFailure:
        print("\n✖ O Discord recusou o token do bot. Rode o CONFIGURAR e cole um token novo.")
        return 1
    except aiohttp.ClientConnectorError:
        print("\n✖ Não consegui falar com o Discord. Confira sua internet e tente de novo.")
        return 1
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(f"\n✖ {exc.code}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
