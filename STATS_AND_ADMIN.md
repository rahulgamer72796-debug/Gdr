# 📊 Stats, Status, Admin system & Log Channel — full guide

*Everything the bot measures, where it lives, how it loads, and how to add the
log ("lock") channel. Code references point at the exact files.*

---

## 1. The three different things people call "stats"

Beginners usually mix these up. They are three separate systems:

| # | System | Command | Who sees it | What it answers |
|---|---|---|---|---|
| 1 | **Live task status** | `/status` | any user (own tasks) | "Is my upload moving right now?" |
| 2 | **Personal usage** | `/mystats` | any user (own numbers) | "How much have *I* uploaded?" |
| 3 | **Admin dashboard** | `/stats` | owner only | "How healthy is the whole bot?" |

Plus the **activity log channel**, which is not a command — it's a stream of
events pushed to a private channel you own.

---

## 2. Live task status — `/status`

**Code:** `bot/services/tasks.py` (`manager.active_for_user`) + `bot/ui/cards.py` (`status_list`)

Every running task holds a `Progress` object (`bot/services/common.py`) which is
updated by the downloader/uploader from worker threads and read by the animator
loop. `/status` renders one line per task:

```
📋 Active tasks (2)

📥 1. bigfile.iso
     ▰▰▰▰▰▰▱▱▱▱ 61% · 34.21 MB/s · #a91f

📤 2. movie.mp4
     ▰▰▰▱▱▱▱▱▱▱ 28% · 12.04 MB/s · #b3c7
```

### How the "one by one" loading works

The **status card is not re-rendered from scratch** — it's edited in place:

```
submit()          → sendMessage("Queued…")            ← 1 message created
   ↓ every PROGRESS_INTERVAL (default 4 s)
animator loop     → editMessageText(next frame)       ← same message, new content
   ↓ on finish
_final_card()     → editMessageText("Task complete")  ← same message, final state
```

So a 10 GB upload edits **one** message ~25 times, not 25 messages. That's why
Telegram doesn't rate-limit you.

**The animation primitives** (`bot/ui/cards.py`):

| Primitive | Code | Looks like |
|---|---|---|
| Spinner | `spin(frame)` | `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` |
| Bar | `bar(percent, 12)` | `▰▰▰▱▱▱▱▱▱▱▱▱` |
| Phase copy | `_rotating(DL_LINES, frame)` | "Pushing chunks to Drive…" |
| Dots | `frame % 4` | `Downloading.` → `…` |
| ETA | `human_time(remaining/speed)` | `2m 04s` |

---

## 3. Personal usage — `/mystats` (new)

**Code:** `bot/handlers/commands.py` → `mystats_cmd()` + `bot/db.py` → `user_stats()`

Any user can ask about **their own** numbers. They can never see anyone else's —
the query is always scoped to `user_id`.

```
👤 Your usage

✅ Uploads done: 14 / 16 tasks
📊 Total uploaded: 23.40 GB
⚡ Success rate: 87.5%
⏰ Last upload: 14 Nov 2026 · 18:22
📁 Drive: My Drive
🔒 Login: connected
```

SQL behind it (`bot/db.py`):

```sql
SELECT COUNT(*), COALESCE(SUM(size),0), MAX(finished_at)
FROM tasks WHERE user_id=? AND status='done';
```

> Want a leaderboard later? `SELECT user_id, SUM(size) FROM tasks WHERE
> status='done' GROUP BY user_id ORDER BY 2 DESC LIMIT 10` — but publish it
> only with your users' consent.

---

## 4. Admin dashboard — `/stats` (rebuilt)

**Code:** `bot/handlers/admin.py` → `_render_dashboard()` + `bot/ui/cards.py` → `admin_stats()`

### 4.1 What it shows — 14 metrics

| Section | Metric | Source |
|---|---|---|
| **Users** | total | `COUNT(*) FROM users` |
| | today | `created_at >= now-24h` |
| | banned | `banned=1` |
| | email-login / service-account split | `drive_mode` |
| **Tasks** | started | counter |
| | done | counter |
| | failed | counter *(new — was missing)* |
| | cancelled | counter *(new — was missing)* |
| | today | `created_at >= now-24h` |
| | running now | `status IN ('queued','running')` |
| **Data** | total uploaded | counter |
| | uploaded today | `SUM(size)` done in last 24 h |
| | success rate | `done / started * 100` |
| | average duration | `AVG(finished_at - created_at)` |

