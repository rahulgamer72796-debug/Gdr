# 🔬 Research report — how Mirror/Leech bots work, and what I checked

*Prepared 14 Nov 2026 · sources: GitHub, Telegram Bot API docs/changelog, the
reference Telegram group, Google Drive API docs.*

---

## 1. The bot you pointed me at

**@PublicMirrorLeechGroup** — *Public Mirror Leech Group*

| Fact | Value |
|---|---|
| Members | 3 174 (290 online at check) |
| Owner channel | [@PublicBotsHub](https://t.me/PublicBotsHub) — *Public Bots Hub 🇮🇳*, 26 105 subscribers |
| Contact | [@super1adminbot](https://t.me/super1adminbot) · support [@PBHSupport_Bot](https://t.me/PBHSupport_Bot) |
| Self-description | "Bots source code are available publicly, credits goes to its Original Creator." |

**What it actually is:** a *support community* for a family of **Mirror/Leech**
bots — not one bot. Members drop a link, a bot downloads it and either

* **mirrors** it into Google Drive / Team Drive, or
* **leeches** it back into Telegram as a file.

These groups are almost all running forks of
**[anasty17/mirror-leech-telegram-bot](https://github.com/anasty17/mirror-leech-telegram-bot)**
(MLTB, ~3.7k ★, Python/asyncio) or its ancestor
[lzzy12/python-aria-mirror-bot](https://github.com/lzzy12/python-aria-mirror-bot).
That's the same lineage as the classic `mirror-leech`, `python-aria-mirror-bot`
and `SVR666/SearchX` families.

## 2. What those bots can do (feature matrix from the MLTB README)

| Feature block | Highlights |
|---|---|
| **Downloaders** | aria2c, qBittorrent (with in-Drive file selection), SABnzbd/Usenet, yt-dlp, gallery-dl, JDownloader, Mega.nz, RSS |
| **Google Drive** | upload, **clone** (server-side copy), delete, count, search, Team/Shared Drives, token.pickle + Service Accounts, random-SA rotation, duplicate-stop |
| **Leech** | split sizes, per-user thumbnails, document vs media, upload to a specific chat, media groups |
| **Archives** | zip/unzip, extract RAR/7z/ISO… with passwords, splits |
| **Status system** | live download/upload/extract/seed status pages, paginated, buttons |
| **Ops** | Mongo-backed settings, sudo users, shell, bot update from upstream repo, Docker multi-arch |

**Deployment reality:** these are heavy. MLTB needs MongoDB, qBittorrent,
aria2, a base URL for its web file-selector, and 1–2 GB RAM. That's why this
project deliberately implements the *useful 80 %* in one small process with
SQLite — no Mongo, no torrent daemon, no web server.

## 3. How the Drive upload actually works (verified against Google's docs)

Three steps, all plain HTTPS — no SDK needed:

1. **Open a session**
   `POST https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable`
   with JSON metadata (`name`, `parents:[folderId]`).
   Response header `Location` = a one-shot **session URI**.
2. **Push chunks** — `PUT` to that URI with
   `Content-Range: bytes 0-8388607/20971520`.
   * chunks **must be multiples of 256 KB** (we use 8 MiB; 32 MiB above 512 MB)
   * `308 Resume Incomplete` = "got it, keep going"; the `Range` header tells you
     how many bytes the server actually kept (this is how you resume after a
     network drop)
   * `200/201` = finished, body = file metadata (`id`, `webViewLink`)
3. **Clone, don't download** — a Drive→Drive copy is
   `POST /drive/v3/files/{id}/copy` with the destination parent. Instant, no
   bandwidth, no local disk. `mirror-leech` users call this `clone`; our bot does
   it automatically whenever it sees a Drive link and the user is connected.

Quotas that shaped the design: 5 TB per-file max on Drive; 750 GB/day upload
per account (free tier, shared across API + web) — so a "mirror" bot must not
loop-retry aggressively; our uploader backs off (429/5xx → 1.5 s, 3 s).

## 4. "Email login and all stuff" — Drive auth options

| Method | Who owns the storage | Headless friendly? | Used by |
|---|---|---|---|
| **OAuth 2.0 device flow** ("TVs and Limited Input devices") | the user's own Drive | ✅ code on `google.com/device`, no redirect URL | **MirrorX default** |
| OAuth web redirect | the user's own Drive | ❌ needs public HTTPS callback | dashboards |
| **Service account** (JSON key, JWT RS256 → access token) | the SA — which has **no personal quota**, so it needs a shared folder/Shared Drive | ✅ | MLTB, most public bots |
| `token.pickle` (user token copied manually) | the token owner | ✅ | older MLTB forks |

MirrorX ships **both #1 and #3**: users tap *Login with Google* (device code),
or the owner configures one service account for a shared workspace.
OAuth tokens are refreshed automatically (`refresh_token` grant) and stored in
SQLite; a 401 triggers a forced refresh + one retry.

## 5. "All animation and Telegram premium emojis" — what's actually possible

This was the most important thing to get right, because bot APIs can't do
everything a user account can.

### Custom / premium (animated) emojis
* Syntax: `<tg-emoji emoji-id="5368324170671202286">👍</tg-emoji>` (HTML) or
  a `custom_emoji` MessageEntity with `custom_emoji_id`.
* **Rules (Bot API 9.4, Feb 2026):** a bot may send custom emojis *if its owner
  has Telegram Premium*, or if the bot owns a Fragment username. Viewers do
  **not** need Premium — they see the animated emoji.
* Therefore the correct engineering answer is **graceful degradation**: try
  custom → on refusal, fall back to plain emoji and never show an error.
  That's `bot/ui/emoji.py` (mode `auto`): it verifies every id once with
  `getCustomEmojiStickers`, drops dead ids, and flips a global switch.
* Buttons can carry `icon_custom_emoji_id` **and** a `style`
  (`primary`/`success`/`danger`) — used for the coloured menu.
* Finding ids: `/grabemoji <key>` (reply to any premium emoji) saves the id
  straight into `data/custom_emojis.json`. No external service needed.

### Animations that work inside a normal bot
Telegram bots cannot play GIFs *as* a message background, but these read as
"animated" and are what premium bots use:

| Trick | Our implementation |
|---|---|
| **Braille spinner** in the status line | `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` rotated every edit |
| **Pulsing bar** `▰▰▰▱▱▱▱▱▱▱▱▱` | filled from real byte counts |
| **Rotating status copy** ("Pushing chunks to Drive…") | 6 lines per phase, swaps every 3 frames |
| **Vanishing dots** `Downloading.` → `Downloading…` | 4-frame cycle |
| **Live card edits** | one `editMessageText` every `PROGRESS_INTERVAL` s (≥2 s, respects `retry_after`) |
| **Message effect** (confetti / fire) on completion | `message_effect_id`, client-side animation in every Telegram app |
| **Animated premium emoji** | `<tg-emoji>` above |

### Why not MTProto (Pyrogram/Telethon)?
MTProto userbots *can* do more (4 GB uploads, reading other chats), but they
log in as a **human account** (phone number, ban risk, session files). The
public mirror bots are Bot-API bots; we matched that, and documented the local
Bot API server path for 2 GB (`telegram_xfer.effective_upload_limit()` detects
`localhost:8081` automatically).

## 6. Limits everyone hits (and how the bot handles them)

| Wall | Value | Our behaviour |
|---|---|---|
| Bot API upload | 50 MB (2 GB local server) | leech pre-checks size, explains, offers Mirror |
| Bot API download of files | 20 MB (getFile) | clear error + "send it to Drive instead" |
| Ordinary bot can't read other chats | — | friendly explanation, no fake promises |
| Drive upload / day | 750 GB (free) | backoff, no hammering |
| Drive file size | 5 TB | Drive handles chunking internally |
| Telegram message edits | ~1/s per chat | interval clamped ≥2 s + `TelegramRetryAfter` |
| Telegram msg length | 4096 chars | all cards clipped |

## 7. Competitive check — what we kept vs dropped

**Kept:** mirror, leech, Drive clone, OAuth + SA, per-user folder, quality
picker, status cards, cancel, broadcast, admin stats, Docker.

**Deliberately dropped (v1):** torrents/qBittorrent, Usenet/SABnzbd, JDownloader,
RSS, zip-splitting, Mongo, multi-SA rotation, shell executor. Each adds a daemon
or a security hole; none is needed for "upload any content to Drive".

**Where this build is better than a stock fork:** one-process install,
per-user Google login (most public bots only offer a shared drive), premium
emoji engine with fallback, animated cards, and a 97-test suite that runs
offline against mocked Telegram/Drive.

---

### Source list
* anasty17/mirror-leech-telegram-bot — README + feature list (GitHub)
* lzzy12/python-aria-mirror-bot, leech-bot/mirror — lineage
* Telegram Bot API changelog (custom emoji 9.4; button style/icon 9.0)
* Telegram Bot API docs — `custom_emoji` entity, `message_effect_id`
* Google Workspace Drive API — *Upload file data* (resumable, 256 KB rule)
* t.me/PublicMirrorLeechGroup · t.me/PublicBotsHub (public preview)
