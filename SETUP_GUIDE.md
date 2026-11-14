# 📖 MirrorX — Step-by-Step Setup Guide

*Follow this top to bottom. At the end you'll have a working Telegram bot that
uploads anything to **your** Google Drive. Time needed: ~20 minutes.*

> Every step says **what you should see**. If you see something else, jump to
> [Troubleshooting](#-troubleshooting) at the bottom.

---

## 🗺 The map of what you're building

```
 You  ──send link──►  Telegram Bot (yours)  ──download──►  temporary disk
                                                    │
                                                    └──resumable upload──►  YOUR Google Drive
```

Three accounts/keys are involved:

| # | Thing | Where you get it | Time |
|---|---|---|---|
| 1 | Bot token | @BotFather on Telegram | 2 min |
| 2 | Your numeric Telegram ID | @userinfobot | 1 min |
| 3 | Google Drive access | Google Cloud Console | 8 min |

---

# PART A — Get your Telegram bot token

### A1. Create the bot
1. Open Telegram, search **`@BotFather`** (blue tick).
2. Send: `/newbot`
3. It asks for a **name** → type anything, e.g. `My Drive Bot`
4. It asks for a **username** → must end in `bot`, e.g. `mygdrivemirror_bot`
5. BotFather replies with a line like:

```
Use this token to access the HTTP API:
PASTE-YOUR-BOT-TOKEN-HERE
```

✅ **What you should see:** a token with a colon in the middle.
📋 Copy it somewhere safe. **This is your `BOT_TOKEN`.** Never share it — anyone
with it controls your bot.

### A2. Get your Telegram ID
1. Search **`@userinfobot`** → send `/start`
2. It replies `Id: 123456789`

📋 That number is your **`OWNER_ID`** (you, the admin).

### A3. (Optional but recommended) Tidy up the bot profile
In @BotFather:
- `/setdescription` → "Mirror anything to Google Drive 🚀"
- `/setuserpic` → upload a logo
- `/setcommands` → paste this block (copy the whole thing):

```
start - Main menu
mirror - Mirror a link to Google Drive
leech - Send a file back to Telegram
login - Connect your Google Drive
drive - Drive status and storage
status - Active tasks
cancel - Cancel a task
files - Browse your Drive
settings - Preferences
help - How to use the bot
```

---

# PART B — Get Google Drive access (the "email login")

You only need **one** of B-option-1 or B-option-2.

> **Which one?**
> * **Option 1 (Email login)** → each user connects **their own** Google
>   account from inside the bot. Best for a personal/shared bot group. ← **start here**
> * **Option 2 (Service account)** → one shared Drive for everyone, no login
>   screen. Easier, but the service account has **no storage of its own**, so it
>   writes into a folder you share with it.

---

## B-option-1 — Email login (OAuth device flow) ⭐ recommended

### B1. Create a Google Cloud project
1. Go to **https://console.cloud.google.com/**
2. Sign in with **the Google account whose Drive you want to use**.
3. Top bar → project dropdown → **New Project**
4. Name: `mirrorx` → **Create** → wait ~10 s → make sure it's selected in the top bar.

### B2. Turn on the Drive API
1. Left menu → **APIs & Services** → **Library**
2. Search **`Google Drive API`** → click it → **ENABLE**

✅ You should now see "API enabled".

### B3. Configure the consent screen
1. **APIs & Services** → **OAuth consent screen**
2. Choose **External** → **Create**
3. Fill:
   - App name: `MirrorX`
   - User support email: your email
   - Developer contact email: your email
4. **Save and Continue** through **Scopes** (nothing to add) and **Test users**.
5. On **Test users** → **+ ADD USERS** → add **your own Gmail address** → Save
   *(skip this and you'll get `Error 403: access_denied` later!)*

### B4. Create the OAuth client
1. **APIs & Services** → **Credentials** → **+ CREATE CREDENTIALS** → **OAuth client ID**
2. **Application type:** choose **TVs and Limited Input devices** ⚠️ *not* "Web application"
3. Name: `mirrorx-bot` → **Create**
4. Copy the two values:

```
Client ID:     PASTE-YOUR-CLIENT-ID-HERE
Client secret: PASTE-YOUR-CLIENT-SECRET-HERE
```

📋 These are your **`GDRIVE_CLIENT_ID`** and **`GDRIVE_CLIENT_SECRET`**.

> Why this client type? It's the *device flow*: the bot shows a short code, you
> type it on `google.com/device`. No website, no redirect URL, no HTTPS needed —
> it works on any PC or cheap VPS. This is the "email login" you asked for.

---

## B-option-2 — Service account (shared Drive, no login screen)

1. Same project as **B1**, Drive API enabled (**B2**).
2. **Credentials** → **CREATE CREDENTIALS** → **Service account**
3. Name: `mirrorx` → **Create** → **Done** (skip optional steps)
4. Click the new account → **KEYS** → **ADD KEY** → **Create new key** → **JSON** → **Create**
5. A `.json` file downloads. **Rename it to `service_account.json`** and put it in
   the bot's `data/` folder.
6. Open that JSON, find `"client_email": "mirrorx@....iam.gserviceaccount.com"`
   📋 copy that email.
7. In **Google Drive** (the normal drive.google.com), create a folder, e.g.
   `MirrorX Uploads` → right-click → **Share** → paste that service-account email
   → **Editor** → Send.
8. Open the folder, look at the URL:
   `https://drive.google.com/drive/folders/`**`1AbCdEfGhIjKlMnOpQr`** ← that's the folder ID.
   📋 That's your **`GDRIVE_FOLDER_ID`**.

> ⚠️ A service account has 0 GB of its own storage. It only works because you
> shared a folder it can write into. If you skip the share step you'll see
> `storageQuotaExceeded`.

---

# PART C — Install the bot

Choose **one** of the three. If unsure → **C2 (VPS)** for a bot that runs 24/7
or **C1 (Windows)** to test on your own PC.

## C1 — Windows PC (quickest test)

1. Install **Python 3.11 or newer**: https://www.python.org/downloads/
   ⚠️ On the first installer screen, **tick "Add python.exe to PATH"**.
2. Unzip the bot folder (e.g. to `C:\mirrorx`).
3. Open **Command Prompt** (Start → type `cmd` → Enter) and run:

```bat
cd C:\mirrorx
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

4. Create your config:
```bat
copy .env.example .env
notepad .env
```
5. In Notepad, fill in the **four** values from Parts A and B:

```env
BOT_TOKEN=PASTE-YOUR-BOT-TOKEN-HERE
OWNER_ID=123456789
GDRIVE_CLIENT_ID=PASTE-YOUR-CLIENT-ID-HERE
GDRIVE_CLIENT_SECRET=PASTE-YOUR-CLIENT-SECRET-HERE
```
   Save (Ctrl+S) and close Notepad.

6. Check your setup:
```bat
python run.py --check
```
✅ You should see `Config check → OK ✔`, `Drive (OAuth): enabled`.

7. **Start the bot:**
```bat
python run.py
```
✅ You should see:

```
──────────────────────────────────────────────────────────────
  MirrorX v1.0.0 is online as @mygdrivemirror_bot
  premium emoji : ON ✔            (or "fallback (plain) mode")
  email login   : enabled
──────────────────────────────────────────────────────────────
```

🎉 **Open Telegram → find your bot → press START.**

> Your PC must stay on while the bot runs. For 24/7 → use C2.

## C2 — Linux VPS, 24/7 (recommended)

A ₹350–500/month VPS is plenty (1 vCPU / 1 GB RAM). Get **≥ 20 GB disk** if you
plan 10 GB files.

1. Connect to your server:
```bash
ssh root@YOUR_SERVER_IP
```
2. Install Docker:
```bash
curl -fsSL https://get.docker.com | sh
```
3. Upload the zip to the server (WinSCP / `scp`), then:
```bash
cd /root
unzip gdrive-mirror-bot.zip
cd gdrive-mirror-bot
cp .env.example .env
nano .env        # paste your 4 values, Ctrl+O, Enter, Ctrl+X
```
4. Check, then start:
```bash
docker compose up -d --build
docker compose logs -f
```
✅ Same "is online" banner appears in the logs. Press `Ctrl+C` to stop watching
(the bot keeps running).

Useful commands:
```bash
docker compose logs -f          # live logs
docker compose restart          # restart
docker compose down             # stop
docker compose up -d --build    # update after changing code
```

## C3 — Without Docker (plain Linux / Python anywhere)

```bash
sudo apt update && sudo apt install -y python3 python3-venv ffmpeg
cd gdrive-mirror-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env      # fill your 4 values
python run.py --check
python run.py
```
To keep it running after you disconnect, use `screen`:
```bash
screen -S mirrorx
python run.py          # then press Ctrl+A then D to detach
# come back later:  screen -r mirrorx
```

---

# PART D — Use the bot (your real goal)

### D1. Connect your Google Drive (once)

1. In the bot, tap **🔐 Connect Google Drive** (or send `/login`).
2. The bot replies with a **code** like `KQ7-DP2` and a button.
3. Tap **Open Google verification page** → choose **your Google account**
   → type the code → **Allow**.
4. Come back to Telegram.

✅ Within ~10 seconds the card changes to:
```
✅ Google Drive connected!
👤 Signed in as you@gmail.com
🚀 Send me a link and I'll start mirroring.
```

The bot now has permission to write into **your** Drive. It never sees your
password — only an OAuth token, which auto-refreshes every hour.

### D2. Upload things

| You want to… | Do this |
|---|---|
| Upload a direct file link | paste the link, e.g. `https://site.com/file.zip` |
| Upload a YouTube/Insta/TikTok video | paste the video link |
| Send a file back to Telegram | `/leech <link>` |
| Copy a Drive file or **folder** to your Drive | paste the Drive link (instant, no re-upload) |
| Upload a file you already have in Telegram | **forward/send it to the bot** |
| Audio only (mp3) | `/audio <link>` |
| See progress | the status card animates itself — % , bar, speed, ETA |
| Cancel a running task | tap **Cancel task** on the card, or `/cancel` |
| Browse your Drive | `/files` |
| Change destination folder | `/settings` → **Drive folder** → send the folder link |

### D3. The 10 GB files you mentioned

1. Make sure `MAX_FILE_GB` is **15** (already the default) and you have
   **≥ 10 GB free disk** where the bot runs.
2. Send the link or the file. The card shows real upload progress to Google.
3. Google's limit is **750 GB per account per day** (~75 × 10 GB). If you hit it,
   the bot tells you plainly and you retry the next day.

💡 **Tip for big files:** on a VPS, put downloads on a big volume:
```env
DOWNLOAD_DIR=/mnt/bigdisk/downloads
```

### D4. Make it look premium (optional)

* If **you** (the bot owner) have **Telegram Premium**, the bot automatically
  shows animated premium emojis. No setting needed.
* Check status any time with `/stats` → `Premium emoji: on`.
* Add your own emojis: reply to any premium emoji with `/grabemoji fire`.

### D5. YouTube stuck on "Sign in to confirm you're not a bot"?

Datacenter IPs get flagged by YouTube. Fix in 2 minutes:
1. Install the **"Get cookies.txt LOCALLY"** browser extension on a PC where
   YouTube works, while logged in.
2. Export cookies for `youtube.com` → you get `cookies.txt`.
3. As the bot owner, send that file to the bot as a **document**.
✅ The bot replies "Cookies installed." Use a throw-away Google account.

---

# PART E — Prove it works (optional, 2 minutes)

On the machine where the bot lives:

```bash
bash tests/run_all.sh --fast
```

You should see:
```
RESULT: 85 passed, 0 failed
E2E RESULT: 16 passed, 0 failed
LOGIN RESULT: 18 passed, 0 failed
COMMAND SMOKE RESULT: 45 passed, 0 failed
LARGE-FILE RESULT: 15 passed, 0 failed
ALL SUITES PASSED ✔
```

This runs the bot against **fake** Telegram and Google servers — no token, no
internet, nothing charged. It also does a real 2 GiB upload and checks the
SHA-256 to prove zero corruption. `bash tests/run_all.sh` (no `--fast`) does 10 GiB.

---

# 🔧 Troubleshooting

| What you see | What it means | Fix |
|---|---|---|
| `BOT_TOKEN is missing or malformed` | `.env` not saved / wrong folder | Confirm `.env` sits next to `run.py`; token must contain `:` |
| Bot doesn't answer `/start` | not running, or token wrong | Check the terminal for the "is online" banner; `docker compose logs` |
| `Error 403: access_denied` on Google | your Gmail isn't a **Test user** | B3 step 5 → add your email |
| `Google refused the login request` | wrong OAuth client type | B4: must be **TVs and Limited Input devices** |
| "Drive isn't connected yet" when you send a link | `/login` not finished | Re-run `/login`, wait for "connected" |
| `storageQuotaExceeded` (service account) | folder not shared, or Drive full | Share folder with the SA email as Editor |
| `This file is X but only Y of disk is free` | not enough disk | Free space or set `DOWNLOAD_DIR` to a bigger disk |
| `Google is throttling this account` | rate limit | Wait a few minutes |
| `750 GB/day reached` | Google's daily cap | Retry after the reset (~24 h) |
| Leech says "over the 50 MB limit" | Telegram platform cap | Use **Mirror to Drive** instead |
| "Sign in to confirm you're not a bot" | YouTube bot-check | Part D5 (`/cookies`) |
| Emojis look plain, not animated | owner has no Telegram Premium | Normal — bot auto-falls back. Premium fixes it |
| Bot stops when I close the terminal | running in foreground | Use C2 (Docker) or `screen` (C3) |

Still stuck? Send me the **last 20 lines** of the log and the exact error text.

---

# 📋 Your copy-paste checklist

```env
BOT_TOKEN=               # @BotFather → /newbot
OWNER_ID=                # @userinfobot  → Id:
GDRIVE_CLIENT_ID=        # B-option-1 → B4
GDRIVE_CLIENT_SECRET=    # B-option-1 → B4
```

Run order:
```bash
cp .env.example .env      # 1. fill it in
python run.py --check     # 2. must say OK ✔
python run.py             # 3. look for "is online"
```
Then in Telegram: **/start → Connect Google Drive → send a link.**
