# 🐙 Upload this bot to GitHub — 3 ways

Everything here is already GitHub-ready: `.gitignore` blocks secrets,
`.gitattributes` fixes line endings, `.github/` has CI tests, issue templates and
Dependabot, and there's a `LICENSE` (MIT).

**Pick the way that matches how comfortable you are with git.**

| Way | Use when | Keeps commit history |
|---|---|---|
| [1. Browser drag-and-drop](#way-1--browser-drag-and-drop-easiest) | You've never used git | ❌ (one "Initial commit") |
| [2. git command line](#way-2--git-command-line-recommended) | You want proper history + CI badge | ✅ 10 commits |
| [3. Restore the .bundle](#way-3--restore-the-git-bundle-full-history) | You want the exact repo I built | ✅ 10 commits, 1 command |

---

## ⚠️ Before you upload — 3 rules

1. **Never commit `.env`** — it holds your bot token. `.gitignore` already blocks
   it, but don't force-add it.
2. **Never commit `service_account.json`** — also blocked. Same reason.
3. **Assume any secret that reaches GitHub is burned.** If you ever slip, run
   `/revoke` in @BotFather immediately and generate a new token.

> Good news: I scanned the whole repo before packing it. Zero real tokens, zero
> private keys, zero client secrets — only clearly-labelled placeholders like
> `PASTE-YOUR-BOT-TOKEN-HERE`, which GitHub's secret scanner ignores.

---

# Way 1 — Browser drag-and-drop (easiest)

**Best if:** you just want the code online in the next 2 minutes.

### 1. Create the repo
1. Go to <https://github.com/new>
2. **Repository name:** `mirrorx-bot`
3. **Visibility:** Public (or Private — your choice)
4. ⚠️ **Do NOT tick** "Add a README file", "Add .gitignore" or "Choose a license"
   — the zip already has all three, and ticking them causes a merge conflict.
5. **Create repository**

### 2. Upload the files
1. Unzip `mirrorx-bot-github.zip` on your computer → you get a folder `mirrorx-bot`
2. On the empty repo page click **"uploading an existing file"**
   (or go to `https://github.com/YOURNAME/mirrorx-bot/upload/main`)
3. **Open the `mirrorx-bot` folder** → select **everything inside it**
   (Ctrl+A) → drag it all into the browser
   > Drag the *contents*, not the folder itself, or you'll get
   > `mirrorx-bot/mirrorx-bot/bot/…`
4. Wait for all ~51 files to list.
   ⚠️ **Hidden files matter**: `.env.example`, `.gitignore`, `.gitattributes` and
   the whole `.github/` folder are hidden on Windows/macOS. In Windows Explorer:
   **View → Show → Hidden items**. If they don't upload, your repo will miss the
   CI tests and the secret protection. Files starting with a dot have no
   "upload" alternative — see [Way 2](#way-2--git-command-line-recommended)
   if the browser won't take them.
5. Commit message: `Initial commit` → **Commit changes**

### 3. Verify it worked
Open `https://github.com/YOURNAME/mirrorx-bot` — you should see:

- ✅ the README rendered with badges
- ✅ a green **tests** badge (first CI run takes ~3 min; a grey dot means it's running)
- ✅ 51 files, and **no** `.env`

---

# Way 2 — git command line (recommended)

**Best if:** you want the 10-commit history and a working CI badge.
You need git installed (<https://git-scm.com/downloads>).

### 1. Create an empty repo on GitHub
Same as Way 1 step 1 — **no** README, no .gitignore, no license.

### 2. Push from your computer
```bash
cd mirrorx-bot            # the folder you unzipped (it already contains .git)
git remote add origin https://github.com/YOURNAME/mirrorx-bot.git
git branch -M main
git push -u origin main
```

If git asks for a password, use a **Personal Access Token**, not your account
password: GitHub → Settings → Developer settings → Personal access tokens →
Tokens (classic) → Generate new token → tick **repo** → copy it → paste as the
password.

### 3. Fix the badge/links with your own path
The README references `OWNER/REPO` in badge and deploy URLs. Replace it:

```bash
# works on Linux/macOS/Git-Bash; on Windows use Notepad instead
grep -rl "OWNER/REPO" . --exclude-dir=.git | xargs sed -i 's|OWNER/REPO|YOURNAME/mirrorx-bot|g'
git add -A && git commit -m "docs: point badges at this repo" && git push
```

---

# Way 3 — Restore the .git bundle (full history)

**Best if:** you want this exact repository — history, branches and all — in one
command. A bundle is a single-file clone of a git repo.

```bash
git clone mirrorx-bot.bundle mirrorx-bot
cd mirrorx-bot
git remote set-url origin https://github.com/YOURNAME/mirrorx-bot.git
git push -u origin main
```

That's it — 10 commits, branch `main`, clean working tree.

---

# ✅ After the repo is live

### Make the CI badge green
1. Repo → **Actions** tab → if asked, click **"I understand my workflows, go ahead and enable them"**
2. Open the **tests** workflow → **Run workflow** (or just push a commit)
3. It installs the deps and runs all 179 checks: lint → compile → unit → e2e →
   login → command smoke → **2 GiB byte-exact upload**.

✅ You should see a green tick and the badge at the top of the README turns
green. A red X means a step failed — click it; the log names the exact test.

### Turn on secret scanning (free, 10 seconds)
Repo → **Settings** → **Code security** → enable **Secret scanning** and
**Push protection**. Now GitHub refuses a push containing a token.

### Add the repo topics (helps people find it)
Repo → ⚙️ next to "About" → add:
`telegram-bot` `google-drive` `mirror-leech` `aiogram` `python` `yt-dlp` `telegram-premium-emoji`

### Star your own repo ⭐
It's good practice, and it makes the project easier to find later.

---

# 🔧 Common problems

| Problem | Cause | Fix |
|---|---|---|
| `refusing to allow an OAuth App to create... workflow` | token lacks the `workflow` scope | Create the token with **workflow** ticked, or push from the browser |
| `src refspec main does not match any` | you're on `master` | `git branch -M main` then push |
| `remote origin already exists` | leftover remote | `git remote set-url origin <new-url>` |
| `! [rejected] main -> main (fetch first)` | you let GitHub add a README | `git pull --rebase origin main` then push |
| Repo shows `mirrorx-bot/mirrorx-bot/…` | you dragged the folder itself | Move files up one level, or re-do Way 1 step 3 |
| Badge is grey / broken | workflow never ran, or `OWNER/REPO` not replaced | Actions tab → enable → run; then do Way 2 step 3 |
| `.github/` missing after drag-drop | hidden files skipped | Use Way 2 (git adds hidden files automatically) |
| CI fails on `ruff` | you edited code | run `ruff check bot run.py tests --select F,B,E9` locally |
| CI fails on the 2 GiB test | runner out of disk | It's byte-generated + streamed; if it persists, set `LARGE_GB=1` in the workflow |

---

# 📦 What you're uploading (51 files)

```
mirrorx-bot/
├── README.md · SETUP_GUIDE.md · AUDIT.md · RESEARCH.md   ← docs
├── GITHUB_UPLOAD_GUIDE.md                                ← this file
├── LICENSE (MIT) · .gitignore · .gitattributes            ← repo hygiene
├── .github/
│   ├── workflows/tests.yml                               ← CI: 179 checks
│   ├── ISSUE_TEMPLATE/{bug_report.md,config.yml}
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── dependabot.yml                                    ← auto dependency PRs
├── bot/            (24 files — config, drive, services, ui, handlers)
├── tests/          (6 files — 5 suites + run_all.sh)
├── Dockerfile · docker-compose.yml · Procfile · heroku.yml
├── requirements.txt · run.py · .env.example
└── preview.html    (animated UI demo)

data/ aur downloads/ repo me NAHI hain — bot start hote hi khud bana leta hai.
```
