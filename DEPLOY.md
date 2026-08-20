# Deploying Adit

Two pieces, deployed separately: a static frontend, and a backend that needs a
real container with a real disk.

---

## Frontend — Vercel

The console and docs are a static Vite build. Nothing about them needs a
server.

1. Import the repository at [vercel.com/new](https://vercel.com/new)
2. Set **Root Directory** to `frontend`
3. Add one environment variable:

   | Name | Value |
   |---|---|
   | `VITE_API_URL` | `https://<your-backend>.up.railway.app` |

4. Deploy

`frontend/vercel.json` already sets the SPA rewrite, immutable caching for
hashed assets, and the usual hardening headers.

**Two things that will bite you:**

- `VITE_API_URL` is read **at build time**, not at runtime. Changing it means
  redeploying, not just restarting.
- It must be **`https`**. A Vercel page is served over HTTPS, and a browser
  blocks plain-HTTP requests from an HTTPS page as mixed content. The console
  will show "API unreachable" with no obvious cause.

Without a backend the site still works: the console explains exactly which
command starts one, so the landing page and docs are useful on their own.

---

## Backend — Railway (or any container host)

The API clones repositories, runs `npm install`, and talks to HydraDB. That
rules out serverless platforms: a scan takes 40–90 seconds and needs disk, and
Vercel/Netlify functions have neither.

You need **two services in one project**.

### Service 1 — HydraDB

| Setting | Value |
|---|---|
| Source | Docker image `ghcr.io/hydra-db/hydradb:latest` |
| Volume | mount at `/data` |

Environment:

```
CLOUD_PROVIDER=local
LOCAL_PATH=/data/store
GRAPH_NAMESPACE=default
GRAPH_ID=default
GRAPH_CELL_ID=cell-0
GRAPH_CELLS=cell-0
GRAPH_NODE_ID=node-0
GRAPH_BOLT_NODE_ADDRESSES=node-0=0.0.0.0:7687
GRAPH_ADVERTISED_BOLT_ADDR=<this service's private hostname>:7687
GRAPH_DATA_CACHE_DIR=/data/cache
GRAPH_AUTH_TOKEN_FILE=/data/auth-token
GRAPH_ALLOW_PLAINTEXT=true
RUST_MIN_STACK=33554432
```

`GRAPH_ADVERTISED_BOLT_ADDR` is the one people get wrong. It is the address
HydraDB hands back to Bolt clients for follow-up connections. `127.0.0.1` is
correct in `docker compose`, where both containers share a network, and wrong
here — set it to the private hostname the API will dial (on Railway that is
`<service>.railway.internal`).

**The startup directories.** HydraDB does not create its own storage, cache or
auth-token file, and fails outright if they are missing. `docker compose` has
an `init` service for this; a single-container platform does not, so fold it
into the start command:

```sh
sh -c "mkdir -p /data/store /data/cache && \
       [ -f /data/auth-token ] || printf '%s\n' 'change-me-to-a-real-token' > /data/auth-token; \
       exec /usr/local/bin/graph-node"
```

The image already runs as uid `10001`. If `mkdir` fails with a permission
error, the mounted volume is root-owned — set the service to run as root for
one deploy so the directories get created, then remove that.

### Service 2 — the API

| Setting | Value |
|---|---|
| Source | this repository, root directory `.` (uses the root `Dockerfile`) |
| Public networking | enabled |

Environment:

```
ADIT_BOLT_URI=bolt://<hydradb private hostname>:7687
ADIT_BOLT_TOKEN=<the same token you wrote to /data/auth-token>
```

Do **not** set `PORT` by hand — the platform injects it and the API listens on
it automatically, falling back to 8420 locally.

### Check it

```sh
curl https://<your-backend>/health      # {"status":"ok"}
```

If that returns `503 HydraDB unreachable`, the two services are not talking:
check `ADIT_BOLT_URI` and `GRAPH_ADVERTISED_BOLT_ADDR`.

Then put the same URL into Vercel as `VITE_API_URL` and redeploy the frontend.

---

## Sizing and limits

- **Disk.** Each scan clones a repository and installs its dependencies into a
  temp directory, then removes it. `node_modules` for a real project is
  routinely 200–400 MB. Give it a few GB of headroom.
- **Memory.** 1 GB is workable; 512 MB will fail on larger `npm install` runs.
- **Concurrency.** The API caps itself at 4 concurrent scans and sheds the rest
  with `503` + `Retry-After`, so it degrades rather than falling over.
- **Rate limit.** 5 scans per 10 minutes per IP, held in process memory. It is
  per-instance, so running more than one replica multiplies the real limit — a
  shared store would be needed for that, and is not built.
- **Storage grows without bound.** HydraDB has no expiry and nothing deletes
  scan data. For a long-lived deployment, plan to wipe the volume periodically.

## The failure you are most likely to hit

HydraDB's local-filesystem storage backend can start rejecting every write
after sustained use:

```
object store error: Operation `put_opts` with mode `PutMode::Update`
not yet implemented by LocalFileSystem
```

This is an upstream limitation of its dev-mode storage path, not an Adit
defect. Locally the fix is `docker compose down -v && docker compose up -d`. On
a hosting platform it means deleting the volume and redeploying. A production
deployment would point `CLOUD_PROVIDER` at real object storage instead, which
implements the operation this path is missing.
