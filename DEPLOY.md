# How to put Adit on the internet

Follow this top to bottom. Don't skip ahead — step 2 needs a name you copy in
step 1.

You are building three things:

```
   HydraDB  ←──  the API  ←──  the website
  (Railway)      (Railway)      (Vercel)
   database       brain          what people see
```

**Time:** about 45 minutes the first time.
**Cost:** Railway needs a paid plan (you have one). Vercel is free.

---

# PART 1 — The database (Railway)

## 1.1 Make a project

1. Go to **[railway.com](https://railway.com)** and log in
2. Click **New Project**
3. Click **Empty Project**
4. Top-left, rename it to `adit`

## 1.2 Add HydraDB

1. Click **+ Create** → **Docker Image**
2. Paste exactly:

   ```
   ghcr.io/hydra-db/hydradb:latest
   ```

3. Press enter. A box appears — this is your database service.
4. Click it, go to **Settings**, and under **Service Name** type:

   ```
   hydradb
   ```

> **Why the name matters:** you will type `hydradb.railway.internal` later.
> If you name it something else, use that name instead — everywhere.

## 1.3 A disk — optional, and you can skip it

If you can find **Settings → Volumes → Add Volume**, mount one at `/data` and
use `/data/...` paths below.

**If you cannot find Volumes, skip this step.** The settings below store data
inside the container instead. Everything works; you just lose old scan data
whenever the service restarts, which for a demo is fine — every scan writes
its own fresh data anyway.

> **Why the paths below are `/tmp/adit` and not `/data`:** the HydraDB image
> runs as a non-root user (`uid=10001`), and `/` is owned by root. Without a
> volume mounted there, the container cannot create `/data` at all and dies on
> boot with `mkdir: cannot create directory '/data': Permission denied`.
> `/tmp` is world-writable, so it can. Verified by running the image both ways.

## 1.4 Give it its settings

1. Click the **Variables** tab
2. Look for **Raw Editor** (or "Edit as raw") and click it
3. Delete anything in the box, then paste all of this:

```
CLOUD_PROVIDER=local
LOCAL_PATH=/tmp/adit/store
GRAPH_NAMESPACE=default
GRAPH_ID=default
GRAPH_CELL_ID=cell-0
GRAPH_CELLS=cell-0
GRAPH_NODE_ID=node-0
GRAPH_BOLT_NODE_ADDRESSES=node-0=0.0.0.0:7687
GRAPH_ADVERTISED_BOLT_ADDR=hydradb.railway.internal:7687
GRAPH_DATA_CACHE_DIR=/tmp/adit/cache
GRAPH_AUTH_TOKEN_FILE=/tmp/adit/auth-token
GRAPH_ALLOW_PLAINTEXT=true
RUST_MIN_STACK=33554432
ADIT_SHARED_TOKEN=aditRailwayToken2026xKq7Mn4Pw9Rt2Vb5
```

4. Change the token on the last line to your own random text — then **count
   the characters**.
5. Click **Update Variables**

> ### ⚠️ The token must be at least 32 characters
>
> HydraDB refuses to start otherwise, with `graph auth token must contain at
> least 32 non-placeholder characters`. The example above is 36. A
> normal-looking password like `myPassword123` is far too short and the
> service will crash-loop forever.
>
> **📝 Copy your token into a notepad now.** It has to be identical in Part 2.

> **The line people get wrong:** `GRAPH_ADVERTISED_BOLT_ADDR`. This is the
> address HydraDB tells other programs to call it back on. On your laptop
> `127.0.0.1` is right. On Railway it is wrong — the API is a different
> machine, and `127.0.0.1` there means "myself". If this is wrong, everything
> connects and then immediately fails.

## 1.5 Tell it to create its own folders

HydraDB does not create the folders it needs and just crashes if they're
missing. So we create them for it.

1. **Settings** tab → scroll to **Deploy**
2. Find **Custom Start Command**
3. Paste this on one line:

```sh
sh -c "mkdir -p /tmp/adit/store /tmp/adit/cache; printf %s aditRailwayToken2026xKq7Mn4Pw9Rt2Vb5 > /tmp/adit/auth-token; exec /usr/local/bin/graph-node"
```

4. Click **Deploy** (top right)

> ### Why the token is written out in full here
>
> The obvious version uses the variable — `printf '%s\n' "$ADIT_SHARED_TOKEN"`
> — and it fails on Railway. The start-command field parses the string before
> the shell sees it, and the `\n` does not survive: what lands in the token
> file is the token with an extra character on the end. HydraDB then rejects
> every connection with `invalid credentials`, which looks like a networking
> problem and is not.
>
> Writing the token literally, with no `$`, no quotes and no backslash
> escapes, removes every layer that can mangle it. Confirmed by reading the
> file back inside a running container: exactly 36 bytes, no newline.
>
> If you change the token, change it in **three** places: this command,
> `ADIT_SHARED_TOKEN` on hydradb, and `ADIT_BOLT_TOKEN` on the api.

## 1.6 Did it work?

Click the **Deployments** tab and watch the log.

**Good** — the last line says:

```
graph node listeners started
```

**Bad — `mkdir: cannot create directory '/data': Permission denied`**
Your variables still say `/data`. Go back to 1.4 and 1.5 and make every path
`/tmp/adit/...`. The container is not allowed to create folders at the root.

**Bad — `graph auth token must contain at least 32 non-placeholder characters`**
Your token is too short. Make it 32+ characters, in both places.

**Bad — `Permission denied` on `/tmp/adit`**
Rare. Settings → Deploy → turn **Root User** on, deploy once, turn it off.

**Do not continue until this stays running.**

---

# PART 2 — The API (Railway)

Same project. Don't make a new one.

## 2.1 Add it from GitHub

1. Click **+ Create** → **GitHub Repo**
2. Choose **`Jhaycrypt001/adit`**
3. Railway finds your `Dockerfile` and starts building
4. **Settings** → **Service Name** → type:

   ```
   api
   ```

## 2.2 Give it its settings

1. **Variables** tab → **Raw Editor**
2. Paste:

```
ADIT_BOLT_URI=bolt://hydradb.railway.internal:7687
ADIT_BOLT_TOKEN=aditRailwayToken2026xKq7Mn4Pw9Rt2Vb5
```

3. Replace the password with **the exact same text** from step 1.4. Not
   similar — identical.
4. Click **Update Variables**

> **Do NOT add a `PORT` variable.** Railway sets it for you and the API reads
> it automatically. Adding your own will break it.

## 2.3 Give it a public address

1. **Settings** → **Networking**
2. Click **Generate Domain**
3. If it asks for a port, type `8420`
4. Copy the URL — something like `api-production-a1b2.up.railway.app`

**Save that URL. You need it in Part 3.**

## 2.4 Test it

Open this in your browser (your URL, then `/health`):

```
https://YOUR-URL.up.railway.app/health
```

| What you see | What it means |
|---|---|
| `{"status":"ok"}` | 🎉 Working. Go to Part 3. |
| `{"detail":"HydraDB unreachable..."}` | The two services can't talk — see below |
| Page won't load at all | Still building, or no domain. Check **Deployments**. |

**If HydraDB is unreachable, check these three things:**

1. `ADIT_BOLT_URI` says `hydradb.railway.internal` — matching the name from 1.2
2. `ADIT_BOLT_TOKEN` (api) is character-for-character the same as the token
   written by the hydradb start command in 1.5
3. `GRAPH_ADVERTISED_BOLT_ADDR` on hydradb is **not** `127.0.0.1`

---

# PART 3 — The website (Vercel)

## 3.1 Import

1. Go to **[vercel.com/new](https://vercel.com/new)**
2. Import **`Jhaycrypt001/adit`**

## 3.2 The one setting that matters

Find **Root Directory**, click **Edit**, and choose the **`frontend`** folder.

> Get this wrong and the build fails — Vercel would look at the Python project
> at the top of the repo instead of the website.

## 3.3 Point it at your API

Open **Environment Variables** and add:

| Name | Value |
|---|---|
| `VITE_API_URL` | `https://YOUR-URL.up.railway.app` |

Three rules:

- Use the URL from step 2.3
- It must start with **`https`**, not `http`
- **No slash at the end**

> **Why `https` matters:** your Vercel page is secure. Browsers silently block
> insecure requests from a secure page. The site would just say "API
> unreachable" and never tell you why.

## 3.4 Deploy

Click **Deploy** and wait ~2 minutes.

---

# PART 4 — Check the whole thing

Open your Vercel URL and add `#console`:

```
https://your-site.vercel.app/#console
```

**Top right should say `API online` with a green dot.**

Then try a real scan:

1. Click the **`Jhaycrypt001/adit — frontend`** button
2. Click **Scan repository**
3. Wait ~30 seconds
4. You should get **`0 of 0 need action`**

That's Adit, on the internet, scanning its own source code. You're done.

---

# When something breaks

### "API unreachable" on the website

| Check | How |
|---|---|
| Is the API alive? | Open `https://YOUR-URL/health` directly |
| Is `VITE_API_URL` right? | Vercel → Settings → Environment Variables |
| Is it `https`, no trailing slash? | Look carefully |
| Did you redeploy after changing it? | **See the next box** |

### ⚠️ Changing `VITE_API_URL` needs a REDEPLOY

This value is baked in when the site is built. Editing it does nothing on its
own.

**Vercel → Deployments → ⋯ on the newest one → Redeploy**

### "could not install dependencies: no package.json..."

Not a bug. That repo keeps its `package.json` in a subfolder. The error names
the folders it found — click one of the buttons that appears.

### "rate limit: max 5 scans per 10 minutes"

Working as designed, so nobody can hammer your server. Wait, or restart the
`api` service on Railway.

### Writes fail with `PutMode::Update not yet implemented`

A known bug in HydraDB itself, not your code. It happens after lots of writes.

**Fix:** Railway → `hydradb` → Settings → Volumes → delete the volume → add it
back at `/data` → redeploy.

You'll lose old scan data. Nothing else.

---

# Things worth knowing

- **Storage grows forever.** Nothing deletes old scans. Wipe the volume every
  so often (see above).
- **Run one copy of the API only.** The rate limit lives in memory, so two
  copies means double the real limit.
- **1 GB RAM minimum.** 512 MB will fail while installing bigger projects.
- **Scans take 40–90 seconds.** That's normal — it clones a real repository
  and installs real dependencies.
- **This can't go on Vercel.** Vercel kills requests after ~60 seconds and
  gives you no disk. That's why the API lives on Railway.

---

# The short version

| # | Where | Do |
|---|---|---|
| 1 | Railway | Docker image `ghcr.io/hydra-db/hydradb:latest`, name `hydradb`, volume `/data`, paste variables, custom start command |
| 2 | Railway | GitHub repo `Jhaycrypt001/adit`, name `api`, 2 variables, generate domain |
| 3 | — | Open `https://YOUR-API/health` → must say `ok` |
| 4 | Vercel | Import repo, Root Directory `frontend`, add `VITE_API_URL`, deploy |
| 5 | — | Open `your-site.vercel.app/#console` → must say `API online` |
