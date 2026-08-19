# Adit frontend

React + Vite + TypeScript + Tailwind, wired to `adit-api`'s three read/write
endpoints (`POST /scan`, `GET /blast/{pkg}@{version}`, `GET /why`). See
`../ARCHITECTURE.md` for the query model these wrap.

## Dev

```
cp .env.example .env    # set VITE_API_URL if adit-api isn't on localhost:8420
npm install
npm run dev
```

Requires `adit-api` running (`docker compose up -d` from the repo root) and
reachable at `VITE_API_URL`.

## Layout

```
src/lib/types.ts        TS types mirroring render.py::to_json / api.py
src/lib/api.ts           fetch client -- getHealth, scanRepo, getBlastRadius, whyReachable
src/components/          one component per concern, functional but unstyled --
                          this is the layer to restyle
src/App.tsx               tab shell: Scan / Blast Radius / Why Reachable
```

`scan_id` from a successful scan is threaded into the Blast Radius and Why
Reachable tabs automatically, so a follow-up query stays scoped to that same
scan's isolated namespace (see `api.py`'s module docstring on multi-tenant
isolation).

## Known gaps (intentionally left for styling/product decisions, not bugs)

- No loading skeletons beyond button text -- swap in whatever loading
  pattern fits the rest of the design.
- `BlastPanel`/`WhyPanel` don't validate key formats client-side; the API's
  4xx responses are surfaced as-is.
- No router -- tabs are local state. Fine at this scope; revisit if the app
  grows deep-linkable views.
