# FunPlus Zone Auto Check-in (Tiles Survive)

**Language:** English · [简体中文](README.zh-CN.md)

Automated daily tasks for [FunPlus Zone / Tiles Survive](https://zone.funplus.com/tilessurvive/) via GitHub Actions — sign-in rewards, task claims, community browsing, and free member packs.

---

## Beginner guide: Fork & deploy on your GitHub (no coding required)

This section is for users who have **never used GitHub Actions** before. Follow the steps in order.

### What you need

- A **GitHub account** (free is fine)
- A **Windows PC** (recommended) or Mac/Linux
- **Python 3.9+** — download from [python.org](https://www.python.org/downloads/). During install, check **“Add Python to PATH”**.

### Step 1 — Fork this repository

1. Open this repo on GitHub.
2. Click the **Fork** button (top-right).
3. Leave the defaults and confirm. You now have a copy under **your** account, e.g. `https://github.com/YOUR_NAME/Funplus-Check`.

### Step 2 — Enable GitHub Actions

Workflows are often **disabled** on new forks.

1. Open **your fork** → tab **Actions**.
2. If you see a yellow banner, click **“I understand my workflows, go ahead and enable them”**.
3. You should see the workflow **“FunPlus 每日签到”** in the list.

### Step 3 — Export your FunPlus login on your PC

FunPlus uses **email OTP** login. Do **not** put your Gmail password in GitHub. Instead, log in once in a browser on your computer and export a session file.

**Option A — Windows one-click (easiest)**

1. Install [GitHub CLI](https://cli.github.com/) and run `gh auth login` once in a terminal.
2. Clone **your fork** to your PC (GitHub → **Code** → copy HTTPS URL):

   ```bash
   git clone https://github.com/YOUR_NAME/Funplus-Check.git
   cd Funplus-Check
   ```

3. Double-click **`refresh_auth.bat`** in the project folder.
4. A Chromium window opens → log in to FunPlus Zone with your email code.
5. When login succeeds, the script uploads **`FUNPLUS_AUTH`** to **your fork** automatically.

**Option B — Manual (all platforms)**

```bash
git clone https://github.com/YOUR_NAME/Funplus-Check.git
cd Funplus-Check
pip install -r requirements.txt
python -m playwright install chromium
python -u export_auth.py
```

After success, open `.auth/funplus_auth.b64.txt`, **copy the entire file contents** (one long line is normal).

### Step 4 — Add the GitHub Secret

1. On GitHub, open **your fork** → **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret**.
3. Name: `FUNPLUS_AUTH`
4. Value: paste everything from `.auth/funplus_auth.b64.txt` (or the JSON from `.auth/funplus_auth.json`).
5. Click **Add secret**.

> Only **`FUNPLUS_AUTH`** is required. Optional notification via PushPlus is supported but not needed for basic use.

### Step 5 — Run a test

1. Go to **Actions** → **FunPlus 每日签到**.
2. Click **Run workflow** → **Run workflow** again.
3. Wait ~2 minutes, open the run, and check the log for **“FunPlus check-in report”**.
4. If you see **login valid** and sign-in / pack lines, you are done.

### Step 6 — Automatic schedule

No extra setup. The workflow runs daily at **08:20** and **22:20 Beijing time** (UTC cron in the YAML).

When login expires (days or weeks later), run **`refresh_auth.bat`** or **`export_auth.py`** again and update the `FUNPLUS_AUTH` secret.

### Quick troubleshooting

| Problem | What to do |
|---------|------------|
| Actions tab is empty / disabled | Enable workflows (Step 2). |
| “h5-auth not found” / not logged in | Re-export auth and update `FUNPLUS_AUTH`. |
| `refresh_auth.bat` says gh not found | Install GitHub CLI and `gh auth login`, or use Option B + Step 4 manually. |
| Fork has no Secrets menu | You must use **your** fork and have admin access to it. |

---

## What gets automated

1. **Daily sign-in** (`/signinbenefit`) — monthly calendar check-in  
2. **Task center** (`/benefits/pointstask`) — claim completed tasks (e.g. game-zone sign-in)  
3. **Community** — browse 5 posts when logged in, then claim related tasks  
4. **Member packs** (`/benefits/pack`) — daily check for **weekly**, **level**, and other **free** packs (skips if already claimed)

Inspired by [SJS-Check](https://github.com/LiJT/SJS-Check): scheduled GitHub Actions + session secret.

## Can GitHub Actions do this?

**Yes.** Recommended approach:

- Log in once locally in a browser  
- Export cookies / `localStorage` (includes `h5-auth`) via `export_auth.py`  
- Store the export in secret **`FUNPLUS_AUTH`**  
- Each Action run reuses that session  

Re-export and update the secret when it expires. **Do not** store login state in Actions Cache — it is not a secrets store.

**About “31-day sign-in”:** rewards follow a **monthly / active-period calendar** (`checkin/month/info`). After a period ends, a new cycle starts; it is not a one-time lifetime cap.

## Quick start (upstream / local dev)

### 1. Export login locally

**Windows:** double-click `refresh_auth.bat` (updates `FUNPLUS_AUTH` on the linked repo if `gh` is logged in).

**Manual:**

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -u export_auth.py --push-secret
```

Local files (do not commit):

- `.auth/funplus_auth.json`
- `.auth/funplus_auth.b64.txt`

### 2. GitHub Secrets

**Settings** → **Secrets and variables** → **Actions**:

| Secret | Required | Description |
|--------|----------|-------------|
| `FUNPLUS_AUTH` | **Yes** | Full contents of `funplus_auth.b64.txt` or JSON |
| `PUSHPLUS_TOKEN` | No | Optional PushPlus notifications |

Optional:

| Secret / Var | Description |
|--------------|-------------|
| `FUNPLUS_H5_AUTH` | Token only |
| `FUNPLUS_COOKIE` | Cookie string only |
| `FUNPLUS_STORAGE_STATE` | Raw Playwright `storage_state` |
| `FUNPLUS_BASENAME` | Default `/tilessurvive` |
| `FUNPLUS_GAME_PROJECT` | Default `ts_global` |

### 3. Enable Actions

1. **Actions** → enable workflows  
2. **FunPlus 每日签到** → **Run workflow** to test  
3. Default schedule: **08:20** & **22:20** Beijing time (twice daily for reliability)

## Run locally

```bash
# After export_auth.py — .auth/funplus_auth.json should exist
python main.py
```

## Automation coverage

| Page / feature | Behavior |
|----------------|----------|
| Sign-in `signinbenefit` | `checkin/month/info` → `checkin/month` if not signed today |
| Weekly sign-in (if active) | `checkin/week/info` → `checkin/week` |
| Task center | `task/task_list` → `task/get` when `get_times > 0` |
| Browse posts | Playwright opens community article pages, then claims |
| Member packs `benefits/pack` | `GET member_gift/list` + `list_grouped` → `member_gift/receive` (weekly/level packs; daily run, skips claimed) |

“Place 1 store order” only becomes claimable after a **real** purchase; the script only **claims** rewards, it does not spend money or points.

## FAQ

**Q: Actions says not logged in / invalid h5-auth**  
A: Run `export_auth.py` again and update `FUNPLUS_AUTH`.

**Q: Community browse count is 0**  
A: Community is a micro-frontend and may change. Check logs; try `FUNPLUS_HEADED=1 python main.py` locally. Other API tasks still run.

**Q: Is this safe?**  
A: Safer than putting Gmail passwords in GitHub. `FUNPLUS_AUTH` is a session token — use a **private** fork/repo and refresh it periodically.

## Disclaimer

For personal learning and self-use only. Follow FunPlus Terms of Service and event rules; avoid excessive request frequency.