### 4.2 The animated load (what you asked for)

`_render_dashboard()` renders the panel in **5 frames**, 0.35 s apart:

```
frame 1:  👑 Admin dashboard
          👤 Users
          total 42 · today 5
          ⠋ loading…
          <code>▰▰▰▱▱▱▱▱▱▱▱▱</code>

frame 2:  … adds the Drive split …
frame 3:  … adds Tasks …
frame 4:  … adds Data …
frame 5:  full panel + buttons appear
```

Why 0.35 s? Telegram allows ~1 edit/second per chat. 0.35 s × 5 is under the
limit and still feels fast. The safe-edit wrapper swallows "message is not
modified" errors, so a dropped frame never breaks the panel.

**Tuning it** (`bot/handlers/admin.py`):

```python
step = 7              # lines revealed per frame
await asyncio.sleep(0.35)   # delay between frames
```

### 4.3 The counter bug I fixed

Before this update, **failed and cancelled tasks were invisible** — `finish_task`
only counted `done`. Your dashboard would have shown:

```
started 120 · done 98      ← where did 22 go?
```

Now (`bot/db.py`):

```python
if status == "done":        await self._bump("tasks_done")
elif status == "failed":    await self._bump("tasks_failed")
elif status == "cancelled": await self._bump("tasks_cancelled")
```

Also removed: a dead line in `commands.py` that read
`await db._bump("users") if False else None` — it never ran, so the user counter
was always wrong until it was replaced by `COUNT(*) FROM users`.

---

## 5. Admin commands — complete list

| Command | What it does | Guard |
|---|---|---|
| `/stats` | animated dashboard | owner |
| `/broadcast <text>` | message every user | owner |
| `/grabemoji <key>` | save a premium emoji id (reply to it) | owner |
| `/cookies` | YouTube cookie status + install | owner |
| `/logchannel` | check + test the activity channel | owner |
| `/shell` | runtime diagnostics (disk, ffmpeg, limits) | owner |
| `/cancel` | cancel your task | any user |
| `/status` | your live tasks | any user |
| `/mystats` | your usage numbers | any user |

Admin buttons live on `menu:admin` → dashboard, active tasks, emoji catalogue,
broadcast, **activity log channel**.

**Security model:** every owner handler starts with `if not _owner(msg): return`
— a non-owner gets *silence*, not an error, so they can't even probe which
commands exist. `/shell` is deliberately read-only (no arbitrary command
execution) — a remote shell in a Telegram bot is how mirror bots get hijacked.

---

## 6. 🔔 The log channel ("lock channel")

**Code:** `bot/services/logger_channel.py` · **Setting:** `LOG_CHANNEL_ID`

### 6.1 What it is

A private Telegram channel where the bot posts **every activity** as it happens.
Only you read it. It's your audit trail: who joined, who uploaded what, who
failed and why, which Google account got linked, what an admin did.

### 6.2 Setup (5 steps, ~2 minutes)

1. Telegram → **New Channel** → name it e.g. `MirrorX Logs` → **Private**
2. Open the channel → **Administrators** → **Add Administrator** → pick your bot
3. Give it **Post Messages** permission (nothing else needed) → Save
4. Forward any message from that channel to **@userinfobot** → copy the id,
   it starts with `-100`, e.g. `-1001234567890`
5. Put it in `.env` and restart:

```env
LOG_CHANNEL_ID=-1001234567890
LOG_NEW_USERS=true
LOG_TASKS=true
LOG_ADMIN_ACTIONS=true
```

Then in the bot: **`/logchannel`** → it replies "active → -100…" and posts a test
event. If you can read that message in your channel, you're done. ✅

### 6.3 What gets logged

