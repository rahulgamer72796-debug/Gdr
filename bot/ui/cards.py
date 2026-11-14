"""Animated status cards — every screen of the bot is rendered from here.

`render_*` functions return HTML text full of premium `<tg-emoji>` tags.
`*_frames` generators power the little animations (spinner, pulsing bar,
rotating status lines) by producing a new card every PROGRESS_INTERVAL seconds.
"""
from __future__ import annotations

from typing import Iterator

from ..config import settings
from ..utils import bar, clip, esc, human_size, human_time, short_id
from .emoji import emoji, spin, t

SPIN_FRAMES = 10

DL_LINES = [
    "Handshaking with the server", "Asking the internet nicely", "Opening the pipe",
    "Receiving packets", "Streaming into the buffer", "Pulling bytes",
]
UP_LINES = [
    "Chatting with Google Drive", "Opening a resumable session", "Pushing chunks to Drive",
    "Negotiating with Drive's gremlins", "Uploading at full throttle", "Syncing with Google",
]
QUEUE_LINES = [
    "Warming up the engine", "Checking the disk space", "Arguing with DNS",
    "Sizing up the file", "Preparing the runway", "Reading the source",
]


def _rotating(pool: list[str], frame: int) -> str:
    return pool[(frame // 3) % len(pool)]


def _effect(ok: bool = True) -> str | None:
    return None  # message effects need a valid id; wired via env if wanted


# ── intro ──────────────────────────────────────────────────────────────────
def welcome(name: str) -> str:
    return t(
        "{rocket} <b>Welcome aboard, " + esc(name) + "!</b>\n\n"
        "I am <b>MirrorX</b> — your personal bridge between the internet and "
        "<b>Google Drive</b>.\n\n"
        "{cloud} <b>Mirror</b> — send me any link, file or video and I upload it to <i>your</i> Drive.\n"
        "{download} <b>Leech</b> — I send the file right back to you on Telegram.\n"
        "{login} <b>Email login</b> — connect your own Google account in ~20 seconds.\n"
        "{shield} <b>Private</b> — your tokens stay encrypted in this bot only.\n\n"
        "{bolt} <i>Just send me a link, or tap a button below.</i>"
    )


def help_text() -> str:
    return t(
        "{help} <b>How to use MirrorX</b>\n\n"
        "{upload} <b>Mirror to Drive</b>\n"
        "Send any of these and I'll push it to Google Drive:\n"
        "  • direct links — <code>https://site.com/file.zip</code>\n"
        "  • YouTube / Instagram / TikTok / X / 1000+ sites\n"
        "  • Google Drive links (server-side clone, no re-upload!)\n"
        "  • a document/photo/video straight into this chat\n\n"
        "{download} <b>Leech to Telegram</b>\n"
        "Same sources, but the finished file comes back to you as a Telegram file.\n\n"
        "{login} <b>Connect Drive</b>\n"
        "<code>/login</code> — email login (OAuth). <code>/logout</code> to disconnect.\n\n"
        "{list} <b>Commands</b>\n"
        "<code>/start</code> menu · <code>/mirror link</code> · <code>/leech link</code>\n"
        "<code>/status</code> running tasks · <code>/files</code> browse Drive\n"
        "<code>/settings</code> · <code>/cancel</code> · <code>/help</code>\n\n"
        "{warn} <b>Limits</b>\n"
        "Leech: up to 50 MB per file on the standard Bot API (2 GB with a local "
        "Bot API server) · Drive: files up to 5 TB.\n\n"
        "{heart} Stuck? Join the support group — buttons are in the menu."
    )


# ── task cards ─────────────────────────────────────────────────────────────
def queued(task) -> str:
    return t(
        f"{spin(0)} <b>Queued</b> {emoji('clock')}\n\n"
        f"{emoji('clip')} <b>Source:</b> <code>{esc(clip(task.display_source, 52))}</code>\n"
        f"{emoji('info')} Waiting for a free slot — <i>{_rotating(QUEUE_LINES, task.frame)}…</i>"
    )


def running(task) -> str:
    s = task.progress.snapshot()
    phase = s["phase"]
    if phase == "uploading":
        head = f"{emoji('upload')} <b>Uploading to Google Drive</b>"
        line = _rotating(UP_LINES, task.frame)
    elif phase == "leeching":
        head = f"{emoji('download')} <b>Sending to Telegram</b>"
        line = _rotating(UP_LINES, task.frame)
    elif phase == "cloning":
        head = f"{emoji('cloud')} <b>Cloning inside Google Drive</b>"
        line = _rotating(UP_LINES, task.frame)
    else:
        head = f"{emoji('download')} <b>Downloading</b>"
        line = _rotating(DL_LINES, task.frame)

    name = esc(clip(s["name"] or task.display_source, 58))
    pct_txt = f"{s['percent']:.1f}%" if s["total"] else "—"
    sizes = f"{human_size(s['done'])} / {human_size(s['total'])}" if s["total"] else human_size(s["done"])

    body = (
        f"{spin(task.frame)} {head}\n"
        f"<code>{name}</code>\n\n"
        f"<code>{bar(s['percent'])}</code> <b>{pct_txt}</b>\n"
        f"{emoji('stats')} {sizes}\n"
        f"{emoji('speed')} {human_size(s['speed'])}/s  {emoji('clock')} ETA {human_time(s['eta'])}\n\n"
        f"{emoji('bolt')} <i>{line}{'.' * (task.frame % 4)}</i>"
    )
    if s["note"]:
        body += f"\n{emoji('info')} <i>{esc(clip(s['note'], 60))}</i>"
    return t(body)


def done(task, link: str = "") -> str:
    s = task.progress.snapshot()
    size = task.size or s["total"] or s["done"]
    dest_line = (
        f"{emoji('cloud')} <b>Google Drive</b>" if task.mode == "mirror"
        else f"{emoji('download')} <b>Telegram</b>"
    )
    body = (
        f"{emoji('check')} <b>Task complete!</b> {emoji('party')}\n\n"
        f"{emoji('doc')} <code>{esc(clip(task.name or s['name'], 58))}</code>\n"
        f"{emoji('stats')} {human_size(size)}  ·  {emoji('clock')} {human_time(task.elapsed)}\n"
        f"{dest_line}\n"
        f"{emoji('bolt')} <b>#{short_id(task.id, 6)}</b>"
    )
    if link:
        body += f"\n{emoji('link')} <a href=\"{esc(link)}\">Open in Google Drive</a>"
    return t(body)


def failed(task, reason: str) -> str:
    return t(
        f"{emoji('cross')} <b>Task failed</b>\n\n"
        f"{emoji('doc')} <code>{esc(clip(task.display_source, 52))}</code>\n"
        f"{emoji('warn')} <b>Reason:</b> <i>{esc(clip(reason, 200))}</i>\n\n"
        f"{emoji('info')} Try again, or drop it in the support group."
    )


def cancelled(task) -> str:
    return t(
        f"{emoji('cross')} <b>Task cancelled</b>\n\n"
        f"{emoji('doc')} <code>{esc(clip(task.display_source, 52))}</code>\n"
        f"{emoji('trash')} Temporary files removed."
    )


# ── drive / login cards ────────────────────────────────────────────────────
def drive_status(connected: bool, email: str = "", mode: str = "", quota: dict | None = None,
                 folder: str = "My Drive") -> str:
    if not connected:
        body = (
            f"{emoji('login')} <b>Google Drive — not connected</b>\n\n"
            f"{emoji('info')} Connect your account to mirror files into <i>your own</i> Drive.\n\n"
            f"{emoji('key')} <b>Email login</b> — tap below, open the Google page, type the code. Done.\n"
        )
        if settings.sa_path:
            body += f"{emoji('shield')} <b>Service account</b> — use the bot's shared Drive instead.\n"
        return t(body)

    who = esc(email or "Service account")
    line = "email login (OAuth)" if mode == "oauth" else "service account"
    q = ""
    if quota:
        try:
            used = float(quota.get("usage") or 0)
            limit = float(quota.get("limit") or 0)
        except (TypeError, ValueError):
            used = limit = 0.0
        if limit:
            q = (f"\n{emoji('stats')} Storage: {human_size(used)} / {human_size(limit)} "
                 f"({used / limit * 100:.1f}%)\n<code>{bar(used / limit * 100)}</code>")
        else:
            q = f"\n{emoji('stats')} Storage: {human_size(used)} used"
    return t(
        f"{emoji('check')} <b>Google Drive connected</b>\n\n"
        f"{emoji('user')} <b>Account:</b> <code>{who}</code>\n"
        f"{emoji('shield')} <b>Mode:</b> {line}\n"
        f"{emoji('folder')} <b>Upload folder:</b> <code>{esc(folder)}</code>" + q
    )


def login_code(user_code: str, url: str, minutes: int) -> str:
    return t(
        f"{emoji('login')} <b>Login with Google</b>\n\n"
        f"<b>1.</b> Tap the button and open Google's page\n"
        f"<b>2.</b> Type this code:\n\n"
        f"<code>{esc(user_code)}</code>\n\n"
        f"<b>3.</b> Approve access to <b>Google Drive</b>\n\n"
        f"{emoji('clock')} The code expires in {minutes} minutes.\n"
        f"{emoji('lock')} <i>I only get the permissions on the consent screen — "
        f"nothing else. Tokens are stored encrypted-at-rest in the bot's database.</i>"
    )


def login_waiting(code: str) -> str:
    return t(
        f"⏳ <b>Waiting for Google…</b>\n\n"
        f"Approve <code>{esc(code)}</code> on Google, then this message updates itself.\n"
        f"{emoji('info')} <i>No need to tap anything else.</i>"
    )


def login_success(email: str) -> str:
    return t(
        f"{emoji('party')} <b>Google Drive connected!</b>\n\n"
        f"{emoji('user')} Signed in as <code>{esc(email)}</code>\n"
        f"{emoji('rocket')} Send me a link and I'll start mirroring."
    )


# ── files ──────────────────────────────────────────────────────────────────
def file_card(meta: dict, idx: int, total: int) -> str:
    mime = meta.get("mimeType", "")
    kind = ("folder" if mime.endswith("folder") else "video" if mime.startswith("video")
            else "audio" if mime.startswith("audio") else "image" if mime.startswith("image")
            else "doc")
    size = meta.get("size")
    return t(
        f"{emoji(kind)} <b>{esc(clip(meta.get('name', '?'), 50))}</b>\n\n"
        f"{emoji('stats')} Size: {human_size(int(size)) if size else '— (folder)'}\n"
        f"{emoji('list')} {idx + 1} / {total}\n"
        f"{emoji('link')} <a href=\"{esc(meta.get('webViewLink', ''))}\">Open in Drive</a>"
    )


# ── settings ───────────────────────────────────────────────────────────────
def settings_card(user: dict) -> str:
    return t(
        f"{emoji('gear')} <b>Your settings</b>\n\n"
        f"{emoji('doc')} Upload format: <b>{'document' if user['as_doc'] else 'media'}</b>\n"
        f"{emoji('image')} Thumbnail for leech: <b>{'on' if user['thumb'] else 'off'}</b>\n"
        f"{emoji('video')} yt-dlp quality: <b>{esc(user['quality'])}</b>\n"
        f"{emoji('folder')} Upload folder: <b>{esc(user['folder_name'])}</b>\n"
        f"{emoji('trash')} Auto-cleanup: <b>{'on' if user['cleanup'] else 'off'}</b>"
    )


# ── status list ────────────────────────────────────────────────────────────
def status_list(tasks: list) -> str:
    if not tasks:
        return t(f"{emoji('info')} <b>No active tasks.</b>\n\n{emoji('rocket')} Send me a link to start!")
    lines = [f"{emoji('list')} <b>Active tasks</b> ({len(tasks)})\n"]
    for i, task in enumerate(tasks, 1):
        s = task.progress.snapshot()
        phase = {"downloading": "downloading", "uploading": "uploading",
                 "leeching": "leeching", "cloning": "cloning"}.get(s["phase"], "queued")
        icon_key = {"downloading": "download", "uploading": "upload",
                    "leeching": "download", "cloning": "cloud", "queued": "clock"}.get(phase, "clock")
        lines.append(
            f"{emoji(icon_key)} <b>{i}.</b> <code>{esc(clip(s['name'] or task.display_source, 32))}</code>\n"
            f"     <code>{bar(s['percent'], 10)}</code> {s['percent']:.0f}% "
            f"· {human_size(s['speed'])}/s · #{short_id(task.id, 4)}"
        )
    return t("\n".join(lines))


def admin_stats(stats: dict, version: str, *, reveal: int | None = None,
                frame: int = 0) -> str:
    """Admin dashboard. `reveal` < total renders a *loading* frame so the panel
    appears line by line (that is the animation you asked for)."""
    up = stats.get("tasks_done", 0)
    started = max(stats.get("tasks_started", 1), 1)
    rate = up / started * 100

    lines = [
        f"{emoji('crown')} <b>Admin dashboard</b>",
        "",
        f"{emoji('user')} <b>Users</b>",
        f"   total <b>{stats.get('users', 0)}</b>  ·  today <b>{stats.get('users_today', 0)}</b>"
        f"  ·  banned <b>{stats.get('banned', 0)}</b>",
        f"   Drive: {stats.get('oauth_users', 0)} email-login · {stats.get('sa_users', 0)} service-account",
        "",
        f"{emoji('rocket')} <b>Tasks</b>",
        f"   started <b>{stats.get('tasks_started', 0)}</b>"
        f"  ·  done <b>{up}</b>"
        f"  ·  failed <b>{stats.get('tasks_failed', 0)}</b>",
        f"   cancelled <b>{stats.get('tasks_cancelled', 0)}</b>"
        f"  ·  today <b>{stats.get('tasks_today', 0)}</b>"
        f"  ·  running <b>{stats.get('queued_now', 0)}</b>",
        "",
        f"{emoji('stats')} <b>Data</b>",
        f"   uploaded <b>{human_size(stats.get('bytes', 0))}</b>",
        f"   today <b>{human_size(stats.get('bytes_today', 0))}</b>",
        f"   success rate <b>{rate:.1f}%</b>  ·  avg <b>{human_time(stats.get('avg_task_seconds', 0))}</b>",
        "",
        f"{emoji('gear')} version <b>{version}</b>"
        f"  ·  emoji <b>{'premium' if emoji.custom else 'fallback'}</b>",
    ]

    if reveal is not None and reveal < len(lines):
        shown = lines[:reveal]
        # pad with the spinner so the card keeps a stable height while loading
        spinner = spin(frame)
        shown = shown + [""] * (len(lines) - reveal)
        shown[reveal] = f"{spinner} <i>loading…</i>"
        out = "\n".join(shown)
        return t(out + "\n\n<code>" + bar(reveal / len(lines) * 100) + "</code>")
    return t("\n".join(lines))


def user_profile(user: dict, ustats: dict) -> str:
    """What a normal user can always see about themselves."""
    last = ustats.get("last_task")
    last_line = (time.strftime("%d %b %Y · %H:%M", time.localtime(last))
                 if last else "no uploads yet")
    return t(
        f"{emoji('user')} <b>Your usage</b>\n\n"
        f"{emoji('check')} Uploads done: <b>{ustats.get('tasks_done', 0)}</b>"
        f" / {ustats.get('tasks_total', 0)} tasks\n"
        f"{emoji('stats')} Total uploaded: <b>{human_size(ustats.get('bytes', 0))}</b>\n"
        f"{emoji('bolt')} Success rate: <b>{ustats.get('success_rate', 0)}%</b>\n"
        f"{emoji('clock')} Last upload: <b>{last_line}</b>\n"
        f"{emoji('folder')} Drive: <b>{esc(user.get('folder_name') or 'My Drive')}</b>\n"
        f"{emoji('shield')} Login: <b>{'connected' if user.get('drive_mode') in ('oauth', 'sa') else 'not connected'}</b>"
    )


def log_channel_status(enabled: bool, detail: str) -> str:
    return t(
        f"{emoji('bell')} <b>Activity log channel</b>\n\n"
        + (f"{emoji('check')} {esc(detail)}\n\n"
           f"{emoji('info')} New users, tasks, Drive logins and admin actions "
           f"are being mirrored there."
           if enabled else
           f"{emoji('warn')} Not active — <code>{esc(detail)}</code>\n\n"
           f"{emoji('info')} Set <code>LOG_CHANNEL_ID</code> in <code>.env</code>, "
           f"then make the bot an <b>admin</b> of that channel."))


def broadcast_started(n: int) -> str:
    return t(f"{emoji('bell')} Broadcasting to <b>{n}</b> users… {emoji('rocket')}")


def emoji_catalogue(entries: list[tuple[str, str, str | None]]) -> str:
    lines = [f"{emoji('star')} <b>Premium emoji catalogue</b>\n",
             f"{emoji('info')} Reply to a premium emoji with "
             f"<code>/grabemoji &lt;key&gt;</code> to add it.\n"]
    for key, ch, eid in entries:
        tag = f'<tg-emoji emoji-id="{eid}">{ch}</tg-emoji>' if eid else ch
        state = f"<code>{eid}</code>" if eid else "<i>fallback</i>"
        lines.append(f"{tag} <code>{key:<12}</code> {state}")
    return t("\n".join(lines))


# ── frame generators (animation loop) ──────────────────────────────────────
def task_frames(task) -> Iterator[str]:
    while True:
        yield running(task)
