"""API HTTP + painel web. Usa aiohttp, que já vem junto com o discord.py (sem lib extra)."""
from __future__ import annotations

import hmac
import logging
import random
from pathlib import Path

import discord
from aiohttp import web

import config
import database
from player import Track, search

log = logging.getLogger("spacelimbo.web")
STATIC = Path(__file__).resolve().parent / "static"
routes = web.RouteTableDef()


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@web.middleware
async def middleware(request: web.Request, handler):
    if request.path.startswith("/api/") and config.PANEL_TOKEN:
        sent = request.headers.get("X-Panel-Token", "")
        if not hmac.compare_digest(sent, config.PANEL_TOKEN):
            return web.json_response({"error": "Token do painel inválido."}, status=401)
    try:
        return await handler(request)
    except ApiError as exc:
        return web.json_response({"error": str(exc)}, status=exc.status)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except web.HTTPException:
        raise
    except Exception as exc:
        log.exception("Erro na API")
        return web.json_response({"error": f"Erro interno: {exc}"}, status=500)


async def body(request: web.Request) -> dict:
    if not request.can_read_body:
        return {}
    try:
        data = await request.json()
    except Exception:
        raise ApiError("JSON inválido.")
    return data if isinstance(data, dict) else {}


def int_param(request: web.Request, name: str) -> int:
    try:
        return int(request.match_info[name])
    except (KeyError, ValueError):
        raise ApiError(f"Parâmetro inválido: {name}")


def get_guild(request: web.Request) -> discord.Guild:
    guild = request.app["bot"].get_guild(int_param(request, "gid"))
    if guild is None:
        raise ApiError("Servidor não encontrado (o bot está nele?).", 404)
    return guild


async def ensure_connected(guild: discord.Guild, player, data: dict) -> None:
    vc = player.vc
    if vc and vc.is_connected():
        return
    channel_id = data.get("channel_id")
    if not channel_id:
        raise ApiError("Escolha um canal de voz para o bot entrar.")
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.VoiceChannel):
        raise ApiError("Canal de voz inválido.")
    await player.connect(channel)


# ------------------------------------------------------------------ páginas

@routes.get("/")
async def index(_request):
    return web.FileResponse(STATIC / "index.html")


# ------------------------------------------------------------------ servidores e player

@routes.get("/api/guilds")
async def guilds(request):
    bot = request.app["bot"]
    return web.json_response([
        {
            "id": str(g.id),
            "name": g.name,
            "icon": g.icon.url if g.icon else None,
            "voice_channels": [{"id": str(c.id), "name": c.name} for c in g.voice_channels],
        }
        for g in bot.guilds
    ])


@routes.get("/api/guilds/{gid}/state")
async def state(request):
    guild = get_guild(request)
    return web.json_response(request.app["bot"].players.get(guild.id).state())


@routes.post("/api/guilds/{gid}/player/{action}")
async def player_action(request):
    guild = get_guild(request)
    p = request.app["bot"].players.get(guild.id)
    action = request.match_info["action"]
    data = await body(request)

    if action == "join":
        if not data.get("channel_id"):
            raise ApiError("Escolha um canal de voz.")
        channel = guild.get_channel(int(data["channel_id"]))
        if not isinstance(channel, discord.VoiceChannel):
            raise ApiError("Canal de voz inválido.")
        await p.connect(channel)
    elif action == "leave":
        await p.disconnect()
    elif action == "play":
        await ensure_connected(guild, p, data)
        if data.get("playlist_id"):
            rows = database.get_tracks(int(data["playlist_id"]))
            if not rows:
                raise ApiError("Playlist vazia.")
            tracks = [Track.from_dict(r, "Painel") for r in rows]
            if data.get("shuffle"):
                random.shuffle(tracks)
        elif data.get("track"):
            tracks = [Track.from_dict(data["track"], "Painel")]
        elif data.get("query"):
            tracks = await search(str(data["query"]), requester="Painel")
            if not tracks:
                raise ApiError("Nada encontrado.")
        else:
            raise ApiError("Informe query, track ou playlist_id.")
        p.add(tracks, front=bool(data.get("next")))
        await p.start_if_idle()
    elif action == "skip":
        p.skip()
    elif action == "seek":
        if "offset" in data:  # relativo: +30 / -10
            target = p.position + int(float(data["offset"]))
        else:
            target = int(float(data.get("position", 0)))
        await p.seek(target)
    elif action == "pause":
        p.pause()
    elif action == "resume":
        p.resume()
    elif action == "stop":
        p.stop()
    elif action == "shuffle":
        p.shuffle()
    elif action == "clear":
        p.queue.clear()
    elif action == "volume":
        p.set_volume(float(data.get("value", 50)) / 100)
    elif action == "loop":
        p.set_loop(str(data.get("mode", "off")))
    elif action == "remove":
        idx = int(data.get("index", -1))
        if not 0 <= idx < len(p.queue):
            raise ApiError("Posição inválida.")
        p.remove(idx)
    elif action == "move":
        src, dst = int(data.get("from", -1)), int(data.get("to", -1))
        if not (0 <= src < len(p.queue) and 0 <= dst < len(p.queue)):
            raise ApiError("Posição inválida.")
        p.move(src, dst)
    else:
        raise ApiError("Ação desconhecida.", 404)

    return web.json_response(p.state())


