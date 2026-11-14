<div align="center">

# 🚀 MirrorX

### Mirror anything → **Google Drive**. Leech anything → **Telegram**.

[![tests](https://github.com/OWNER/REPO/actions/workflows/tests.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![checks](https://img.shields.io/badge/verified-179%20checks%20passing-brightgreen.svg)](AUDIT.md)
[![largest%20file](https://img.shields.io/badge/largest%20file-10%20GiB%20byte--exact-orange.svg)](AUDIT.md)

Direct links · YouTube/Instagram/TikTok + 1000 sites · Telegram files · Drive **folder** clone
Email-login OAuth or service account · resumable uploads · premium emoji UI

**[📖 Setup guide](SETUP_GUIDE.md)** · **[📊 Stats & admin guide](STATS_AND_ADMIN.md)** · **[🔍 Verification](AUDIT.md)** · **[🔬 Research](RESEARCH.md)** · **[🐙 GitHub](GITHUB_UPLOAD_GUIDE.md)** · **[🖥 UI preview](preview.html)**

</div>

---

A production-style **Mirror / Leech** bot in the spirit of
[anasty17/mirror-leech-telegram-bot](https://github.com/anasty17/mirror-leech-telegram-bot)
(the engine behind groups like [@PublicMirrorLeechGroup](https://t.me/PublicMirrorLeechGroup)),
rebuilt from scratch, smaller, async-first, and with a modern Telegram UI:
**premium/animated emojis, live progress animations, coloured buttons.**

---

## ✨ What it does

| Area | Support |
|---|---|
| **Mirror → Drive** | direct links, YouTube/Instagram/TikTok/X + 1000 sites (yt-dlp), Telegram files, Google Drive links (server-side clone, no re-upload) |
| **Leech → Telegram** | same sources, delivered back as document / video / audio / photo |
| **Drive auth** | **Email login (OAuth 2.0 device flow)** per user, or a shared **service account** |
| **Uploads** | resumable chunked upload (8 MiB chunks, 308-resume, retries) with real % / speed / ETA |
| **UI** | premium `<tg-emoji>` icons with automatic fallback, animated progress cards, rotary status lines, completion confetti effect, coloured inline buttons |
| **Storage** | SQLite (users, tokens, tasks) — zero external DB needed |
| **Ops** | Docker/Compose, Heroku/Koyeb/Railway ready |
| **Stats** | live task cards, per-user `/mystats`, animated 14-metric admin dashboard |
| **Audit log** | private log channel (`LOG_CHANNEL_ID`) — new users, tasks, Drive logins, admin actions |

---

> 🧭 **New to this? Follow [`SETUP_GUIDE.md`](SETUP_GUIDE.md)** — click-by-click, with screenshots of what you should see. This README is the condensed version.

## ☁️ One-click deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/OWNER/REPO)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

> Both need the four environment variables from `.env.example`
> (`BOT_TOKEN`, `OWNER_ID`, `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`).
> Replace `OWNER/REPO` in the badge URLs above with your own GitHub repo path
> after you push, and the CI badge + issue links will work.

## ⚡ 10-minute setup

### 1. Get a bot token
Open [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.

### 2. Get your numeric Telegram id
Message [@userinfobot](https://t.me/userinfobot) — you need this for `OWNER_ID`.

### 3. Enable Google Drive

You need **one** of these two options (you can enable both).

#### Option A — Email login (recommended, each user connects their own Drive)

1. Go to <https://console.cloud.google.com/> → create a project (free).
2. **APIs & Services → Library** → search **Google Drive API** → *Enable*.
3. **APIs & Services → OAuth consent screen** → choose **External** →
   fill app name + your e-mail → **Save**.
   Then add yourself under **Test users** (or *Publish* the app later).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   → Application type: **TVs and Limited Input devices** → Create.
5. Copy the **Client ID** and **Client secret** into `.env`:

```env
GDRIVE_CLIENT_ID=PASTE-YOUR-CLIENT-ID-HERE
GDRIVE_CLIENT_SECRET=PASTE-YOUR-CLIENT-SECRET-HERExxxx
```

> Why this client type? It's the *device flow* — the bot shows a short code,
> the user types it on `google.com/device`. No redirect URL, no public HTTPS
> server required. Works on any VPS, phone-hosted box, whatever.

#### Option B — Service account (one shared Drive)

1. Same project as above → **Credentials → Create credentials → Service account**.
2. Open it → **Keys → Add key → JSON** → download the file.
3. **Enable the Google Drive API** for the project.
4. Create a folder in Google Drive, **Share** it with the service-account
   e-mail (`xxx@xxx.iam.gserviceaccount.com`) as **Editor**.
5. Put the JSON at `data/service_account.json` (or paste it as one line into
   `GDRIVE_SA_JSON`), and put the folder id in `GDRIVE_FOLDER_ID`.

> A service account has **no personal storage quota** — it can only write into
> Shared Drives or folders owned by a real account. That's why the folder + share
> step matters.

### 4. Configure and run

```bash
cp .env.example .env
nano .env            # BOT_TOKEN, OWNER_ID, Google credentials

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python run.py --check     # validates config, prints what's enabled
python run.py             # 🚀 start
```

Docker instead:

```bash
docker compose up -d --build
docker compose logs -f
```

### Railway (tested config included)

`railway.toml` + `Dockerfile` are already set up for Railway's builder, which
**rejects any Dockerfile `VOLUME` instruction**. Two things you must do in the
dashboard:

1. **Variables** → add `BOT_TOKEN`, `OWNER_ID`, `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`
2. **Volumes** → *New Volume* → **Mount path `/app/data`** (this is where the
   SQLite DB and service-account files live; without it everything resets on deploy)

The image starts as root only long enough to `chown` the volume (Railway mounts
it root-owned), then the bot runs as uid 1000 — otherwise SQLite could not write.

> Downloads (`DOWNLOAD_DIR`) can also sit on the volume, but 10 GB files will
> eat your Railway volume quota — keep `MAX_FILE_GB` sensible or use a VPS.

---

## 🎛 Using the bot

| Action | How |
|---|---|
| Menu | `/start` |
| Connect Drive | `/login` → open `google.com/device` → type the code → done |
| Mirror a link | send the link (or `/mirror <link>`) |
| Leech a link | `/leech <link>` |
| Mirror a Drive link | send it — files are **cloned server-side** (instant, no download); Drive *folders* are cloned recursively |
| Audio only | `/audio <link>` (mp3/m4a) |
| YouTube cookies (owner) | `/cookies` → send `cookies.txt` |
| Mirror a Telegram file | send the file to the bot |
| Watch progress | the status card animates %, bar, speed, ETA by itself |
| Cancel | button on the card, or `/cancel` |
| Browse Drive | `/files` → download back to Telegram |
| Preferences | `/settings` (document vs media, quality, folder, cleanup) |
| Admin | `/stats`, `/broadcast`, `/grabemoji`, `/shell` (owner only) |

### Limiting, at a glance
* **Mirror**: **10 GB+ per file works** (proven — see `AUDIT.md`). Drive allows
  up to 5 TB; the real limits are your free disk (`MAX_FILE_GB`, default 15) and
  Google's 750 GB/day/account upload quota.
* **Leech**: 50 MB per file on the cloud Bot API (2 GB with a
  [local Bot API server](#self-hosted-bot-api-server)) — a Telegram platform
  limit, not a bot limit.
* **Disk**: a 10 GB task needs ~10 GB free in `DOWNLOAD_DIR`, per concurrent
  task (default 2). The bot refuses *before* downloading if space is short.
* Ordinary bots **cannot read other chats** — forward files to the bot instead
  of pasting `t.me/...` group links.

---

## 🎨 Premium emojis (the "premium bot" look)

The UI is rendered through `<tg-emoji emoji-id="…">`, the official way bots show
custom/animated premium emojis (Bot API 9.4+, `CUSTOM_EMOJI=auto` by default):

* If the bot's **owner has Telegram Premium** (or the bot owns a Fragment
  username), Telegram accepts them and everyone — Premium or not — sees the
  animated icons.
* If not, the bot **automatically falls back** to plain emojis for every
  emoji; on a failed send it flips to plain mode permanently for the session.
  Nothing ever breaks in the user's face.
* Add your own: reply to any premium emoji with
  `/grabemoji <key>` (e.g. `/grabemoji fire`) — the id is saved to
  `data/custom_emojis.json` and used immediately.

Catalogue lives in `bot/ui/emoji.py` (`DEFAULT_CATALOG`) and is hot-extendable
from Telegram. Coloured buttons use the Bot API `style` field
(`primary` / `success` / `danger`).

---

## 🧪 Tests (no token needed) — 179 checks, all green

```bash
bash tests/run_all.sh           # everything (~2 min), GB=10 by default
bash tests/run_all.sh --fast    # 2 GiB instead of 10 GiB

python tests/test_suite.py      # 85 unit tests: utils, emoji, cards, db, routing
python tests/e2e_mock.py        # 16 e2e: mirror → Drive, leech → Telegram, clone
python tests/e2e_login.py       # 18 e2e: email login → Drive access, refresh, revoke
python tests/e2e_commands.py    # 45 smoke: every command + menu button
LARGE_GB=10 python tests/e2e_large.py   # 10 GiB byte-exact upload, failure-injected
```

See **`AUDIT.md`** for the full report: what was verified, the 17 real bugs found
and fixed (including a silent **corruption bug** that only appears on multi-GB
uploads), and the honest list of things no bot can bypass.

`e2e_mock.py` boots the **real bot** on `127.0.0.1`, fakes `api.telegram.org`
and the Drive resumable endpoint, then proves the full pipeline:

```
link → detect → download 20 MB → open resumable session → 8 MiB chunks (308) →
progress edits → "Task complete" + Drive link → leech delivers the file back
```

That's how the bot was verified before you ever paste a real token.

---

## 🗂 Project layout

```
gdrive-mirror-bot/
├── run.py                  entrypoint (+ --check)
├── bot/
│   ├── main.py             dispatcher, startup, bot commands
│   ├── config.py           .env → typed settings + validation
│   ├── db.py               async SQLite (users, tokens, tasks, counters)
│   ├── drive.py            OAuth device flow, service account, resumable upload
│   ├── net.py              dedicated aiohttp client (NOT bot.session!)
│   ├── ui/
│   │   ├── emoji.py        premium emoji engine + {token} templating
│   │   ├── cards.py        every screen, animated cards
│   │   └── keyboards.py    coloured buttons with emoji icons
│   ├── services/
│   │   ├── common.py       Progress meter (thread-safe) + cancellation
│   │   ├── downloads.py    direct http + yt-dlp + Drive-link detection
│   │   ├── tasks.py        queue → download → Drive/Telegram + animator
│   │   └── telegram_xfer.py leech upload + getFile download
│   └── handlers/           commands, callbacks, upload, files, admin
├── tests/                  unit + e2e mock harness
├── Dockerfile · docker-compose.yml · Procfile · heroku.yml
└── .env.example
```

---

## 🐳 Self-hosted Bot API server

Unlocks **2 GB uploads / 4 GB downloads** for bots. Run
[telegram-bot-api](https://github.com/tdlib/telegram-bot-api) and start the bot
with the session pointed at it (or set `TELEGRAM_API_HOST` in your fork):

```python
from aiogram.client.telegram import TelegramAPIServer
session = AiohttpSession(api=TelegramAPIServer.from_local("http://localhost:8081"))
```

`telegram_xfer.effective_upload_limit()` detects this automatically and raises
the leech limit from 50 MB to 2 GB.

---

## 🔐 Security notes

* Tokens live only in your SQLite DB; OAuth refresh tokens are per-user.
* `safe_url()` blocks `javascript:` / `data:` / `file:` schemes.
* Filenames are sanitized before touching disk.
* Admin commands are owner-gated; `/shell` is intentionally read-only
  diagnostics (no arbitrary shell).
* Run the container as the unprivileged `mirrorx` user (already set in Dockerfile).

---

## 🧭 Troubleshooting

| Symptom | Fix |
|---|---|
| `Access blocked / Error 403: access_denied` on Google | Add your e-mail under **Test users** on the OAuth consent screen, or publish the app. |
| `Google refused the login request` | You created the wrong OAuth client type — it must be **TVs and Limited Input devices**. |
| Service account: `storageQuotaExceeded` | Share a folder from a real account (or use a Shared Drive) and set `GDRIVE_FOLDER_ID`. |
| `file is too big` on leech | Cloud Bot API caps bot uploads at 50 MB — use Mirror, or a local Bot API server. |
| No premium emojis | Owner needs Telegram Premium; the bot silently falls back. Check `/stats` → "Premium emoji". |
| YouTube 1080p fails | `ffmpeg` missing — but `imageio-ffmpeg` is in `requirements.txt`, so a static build is used automatically. Docker installs the system one. |
| YouTube says *"Sign in to confirm you're not a bot"* | Datacenter IPs get flagged. As owner, run `/cookies` and send a `cookies.txt` (use a throw-away account), or set `YTDL_COOKIES_FILE`. |
| 10 GB task says "not enough disk" | Free space in `DOWNLOAD_DIR` (or point it at a bigger volume). One task needs ~file-size in free space. |
| Upload stops at ~750 GB in a day | Google's per-account daily upload cap. Wait for the reset; files already uploaded are safe. |
| `Press /login` loop | The message means `drive_mode=none` — reconnect; check the log for `AuthExpired`. |

---

## 🙏 Credits & research trail

Built after studying **anasty17/mirror-leech-telegram-bot** (features, GDrive
clone semantics, leech splitting), Google's **Drive resumable-upload** docs,
the Telegram **Bot API changelog** (custom emoji since 9.4; button `style` /
`icon_custom_emoji_id` since 9.0), and
[@PublicBotsHub](https://t.me/PublicBotsHub) /
[@PublicMirrorLeechGroup](https://t.me/PublicMirrorLeechGroup) as the reference
product. Original code — no AGPL code copied.

**License:** MIT (your own deployments, your own rules — respect Telegram ToS and
copyright when mirroring content).