| Event | Example message |
|---|---|
| **Bot online** | 🚀 MirrorX is online · v1.1.0 · 14 Nov 2026 · 18:20 |
| **New user** | 👤 New user · Tester · `123456789` · @tester |
| **Task started** | 🚀 Task started `#a91f3c` · mode mirror · link · size 2.00 GB |
| **Task finished** | ✅ Task finished · 2.00 GB · 2m 05s · [open](drive link) |
| **Task failed** | ❌ Task failed · ⚠ The server answered 404 |
| **Cancelled** | 🛑 Task cancelled · 1.20 GB · 0m 31s |
| **Drive login** | 🔐 Google Drive connected · `you@gmail.com` · oauth |
| **Admin action** | 👑 Admin action · broadcast · sent to 42 users |
| **Security** | 🛡 Test event / suspicious link / ban |

### 6.4 Design rules (why it can't break your bot)

| Rule | Implementation |
|---|---|
| **Never crashes the bot** | every send is wrapped in `try/except`; failure sets a flag and disables logging, bot continues |
| **Never spams** | per-user throttle: **3 events / 10 s**; failures bypass the throttle so you never miss a real error |
| **Never leaks secrets** | tokens, cookies, keys are never passed to the logger |
| **No-op when off** | `LOG_CHANNEL_ID=0` → zero overhead, zero network calls |
| **Explains its own failure** | "bot is not an admin / chat not found / needs Post Messages" |

### 6.5 Code — the event functions

```python
# bot/services/logger_channel.py
async def new_user(user, *, is_new=False)          # 👤
async def task_started(user, task)                 # 🚀
async def task_finished(user, task, status, error) # ✅ / ❌ / 🛑
async def drive_linked(user, email, mode)          # 🔐
async def admin_action(actor, action, detail)      # 👑
async def security(user, event, detail)            # 🛡
async def startup(version)                         # 🚀 online ping
```

Call them from anywhere — they're fire-and-forget:

```python
from bot.services import logger_channel
await logger_channel.security(user, "Blocked a javascript: link", url)
```

The core send path:

```python
async def _send(text, *, user_id=0, urgent=False):
    if not enabled(): return                      # cheap no-op
    if user_id and not urgent and _throttled(user_id): return
    try:
        await _bot.send_message(settings.log_channel_id, text, parse_mode="HTML")
    except TelegramAPIError as e:
        _fail(e)                                  # disable + explain once
```

### 6.6 Every place it's wired in (audit)

| File | Hook |
|---|---|
| `bot/main.py` | `logger_channel.setup(bot)` + `startup()` ping |
| `bot/handlers/commands.py` | `new_user()` on a first `/start` |
| `bot/services/tasks.py` | `task_started()` / `task_finished()` |
| `bot/handlers/callbacks.py` | `drive_linked()` after OAuth success |
| `bot/handlers/admin.py` | `admin_action()` in broadcast, cookies, emoji |

---

## 7. What I verified (not assumed)

`tests/e2e_logchannel.py` — **24 checks, all passing**, against a mock Telegram
channel:

```
✔ startup ping reaches the channel
✔ "New user" logged with the user id
✔ "Task started" logged with mode + size
✔ "Task finished" logged with the Drive link
✔ "Task failed" logged with the reason (404)
✔ "Google Drive connected" logged with the e-mail
✔ "Admin action" logged
✔ counters: done / failed / cancelled all move correctly
✔ stats returns 14 fields
✔ per-user: total 3, done 1, success rate 33.3%
✔ throttle: 20 rapid events → ≤ 3 delivered (and not 0)
✔ dead channel → bot survives, reason recorded
```

Full suite: **203 checks** across 6 suites — `bash tests/run_all.sh`.

---

## 8. If you want to go further (in priority order)

| Upgrade | Effort | Why it matters |
|---|---|---|
| **Daily digest** — 09:00 summary of yesterday to the log channel | S | you stop checking the channel manually |
| **`/banned`, `/ban <id>`** — ban abusers (the `banned` column already exists) | S | one spammer can't kill your queue |
| **Per-user quota** — `MAX_GB_PER_DAY` in the users table | M | stops one person eating 750 GB |
| **Persist stats to a file** — `data/stats.json` snapshot every 5 min | S | dashboard survives a DB wipe |
| **Prometheus `/metrics`** endpoint | M | only if you run a real monitoring stack |
| **Separate status channels per task group** | S | nice when you run 20+ tasks |

Tell me which one and I'll build it the same way — code + tests + proof.