# ------------------------------------------------------------------ busca

@routes.get("/api/search")
async def api_search(request):
    q = request.query.get("q", "").strip()
    if not q:
        raise ApiError("Digite algo para buscar.")
    tracks = await search(q, limit=8, allow_playlist=False)
    return web.json_response([t.to_dict() for t in tracks])


# ------------------------------------------------------------------ playlists

def get_pl(request) -> dict:
    pl = database.get_playlist(int_param(request, "pid"))
    if not pl:
        raise ApiError("Playlist não encontrada.", 404)
    return pl


@routes.get("/api/playlists")
async def pl_list(_request):
    return web.json_response(database.list_playlists())


@routes.post("/api/playlists")
async def pl_create(request):
    data = await body(request)
    return web.json_response(database.create_playlist(str(data.get("name", ""))), status=201)


@routes.patch("/api/playlists/{pid}")
async def pl_rename(request):
    pl = get_pl(request)
    data = await body(request)
    database.rename_playlist(pl["id"], str(data.get("name", "")))
    return web.json_response(database.get_playlist(pl["id"]))


@routes.delete("/api/playlists/{pid}")
async def pl_delete(request):
    pl = get_pl(request)
    database.delete_playlist(pl["id"])
    return web.json_response({"ok": True})


@routes.get("/api/playlists/{pid}/tracks")
async def pl_tracks(request):
    pl = get_pl(request)
    return web.json_response({**pl, "tracks": database.get_tracks(pl["id"])})


@routes.post("/api/playlists/{pid}/tracks")
async def pl_add(request):
    pl = get_pl(request)
    data = await body(request)
    if data.get("track"):
        tracks = [Track.from_dict(data["track"]).to_dict()]
    elif data.get("query"):
        found = await search(str(data["query"]))
        if not found:
            raise ApiError("Nada encontrado.")
        tracks = [t.to_dict() for t in found]
    else:
        raise ApiError("Informe track ou query.")
    added = database.add_tracks(pl["id"], tracks)
    return web.json_response({"added": added, "tracks": database.get_tracks(pl["id"])}, status=201)


@routes.put("/api/playlists/{pid}/order")
async def pl_order(request):
    pl = get_pl(request)
    data = await body(request)
    database.reorder_tracks(pl["id"], [int(i) for i in data.get("ids", [])])
    return web.json_response({"tracks": database.get_tracks(pl["id"])})


@routes.delete("/api/tracks/{tid}")
async def track_delete(request):
    database.remove_track(int_param(request, "tid"))
    return web.json_response({"ok": True})


# ------------------------------------------------------------------ servidor

def create_app(bot) -> web.Application:
    app = web.Application(middlewares=[middleware])
    app["bot"] = bot
    app.add_routes(routes)
    app.router.add_static("/static/", STATIC)
    return app


async def start_web(bot) -> web.AppRunner:
    runner = web.AppRunner(create_app(bot))
    await runner.setup()
    await web.TCPSite(runner, config.PANEL_HOST, config.PANEL_PORT).start()
    return runner
