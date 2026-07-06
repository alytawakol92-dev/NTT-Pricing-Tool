# Host the NTT Pricing Tool online (Render)

This puts the tool on the internet at your own web address. After this,
**you never update anything** — when a fix is pushed, the site rebuilds itself
and you just refresh the page.

Everything is already prepared in this repo (`Dockerfile`, `render.yaml`).

## Steps (about 10 minutes, mostly waiting)

1. Go to **<https://render.com>** and **Sign up** — choose **“Sign in with
   GitHub”** and authorise it.
2. Click **New +** → **Blueprint**.
3. Pick the repository **`alytawakol92-dev/NTT-Pricing-Tool`** and the branch
   **`claude/quotation-panel-design-tool-moy141`**. Render reads `render.yaml`
   automatically.
4. It will ask you to fill in **`APP_PASSWORD`** — type a password of your
   choice. This is the password to open the site. Click **Apply**.
5. Render builds the app (the first build takes ~5–10 min because it compiles
   the DWG converter). When it finishes you get a URL like
   **`https://ntt-pricing-tool.onrender.com`**.
6. Open that URL, log in (username can be anything, password = the one you
   set), and use it exactly like the local version — upload the SLD + price
   book, get the offers.

## What you get

- **A private link** — protected by your password, served over **HTTPS**.
- **Auto-updates** — every fix I push rebuilds the site automatically
  (`autoDeploy`). No more downloading or pulling.
- **Auto-delete** — uploaded files and generated offers are erased after
  **2 hours** (change `RUN_RETENTION_MINUTES` in the dashboard).
- **DWG, DXF, PDF and JSON** all work (the DWG converter is built into the
  image).

## Data & privacy

- Files are uploaded over HTTPS and stored **only** in a temporary folder on
  the server while you use them, then auto-deleted. **No database.**
- The site is password-gated, so only people with the password can reach it.
- Want **zero** third-party storage? Deploy the same `Dockerfile` on your own
  company server/VPS instead of Render — identical app, your infrastructure.

## Good to know

- The **free** plan sleeps after ~15 minutes idle; the next visit takes ~1
  minute to wake up. For always-on and more memory, switch the service to a
  paid plan in the dashboard (a few dollars a month).
- If a big price book ever makes it run out of memory on the free plan, set
  **`WEB_CONCURRENCY=1`** in the dashboard’s Environment settings.
- Other hosts (Railway, Fly.io, a VPS) work too — they all use the same
  `Dockerfile`.
