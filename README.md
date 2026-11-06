<h1 align="center">
    spaceLimbo
</h1>
<p align="center">
  <img src="./assets/spaceLimbo1.png" width="350" title="spaceLimbo">
</p>

<p align="center">
Bot de música para Discord, em Python, com um painel web para organizar playlists (no estilo do Jockie Music).
</p>

<h3 align="center">
<a href="https://discord.com/oauth2/authorize?client_id=1203134553624158240&permissions=3165184&scope=bot%20applications.commands">Convidar o spaceLimbo</a> <img src="./assets/cat-strange-hehe.jpg" width="40" title="hehe">
</h3>

## Jeito fácil (sem programar) — Windows

1. Baixe o projeto (**Code → Download ZIP**) e extraia numa pasta.
2. Dê **dois cliques em `INICIAR.bat`**.
   - Na primeira vez ele instala o Python (se faltar) e as bibliotecas sozinho, e abre um assistente
     que pede o token do bot, cria a senha do painel e abre o convite do bot.
   - Se o Windows mostrar "O Windows protegeu o computador", clique em **Mais informações → Executar assim mesmo**.
3. Deixe a janela preta aberta: enquanto ela estiver aberta, o bot está ligado.
   A janela mostra o **link para os amigos** (já com a senha embutida) — é só mandar para eles.
4. Para trocar o token ou ligar/desligar o link dos amigos: **`CONFIGURAR.bat`**.

Linux/macOS: `./iniciar.sh` (e `./iniciar.sh --configurar`).

Seus amigos **não** precisam instalar nada: usam `/play` no Discord e o painel pelo link.
Veja também o [`COMO USAR.txt`](COMO%20USAR.txt).

## Como rodar (manual)

1. **Python 3.10+**. O FFmpeg vem embutido (`imageio-ffmpeg`); se houver um FFmpeg instalado, ele é usado.
2. **Criar o bot:** https://discord.com/developers/applications → New Application → aba *Bot* → *Reset Token*.
   Nenhum *Privileged Intent* é necessário.
3. **Convidar:** *OAuth2 → URL Generator* → escopos `bot` e `applications.commands`;
   permissões *View Channels, Send Messages, Embed Links, Connect, Speak*.
4. **Instalar e rodar:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
   pip install -r requirements.txt
   cp .env.example .env          # preencha DISCORD_TOKEN e PANEL_TOKEN
   python bot.py
   ```
5. Abra http://127.0.0.1:8080

## Comandos

| Comando | O que faz |
|---|---|
| `/play busca` | Toca por nome ou link (aceita playlist do YouTube) |
| `/playnext busca` | Coloca no início da fila |
| `/skip` `/pause` `/resume` `/stop` `/leave` | Controles |
| `/queue [pagina]` `/nowplaying` | Fila e música atual |
| `/volume 0–150` `/loop off/track/queue` `/shuffle` `/remove posicao` | Ajustes da fila |
| `/playlist tocar · listar · criar · adicionar · salvar_fila` | Playlists salvas |
| `/painel` | Link do painel |

## Painel

- Escolha servidor e canal de voz; play/pause/pular/parar/loop/volume
- Busque músicas e mande para a fila, "tocar a seguir" ou para uma playlist
- Crie, renomeie e exclua playlists; **arraste para reordenar** a fila e as playlists
- Link público opcional para amigos via **Cloudflare Quick Tunnel** (grátis, sem conta; muda a cada vez que o bot liga)

## Estrutura

```
bot.py        comandos slash, liga o painel e o túnel
player.py     busca (yt-dlp), fila por servidor, reprodução (FFmpeg)
database.py   playlists em SQLite
web.py        API REST + painel
tunnel.py     link público do painel (cloudflared)
config.py     lê o .env
launcher.py   assistente usado pelo INICIAR.bat / iniciar.sh
static/       painel (HTML/CSS/JS puro)
```

Dependências pip: `discord.py[voice]`, `yt-dlp` e `imageio-ffmpeg`. Banco, `.env` e painel usam só a biblioteca padrão e o aiohttp que já vem com o discord.py.

## Avisos

- Desde março/2026 o Discord exige criptografia **DAVE** na voz. O discord.py ≥ 2.7 suporta via pacote `davey`
  (instalado pelo extra `[voice]`). Se o bot entrar no canal mas ficar mudo, rode `python -m discord --version`
  e confira se o `davey` aparece.
- Tocar YouTube vai contra os Termos do YouTube. Se o YouTube bloquear, atualize o yt-dlp
  (o `INICIAR.bat` já faz isso a cada vez que liga).
- O painel controla o bot: só compartilhe o link com quem você confia.

## Licença

MIT — veja [LICENSE](LICENSE).
