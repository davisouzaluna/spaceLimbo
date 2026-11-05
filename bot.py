"""spaceLimbo — bot de música para Discord.

Execute:  python bot.py
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from player import PlayerManager, fmt_duration, search

log = logging.getLogger("spacelimbo")


class SpaceLimbo(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()  # inclui guilds e voice_states; nada privilegiado
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.players = PlayerManager(self)

    async def setup_hook(self) -> None:
        await self.add_cog(Music(self))
        if config.DEV_GUILD_ID:
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()  # global: pode levar alguns minutos para aparecer

    async def on_ready(self) -> None:
        log.info("Conectado como %s (%s servidores)", self.user, len(self.guilds))
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/play"))


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
        raise SystemExit("Defina DISCORD_TOKEN no arquivo .env (veja .env.example).")
    async with SpaceLimbo() as bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
